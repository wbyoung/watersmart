"""Fixtures for testing."""

from unittest.mock import AsyncMock, patch
from pathlib import Path

import json
import pytest
from typing import Generator

FIXTURES_DIR = Path(__file__).parent.joinpath("fixtures")


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
    return FIXTURES_DIR.joinpath("login_success.html").read_text()


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


class MockAiohttpResponse:
    def __init__(self, text="", json={}, status=200):
        self.text = AsyncMock(return_value="", spec="aiohttp.ClientResponse.text")

    async def json(self):
        return json.loads(await self.text())


@pytest.fixture
def mock_aiohttp_session() -> Generator[dict[str, AsyncMock], None, None]:
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
def mock_watersmart_client() -> Generator[AsyncMock, None, None]:
    """Mock a WaterSmart client."""

    hourly_data = FixtureLoader().realtime_api_response_obj["data"]["series"]

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

        yield client
