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
from domain.ukraine_alarm import (
    DEFAULT_STATE_ID_TO_OBLAST,
    ApiAlertKind,
    ApiAlertLevel,
    ApiRegionType,
    TargetAlert,
    UkraineAlarmGeoResolver,
    compute_alerts_diff,
    extract_active_threats_by_district,
    normalize_geo_name,
    parse_alert_kind_and_level,
)

__all__ = [
    "APOSTROPHES",
    "ApiAlertKind",
    "ApiAlertLevel",
    "ApiRegionType",
    "BROADCAST_CITIES",
    "BROADCAST_DISTRICTS",
    "CITIES_LIST",
    "DEFAULT_STATE_ID_TO_OBLAST",
    "DISTRICT_CONFIG",
    "DISTRICTS_BY_OBLAST",
    "LOCATION_LOCATIVE",
    "MESSAGES",
    "OBLAST_NAMES",
    "OBLAST_TRIGGERS",
    "REGION_CONFIG",
    "SOURCE_KEYS",
    "TargetAlert",
    "UkraineAlarmGeoResolver",
    "alert_message_key",
    "apostrophe_variants",
    "compute_alerts_diff",
    "extract_active_threats_by_district",
    "normalize_geo_name",
    "parse_alert_kind_and_level",
    "real_channels",
    "real_source_channels",
    "test_channels",
    "test_source_channels",
]
