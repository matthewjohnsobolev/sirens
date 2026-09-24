"""
Integration models, mappings, and translation logic for Ukraine Alert API 3.0.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from domain.geo import DISTRICT_CONFIG, DISTRICTS_BY_OBLAST, OBLAST_NAMES

log = logging.getLogger(__name__)


class ApiRegionType(str, Enum):
    STATE = "State"
    DISTRICT = "District"
    COMMUNITY = "Community"
    CITY_OR_VILLAGE = "CityOrVillage"
    CITY_DISTRICT = "CityDistrict"
    NULL = "Null"


class ApiAlertKind(str, Enum):
    AIR = "AIR"
    ARTILLERY = "ARTILLERY"
    URBAN_FIGHTS = "URBAN_FIGHTS"
    CHEMICAL = "CHEMICAL"
    NUCLEAR = "NUCLEAR"
    INFO = "INFO"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


class ApiAlertLevel(str, Enum):
    RED = "Red"
    YELLOW = "Yellow"


@dataclass(frozen=True)
class TargetAlert:
    alert_type: str
    level: str | None = None


CITY_ONLY_DISTRICTS: frozenset[str] = frozenset({"kharkiv", "zaporizhzhia", "nikopol"})

DEFAULT_STATE_ID_TO_OBLAST: dict[str, str] = {
    "3": "khmelnytskyi_oblast",
    "4": "vinnytsia_oblast",
    "5": "rivne_oblast",
    "8": "volyn_oblast",
    "9": "dnipropetrovsk_oblast",
    "10": "zhytomyr_oblast",
    "11": "zakarpattia_oblast",
    "12": "zaporizhzhia_oblast",
    "13": "ivanofrankivsk_oblast",
    "14": "kyiv_oblast",
    "15": "kirovohrad_oblast",
    "16": "luhansk_oblast",
    "17": "mykolaiv_oblast",
    "18": "odesa_oblast",
    "19": "poltava_oblast",
    "20": "sumy_oblast",
    "21": "ternopil_oblast",
    "22": "kharkiv_oblast",
    "23": "kherson_oblast",
    "24": "cherkasy_oblast",
    "25": "chernihiv_oblast",
    "26": "chernivtsi_oblast",
    "27": "lviv_oblast",
    "28": "donetsk_oblast",
    "31": "kyiv",
    "9999": "crimea",
}


def normalize_geo_name(name: str) -> str:
    """Normalizes region/district/city names for robust matching."""
    if not name:
        return ""
    text = name.strip().lower()
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"^(м\.|місто|смт|селище|село)\s+", "", text)
    text = re.sub(r"\s+та\s+.*$", "", text)
    text = re.sub(
        r"\s+(район|область|громада|територіальна громада|міська територіальна громада)$",
        "",
        text,
    )
    return text.strip()


class UkraineAlarmGeoResolver:
    """
    Resolves Ukraine Alarm API region IDs to Sirens oblast and district keys.
    Builds hierarchy (State -> District -> Community) and provides lookups.
    """

    def __init__(self) -> None:
        self.state_id_to_oblast: dict[str, str] = dict(DEFAULT_STATE_ID_TO_OBLAST)
        self.district_id_to_district: dict[str, str] = {}
        self.community_id_to_district: dict[str, str] = {}
        self._build_static_district_lookup()

    def _build_static_district_lookup(self) -> None:
        """Indexes DISTRICT_CONFIG by normalized name and aliases."""
        self._name_to_district: dict[str, str] = {}
        for d_key, conf in DISTRICT_CONFIG.items():
            if d_key in CITY_ONLY_DISTRICTS:
                for alias in conf.get("aliases", []):
                    norm_alias = normalize_geo_name(alias)
                    if norm_alias:
                        self._name_to_district[norm_alias] = d_key
                for trig in conf.get("city_triggers", []):
                    norm_trig = normalize_geo_name(trig)
                    if norm_trig:
                        self._name_to_district[norm_trig] = d_key
            else:
                norm_name = normalize_geo_name(conf.get("name", ""))
                if norm_name:
                    self._name_to_district[norm_name] = d_key
                for alias in conf.get("aliases", []):
                    norm_alias = normalize_geo_name(alias)
                    if norm_alias:
                        self._name_to_district[norm_alias] = d_key

        self._name_to_oblast: dict[str, str] = {}
        for obl_key, obl_name in OBLAST_NAMES.items():
            norm_obl = normalize_geo_name(obl_name)
            if norm_obl:
                self._name_to_oblast[norm_obl] = obl_key

    def _map_descendants(self, node: dict[str, Any], target_key: str) -> None:
        for child in node.get("regionChildIds") or node.get("children") or []:
            cid = str(child.get("regionId") or child.get("id") or "")
            if cid:
                self.community_id_to_district[cid] = target_key
            self._map_descendants(child, target_key)

    def load_regions_tree(self, regions_payload: dict[str, Any] | list[dict[str, Any]]) -> None:
        """
        Parses GET /api/v3/regions response and binds region IDs to Sirens keys.
        """
        states_list = (
            regions_payload.get("states", [])
            if isinstance(regions_payload, dict)
            else regions_payload
        )
        for state in states_list:
            state_id = str(state.get("regionId") or state.get("id") or "")
            state_name = state.get("regionName") or state.get("name") or ""
            norm_state = normalize_geo_name(state_name)

            matched_oblast = self._name_to_oblast.get(norm_state)
            if not matched_oblast and norm_state in ("київ", "киев"):
                matched_oblast = "kyiv"
            if not matched_oblast and norm_state in (
                "крим",
                "автономна республіка крим",
                "ар крим",
            ):
                matched_oblast = "crimea"
            if not matched_oblast and state_id in DEFAULT_STATE_ID_TO_OBLAST:
                matched_oblast = DEFAULT_STATE_ID_TO_OBLAST[state_id]

            if matched_oblast:
                self.state_id_to_oblast[state_id] = matched_oblast
            else:
                # Top-level city state (e.g. Kharkiv or Zaporizhzhia city)
                matched_city = self._name_to_district.get(norm_state)
                if matched_city in CITY_ONLY_DISTRICTS:
                    self.district_id_to_district[state_id] = matched_city
                    self._map_descendants(state, matched_city)
                    continue

            children = state.get("regionChildIds") or state.get("children") or []
            for district in children:
                dist_id = str(district.get("regionId") or district.get("id") or "")
                dist_name = district.get("regionName") or district.get("name") or ""
                norm_dist = normalize_geo_name(dist_name)

                matched_dist = self._name_to_district.get(norm_dist)
                if not matched_dist and norm_dist in ("київ", "киев"):
                    matched_dist = "kyiv"

                if matched_dist:
                    self.district_id_to_district[dist_id] = matched_dist
                    self._map_descendants(district, matched_dist)
                else:
                    # District itself is not matched (e.g. suburban Kharkiv, Zaporizhzhia, Nikopol district).
                    # Check child communities for city-level match (e.g. Nikopol city)
                    for child in district.get("regionChildIds") or district.get("children") or []:
                        cid = str(child.get("regionId") or child.get("id") or "")
                        cname = child.get("regionName") or child.get("name") or ""
                        norm_child = normalize_geo_name(cname)
                        matched_child = self._name_to_district.get(norm_child)
                        if matched_child in CITY_ONLY_DISTRICTS:
                            self.community_id_to_district[cid] = matched_child
                            self._map_descendants(child, matched_child)

    def resolve_districts_for_region(
        self,
        region_id: str,
        region_type: str | None = None,
        region_name: str | None = None,
    ) -> list[str]:
        """
        Returns list of Sirens district_keys affected by this region.
        """
        reg_id_str = str(region_id)
        r_type = (region_type or "").capitalize()

        if reg_id_str in self.district_id_to_district:
            return [self.district_id_to_district[reg_id_str]]

        if reg_id_str in self.community_id_to_district:
            return [self.community_id_to_district[reg_id_str]]

        if r_type in ("State", "Oblast") or reg_id_str in self.state_id_to_oblast:
            oblast_key = None
            if region_name:
                norm_name = normalize_geo_name(region_name)
                oblast_key = self._name_to_oblast.get(norm_name)
                if not oblast_key and norm_name in ("крим", "автономна республіка крим", "ар крим"):
                    oblast_key = "crimea"
            if not oblast_key:
                oblast_key = self.state_id_to_oblast.get(reg_id_str)
            if oblast_key:
                if oblast_key == "kyiv":
                    return ["kyiv"]
                if oblast_key == "crimea":
                    return ["crimea"]
                return list(DISTRICTS_BY_OBLAST.get(oblast_key, []))

        if region_name:
            norm_name = normalize_geo_name(region_name)
            if norm_name in self._name_to_oblast:
                obl_key = self._name_to_oblast[norm_name]
                if obl_key == "kyiv":
                    return ["kyiv"]
                if obl_key == "crimea":
                    return ["crimea"]
                return list(DISTRICTS_BY_OBLAST.get(obl_key, []))

            if norm_name in self._name_to_district:
                d_key = self._name_to_district[norm_name]
                if r_type in ("Community", "Cityorvillage", "Citydistrict"):
                    self.community_id_to_district[reg_id_str] = d_key
                else:
                    self.district_id_to_district[reg_id_str] = d_key
                return [d_key]

        log.debug(
            "Could not resolve regionId %s (%s, %s) to any Sirens district",
            region_id,
            region_type,
            region_name,
        )
        return []


def parse_alert_kind_and_level(alert_dict: dict[str, Any]) -> TargetAlert | None:
    """
    Extracts alert_type and level from a single active alert dictionary.
    """
    raw_type = (alert_dict.get("type") or "AIR").upper()
    active_levels = alert_dict.get("activeAlertLevels") or []

    level: str | None = None
    for lvl_item in active_levels:
        lvl_val = (
            lvl_item.get("alertLevel")
            if isinstance(lvl_item, dict)
            else getattr(lvl_item, "alertLevel", None)
        )
        if lvl_val:
            lvl_lower = str(lvl_val).lower()
            if lvl_lower in ("red", "червоний"):
                level = "red"
                break
            if lvl_lower in ("yellow", "жовтий"):
                level = "yellow"

    if raw_type == ApiAlertKind.ARTILLERY.value:
        return TargetAlert(alert_type="threat_of_shelling", level=None)

    if raw_type in (
        ApiAlertKind.AIR.value,
        ApiAlertKind.UNKNOWN.value,
        ApiAlertKind.URBAN_FIGHTS.value,
        ApiAlertKind.CHEMICAL.value,
        ApiAlertKind.NUCLEAR.value,
        ApiAlertKind.CUSTOM.value,
    ):
        return TargetAlert(alert_type="air_raid_alert", level=level)

    return None


def extract_active_threats_by_district(
    alerts_payload: list[dict[str, Any]],
    geo_resolver: UkraineAlarmGeoResolver,
) -> dict[str, dict[str, TargetAlert]]:
    """
    Aggregates active alerts from API payload into a map:
      { district_key: { "air_raid_alert": TargetAlert(...), "threat_of_shelling": TargetAlert(...) } }
    """
    result: dict[str, dict[str, TargetAlert]] = {}

    for region_item in alerts_payload:
        region_id = region_item.get("regionId") or region_item.get("id") or ""
        region_type = region_item.get("regionType") or ""
        region_name = region_item.get("regionName") or ""
        active_alerts = region_item.get("activeAlerts") or []

        if not active_alerts:
            continue

        target_districts = geo_resolver.resolve_districts_for_region(
            region_id=str(region_id),
            region_type=str(region_type),
            region_name=region_name,
        )

        for alert_dict in active_alerts:
            target_alert = parse_alert_kind_and_level(alert_dict)
            if not target_alert:
                continue

            alert_reg_id = alert_dict.get("regionId")
            alert_reg_type = alert_dict.get("regionType")
            districts = []
            if alert_reg_id and str(alert_reg_id) != str(region_id):
                districts = geo_resolver.resolve_districts_for_region(
                    region_id=str(alert_reg_id),
                    region_type=str(alert_reg_type) if alert_reg_type else None,
                )
            if not districts:
                districts = target_districts

            for d_key in districts:
                d_threats = result.setdefault(d_key, {})
                existing = d_threats.get(target_alert.alert_type)

                if existing and existing.level == "red":
                    continue
                d_threats[target_alert.alert_type] = target_alert

    return result


def compute_alerts_diff(
    previous_state: dict[str, dict[str, TargetAlert]],
    current_state: dict[str, dict[str, TargetAlert]],
) -> tuple[list[tuple[str, TargetAlert]], list[tuple[str, str, str | None]]]:
    """
    Computes delta between previous and current active threats across all districts.

    Returns:
      to_trigger: list of (district_key, TargetAlert)
      to_cancel:  list of (district_key, cancel_event_type, previous_level)
    """
    to_trigger: list[tuple[str, TargetAlert]] = []
    to_cancel: list[tuple[str, str, str | None]] = []

    all_districts = set(previous_state) | set(current_state)

    for d_key in all_districts:
        prev_threats = previous_state.get(d_key, {})
        curr_threats = current_state.get(d_key, {})

        for alert_type, curr_alert in curr_threats.items():
            prev_alert = prev_threats.get(alert_type)
            if prev_alert is None:
                to_trigger.append((d_key, curr_alert))
            elif prev_alert.level != curr_alert.level:
                to_trigger.append((d_key, curr_alert))

        for alert_type, prev_alert in prev_threats.items():
            if alert_type not in curr_threats:
                if alert_type == "air_raid_alert":
                    to_cancel.append((d_key, "air_raid_alert_cancelled", prev_alert.level))
                elif alert_type == "threat_of_shelling":
                    to_cancel.append((d_key, "threat_of_shelling_cancelled", None))

    return to_trigger, to_cancel
