import hashlib
import logging
import os
import threading
import time
from functools import cache
from logging.handlers import RotatingFileHandler
from typing import Any

import requests
import sentry_sdk
from flask import Flask, Response, current_app, jsonify, redirect, render_template, request, url_for
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from config import (
    APP_ENV,
    GA_MEASUREMENT_ID,
    HEALTHCHECKS_WEB_PING_URL,
    LOGS_PATH,
    SENTRY_DSN,
    SITE_URL,
    VERSION,
)
from web.db import ensure_pg_tables, get_all_threats_data, redis_client
from web.issue import CATEGORIES as ISSUE_CATEGORIES
from web.issue import (
    CATEGORY_ALIASES,
    CATEGORY_INFO,
    OPTION_INFO,
    OPTIONS_BY_CATEGORY,
    TIME_INFO,
    TIME_NAMES,
    page_config,
)

os.makedirs(LOGS_PATH, exist_ok=True)
LOG_FILE = os.path.join(LOGS_PATH, "web.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

HEALTHCHECK_PING_INTERVAL = 60
HEALTHCHECK_PING_TIMEOUT = 10
HEALTHCHECK_LOCK_KEY = "healthcheck:web:ping-leader"
HEALTHCHECK_LOCK_TTL = 50

REPORT_FIELD_LIMITS = {
    "city": 100,
    "district": 100,
    "time": 50,
    "exact_time": 50,
    "exact_date": 50,
    "exact_datetime": 50,
    "message": 1000,
    "contact": 100,
}
REPORT_RATE_LIMIT = 5
REPORT_RATE_WINDOW = 3600
SENTRY_FLUSH_TIMEOUT = 2


def _ping_healthcheck(suffix: str = "") -> None:
    if not HEALTHCHECKS_WEB_PING_URL:
        return
    try:
        requests.get(f"{HEALTHCHECKS_WEB_PING_URL}{suffix}", timeout=HEALTHCHECK_PING_TIMEOUT)
    except Exception:
        log.warning("Failed to ping healthchecks.io", exc_info=True)


def _claim_slot(key: str, ttl: int) -> bool:
    return bool(redis_client.set(key, os.getpid(), nx=True, ex=ttl))


def _claim_ping_slot() -> bool:
    return _claim_slot(HEALTHCHECK_LOCK_KEY, HEALTHCHECK_LOCK_TTL)


def _healthcheck_loop() -> None:
    while True:
        time.sleep(HEALTHCHECK_PING_INTERVAL)
        try:
            if _claim_ping_slot():
                _ping_healthcheck()
        except Exception:
            log.warning("Redis unreachable; skipping healthcheck ping", exc_info=True)


def _start_healthcheck_thread() -> None:
    if not HEALTHCHECKS_WEB_PING_URL:
        log.warning("HEALTHCHECKS_WEB_PING_URL not set; skipping healthcheck pings")
        return

    threading.Thread(target=_healthcheck_loop, daemon=True, name="healthcheck-ping").start()


def index() -> str:
    return render_template("index.html")


def api() -> Any:
    return jsonify(get_all_threats_data())


def status() -> Any:
    return redirect("https://status.sirens.live", code=301)


# The pages this origin serves. The status page is a separate host and ships its
# own pair of files: a sitemap may only list URLs under the origin serving it.
SITEMAP_PATHS = ("/", "/issue")


def sitemap() -> Response:
    urls = "".join(f"    <url><loc>{SITE_URL}{path}</loc></url>\n" for path in SITEMAP_PATHS)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )
    return Response(body, mimetype="application/xml")


def _client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (
        request.headers.get("CF-Connecting-IP")
        or forwarded.split(",")[0].strip()
        or request.remote_addr
        or "unknown"
    )


def _claim_report_slot() -> bool:
    key = f"issue:rate:{_client_ip()}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, REPORT_RATE_WINDOW)
    except Exception:
        log.warning("Redis unreachable; skipping report rate limit", exc_info=True)
        return True
    return count <= REPORT_RATE_LIMIT


