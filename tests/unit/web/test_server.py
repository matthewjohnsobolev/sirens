import json
import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import request
from sentry_sdk.integrations.flask import FlaskIntegration

from config import VERSION
from domain import BROADCAST_CITIES, BROADCAST_DISTRICTS
from web import issue
from web import server as web_server
from web.server import create_app

SUCCESS_MARKER = "Повідомлення надіслано"


def test_index_route(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-cache, must-revalidate"


def test_api_route(client):
    payload = {"kyiv": {"alert": {"status": True}}}
    with patch("web.server.get_all_threats_data", return_value=payload) as mock_data:
        response = client.get("/api")

    assert response.status_code == 200
    assert response.json == payload
    assert response.headers.get("Cache-Control") == "public, max-age=2, s-maxage=2"
    mock_data.assert_called_once_with()


def test_static_caching_header(client):
    response = client.get("/static/ukraine.geojson")
    if response.status_code == 200:
        assert response.headers.get("Cache-Control") == "public, max-age=2592000, immutable"


def test_stats_csv_route_not_found(client):
    assert client.get("/bi/stats.csv").status_code == 404


def test_status_route_redirects_to_status_subdomain(client):
    response = client.get("/status")
    assert response.status_code == 301
    assert response.headers.get("Location") == "https://status.sirens.live"


def test_issue_footer_contains_status_link_and_disclaimer(client):
    html = client.get("/issue").get_data(as_text=True)
    assert "https://status.sirens.live" in html
    assert "Стан системи" in html
    assert "Мапа тривог" in html
    assert "«Сирени» — незалежний сервіс агрегації тривог." in html
    assert "© 2026 «Сирени»" in html


def test_index_versions_every_stylesheet_and_script(client):
    """Static assets are cached with immutable headers, requiring URL version hashes."""
    html = client.get("/").get_data(as_text=True)

    assets = re.findall(r'(?:href|src)="(/static/(?:css|js)/[^"]+)"', html)
    assert assets, "no css/js assets found on the page"
    unversioned = [a for a in assets if "?v=" not in a]
    assert unversioned == [], f"unversioned assets: {unversioned}"


def test_static_url_fingerprint_follows_the_file_contents(app, tmp_path):
    from web.server import _static_fingerprint, static_url

    _static_fingerprint.cache_clear()
    asset = tmp_path / "probe.css"
    asset.write_text("a{}")

    with app.test_request_context():
        first = static_url("css/main.css")
        assert first == static_url("css/main.css")

    assert _static_fingerprint(str(tmp_path), "probe.css") != _static_fingerprint(
        str(tmp_path), "missing.css"
    )

    before = _static_fingerprint(str(tmp_path), "probe.css")
    asset.write_text("a{color:red}")
    _static_fingerprint.cache_clear()
    assert _static_fingerprint(str(tmp_path), "probe.css") != before


def test_static_url_falls_back_to_the_release_when_the_file_is_gone(app, caplog):
    from web.server import _static_fingerprint, static_url

    _static_fingerprint.cache_clear()
    caplog.set_level(logging.WARNING)

    with app.test_request_context():
        assert f"v={VERSION}" in static_url("css/does-not-exist.css")

    assert "does-not-exist.css" in caplog.text


def test_schema_is_created_on_first_request_only():
    with patch("web.server.ensure_pg_tables") as mock_ensure:
        flask_app = create_app(init_db=True)
        mock_ensure.assert_not_called()

        test_client = flask_app.test_client()
        test_client.get("/")
        test_client.get("/")

        mock_ensure.assert_called_once_with()


def test_app_can_be_built_without_schema_bootstrap():
    with patch("web.server.ensure_pg_tables") as mock_ensure:
        flask_app = create_app(init_db=False)
        flask_app.test_client().get("/")

    mock_ensure.assert_not_called()


def test_create_app_initializes_sentry_with_flask_integration(monkeypatch):
    monkeypatch.setattr(web_server, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    with patch("web.server.sentry_sdk.init") as mock_sentry_init:
        create_app(init_db=False, start_healthcheck=False)

    mock_sentry_init.assert_called_once()
    _, kwargs = mock_sentry_init.call_args
    assert kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
    assert kwargs["send_default_pii"] is False
    assert kwargs["release"] == VERSION
    assert any(isinstance(i, FlaskIntegration) for i in kwargs["integrations"])


def test_create_app_tags_events_with_its_service_name(monkeypatch):
    monkeypatch.setattr(web_server, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    with (
        patch("web.server.sentry_sdk.init"),
        patch("web.server.sentry_sdk.set_tag") as mock_set_tag,
    ):
        create_app(init_db=False, start_healthcheck=False)

    mock_set_tag.assert_called_once_with("service", "web")


def test_ping_healthcheck_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "")

    with patch("web.server.requests.get") as mock_get:
        web_server._ping_healthcheck()

    mock_get.assert_not_called()


def test_ping_healthcheck_sends_get_with_suffix(monkeypatch):
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "https://hc-ping.com/test-uuid")

    with patch("web.server.requests.get") as mock_get:
        web_server._ping_healthcheck("/fail")

    mock_get.assert_called_once_with(
        "https://hc-ping.com/test-uuid/fail", timeout=web_server.HEALTHCHECK_PING_TIMEOUT
    )


def test_ping_healthcheck_logs_but_survives_request_failure(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "https://hc-ping.com/test-uuid")

    with patch("web.server.requests.get", side_effect=Exception("network down")):
        web_server._ping_healthcheck()

    assert "Failed to ping healthchecks.io" in caplog.text


def test_claim_ping_slot_uses_atomic_set():
    """gunicorn runs several workers, each with its own ping thread, so the slot
    is claimed with an atomic SET NX EX rather than a read-then-write."""
    with patch("web.server.redis_client") as mock_redis:
        mock_redis.set.return_value = True

        assert web_server._claim_ping_slot() is True

    _, kwargs = mock_redis.set.call_args
    assert kwargs["nx"] is True
    assert kwargs["ex"] == web_server.HEALTHCHECK_LOCK_TTL
    assert web_server.HEALTHCHECK_LOCK_TTL < web_server.HEALTHCHECK_PING_INTERVAL


def test_claim_ping_slot_false_when_another_worker_holds_it():
    with patch("web.server.redis_client") as mock_redis:
        mock_redis.set.return_value = None

        assert web_server._claim_ping_slot() is False


def test_healthcheck_loop_pings_after_each_sleep():
    with (
        patch("web.server.time.sleep", side_effect=[None, StopIteration]) as mock_sleep,
        patch("web.server._claim_ping_slot", return_value=True),
        patch("web.server._ping_healthcheck") as mock_ping,
    ):
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    assert mock_sleep.call_count == 2
    mock_ping.assert_called_once_with()


def test_healthcheck_loop_skips_ping_when_slot_already_taken():
    with (
        patch("web.server.time.sleep", side_effect=[None, StopIteration]),
        patch("web.server._claim_ping_slot", return_value=False),
        patch("web.server._ping_healthcheck") as mock_ping,
    ):
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    mock_ping.assert_not_called()


def test_healthcheck_loop_withholds_ping_when_redis_is_down(caplog):
    """Redis down means /api can serve nothing, so withholding the ping is the
    point: healthchecks.io must go red instead of staying falsely green."""
    caplog.set_level(logging.WARNING)

    with (
        patch("web.server.time.sleep", side_effect=[None, StopIteration]),
        patch("web.server._claim_ping_slot", side_effect=ConnectionError("redis down")),
        patch("web.server._ping_healthcheck") as mock_ping,
    ):
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    mock_ping.assert_not_called()
    assert "Redis unreachable" in caplog.text


def test_create_app_starts_healthcheck_thread_when_configured(monkeypatch):
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "https://hc-ping.com/test-uuid")

    with patch("web.server.threading.Thread") as MockThread:
        create_app(init_db=False, start_healthcheck=True)

    MockThread.assert_called_once()
    _, kwargs = MockThread.call_args
    assert kwargs["daemon"] is True
    MockThread.return_value.start.assert_called_once()


