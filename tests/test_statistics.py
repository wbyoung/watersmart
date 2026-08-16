"""Tests for the WaterSmart long-term-statistics module."""

import datetime as dt
from typing import Self
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.recorder.db_schema import StatisticsMeta
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import get_default_time_zone
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.watersmart.client import UsageRecord
from custom_components.watersmart.const import DOMAIN
from custom_components.watersmart.statistics import (
    ANCHOR_LOOKBACK,
    COLD_START,
    REFOLD_WINDOW,
    Anchor,
    anchor_window,
    bucket_records,
    clear,
    fold_cumulative,
    metadata_for,
    select_anchor,
    statistic_id_for,
)

_STATISTICS = "custom_components.watersmart.statistics"


def test_statistic_id_for_returns_prefixed_entry_id():
    assert statistic_id_for("abc123") == "watersmart:abc123"


def test_statistic_id_for_lowercases_ulid_entry_id():
    # HA config-entry ids are uppercase ULIDs; HA requires statistic_ids to be
    # slugs (lowercase). Lowercasing a Crockford-base32 ULID is lossless.
    assert (
        statistic_id_for("01KS0XG47WMNF3GZYEPDT2A76F")
        == "watersmart:01ks0xg47wmnf3gzyepdt2a76f"
    )


def test_metadata_for_has_expected_shape():
    meta = metadata_for("abc123", "bendoregon")
    assert meta["statistic_id"] == "watersmart:abc123"
    assert meta["source"] == "watersmart"
    assert meta["name"] == "Water consumption (bendoregon)"
    assert meta["unit_of_measurement"] == UnitOfVolume.GALLONS
    assert meta["has_sum"] is True
    assert meta["mean_type"] is StatisticMeanType.NONE


def test_metadata_for_sets_unit_class_where_the_recorder_accepts_it():
    with patch(f"{_STATISTICS}._SUPPORTS_UNIT_CLASS", new=True):
        meta = metadata_for("abc123", "bendoregon")
    assert meta["unit_class"] == "volume"


def test_metadata_for_omits_unit_class_where_the_recorder_lacks_it():
    # Before HA 2025.11.0, `StatisticsMeta(**metadata)` raises TypeError on it.
    with patch(f"{_STATISTICS}._SUPPORTS_UNIT_CLASS", new=False):
        meta = metadata_for("abc123", "bendoregon")
    assert "unit_class" not in meta


def test_metadata_for_is_accepted_by_the_recorder_schema():
    # The import tests mock `async_add_external_statistics`, so nothing else
    # checks the metadata against the recorder. `StatisticsMeta.from_meta`
    # splats it into the ORM model, where an unsupported key is a TypeError.
    # Left unpatched so the version probe is checked against the installed
    # recorder, whichever version that is.
    row = StatisticsMeta.from_meta(metadata_for("abc123", "bendoregon"))
    assert row.statistic_id == "watersmart:abc123"


def _utc(year, month, day, hour):
    """A UTC instant, as the recorder stores and returns them."""
    return dt.datetime(year, month, day, hour, tzinfo=dt.UTC)


def _local(year, month, day, hour):
    """The UTC instant at a given *local* wall-clock hour.

    Buckets are keyed by UTC instants, but the hour a reading belongs to is the
    utility's local hour, so this is what ``bucket_records`` returns.
    """
    return dt.datetime(
        year, month, day, hour, tzinfo=get_default_time_zone()
    ).astimezone(dt.UTC)


def _ts(year, month, day, hour, minute=0):
    """A WaterSmart ``read_datetime``.

    The portal encodes the utility's local wall clock as though it were UTC, so
    the digits passed here are *local* time, not UTC (see
    ``statistics._hour_start_utc``).
    """
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC).timestamp())


def _bucket_start(read_datetime: float) -> dt.datetime:
    """The UTC instant a reading's hour bucket is keyed by.

    ``read_datetime`` carries local wall clock, so the hour is truncated in
    local time and then converted.
    """
    local = dt.datetime.fromtimestamp(read_datetime, tz=dt.UTC).replace(
        tzinfo=get_default_time_zone()
    )
    return local.replace(minute=0, second=0, microsecond=0).astimezone(dt.UTC)


def _record(read_datetime: int, gallons: float | None) -> UsageRecord:
    """Build a usage record; ``leak_gallons``/``flags`` are irrelevant here."""
    return {
        "read_datetime": read_datetime,
        "gallons": gallons,
        "leak_gallons": 0,
        "flags": None,
    }


