import logging

import pytest
from unittest.mock import MagicMock, patch
from psycopg2.extras import RealDictCursor
from sentry_sdk.integrations.flask import FlaskIntegration

from config import DATABASE_URL
from web import server as web_server
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


# --------------------------------------------------------------------------
# Sentry
# --------------------------------------------------------------------------

def test_create_app_initializes_sentry_with_flask_integration(monkeypatch):
    monkeypatch.setattr(web_server, 'SENTRY_DSN_WEB', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('web.server.sentry_sdk.init') as mock_sentry_init:
        create_app(init_db=False, start_healthcheck=False)

    mock_sentry_init.assert_called_once()
    _, kwargs = mock_sentry_init.call_args
    assert kwargs['dsn'] == 'https://examplePublicKey@o0.ingest.sentry.io/0'
    assert kwargs['send_default_pii'] is False
    assert any(isinstance(i, FlaskIntegration) for i in kwargs['integrations'])


# --------------------------------------------------------------------------
# healthchecks.io pings
# --------------------------------------------------------------------------

def test_ping_healthcheck_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', '')

    with patch('web.server.requests.get') as mock_get:
        web_server._ping_healthcheck()

    mock_get.assert_not_called()


def test_ping_healthcheck_sends_get_with_suffix(monkeypatch):
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', 'https://hc-ping.com/test-uuid')

    with patch('web.server.requests.get') as mock_get:
        web_server._ping_healthcheck('/fail')

    mock_get.assert_called_once_with(
        'https://hc-ping.com/test-uuid/fail', timeout=web_server.HEALTHCHECK_PING_TIMEOUT
    )


def test_ping_healthcheck_logs_but_survives_request_failure(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', 'https://hc-ping.com/test-uuid')

    with patch('web.server.requests.get', side_effect=Exception('network down')):
        web_server._ping_healthcheck()

    assert "Failed to ping healthchecks.io" in caplog.text


def test_healthcheck_loop_pings_after_each_sleep():
    with patch('web.server.time.sleep', side_effect=[None, StopIteration]) as mock_sleep, \
         patch('web.server._ping_healthcheck') as mock_ping:
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    assert mock_sleep.call_count == 2
    mock_ping.assert_called_once_with()


def test_create_app_starts_healthcheck_thread_when_configured(monkeypatch):
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', 'https://hc-ping.com/test-uuid')

    with patch('web.server.threading.Thread') as MockThread:
        create_app(init_db=False, start_healthcheck=True)

    MockThread.assert_called_once()
    _, kwargs = MockThread.call_args
    assert kwargs['daemon'] is True
    MockThread.return_value.start.assert_called_once()


def test_create_app_skips_healthcheck_thread_when_unconfigured(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', '')

    with patch('web.server.threading.Thread') as MockThread:
        create_app(init_db=False, start_healthcheck=True)

    MockThread.assert_not_called()
    assert "HEALTHCHECKS_PING_URL_WEB not set" in caplog.text


def test_create_app_skips_healthcheck_thread_when_disabled(monkeypatch):
    monkeypatch.setattr(web_server, 'HEALTHCHECKS_PING_URL_WEB', 'https://hc-ping.com/test-uuid')

    with patch('web.server.threading.Thread') as MockThread:
        create_app(init_db=False, start_healthcheck=False)

    MockThread.assert_not_called()