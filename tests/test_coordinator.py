"""Test the WaterSmart update coordinator."""

import datetime as dt
import functools
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.recorder.statistics import (
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.loader import DATA_CUSTOM_COMPONENTS
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.watersmart.const import DOMAIN
from custom_components.watersmart.coordinator import _to_statistic_slug  # noqa: PLC2701

STATISTIC_ID = f"{DOMAIN}:test_hourly_usage"

# Timestamps and gallons from realtime_api_response.json
_T1, _T2, _T3, _T4 = 1718823600, 1718827200, 1718830800, 1718834400
#   gallons:  7.48       0          7.48       0


@pytest.mark.parametrize(
    ("hostname", "expected_slug"),
    [
        ("test", "test"),                             # baseline used throughout tests
        ("mywater.smart.com", "mywater_smart_com"),   # dots → underscores
        ("MY-UTILITY.COM", "my_utility_com"),         # uppercase lowercased, hyphens → underscores
        ("double--dash", "double_dash"),              # consecutive specials collapsed
        ("-leading-trailing-", "leading_trailing"),   # leading/trailing underscores stripped
        ("123abc", "123abc"),                         # leading digits are valid
    ],
)
def test_to_statistic_slug(hostname: str, expected_slug: str) -> None:
    """_to_statistic_slug produces a stable, valid slug for real-world hostnames.

    The slug is embedded in the permanent statistic ID stored in the HA recorder;
    an incorrect mapping would orphan historical water-usage data under the wrong key.
    """
    assert _to_statistic_slug(hostname) == expected_slug


# Override the conftest autouse fixture so it does not force `hass` to be
# created before recorder fixtures (which must run first).  Custom-integration
# enablement is handled manually inside _init instead.
@pytest.fixture(autouse=True)
def auto_enable_custom_integrations():
    """No-op override - custom integrations are enabled inside _init."""


async def _init(hass, mock_config_entry):
    """Set up the WaterSmart integration (mirrors the init_integration fixture)."""
    hass.data.pop(DATA_CUSTOM_COMPONENTS, None)  # enable custom integrations
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_statistics_full_backfill(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """All records are imported and summed correctly on first run."""
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value={})

    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        await _init(hass, mock_config_entry)

        assert mock_add.call_count == 1
        _, metadata, stat_data = mock_add.call_args.args

        assert metadata["statistic_id"] == STATISTIC_ID
        assert metadata["has_sum"] is True

        assert len(stat_data) == 4

        assert stat_data[0]["start"] == dt.datetime(2024, 6, 19, 19, 0, tzinfo=dt.UTC)
        assert stat_data[0]["mean"] == pytest.approx(7.48)
        assert stat_data[0]["sum"] == pytest.approx(7.48)

        assert stat_data[1]["start"] == dt.datetime(2024, 6, 19, 20, 0, tzinfo=dt.UTC)
        assert stat_data[1]["mean"] == 0
        assert stat_data[1]["sum"] == pytest.approx(7.48)

        assert stat_data[2]["start"] == dt.datetime(2024, 6, 19, 21, 0, tzinfo=dt.UTC)
        assert stat_data[2]["mean"] == pytest.approx(7.48)
        assert stat_data[2]["sum"] == pytest.approx(14.96)

        assert stat_data[3]["start"] == dt.datetime(2024, 6, 19, 22, 0, tzinfo=dt.UTC)
        assert stat_data[3]["mean"] == 0
        assert stat_data[3]["sum"] == pytest.approx(14.96)

        total_sensor = hass.states.get(
            "sensor.watersmart_test_total_hourly_usage"
        )
        assert total_sensor.state not in {"unknown", "unavailable"}


async def test_statistics_incremental_import(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """Only records newer than the last stored statistic are imported."""
    last_stats = {STATISTIC_ID: [{"start": float(_T2), "sum": 7.48}]}

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value=last_stats)

    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        await _init(hass, mock_config_entry)

        assert mock_add.call_count == 1
        _, _metadata, stat_data = mock_add.call_args.args

        # Only records 3 and 4 (timestamps > _T2) should be imported.
        assert len(stat_data) == 2

        assert stat_data[0]["start"] == dt.datetime(2024, 6, 19, 21, 0, tzinfo=dt.UTC)
        assert stat_data[0]["mean"] == pytest.approx(7.48)
        assert stat_data[0]["sum"] == pytest.approx(14.96)  # prior 7.48 + 7.48

        assert stat_data[1]["start"] == dt.datetime(2024, 6, 19, 22, 0, tzinfo=dt.UTC)
        assert stat_data[1]["mean"] == 0
        assert stat_data[1]["sum"] == pytest.approx(14.96)


async def test_statistics_no_new_records(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """No statistics are pushed when all records are already stored."""
    last_stats = {STATISTIC_ID: [{"start": float(_T4), "sum": 14.96}]}

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value=last_stats)

    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        await _init(hass, mock_config_entry)

        mock_add.assert_not_called()


async def test_statistics_zero_prior_sum_preserved(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """A prior sum of 0.0 is not treated as falsy when resuming the running total."""
    last_stats = {STATISTIC_ID: [{"start": float(_T2), "sum": 0.0}]}

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(return_value=last_stats)

    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        await _init(hass, mock_config_entry)

        _, _metadata, stat_data = mock_add.call_args.args

        # Records 3 and 4 imported; running sum starts from 0.0, not a fallback default.
        assert len(stat_data) == 2
        assert stat_data[0]["sum"] == pytest.approx(7.48)   # 0.0 + 7.48
        assert stat_data[1]["sum"] == pytest.approx(7.48)   # + 0


@pytest.mark.parametrize("error", [HomeAssistantError, KeyError])
async def test_statistics_recorder_unavailable(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
    error,
):
    """Statistics import is silently skipped when the recorder is unavailable."""
    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance",
            side_effect=error,
        ),
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add,
    ):
        await _init(hass, mock_config_entry)

        mock_add.assert_not_called()

        # Non-statistics sensors must still be functional even without the recorder.
        recent_hour = hass.states.get(
            "sensor.watersmart_test_gallons_for_most_recent_hour"
        )
        assert recent_hour is not None
        assert recent_hour.state not in {"unknown", "unavailable"}

        total_sensor = hass.states.get(
            "sensor.watersmart_test_total_hourly_usage"
        )
        assert total_sensor.state == "unknown"