def _stat_row(start: dt.datetime, **values: float) -> dict[str, float]:
    """A recorder statistics row as HA returns it.

    HA's recorder query API (``get_last_statistics``,
    ``statistics_during_period``) returns ``StatisticsRow`` with ``start`` as a
    float epoch timestamp -- even though the write side takes a ``datetime``.
    Doubles must use that representation or they hide read-side type bugs.
    """
    return {"start": start.timestamp(), **values}


def test_bucket_records_empty_input():
    assert bucket_records([]) == []


def test_bucket_records_simple_pass_through():
    records = [
        _record(_ts(2026, 5, 1, 0), 1.0),
        _record(_ts(2026, 5, 1, 1), 2.0),
    ]
    assert bucket_records(records) == [
        (_local(2026, 5, 1, 0), 1.0),
        (_local(2026, 5, 1, 1), 2.0),
    ]


def test_bucket_records_drops_none_gallons():
    records = [
        _record(_ts(2026, 5, 1, 0), 1.0),
        _record(_ts(2026, 5, 1, 1), None),
        _record(_ts(2026, 5, 1, 2), 3.0),
    ]
    assert bucket_records(records) == [
        (_local(2026, 5, 1, 0), 1.0),
        (_local(2026, 5, 1, 2), 3.0),
    ]


def test_bucket_records_sums_duplicate_hour():
    # Sub-hour timestamp jitter can land two readings in the same hour.
    records = [
        _record(_ts(2026, 5, 1, 0, 0), 1.0),
        _record(_ts(2026, 5, 1, 0, 30), 2.5),
    ]
    assert bucket_records(records) == [(_local(2026, 5, 1, 0), 3.5)]


def test_bucket_records_sorts_chronologically():
    records = [
        _record(_ts(2026, 5, 1, 2), 3.0),
        _record(_ts(2026, 5, 1, 0), 1.0),
        _record(_ts(2026, 5, 1, 1), 2.0),
    ]
    assert bucket_records(records) == [
        (_local(2026, 5, 1, 0), 1.0),
        (_local(2026, 5, 1, 1), 2.0),
        (_local(2026, 5, 1, 2), 3.0),
    ]


def test_bucket_records_reads_timestamps_as_local_wall_clock():
    # The portal's `read_datetime` digits are the utility's local time, so a
    # reading labelled midnight belongs to the UTC hour midnight *local* falls
    # in -- not to 00:00 UTC.
    (start, _gallons) = bucket_records([_record(_ts(2026, 5, 1, 0), 1.0)])[0]
    assert start == _local(2026, 5, 1, 0)
    assert start != _utc(2026, 5, 1, 0)


def test_bucket_records_spans_the_spring_forward_gap():
    # Local time skips 02:00 on a spring-forward, and the portal's series skips
    # it too -- proof the timestamps carry wall clock rather than instants.
    # Reading them as local keeps the buckets an hour apart across the seam.
    records = [
        _record(_ts(2026, 3, 8, 1), 1.0),
        _record(_ts(2026, 3, 8, 3), 2.0),
    ]
    buckets = bucket_records(records)
    assert [start for start, _ in buckets] == [
        _local(2026, 3, 8, 1),
        _local(2026, 3, 8, 3),
    ]
    assert buckets[1][0] - buckets[0][0] == dt.timedelta(hours=1)


def test_bucket_records_folds_the_repeated_fall_back_hour():
    # Fall-back repeats 01:00 local, and the portal emits both readings under
    # the same `read_datetime`. Ambiguous wall clock resolves to the first
    # (fold=0) occurrence, so the pair lands in one bucket rather than being
    # spread across two hours or silently dropped.
    records = [
        _record(_ts(2026, 11, 1, 1), 1.0),
        _record(_ts(2026, 11, 1, 1), 2.0),
    ]
    assert bucket_records(records) == [(_local(2026, 11, 1, 1), 3.0)]


def test_fold_cumulative_empty():
    assert fold_cumulative([], COLD_START) == []


def test_fold_cumulative_from_zero():
    buckets = [
        (_utc(2026, 5, 1, 0), 1.0),
        (_utc(2026, 5, 1, 1), 2.0),
        (_utc(2026, 5, 1, 2), 3.0),
    ]
    rows = fold_cumulative(buckets, COLD_START)
    assert [r["start"] for r in rows] == [b[0] for b in buckets]
    assert [r["sum"] for r in rows] == [1.0, 3.0, 6.0]
    # state is each hour's own gallons (per-period), not the running cumulative.
    assert [r["state"] for r in rows] == [1.0, 2.0, 3.0]


