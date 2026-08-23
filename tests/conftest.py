import os

for _external in (
    "SENTRY_DSN",
    "HEALTHCHECKS_PING_URL_ALERTS_SOURCE",
    "HEALTHCHECKS_PING_URL_ALERTS_BROADCAST",
    "HEALTHCHECKS_PING_URL_WEB",
    # Без цього фоновий потік оновлення статусу пішов би в реальний
    # healthchecks.io з ключем із .env розробника.
    "HEALTHCHECKS_API",
    "HEALTHCHECKS_READ_ONLY_API",
    "HEALTHCHECKS_API_KEY",
    # Те саме для другого провайдера.
    "UPTIMEROBOT_SIRENS_WEB_API",
    "UPTIMEROBOT_SIRENS_API_API",
):
    os.environ[_external] = ""

import pytest  # noqa: E402
from unittest.mock import AsyncMock, patch, MagicMock  # noqa: E402


@pytest.fixture(autouse=True)
def _neutralize_external_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "0")

    # Belt and braces on top of the env blanking above: a test that re-imports or
    # reassigns one of these still cannot reach the real Sentry/healthchecks.io.
    from alerts import main as alerts_main
    from bi import main as bi_main
    from web import server as web_server
    from web import status as web_status
    from web import uptime as web_uptime

    monkeypatch.setattr(alerts_main, "SENTRY_DSN", "", raising=False)
    monkeypatch.setattr(alerts_main, "HEALTHCHECKS_PING_URL_ALERTS_SOURCE", "", raising=False)
    monkeypatch.setattr(alerts_main, "HEALTHCHECKS_PING_URL_ALERTS_BROADCAST", "", raising=False)
    monkeypatch.setattr(bi_main, "SENTRY_DSN", "", raising=False)
    monkeypatch.setattr(bi_main, "R2_ACCESS_KEY_ID", "", raising=False)
    monkeypatch.setattr(bi_main, "R2_SECRET_ACCESS_KEY", "", raising=False)
    monkeypatch.setattr(bi_main, "GITHUB_PAT", "", raising=False)
    monkeypatch.setattr(web_server, "SENTRY_DSN", "", raising=False)
    monkeypatch.setattr(web_server, "HEALTHCHECKS_PING_URL_WEB", "", raising=False)
    monkeypatch.setattr(web_server, "HEALTHCHECKS_API", "", raising=False)
    monkeypatch.setattr(web_status, "HEALTHCHECKS_API", "", raising=False)
    monkeypatch.setattr(web_uptime, "UPTIMEROBOT_SIRENS_WEB_API", "", raising=False)
    monkeypatch.setattr(web_uptime, "UPTIMEROBOT_SIRENS_API_API", "", raising=False)



@pytest.fixture(autouse=True)
def _isolate_alerts_globals():
    from alerts import main as alerts_main

    saved = (alerts_main.client, alerts_main.redis_client, alerts_main.pg_pool)
    alerts_main.running_tasks.clear()
    # Стан моніторингу теж глобальний: без скидання мітка тиші й вердикт
    # бродкасту протікали б з тесту в тест.
    alerts_main.last_source_message_at = None
    alerts_main.last_broadcast_at = None
    alerts_main.source_silence_reported = False
    alerts_main.broadcast_silence_reported = False
    yield
    alerts_main.client, alerts_main.redis_client, alerts_main.pg_pool = saved
    alerts_main.running_tasks.clear()
    alerts_main.last_source_message_at = None
    alerts_main.last_broadcast_at = None
    alerts_main.source_silence_reported = False
    alerts_main.broadcast_silence_reported = False


@pytest.fixture
def mock_redis():
    with patch('alerts.main.redis_client', new_callable=AsyncMock) as mock_r:
        yield mock_r


@pytest.fixture
def mock_pg_pool():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_acquire

    with patch('alerts.main.pg_pool', mock_pool):
        yield mock_pool, mock_conn


@pytest.fixture
def bi_pool():
    """asyncpg pool double for the snapshot: `async with pool.acquire() as conn`."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_acquire

    return mock_pool, mock_conn


@pytest.fixture
def mock_telegram_client():
    with patch('alerts.main.client', new_callable=AsyncMock) as mock_c:
        yield mock_c


@pytest.fixture
def mock_web_redis():
    with patch('web.db.redis_client', MagicMock()) as mock_r:
        yield mock_r


@pytest.fixture
def mock_web_pg():
    """Stub web.db.get_pg_conn, yielding the connection and cursor mocks."""
    with patch('web.db.get_pg_conn') as mock_get_conn:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        yield mock_conn, mock_cursor


@pytest.fixture
def app():
    """A fresh app per test.

    init_db=False skips the schema bootstrap, so no test needs a live
    PostgreSQL. Building a new instance per test also stops config or route
    changes from leaking between tests.
    """
    from web.server import create_app

    flask_app = create_app(init_db=False)
    flask_app.config.update({
        'TESTING': True,
    })
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
