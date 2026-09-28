import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from strikes import (
    Certainty,
    EventType,
    ObjectType,
    StrikeLocation,
    StrikeParser,
    StrikeParserError,
    clean_message,
    looks_like_strike,
    resolve_location,
)
from strikes.models import RESPONSE_SCHEMA
from strikes.prompt import EXAMPLE_RESPONSE

KYIV_POST = (
    "Повторне влучання в нежитлову будівлю в Оболонському районі. \n\n"
    "Також, попередньо, влучання в Соломʼянському районі. Нежитлова будівля.\n"
    "ㅤ \n"
    "Надіслати новину @novosti_kieva_bot\n"
    "👉ПІДПИСАТИСЯ"
)


def _location(**overrides):
    base = {
        "oblast": None,
        "raion": None,
        "hromada": None,
        "settlement": None,
        "city_district": None,
        "address": None,
        "inferred_from_context": False,
    }
    return {**base, **overrides}


def _event(**overrides):
    base = {
        "event_type": "hit",
        "certainty": "confirmed",
        "repeated": False,
        "object_type": "unknown",
        "object_description": None,
        "location": _location(),
        "killed": None,
        "injured": None,
        "quote": "",
    }
    return {**base, **overrides}


def _client(payload, stop_reason="end_turn"):
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    response = SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=None,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=body),
        ],
    )
    client = MagicMock()
    client.beta.messages.create.return_value = response
    return client


def test_clean_message_drops_promo_and_fillers():
    cleaned = clean_message(KYIV_POST)
    assert cleaned == (
        "Повторне влучання в нежитлову будівлю в Оболонському районі.\n"
        "Також, попередньо, влучання в Солом'янському районі. Нежитлова будівля."
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        (KYIV_POST, True),
        ("Падіння уламків на Троєщині", True),
        ("🔴 Повітряна тривога в м. Київ", False),
        ("Відбій тривоги. Гарного вечора!", False),
    ],
)
def test_looks_like_strike(text, expected):
    assert looks_like_strike(text) is expected


def test_parse_kyiv_post_two_typed_events():
    parser = StrikeParser(client=_client(EXAMPLE_RESPONSE), model="m", effort="low")
    result = parser.parse(KYIV_POST, region_hint="kyiv")

    assert result.is_strike_report
    first, second = result.events

    assert first.event_type is EventType.HIT
    assert first.certainty is Certainty.CONFIRMED
    assert first.repeated is True
    assert first.object_type is ObjectType.NON_RESIDENTIAL
    assert first.location.city_district == "Оболонський район"
    assert first.location.district_key == "kyiv"
    assert first.location.oblast_key == "kyiv"

    assert second.certainty is Certainty.PRELIMINARY
    assert second.repeated is False
    assert second.location.city_district == "Солом'янський район"
    assert second.location.district_key == "kyiv"


def test_parse_sends_schema_bound_request():
    client = _client({"is_strike_report": False, "events": []})
    StrikeParser(client=client, model="m", effort="low").parse(KYIV_POST, region_hint="kyiv")

    kwargs = client.beta.messages.create.call_args.kwargs
    assert kwargs["model"] == "m"
    assert kwargs["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
    }
    assert kwargs["fallbacks"] == "default"
    last = kwargs["messages"][-1]
    assert last["role"] == "user"
    assert "м. Київ" in last["content"]
    assert "ПІДПИСАТИСЯ" not in last["content"]


def test_parse_skips_model_for_non_strike_posts():
    client = _client({"is_strike_report": False, "events": []})
    result = StrikeParser(client=client).parse("🟢 Відбій тривоги в м. Київ")
    assert not result.is_strike_report
    assert result.events == ()
    client.beta.messages.create.assert_not_called()


def test_parse_report_without_events_is_not_a_report():
    client = _client({"is_strike_report": True, "events": []})
    assert not StrikeParser(client=client).parse("Вибухи в Києві").is_strike_report


@pytest.mark.parametrize(
    "payload, stop_reason",
    [
        ({"is_strike_report": True, "events": []}, "refusal"),
        ({"is_strike_report": True, "events": []}, "max_tokens"),
        ("not json", "end_turn"),
        ({"is_strike_report": True, "events": [_event(event_type="nuke")]}, "end_turn"),
    ],
)
def test_parse_raises_on_unusable_response(payload, stop_reason):
    parser = StrikeParser(client=_client(payload, stop_reason))
    with pytest.raises(StrikeParserError):
        parser.parse("Влучання в Харкові")


@pytest.mark.parametrize(
    "location, hint, district, oblast",
    [
        (StrikeLocation(settlement="Харків"), None, "kharkiv", "kharkiv_oblast"),
        (
            StrikeLocation(settlement="Бровари", raion="Броварський район"),
            None,
            "brovary",
            "kyiv_oblast",
        ),
        (StrikeLocation(settlement="Одеса", raion="Одеський район"), None, "odesa", "odesa_oblast"),
        (StrikeLocation(oblast="Сумська область"), None, None, "sumy_oblast"),
        (StrikeLocation(city_district="Дніпровський район"), "kyiv", "kyiv", "kyiv"),
        (StrikeLocation(settlement="Нікополь"), "kyiv", "nikopol", "dnipropetrovsk_oblast"),
        (StrikeLocation(oblast="Львівська область"), "kyiv", None, "lviv_oblast"),
        (StrikeLocation(), "kharkiv_oblast", None, "kharkiv_oblast"),
    ],
)
def test_resolve_location(location, hint, district, oblast):
    resolved = resolve_location(location, hint)
    assert resolved.district_key == district
    assert resolved.oblast_key == oblast


def test_resolve_location_canonicalises_kyiv_city_district():
    resolved = resolve_location(StrikeLocation(settlement="Київ", city_district="Соломʼянський"))
    assert resolved.city_district == "Солом'янський район"


def test_parsed_message_serialises_to_json():
    result = StrikeParser(client=_client(EXAMPLE_RESPONSE)).parse(KYIV_POST, "kyiv")
    dumped = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    assert dumped["events"][0]["event_type"] == "hit"
    assert dumped["events"][1]["location"]["district_key"] == "kyiv"


def test_cli_prints_parsed_json(mocker):
    from click.testing import CliRunner

    from strikes.__main__ import main

    mocker.patch("strikes.parser.anthropic.Anthropic", return_value=_client(EXAMPLE_RESPONSE))
    result = CliRunner().invoke(main, ["--region", "kyiv"], input=KYIV_POST)

    assert result.exit_code == 0, result.output
    dumped = json.loads(result.output)
    assert [e["location"]["city_district"] for e in dumped["events"]] == [
        "Оболонський район",
        "Солом'янський район",
    ]
