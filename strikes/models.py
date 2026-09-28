"""
Typed result of parsing a strike report: what happened, how sure the source is, and where.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum


class EventType(str, Enum):
    HIT = "hit"
    DEBRIS = "debris"
    EXPLOSION = "explosion"
    FIRE = "fire"
    INTERCEPTION = "interception"
    OTHER = "other"


class Certainty(str, Enum):
    CONFIRMED = "confirmed"
    PRELIMINARY = "preliminary"
    UNCONFIRMED = "unconfirmed"


class ObjectType(str, Enum):
    RESIDENTIAL = "residential"
    NON_RESIDENTIAL = "non_residential"
    INFRASTRUCTURE = "infrastructure"
    ENERGY = "energy"
    INDUSTRIAL = "industrial"
    TRANSPORT = "transport"
    EDUCATIONAL = "educational"
    MEDICAL = "medical"
    VEHICLE = "vehicle"
    OPEN_AREA = "open_area"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StrikeLocation:
    oblast: str | None = None
    raion: str | None = None
    hromada: str | None = None
    settlement: str | None = None
    city_district: str | None = None
    address: str | None = None
    inferred_from_context: bool = False
    district_key: str | None = None
    oblast_key: str | None = None


@dataclass(frozen=True)
class StrikeEvent:
    event_type: EventType
    certainty: Certainty
    repeated: bool
    object_type: ObjectType
    location: StrikeLocation
    object_description: str | None = None
    killed: int | None = None
    injured: int | None = None
    quote: str = ""


@dataclass(frozen=True)
class ParsedMessage:
    text: str
    is_strike_report: bool
    events: tuple[StrikeEvent, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_INT = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _enum(cls: type[Enum]) -> dict:
    return {"type": "string", "enum": [member.value for member in cls]}


def _object(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


LOCATION_SCHEMA = _object(
    {
        "oblast": _NULLABLE_STRING,
        "raion": _NULLABLE_STRING,
        "hromada": _NULLABLE_STRING,
        "settlement": _NULLABLE_STRING,
        "city_district": _NULLABLE_STRING,
        "address": _NULLABLE_STRING,
        "inferred_from_context": {"type": "boolean"},
    }
)

EVENT_SCHEMA = _object(
    {
        "event_type": _enum(EventType),
        "certainty": _enum(Certainty),
        "repeated": {"type": "boolean"},
        "object_type": _enum(ObjectType),
        "object_description": _NULLABLE_STRING,
        "location": LOCATION_SCHEMA,
        "killed": _NULLABLE_INT,
        "injured": _NULLABLE_INT,
        "quote": {"type": "string"},
    }
)

RESPONSE_SCHEMA = _object(
    {
        "is_strike_report": {"type": "boolean"},
        "events": {"type": "array", "items": EVENT_SCHEMA},
    }
)
