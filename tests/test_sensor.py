"""Test sensor for simple integration."""

from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

import datetime as dt
import pytest
from unittest.mock import patch, PropertyMock
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from typing import Generator

from custom_components.watersmart.client import AuthenticationError
from custom_components.watersmart.const import DOMAIN


class AdvacnedPropertyMock(PropertyMock):
    def __get__(self, obj, obj_type=None):
        return self(obj)

    def __set__(self, obj, val):
        self(obj, val)


@pytest.fixture
def mock_sensor_name() -> Generator[PropertyMock, None, None]:
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


async def test_most_recent_day_sensor(
    hass: HomeAssistant, mock_watersmart_client, mock_sensor_name
):
    """Test sensor."""
    hourly = mock_watersmart_client.async_get_hourly_data.return_value

    for gallons in range(25):
        last_time = dt.datetime.fromtimestamp(hourly[-1]["read_datetime"])
        next_time = int((last_time + dt.timedelta(hours=1)).timestamp())
        hourly.append(
            dict(
                hourly[-1],
                **{
                    "read_datetime": next_time,
                    "gallons": gallons,
                },
            )
        )

    mock_watersmart_client.async_get_hourly_data.return_value = hourly

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    recent_day_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_full_day"
    )

    assert recent_day_sensor_state
    assert recent_day_sensor_state.state == "1136"  # gallons changed to liters
    assert recent_day_sensor_state.attributes == {
        "attribution": "Data scraped from WaterSmart",
        "friendly_name": "WaterSmart (test) Gallons for most recent full day",
        "device_class": "water",
        "unit_of_measurement": UnitOfVolume.LITERS,
        "related": [
            {"start": "2024-06-20T00:00:00-07:00", "gallons": 1},
            {"start": "2024-06-20T01:00:00-07:00", "gallons": 2},
            {"start": "2024-06-20T02:00:00-07:00", "gallons": 3},
            {"start": "2024-06-20T03:00:00-07:00", "gallons": 4},
            {"start": "2024-06-20T04:00:00-07:00", "gallons": 5},
            {"start": "2024-06-20T05:00:00-07:00", "gallons": 6},
            {"start": "2024-06-20T06:00:00-07:00", "gallons": 7},
            {"start": "2024-06-20T07:00:00-07:00", "gallons": 8},
            {"start": "2024-06-20T08:00:00-07:00", "gallons": 9},
            {"start": "2024-06-20T09:00:00-07:00", "gallons": 10},
            {"start": "2024-06-20T10:00:00-07:00", "gallons": 11},
            {"start": "2024-06-20T11:00:00-07:00", "gallons": 12},
            {"start": "2024-06-20T12:00:00-07:00", "gallons": 13},
            {"start": "2024-06-20T13:00:00-07:00", "gallons": 14},
            {"start": "2024-06-20T14:00:00-07:00", "gallons": 15},
            {"start": "2024-06-20T15:00:00-07:00", "gallons": 16},
            {"start": "2024-06-20T16:00:00-07:00", "gallons": 17},
            {"start": "2024-06-20T17:00:00-07:00", "gallons": 18},
            {"start": "2024-06-20T18:00:00-07:00", "gallons": 19},
            {"start": "2024-06-20T19:00:00-07:00", "gallons": 20},
            {"start": "2024-06-20T20:00:00-07:00", "gallons": 21},
            {"start": "2024-06-20T21:00:00-07:00", "gallons": 22},
            {"start": "2024-06-20T22:00:00-07:00", "gallons": 23},
            {"start": "2024-06-20T23:00:00-07:00", "gallons": 24},
        ],
    }

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1


async def test_most_recent_hour_sensor(
    hass: HomeAssistant, mock_watersmart_client, mock_sensor_name
):
    """Test sensor."""
    mock_watersmart_client.async_get_hourly_data.return_value[-1]["gallons"] = 14.3

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    recent_hour_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_hour"
    )

    assert recent_hour_sensor_state
    assert recent_hour_sensor_state.state == "54.1"  # gallons changed to liters
    assert recent_hour_sensor_state.attributes == {
        "attribution": "Data scraped from WaterSmart",
        "friendly_name": "WaterSmart (test) Gallons for most recent hour",
        "device_class": "water",
        "unit_of_measurement": UnitOfVolume.LITERS,
        "start": "2024-06-19T22:00:00-07:00",
        "related": [
            {"gallons": 7.48, "start": "2024-06-19T19:00:00-07:00"},
            {"gallons": 0, "start": "2024-06-19T20:00:00-07:00"},
            {"gallons": 7.48, "start": "2024-06-19T21:00:00-07:00"},
            {"gallons": 14.3, "start": "2024-06-19T22:00:00-07:00"},
        ],
    }

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1


async def test_sensors_for_zero_gallons(
    hass: HomeAssistant, mock_watersmart_client, mock_sensor_name
):
    """Test sensor."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    recent_day_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_full_day"
    )

    assert recent_day_sensor_state
    assert recent_day_sensor_state.state == "0"

    recent_hour_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_hour"
    )

    assert recent_hour_sensor_state
    assert recent_hour_sensor_state.state == "0"

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1


async def test_sensor_update(
    hass: HomeAssistant, mock_watersmart_client, mock_sensor_name
):
    """Test sensor."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1

    async_fire_time_changed(hass, utcnow() + dt.timedelta(minutes=10))
    await hass.async_block_till_done()

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1

    async_fire_time_changed(hass, utcnow() + dt.timedelta(hours=1))
    await hass.async_block_till_done()

    assert mock_watersmart_client.async_get_hourly_data.call_count == 2


async def test_sensor_update_failure(
    hass: HomeAssistant, mock_watersmart_client, mock_sensor_name
):
    """Test sensor."""
    mock_watersmart_client.async_get_hourly_data.side_effect = AuthenticationError(
        "invalid credentials"
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "host": "test",
            "username": "test@home-assistant.io",
            "password": "Passw0rd",
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    recent_day_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_full_day"
    )

    assert recent_day_sensor_state is None

    recent_hour_sensor_state = hass.states.get(
        "sensor.watersmart_test_gallons_for_most_recent_hour"
    )

    assert recent_hour_sensor_state is None

    assert mock_watersmart_client.async_get_hourly_data.call_count == 1
