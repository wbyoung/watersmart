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
from homeassistant.util import dt as dt_util
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
ATTR_METER_ID: Final = "meter_id"
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
        vol.Optional(ATTR_METER_ID): str,
    }
)


def __get_date(date_input: str | int | None) -> date | datetime | None:
    """Get date.

    Returns:
        The date from the input.

    Raises:
        ServiceValidationError: When the date is not valid.
    """

    if not date_input:
        return None

    if isinstance(date_input, int) and (
        value := dt_util.utc_from_timestamp(date_input)
    ):
        return cast("datetime", value)

    if isinstance(date_input, str) and (value := dt_util.parse_datetime(date_input)):
        return cast("datetime", value)

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="invalid_date",
        translation_placeholders={
            "date": date_input,
        },
    )


def __get_coordinator_and_meter(
    hass: HomeAssistant, call: ServiceCall
) -> tuple[WaterSmartUpdateCoordinator, str]:
    """Get the coordinator and meter_id from the entry.

    Returns:
        A tuple of (coordinator, meter_id).

    Raises:
        ServiceValidationError: When the entry is not valid.
    """

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
    coordinator = runtime_data.coordinator

    # Get meter_id from call data, or use first available meter
    meter_id: str | None = call.data.get(ATTR_METER_ID)

    if meter_id:
        # Validate meter_id exists
        if not any(m["meter_id"] == meter_id for m in coordinator.meters):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_meter_id",
                translation_placeholders={
                    "meter_id": meter_id,
                },
            )
    else:
        # Use first meter if no meter_id specified
        meter_id = coordinator.meters[0]["meter_id"]

    return coordinator, meter_id


async def __get_hourly_history(
    call: ServiceCall,
    *,
    hass: HomeAssistant,
) -> ServiceResponse:
    coordinator, meter_id = __get_coordinator_and_meter(hass, call)

    start = __get_date(call.data.get(ATTR_START))
    end = __get_date(call.data.get(ATTR_END))

    if call.data.get(ATTR_FROM_CACHE) is False:
        await coordinator.async_refresh()

    records = []

    # Get data for the specific meter
    meter_data = coordinator.data.get(meter_id, {})
    for record in meter_data.get("hourly", []):
        record_date = _from_timestamp(record["read_datetime"])

        if start and dt_util.as_local(record_date) < dt_util.as_local(start):
            continue

        if end and dt_util.as_local(record_date) > dt_util.as_local(end):
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
