"""Test client."""

from unittest.mock import call

from homeassistant.core import HomeAssistant
import pytest

from custom_components.watersmart.client import (
    AuthenticationError,
    InvalidAccountNumberError,
    ScrapeError,
    WaterSmartClient,
)


async def test_login_success(hass: HomeAssistant, mock_aiohttp_session, fixture_loader):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    await client.async_get_account_number()

    mock_aiohttp_session.post.assert_has_calls(
        [
            call(
                "https://test.watersmart.com/index.php/welcome/login?forceEmail=1",
                data={
                    "token": "",
                    "email": "test@home-assistant.io",
                    "password": "Passw0rd",
                },
            ),
        ]
    )


async def test_login_is_preserved(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    await client.async_get_account_number()
    await client.async_get_account_number()

    assert mock_aiohttp_session.post.call_count == 1


async def test_login_failure(hass: HomeAssistant, mock_aiohttp_session, fixture_loader):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_error_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    with pytest.raises(AuthenticationError):
        await client.async_get_account_number()


async def test_structure_change_failure(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_structure_change_failure_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    with pytest.raises(ScrapeError):
        await client.async_get_account_number()


async def test_async_get_account_number(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )
    account_number = await client.async_get_account_number()

    assert account_number == "1234567-8900"


async def test_account_number_unmatchable(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.account_number_unmatchable_html
    )

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    with pytest.raises(InvalidAccountNumberError):
        await client.async_get_account_number()


async def test_async_get_async_get_hourly_data(
    hass: HomeAssistant,
    mock_aiohttp_session,
    fixture_loader,
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_html
    )
    mock_aiohttp_session.get.return_value.text.return_value = (
        fixture_loader.realtime_api_response_json
    )

    client = WaterSmartClient(hostname="", username="", password="")
    hourly = await client.async_get_hourly_data()

    mock_aiohttp_session.get.assert_has_calls(
        [
            call("https://.watersmart.com/index.php/rest/v1/Chart/RealTimeChart"),
        ]
    )

    assert mock_aiohttp_session.post.call_count == 1  # for login
    assert hourly == [
        {
            "read_datetime": 1718823600,
            "gallons": 7.48,
            "flags": None,
            "leak_gallons": 0,
        },
        {"read_datetime": 1718827200, "gallons": 0, "flags": None, "leak_gallons": 0},
        {
            "read_datetime": 1718830800,
            "gallons": 7.48,
            "flags": None,
            "leak_gallons": 0,
        },
        {"read_datetime": 1718834400, "gallons": 0, "flags": None, "leak_gallons": 0},
    ]
