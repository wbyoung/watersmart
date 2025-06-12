"""Diagnostics support for WaterSmart."""

from typing import Any, cast

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import WaterSmartUpdateCoordinator

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
}


async def async_get_config_entry_diagnostics(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: WaterSmartUpdateCoordinator = entry.runtime_data.coordinator

    return cast(
        "dict[str, Any]",
        async_redact_data(
            {
                "entry": entry.as_dict(),
                "data": coordinator.data,
            },
            TO_REDACT,
        ),
    )