def _clean_report_form(form: Any) -> tuple[dict[str, str], str]:
    category = (form.get("category") or "").strip()
    category = CATEGORY_ALIASES.get(category, category)
    if category not in OPTIONS_BY_CATEGORY:
        return {}, "Оберіть категорію помилки."

    options = OPTIONS_BY_CATEGORY[category]
    sub_option = (form.get("sub_option") or "").strip()

    def field(name: str) -> str:
        return (form.get(name) or "").strip()[: REPORT_FIELD_LIMITS[name]]

    city = field("city")
    district = field("district")
    contact = field("contact")

    message = (form.get("message") or "").strip()
    if len(message) > REPORT_FIELD_LIMITS["message"]:
        return {}, f"Коментар не може бути довшим за {REPORT_FIELD_LIMITS['message']} символів."

    if options:
        if sub_option not in options:
            return {}, "Оберіть, будь ласка, що саме сталося."
    else:
        sub_option = ""

    time_val = (form.get("time") or "").strip()
    exact_time = (form.get("exact_time") or "").strip()
    exact_date = (form.get("exact_date") or "").strip()

    if time_val in ("Вибрати дату і час", "Вибрати час"):
        if exact_date and exact_time:
            time_val = f"{exact_date} {exact_time}"
        elif exact_time:
            time_val = exact_time
        elif exact_date:
            time_val = exact_date
        else:
            return {}, "Вкажіть, будь ласка, дату і час."
    elif time_val and time_val not in TIME_NAMES:
        import re

        if not re.match(
            r"^(?:(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+[^\d\s]+)\s+)?(?:[01]?\d|2[0-3]):[0-5]\d$",
            time_val,
        ):
            return {}, "Оберіть, будь ласка, коли це сталося."

    if category in ("Сповіщення", "Мапа тривог"):
        if not time_val:
            return {}, "Оберіть, будь ласка, коли це сталося."

    if category == "Сповіщення" and not city:
        return {}, "Будь ласка, вкажіть місто."
    if category == "Мапа тривог" and not (district or city):
        return {}, "Будь ласка, вкажіть район."

    if not options and not message:
        return {}, "Опис помилки обовʼязковий для цієї категорії."

    return {
        "category": category,
        "sub_option": sub_option,
        "time": time_val,
        "city": city,
        "district": district,
        "message": message,
        "contact": contact,
    }, ""


def _report_to_sentry(report: dict[str, str]) -> bool:
    if not SENTRY_DSN:
        return True

    try:
        category = CATEGORY_INFO[report["category"]]
        option = OPTION_INFO.get(report["sub_option"])
        time_val = report.get("time", "")
        if time_val in TIME_INFO:
            time_tag = TIME_INFO[time_val]["key"]
            time_en = TIME_INFO[time_val]["en"]
        elif time_val:
            time_tag = "custom"
            time_en = time_val
        else:
            time_tag = "unspecified"
            time_en = "—"

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("report.category", category["key"])
            scope.set_tag("report.option", option["key"] if option else "unspecified")
            scope.set_tag("report.time", time_tag)
            if category["key"] == "map":
                scope.set_tag(
                    "report.district", report.get("district") or report.get("city") or "unspecified"
                )
            else:
                scope.set_tag(
                    "report.city", report.get("city") or report.get("district") or "unspecified"
                )

            if report["contact"]:
                scope.set_user({"username": report["contact"]})

            context_data = {
                "Category": category["en"],
                "Problem": option["en"] if option else "—",
                "When": time_en,
                "Comment": report["message"] or "—",
                "Contact": report["contact"] or "—",
            }
            if category["key"] == "map":
                context_data["District"] = report.get("district") or report.get("city") or "—"
            else:
                context_data["City"] = report.get("city") or report.get("district") or "—"

            scope.set_context("Issue report", context_data)

            title = f"Issue report: {category['en']}"
            if option:
                title += f" — {option['en']}"

            event_id = sentry_sdk.capture_message(title, level="info")

        sentry_sdk.flush(timeout=SENTRY_FLUSH_TIMEOUT)
        if event_id is None:
            log.warning("Sentry declined an issue report; it is not stored anywhere")
            return False

        log.info(
            "Issue report forwarded to Sentry: event_id=%s environment=%s",
            event_id,
            APP_ENV,
        )
        return True
    except Exception:
        log.exception("Failed to forward an issue report to Sentry")
        return False