def test_create_app_skips_healthcheck_thread_when_unconfigured(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "")

    with patch("web.server.threading.Thread") as MockThread:
        create_app(init_db=False, start_healthcheck=True)

    MockThread.assert_not_called()
    assert "HEALTHCHECKS_WEB_PING_URL not set" in caplog.text


def test_create_app_skips_healthcheck_thread_when_disabled(monkeypatch):
    monkeypatch.setattr(web_server, "HEALTHCHECKS_WEB_PING_URL", "https://hc-ping.com/test-uuid")

    with patch("web.server.threading.Thread") as MockThread:
        create_app(init_db=False, start_healthcheck=False)

    MockThread.assert_not_called()



def test_unknown_url_renders_the_branded_404_page(client):
    response = client.get("/no-such-page")
    body = response.get_data(as_text=True)

    assert response.status_code == 404
    assert "404" in body
    assert "Сторінку не знайдено" in body


def test_error_page_offers_a_way_to_return_home(client):
    body = client.get("/no-such-page").get_data(as_text=True)

    assert "На головну" in body
    assert 'href="/"' in body


def test_unhandled_exception_renders_the_500_page():
    """TESTING=True re-raises instead of rendering, so the handler needs a
    plain app to run against."""
    flask_app = create_app(init_db=False, start_healthcheck=False)

    @flask_app.route("/boom")
    def boom():
        raise RuntimeError("kaboom")

    response = flask_app.test_client().get("/boom")

    assert response.status_code == 500
    assert "500" in response.get_data(as_text=True)
    assert "Щось зламалось у нас" in response.get_data(as_text=True)
    assert "На головну" in response.get_data(as_text=True)