def test_fold_cumulative_continues_from_anchor_sum():
    buckets = [
        (_utc(2026, 5, 1, 3), 1.0),
        (_utc(2026, 5, 1, 4), 2.0),
    ]
    rows = fold_cumulative(buckets, Anchor(start=_utc(2026, 5, 1, 2), sum=100.0))
    assert [r["sum"] for r in rows] == [101.0, 103.0]
    # state is the per-hour gallons; only sum carries the anchor's cumulative.
    assert [r["state"] for r in rows] == [1.0, 2.0]


def test_fold_cumulative_drops_buckets_at_or_before_anchor():
    buckets = [
        (_utc(2026, 5, 1, 1), 1.0),
        (_utc(2026, 5, 1, 2), 2.0),
        (_utc(2026, 5, 1, 3), 3.0),
    ]
    rows = fold_cumulative(buckets, Anchor(start=_utc(2026, 5, 1, 2), sum=10.0))
    assert [r["start"] for r in rows] == [_utc(2026, 5, 1, 3)]
    assert [r["sum"] for r in rows] == [13.0]


def test_anchor_window_spans_lookback_before_the_refold_cutoff():
    last_start = _utc(2026, 5, 10, 0)
    window_start, window_end = anchor_window(_stat_row(last_start))
    cutoff = last_start - REFOLD_WINDOW
    assert window_start == cutoff - ANCHOR_LOOKBACK
    assert window_end == cutoff + dt.timedelta(hours=1)


def test_select_anchor_prefers_latest_window_row():
    latest = _utc(2026, 5, 8, 1)
    window = [
        _stat_row(_utc(2026, 5, 8, 0), sum=100.0),
        _stat_row(latest, sum=110.0),
    ]
    assert select_anchor(window) == Anchor(start=latest, sum=110.0)


def test_select_anchor_cold_starts_when_window_empty():
    # No row in the anchor window (series younger than the refold window, or a
    # recorded gap): re-fold the whole series from zero rather than appending.
    assert select_anchor([]) == COLD_START


@pytest.mark.asyncio
async def test_clear_calls_recorder_with_statistic_id(  # noqa: RUF029
    hass: HomeAssistant,
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "test", "username": "u@example.com", "password": "x"},
        entry_id="entry-id-123",
    )
    mock_recorder = MagicMock()
    with patch(
        "custom_components.watersmart.statistics.get_instance",
        return_value=mock_recorder,
    ):
        clear(hass, entry)

    mock_recorder.async_clear_statistics.assert_called_once_with(
        ["watersmart:entry-id-123"]
    )


