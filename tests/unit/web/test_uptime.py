"""Тести провайдера UptimeRobot.

Фікстури тут повторюють РЕАЛЬНУ форму відповіді getMonitors: помилка приїжджає
зі статусом 200 і полем stat="fail", логи лежать у monitors[].logs, а час у них
- unix-секунди. Саме на цьому провайдер найлегше обманути себе зеленим кольором.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from web import uptime
from web.status import KYIV_TZ


# --- допоміжне -------------------------------------------------------------

def _monitor(status=2, logs=None, created=None, name="sirens-web"):
    return {
        "id": 777001,
        "friendly_name": name,
        "url": "https://sirens.example",
        "status": status,
        "create_datetime": int((created or datetime.now(KYIV_TZ) - timedelta(days=10)).timestamp()),
        "logs": logs if logs is not None else [],
    }


def _log(moment, log_type):
    return {"type": log_type, "datetime": int(moment.timestamp()), "duration": 60}


def _responder(payload, status_code=200):
    def fake_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = status_code
        if status_code != 200:
            resp.raise_for_status.side_effect = RuntimeError("boom")
            return resp
        resp.json.return_value = payload
        return resp
    return fake_post


@pytest.fixture
def _web_key(monkeypatch):
    monkeypatch.setattr(uptime, "UPTIMEROBOT_SIRENS_WEB_API", "ur-web-key")


# --- налаштування ----------------------------------------------------------

def test_is_configured_needs_at_least_one_key(monkeypatch):
    assert uptime.is_configured() is False

    monkeypatch.setattr(uptime, "UPTIMEROBOT_SIRENS_API_API", "ur-api-key")
    assert uptime.is_configured() is True


def test_component_without_a_key_is_unmonitored(caplog):
    """Порожній ключ - це «моніторингу немає», а не «все добре»."""
    with caplog.at_level("WARNING"):
        probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["present"] is False
    assert probes["map"]["flips_ok"] is False
    assert probes["map"]["live"] is None
    assert "No UptimeRobot key configured" in caplog.text


def test_each_component_uses_its_own_key(monkeypatch):
    """Ключі помоніторні: переплутати «Мапу» з «API» не можна."""
    monkeypatch.setattr(uptime, "UPTIMEROBOT_SIRENS_WEB_API", "ur-web-key")
    monkeypatch.setattr(uptime, "UPTIMEROBOT_SIRENS_API_API", "ur-api-key")

    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor()]})) as mock_post:
        uptime.fetch_probes(["map", "api"], KYIV_TZ)

    sent = [call.kwargs["data"]["api_key"] for call in mock_post.call_args_list]
    assert sent == ["ur-web-key", "ur-api-key"]


def test_request_asks_for_logs_without_time_bounds(_web_key):
    """Без події ДО початку вікна неможливо знати, в якому стані його зустріли."""
    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor()]})) as mock_post:
        uptime.fetch_probes(["map"], KYIV_TZ)

    data = mock_post.call_args.kwargs["data"]
    assert data["logs"] == 1
    assert data["log_types"] == "1-2"
    assert "logs_start_date" not in data
    assert "logs_end_date" not in data


# --- розбір відповіді ------------------------------------------------------

def test_logs_become_flips_oldest_first(_web_key):
    now = datetime.now(KYIV_TZ)
    logs = [
        _log(now - timedelta(hours=1), uptime.LOG_TYPE_UP),
        _log(now - timedelta(hours=3), uptime.LOG_TYPE_DOWN),
    ]

    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor(logs=logs)]})):
        probes = uptime.fetch_probes(["map"], KYIV_TZ)

    flips = probes["map"]["flips"]
    assert [up for _moment, up in flips] == [0, 1]
    assert flips[0][0] < flips[1][0]
    assert flips[0][0].tzinfo is not None


def test_unusable_log_entries_are_skipped(_web_key):
    now = datetime.now(KYIV_TZ)
    logs = [
        _log(now - timedelta(hours=1), uptime.LOG_TYPE_DOWN),
        {"type": 99, "datetime": int(now.timestamp())},          # пауза, не падіння
        {"type": uptime.LOG_TYPE_UP, "datetime": "вчора"},   # непридатний час
        "not a dict",
    ]

    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor(logs=logs)]})):
        probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert len(probes["map"]["flips"]) == 1


@pytest.mark.parametrize("status, live", [
    (0, "mnt"),
    (1, "nodata"),
    (2, "ok"),
    (8, "minor"),
    (9, "down"),
    (42, "nodata"),
])
def test_every_monitor_status_has_a_reading(_web_key, status, live):
    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor(status=status)]})):
        probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["live"] == live


def test_history_starts_when_the_monitor_was_created(_web_key):
    created = datetime.now(KYIV_TZ) - timedelta(days=30)

    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": [_monitor(created=created)]})):
        probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["history_start"].date() == created.date()


# --- чесність замість вигаданих ста відсотків ------------------------------

def test_refused_request_stops_the_whole_pass(_web_key, caplog):
    """stat="fail" приїжджає зі статусом 200 - помітити її можна лише тут."""
    payload = {"stat": "fail", "error": {"type": "invalid_parameter", "message": "api_key is wrong"}}

    with patch("requests.post", side_effect=_responder(payload)):
        with caplog.at_level("WARNING"):
            probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["present"] is False
    assert probes["map"]["flips_ok"] is False
    assert "UptimeRobot refused the request" in caplog.text


def test_empty_monitor_list_is_unmonitored(_web_key, caplog):
    with patch("requests.post", side_effect=_responder({"stat": "ok", "monitors": []})):
        with caplog.at_level("WARNING"):
            probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["present"] is False
    assert "no monitor" in caplog.text


def test_transport_failure_is_raised_not_swallowed(_web_key):
    """Обхід має зірватись цілком, щоб refresh_status_cache не затер історію
    суцільним «немає даних»."""
    with patch("requests.post", side_effect=RuntimeError("uptimerobot down")):
        with pytest.raises(RuntimeError):
            uptime.fetch_probes(["map"], KYIV_TZ)


def test_http_error_is_raised_not_swallowed(_web_key):
    with patch("requests.post", side_effect=_responder({}, status_code=500)):
        with pytest.raises(RuntimeError):
            uptime.fetch_probes(["map"], KYIV_TZ)


def test_payload_of_an_unknown_shape_is_unmonitored(_web_key, caplog):
    with patch("requests.post", side_effect=_responder(["surprise"])):
        with caplog.at_level("WARNING"):
            probes = uptime.fetch_probes(["map"], KYIV_TZ)

    assert probes["map"]["present"] is False
