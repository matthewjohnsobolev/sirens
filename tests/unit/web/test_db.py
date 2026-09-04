"""Unit tests for web.db (schema, rehydration, and the /api threat snapshot)."""

import datetime
import logging
import re
from unittest.mock import MagicMock, patch

import pytest

from config import DATABASE_URL
from domain import (
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    REGION_CONFIG,
    real_channels,
)
from web.db import (
    SCHEMA_LOCK_KEY,
    ensure_pg_tables,
    get_all_threats_data,
    get_pg_conn,
    rehydrate_state_from_db,
)

TIME_RE = re.compile(r"\d{2}:\d{2}")
KYIV_CHANNEL = real_channels["kyiv"]

def test_get_pg_conn_uses_configured_database_url():
    with patch("web.db.psycopg2.connect") as mock_connect:
        conn = get_pg_conn()

    assert conn is mock_connect.return_value
    mock_connect.assert_called_once_with(DATABASE_URL)


def test_ensure_pg_tables_serializes_concurrent_creators(mock_web_pg):
    _, mock_cursor = mock_web_pg

    ensure_pg_tables()

    first_sql, first_params = mock_cursor.execute.call_args_list[0].args
    assert "pg_advisory_xact_lock" in first_sql
    assert first_params == (SCHEMA_LOCK_KEY,)


def test_ensure_pg_tables_creates_alert_history(mock_web_pg):
    mock_conn, mock_cursor = mock_web_pg

    ensure_pg_tables()

    sql = "\n".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS alert_history" in sql
    for column in ("datetime", "date", "time", "district_key", "oblast_key", "type"):
        assert column in sql
    mock_conn.commit.assert_called_once()


def test_ensure_pg_tables_creates_subscribers(mock_web_pg):
    _, mock_cursor = mock_web_pg

    ensure_pg_tables()

    sql = "\n".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS subscribers" in sql
    for column in ("channel_key", "channel_id", "subscribers", "date", "time"):
        assert column in sql
    assert "UNIQUE (channel_key, time)" in sql
    assert "CREATE INDEX IF NOT EXISTS subscribers_date_idx" in sql
    assert "CREATE INDEX IF NOT EXISTS subscribers_time_idx" in sql


def test_ensure_pg_tables_leaves_issue_reports_to_sentry(mock_web_pg):
    """Issue submissions are forwarded directly to Sentry rather than stored in PostgreSQL."""
    _, mock_cursor = mock_web_pg

    ensure_pg_tables()

    sql = "\n".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "error_reports" not in sql


def test_ensure_pg_tables_raises_and_logs_when_pg_is_unreachable(caplog):
    caplog.set_level(logging.ERROR)

    with patch("web.db.get_pg_conn", side_effect=OSError("connection refused")):
        with pytest.raises(OSError):
            ensure_pg_tables()

    assert "Failed to ensure the database schema exists" in caplog.text

def test_rehydrate_state_from_db(mock_web_pg, mock_web_redis):
    mock_conn, mock_cursor = mock_web_pg
    now = datetime.datetime.now()
    mock_cursor.fetchall.return_value = [
        ("kyiv", "kyiv", "air_raid_alert", "14:00", now, "https://t.me/kyiv_alert/42"),
        ("lviv", "lviv_oblast", "air_raid_alert_cancelled", "13:00", now, None),
        (None, "odesa_oblast", "start", "12:00", now, None),
        (
            "nikopol",
            "dnipropetrovsk_oblast",
            "threat_of_shelling",
            "11:00",
            now,
            "https://t.me/nikopol_alert/7",
        ),
    ]

    pipeline = MagicMock()
    mock_web_redis.pipeline.return_value = pipeline

    rehydrate_state_from_db()

    city_calls = [
        c for c in pipeline.hset.call_args_list if c.args and c.args[0] == "threat:alerts:city:kyiv"
    ]
    assert len(city_calls) == 1
    mapping = city_calls[0].kwargs["mapping"]
    assert mapping["status"] == "true"
    assert mapping["time"] == "14:00"
    assert mapping["source"] == "https://t.me/kyiv_alert/42"
    assert mapping["type"] == "air_raid_alert"
    assert "updated_at" in mapping

    lviv_calls = [
        c for c in pipeline.hset.call_args_list if c.args and c.args[0] == "threat:alerts:city:lviv"
    ]
    assert lviv_calls[0].kwargs["mapping"]["source"] == "telegram"

    shelling_calls = [
        c
        for c in pipeline.hset.call_args_list
        if c.args and c.args[0] == "threat:shellings:nikopol"
    ]
    assert len(shelling_calls) == 1
    assert shelling_calls[0].kwargs["mapping"]["status"] == "true"
    assert shelling_calls[0].kwargs["mapping"]["source"] == "https://t.me/nikopol_alert/7"
    assert "updated_at" in shelling_calls[0].kwargs["mapping"]

    pipeline.sadd.assert_any_call("threat:alerts:active:kyiv", "kyiv")
    pipeline.set.assert_called_with("system:state_initialized", "true")
    pipeline.execute.assert_called_once()


