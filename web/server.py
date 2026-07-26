import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, g

from config import DATABASE_URL
from web.db import get_all_threats_data, ensure_pg_tables

SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')

app = Flask(__name__)
app.secret_key = SECRET_KEY


ensure_pg_tables()


def get_db() -> psycopg2.extensions.connection:
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return g.db


@app.teardown_appcontext
def close_db(exception: BaseException | None) -> None:
    db = g.pop('db', None)
    if db is not None:
        db.close()


@app.route('/')
def index() -> str:
    """Головна сторінка — карта тривог."""
    return render_template('index.html')


@app.route('/api', methods=['GET'])
def api() -> Any:
    return jsonify(get_all_threats_data())



if __name__ == "__main__":
    debug_mode = os.environ.get('APP_MODE') == 'dev'
    app.run(host="0.0.0.0", debug=debug_mode, port=5000)