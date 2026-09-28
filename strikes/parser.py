"""
Strike report parser: cleans a channel post, asks Claude for a schema-bound
classification and resolves the extracted places onto Sirens district keys.
"""

import json
import logging
from typing import Any

import anthropic

from config import STRIKES_EFFORT, STRIKES_MODEL
from strikes.geo import region_title, resolve_location
from strikes.models import (
    RESPONSE_SCHEMA,
    Certainty,
    EventType,
    ObjectType,
    ParsedMessage,
    StrikeEvent,
    StrikeLocation,
)
from strikes.prompt import (
    EXAMPLE_REQUEST,
    EXAMPLE_RESPONSE,
    SYSTEM_PROMPT,
    build_user_message,
)
from strikes.text import clean_message, looks_like_strike

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000


class StrikeParserError(RuntimeError):
    """The model did not return a usable classification."""


def _event_from_dict(data: dict[str, Any], region_hint: str | None) -> StrikeEvent:
    loc = data["location"]
    location = StrikeLocation(
        oblast=loc.get("oblast"),
        raion=loc.get("raion"),
        hromada=loc.get("hromada"),
        settlement=loc.get("settlement"),
        city_district=loc.get("city_district"),
        address=loc.get("address"),
        inferred_from_context=bool(loc.get("inferred_from_context")),
    )
    return StrikeEvent(
        event_type=EventType(data["event_type"]),
        certainty=Certainty(data["certainty"]),
        repeated=bool(data["repeated"]),
        object_type=ObjectType(data["object_type"]),
        object_description=data.get("object_description"),
        location=resolve_location(location, region_hint),
        killed=data.get("killed"),
        injured=data.get("injured"),
        quote=data.get("quote") or "",
    )


class StrikeParser:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = STRIKES_MODEL,
        effort: str = STRIKES_EFFORT,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def _request(self, text: str, region_hint: str | None) -> dict[str, Any]:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            cache_control={"type": "ephemeral"},
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": EXAMPLE_REQUEST},
                {"role": "assistant", "content": EXAMPLE_RESPONSE},
                {"role": "user", "content": build_user_message(text, region_title(region_hint))},
            ],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise StrikeParserError(f"model refused: {getattr(details, 'category', None)}")
        if response.stop_reason == "max_tokens":
            raise StrikeParserError("model output was cut at max_tokens")
        body = next((block.text for block in response.content if block.type == "text"), None)
        if body is None:
            raise StrikeParserError(f"no text block, stop_reason={response.stop_reason}")
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise StrikeParserError(f"invalid JSON from model: {exc}") from exc

    def parse(self, text: str, region_hint: str | None = None) -> ParsedMessage:
        """Classifies one post. `region_hint` is the district/oblast key the channel covers."""
        cleaned = clean_message(text)
        if not cleaned or not looks_like_strike(cleaned):
            return ParsedMessage(text=cleaned, is_strike_report=False)

        data = self._request(cleaned, region_hint)
        try:
            events = tuple(_event_from_dict(event, region_hint) for event in data["events"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StrikeParserError(f"response does not match schema: {exc}") from exc

        is_report = bool(data.get("is_strike_report")) and bool(events)
        return ParsedMessage(text=cleaned, is_strike_report=is_report, events=events)