def test_rehydrate_state_from_db_logs_and_raises_on_error(mock_web_pg, caplog):
    caplog.set_level(logging.ERROR)

    with patch("web.db.get_pg_conn", side_effect=OSError("pg down")):
        with pytest.raises(OSError):
            rehydrate_state_from_db()

    assert "Failed to query alert_history for rehydration" in caplog.text


class _FakePipeline:
    def __init__(self, store, sets=None):
        self._store = store
        self._sets = sets or {}
        self.operations = []

    def hgetall(self, key):
        self.operations.append(("hgetall", key))
        return self

    def smembers(self, key):
        self.operations.append(("smembers", key))
        return self

    def execute(self):
        results = []
        for op, key in self.operations:
            if op == "hgetall":
                results.append(dict(self._store.get(key, {})))
            elif op == "smembers":
                results.append(set(self._sets.get(key, set())))
        return results


@pytest.fixture
def threats_store(mock_web_redis):
    store = {
        "threat:alerts:kyiv": {
            "status": "true",
            "time": "10:00",
            "source": "telegram",
            "updated_at": "1000",
        },
        "threat:alerts:dnipropetrovsk_oblast": {
            "status": "true",
            "time": "11:00",
            "source": "tg-dnipro",
            "updated_at": "1000",
        },
        "threat:alerts:kherson_oblast": {
            "status": "true",
            "time": "12:00",
            "source": "tg-kherson",
            "updated_at": "1000",
        },
        "threat:alerts:lviv_oblast": {
            "status": "false",
            "time": "09:00",
            "source": "tg-lviv",
            "updated_at": "1000",
        },
        "threat:explosions:dnipropetrovsk_oblast": {
            "status": "true",
            "time": "11:30",
            "source": "ex-dnipro",
            "updated_at": "1000",
        },
        "threat:shellings:nikopol": {
            "status": "true",
            "time": "11:45",
            "source": "sh-nikopol",
            "updated_at": "1000",
        },
        "threat:shellings:kherson": {
            "status": "false",
            "time": "12:15",
            "source": "sh-kherson",
            "updated_at": "1000",
        },
    }
    sets = {
        "threat:alerts:active:kyiv": {"kyiv"},
        "threat:alerts:active:dnipropetrovsk_oblast": {"nikopol"},
    }
    pipeline = _FakePipeline(store, sets)
    mock_web_redis.pipeline.return_value = pipeline
    return pipeline


def test_get_all_threats_data_raises_and_logs_when_redis_is_down(threats_store, caplog):
    caplog.set_level(logging.ERROR)

    with patch.object(threats_store, "execute", side_effect=ConnectionError("redis down")):
        with pytest.raises(ConnectionError):
            get_all_threats_data()

    assert "Failed to read threat data from Redis" in caplog.text


def test_get_all_threats_data_queries_every_table_and_oblast(threats_store):
    get_all_threats_data()

    keys = [k for _, k in threats_store.operations]
    for table in ("alerts", "explosions", "shellings"):
        assert f"threat:{table}:kyiv" in keys


def test_get_all_threats_data_normalises_status(threats_store):
    result = get_all_threats_data()

    assert result["kyiv"]["alert"]["status"] is True
    assert result["kyiv"]["alert"]["time"] == "10:00"
    assert result["kyiv"]["alert"]["updated_at"] == 1000
    assert result["lviv_oblast"]["alert"]["status"] is False


def test_get_all_threats_data_defaults_missing_keys(threats_store):
    result = get_all_threats_data()

    assert result["crimea"]["alert"]["status"] is False
    assert result["crimea"]["alert"]["updated_at"] == 0
    assert result["crimea"]["explosion"]["status"] is False
    assert result["crimea"]["explosion"]["updated_at"] == 0


@pytest.mark.parametrize(
    "city, parent_oblast",
    [
        ("nikopol", "dnipropetrovsk_oblast"),
        ("kherson", "kherson_oblast"),
    ],
)
def test_get_all_threats_data_maps_cities_to_parent_oblast(threats_store, city, parent_oblast):
    result = get_all_threats_data()

    assert result[city]["alert"] == result[parent_oblast]["alert"]
    assert result[city]["explosion"] == result[parent_oblast]["explosion"]


