"""Test client."""

from unittest.mock import AsyncMock, MagicMock, call

from bs4 import BeautifulSoup
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


async def test_login_success_with_refreshtoken(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    resp1 = AsyncMock()
    resp1.text.return_value = fixture_loader.login_refreshtoken_html
    resp2 = AsyncMock()
    resp2.text.return_value = fixture_loader.login_success_html
    mock_aiohttp_session.post.side_effect = [resp1, resp2]

    client = WaterSmartClient(
        hostname="test",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    await client.async_get_account_number()

    assert mock_aiohttp_session.post.call_count == 2

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
    mock_aiohttp_session.post.assert_has_calls(
        [
            call(
                "https://test.watersmart.com/index.php/welcome/login?forceEmail=1",
                data={
                    "token": "",
                    "loginRefreshToken": "12.34 56.78",
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


async def test_multimeter_login_success(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )

    client = WaterSmartClient(
        hostname="hptx",
        username="test@home-assistant.io",
        password="Passw0rd",  # noqa: S106
    )

    await client.async_get_account_number()

    mock_aiohttp_session.post.assert_called_once_with(
        "https://hptx.watersmart.com/index.php/welcome/login?forceEmail=1",
        data={
            "token": "",
            "email": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )


async def test_multimeter_account_number(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    """Account number is the first non-summary div.account in the hptx format."""
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )

    client = WaterSmartClient(hostname="hptx", username="", password="")
    account_number = await client.async_get_account_number()

    assert account_number == "1234567-8900"


async def test_multimeter_available_meters(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    """Both combined=0 meter links are extracted; the combined=1 summary is skipped."""
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )

    client = WaterSmartClient(hostname="hptx", username="", password="")
    meters = await client.async_get_available_meters()

    assert meters == [
        {
            "meter_id": "13089_11499",
            "name": "123 N Main St",
            "account_number": "1234567-8900",
            "user_id": "13089",
            "residence_id": "11499",
        },
        {
            "meter_id": "13090_11500",
            "name": "456 S Oak Ave",
            "account_number": "9876543-2100",
            "user_id": "13090",
            "residence_id": "11500",
        },
    ]


# ---------------------------------------------------------------------------
# async_switch_meter
# ---------------------------------------------------------------------------


async def test_switch_meter(hass: HomeAssistant, mock_aiohttp_session, fixture_loader):
    """Switching to a valid meter issues a GET to userPicker/pick."""
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )

    client = WaterSmartClient(hostname="hptx", username="", password="")
    await client.async_get_available_meters()  # authenticate and populate _meters

    await client.async_switch_meter("13089_11499")

    mock_aiohttp_session.get.assert_called_once_with(
        "https://hptx.watersmart.com/index.php/userPicker/pick",
        params={
            "userID": "13089",
            "residenceID": "11499",
            "combined": "0",
            "returnUrlOverride": "",
        },
    )


async def test_switch_meter_unknown_id(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    """Switching to an unknown meter_id raises ValueError."""
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )

    client = WaterSmartClient(hostname="hptx", username="", password="")
    await client.async_get_available_meters()

    with pytest.raises(ValueError, match="nonexistent"):
        await client.async_switch_meter("nonexistent")


async def test_async_get_hourly_data_with_meter_id(
    hass: HomeAssistant, mock_aiohttp_session, fixture_loader
):
    """Providing a meter_id that differs from the active meter triggers a switch."""
    mock_aiohttp_session.post.return_value.text.return_value = (
        fixture_loader.login_success_multimeter_html
    )
    mock_aiohttp_session.get.return_value.text.return_value = (
        fixture_loader.realtime_api_response_json
    )

    client = WaterSmartClient(hostname="hptx", username="", password="")
    # _current_meter_id is None after auth, so any meter_id triggers async_switch_meter
    await client.async_get_hourly_data(meter_id="13090_11500")

    mock_aiohttp_session.get.assert_any_call(
        "https://hptx.watersmart.com/index.php/userPicker/pick",
        params={
            "userID": "13090",
            "residenceID": "11500",
            "combined": "0",
            "returnUrlOverride": "",
        },
    )


# ---------------------------------------------------------------------------
# _extract_account_number parsing branches
# ---------------------------------------------------------------------------


def test_extract_account_number_account_nav_no_title():
    """Falls through to hptx format when #account-navigation has no 'Account Number' child."""
    soup = BeautifulSoup(
        '<div id="account-navigation"><div>No title here</div></div>'
        '<div class="account">1234567-8900</div>',
        "html.parser",
    )
    assert WaterSmartClient._extract_account_number(soup) == "1234567-8900"


def test_extract_account_number_skips_digits_only():
    """A div.account containing only digits is skipped in the hptx fallback path."""
    soup = BeautifulSoup(
        '<div class="account">99999</div><div class="account">1234567-8900</div>',
        "html.parser",
    )
    assert WaterSmartClient._extract_account_number(soup) == "1234567-8900"


# ---------------------------------------------------------------------------
# _extract_meters parsing branches
# ---------------------------------------------------------------------------


def test_extract_meters_link_without_ids_falls_back_to_default():
    """A combined=0 userPicker link missing userID/residenceID is skipped."""
    soup = BeautifulSoup(
        '<a href="/index.php/userPicker/pick?combined=0&returnUrlOverride=">'
        '<div class="inline"><h3>Meter</h3></div>'
        "</a>",
        "html.parser",
    )
    client = WaterSmartClient(
        hostname="test", username="", password="", session=MagicMock()
    )
    client._account_number = "1234567-8900"
    meters = client._extract_meters(soup)
    assert len(meters) == 1
    assert meters[0]["meter_id"] == "default"


def test_extract_meters_link_without_inline_div_falls_back_to_default():
    """A userPicker link with valid IDs but no div.inline is skipped."""
    soup = BeautifulSoup(
        '<a href="/index.php/userPicker/pick?userID=123&residenceID=456&combined=0&returnUrlOverride=">'
        "Just a link"
        "</a>",
        "html.parser",
    )
    client = WaterSmartClient(
        hostname="test", username="", password="", session=MagicMock()
    )
    client._account_number = "1234567-8900"
    meters = client._extract_meters(soup)
    assert len(meters) == 1
    assert meters[0]["meter_id"] == "default"
