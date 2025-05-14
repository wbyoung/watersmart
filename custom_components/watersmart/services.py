"""Support for the WaterSmart integration."""

from datetime import date, datetime
from functools import partial
from typing import Final, cast

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import selector
from homeassistant.util import dt
import voluptuous as vol

from .const import DOMAIN
from .coordinator import (
    WaterSmartUpdateCoordinator,
    _from_timestamp,
    _serialize_records,
)
from .types import WaterSmartData

ATTR_CONFIG_ENTRY: Final = "config_entry"
ATTR_FROM_CACHE: Final = "cached"
ATTR_START: Final = "start"
ATTR_END: Final = "end"
HOURLY_HISTORY_SERVICE_NAME: Final = "get_hourly_history"

SERVICE_SCHEMA: Final = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): selector.ConfigEntrySelector(
            {
                "integration": DOMAIN,
            }
        ),
        vol.Optional(ATTR_FROM_CACHE): bool,
        vol.Optional(ATTR_START): vol.Any(str, int),
        vol.Optional(ATTR_END): vol.Any(str, int),
    }
)


def __get_date(date_input: str | int | None) -> date | datetime | None:
    """Get date."""

    if not date_input:
        return None

    if isinstance(date_input, int) and (value := dt.utc_from_timestamp(date_input)):
        return cast(datetime, value)

    if isinstance(date_input, str) and (value := dt.parse_datetime(date_input)):
        return cast(datetime, value)

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_date",
        translation_placeholders={
            "date": date_input,
        },
    )


def __get_coordinator(
    hass: HomeAssistant, call: ServiceCall
) -> WaterSmartUpdateCoordinator:
    """Get the coordinator from the entry."""

    entry_id: str = call.data[ATTR_CONFIG_ENTRY]
    entry: ConfigEntry | None = hass.config_entries.async_get_entry(entry_id)

    if not entry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_config_entry",
            translation_placeholders={
                "config_entry": entry_id,
            },
        )

    if entry.state != ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unloaded_config_entry",
            translation_placeholders={
                "config_entry": entry.title,
            },
        )

    runtime_data: WaterSmartData = hass.data[DOMAIN][entry_id]

    return runtime_data.coordinator


async def __get_hourly_history(
    call: ServiceCall,
    *,
    hass: HomeAssistant,
) -> ServiceResponse:
    coordinator = __get_coordinator(hass, call)

    start = __get_date(call.data.get(ATTR_START))
    end = __get_date(call.data.get(ATTR_END))

    if call.data.get(ATTR_FROM_CACHE) is False:
        await coordinator.async_refresh()

    records = []

    for record in coordinator.data["hourly"]:
        record_date = _from_timestamp(record["read_datetime"])

        if start and dt.as_local(record_date) < dt.as_local(start):
            continue

        if end and dt.as_local(record_date) > dt.as_local(end):
            continue

        records.append(record)

    return {"history": _serialize_records(records)}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up WaterSmart services."""

    hass.services.async_register(
        DOMAIN,
        HOURLY_HISTORY_SERVICE_NAME,
        partial(__get_hourly_history, hass=hass),
        schema=SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
