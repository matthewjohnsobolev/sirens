import importlib
import pytest
from unittest.mock import patch
import config


@pytest.fixture(autouse=True)
def _mock_load_dotenv():
    with patch('dotenv.load_dotenv'):
        yield


def test_config_r2_endpoint_defaults_to_eu_when_account_id_set(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.delenv("CLOUDFLARE_R2_ENDPOINT", raising=False)

    importlib.reload(config)

    assert config.R2_ENDPOINT == "https://account123.eu.r2.cloudflarestorage.com"


def test_config_cloudflare_r2_keys_and_bucket(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "cf-key-id")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "cf-secret")
    monkeypatch.setenv("CLOUDFLARE_R2_DATA_BUCKET", "cf-data-bucket")
    monkeypatch.setenv("CLOUDFLARE_R2_WEB_BUCKET", "cf-web-bucket")
    monkeypatch.setenv("CLOUDFLARE_R2_ENDPOINT", "https://cf.r2.endpoint")

    importlib.reload(config)

    assert config.R2_ACCESS_KEY_ID == "cf-key-id"
    assert config.R2_SECRET_ACCESS_KEY == "cf-secret"
    assert config.R2_DATA_BUCKET == "cf-data-bucket"
    assert config.R2_BUCKET == "cf-data-bucket"
    assert config.R2_WEB_BUCKET == "cf-web-bucket"
    assert config.R2_ENDPOINT == "https://cf.r2.endpoint"



def test_config_github_repo_normalization(monkeypatch):
    monkeypatch.setenv("GITHUB_REPO", "https://github.com/matthewjohnsobolev/sirens/")
    importlib.reload(config)
    assert config.GITHUB_REPO == "matthewjohnsobolev/sirens"

    monkeypatch.setenv("GITHUB_REPO", "git@github.com:matthewjohnsobolev/sirens")
    importlib.reload(config)
    assert config.GITHUB_REPO == "matthewjohnsobolev/sirens"


