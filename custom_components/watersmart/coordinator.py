"""The WaterSmart coordinator."""

from asyncio import timeout
from collections.abc import Callable
import datetime as dt
import functools
import logging
import re
from typing import Any, Protocol, TypedDict, cast

from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import as_local, get_default_time_zone, start_of_local_day

from .client import AuthenticationError, MeterInfo, UsageRecord, WaterSmartClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MANUFACTURER, SensorKey
from .types import SensorData

EXCEPTIONS = (AuthenticationError, ClientConnectorError)

_LOGGER = logging.getLogger(__name__)


def _to_statistic_slug(value: str) -> str:
    """Convert a string to a valid statistic ID slug.

    Replaces any character not in [a-z0-9] with an underscore, collapses
    consecutive underscores, and strips leading/trailing underscores.

    Args:
        value: The raw string to convert.

    Returns:
        A slug containing only [a-z0-9_], with no leading/trailing/double underscores.
    """
    slug = re.sub(r"[^a-z0-9]", "_", value.lower())
    slug = re.sub(r"_+", "_", slug)
    return slug.strip("_")


class MeterData(TypedDict, total=False):
   
    gallons_for_most_recent_hour: SensorData
    gallons_for_most_recent_full_day: SensorData
    hourly: list[UsageRecord]


type CoordinatorData = dict[str, MeterData]


class _DataConverterT(Protocol):
    converter_key: SensorKey

    def __call__(self, data: MeterData) -> SensorData: ...  # pragma no cover


class WaterSmartUpdateCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Class to manage fetching Watersmart data."""

    data_converters: tuple[_DataConverterT, ...] = ()

    def __init__(
        self,
        hass: HomeAssistant,
        watersmart: WaterSmartClient,
        hostname: str,
        username: str,
        meters: list[MeterInfo],
    ) -> None:
        """Initialize."""

        super().__init__(
            hass,
            _LOGGER,
            name=f"WaterSmart {hostname}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

        self.watersmart = watersmart
        self.hostname = hostname
        self.username = username
        self.meters = meters
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
        result: CoordinatorData = {}

        try:
            async with timeout(30):
                # Fetch data for each meter sequentially, important as we do not want multiple concurrent requests hitting Watersmart.
                for meter in self.meters:
                    meter_id = meter["meter_id"]

                    meter_data: MeterData = {
                        "hourly": await self.watersmart.async_get_hourly_data(
                            meter_id=meter_id if meter_id != "default" else None
                        ),
                    }

                    # Apply data converters for this meter
                    for converter in self.data_converters:
                        cast("dict[str, SensorData]", meter_data)[
                            converter.converter_key
                        ] = converter(meter_data)

                    result[meter_id] = meter_data
                    _LOGGER.debug("Async update complete for meter %s", meter_id)

        except EXCEPTIONS as error:
            raise UpdateFailed(error) from error

        # Import statistics outside the API timeout block so a large initial
        # backfill doesn't race against the 30-second fetch timeout.
        # Errors here are non-fatal — sensor data is still valid without statistics.
        for meter in self.meters:
            if meter["meter_id"] in result:
                try:
                    await self._async_import_statistics(
                        meter, result[meter["meter_id"]]["hourly"]
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to import statistics for meter %s",
                        meter["meter_id"],
                        exc_info=True,
                    )

        return result

    async def _async_import_statistics(
        self,
        meter: MeterInfo,
        records: list[UsageRecord],
    ) -> None:
        """Import hourly usage statistics into HA recorder.

        On first call, imports the full historical record set. On subsequent
        calls, only records newer than the last imported timestamp are added.

        Args:
            meter: The meter whose data is being imported.
            records: All hourly usage records returned by the API.
        """
        try:
            recorder_instance = get_instance(self.hass)
        except (HomeAssistantError, KeyError):
            _LOGGER.debug(
                "Recorder not available, skipping statistics import for meter %s",
                meter["meter_id"],
            )
            return

        meter_id = meter["meter_id"]
        statistic_id = (
            f"{DOMAIN}:"
            f"{_to_statistic_slug(self.hostname)}_"
            f"{_to_statistic_slug(meter_id)}_hourly_usage"
        )

        # Find the last imported record so we only push new data.
        last_stats = await recorder_instance.async_add_executor_job(
            functools.partial(
                get_last_statistics, self.hass, 1, statistic_id, False, {"sum"}
            )
        )

        last_timestamp: float | None = None
        running_sum: float = 0.0

        if last_stats and statistic_id in last_stats:
            last_stat = last_stats[statistic_id][0]
            last_timestamp = last_stat["start"]  # already a Unix float timestamp
            running_sum = last_stat.get("sum") or 0.0

        new_records = [
            r for r in records
            if last_timestamp is None or r["read_datetime"] > last_timestamp
        ]

        if not new_records:
            return

        _LOGGER.debug(
            "Importing %d new statistics records for meter %s",
            len(new_records),
            meter_id,
        )

        stat_data: list[StatisticData] = []
        for record in new_records:
            gallons = _record_gallons(record)
            running_sum += gallons
            start = dt.datetime.fromtimestamp(record["read_datetime"], tz=dt.UTC)
            stat_data.append(
                StatisticData(
                    start=start,
                    mean=gallons,
                    sum=running_sum,
                )
            )

        metadata = StatisticMetaData(
            has_mean=True,
            has_sum=True,
            name=f"WaterSmart {meter['name']} Hourly Usage",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfVolume.GALLONS,
        )

        async_add_external_statistics(self.hass, metadata, stat_data)


def _get_device_info(
    hostname: str, username: str, meter_id: str = "default", meter_name: str = ""
) -> DeviceInfo:
    """Get device info.

    Returns:
        The device info.
    """
    display_name = meter_name or hostname
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
        func: Callable[[MeterData], SensorData],
    ) -> None:
        super().__init__()
        self.converter_key = key
        self.func = func

    def __call__(self, data: MeterData) -> SensorData:
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
def _sensor_data_for_most_recent_hour(data: MeterData) -> SensorData:
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
def _sensor_data_for_most_recent_full_day(data: MeterData) -> SensorData:
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


def _records_from_first_full_day(data: MeterData) -> list[UsageRecord]:
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
