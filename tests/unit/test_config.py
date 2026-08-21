import importlib
import pytest
from unittest.mock import patch
import config


@pytest.fixture(autouse=True)
def _mock_load_dotenv():
    with patch('dotenv.load_dotenv'):
        yield


def test_config_r2_endpoint_defaults_when_account_id_set(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account123")
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.delenv("CLOUDFLARE_R2_ENDPOINT", raising=False)

    importlib.reload(config)

    assert config.R2_ENDPOINT == "https://account123.r2.cloudflarestorage.com"



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


def test_config_districts_by_oblast_covers_every_district():
    assert set(config.DISTRICTS_BY_OBLAST['cherkasy_oblast']) == {
        'cherkasy', 'zvenyhorodka', 'zolotonosha', 'uman'
    }
    assert set(config.DISTRICTS_BY_OBLAST['kyiv_oblast']) == {
        'bilatserkva', 'boryspil', 'brovary', 'bucha', 'vyshhorod', 'obukhiv', 'fastiv'
    }
    assert set(config.DISTRICTS_BY_OBLAST['lviv_oblast']) == {
        'lviv', 'drohobych', 'zolochiv', 'sambir', 'stryi', 'chervonohrad', 'yavoriv'
    }
    assert config.DISTRICTS_BY_OBLAST['kyiv'] == ['kyiv']
    assert sum(len(d) for d in config.DISTRICTS_BY_OBLAST.values()) == len(config.DISTRICT_CONFIG)


def test_config_occupied_regions_have_no_districts():
    """Крим, Севастополь, Донеччина й Луганщина лишаються поза довідником."""
    for region in ('crimea', 'sevastopol', 'donetsk_oblast', 'luhansk_oblast'):
        assert region not in config.DISTRICTS_BY_OBLAST


def test_config_region_config_is_the_broadcast_subset():
    """REGION_CONFIG - рівно ті райони, у яких є канал."""
    assert set(config.REGION_CONFIG) == config.BROADCAST_DISTRICTS
    assert config.BROADCAST_DISTRICTS <= set(config.DISTRICT_CONFIG)
    assert set(config.real_channels) == set(config.test_channels)
    assert all('display_name' in conf for conf in config.REGION_CONFIG.values())


def test_config_broadcast_triggers_keep_the_oblast_name():
    """Формат REGION_CONFIG незмінний: назва району плюс назва області."""
    assert config.REGION_CONFIG['bucha']['triggers'] == [
        'Бучанський район', 'Київська область'
    ]
    assert config.DISTRICT_CONFIG['bucha']['triggers'] == ['Бучанський район']


def test_config_triggers_cover_both_apostrophes():
    assert config.DISTRICT_CONFIG['kamianske']['triggers'] == [
        "Кам'янський район", "Кам\u2019янський район"
    ]
    assert config.DISTRICT_CONFIG['kupiansk']['triggers'] == [
        "Куп'янський район", "Куп\u2019янський район"
    ]


def test_config_renamed_districts_keep_their_former_name():
    for key, former in [
        ('zviahel', 'Новоград-Волинський район'),
        ('volodymyr', 'Володимир-Волинський район'),
        ('samar', 'Новомосковський район'),
        ('berestyn', 'Красноградський район'),
    ]:
        assert former in config.DISTRICT_CONFIG[key]['triggers']


def test_config_no_trigger_belongs_to_two_districts():
    """Однакова назва в двох областях зробила б зіставлення неоднозначним."""
    owners = {}
    for key, conf in config.DISTRICT_CONFIG.items():
        for trigger in conf['triggers']:
            owners.setdefault(trigger, []).append(key)

    assert {t: keys for t, keys in owners.items() if len(keys) > 1} == {}
