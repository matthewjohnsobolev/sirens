"""
Maps the place names the model extracted onto Sirens district and oblast keys.
"""

from dataclasses import replace

from domain.geo import DISTRICT_CONFIG, OBLAST_NAMES
from domain.ukraine_alarm import normalize_geo_name
from strikes.models import StrikeLocation

KYIV_CITY_DISTRICTS = (
    "Голосіївський район",
    "Дарницький район",
    "Деснянський район",
    "Дніпровський район",
    "Оболонський район",
    "Печерський район",
    "Подільський район",
    "Святошинський район",
    "Солом'янський район",
    "Шевченківський район",
)

CITY_OBLASTS = {"kyiv", "sevastopol"}


def _norm(name: str | None) -> str:
    return normalize_geo_name((name or "").replace("ʼ", "'"))


_TRIGGER_INDEX: dict[str, list[str]] = {}
for _key, _conf in DISTRICT_CONFIG.items():
    for _trigger in _conf["triggers"]:
        _keys = _TRIGGER_INDEX.setdefault(_norm(_trigger), [])
        if _key not in _keys:
            _keys.append(_key)

_OBLAST_INDEX = {_norm(name): key for key, name in OBLAST_NAMES.items()}
_KYIV_DISTRICT_INDEX = {_norm(name): name for name in KYIV_CITY_DISTRICTS}


def region_title(key: str | None) -> str | None:
    """Human name for a district or oblast key, used as a hint in the prompt."""
    if not key:
        return None
    if key in DISTRICT_CONFIG:
        return DISTRICT_CONFIG[key]["name"]
    return OBLAST_NAMES.get(key)


def _oblast_of(key: str) -> str:
    return DISTRICT_CONFIG[key]["oblast"]


def _match(name: str | None, oblast_key: str | None) -> str | None:
    candidates = _TRIGGER_INDEX.get(_norm(name), [])
    if oblast_key:
        candidates = [key for key in candidates if _oblast_of(key) == oblast_key] or candidates
    return candidates[0] if candidates else None


def resolve_location(location: StrikeLocation, region_hint: str | None = None) -> StrikeLocation:
    """Fills `district_key` / `oblast_key`: settlement first, then raion, then hromada.

    `region_hint` is the district or oblast key the source channel covers; it only
    decides when the text itself names nothing resolvable.
    """
    oblast_key = _OBLAST_INDEX.get(_norm(location.oblast))
    district_key = None
    for name in (location.settlement, location.raion, location.hromada):
        district_key = _match(name, oblast_key)
        if district_key:
            break

    if district_key is None and region_hint:
        if region_hint in DISTRICT_CONFIG:
            hinted_oblast = _oblast_of(region_hint)
            if oblast_key in (None, hinted_oblast):
                district_key = region_hint
        elif oblast_key is None:
            oblast_key = region_hint if region_hint in OBLAST_NAMES else None

    if district_key:
        oblast_key = _oblast_of(district_key)

    city_district = location.city_district
    if district_key == "kyiv" and city_district:
        city_district = _KYIV_DISTRICT_INDEX.get(_norm(city_district), city_district)

    return replace(
        location,
        city_district=city_district,
        district_key=district_key,
        oblast_key=oblast_key,
    )
