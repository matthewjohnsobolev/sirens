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
    OBLAST_NAMES,
    OBLAST_TRIGGERS,
    apostrophe_variants,
)
from domain.messages import MESSAGES, alert_message_key

__all__ = [
    "APOSTROPHES",
    "BROADCAST_CITIES",
    "BROADCAST_DISTRICTS",
    "CITIES_LIST",
    "DISTRICT_CONFIG",
    "DISTRICTS_BY_OBLAST",
    "LOCATION_LOCATIVE",
    "MESSAGES",
    "OBLAST_NAMES",
    "OBLAST_TRIGGERS",
    "REGION_CONFIG",
    "SOURCE_KEYS",
    "alert_message_key",
    "apostrophe_variants",
    "real_channels",
    "real_source_channels",
    "test_channels",
    "test_source_channels",
]
