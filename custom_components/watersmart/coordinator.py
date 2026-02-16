"""The WaterSmart coordinator."""

from asyncio import timeout
from collections.abc import Callable
import datetime as dt
import functools
import logging
from typing import Any, Protocol, TypedDict, cast

from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import as_local, get_default_time_zone, start_of_local_day

from .client import AuthenticationError, UsageRecord, WaterSmartClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MANUFACTURER, SensorKey
from .types import SensorData

EXCEPTIONS = (AuthenticationError, ClientConnectorError)

_LOGGER = logging.getLogger(__name__)


class CoordinatorData(TypedDict, total=False):
    """Shape of coordinator data."""

    gallons_for_most_recent_hour: SensorData
    gallons_for_most_recent_full_day: SensorData
    hourly: list[UsageRecord]


class _DataConverterT(Protocol):
    converter_key: SensorKey

    def __call__(self, data: CoordinatorData) -> SensorData: ...  # pragma no cover


class WaterSmartUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Class to manage fetching Watersmart data."""

    data_converters: tuple[_DataConverterT, ...] = ()

    def __init__(
        self,
        hass: HomeAssistant,
        watersmart: WaterSmartClient,
        hostname: str,
        username: str,
        meter_id: str = "default",
        meter_name: str = "",
    ) -> None:
        """Initialize."""

        display_name = meter_name if meter_name else hostname
        super().__init__(
            hass,
            _LOGGER,
            name=f"WaterSmart {display_name}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

        self.watersmart = watersmart
        self.hostname = hostname
        self.username = username
        self.meter_id = meter_id
        self.meter_name = meter_name
        self.device_info = _get_device_info(hostname, username, meter_id, meter_name)
        self.data: CoordinatorData = {}
        self.data_converters = (
            _sensor_data_for_most_recent_hour,
            _sensor_data_for_most_recent_full_day,
        )

    async def _async_update_data(self) -> CoordinatorData:
        """Update data via library.

        Returns:
            The updated data.

        Raises:
            UpdateFailed: If there is an error that could typically occur.
        """
        try:
            async with timeout(30):
                result: CoordinatorData = {
                    "hourly": await self.watersmart.async_get_hourly_data(
                        meter_id=self.meter_id if self.meter_id != "default" else None
                    ),
                }
        except EXCEPTIONS as error:
            raise UpdateFailed(error) from error

        for converter in self.data_converters:
            cast("dict[str, SensorData]", result)[converter.converter_key] = converter(
                result
            )

        _LOGGER.debug("Async update complete for meter %s", self.meter_id)

        return result


def _get_device_info(
    hostname: str, username: str, meter_id: str = "default", meter_name: str = ""
) -> DeviceInfo:
    """Get device info.

    Returns:
        The device info.
    """
    display_name = meter_name if meter_name else hostname
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, f"{hostname}-{username}-{meter_id}")},
        manufacturer=MANUFACTURER,
        name=f"WaterSmart ({display_name})",
    )


def _from_timestamp(timestamp: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).replace(
        tzinfo=get_default_time_zone()
    )


class _DataConverter:
    def __init__(
        self,
        key: SensorKey,
        func: Callable[[CoordinatorData], SensorData],
    ) -> None:
        super().__init__()
        self.converter_key = key
        self.func = func

    def __call__(self, data: CoordinatorData) -> SensorData:
        return self.func(data)


def _data_converter[F: Callable[..., Any]](
    key: SensorKey,
) -> Callable[[F], _DataConverterT]:
    """Annotate and add a converter key to data converters.

    Returns:
        A decorator.
    """

    def wrapper(func: F) -> _DataConverterT:
        return cast(
            "_DataConverter",
            functools.wraps(func)(_DataConverter(key, func)),
        )

    return wrapper


@_data_converter(SensorKey.GALLONS_FOR_MOST_RECENT_HOUR)
def _sensor_data_for_most_recent_hour(data: CoordinatorData) -> SensorData:
    """Extract data for most recent hour.

    Returns:
        The extracted & converted records.
    """

    records = data["hourly"][-24:]
    record = records[-1]
    record_date = as_local(_from_timestamp(record["read_datetime"]))

    return {
        "state": _record_gallons(record),
        "attrs": {
            "start": record_date.isoformat(),
            "related": _serialize_records(records),
        },
    }


@_data_converter(SensorKey.GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY)
def _sensor_data_for_most_recent_full_day(data: CoordinatorData) -> SensorData:
    """Extract data for first full day.

    Returns:
        The extracted & converted records.
    """

    records = _records_from_first_full_day(data)
    gallons = sum(_record_gallons(r) for r in records)

    return {
        "state": gallons,
        "attrs": {
            "related": _serialize_records(records),
        },
    }


def _records_from_first_full_day(data: CoordinatorData) -> list[UsageRecord]:
    """Extract records for first full day.

    Returns:
        The extracted records.
    """

    full_day_records = []
    last_full_day = None

    for record in reversed(data["hourly"]):
        record_date = as_local(_from_timestamp(record["read_datetime"]))
        start_of_day = start_of_local_day(record_date)

        if last_full_day and start_of_day < last_full_day:
            break

        if last_full_day and start_of_day == last_full_day:
            full_day_records.append(record)
        elif (
            not last_full_day
            and (record_date - start_of_day).total_seconds() // 3600 >= 23
        ):
            full_day_records.append(record)
            last_full_day = start_of_day

    return list(reversed(full_day_records))


def _record_gallons(record: UsageRecord) -> float | int:
    """Get record gallons guarded to ensure it's a number.

    Returns:
        The gallons or zero if it was not available.
    """

    result = record["gallons"]
    if result is None:
        result = 0
    return result


def _serialize_records(records: list[UsageRecord]) -> list[dict[str, Any]]:
    """Convert records for returning in attributes & service calls.

    Returns:
        The serialized records.
    """

    return [
        {
            "start": as_local(_from_timestamp(record["read_datetime"])).isoformat(),
            "gallons": _record_gallons(record),
        }
        for record in records
    ]