def _render_issue_form(**context: Any) -> str:
    return render_template(
        "issue.html",
        categories=ISSUE_CATEGORIES,
        page_config=page_config(),
        **context,
    )


def issue() -> Any:
    if request.method == "GET":
        return _render_issue_form()

    if not _claim_report_slot():
        return render_template(
            "error.html",
            error_code=429,
            error_message="Забагато повідомлень",
        ), 429

    report, error = _clean_report_form(request.form)
    if error:
        log.info("Rejected issue report: %s", error)
        return _render_issue_form(), 400

    log.info(
        "Issue report: category=%s option=%s time=%s city=%s district=%s",
        report["category"],
        report["sub_option"],
        report.get("time", ""),
        report.get("city", ""),
        report.get("district", ""),
    )

    if not _report_to_sentry(report):
        return _render_issue_form(), 503

    return _render_issue_form(success=True)


def handle_not_found(error: Exception) -> tuple[str, int]:
    return render_template(
        "error.html",
        error_code=404,
        error_message="Сторінку не знайдено",
    ), 404


def handle_server_error(error: Exception) -> tuple[str, int]:
    return render_template(
        "error.html",
        error_code=500,
        error_message="Щось зламалось у нас",
    ), 500


@cache
def _static_fingerprint(static_folder: str, filename: str) -> str:
    try:
        with open(os.path.join(static_folder, filename), "rb") as handle:
            return hashlib.md5(handle.read()).hexdigest()[:8]
    except OSError:
        log.warning("Static file %s is missing; falling back to the release stamp", filename)
        return VERSION


def static_url(filename: str) -> str:
    return url_for(
        "static", filename=filename, v=_static_fingerprint(current_app.static_folder, filename)
    )


def add_caching_headers(response: Response) -> Response:
    if request.path == "/api":
        response.headers["Cache-Control"] = "public, max-age=2, s-maxage=2"
    elif request.path == "/sitemap.xml":
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.path.startswith("/static/") or request.path.endswith(".geojson"):
        response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
    elif request.method == "GET" and response.status_code == 200:
        response.headers["Cache-Control"] = "no-cache, must-revalidate"

    return response


def _register_schema_init(app: Flask) -> None:
    state = {"done": False}

    @app.before_request
    def _init_schema() -> None:
        if state["done"]:
            return
        ensure_pg_tables()
        state["done"] = True


def create_app(*, init_db: bool = True, start_healthcheck: bool = True) -> Flask:
    app = Flask(__name__)

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
        ],
        environment=APP_ENV,
        release=VERSION,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", "web")

    if not SENTRY_DSN:
        log.warning("SENTRY_DSN not set; issue reports will not be delivered anywhere")

    @app.context_processor
    def inject_page_globals() -> dict[str, str]:
        return {
            "version": VERSION,
            "site_url": SITE_URL,
            "ga_measurement_id": GA_MEASUREMENT_ID,
        }

    app.after_request(add_caching_headers)
    app.jinja_env.globals["static_url"] = static_url

    app.add_url_rule("/", view_func=index)
    app.add_url_rule("/api", view_func=api, methods=["GET"])
    app.add_url_rule("/issue", view_func=issue, methods=["GET", "POST"])
    app.add_url_rule("/status", view_func=status, methods=["GET"])
    app.add_url_rule("/sitemap.xml", view_func=sitemap, methods=["GET"])

    app.register_error_handler(404, handle_not_found)
    app.register_error_handler(500, handle_server_error)

    if init_db:
        _register_schema_init(app)

    if start_healthcheck:
        _start_healthcheck_thread()

    return app


app = create_app()


if __name__ == "__main__":
    debug_mode = APP_ENV == "dev"
    app.run(host="0.0.0.0", debug=debug_mode, port=5000)
