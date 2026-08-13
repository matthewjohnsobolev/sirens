import pytest
from unittest.mock import patch
from psycopg2.extras import RealDictCursor

from config import DATABASE_URL
from web.server import create_app, get_db

SUCCESS_MARKER = 'Ваше повідомлення успішно надіслано'


def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200


def test_api_route(client):
    payload = {"kyiv": {"alert": {"status": 1}}}
    with patch('web.server.get_all_threats_data', return_value=payload) as mock_data:
        response = client.get('/api')

    assert response.status_code == 200
    assert response.json == payload
    mock_data.assert_called_once_with()

# --------------------------------------------------------------------------
# request-scoped database connection
# --------------------------------------------------------------------------

def test_get_db_reuses_one_connection_per_request(app):
    with patch('web.server.psycopg2.connect') as mock_connect:
        with app.test_request_context('/'):
            first = get_db()
            second = get_db()

        assert first is second is mock_connect.return_value
        mock_connect.assert_called_once_with(DATABASE_URL, cursor_factory=RealDictCursor)


def test_close_db_closes_connection_on_teardown(app):
    with patch('web.server.psycopg2.connect') as mock_connect:
        with app.test_request_context('/'):
            get_db()
        mock_connect.return_value.close.assert_called_once()


def test_teardown_without_db_is_a_noop(app):
    with patch('web.server.psycopg2.connect') as mock_connect:
        with app.test_request_context('/'):
            pass

    mock_connect.assert_not_called()


# --------------------------------------------------------------------------
# schema bootstrap
# --------------------------------------------------------------------------

def test_schema_is_created_on_first_request_only():
    with patch('web.server.ensure_pg_tables') as mock_ensure:
        flask_app = create_app(init_db=True)
        mock_ensure.assert_not_called()

        test_client = flask_app.test_client()
        test_client.get('/')
        test_client.get('/')

        mock_ensure.assert_called_once_with()


def test_app_can_be_built_without_schema_bootstrap():
    with patch('web.server.ensure_pg_tables') as mock_ensure:
        flask_app = create_app(init_db=False)
        flask_app.test_client().get('/')

    mock_ensure.assert_not_called()