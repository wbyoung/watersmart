"""Constants for the WaterSmart integration."""

from datetime import timedelta
from typing import Final

ATTRIBUTION: Final = "Data scraped from WaterSmart"
DOMAIN: Final = "watersmart"
MANUFACTURER: Final = "WaterSmart by VertexOne"
DEFAULT_SCAN_INTERVAL = timedelta(hours=1)

GALLONS_FOR_MOST_RECENT_HOUR: Final = "GallonsForMostRecentHour"
GALLONS_FOR_MOST_RECENT_FULL_DAY_KEY: Final = "GallonsForMostRecentFullDay"
