import importlib
from unittest.mock import patch

import pytest

import config


@pytest.fixture(autouse=True)
def _mock_load_dotenv():
    with patch("dotenv.load_dotenv"):
        yield


def test_config_paths():
    assert config.PROJECT_ROOT.exists()
    assert config.IMAGES_PATH.name == "img"
    assert config.SESSION_PATH.name == "sessions"
    assert config.LOGS_PATH.name == "logs"
    assert config.VERSION == "1.1.0"


def test_config_r2_endpoint_defaults_when_account_id_set(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.delenv("CLOUDFLARE_R2_S3_ENDPOINT", raising=False)

    importlib.reload(config)

    assert config.CLOUDFLARE_R2_S3_ENDPOINT == "https://account123.r2.cloudflarestorage.com"


def test_config_cloudflare_r2_custom_endpoint(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.setenv("CLOUDFLARE_R2_S3_ENDPOINT", "https://custom.endpoint")

    importlib.reload(config)

    assert config.CLOUDFLARE_R2_S3_ENDPOINT == "https://custom.endpoint"


def test_config_cloudflare_r2_keys_and_buckets(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "cf-key-id")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "cf-secret")
    monkeypatch.setenv("CLOUDFLARE_R2_BI_DATA_BUCKET", "cf-data-bucket")
    monkeypatch.setenv("CLOUDFLARE_R2_BI_WEB_BUCKET", "cf-web-bucket")

    importlib.reload(config)

    assert config.CLOUDFLARE_R2_ACCESS_KEY_ID == "cf-key-id"
    assert config.CLOUDFLARE_R2_SECRET_ACCESS_KEY == "cf-secret"
    assert config.CLOUDFLARE_R2_BI_DATA_BUCKET == "cf-data-bucket"
    assert config.CLOUDFLARE_R2_BI_WEB_BUCKET == "cf-web-bucket"


def test_config_cloudflare_kv_keys(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-api-token-test")
    monkeypatch.setenv("CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "cf-kv-namespace-id")

    importlib.reload(config)

    assert config.CLOUDFLARE_API_TOKEN == "cf-api-token-test"
    assert config.CLOUDFLARE_TELEMETRY_NAMESPACE_ID == "cf-kv-namespace-id"


def test_config_healthchecks_keys(monkeypatch):
    monkeypatch.setenv("HEALTHCHECKS_API_KEY", "hc-key")
    monkeypatch.setenv("HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/source")
    monkeypatch.setenv("HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "https://hc-ping.com/bcast")
    monkeypatch.setenv("HEALTHCHECKS_WEB_PING_URL", "https://hc-ping.com/web")
    monkeypatch.setenv("HEALTHCHECKS_BACKUP_PING_URL", "https://hc-ping.com/backup")
    monkeypatch.setenv("HEALTHCHECKS_BI_PING_URL", "https://hc-ping.com/bi")

    importlib.reload(config)

    assert config.HEALTHCHECKS_API_KEY == "hc-key"
    assert config.HEALTHCHECKS_ALERTS_SOURCE_PING_URL == "https://hc-ping.com/source"
    assert config.HEALTHCHECKS_ALERTS_BROADCAST_PING_URL == "https://hc-ping.com/bcast"
    assert config.HEALTHCHECKS_WEB_PING_URL == "https://hc-ping.com/web"
    assert config.HEALTHCHECKS_BACKUP_PING_URL == "https://hc-ping.com/backup"
    assert config.HEALTHCHECKS_BI_PING_URL == "https://hc-ping.com/bi"


def test_config_uptimerobot_keys(monkeypatch):
    monkeypatch.setenv("UPTIMEROBOT_API_MONITOR_KEY", "ur-api")
    monkeypatch.setenv("UPTIMEROBOT_WEB_MONITOR_KEY", "ur-web")

    importlib.reload(config)

    assert config.UPTIMEROBOT_API_MONITOR_KEY == "ur-api"
    assert config.UPTIMEROBOT_WEB_MONITOR_KEY == "ur-web"


def test_config_app_and_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://sirens:pass@localhost:5432/sirens_prod")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")

    importlib.reload(config)

    assert config.APP_ENV == "production"
    assert config.DATABASE_URL == "postgresql://sirens:pass@localhost:5432/sirens_prod"
    assert config.REDIS_URL == "redis://localhost:6379/1"


def test_config_telegram_settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hashabc")

    importlib.reload(config)

    assert config.TELEGRAM_API_ID == "12345"
    assert config.TELEGRAM_API_HASH == "hashabc"


def test_config_github_repo_normalization(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "https://github.com/matthewjohnsobolev/sirens/")
    importlib.reload(config)
    assert config.GITHUB_REPO == "matthewjohnsobolev/sirens"

    monkeypatch.setenv("GITHUB_REPO", "git@github.com:matthewjohnsobolev/sirens")
    importlib.reload(config)
    assert config.GITHUB_REPO == "matthewjohnsobolev/sirens"
