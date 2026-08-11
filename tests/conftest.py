import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture(autouse=True)
def _neutralize_external_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_ID", "0")


@pytest.fixture(autouse=True)
def _isolate_alerts_globals():
    from alerts import main as alerts_main

    saved = (alerts_main.client, alerts_main.redis_client, alerts_main.pg_pool)
    alerts_main.running_tasks.clear()
    yield
    alerts_main.client, alerts_main.redis_client, alerts_main.pg_pool = saved
    alerts_main.running_tasks.clear()


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
