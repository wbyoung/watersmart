"""WaterSmart dataclasses and typing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry

from . import coordinator as cdn

type WaterSmartConfigEntry = ConfigEntry[WaterSmartData]


@dataclass
class WaterSmartData:
    """Runtime data definition."""

    coordinators: dict[str, cdn.WaterSmartUpdateCoordinator]  # meter_id -> coordinator


class SensorData(TypedDict):
    """Shape of data stored on coordinator for individual sensors."""

    state: Any
    attrs: dict[str, Any]
