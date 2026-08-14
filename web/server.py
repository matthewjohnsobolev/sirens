import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from typing import Any

import psycopg2
import requests
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, g

from config import DATABASE_URL, LOGS_PATH, SENTRY_DSN_WEB, HEALTHCHECKS_PING_URL_WEB
from web.db import get_all_threats_data, ensure_pg_tables, redis_client

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
        dsn=SENTRY_DSN_WEB,
        integrations=[
            FlaskIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
        ],
        environment=os.environ.get('APP_MODE', 'dev'),
        traces_sample_rate=0.0,
        send_default_pii=False,
    )

    app.teardown_appcontext(close_db)

    app.add_url_rule('/', view_func=index)
    app.add_url_rule('/api', view_func=api, methods=['GET'])

    if init_db:
        _register_schema_init(app)

    if start_healthcheck:
        _start_healthcheck_thread()

    return app


# gunicorn entry point: web.server:app
app = create_app()


if __name__ == "__main__":
    debug_mode = os.environ.get('APP_MODE') == 'dev'
    app.run(host="0.0.0.0", debug=debug_mode, port=5000)
