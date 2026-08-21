import logging
import re

import pytest
from flask import request
from unittest.mock import MagicMock, patch
from psycopg2.extras import RealDictCursor
from sentry_sdk.integrations.flask import FlaskIntegration

from config import DATABASE_URL, VERSION
from web import server as web_server
from web.server import create_app, get_db

SUCCESS_MARKER = 'Повідомлення надіслано'


def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers.get('Cache-Control') == 'no-cache, must-revalidate'


def test_api_route(client):
    payload = {"kyiv": {"alert": {"status": True}}}
    with patch('web.server.get_all_threats_data', return_value=payload) as mock_data:
        response = client.get('/api')

    assert response.status_code == 200
    assert response.json == payload
    assert response.headers.get('Cache-Control') == 'public, max-age=2, s-maxage=2'
    mock_data.assert_called_once_with()


def test_static_caching_header(client):
    response = client.get('/static/ukraine.geojson')
    if response.status_code == 200:
        assert response.headers.get('Cache-Control') == 'public, max-age=2592000, immutable'


def test_stats_csv_route_not_found(client):
    assert client.get('/bi/stats.csv').status_code == 404


# --------------------------------------------------------------------------
# cache busting
# --------------------------------------------------------------------------


def test_index_versions_every_stylesheet_and_script(client):
    """Статика віддається як immutable, тож без версії в URL зміни JS не доїдуть."""
    html = client.get('/').get_data(as_text=True)

    assets = re.findall(r'(?:href|src)="(/static/(?:css|js)/[^"]+)"', html)
    assert assets, "у сторінці не знайшлось жодного css/js"
    unversioned = [a for a in assets if '?v=' not in a]
    assert unversioned == [], f"без версії: {unversioned}"


def test_static_url_fingerprint_follows_the_file_contents(app, tmp_path):
    from web.server import _static_fingerprint, static_url

    _static_fingerprint.cache_clear()
    asset = tmp_path / 'probe.css'
    asset.write_text('a{}')

    with app.test_request_context():
        first = static_url('css/main.css')
        assert first == static_url('css/main.css')   # стабільний, поки файл не змінився

    assert _static_fingerprint(str(tmp_path), 'probe.css') != _static_fingerprint(
        str(tmp_path), 'missing.css'
    )

    before = _static_fingerprint(str(tmp_path), 'probe.css')
    asset.write_text('a{color:red}')
    _static_fingerprint.cache_clear()
    assert _static_fingerprint(str(tmp_path), 'probe.css') != before


