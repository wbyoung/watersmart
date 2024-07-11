"""WaterSmart dataclasses and typing."""

from __future__ import annotations

from dataclasses import dataclass
from homeassistant.config_entries import ConfigEntry

from .coordinator import WaterSmartUpdateCoordinator

type WaterSmartConfigEntry = ConfigEntry[WaterSmartData]


@dataclass
class WaterSmartData:
    """Runtime data definition."""

    coordinator: WaterSmartUpdateCoordinator