VALID_REPORT = {
    "category": "Сповіщення",
    "sub_option": "Сповіщення прийшло із запізненням",
    "time": "Щойно",
    "city": "Київ",
    "district": "",
    "message": "Сирена о 3:00 прийшла на 10 хвилин пізніше",
    "contact": "@reporter",
}


@pytest.fixture
def report_deps():
    """Both things a submission touches: the rate limiter and the only sink."""
    with (
        patch("web.server._claim_report_slot", return_value=True),
        patch("web.server._report_to_sentry", return_value=True) as mock_report,
    ):
        yield mock_report


def sent_report(mock_report):
    """Extracts the report payload sent to Sentry."""
    return mock_report.call_args.args[0]


def test_report_form_is_served(client):
    response = client.get("/issue")

    assert response.status_code == 200
    assert "Повідомити про збій" in response.get_data(as_text=True)


def test_report_form_carries_the_taxonomy_the_server_checks_against(client):
    """The page renders using the same option definitions that the server validates against."""
    html = client.get("/issue").get_data(as_text=True)
    config = json.loads(
        re.search(
            r'<script type="application/json" id="report-config">(.*?)</script>', html, re.S
        ).group(1)
    )

    assert config["categories"] == {c["id"]: c["name"] for c in issue.CATEGORIES}
    assert config["sets"] == {c["id"]: [o["name"] for o in c["options"]] for c in issue.CATEGORIES}
    assert config["cities"] == list(issue.CITIES)
    assert config["districts"] == list(issue.DISTRICTS)
    assert config["time_options"] == list(issue.TIME_NAMES)


def test_report_form_keeps_the_sentry_vocabulary_off_the_page(client):
    """Internal keys and English labels are kept out of the frontend page bundle."""
    html = client.get("/issue").get_data(as_text=True)
    config = json.loads(
        re.search(
            r'<script type="application/json" id="report-config">(.*?)</script>', html, re.S
        ).group(1)
    )

    dumped = json.dumps(config, ensure_ascii=False)
    assert "Notification arrived late" not in dumped
    assert "never_arrived" not in dumped


def test_report_form_suggests_every_city_with_a_channel(client):
    """City suggestions match the set of cities that receive broadcast alerts."""
    html = client.get("/issue").get_data(as_text=True)
    config = json.loads(
        re.search(
            r'<script type="application/json" id="report-config">(.*?)</script>', html, re.S
        ).group(1)
    )

    assert set(config["cities"]) == set(BROADCAST_CITIES.values())
    assert len(config["cities"]) == len(BROADCAST_DISTRICTS)
    assert "Харків" in config["cities"] and "Звенигородка" in config["cities"]


def test_report_form_suggests_districts(client):
    """District suggestions contain all configured districts."""
    html = client.get("/issue").get_data(as_text=True)
    config = json.loads(
        re.search(
            r'<script type="application/json" id="report-config">(.*?)</script>', html, re.S
        ).group(1)
    )

    assert "Бучанський район" in config["districts"]
    assert "Харківський район" in config["districts"]


