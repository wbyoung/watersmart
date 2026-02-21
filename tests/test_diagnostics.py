"""Test WaterSmart diagnostics."""

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.watersmart.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.usefixtures("init_integration")
async def test_entry_diagnostics(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_watersmart_client,
    snapshot: SnapshotAssertion,
) -> None:
    """Test config entry diagnostics."""
    assert await async_get_config_entry_diagnostics(
        hass, mock_config_entry
    ) == snapshot(exclude=props("entry_id", "created_at", "modified_at"))
