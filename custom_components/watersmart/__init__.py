"""The WaterSmart integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import WaterSmartClient
from .coordinator import WaterSmartUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type WaterSmartConfigEntry = ConfigEntry[WaterSmartData]


@dataclass
class WaterSmartData:
    """Runtime data definition."""

    coordinator: WaterSmartUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> bool:
    """Set up WaterSmart from a config entry."""

    hostname: str = entry.data[CONF_HOST]
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    watersmart = WaterSmartClient(hostname, username, password, session=session)

    coordinator = WaterSmartUpdateCoordinator(
        hass,
        watersmart,
        hostname,
        username,
        password,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = WaterSmartData(
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