def test_report_form_keeps_three_tabs(client):
    """The section switcher contains exactly three tabs for layout consistency."""
    html = client.get("/issue").get_data(as_text=True)

    assert len(re.findall(r'role="radio"', html)) == 3


def test_form_fields_are_named_the_way_the_server_reads_them(client, app):
    """Form input names match the keys expected by the server handler."""
    html = client.get("/issue").get_data(as_text=True)

    assert 'name="message"' in html and 'name="contact"' in html
    assert 'name="exact_date"' in html and 'name="exact_time"' in html
    assert 'name="comment"' not in html and 'name="tg"' not in html
    assert 'maxlength="1000"' in html

    js = (Path(app.static_folder) / "js" / "issue.js").read_text(encoding="utf-8")
    assert "formData.append('message'" in js
    assert "formData.append('contact'" in js
    assert "formData.append('exact_date'" in js
    assert "formData.append('exact_time'" in js


def test_the_page_travels_time_as_its_own_field(app):
    """The frontend transmits time as a distinct form field."""
    js = (Path(app.static_folder) / "js" / "issue.js").read_text(encoding="utf-8")

    assert "formData.append('time', chosenTime)" in js


def test_report_notice_shows_one_icon_at_a_time(app):
    """Notice status indicators display one icon state at a time."""
    css = (Path(app.static_folder) / "css" / "issue.css").read_text(encoding="utf-8")
    icon_rule = re.search(r"\.notice-icon img\{([^}]*)\}", css).group(1)

    assert "display" not in icon_rule
    assert ".notice-icon-error{display:none}" in css
    assert ".notice--error .notice-icon-error{display:block}" in css


def test_report_notice_icon_keeps_the_popup_proportion(app):
    """Notice icon dimensions match the expected proportions."""
    css = (Path(app.static_folder) / "css" / "issue.css").read_text(encoding="utf-8")
    popup = (Path(app.static_folder) / "css" / "oblasts.css").read_text(encoding="utf-8")

    pill = int(re.search(r"--control-h:(\d+)px", css).group(1))
    popup_pill = int(
        re.search(r"\.green-oblast-button\s*\{[^}]*?height:\s*(\d+)px", popup, re.S).group(1)
    )
    popup_icon = int(re.search(r"\.icon\s*\{[^}]*?height:\s*(\d+)px", popup, re.S).group(1))

    assert f".notice-icon img{{width:{pill * popup_icon // popup_pill}px" in css
    html = app.test_client().get("/issue").get_data(as_text=True)
    assert html.count('width="24" height="24"') == 2


def test_report_form_versions_every_stylesheet_and_script(client):
    """Issue form stylesheets and scripts include version parameters."""
    html = client.get("/issue").get_data(as_text=True)

    assets = re.findall(r'(?:href|src)="(/static/(?:css|js)/[^"]+)"', html)
    assert assets, "no css/js assets found on the page"
    assert [a for a in assets if "?v=" not in a] == []


def test_valid_report_reaches_sentry_and_is_confirmed(client, report_deps):
    response = client.post("/issue", data=VALID_REPORT)

    assert response.status_code == 200
    assert 'class="sent"' in response.get_data(as_text=True)
    assert sent_report(report_deps) == {
        "category": "Сповіщення",
        "sub_option": "Сповіщення прийшло із запізненням",
        "time": "Щойно",
        "city": "Київ",
        "district": "",
        "message": "Сирена о 3:00 прийшла на 10 хвилин пізніше",
        "contact": "@reporter",
    }


def test_only_a_sent_report_gets_the_sent_class(client):
    """The sent CSS class is applied only upon a successful submission."""
    page = client.get("/issue").get_data(as_text=True)

    assert SUCCESS_MARKER in page
    assert 'class="sent"' not in page


def test_report_normalizes_the_short_tab_label(client, report_deps):
    """Normalizes tab label aliases into full category names."""
    response = client.post(
        "/issue",
        data={
            "category": "Мапа",
            "sub_option": "Мапа не відкривається зовсім",
            "time": "Щойно",
            "district": "Харківський район",
            "message": "Зависла сирена",
            "contact": "@user",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["category"] == "Мапа тривог"
    assert sent_report(report_deps)["district"] == "Харківський район"


def test_report_keeps_only_the_options_its_own_form_offers(client, report_deps):
    """Rejects options that belong to a different category."""
    response = client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "sub_option": "Область не підсвічена, хоча тривога є",
        },
    )

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_report_ignores_the_sub_option_of_a_category_without_options(client, report_deps):
    """Ignores sub-options submitted for the catch-all category."""
    client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "category": "Інше",
            "sub_option": "Сповіщення не прийшло взагалі",
        },
    )

    assert sent_report(report_deps)["sub_option"] == ""


