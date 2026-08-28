"""
Domain layer for Sirens: geographic data, Telegram channels, and message templates.
"""

from domain.channels import (
    BROADCAST_CITIES,
    BROADCAST_DISTRICTS,
    CITIES_LIST,
    REGION_CONFIG,
    real_channels,
    test_channels,
)
from domain.geo import (
    APOSTROPHES,
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    OBLAST_TRIGGERS,
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
    "MESSAGES",
    "OBLAST_TRIGGERS",
    "REGION_CONFIG",
    "apostrophe_variants",
    "real_channels",
    "test_channels",
]
