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


def test_report_error_get(client):
    response = client.get('/report-error')
    assert response.status_code == 200
    assert SUCCESS_MARKER not in response.get_data(as_text=True)


def test_report_error_post_success(client):
    with patch('web.server.requests.post') as mock_post:
        response = client.post('/report-error', data={
            'category': 'Мапа тривог',
            'sub_option_map': 'Неправильний колір області',
            'message': 'Test message',
            'city': 'Kyiv',
            'contact': '@someone',
        })

    assert response.status_code == 200
    assert SUCCESS_MARKER in response.get_data(as_text=True)

    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    data = mock_post.call_args.kwargs['data']

    assert url == 'https://api.telegram.org/bottest-token/sendMessage'
    assert data['chat_id'] == '0'
    assert data['parse_mode'] == 'HTML'
    for fragment in ('Мапа тривог', 'Неправильний колір області', 'Kyiv', 'Test message', '@someone'):
        assert fragment in data['text']


def test_report_error_post_defaults_missing_contact(client):
    with patch('web.server.requests.post') as mock_post:
        client.post('/report-error', data={
            'category': 'Мапа тривог',
            'message': 'Test message',
        })

    assert 'Не вказано' in mock_post.call_args.kwargs['data']['text']


def test_report_error_post_fallback_validation(client):
    with patch('web.server.requests.post') as mock_post:
        response = client.post('/report-error', data={
            'category': 'Інше',
            'message': '',
        })

    assert response.status_code == 200
    assert SUCCESS_MARKER not in response.get_data(as_text=True)
    mock_post.assert_not_called()


def test_report_error_survives_telegram_outage(client):
    with patch('web.server.requests.post', side_effect=Exception("telegram down")):
        response = client.post('/report-error', data={
            'category': 'Мапа тривог',
            'message': 'Test message',
        })

    assert response.status_code == 200
    assert SUCCESS_MARKER in response.get_data(as_text=True)


def test_report_error_post_notification_sub_option(client):
    with patch('web.server.requests.post') as mock_post:
        client.post('/report-error', data={
            'category': 'Сповіщення',
            'sub_option_notification': 'Не приходять сповіщення',
            'message': 'Test message',
        })

    assert 'Не приходять сповіщення' in mock_post.call_args.kwargs['data']['text']


def test_report_error_skips_telegram_when_not_configured(client, monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '')

    with patch('web.server.requests.post') as mock_post:
        response = client.post('/report-error', data={
            'category': 'Мапа тривог',
            'message': 'Test message',
        })

    # no credentials -> no outbound call, but the user still gets a confirmation
    mock_post.assert_not_called()
    assert SUCCESS_MARKER in response.get_data(as_text=True)


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
# error handlers
# --------------------------------------------------------------------------

def test_404_handler(client):
    response = client.get('/nonexistent_page')
    assert response.status_code == 404
    assert 'Сторінку не знайдено' in response.get_data(as_text=True)


def test_500_handler_renders_error_page():
    flask_app = create_app(init_db=False)
    flask_app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)

    @flask_app.route('/boom')
    def boom():
        raise RuntimeError("kaboom")

    response = flask_app.test_client().get('/boom')

    assert response.status_code == 500
    assert 'Внутрішня помилка сервера' in response.get_data(as_text=True)