def test_report_without_a_city_is_rejected(client, report_deps):
    response = client.post("/issue", data={**VALID_REPORT, "city": ""})

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_report_map_without_a_district_is_rejected(client, report_deps):
    response = client.post(
        "/issue",
        data={
            "category": "Мапа",
            "sub_option": "Мапа не відкривається зовсім",
            "time": "Щойно",
            "district": "",
            "city": "",
            "message": "Не відкривається",
            "contact": "",
        },
    )

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_report_without_time_is_rejected_for_alerts_and_map(client, report_deps):
    response = client.post("/issue", data={**VALID_REPORT, "time": ""})

    assert response.status_code == 400
    report_deps.assert_not_called()

    response_map = client.post(
        "/issue",
        data={
            "category": "Мапа",
            "sub_option": "Мапа не відкривається зовсім",
            "time": "",
            "district": "Бучанський район",
            "message": "",
            "contact": "",
        },
    )
    assert response_map.status_code == 400
    report_deps.assert_not_called()


def test_other_category_needs_a_description(client, report_deps):
    response = client.post("/issue", data={**VALID_REPORT, "category": "Інше", "message": ""})

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_other_category_without_city_and_time_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            "category": "Інше",
            "city": "",
            "district": "",
            "time": "",
            "message": "Щось сталося на сайті",
            "contact": "@tester",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps) == {
        "category": "Інше",
        "sub_option": "",
        "time": "",
        "city": "",
        "district": "",
        "message": "Щось сталося на сайті",
        "contact": "@tester",
    }


def test_time_travels_as_its_own_field(client, report_deps):
    response = client.post(
        "/issue",
        data={
            "category": "Сповіщення",
            "sub_option": "Сповіщення прийшло із запізненням",
            "time": "Менше години тому",
            "city": "Київ",
            "message": "",
            "contact": "",
        },
    )

    assert response.status_code == 200
    report = sent_report(report_deps)
    assert report["sub_option"] == "Сповіщення прийшло із запізненням"
    assert report["time"] == "Менше години тому"


def test_exact_time_selection_without_value_is_rejected(client, report_deps):
    report, error = web_server._clean_report_form(
        {
            **VALID_REPORT,
            "time": "Вибрати дату і час",
            "exact_time": "",
        }
    )
    assert error == "Вкажіть, будь ласка, дату і час."

    response = client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "time": "Вибрати дату і час",
            "exact_time": "",
        },
    )

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_exact_time_selection_with_value_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "time": "Вибрати дату і час",
            "exact_time": "12:45",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["time"] == "12:45"


def test_exact_date_and_time_selection_with_both_values_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "time": "Вибрати дату і час",
            "exact_date": "2026-08-23",
            "exact_time": "12:45",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["time"] == "2026-08-23 12:45"


def test_exact_date_only_selection_with_value_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            **VALID_REPORT,
            "time": "Вибрати дату і час",
            "exact_date": "2026-08-23",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["time"] == "2026-08-23"


def test_custom_time_format_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            "category": "Сповіщення",
            "sub_option": "Сповіщення прийшло із запізненням",
            "time": "14:30",
            "city": "Київ",
            "message": "",
            "contact": "",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["time"] == "14:30"


def test_custom_datetime_format_with_date_is_accepted(client, report_deps):
    response = client.post(
        "/issue",
        data={
            "category": "Сповіщення",
            "sub_option": "Сповіщення прийшло із запізненням",
            "time": "23 серп. 23:56",
            "city": "Київ",
            "message": "",
            "contact": "",
        },
    )

    assert response.status_code == 200
    assert sent_report(report_deps)["time"] == "23 серп. 23:56"


def test_time_outside_the_vocabulary_is_rejected(client, report_deps):
    response = client.post("/issue", data={**VALID_REPORT, "time": "3 доби"})

    assert response.status_code == 400
    report_deps.assert_not_called()


