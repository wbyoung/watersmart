"""Fixtures for testing."""

from collections.abc import Generator
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, PropertyMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.watersmart.client import AuthenticationError
from custom_components.watersmart.const import DOMAIN

FIXTURES_DIR = Path(__file__).parent.joinpath("fixtures")


class AdvacnedPropertyMock(PropertyMock):
    def __get__(self, obj, obj_type=None):
        return self(obj)

    def __set__(self, obj, val):
        self(obj, val)


class FixtureLoader:
    """Fixture loader."""

    def __getitem__(self, name):
        return self.__getattr__(name)

    def __getattr__(self, name):
        name, ext = name.rsplit("_", 1)
        parse = False

        if ext == "obj":
            parse = True
            ext = "json"

        data = FIXTURES_DIR.joinpath(f"{name}.{ext}").read_text()

        if parse:
            data = json.loads(data)

        return data


@pytest.fixture
def fixture_loader():
    return FixtureLoader()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


class MockAiohttpResponse:
    def __init__(
        self,
        text: str = "",  # noqa: ARG002
        json: dict[str, Any] | None = None,
        status: int = 200,  # noqa: ARG002
    ):
        if json is None:
            json = {}
        self.text = AsyncMock(return_value="", spec="aiohttp.ClientResponse.text")

    async def json(self):
        return json.loads(await self.text())


@pytest.fixture
def mock_aiohttp_session() -> Generator[dict[str, AsyncMock]]:
    with patch("aiohttp.ClientSession", autospec=True) as mock_session:
        session = mock_session.return_value
        session.get = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.get"
        )
        session.put = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.put"
        )
        session.post = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.post"
        )
        session.delete = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.delete"
        )
        session.options = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.options"
        )
        session.patch = AsyncMock(
            return_value=MockAiohttpResponse(), spec="aiohttp.ClientSession.patch"
        )

        yield session


@pytest.fixture
def mock_watersmart_client(fixture_loader) -> Generator[AsyncMock]:
    """Mock a WaterSmart client."""

    hourly_data = fixture_loader.realtime_api_response_obj["data"]["series"]

    with (
        patch(
            "custom_components.watersmart.client.WaterSmartClient", autospec=True
        ) as mock_client,
        patch(
            "custom_components.watersmart.WaterSmartClient",
            new=mock_client,
        ),
        patch(
            "custom_components.watersmart.config_flow.WaterSmartClient",
            new=mock_client,
        ),
        patch(
            "custom_components.watersmart.coordinator.WaterSmartClient",
            new=mock_client,
        ),
    ):
        client = mock_client.return_value
        client.async_get_account_number.return_value = "1234567-8900"
        client.async_get_hourly_data.return_value = hourly_data
        # Add meter support for multi-meter functionality
        client.async_get_available_meters.return_value = [
            {
                "meter_id": "default",
                "name": "test",
                "account_number": "1234567-8900",
                "user_id": "",
                "residence_id": "",
            }
        ]

        yield client


@pytest.fixture
def client_authentication_error(mock_watersmart_client):
    mock_watersmart_client.async_get_hourly_data.side_effect = AuthenticationError(
        ["invalid credentials"]
    )


@pytest.fixture
def mock_sensor_name() -> Generator[PropertyMock]:
    """Mock sensor names.

    This testing setup/library does not use `strings.json` and the entity description to translation key
    to get the entity name, so it's being patched here to just use the translaiton key. That way we at least
    get entity ids that are closer to what they will really be.
    """

    with patch(
        "homeassistant.components.sensor.SensorEntity.name",
        new_callable=AdvacnedPropertyMock,
    ) as mock_name:

        def name_from_entity_description(sensor):
            return sensor.entity_description.translation_key.replace(
                "_", " "
            ).capitalize()

        mock_name.side_effect = lambda self: (
            name_from_entity_description(self) if self else None
        )

        yield mock_name


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_sensor_name: Generator[PropertyMock],
    mock_watersmart_client: Generator[AsyncMock],
) -> MockConfigEntry:
    """Set up the WaterSmart integration for testing."""

    mock_config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    return mock_config_entry