def test_get_all_threats_data_aggregates_shelling(threats_store):
    result = get_all_threats_data()

    assert result["nikopol"]["shelling"]["status"] is True
    assert result["kherson"]["shelling"]["status"] is False
    assert result["dnipropetrovsk_oblast"]["shelling"]["status"] is True
    assert result["kyiv"]["shelling"]["status"] is False


def test_get_all_threats_data_coverage_partial(mock_web_redis):
    store = {
        "threat:alerts:city:bucha": {"status": "true", "time": "12:00", "updated_at": "100"},
    }
    sets = {
        "threat:alerts:active:kyiv_oblast": {"bucha"},
    }
    mock_web_redis.pipeline.return_value = _FakePipeline(store, sets)
    result = get_all_threats_data()

    kyiv_obl = result["kyiv_oblast"]
    assert kyiv_obl["alert"]["status"] is True
    assert kyiv_obl["alert"]["coverage"] == "partial"
    assert kyiv_obl["alert"]["active_districts"] == ["bucha"]
    assert set(kyiv_obl["alert"]["tracked_districts"]) == set(DISTRICTS_BY_OBLAST["kyiv_oblast"])
    assert "bucha" in kyiv_obl["districts"]
    assert kyiv_obl["districts"]["bucha"]["alert"]["status"] is True


def test_get_all_threats_data_coverage_full(mock_web_redis):
    store = {}
    sets = {
        "threat:alerts:active:volyn_oblast": set(DISTRICTS_BY_OBLAST["volyn_oblast"]),
        "threat:alerts:active:lviv_oblast": set(DISTRICTS_BY_OBLAST["lviv_oblast"]),
    }
    mock_web_redis.pipeline.return_value = _FakePipeline(store, sets)
    result = get_all_threats_data()

    assert result["volyn_oblast"]["alert"]["coverage"] == "full"
    assert result["lviv_oblast"]["alert"]["coverage"] == "full"
    assert result["crimea"]["alert"]["coverage"] == "none"
    assert result["crimea"]["alert"]["active_districts"] == []
    assert result["crimea"]["alert"]["tracked_districts"] == []


def test_get_all_threats_data_carries_district_names(mock_web_redis):
    """Oblast popups label items using district names from /api."""
    mock_web_redis.pipeline.return_value = _FakePipeline({}, {})
    result = get_all_threats_data()

    districts = result["kyiv_oblast"]["districts"]
    assert districts["bucha"]["name"] == "Бучанський район"
    assert districts["vyshhorod"]["name"] == "Вишгородський район"
    assert all(entry["name"] == DISTRICT_CONFIG[key]["name"] for key, entry in districts.items())


def test_get_all_threats_data_covers_every_district(mock_web_redis):
    """The map tracks all districts, not just those with broadcast channels."""
    mock_web_redis.pipeline.return_value = _FakePipeline({}, {})
    result = get_all_threats_data()

    tracked = {key for oblast in DISTRICTS_BY_OBLAST for key in result[oblast]["districts"]}
    assert tracked == set(DISTRICT_CONFIG)
    assert set(REGION_CONFIG) < tracked


def test_get_all_threats_data_filters_untracked_from_active_districts(mock_web_redis):
    store = {}
    sets = {
        "threat:alerts:active:kyiv_oblast": {"bucha", "nonexistent_district"},
    }
    mock_web_redis.pipeline.return_value = _FakePipeline(store, sets)
    result = get_all_threats_data()

    assert result["kyiv_oblast"]["alert"]["active_districts"] == ["bucha"]
    assert result["kyiv_oblast"]["alert"]["coverage"] == "partial"


def test_aggregate_shelling_selects_latest():
    from web.db import DEFAULT_THREAT, _aggregate_shelling

    districts_empty = {}
    assert _aggregate_shelling(districts_empty) == DEFAULT_THREAT

    districts_no_active = {
        "d1": {"shelling": {"status": False, "time": "10:00", "updated_at": 50}},
    }
    assert _aggregate_shelling(districts_no_active) == DEFAULT_THREAT

    districts_multi = {
        "d1": {"shelling": {"status": True, "time": "10:00", "source": "s1", "updated_at": 100}},
        "d2": {"shelling": {"status": True, "time": "11:00", "source": "s2", "updated_at": 200}},
        "d3": {"shelling": {"status": False, "time": "12:00", "source": "s3", "updated_at": 300}},
    }
    agg = _aggregate_shelling(districts_multi)
    assert agg["status"] is True
    assert agg["time"] == "11:00"
    assert agg["source"] == "s2"
    assert agg["updated_at"] == 200