def test_unknown_category_is_rejected(client, report_deps):
    response = client.post("/issue", data={**VALID_REPORT, "category": "Хакер"})

    assert response.status_code == 400
    report_deps.assert_not_called()


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"city": ""}, "Будь ласка, вкажіть місто."),
        ({"time": ""}, "Оберіть, будь ласка, коли це сталося."),
        (
            {
                "category": "Мапа",
                "sub_option": "Мапа не відкривається зовсім",
                "city": "",
                "district": "",
            },
            "Будь ласка, вкажіть район.",
        ),
        ({"category": "Інше", "message": ""}, "Опис помилки обовʼязковий для цієї категорії."),
        ({"category": "Хакер"}, "Оберіть категорію помилки."),
        ({"sub_option": "Щось своє"}, "Оберіть, будь ласка, що саме сталося."),
        ({"time": "3 доби"}, "Оберіть, будь ласка, коли це сталося."),
        ({"message": "я" * 1001}, "Коментар не може бути довшим за 1000 символів."),
    ],
)
def test_rejection_messages(app, overrides, expected):
    """The wording lives in the validator, not the page: the form renders only
    its own client-side errors."""
    with app.test_request_context("/issue", method="POST", data={**VALID_REPORT, **overrides}):
        report, error = web_server._clean_report_form(request.form)

    assert report == {}
    assert error == expected


def test_overlong_fields_are_truncated_to_the_event_budget(client, report_deps):
    client.post(
        "/issue", data={**VALID_REPORT, "contact": "@" + "я" * 500, "city": "Київ" + "я" * 500}
    )

    report = sent_report(report_deps)
    assert len(report["contact"]) == web_server.REPORT_FIELD_LIMITS["contact"]
    assert len(report["city"]) == web_server.REPORT_FIELD_LIMITS["city"]


def test_report_is_refused_once_the_client_runs_out_of_slots(client):
    with (
        patch("web.server._claim_report_slot", return_value=False),
        patch("web.server._report_to_sentry") as mock_report,
    ):
        response = client.post("/issue", data=VALID_REPORT)

    assert response.status_code == 429
    assert "Забагато повідомлень" in response.get_data(as_text=True)
    mock_report.assert_not_called()


def test_a_report_that_did_not_get_through_is_not_called_sent(client):
    """Returns HTTP 503 when Sentry delivery fails, allowing the user to retry."""
    with (
        patch("web.server._claim_report_slot", return_value=True),
        patch("web.server._report_to_sentry", return_value=False),
    ):
        response = client.post("/issue", data=VALID_REPORT)

    assert response.status_code == 503
    assert 'class="sent"' not in response.get_data(as_text=True)


def test_the_log_line_keeps_the_choices_and_not_the_free_text(client, report_deps, caplog):
    """Server logs record structured issue metadata without freeform text."""
    caplog.set_level(logging.INFO)

    client.post("/issue", data=VALID_REPORT)

    assert "Сповіщення прийшло із запізненням" in caplog.text
    assert "Київ" in caplog.text
    assert VALID_REPORT["message"] not in caplog.text
    assert "@reporter" not in caplog.text


def test_rate_limit_window_is_set_on_the_first_report_only(app):
    with patch("web.server.redis_client") as mock_redis:
        mock_redis.incr.side_effect = [1, 2]

        with app.test_request_context("/issue", method="POST"):
            assert web_server._claim_report_slot() is True
            assert web_server._claim_report_slot() is True

    mock_redis.expire.assert_called_once_with(
        mock_redis.incr.call_args.args[0], web_server.REPORT_RATE_WINDOW
    )


def test_rate_limit_rejects_past_the_allowance(app):
    with patch("web.server.redis_client") as mock_redis:
        mock_redis.incr.return_value = web_server.REPORT_RATE_LIMIT + 1

        with app.test_request_context("/issue", method="POST"):
            assert web_server._claim_report_slot() is False


def test_rate_limit_lets_reports_through_when_redis_is_down(app, caplog):
    """Losing a genuine report costs more than letting a flood through."""
    caplog.set_level(logging.WARNING)

    with patch("web.server.redis_client") as mock_redis:
        mock_redis.incr.side_effect = ConnectionError("redis down")

        with app.test_request_context("/issue", method="POST"):
            assert web_server._claim_report_slot() is True

    assert "skipping report rate limit" in caplog.text


