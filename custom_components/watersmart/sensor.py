"""Support for the WaterSmart service."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import WaterSmartConfigEntry
from .const import ATTRIBUTION, SensorKey
from .coordinator import MeterData, WaterSmartUpdateCoordinator, _get_device_info
from .types import SensorData


@dataclass(frozen=True, kw_only=True)
class WaterSmartSensorDescription(SensorEntityDescription):
    """Class describing WaterSmart sensor entities."""

    value_fn: Callable[[SensorData], str | int | float | None]
    attr_fn: Callable[[dict[str, Any]], dict[str, Any]] = lambda attrs: attrs


SENSOR_TYPES: tuple[WaterSmartSensorDescription, ...] = (
    WaterSmartSensorDescription(
        key=SensorKey.GALLONS_FOR_MOST_RECENT_HOUR,
        value_fn=lambda data: cast("float", data),
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        translation_key="gallons_for_most_recent_hour",
    ),
    WaterSmartSensorDescription(
        key=SensorKey.GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY,
        value_fn=lambda data: cast("float", data),
        device_class=SensorDeviceClass.WATER,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        translation_key="gallons_for_most_recent_full_day",
    ),
)


async def async_setup_entry(  # noqa: RUF029
    hass: HomeAssistant,  # noqa: ARG001
    entry: WaterSmartConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WaterSmart sensor entities based on a config entry."""
    data = entry.runtime_data
    coordinator = data.coordinator

    # Create sensors for each meter
    entities = [
        WaterSmartSensor(coordinator, meter, description)
        for meter in coordinator.meters
        for description in SENSOR_TYPES
    ]

    async_add_entities(entities)


class WaterSmartSensor(CoordinatorEntity[WaterSmartUpdateCoordinator], SensorEntity):
    """Abstract class for an OpenWeatherMap sensor."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    entity_description: WaterSmartSensorDescription

    def __init__(
        self,
        coordinator: WaterSmartUpdateCoordinator,
        meter: dict[str, str],
        description: WaterSmartSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self.entity_description = description
        self._meter_id = meter["meter_id"]
        self._sensor_data = self._get_sensor_data(
            coordinator.data, self._meter_id, description.key
        )
        self._attr_unique_id = f"{coordinator.hostname}-{coordinator.username}-{self._meter_id}-{description.key}".lower()
        self._attr_device_info = _get_device_info(
            coordinator.hostname,
            coordinator.username,
            meter["meter_id"],
            meter["name"],
        )

    @property
    def native_value(self) -> str | int | float | None:
        """Return the state."""
        return self.entity_description.value_fn(self._sensor_data["state"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return self.entity_description.attr_fn(self._sensor_data.get("attrs", {}))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle data update."""
        self._sensor_data = self._get_sensor_data(
            self.coordinator.data, self._meter_id, self.entity_description.key
        )
        super()._handle_coordinator_update()

    @staticmethod
    def _get_sensor_data(
        coordinator_data: dict[str, MeterData],
        meter_id: str,
        kind: SensorKey,
    ) -> SensorData:
        """Get sensor data.

        Returns:
            The actual sensor data.
        """
        meter_data = coordinator_data.get(meter_id, {})
        return cast("dict[str, SensorData]", meter_data).get(
            kind, {"state": None, "attrs": {}}
        )
