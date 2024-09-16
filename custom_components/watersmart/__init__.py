"""The WaterSmart integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .client import WaterSmartClient
from .const import DOMAIN
from .coordinator import WaterSmartUpdateCoordinator
from .services import async_setup_services
from .types import WaterSmartConfigEntry, WaterSmartData

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up WaterSmart services."""

    async_setup_services(hass)

    return True


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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