def test_static_url_falls_back_to_the_release_when_the_file_is_gone(app, caplog):
    from web.server import _static_fingerprint, static_url

    _static_fingerprint.cache_clear()
    caplog.set_level(logging.WARNING)

    with app.test_request_context():
        assert f'v={VERSION}' in static_url('css/does-not-exist.css')

    assert 'does-not-exist.css' in caplog.text



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
    monkeypatch.setattr(web_server, 'SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('web.server.sentry_sdk.init') as mock_sentry_init:
        create_app(init_db=False, start_healthcheck=False)

    mock_sentry_init.assert_called_once()
    _, kwargs = mock_sentry_init.call_args
    assert kwargs['dsn'] == 'https://examplePublicKey@o0.ingest.sentry.io/0'
    assert kwargs['send_default_pii'] is False
    assert kwargs['release'] == VERSION
    assert any(isinstance(i, FlaskIntegration) for i in kwargs['integrations'])


def test_create_app_tags_events_with_its_service_name(monkeypatch):
    """Both services share one Sentry project, so the tag is the only thing
    separating web errors from alerts errors in the issue stream."""
    monkeypatch.setattr(web_server, 'SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('web.server.sentry_sdk.init'), \
         patch('web.server.sentry_sdk.set_tag') as mock_set_tag:
        create_app(init_db=False, start_healthcheck=False)

    mock_set_tag.assert_called_once_with("service", "web")


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


def test_claim_ping_slot_uses_atomic_set():
    """gunicorn runs several workers, each with its own ping thread, so the slot
    is claimed with an atomic SET NX EX rather than a read-then-write."""
    with patch('web.server.redis_client') as mock_redis:
        mock_redis.set.return_value = True

        assert web_server._claim_ping_slot() is True

    _, kwargs = mock_redis.set.call_args
    assert kwargs['nx'] is True
    assert kwargs['ex'] == web_server.HEALTHCHECK_LOCK_TTL
    assert web_server.HEALTHCHECK_LOCK_TTL < web_server.HEALTHCHECK_PING_INTERVAL


def test_claim_ping_slot_false_when_another_worker_holds_it():
    with patch('web.server.redis_client') as mock_redis:
        mock_redis.set.return_value = None  # redis-py returns None when NX fails

        assert web_server._claim_ping_slot() is False


def test_healthcheck_loop_pings_after_each_sleep():
    with patch('web.server.time.sleep', side_effect=[None, StopIteration]) as mock_sleep, \
         patch('web.server._claim_ping_slot', return_value=True), \
         patch('web.server._ping_healthcheck') as mock_ping:
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    assert mock_sleep.call_count == 2
    mock_ping.assert_called_once_with()


def test_healthcheck_loop_skips_ping_when_slot_already_taken():
    with patch('web.server.time.sleep', side_effect=[None, StopIteration]), \
         patch('web.server._claim_ping_slot', return_value=False), \
         patch('web.server._ping_healthcheck') as mock_ping:
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    mock_ping.assert_not_called()


def test_healthcheck_loop_withholds_ping_when_redis_is_down(caplog):
    """Redis down means /api can serve nothing, so withholding the ping is the
    point: healthchecks.io must go red instead of staying falsely green."""
    caplog.set_level(logging.WARNING)

    with patch('web.server.time.sleep', side_effect=[None, StopIteration]), \
         patch('web.server._claim_ping_slot', side_effect=ConnectionError('redis down')), \
         patch('web.server._ping_healthcheck') as mock_ping:
        with pytest.raises(StopIteration):
            web_server._healthcheck_loop()

    mock_ping.assert_not_called()
    assert "Redis unreachable" in caplog.text


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

# --------------------------------------------------------------------------
# error pages
# --------------------------------------------------------------------------

def test_unknown_url_renders_the_branded_404_page(client):
    response = client.get('/no-such-page')
    body = response.get_data(as_text=True)

    assert response.status_code == 404
    assert '404' in body
    assert 'Сторінку не знайдено' in body


def test_error_page_offers_a_way_to_return_home(client):
    body = client.get('/no-such-page').get_data(as_text=True)

    assert 'На головну' in body
    assert 'href="/"' in body


def test_unhandled_exception_renders_the_500_page():
    """TESTING=True re-raises instead of rendering, so the handler needs a
    plain app to run against."""
    flask_app = create_app(init_db=False, start_healthcheck=False)

    @flask_app.route('/boom')
    def boom():
        raise RuntimeError('kaboom')

    response = flask_app.test_client().get('/boom')

    assert response.status_code == 500
    assert '500' in response.get_data(as_text=True)
    assert 'Щось зламалось у нас' in response.get_data(as_text=True)
    assert 'На головну' in response.get_data(as_text=True)


# --------------------------------------------------------------------------
# /report-error
# --------------------------------------------------------------------------

VALID_REPORT = {
    'category': 'Сповіщення',
    'sub_option_notification': 'Опіздало',
    'sub_option_map': 'Зовсім не відображається',
    'city': 'Київ',
    'message': 'Сирена о 3:00 прийшла на 10 хвилин пізніше',
    'contact': '@reporter',
}


@pytest.fixture
def report_deps():
    """Everything a submission touches: the rate limiter, the write and the ping."""
    with patch('web.server._claim_report_slot', return_value=True), \
         patch('web.server.get_db') as mock_get_db, \
         patch('web.server.save_error_report') as mock_save, \
         patch('web.server._notify_admin') as mock_notify:
        yield mock_get_db, mock_save, mock_notify


def test_report_form_is_served(client):
    response = client.get('/report-error')

    assert response.status_code == 200
    assert 'Повідомити про помилку' in response.get_data(as_text=True)


def test_valid_report_is_stored_and_confirmed(client, report_deps):
    mock_get_db, mock_save, mock_notify = report_deps

    response = client.post('/report-error', data=VALID_REPORT)

    assert response.status_code == 200
    assert SUCCESS_MARKER in response.get_data(as_text=True)
    mock_save.assert_called_once_with(
        mock_get_db.return_value,
        category='Сповіщення',
        sub_option='Опіздало',
        city='Київ',
        message='Сирена о 3:00 прийшла на 10 хвилин пізніше',
        contact='@reporter',
    )
    mock_notify.assert_called_once()


def test_valid_report_with_new_form_fields(client, report_deps):
    mock_get_db, mock_save, mock_notify = report_deps

    response = client.post('/report-error', data={
        'category': 'Мапа',
        'sub_option': 'Тривога не зникає з мапи',
        'city': 'Харків',
        'comment': 'Зависла сирена',
        'tg': '@user',
    })

    assert response.status_code == 200
    assert SUCCESS_MARKER in response.get_data(as_text=True)
    mock_save.assert_called_once_with(
        mock_get_db.return_value,
        category='Мапа тривог',
        sub_option='Тривога не зникає з мапи',
        city='Харків',
        message='Зависла сирена',
        contact='@user',
    )
    mock_notify.assert_called_once()


def test_report_keeps_only_the_sub_option_of_the_chosen_category(client, report_deps):
    """Both radio groups are always submitted; the hidden one is noise."""
    _, mock_save, _ = report_deps

    client.post('/report-error', data={**VALID_REPORT, 'category': 'Мапа тривог',
                                       'sub_option_map': 'Неправильний статус регіону'})

    assert mock_save.call_args.kwargs['sub_option'] == 'Неправильний статус регіону'


def test_report_drops_the_city_when_the_map_does_not_render_at_all(client, report_deps):
    """The form hides and clears the city field for this answer, so a city that
    arrives anyway is stale."""
    _, mock_save, _ = report_deps

    response = client.post('/report-error', data={
        **VALID_REPORT,
        'category': 'Мапа тривог',
        'sub_option_map': 'Зовсім не відображається',
        'city': '',
    })

    assert response.status_code == 200
    assert mock_save.call_args.kwargs['city'] == ''


def test_report_without_a_city_is_rejected(client, report_deps):
    _, mock_save, _ = report_deps

    response = client.post('/report-error', data={**VALID_REPORT, 'city': ''})

    assert response.status_code == 400
    mock_save.assert_not_called()


def test_other_category_needs_a_description(client, report_deps):
    _, mock_save, _ = report_deps

    response = client.post('/report-error', data={**VALID_REPORT, 'category': 'Інше', 'message': ''})

    assert response.status_code == 400
    mock_save.assert_not_called()


def test_unknown_category_is_rejected(client, report_deps):
    _, mock_save, _ = report_deps

    response = client.post('/report-error', data={**VALID_REPORT, 'category': 'Хакер'})

    assert response.status_code == 400
    mock_save.assert_not_called()


@pytest.mark.parametrize("overrides, expected", [
    ({'city': ''}, 'Будь ласка, вкажіть місто.'),
    ({'category': 'Інше', 'message': ''}, 'Опис помилки обовʼязковий для цієї категорії.'),
    ({'category': 'Хакер'}, 'Оберіть категорію помилки.'),
])
def test_rejection_messages(app, overrides, expected):
    """The wording lives in the validator, not the page: the form renders only
    its own client-side errors."""
    with app.test_request_context('/report-error', method='POST',
                                  data={**VALID_REPORT, **overrides}):
        report, error = web_server._clean_report_form(request.form)

    assert report == {}
    assert error == expected


def test_overlong_fields_are_truncated_to_the_column_budget(client, report_deps):
    _, mock_save, _ = report_deps

    client.post('/report-error', data={**VALID_REPORT, 'message': 'я' * 5000})

    assert len(mock_save.call_args.kwargs['message']) == web_server.REPORT_FIELD_LIMITS['message']


def test_report_is_refused_once_the_client_runs_out_of_slots(client):
    with patch('web.server._claim_report_slot', return_value=False), \
         patch('web.server.save_error_report') as mock_save:
        response = client.post('/report-error', data=VALID_REPORT)

    assert response.status_code == 429
    assert 'Забагато повідомлень' in response.get_data(as_text=True)
    mock_save.assert_not_called()


# --------------------------------------------------------------------------
# report rate limiting
# --------------------------------------------------------------------------

def test_rate_limit_window_is_set_on_the_first_report_only(app):
    with patch('web.server.redis_client') as mock_redis:
        mock_redis.incr.side_effect = [1, 2]

        with app.test_request_context('/report-error', method='POST'):
            assert web_server._claim_report_slot() is True
            assert web_server._claim_report_slot() is True

    mock_redis.expire.assert_called_once_with(
        mock_redis.incr.call_args.args[0], web_server.REPORT_RATE_WINDOW
    )


def test_rate_limit_rejects_past_the_allowance(app):
    with patch('web.server.redis_client') as mock_redis:
        mock_redis.incr.return_value = web_server.REPORT_RATE_LIMIT + 1

        with app.test_request_context('/report-error', method='POST'):
            assert web_server._claim_report_slot() is False


def test_rate_limit_lets_reports_through_when_redis_is_down(app, caplog):
    """Losing a genuine report costs more than letting a flood through."""
    caplog.set_level(logging.WARNING)

    with patch('web.server.redis_client') as mock_redis:
        mock_redis.incr.side_effect = ConnectionError('redis down')

        with app.test_request_context('/report-error', method='POST'):
            assert web_server._claim_report_slot() is True

    assert "skipping report rate limit" in caplog.text


def test_rate_limit_keys_on_the_cloudflare_client_ip(app):
    with patch('web.server.redis_client') as mock_redis:
        mock_redis.incr.return_value = 1

        with app.test_request_context('/report-error', method='POST',
                                      headers={'CF-Connecting-IP': '203.0.113.7'}):
            web_server._claim_report_slot()

    assert '203.0.113.7' in mock_redis.incr.call_args.args[0]


# --------------------------------------------------------------------------
# admin notification
# --------------------------------------------------------------------------

REPORT = {
    'category': 'Сповіщення',
    'sub_option': 'Опіздало',
    'city': 'Київ',
    'message': '',
    'contact': '@reporter',
}


def test_admin_notification_is_skipped_when_unconfigured(monkeypatch):
    monkeypatch.setattr(web_server, 'TELEGRAM_BOT_TOKEN', '')
    monkeypatch.setattr(web_server, 'ADMIN_CHAT_ID', '123')

    with patch('web.server.requests.post') as mock_post:
        web_server._notify_admin(REPORT)

    mock_post.assert_not_called()


def test_admin_notification_lists_only_the_filled_in_fields(monkeypatch):
    monkeypatch.setattr(web_server, 'TELEGRAM_BOT_TOKEN', 'bot-token')
    monkeypatch.setattr(web_server, 'ADMIN_CHAT_ID', '123')

    with patch('web.server.requests.post') as mock_post:
        web_server._notify_admin(REPORT)

    _, kwargs = mock_post.call_args
    text = kwargs['json']['text']
    assert kwargs['json']['chat_id'] == '123'
    assert 'Місто: Київ' in text
    assert 'Контакт: @reporter' in text
    assert 'Коментар' not in text


def test_admin_notification_failure_does_not_break_the_submission(monkeypatch, caplog):
    """The report is already in PostgreSQL by then; Telegram is a convenience."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(web_server, 'TELEGRAM_BOT_TOKEN', 'bot-token')
    monkeypatch.setattr(web_server, 'ADMIN_CHAT_ID', '123')

    with patch('web.server.requests.post', side_effect=Exception('telegram down')):
        web_server._notify_admin(REPORT)

    assert "Failed to forward an error report to Telegram" in caplog.text
