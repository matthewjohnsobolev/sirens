import os
from typing import Any

import psycopg2
import requests
from psycopg2.extras import RealDictCursor
from flask import Flask, current_app, render_template, jsonify, g, request

from config import DATABASE_URL
from web.db import get_all_threats_data, ensure_pg_tables

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


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


def create_app(*, init_db: bool = True) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get('FLASK_SECRET_KEY')

    app.teardown_appcontext(close_db)

    app.add_url_rule('/', view_func=index)
    app.add_url_rule('/api', view_func=api, methods=['GET'])

    if init_db:
        _register_schema_init(app)

    return app


# gunicorn entry point: web.server:app
app = create_app()


if __name__ == "__main__":
    debug_mode = os.environ.get('APP_MODE') == 'dev'
    app.run(host="0.0.0.0", debug=debug_mode, port=5000)
