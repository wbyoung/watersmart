"""WaterSmart long-term-statistics import.

Home Assistant records a consumption series as a running total: each hourly row
carries that hour's own usage in ``state`` and the cumulative total of every
hour up to and including it in ``sum``. WaterSmart reports each hour on its own,
so the hourly values have to be accumulated before the recorder will take them.

Two terms recur below. *Folding* is that accumulation -- turning per-hour
gallons into rows whose ``sum`` is the running total. An *anchor* is the row a
fold resumes from, identified by its hour and the running total reached there.

A cold start folds the whole history from zero. A warm refresh anchors on an
already-recorded hour far enough back to be settled and folds only the hours
after it, so the recent hours WaterSmart still restates are recomputed while
older rows are left alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import datetime as dt
from operator import itemgetter
from typing import Any, cast

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import VolumeConverter

from .client import UsageRecord
from .const import DOMAIN
from .types import WaterSmartConfigEntry

# A warm refresh re-folds the trailing window of buckets so late upstream
# corrections are absorbed without rewriting the whole series.
REFOLD_WINDOW = dt.timedelta(hours=48)
# The anchor lookup spans a 25h window so a bucket landing exactly on the
# cutoff is still found.
ANCHOR_LOOKBACK = dt.timedelta(hours=24)
# ``unit_class`` names the converter the recorder uses to render the series in
# the user's preferred volume unit. The recorder gained the field in HA
# 2025.11.0 and builds its metadata row with ``StatisticsMeta(**metadata)``, so
# an older recorder raises TypeError on the key instead of ignoring it. Probe
# for the field rather than pinning a minimum HA version; delete the probe once
# the supported floor reaches 2025.11.0.
_SUPPORTS_UNIT_CLASS = "unit_class" in StatisticMetaData.__annotations__


def _utc_from_epoch(timestamp: float) -> dt.datetime:
    """Interpret an epoch timestamp as a UTC datetime.

    Both source representations the import consumes -- the client's
    ``read_datetime`` and the recorder's ``StatisticsRow["start"]`` -- carry
    times as epoch seconds; the fold works in UTC datetimes throughout.

    Returns:
        The timestamp as a timezone-aware UTC datetime.
    """
    return dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)


def statistic_id_for(entry_id: str) -> str:
    """Return the external statistic id for this config entry.

    HA config-entry ids are uppercase ULIDs, but HA requires statistic ids to
    be slugs (lowercase). ULIDs are case-insensitive Crockford base32, so
    lowercasing is lossless and keeps the statistic id 1:1 with the entry.
    """
    return f"{DOMAIN}:{entry_id.lower()}"


def metadata_for(entry_id: str, hostname: str) -> StatisticMetaData:
    """Build the external-statistics metadata for this config entry.

    Water usage is an accumulated-quantity statistic: each hour's value is the
    total consumed during that hour. ``has_sum=True``; ``mean_type`` is
    ``StatisticMeanType.NONE`` because there are no underlying instantaneous
    observations to average. ``unit_class`` is set only on recorders that
    accept it (see :data:`_SUPPORTS_UNIT_CLASS`).

    Returns:
        Metadata describing the external-statistics series for the entry.
    """
    # Assembled as a plain mapping because the accepted keys vary by HA version.
    metadata: dict[str, Any] = {
        "mean_type": StatisticMeanType.NONE,
        "has_sum": True,
        "name": f"Water consumption ({hostname})",
        "source": DOMAIN,
        "statistic_id": statistic_id_for(entry_id),
        "unit_of_measurement": UnitOfVolume.GALLONS,
    }
    if _SUPPORTS_UNIT_CLASS:
        metadata["unit_class"] = VolumeConverter.UNIT_CLASS
    return cast("StatisticMetaData", metadata)


def bucket_records(
    records: Iterable[UsageRecord],
) -> list[tuple[dt.datetime, float]]:
    """Group records by UTC hour.

    Drops records with ``gallons is None``; sums multiple records that fall
    within the same UTC hour (sub-hour timestamp jitter in the source data can
    place two readings in one hour); returns the result sorted chronologically.

    Returns:
        ``(hour_start_utc, gallons)`` pairs sorted chronologically.
    """
    buckets: dict[dt.datetime, float] = {}
    for record in records:
        gallons = record["gallons"]
        if gallons is None:
            continue
        start = _utc_from_epoch(record["read_datetime"]).replace(
            minute=0, second=0, microsecond=0
        )
        buckets[start] = buckets.get(start, 0.0) + gallons
    return sorted(buckets.items())


def fold_cumulative(
    buckets: Iterable[tuple[dt.datetime, float]],
    anchor: Anchor,
) -> list[StatisticData]:
    """Fold per-hour gallons after ``anchor`` into cumulative-sum statistic rows.

    Buckets at or before ``anchor.start`` are dropped; the rest accumulate onto
    ``anchor.sum`` to form each row's ``sum``. Each row's ``state`` is that
    hour's own gallons, not the running total: HA's external-statistics
    convention pairs a per-period ``state`` with the cumulative ``sum`` (the
    Energy dashboard reads ``sum``, and the statistics UI derives each period's
    change from consecutive sums while ``state`` records the period value).

    Returns:
        Cumulative-sum statistic rows in chronological order.
    """
    rows: list[StatisticData] = []
    running = anchor.sum
    for start, gallons in buckets:
        if anchor.start is not None and start <= anchor.start:
            continue
        running += gallons
        rows.append(StatisticData(start=start, state=gallons, sum=running))
    return rows


@dataclass(frozen=True)
class Anchor:
    """The cumulative state a fold continues from.

    ``start`` is ``None`` on a cold start, meaning every bucket is folded;
    otherwise only buckets strictly after ``start`` are folded onto ``sum``.
    """

    start: dt.datetime | None
    sum: float


# A cold start (no prior statistics row) folds the whole series from zero.
COLD_START = Anchor(start=None, sum=0.0)


def anchor_window(last_row: Mapping[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    """Return the time span to search for a warm-refresh anchor row.

    The window ends one refold-window before ``last_row`` and reaches back a
    further lookback span so a bucket on the cutoff boundary is still found.

    Returns:
        ``(window_start, window_end)`` for ``statistics_during_period``.
    """
    cutoff = _utc_from_epoch(last_row["start"]) - REFOLD_WINDOW
    return cutoff - ANCHOR_LOOKBACK, cutoff + dt.timedelta(hours=1)


def select_anchor(window_rows: Sequence[Mapping[str, Any]]) -> Anchor:
    """Choose the anchor a warm refresh folds the trailing window onto.

    Anchors on the most recent statistics row inside :func:`anchor_window`. An
    empty window -- a series shorter than the refold window, or a gap in
    recorded statistics there -- has no row to anchor on, so the whole series
    is re-folded from zero. Folding from zero is the correct fallback: a
    partial fold needs an anchor sum paired with the matching anchor start, and
    no row supplies that pair. Anchoring on the last recorded row instead would
    skip every bucket in the trailing window, silently dropping late upstream
    corrections.

    Returns:
        The anchor to fold onto.
    """
    if not window_rows:
        return COLD_START
    row = max(window_rows, key=itemgetter("start"))
    return Anchor(start=_utc_from_epoch(row["start"]), sum=row["sum"] or 0.0)


def clear(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> None:
    """Clear the external statistics series for an entry.

    ``async_clear_statistics`` schedules work on the recorder thread and
    returns immediately, so there is nothing to await.
    """
    get_instance(hass).async_clear_statistics([statistic_id_for(entry.entry_id)])
