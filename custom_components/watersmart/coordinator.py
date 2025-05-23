"""The WaterSmart coordinator."""

from asyncio import timeout
import datetime as dt
import functools
import logging
from typing import Any, Callable, Protocol, cast

from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import as_local, get_default_time_zone, start_of_local_day

from .client import AuthenticationError, WaterSmartClient
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY,
    GALLONS_FOR_MOST_RECENT_HOUR,
    MANUFACTURER,
)

EXCEPTIONS = (AuthenticationError, ClientConnectorError)

_LOGGER = logging.getLogger(__name__)


class _DataConverterT(Protocol):
    converter_key: str

    def __call__(self, data: dict[str, Any]) -> dict[str, Any]: ...  # pragma no cover


class WaterSmartUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching AccuWeather data API."""

    data_converters: tuple[_DataConverterT, ...] = ()

    def __init__(
        self,
        hass: HomeAssistant,
        watersmart: WaterSmartClient,
        hostname: str,
        username: str,
        password: str,
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
        self.device_info = _get_device_info(hostname, username)
        self.data_converters = (
            _sensor_data_for_most_recent_hour,
            _sensor_data_for_most_recent_full_day,
        )

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Update data via library."""
        try:
            async with timeout(30):
                result = {
                    "hourly": await self.watersmart.async_get_hourly_data(),
                }
        except EXCEPTIONS as error:
            raise UpdateFailed(error) from error

        for converter in self.data_converters:
            result[converter.converter_key] = converter(result)

        _LOGGER.debug("Async update complete")

        return result


def _get_device_info(hostname: str, username: str) -> DeviceInfo:
    """Get device info."""
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, f"{hostname}-{username}")},
        manufacturer=MANUFACTURER,
        name=f"WaterSmart ({hostname})",
    )


def _from_timestamp(timestamp: int):
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).replace(
        tzinfo=get_default_time_zone()
    )


class _DataConverter:
    def __init__(self, key: str, func: Callable[[dict[str, Any]], dict[str, Any]]):
        super().__init__()
        self.converter_key = key
        self.func = func

    def __call__(self, data):
        return self.func(data)


def _data_converter(key: str):
    """Annotate and add a converter key to data converters."""

    def wrapper(func) -> _DataConverterT:
        return cast(_DataConverter, functools.wraps(func)(_DataConverter(key, func)))

    return wrapper


@_data_converter(GALLONS_FOR_MOST_RECENT_HOUR)
def _sensor_data_for_most_recent_hour(data: dict[str, Any]) -> dict[str, Any]:
    """Extract data for most recent hour."""

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


@_data_converter(GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY)
def _sensor_data_for_most_recent_full_day(data: dict[str, Any]) -> dict[str, Any]:
    """Extract data for first full day."""

    records = _records_from_first_full_day(data)
    gallons = sum([_record_gallons(r) for r in records])

    return {
        "state": gallons,
        "attrs": {
            "related": _serialize_records(records),
        },
    }


def _records_from_first_full_day(data):
    """Extract records for first full day."""

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


def _record_gallons(record: dict[str, Any]):
    """Get record gallons guarded to ensure it's a number."""

    result = record["gallons"]
    if result is None:
        result = 0
    return result


def _serialize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert records for returning in attributes & service calls."""

    return [
        {
            "start": as_local(_from_timestamp(record["read_datetime"])).isoformat(),
            "gallons": _record_gallons(record),
        }
        for record in records
    ]