def test_rate_limit_keys_on_the_cloudflare_client_ip(app):
    with patch("web.server.redis_client") as mock_redis:
        mock_redis.incr.return_value = 1

        with app.test_request_context(
            "/issue", method="POST", headers={"CF-Connecting-IP": "203.0.113.7"}
        ):
            web_server._claim_report_slot()

    assert "203.0.113.7" in mock_redis.incr.call_args.args[0]


DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"

REPORT = {
    "category": "Сповіщення",
    "sub_option": "Сповіщення прийшло із запізненням",
    "time": "Щойно",
    "city": "Київ",
    "district": "",
    "message": "Запізнилось",
    "contact": "@reporter",
}


@pytest.fixture
def sentry(monkeypatch):
    """Sentry configured, with its scope and transport stubbed out."""
    monkeypatch.setattr(web_server, "SENTRY_DSN", DSN)

    with (
        patch("web.server.sentry_sdk.new_scope") as mock_new_scope,
        patch("web.server.sentry_sdk.capture_message") as mock_capture,
        patch("web.server.sentry_sdk.flush") as mock_flush,
    ):
        mock_scope = MagicMock()
        mock_new_scope.return_value.__enter__.return_value = mock_scope
        mock_capture.return_value = "deadbeef"
        yield mock_scope, mock_capture, mock_flush


def test_sentry_forward_is_skipped_when_unconfigured(monkeypatch):
    """Skips forwarding to Sentry without error when DSN is unconfigured."""
    monkeypatch.setattr(web_server, "SENTRY_DSN", "")

    with patch("web.server.sentry_sdk.capture_message") as mock_capture:
        assert web_server._report_to_sentry(REPORT) is True

    mock_capture.assert_not_called()


def test_sentry_title_is_english(sentry):
    _, mock_capture, _ = sentry

    assert web_server._report_to_sentry(REPORT) is True
    mock_capture.assert_called_once_with(
        "Issue report: Alerts — Notification arrived late", level="info"
    )


def test_sentry_tags_are_stable_ascii_keys(sentry):
    """Sentry tags use stable ASCII keys for consistency."""
    mock_scope, _, _ = sentry

    web_server._report_to_sentry(REPORT)

    tags = dict(call.args for call in mock_scope.set_tag.call_args_list)
    assert tags == {
        "report.category": "alerts",
        "report.option": "late",
        "report.time": "just_now",
        "report.city": "Київ",
    }


def test_sentry_map_report_tags_district(sentry):
    mock_scope, _, _ = sentry

    map_report = {
        "category": "Мапа тривог",
        "sub_option": "Мапа не відкривається зовсім",
        "time": "15:20",
        "district": "Бучанський район",
        "city": "",
        "message": "Не працює",
        "contact": "",
    }
    web_server._report_to_sentry(map_report)

    tags = dict(call.args for call in mock_scope.set_tag.call_args_list)
    assert tags == {
        "report.category": "map",
        "report.option": "map_not_opening",
        "report.time": "custom",
        "report.district": "Бучанський район",
    }
    name, context = mock_scope.set_context.call_args.args
    assert context["District"] == "Бучанський район"
    assert context["When"] == "15:20"


def test_sentry_context_spells_the_choices_out_in_english(sentry):
    mock_scope, _, _ = sentry

    web_server._report_to_sentry(REPORT)

    name, context = mock_scope.set_context.call_args.args
    assert name == "Issue report"
    assert context == {
        "Category": "Alerts",
        "Problem": "Notification arrived late",
        "When": "Just now",
        "City": "Київ",
        "Comment": "Запізнилось",
        "Contact": "@reporter",
    }


def test_sentry_carries_the_handle_the_reporter_offered(sentry):
    """Includes the user handle in Sentry payload when provided."""
    mock_scope, _, _ = sentry

    web_server._report_to_sentry(REPORT)

    mock_scope.set_user.assert_called_once_with({"username": "@reporter"})


def test_sentry_does_not_invent_a_user_when_no_handle_was_left(sentry):
    mock_scope, _, _ = sentry

    web_server._report_to_sentry({**REPORT, "contact": ""})

    mock_scope.set_user.assert_not_called()


