"""Constants for the WaterSmart integration."""

from datetime import timedelta
from enum import StrEnum, auto
from typing import Final

ATTRIBUTION: Final = "Data scraped from WaterSmart"
DOMAIN: Final = "watersmart"
MANUFACTURER: Final = "WaterSmart by VertexOne"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)


class SensorKey(StrEnum):
    """Converter key enumeration class."""

    GALLONS_FOR_MOST_RECENT_HOUR = auto()
    GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY = auto()