class _Recorder:
    """Patches the coordinator's recorder calls for an integration test.

    The recorder isn't set up in tests, so `get_instance` would raise. The
    coordinator dispatches `get_last_statistics` and `statistics_during_period`
    through the executor; this stub runs them inline so the patched callables
    are what actually run. `async_add_external_statistics` is sync (the
    `async_` prefix is HA's "safe-on-event-loop" convention, not "returns a
    coroutine"), so it is a plain `MagicMock`.
    """

    def __init__(
        self,
        *,
        last_statistics: dict | None = None,
        during_period: dict | None = None,
        add_side_effect: Exception | None = None,
        query_side_effect: Exception | None = None,
    ) -> None:
        self.add_external = MagicMock(side_effect=add_side_effect, return_value=None)
        self.get_last = MagicMock(
            side_effect=query_side_effect, return_value=last_statistics or {}
        )
        self.stats_during = MagicMock(return_value=during_period or {})

    @property
    def imported_rows(self) -> list:
        """The rows passed to the most recent recorder write."""
        return list(self.add_external.call_args.args[2])

    def __enter__(self) -> Self:
        inline = MagicMock()
        inline.async_add_executor_job = AsyncMock(
            side_effect=lambda func, *args, **kwargs: func(*args, **kwargs)
        )
        prefix = "custom_components.watersmart.coordinator"
        self._patches = [
            patch(f"{prefix}.get_instance", return_value=inline),
            patch(f"{prefix}.async_add_external_statistics", self.add_external),
            patch(f"{prefix}.get_last_statistics", self.get_last),
            patch(f"{prefix}.statistics_during_period", self.stats_during),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in self._patches:
            p.stop()


def _coordinator(hass: HomeAssistant):
    """Return the coordinator of the single configured WaterSmart entry."""
    return hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator


async def _refresh(hass: HomeAssistant) -> None:
    """Trigger a coordinator refresh and wait for it to settle."""
    await _coordinator(hass).async_refresh()
    await hass.async_block_till_done()


@pytest.fixture
def client_hourly_data_long(mock_watersmart_client):
    """Extend the default fixture to 100 hours so the 48h re-import window has room."""
    hourly = mock_watersmart_client.async_get_hourly_data.return_value
    for _ in range(96):
        last_time = dt.datetime.fromtimestamp(hourly[-1]["read_datetime"], tz=dt.UTC)
        next_time = int((last_time + dt.timedelta(hours=1)).timestamp())
        hourly.append(_record(next_time, 1.0))
    mock_watersmart_client.async_get_hourly_data.return_value = hourly


@pytest.fixture
def warm_anchor(
    hass: HomeAssistant,
    client_hourly_data_long,
    mock_watersmart_client,
    init_integration,
):
    """Recorder state for a warm refresh anchored 48h before the last bucket.

    Extends the client series to 100 hours so the 48h window has room, then
    yields ``(recorder_kwargs, anchor, last_sum)`` where ``anchor`` is the
    ``(start, sum)`` the trailing window folds onto and ``last_sum`` is the
    cumulative sum of the whole series.
    """
    records = mock_watersmart_client.async_get_hourly_data.return_value
    last_start = _bucket_start(records[-1]["read_datetime"])
    last_sum = sum(r["gallons"] for r in records if r["gallons"] is not None)
    anchor_start = last_start - REFOLD_WINDOW
    anchor_sum = sum(
        r["gallons"]
        for r in records
        if r["gallons"] is not None
        and _bucket_start(r["read_datetime"]) <= anchor_start
    )

    statistic_id = statistic_id_for(_coordinator(hass).entry_id)
    recorder_kwargs = {
        "last_statistics": {statistic_id: [_stat_row(last_start, sum=last_sum)]},
        "during_period": {
            statistic_id: [_stat_row(anchor_start, sum=anchor_sum)],
        },
    }
    return recorder_kwargs, (anchor_start, anchor_sum), last_sum


@pytest.mark.asyncio
async def test_cold_start_imports_full_history(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,  # fixture sets up the entry
):
    """On cold start, all hours from the API are imported with monotonic sum."""

    expected_records = mock_watersmart_client.async_get_hourly_data.return_value

    with _Recorder() as recorder:  # empty last_statistics => cold start
        await _refresh(hass)

    recorder.add_external.assert_called_once()
    _hass_arg, metadata, _statistics = recorder.add_external.call_args.args
    assert metadata["source"] == "watersmart"
    rows = recorder.imported_rows
    assert len(rows) == len(expected_records)
    # Monotonic non-decreasing sum starting from the first hour's gallons.
    assert rows[0]["sum"] == expected_records[0]["gallons"]
    expected_total = sum(
        r["gallons"] for r in expected_records if r["gallons"] is not None
    )
    assert rows[-1]["sum"] == pytest.approx(expected_total)


@pytest.mark.asyncio
async def test_warm_path_reimports_last_48h_only(
    hass: HomeAssistant,
    warm_anchor: tuple[dict, tuple[dt.datetime, float], float],
):
    """On a warm refresh, only the last 48h are re-folded against the anchor."""
    recorder_kwargs, (anchor_start, anchor_sum), last_sum = warm_anchor

    with _Recorder(**recorder_kwargs) as recorder:
        await _refresh(hass)

    recorder.add_external.assert_called_once()
    rows = recorder.imported_rows
    assert len(rows) == 48
    assert rows[0]["sum"] == pytest.approx(anchor_sum + 1.0)
    assert rows[-1]["sum"] == pytest.approx(last_sum)

    # The re-import hinges on looking the anchor up over the ±1h-padded window,
    # so assert the span actually passed to statistics_during_period rather
    # than trusting the resulting row count (the mock ignores its time args).
    last_start = anchor_start + REFOLD_WINDOW
    _hass, window_start, window_end, *_ = recorder.stats_during.call_args.args
    assert window_start == last_start - REFOLD_WINDOW - ANCHOR_LOOKBACK
    assert window_end == last_start - REFOLD_WINDOW + dt.timedelta(hours=1)


@pytest.mark.asyncio
@pytest.mark.usefixtures("client_hourly_data_long")
async def test_warm_path_no_new_buckets_does_not_write(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
):
    """If no buckets are newer than the anchor, the recorder isn't called."""

    records = mock_watersmart_client.async_get_hourly_data.return_value
    last_start = _bucket_start(records[-1]["read_datetime"])
    anchor_sum = sum(r["gallons"] for r in records if r["gallons"] is not None)

    statistic_id = statistic_id_for(_coordinator(hass).entry_id)
    with _Recorder(
        last_statistics={statistic_id: [_stat_row(last_start, sum=anchor_sum)]},
        during_period={statistic_id: [_stat_row(last_start, sum=anchor_sum)]},
    ) as recorder:
        await _refresh(hass)

    recorder.add_external.assert_not_called()


@pytest.mark.asyncio
async def test_warm_path_refolds_from_zero_when_anchor_window_empty(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
):
    """A series younger than the refold window has no anchor row to fold onto.

    The warm refresh re-folds the whole series from zero rather than appending
    only newer buckets, so a restated historical hour is still corrected.
    """
    records = mock_watersmart_client.async_get_hourly_data.return_value
    records[1]["gallons"] = 99.0  # a historical hour restated by upstream
    last_start = _bucket_start(records[-1]["read_datetime"])
    restated_start = _bucket_start(records[1]["read_datetime"])

    statistic_id = statistic_id_for(_coordinator(hass).entry_id)
    # A prior row exists, but the anchor window (a refold-window back) is empty.
    with _Recorder(
        last_statistics={statistic_id: [_stat_row(last_start, sum=500.0)]},
        during_period={},
    ) as recorder:
        await _refresh(hass)

    recorder.add_external.assert_called_once()
    rows = recorder.imported_rows
    assert len(rows) == len(records)
    assert rows[0]["sum"] == pytest.approx(records[0]["gallons"])
    restated = next(r for r in rows if r["start"] == restated_start)
    assert restated["sum"] == pytest.approx(records[0]["gallons"] + 99.0)


@pytest.mark.asyncio
async def test_recorder_failure_is_swallowed(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
    caplog,
):
    """A recorder failure inside _insert_statistics must not fail the refresh."""

    # Empty last_statistics => cold start reaches async_add_external_statistics.
    with _Recorder(add_side_effect=RuntimeError("recorder down")):
        await _refresh(hass)

    assert _coordinator(hass).last_update_success is True
    assert "Failed to write statistics" in caplog.text


@pytest.mark.asyncio
async def test_recorder_query_failure_is_swallowed(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
    caplog,
):
    """A failing recorder query must not fail the refresh, nor write rows."""
    with _Recorder(query_side_effect=RuntimeError("recorder down")) as recorder:
        await _refresh(hass)

    assert _coordinator(hass).last_update_success is True
    assert "Failed to read last statistics" in caplog.text
    recorder.add_external.assert_not_called()


@pytest.mark.asyncio
async def test_none_gallons_mid_series_skipped(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
):
    """A None-gallons record mid-series is skipped; surrounding rows import."""
    records = mock_watersmart_client.async_get_hourly_data.return_value
    records[1]["gallons"] = None

    with _Recorder() as recorder:
        await _refresh(hass)

    assert len(recorder.imported_rows) == len(records) - 1


@pytest.mark.asyncio
async def test_empty_hourly_response_no_write(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
):
    """If the API returns an empty list, no recorder write happens."""
    mock_watersmart_client.async_get_hourly_data.return_value = []

    with _Recorder() as recorder:
        await _refresh(hass)

    recorder.add_external.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("client_hourly_data_long")
async def test_restated_historical_hour_within_48h_upserts(
    hass: HomeAssistant,
    mock_watersmart_client,
    init_integration,
):
    """A restated value within the 48h window flows through to the recorder."""
    records = mock_watersmart_client.async_get_hourly_data.return_value
    last_start = _bucket_start(records[-1]["read_datetime"])
    target_ts = int((last_start - dt.timedelta(hours=24)).timestamp())
    for r in records:
        if r["read_datetime"] == target_ts:
            r["gallons"] = 99.0
            break

    anchor_start = last_start - REFOLD_WINDOW

    statistic_id = statistic_id_for(_coordinator(hass).entry_id)
    with _Recorder(
        last_statistics={statistic_id: [_stat_row(last_start, sum=0.0)]},
        during_period={statistic_id: [_stat_row(anchor_start, sum=0.0)]},
    ) as recorder:
        await _refresh(hass)

    recorder.add_external.assert_called_once()
    restated = [
        r
        for r in recorder.imported_rows
        if r["start"] == last_start - dt.timedelta(hours=24)
    ]
    assert len(restated) == 1