def test_sentry_custom_ukrainian_datetime_and_tags(sentry):
    mock_scope, mock_capture, _ = sentry

    report = {
        "category": "Сповіщення",
        "sub_option": "Сповіщення прийшло із запізненням",
        "time": "23 серп. 23:56",
        "city": "Харків",
        "district": "",
        "message": "Спізнилось на 15 хв",
        "contact": "@testuser",
    }
    web_server._report_to_sentry(report)

    tags = dict(call.args for call in mock_scope.set_tag.call_args_list)
    assert tags == {
        "report.category": "alerts",
        "report.option": "late",
        "report.time": "custom",
        "report.city": "Харків",
    }
    mock_scope.set_user.assert_called_once_with({"username": "@testuser"})
    name, context = mock_scope.set_context.call_args.args
    assert name == "Issue report"
    assert context == {
        "Category": "Alerts",
        "Problem": "Notification arrived late",
        "When": "23 серп. 23:56",
        "City": "Харків",
        "Comment": "Спізнилось на 15 хв",
        "Contact": "@testuser",
    }
    mock_capture.assert_called_once_with(
        "Issue report: Alerts — Notification arrived late", level="info"
    )


def test_sentry_marks_the_choices_a_report_did_not_make(sentry):
    """Tags unspecified fields with default values for proper Sentry filtering."""
    mock_scope, mock_capture, _ = sentry

    web_server._report_to_sentry(
        {
            "category": "Інше",
            "sub_option": "",
            "time": "",
            "city": "",
            "district": "",
            "message": "Щось зламалось",
            "contact": "",
        }
    )

    tags = dict(call.args for call in mock_scope.set_tag.call_args_list)
    assert tags == {
        "report.category": "other",
        "report.option": "unspecified",
        "report.time": "unspecified",
        "report.city": "unspecified",
    }
    mock_capture.assert_called_once_with("Issue report: Other", level="info")


def test_sentry_groups_one_failure_regardless_of_city_or_time(sentry):
    """Groups issue reports under stable titles regardless of location or time."""
    _, mock_capture, _ = sentry

    web_server._report_to_sentry({**REPORT, "city": "Львів", "time": "Щойно"})
    web_server._report_to_sentry({**REPORT, "city": "Харків", "time": "Менше години тому"})

    titles = {call.args[0] for call in mock_capture.call_args_list}
    assert titles == {"Issue report: Alerts — Notification arrived late"}


def test_sentry_send_is_flushed_before_the_response(sentry):
    """Flushes pending Sentry events before sending the HTTP response."""
    _, _, mock_flush = sentry

    web_server._report_to_sentry(REPORT)

    mock_flush.assert_called_once_with(timeout=web_server.SENTRY_FLUSH_TIMEOUT)


def test_the_event_id_is_logged_so_a_report_can_be_found_again(sentry, caplog):
    """Logs the Sentry event ID for traceability."""
    caplog.set_level(logging.INFO)

    web_server._report_to_sentry(REPORT)

    assert "event_id=deadbeef" in caplog.text


def test_a_declined_event_is_logged_as_such(sentry, caplog):
    caplog.set_level(logging.WARNING)
    _, mock_capture, _ = sentry
    mock_capture.return_value = None

    web_server._report_to_sentry(REPORT)

    assert "Sentry declined an issue report" in caplog.text


def test_sentry_reports_a_dropped_event_as_failure(sentry):
    """Treats dropped Sentry events as failures."""
    _, mock_capture, _ = sentry
    mock_capture.return_value = None

    assert web_server._report_to_sentry(REPORT) is False


def test_sentry_failure_is_reported_not_swallowed(monkeypatch, caplog):
    """Surfaces Sentry client exceptions as errors."""
    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(web_server, "SENTRY_DSN", DSN)

    with patch("web.server.sentry_sdk.new_scope", side_effect=Exception("sentry down")):
        assert web_server._report_to_sentry(REPORT) is False

    assert "Failed to forward an issue report to Sentry" in caplog.text


def test_missing_dsn_is_announced_at_startup(caplog):
    """Warns on startup when SENTRY_DSN is not configured."""
    caplog.set_level(logging.WARNING)

    create_app(init_db=False, start_healthcheck=False)

    assert "issue reports will not be delivered anywhere" in caplog.text
