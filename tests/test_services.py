"""Test services for WaterSmart integration."""

import re
from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from syrupy.assertion import SnapshotAssertion
import voluptuous as vol

from custom_components.watersmart.const import DOMAIN, PSEUDO_METER_ID
from custom_components.watersmart.services import (
    ATTR_CONFIG_ENTRY,
    ATTR_METER_ID,
    HOURLY_HISTORY_SERVICE_NAME,
)

from .conftest import MockConfigEntry


@pytest.mark.usefixtures("init_integration")
def test_has_services(
    hass: HomeAssistant,
) -> None:
    """Test the existence of the WaterSmart Service."""
    assert hass.services.has_service(DOMAIN, HOURLY_HISTORY_SERVICE_NAME)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize("service", [HOURLY_HISTORY_SERVICE_NAME])
@pytest.mark.parametrize(
    ("cached", "update_call_count"),
    [({"cached": False}, 2), ({"cached": True}, 1), ({}, 1)],
)
@pytest.mark.parametrize(
    "start",
    [
        {"start": "2024-06-19T19:30:00-07:00"},
        {"start": "2024-06-19 19:30:00"},
        {"start": "2024-06-20T02:30:00.000Z"},
        {"start": 1718850600},
        {},
    ],
)
@pytest.mark.parametrize(
    "end",
    [
        {"end": "2024-06-19T21:30:00-07:00"},
        {"end": "2024-06-19 21:30:00"},
        {"end": "2024-06-20T04:30:00.000Z"},
        {"end": 1718857800},
        {},
    ],
)
async def test_service(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_watersmart_client,
    snapshot: SnapshotAssertion,
    service: str,
    cached: dict[str, bool],
    update_call_count: int,
    start: dict[str, str],
    end: dict[str, str],
):
    entry = {ATTR_CONFIG_ENTRY: mock_config_entry.entry_id}

    data = entry | cached | start | end

    assert snapshot == await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
    )

    assert mock_watersmart_client.async_get_hourly_data.call_count == update_call_count


@pytest.fixture
def config_entry_data(
    mock_config_entry: MockConfigEntry, request: pytest.FixtureRequest
) -> dict[str, str]:
    """Fixture for the config entry."""
    if "config_entry" in request.param and request.param["config_entry"] is True:
        return {"config_entry": mock_config_entry.entry_id}

    return cast("dict[str, str]", request.param)


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize("service", [HOURLY_HISTORY_SERVICE_NAME])
@pytest.mark.parametrize(
    ("config_entry_data", "service_data", "error", "error_message"),
    [
        ({}, {}, vol.er.Error, "required key not provided .+"),
        (
            {"config_entry": True},
            {"cached": "incorrect cache value"},
            vol.er.Error,
            "expected bool for dictionary value .+",
        ),
        (
            {"config_entry": "incorrect entry"},
            {},
            ServiceValidationError,
            "Invalid config entry.+",
        ),
        (
            {"config_entry": True},
            {
                "start": "incorrect date",
            },
            ServiceValidationError,
            "Invalid date provided. Got incorrect date",
        ),
        (
            {"config_entry": True},
            {
                "end": "incorrect date",
            },
            ServiceValidationError,
            "Invalid date provided. Got incorrect date",
        ),
        (
            {"config_entry": True},
            {ATTR_METER_ID: "nonexistent"},
            ServiceValidationError,
            "Invalid meter ID provided. Got nonexistent",
        ),
    ],
    indirect=["config_entry_data"],
)
async def test_service_validation(
    hass: HomeAssistant,
    service: str,
    config_entry_data: dict[str, str],
    service_data: dict[str, str],
    error: type[Exception],
    error_message: str,
) -> None:
    """Test the WaterSmart Service validation."""

    with pytest.raises(error) as exc:
        await hass.services.async_call(
            DOMAIN,
            service,
            config_entry_data | service_data,
            blocking=True,
            return_response=True,
        )
    assert re.match(error_message, str(exc.value))


@pytest.mark.usefixtures("init_integration")
async def test_service_with_valid_meter_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_watersmart_client,
) -> None:
    """Service call with a known meter_id succeeds (exercises the valid-meter branch)."""
    result = await hass.services.async_call(
        DOMAIN,
        HOURLY_HISTORY_SERVICE_NAME,
        {ATTR_CONFIG_ENTRY: mock_config_entry.entry_id, ATTR_METER_ID: PSEUDO_METER_ID},
        blocking=True,
        return_response=True,
    )
    assert result is not None


@pytest.mark.usefixtures("init_integration")
async def test_service_requires_meter_id_for_multiple_meters(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_watersmart_client,
) -> None:
    """Service call without meter_id fails when multiple meters are configured."""
    mock_watersmart_client.async_get_available_meters.return_value = [
        {"meter_id": "111222", "name": "Meter A", "account_number": "A", "user_id": "111", "residence_id": "222"},
        {"meter_id": "333444", "name": "Meter B", "account_number": "B", "user_id": "333", "residence_id": "444"},
    ]
    # Re-setup to pick up multiple meters
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError, match="Multiple meters found"):
        await hass.services.async_call(
            DOMAIN,
            HOURLY_HISTORY_SERVICE_NAME,
            {ATTR_CONFIG_ENTRY: mock_config_entry.entry_id},
            blocking=True,
            return_response=True,
        )


@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize("service", [HOURLY_HISTORY_SERVICE_NAME])
async def test_service_called_with_unloaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    service: str,
) -> None:
    """Test service calls with unloaded config entry."""
    await hass.config_entries.async_unload(mock_config_entry.entry_id)

    data = {"config_entry": mock_config_entry.entry_id}

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
            blocking=True,
            return_response=True,
        )
