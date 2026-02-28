"""Tests for statistics import."""

import datetime as dt
from unittest.mock import AsyncMock, patch

from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.watersmart.const import DOMAIN


@pytest.fixture
def mock_recorder():
    """Mock the recorder instance and statistics helpers."""
    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance"
        ) as mock_get_instance,
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add_stats,
    ):
        recorder = mock_get_instance.return_value
        # Simulate no previously imported statistics (fresh import).
        recorder.async_add_executor_job = AsyncMock(return_value={})
        yield mock_add_stats


@pytest.fixture
def mock_recorder_with_existing(fixture_loader):
    """Mock recorder that reports all current records as already imported."""
    with (
        patch(
            "custom_components.watersmart.coordinator.get_instance"
        ) as mock_get_instance,
        patch(
            "custom_components.watersmart.coordinator.async_add_external_statistics"
        ) as mock_add_stats,
    ):
        recorder = mock_get_instance.return_value
        hourly = fixture_loader.realtime_api_response_obj["data"]["series"]
        last_ts = hourly[-1]["read_datetime"]
        # hostname=test, meter_id=default
        statistic_id = f"{DOMAIN}:test_default_hourly_usage"
        recorder.async_add_executor_job = AsyncMock(
            return_value={
                statistic_id: [
                    {
                        "start": float(last_ts),  # StatisticsRow.start is a float
                        "sum": 999.0,
                    }
                ]
            }
        )
        yield mock_add_stats


@pytest.mark.usefixtures("mock_recorder", "init_integration")
async def test_statistics_imported_on_update(
    hass: HomeAssistant,
    mock_recorder,
    mock_watersmart_client,
    fixture_loader,
):
    """Test that statistics are imported on coordinator update."""
    assert mock_recorder.called

    _hass, metadata, stat_data = mock_recorder.call_args[0]
    hourly = fixture_loader.realtime_api_response_obj["data"]["series"]

    # StatisticMetaData is a TypedDict — use dict-style access
    assert metadata["source"] == DOMAIN
    assert metadata["has_mean"]
    assert metadata["has_sum"]
    assert metadata["unit_of_measurement"] == UnitOfVolume.GALLONS
    assert "hourly_usage" in metadata["statistic_id"]
    assert len(stat_data) == len(hourly)


@pytest.mark.usefixtures("mock_recorder", "init_integration")
async def test_statistics_sum_is_cumulative(
    hass: HomeAssistant,
    mock_recorder,
    fixture_loader,
):
    """Test that the sum field in statistics is a running cumulative total."""
    _hass, _metadata, stat_data = mock_recorder.call_args[0]
    hourly = fixture_loader.realtime_api_response_obj["data"]["series"]

    expected_sum = sum(r["gallons"] or 0 for r in hourly)
    # StatisticData is a TypedDict — use dict-style access
    assert stat_data[-1]["sum"] == pytest.approx(expected_sum)

    # Verify each entry's sum is monotonically non-decreasing
    for i in range(1, len(stat_data)):
        assert stat_data[i]["sum"] >= stat_data[i - 1]["sum"]


@pytest.mark.usefixtures("mock_recorder", "init_integration")
async def test_statistics_mean_matches_hourly_gallons(
    hass: HomeAssistant,
    mock_recorder,
    fixture_loader,
):
    """Test that each statistic's mean equals the hourly gallons value."""
    _hass, _metadata, stat_data = mock_recorder.call_args[0]
    hourly = fixture_loader.realtime_api_response_obj["data"]["series"]

    for stat, record in zip(stat_data, hourly, strict=True):
        assert stat["mean"] == (record["gallons"] or 0)


@pytest.mark.usefixtures("mock_recorder_with_existing", "init_integration")
async def test_statistics_no_duplicate_import(
    hass: HomeAssistant,
    mock_recorder_with_existing,
):
    """Test that no statistics are imported when all records are already present."""
    assert not mock_recorder_with_existing.called


@pytest.mark.usefixtures("mock_recorder", "init_integration")
async def test_statistics_imported_on_subsequent_update(
    hass: HomeAssistant,
    mock_recorder,
):
    """Test that statistics are re-imported on each coordinator poll."""
    initial_call_count = mock_recorder.call_count

    async_fire_time_changed(hass, utcnow() + dt.timedelta(hours=1))
    await hass.async_block_till_done()

    assert mock_recorder.call_count == initial_call_count + 1
