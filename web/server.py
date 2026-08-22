import hashlib
import logging
import os
import threading
import time
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from typing import Any

import requests
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from flask import Flask, current_app, render_template, jsonify, request, url_for, Response

from config import (
    LOGS_PATH, SENTRY_DSN, HEALTHCHECKS_PING_URL_WEB, VERSION
)
from web.db import get_all_threats_data, ensure_pg_tables, redis_client
from web.issue import (
    CATEGORIES as ISSUE_CATEGORIES, CATEGORY_ALIASES, CATEGORY_INFO, DELAY_APPLIES_TO,
    DELAY_INFO, DELAY_NAMES, OPTION_INFO, OPTIONS_BY_CATEGORY, page_config
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

# What the page asks, and which answers count as answers, lives in
# web/issue.py. The limits below cap what one submission may put into a Sentry
# event; the comment cap matches COMMENT_MAX in web/static/js/issue.js.
REPORT_FIELD_LIMITS = {'city': 100, 'message': 250, 'contact': 100}
# Submissions per window, per client IP - not accepted reports: the slot is
# claimed before the form is checked, so a flood of malformed posts runs a
# client out of slots just as a flood of valid ones would.
REPORT_RATE_LIMIT = 5
REPORT_RATE_WINDOW = 3600  # seconds

# A report lives nowhere else, so the send has to finish before the worker can
# be recycled out from under the queued event.
SENTRY_FLUSH_TIMEOUT = 2  # seconds


def _ping_healthcheck(suffix: str = "") -> None:
    if not HEALTHCHECKS_PING_URL_WEB:
        return
    try:
        requests.get(f"{HEALTHCHECKS_PING_URL_WEB}{suffix}", timeout=HEALTHCHECK_PING_TIMEOUT)
    except Exception:
        log.warning("Failed to ping healthchecks.io", exc_info=True)


def _claim_slot(key: str, ttl: int) -> bool:
    """Виграти цикл для цього воркера: SET NX атомарний, тож переможець один."""
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
    if not HEALTHCHECKS_PING_URL_WEB:
        log.warning("HEALTHCHECKS_PING_URL_WEB not set; skipping healthcheck pings")
        return

    threading.Thread(target=_healthcheck_loop, daemon=True, name="healthcheck-ping").start()


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
    """Throttle the public form so one client cannot flood the issue tracker."""
    key = f"issue:rate:{_client_ip()}"
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

    Returns the fields to forward plus an empty string, or an empty dict plus
    the message to show the reporter.
    """
    # Without JavaScript the field carries the tab label ("Мапа") instead of the
    # name the report lives under from here on ("Мапа тривог").
    category = (form.get('category') or '').strip()
    category = CATEGORY_ALIASES.get(category, category)
    if category not in OPTIONS_BY_CATEGORY:
        return {}, 'Оберіть категорію помилки.'

    options = OPTIONS_BY_CATEGORY[category]
    sub_option = (form.get('sub_option') or '').strip()

    def field(name: str) -> str:
        return (form.get(name) or '').strip()[:REPORT_FIELD_LIMITS[name]]

    city = field('city')
    contact = field('contact')

    message = (form.get('message') or '').strip()
    if len(message) > REPORT_FIELD_LIMITS['message']:
        return {}, 'Коментар не може бути довшим за 250 символів.'

    # An answer has to belong to the category it arrived with. Otherwise Sentry
    # collects wording the form never offered, and a breakdown by failure type
    # stops meaning anything.
    if options:
        if sub_option not in options:
            return {}, 'Оберіть, будь ласка, що саме сталося.'
    else:
        sub_option = ''

    delay = (form.get('delay') or '').strip()
    if delay and delay not in DELAY_NAMES:
        return {}, 'Оберіть, будь ласка, на скільки запізнилося сповіщення.'
    # Підпитання існує рівно під одним варіантом; під рештою відповідь на нього
    # нічого не означає, і тягти її далі нема сенсу.
    if sub_option != DELAY_APPLIES_TO:
        delay = ''

    # Місто обов'язкове для розділів з варіантами («Сповіщення», «Мапа»),
    # але необов'язкове для розділу «Інше»
    if options and not city:
        return {}, 'Будь ласка, вкажіть місто.'
    # A category with no options ("Інше") exists for what we did not foresee, so
    # the whole report is the comment - without it there is nothing to act on.
    if not options and not message:
        return {}, 'Опис помилки обовʼязковий для цієї категорії.'

    return {
        'category': category,
        'sub_option': sub_option,
        'delay': delay,
        'city': city,
        'message': message,
        'contact': contact,
    }, ''


def _report_to_sentry(report: dict[str, str]) -> bool:
    """The only place a report is kept. False means it did not get through.

    English throughout, because these events are read alongside the rest of the
    project's Sentry issues. The tags carry stable keys rather than the wording
    they came from: rephrasing an option in web/issue.py must not scatter its
    history across two groups.
    """
    if not SENTRY_DSN:
        # Dev, or a deploy that forgot the DSN - create_app warns about the
        # latter. The log line in issue() is the only record either way.
        return True

    try:
        category = CATEGORY_INFO[report['category']]
        option = OPTION_INFO.get(report['sub_option'])
        delay = DELAY_INFO.get(report['delay'])

        with sentry_sdk.new_scope() as scope:
            scope.set_tag('report.category', category['key'])
            scope.set_tag('report.option', option['key'] if option else 'unspecified')
            scope.set_tag('report.delay', delay['key'] if delay else 'unspecified')
            # Місто - не підпис, а те, що ввела людина: перекладати нема чого.
            scope.set_tag('report.city', report['city'] or 'unspecified')

            # send_default_pii=False governs what the SDK picks up on its own;
            # the handle is here because the reporter typed it in so we could
            # come back to them.
            if report['contact']:
                scope.set_user({'username': report['contact']})

            scope.set_context('Issue report', {
                'Category': category['en'],
                'Problem': option['en'] if option else '—',
                'Delay': delay['en'] if delay else '—',
                'City': report['city'] or '—',
                'Comment': report['message'] or '—',
                'Contact': report['contact'] or '—',
            })

            # Neither city nor delay belongs in the title: they would split one
            # failure into a group per city. Both are tags, which is what you
            # filter on anyway.
            title = f"Issue report: {category['en']}"
            if option:
                title += f" — {option['en']}"

            event_id = sentry_sdk.capture_message(title, level='info')

        sentry_sdk.flush(timeout=SENTRY_FLUSH_TIMEOUT)
        if event_id is None:
            log.warning("Sentry declined an issue report; it is not stored anywhere")
            return False

        # The id is the only thread back to the event: it makes "did this
        # report arrive?" a search in Sentry rather than a guess. Note that
        # events carry environment=APP_MODE, so a dev submission is invisible
        # while the Sentry UI is filtered to production.
        log.info("Issue report forwarded to Sentry: event_id=%s environment=%s",
                 event_id, os.environ.get('APP_MODE', 'dev'))
        return True
    except Exception:
        log.exception("Failed to forward an issue report to Sentry")
        return False


def _render_issue_form(**context: Any) -> str:
    """The page together with the taxonomy it draws itself from."""
    return render_template(
        'issue.html',
        categories=ISSUE_CATEGORIES,
        page_config=page_config(),
        **context,
    )


def issue() -> Any:
    if request.method == 'GET':
        return _render_issue_form()

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
        log.info("Rejected issue report: %s", error)
        return _render_issue_form(), 400

    # The choices, but not the comment or the handle: web.log rotates on disk,
    # and free text someone typed about themselves does not belong there.
    log.info(
        "Issue report: category=%s option=%s delay=%s city=%s",
        report['category'], report['sub_option'], report['delay'], report['city'],
    )

    if not _report_to_sentry(report):
        # Nothing else is holding the report, so a failed send has to reach the
        # reporter: the page keeps what they typed and lets them try again.
        return _render_issue_form(), 503

    return _render_issue_form(success=True)


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

    if not SENTRY_DSN:
        # /issue keeps reports nowhere else, so an unset DSN silently discards
        # every one of them while the page still says "надіслано".
        log.warning("SENTRY_DSN not set; issue reports will not be delivered anywhere")

    @app.context_processor
    def inject_version() -> dict[str, str]:
        return {'version': VERSION}

    app.after_request(add_caching_headers)
    app.jinja_env.globals['static_url'] = static_url

    app.add_url_rule('/', view_func=index)
    app.add_url_rule('/api', view_func=api, methods=['GET'])
    app.add_url_rule('/issue', view_func=issue, methods=['GET', 'POST'])

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
