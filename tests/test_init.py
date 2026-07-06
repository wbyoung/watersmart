"""Test component setup."""

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest

from custom_components.watersmart.const import DOMAIN
from custom_components.watersmart.statistics import statistic_id_for


async def test_async_setup(hass: HomeAssistant):
    """Test the component gets setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True


@pytest.mark.asyncio
async def test_remove_entry_clears_statistics(hass: HomeAssistant, init_integration):
    """Removing the config entry clears the external statistics series."""
    entry = init_integration

    mock_recorder = MagicMock()
    with patch(
        "custom_components.watersmart.statistics.get_instance",
        return_value=mock_recorder,
    ):
        await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()

    mock_recorder.async_clear_statistics.assert_called_once_with(
        [statistic_id_for(entry.entry_id)]
    )
