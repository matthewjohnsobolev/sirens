"""
Domain layer for Sirens: geographic data, Telegram channels, and message templates.
"""

from domain.channels import (
    BROADCAST_CITIES,
    BROADCAST_DISTRICTS,
    CITIES_LIST,
    REGION_CONFIG,
    SOURCE_KEYS,
    real_channels,
    real_source_channels,
    test_channels,
    test_source_channels,
)
from domain.geo import (
    APOSTROPHES,
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    LOCATION_LOCATIVE,
    OBLAST_TRIGGERS,
    REGIONS,
    apostrophe_variants,
)
from domain.messages import MESSAGES

__all__ = [
    "APOSTROPHES",
    "BROADCAST_CITIES",
    "BROADCAST_DISTRICTS",
    "CITIES_LIST",
    "DISTRICT_CONFIG",
    "DISTRICTS_BY_OBLAST",
    "LOCATION_LOCATIVE",
    "MESSAGES",
    "OBLAST_TRIGGERS",
    "REGION_CONFIG",
    "REGIONS",
    "SOURCE_KEYS",
    "apostrophe_variants",
    "real_channels",
    "real_source_channels",
    "test_channels",
    "test_source_channels",
]
