"""Test the Simple Integration config flow."""

from unittest.mock import patch

from homeassistant import config_entries, setup
from homeassistant.core import HomeAssistant
import pytest

from custom_components.watersmart.client import AuthenticationError
from custom_components.watersmart.const import DOMAIN


async def test_successful_flow(hass: HomeAssistant, mock_watersmart_client):
    """Test we get the form."""

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    with patch(
        "custom_components.watersmart.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        configured_result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "test",
                "username": "test@home-assistant.io",
                "password": "Passw0rd",
            },
        )

    assert configured_result["type"] == "create_entry"
    assert configured_result["title"] == "test (test@home-assistant.io)"
    assert configured_result["data"] == {
        "host": "test",
        "username": "test@home-assistant.io",
        "password": "Passw0rd",
    }
    await hass.async_block_till_done()
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("side_effect", "expected_errors"),
    [
        (None, {"base": "invalid_auth"}),
        (TimeoutError("timeout"), {"base": "cannot_connect"}),
        (
            AuthenticationError(["invalid credentials"]),
            {
                "base": "invalid_auth",
            },
        ),
        (
            Exception("unknown error"),
            {
                "base": "unknown",
            },
        ),
    ],
    ids=["no_account_number", "client_timeout", "auth_error", "unknown_error"],
)
async def test_error(
    hass: HomeAssistant,
    mock_watersmart_client,
    side_effect,
    expected_errors,
):
    """Test we get the form."""

    mock_watersmart_client.async_get_account_number.return_value = None
    mock_watersmart_client.async_get_account_number.side_effect = side_effect

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    with patch(
        "custom_components.watersmart.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        configured_result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "test",
                "username": "test@home-assistant.io",
                "password": "Passw0rd",
            },
        )

    assert "title" not in configured_result
    assert "data" not in configured_result

    assert configured_result["type"] == "form"
    assert configured_result["errors"] == expected_errors
    await hass.async_block_till_done()
    assert len(mock_setup_entry.mock_calls) == 0