async def test_statistics_recorder_contains_historical_data(
    recorder_mock,
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """On first setup, the HA recorder contains statistic ID watersmart:<hostname>_hourly_usage.

    Historical data goes back to the earliest available API record.
    """
    await _init(hass, mock_config_entry)
    await async_wait_recording_done(hass)

    # Verify the statistic ID exists and the final running sum is correct.
    last = await recorder_mock.async_add_executor_job(
        functools.partial(
            get_last_statistics, hass, 1, STATISTIC_ID, convert_units=False, types={"sum"}
        )
    )
    assert STATISTIC_ID in last
    assert last[STATISTIC_ID][0]["sum"] == pytest.approx(14.96)  # 7.48 + 0 + 7.48 + 0

    # Verify all historical records were written, starting from the earliest.
    all_stats = await recorder_mock.async_add_executor_job(
        functools.partial(
            statistics_during_period,
            hass,
            dt.datetime(2024, 6, 19, 0, 0, tzinfo=dt.UTC),
            None,
            {STATISTIC_ID},
            "hour",
            None,
            {"sum"},
        )
    )
    assert STATISTIC_ID in all_stats
    rows = all_stats[STATISTIC_ID]
    assert len(rows) == 4
    assert float(rows[0]["start"]) == pytest.approx(float(_T1))  # earliest record


async def test_total_usage_sensor_selectable_in_energy_dashboard(
    recorder_mock,
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """The total_hourly_usage sensor must have a valid state and the correct attributes.

    Ensures it appears as a selectable entity (not 'entity without state') in the
    Energy Dashboard -> Water consumption configuration panel.
    """
    await _init(hass, mock_config_entry)
    await async_wait_recording_done(hass)

    sensor = hass.states.get("sensor.watersmart_test_total_hourly_usage")
    assert sensor is not None
    # A state of "unknown" or "unavailable" causes the Energy Dashboard to show
    # the entity as "entity without state" rather than as a usable data source.
    assert sensor.state not in {"unknown", "unavailable"}
    # These two attributes determine eligibility in the Energy Dashboard water picker.
    assert sensor.attributes["device_class"] == "water"
    assert sensor.attributes["state_class"] == "total_increasing"


async def test_statistics_incremental_append_to_recorder(
    recorder_mock,
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """On subsequent refreshes, only new records are appended to the recorder."""
    t5 = _T4 + 3600  # one hour after the last fixture record

    # First refresh: import the initial 4 records.
    await _init(hass, mock_config_entry)
    await async_wait_recording_done(hass)

    # Simulate a new API record appearing since the last refresh.
    original_data = mock_watersmart_client.async_get_hourly_data.return_value
    new_record = {"read_datetime": t5, "gallons": 5.0, "flags": None, "leak_gallons": 0}
    mock_watersmart_client.async_get_hourly_data.return_value = [*original_data, new_record]

    # Trigger a second coordinator refresh.
    coordinator = hass.data[DOMAIN][mock_config_entry.entry_id].coordinator
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)

    # Only the new record is appended: 5 rows total, not 4+5=9 from a full re-import.
    all_stats = await recorder_mock.async_add_executor_job(
        functools.partial(
            statistics_during_period,
            hass,
            dt.datetime(2024, 6, 19, 0, 0, tzinfo=dt.UTC),
            None,
            {STATISTIC_ID},
            "hour",
            None,
            {"sum"},
        )
    )
    assert STATISTIC_ID in all_stats
    rows = all_stats[STATISTIC_ID]
    assert len(rows) == 5  # 4 original + 1 new

    # The final running sum should be 14.96 + 5.0 = 19.96.
    last = await recorder_mock.async_add_executor_job(
        functools.partial(
            get_last_statistics, hass, 1, STATISTIC_ID, convert_units=False, types={"sum"}
        )
    )
    assert last[STATISTIC_ID][0]["sum"] == pytest.approx(19.96)


async def test_statistics_import_failure_is_nonfatal(
    hass: HomeAssistant,
    mock_config_entry,
    mock_sensor_name,
    mock_watersmart_client,
):
    """A failure during statistics import does not prevent other sensors from loading."""
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(
        side_effect=RuntimeError("db error")
    )

    with patch(
        "custom_components.watersmart.coordinator.get_instance",
        return_value=mock_recorder,
    ):
        await _init(hass, mock_config_entry)

        recent_hour = hass.states.get(
            "sensor.watersmart_test_gallons_for_most_recent_hour"
        )
        assert recent_hour is not None
        assert recent_hour.state not in {"unknown", "unavailable"}

        total_sensor = hass.states.get(
            "sensor.watersmart_test_total_hourly_usage"
        )
        assert total_sensor.state == "unknown"
