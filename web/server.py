import hashlib
import logging
import os
import threading
import time
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import Any

import psycopg2
import requests
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from psycopg2.extras import RealDictCursor
from flask import Flask, current_app, render_template, jsonify, g, request, url_for, Response

from config import (
    ADMIN_CHAT_ID, DATABASE_URL, LOGS_PATH, SENTRY_DSN, TELEGRAM_BOT_TOKEN,
    HEALTHCHECKS_PING_URL_WEB, VERSION
)
from web.db import (
    get_all_threats_data, ensure_pg_tables, redis_client, save_error_report
)
from web.report_form import (
    CATEGORIES as REPORT_CATEGORIES, CATEGORY_ALIASES, OPTIONS_BY_CATEGORY, page_config
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

HEALTHCHECK_PING_INTERVAL = 60  # seconds; pair with a ~3min period on the healthchecks.io check
HEALTHCHECK_PING_TIMEOUT = 10  # seconds
HEALTHCHECK_LOCK_KEY = "healthcheck:web:ping-leader"
HEALTHCHECK_LOCK_TTL = 50  # seconds; must stay below the interval so each cycle can re-elect

TELEGRAM_API_TIMEOUT = 10  # seconds

# What the page asks, and which answers count as answers, lives in
# web/report_form.py. The limits below belong to the table, not the form: they
# are the widths of the error_reports columns.
REPORT_FIELD_LIMITS = {'city': 100, 'message': 2000, 'contact': 100}
REPORT_RATE_LIMIT = 5  # accepted reports per window, per client IP
REPORT_RATE_WINDOW = 3600  # seconds


def _ping_healthcheck(suffix: str = "") -> None:
    if not HEALTHCHECKS_PING_URL_WEB:
        return
    try:
        requests.get(f"{HEALTHCHECKS_PING_URL_WEB}{suffix}", timeout=HEALTHCHECK_PING_TIMEOUT)
    except Exception:
        log.warning("Failed to ping healthchecks.io", exc_info=True)


def _claim_ping_slot() -> bool:
    return bool(
        redis_client.set(HEALTHCHECK_LOCK_KEY, os.getpid(), nx=True, ex=HEALTHCHECK_LOCK_TTL)
    )


def _healthcheck_loop() -> None:
    while True:
        time.sleep(HEALTHCHECK_PING_INTERVAL)
        try:
            if _claim_ping_slot():
                _ping_healthcheck()
        except Exception:
            log.warning("Redis unreachable; skipping healthcheck ping", exc_info=True)


def _start_healthcheck_thread() -> None:
    if not HEALTHCHECKS_PING_URL_WEB:
        log.warning("HEALTHCHECKS_PING_URL_WEB not set; skipping healthcheck pings")
        return

    threading.Thread(target=_healthcheck_loop, daemon=True, name="healthcheck-ping").start()


def get_db() -> psycopg2.extensions.connection:
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db


def close_db(exception: BaseException | None = None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


def index() -> str:
    return render_template('index.html')


def api() -> Any:
    return jsonify(get_all_threats_data())


def _client_ip() -> str:
    """The real visitor address; the app sits behind Cloudflare."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (
        request.headers.get('CF-Connecting-IP')
        or forwarded.split(',')[0].strip()
        or request.remote_addr
        or 'unknown'
    )


def _claim_report_slot() -> bool:
    """Throttle the public form so one client cannot flood the reports table."""
    key = f"report-error:rate:{_client_ip()}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, REPORT_RATE_WINDOW)
    except Exception:
        # Redis being down is our problem, not the reporter's: let them through.
        log.warning("Redis unreachable; skipping report rate limit", exc_info=True)
        return True
    return count <= REPORT_RATE_LIMIT


def _clean_report_form(form: Any) -> tuple[dict[str, str], str]:
    """Re-check the form the way its JavaScript does, for submissions that skipped it.

    Returns the fields to store plus an empty string, or an empty dict plus the
    message to show the reporter.
    """
    # Without JavaScript the field carries the tab label ("Мапа") instead of the
    # name the report lives under from here on ("Мапа тривог").
    category = (form.get('category') or '').strip()
    category = CATEGORY_ALIASES.get(category, category)
    if category not in OPTIONS_BY_CATEGORY:
        return {}, 'Оберіть категорію помилки.'

    options = OPTIONS_BY_CATEGORY[category]
    sub_option = (form.get('sub_option') or '').strip()

    def field(name: str, *aliases: str) -> str:
        val = form.get(name)
        if not val:
            for alias in aliases:
                val = form.get(alias)
                if val:
                    break
        return (val or '').strip()[:REPORT_FIELD_LIMITS[name]]

    city = field('city')
    # The page sends message/contact through fetch; a plain POST sends the field
    # names themselves. Both spellings are accepted.
    message = field('message', 'comment')
    contact = field('contact', 'tg')

    # An answer has to belong to the category it arrived with. Otherwise the
    # table collects wording the form never offered, and a breakdown by failure
    # type stops meaning anything.
    if options and sub_option not in options:
        return {}, 'Оберіть, будь ласка, що саме сталося.'
    if not options:
        sub_option = ''
    if not city:
        return {}, 'Будь ласка, вкажіть місто.'
    # A category with no options ("Інше") exists for what we did not foresee, so
    # the whole report is the comment - without it there is nothing to act on.
    if not options and not message:
        return {}, 'Опис помилки обовʼязковий для цієї категорії.'

    return {
        'category': category,
        'sub_option': sub_option,
        'city': city,
        'message': message,
        'contact': contact,
    }, ''


def _notify_admin(report: dict[str, str]) -> None:
    """Best-effort ping to the admin chat; a failure must not lose the report."""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return

    lines = ['🐞 Нове повідомлення про помилку', f"Категорія: {report['category']}"]
    labels = {
        'sub_option': 'Деталі',
        'city': 'Місто',
        'message': 'Коментар',
        'contact': 'Контакт',
    }
    lines += [f"{label}: {report[key]}" for key, label in labels.items() if report[key]]

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': ADMIN_CHAT_ID,
                'text': '\n'.join(lines),
                'disable_web_page_preview': True,
            },
            timeout=TELEGRAM_API_TIMEOUT,
        )
    except Exception:
        log.warning("Failed to forward an error report to Telegram", exc_info=True)


def _render_report_form(**context: Any) -> str:
    """The page together with the taxonomy it draws itself from."""
    return render_template(
        'report_error.html',
        categories=REPORT_CATEGORIES,
        page_config=page_config(),
        **context,
    )


def report_error() -> Any:
    if request.method == 'GET':
        return _render_report_form()

    if not _claim_report_slot():
        return render_template(
            'error.html',
            error_code=429,
            error_message='Забагато повідомлень',
            error_description=(
                'Ви надіслали кілька повідомлень поспіль. '
                'Спробуйте ще раз за годину — попередні вже в роботі.'
            ),
        ), 429

    report, error = _clean_report_form(request.form)
    if error:
        # The form shows client-side errors only, so a rejection here just
        # re-serves it. This path is reached only by submissions that bypassed
        # the JavaScript checks, hence the log line instead of on-page feedback.
        log.info("Rejected error report: %s", error)
        return _render_report_form(), 400

    save_error_report(get_db(), **report)
    log.info("Error report received: category=%s city=%s", report['category'], report['city'])
    _notify_admin(report)

    return _render_report_form(success=True)


def handle_not_found(error: Exception) -> tuple[str, int]:
    return render_template(
        'error.html',
        error_code=404,
        error_message='Сторінку не знайдено',
        error_description='Можливо, в адресі є помилка або сторінку було перенесено.',
    ), 404


def handle_server_error(error: Exception) -> tuple[str, int]:
    return render_template(
        'error.html',
        error_code=500,
        error_message='Щось зламалось у нас',
        error_description=(
            'Ми вже знаємо про проблему та працюємо над нею. '
            'Спробуйте оновити сторінку трохи згодом.'
        ),
    ), 500


@lru_cache(maxsize=None)
def _static_fingerprint(static_folder: str, filename: str) -> str:
    """Відбиток вмісту файлу статики; рахується раз на процес."""
    try:
        with open(os.path.join(static_folder, filename), 'rb') as handle:
            return hashlib.md5(handle.read()).hexdigest()[:8]
    except OSError:
        log.warning("Static file %s is missing; falling back to the release stamp", filename)
        return VERSION


def static_url(filename: str) -> str:
    """Посилання на статику з відбитком вмісту в запиті.

    /static/ віддається як immutable на 30 днів (див. add_caching_headers), тож
    без відбитка браузер, який уже відкривав карту, місяць тримав би старий JS
    поруч зі свіжим /api. Саме через це попап області показував ключі районів
    замість назв: стара розмітка не знала про поле, що з'явилось у відповіді.
    """
    return url_for('static', filename=filename,
                   v=_static_fingerprint(current_app.static_folder, filename))


def add_caching_headers(response: Response) -> Response:
    if request.path == '/api':
        response.headers['Cache-Control'] = 'public, max-age=2, s-maxage=2'
    elif request.path.startswith('/static/') or request.path.endswith('.geojson'):
        response.headers['Cache-Control'] = 'public, max-age=2592000, immutable'
    elif request.method == 'GET' and response.status_code == 200:
        response.headers['Cache-Control'] = 'no-cache, must-revalidate'
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
    app.secret_key = os.environ.get('FLASK_SECRET_KEY')

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
        ],
        environment=os.environ.get('APP_MODE', 'dev'),
        release=VERSION,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", "web")

    @app.context_processor
    def inject_version() -> dict[str, str]:
        return {'version': VERSION}

    app.teardown_appcontext(close_db)
    app.after_request(add_caching_headers)
    app.jinja_env.globals['static_url'] = static_url

    app.add_url_rule('/', view_func=index)
    app.add_url_rule('/api', view_func=api, methods=['GET'])
    app.add_url_rule('/report-error', view_func=report_error, methods=['GET', 'POST'])

    app.register_error_handler(404, handle_not_found)
    app.register_error_handler(500, handle_server_error)

    if init_db:
        _register_schema_init(app)

    if start_healthcheck:
        _start_healthcheck_thread()

    return app


app = create_app()


if __name__ == "__main__":
    debug_mode = os.environ.get('APP_MODE') == 'dev'
    app.run(host="0.0.0.0", debug=debug_mode, port=5000)
