"""The WaterSmart integration."""

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .client import WaterSmartClient
from .const import DOMAIN
from .coordinator import WaterSmartUpdateCoordinator
from .services import async_setup_services
from .types import WaterSmartConfigEntry, WaterSmartData

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(  # noqa: RUF029
    hass: HomeAssistant,
    config: ConfigType,  # noqa: ARG001
) -> bool:
    """Set up WaterSmart services.

    Returns:
        If the setup was successful.
    """

    async_setup_services(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> bool:
    """Set up WaterSmart from a config entry.

    Returns:
        If the setup was successful.
    """

    hostname: str = entry.data[CONF_HOST]
    username: str = entry.data[CONF_USERNAME]
    password: str = entry.data[CONF_PASSWORD]

    session = async_get_clientsession(hass)
    watersmart = WaterSmartClient(hostname, username, password, session=session)

    # Get available meters by authenticating first
    available_meters = await watersmart.async_get_available_meters()

    # Create a single coordinator for all meters
    coordinator = WaterSmartUpdateCoordinator(
        hass,
        watersmart,
        hostname,
        username,
        meters=available_meters,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = WaterSmartData(
        coordinator=coordinator,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry.runtime_data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: WaterSmartConfigEntry) -> bool:
    """Unload a config entry.

    Returns:
        If the unload was successful.
    """
    return bool(await hass.config_entries.async_unload_platforms(entry, PLATFORMS))
