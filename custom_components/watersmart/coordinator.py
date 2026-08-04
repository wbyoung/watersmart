"""The WaterSmart coordinator."""

from asyncio import timeout
from collections.abc import Callable
import datetime as dt
import functools
import logging
from typing import Any, Protocol, TypedDict, cast

from aiohttp.client_exceptions import ClientConnectorError
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.dt import as_local, get_default_time_zone, start_of_local_day

from . import statistics as stats
from .client import AuthenticationError, UsageRecord, WaterSmartClient
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MANUFACTURER, SensorKey
from .types import SensorData

EXCEPTIONS = (AuthenticationError, ClientConnectorError)

_LOGGER = logging.getLogger(__name__)


class _RecorderQueryFailed(Exception):
    """A recorder query raised; the statistics import is abandoned this cycle."""


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
        *,
        entry_id: str,
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
        self.entry_id = entry_id
        self.device_info = _get_device_info(hostname, username)
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
                    "hourly": await self.watersmart.async_get_hourly_data(),
                }
        except EXCEPTIONS as error:
            raise UpdateFailed(error) from error

        for converter in self.data_converters:
            cast("dict[str, SensorData]", result)[converter.converter_key] = converter(
                result
            )

        await self._insert_statistics(result["hourly"])

        _LOGGER.debug("Async update complete")

        return result

    async def _insert_statistics(self, hourly: list[UsageRecord]) -> None:
        """Import the hourly series into HA's long-term statistics.

        Cold start: fold every record against a zero anchor and upsert.

        Warm refresh: re-fold the trailing window onto the most recent anchor
        row so late upstream corrections are absorbed (see :mod:`.statistics`).

        Errors from the recorder are logged and swallowed: a recorder failure
        must not mask the sensor data the refresh succeeded in producing.
        """
        try:
            anchor = await self._resolve_anchor()
            rows = stats.fold_cumulative(stats.bucket_records(hourly), anchor)
            if not rows:
                _LOGGER.debug("No new statistics buckets to import")
                return
            self._write_statistics(rows)
        except _RecorderQueryFailed:
            return

        _LOGGER.debug("Imported %d statistics rows", len(rows))

    async def _resolve_anchor(self) -> stats.Anchor:
        """Resolve the cumulative anchor the trailing window folds onto.

        Returns:
            A cold-start anchor when no prior statistics exist, otherwise the
            warm-refresh anchor selected from the recorder.
        """
        statistic_id = stats.statistic_id_for(self.entry_id)

        # Both queries read back cumulative sums that the next fold accumulates
        # onto, so they must arrive in the unit the series is stored in.
        # `convert_units` and `units` would render them in the display unit
        # instead, silently mixing units into the running total.
        last = await self._recorder_query(
            "read last statistics",
            functools.partial(
                get_last_statistics,
                self.hass,
                1,
                statistic_id,
                convert_units=False,
                types={"sum"},
            ),
        )
        last_rows = last.get(statistic_id, [])
        if not last_rows:
            return stats.COLD_START

        last_row = last_rows[0]
        window_start, window_end = stats.anchor_window(last_row)
        window = await self._recorder_query(
            "look up anchor statistics",
            functools.partial(
                statistics_during_period,
                self.hass,
                window_start,
                window_end,
                statistic_ids={statistic_id},
                period="hour",
                units=None,
                types={"sum"},
            ),
        )
        window_rows = window.get(statistic_id, [])
        if not window_rows:
            _LOGGER.warning(
                "No anchor row in the trailing window for %s despite an "
                "existing series; re-folding the whole history this refresh",
                statistic_id,
            )
        return stats.select_anchor(window_rows)

    async def _recorder_query(
        self,
        description: str,
        query: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Run a recorder query off the event loop, swallowing failures.

        Returns:
            The query result keyed by statistic id.

        Raises:
            _RecorderQueryFailed: If ``query`` raised.
        """
        try:
            result = await get_instance(self.hass).async_add_executor_job(query)
        except Exception as error:
            _LOGGER.warning("Failed to %s", description, exc_info=True)
            raise _RecorderQueryFailed from error
        # async_add_executor_job's stub erases func's return type to Any.
        return cast("dict[str, Any]", result)

    def _write_statistics(self, rows: list[StatisticData]) -> None:
        """Upsert statistic rows.

        Raises:
            _RecorderQueryFailed: If the recorder write failed.
        """
        metadata = stats.metadata_for(self.entry_id, self.hostname)
        try:
            async_add_external_statistics(self.hass, metadata, rows)
        except Exception as error:
            _LOGGER.warning("Failed to write statistics", exc_info=True)
            raise _RecorderQueryFailed from error


def _get_device_info(hostname: str, username: str) -> DeviceInfo:
    """Get device info.

    Returns:
        The device info.
    """
    return DeviceInfo(
        entry_type=DeviceEntryType.SERVICE,
        identifiers={(DOMAIN, f"{hostname}-{username}")},
        manufacturer=MANUFACTURER,
        name=f"WaterSmart ({hostname})",
    )


def _from_timestamp(timestamp: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).astimezone(
        get_default_time_zone()
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
