import datetime
import logging
import re

import pytest
from unittest.mock import patch

from config import DATABASE_URL, REGION_CONFIG, real_channels, test_channels
from web.db import (
    SCHEMA_LOCK_KEY,
    THREAT_TABLES,
    _validate_table,
    ensure_pg_tables,
    get_all_threats_data,

    get_pg_conn,
    get_region_by_channel_id,
    get_threat_source,
    get_threat_status,
    get_threat_time,
    reset_threat_status,
    update_alert_source,
    update_alert_status,
    update_explosion_source,
    update_shelling_source,
    update_threat_status,
)

TIME_RE = re.compile(r"\d{2}:\d{2}")

KYIV_CHANNEL = real_channels['kyiv']


# --------------------------------------------------------------------------
# get_region_by_channel_id
# --------------------------------------------------------------------------

def test_get_region_by_channel_id():
    assert get_region_by_channel_id(real_channels['kyiv']) == 'kyiv'
    assert get_region_by_channel_id(test_channels['source']) == 'source'
    assert get_region_by_channel_id(12345) is None


# --------------------------------------------------------------------------
# connection helper
# --------------------------------------------------------------------------

def test_get_pg_conn_uses_configured_database_url():
    with patch('web.db.psycopg2.connect') as mock_connect:
        conn = get_pg_conn()

    assert conn is mock_connect.return_value
    mock_connect.assert_called_once_with(DATABASE_URL)


# --------------------------------------------------------------------------
# ensure_pg_tables
# --------------------------------------------------------------------------

def test_ensure_pg_tables_serializes_concurrent_creators(mock_web_pg):
    """Three gunicorn workers and the bi job all call this. CREATE TABLE IF NOT
    EXISTS is not atomic against a concurrent creator - without the lock one of
    them dies on "duplicate key ... pg_class_relname_nsp_index"."""
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
    for column in ("datetime", "date", "time", "oblast", "type"):
        assert column in sql
    mock_conn.commit.assert_called_once()


def test_ensure_pg_tables_creates_subscribers(mock_web_pg):
    """The UNIQUE constraint is the load-bearing part: it is what lets the
    snapshot re-run without duplicating rows."""
    _, mock_cursor = mock_web_pg

    ensure_pg_tables()

    sql = "\n".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS subscribers" in sql
    for column in ("channel_key", "channel_id", "subscribers", "date", "collected_at"):
        assert column in sql
    assert "UNIQUE (channel_key, collected_at)" in sql
    assert "CREATE INDEX IF NOT EXISTS subscribers_date_idx" in sql
    assert "CREATE INDEX IF NOT EXISTS subscribers_collected_at_idx" in sql



def test_ensure_pg_tables_raises_and_logs_when_pg_is_unreachable(caplog):
    caplog.set_level(logging.ERROR)

    with patch('web.db.get_pg_conn', side_effect=OSError('connection refused')):
        with pytest.raises(OSError):
            ensure_pg_tables()

    assert "Failed to ensure the database schema exists" in caplog.text


# --------------------------------------------------------------------------
# _validate_table - guards the Redis key namespace
# --------------------------------------------------------------------------

@pytest.mark.parametrize("table", sorted(THREAT_TABLES))
def test_validate_table_accepts_known_tables(table):
    _validate_table(table)  # must not raise


@pytest.mark.parametrize("func, args", [
    (get_threat_status, ("bad_table", "kyiv")),
    (get_threat_time, ("bad_table", "kyiv")),
    (get_threat_source, ("bad_table", "kyiv")),
    (update_threat_status, ("bad_table", "kyiv")),
    (reset_threat_status, ("bad_table", "kyiv")),
])
def test_threat_helpers_reject_unknown_table(mock_web_redis, func, args):
    with pytest.raises(ValueError, match="Invalid threat table: bad_table"):
        func(*args)

    mock_web_redis.hget.assert_not_called()
    mock_web_redis.hset.assert_not_called()


# --------------------------------------------------------------------------
# reading threat fields
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("1", 1), ("true", 1), ("TRUE", 1), ("active", 1), ("Active", 1),
    ("0", 0), ("false", 0), ("", 0), ("nonsense", 0), (None, 0),
])
def test_get_threat_status_normalisation(mock_web_redis, raw, expected):
    mock_web_redis.hget.return_value = raw

    assert get_threat_status("alerts", "kyiv") == expected
    mock_web_redis.hget.assert_called_once_with("threat:alerts:kyiv", "status")


def test_get_threat_time_returns_stored_value(mock_web_redis):
    mock_web_redis.hget.return_value = "12:30"

    assert get_threat_time("alerts", "kyiv") == "12:30"
    mock_web_redis.hget.assert_called_once_with("threat:alerts:kyiv", "time")


def test_get_threat_source_defaults_to_none_string(mock_web_redis):
    mock_web_redis.hget.return_value = None

    assert get_threat_source("explosions", "kyiv") == "None"
    mock_web_redis.hget.assert_called_once_with("threat:explosions:kyiv", "source")


# --------------------------------------------------------------------------
# writing threat fields
# --------------------------------------------------------------------------

def test_update_threat_status(mock_web_redis):
    update_threat_status("alerts", "kyiv", status=1, time_val="12:00")

    mock_web_redis.hset.assert_called_once_with(
        "threat:alerts:kyiv",
        mapping={"status": "1", "time": "12:00"},
    )


def test_update_threat_status_includes_source_when_given(mock_web_redis):
    update_threat_status("explosions", "kyiv", status=1, time_val="12:00", source_val="https://t.me/x/1")

    mock_web_redis.hset.assert_called_once_with(
        "threat:explosions:kyiv",
        mapping={"status": "1", "time": "12:00", "source": "https://t.me/x/1"},
    )


def test_update_threat_status_defaults_time_to_now(mock_web_redis):
    update_threat_status("alerts", "kyiv", status=1)

    assert mock_web_redis.hset.call_args.args[0] == "threat:alerts:kyiv"
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert mapping["status"] == "1"
    assert TIME_RE.fullmatch(mapping["time"])
    assert "source" not in mapping


def test_reset_threat_status(mock_web_redis):
    reset_threat_status("alerts", "kyiv")

    mock_web_redis.hset.assert_called_once_with(
        "threat:alerts:kyiv",
        mapping={"status": "0", "time": "None", "source": "None"},
    )


# --------------------------------------------------------------------------
# source links
# --------------------------------------------------------------------------

@pytest.mark.parametrize("func, table", [
    (update_explosion_source, "explosions"),
    (update_shelling_source, "shellings"),
])
def test_update_threat_source_marks_threat_active(mock_web_redis, func, table):
    func('kyiv', 'https://t.me/channel/1')

    assert mock_web_redis.hset.call_args.args[0] == f"threat:{table}:kyiv"
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert mapping["source"] == 'https://t.me/channel/1'
    assert mapping["status"] == "1"
    assert TIME_RE.fullmatch(mapping["time"])


def test_update_alert_source_writes_single_field(mock_web_redis):
    update_alert_source(KYIV_CHANNEL, 'https://t.me/channel/1')

    # note: this one sets a single field, it must not clobber status/time
    mock_web_redis.hset.assert_called_once_with(
        "threat:alerts:kyiv", "source", 'https://t.me/channel/1'
    )


@pytest.mark.parametrize("channel_id", [
    pytest.param(12345, id="unknown-channel"),
    pytest.param(real_channels['source'], id="region-missing-from-region-config"),
])
def test_update_alert_source_ignores_unmapped_channels(mock_web_redis, channel_id):
    update_alert_source(channel_id, 'https://t.me/channel/1')

    mock_web_redis.hset.assert_not_called()


# --------------------------------------------------------------------------
# update_alert_status
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status_text, expected_status, expected_event", [
    ("Повітряна тривога", "1", "start"),
    ("Відбій повітряної тривоги", "0", "end"),
])
async def test_update_alert_status_writes_redis_and_history(
    mock_web_redis, mock_web_pg, status_text, expected_status, expected_event
):
    mock_conn, mock_cursor = mock_web_pg

    await update_alert_status(KYIV_CHANNEL, status_text)

    assert mock_web_redis.hset.call_args.args[0] == "threat:alerts:kyiv"
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert mapping["status"] == expected_status
    assert TIME_RE.fullmatch(mapping["time"])

    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args.args
    assert "INSERT INTO alert_history" in sql
    assert params[2] == mapping["time"]
    assert params[3] == REGION_CONFIG['kyiv']['triggers'][0]
    assert params[4] == expected_event
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_alert_status_raises_and_logs_when_history_write_fails(
    mock_web_redis, mock_web_pg, caplog
):
    caplog.set_level(logging.ERROR)

    with patch('web.db.get_pg_conn', side_effect=OSError('connection refused')):
        with pytest.raises(OSError):
            await update_alert_status(KYIV_CHANNEL, "Повітряна тривога")

    assert "Failed to record alert start for kyiv in history" in caplog.text


@pytest.mark.asyncio
async def test_update_alert_status_unknown_text_updates_time_only(mock_web_redis, mock_web_pg):
    _, mock_cursor = mock_web_pg

    await update_alert_status(KYIV_CHANNEL, "Щось незрозуміле")

    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert "status" not in mapping
    assert TIME_RE.fullmatch(mapping["time"])
    mock_cursor.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel_id", [
    pytest.param(12345, id="unknown-channel"),
    pytest.param(real_channels['source'], id="region-missing-from-region-config"),
])
async def test_update_alert_status_ignores_unmapped_channels(
    mock_web_redis, mock_web_pg, channel_id
):
    _, mock_cursor = mock_web_pg

    await update_alert_status(channel_id, "Повітряна тривога")

    mock_web_redis.hset.assert_not_called()
    mock_cursor.execute.assert_not_called()


# --------------------------------------------------------------------------
# get_all_threats_data
# --------------------------------------------------------------------------

class _FakePipeline:

    def __init__(self, store):
        self._store = store
        self.requested_keys = []

    def hgetall(self, key):
        self.requested_keys.append(key)
        return self

    def execute(self):
        return [dict(self._store.get(key, {})) for key in self.requested_keys]


@pytest.fixture
def threats_store(mock_web_redis):
    store = {
        'threat:alerts:kyiv': {'status': 'true', 'time': '10:00', 'source': 'telegram'},
        'threat:alerts:dnipropetrovsk_oblast': {'status': '1', 'time': '11:00', 'source': 'tg-dnipro'},
        'threat:alerts:kherson_oblast': {'status': 'active', 'time': '12:00', 'source': 'tg-kherson'},
        'threat:alerts:lviv_oblast': {'status': '0', 'time': '09:00', 'source': 'tg-lviv'},
        'threat:explosions:dnipropetrovsk_oblast': {'status': '1', 'time': '11:30', 'source': 'ex-dnipro'},
        'threat:shellings:nikopol': {'status': '1', 'time': '11:45', 'source': 'sh-nikopol'},
        'threat:shellings:kherson': {'status': 'false', 'time': '12:15', 'source': 'sh-kherson'},
    }
    pipeline = _FakePipeline(store)
    mock_web_redis.pipeline.return_value = pipeline
    return pipeline


def test_get_all_threats_data_raises_and_logs_when_redis_is_down(threats_store, caplog):
    """The map must never degrade to zeros: an all-clear map drawn from a dead
    Redis reads as "no alerts anywhere", so the request has to fail instead."""
    caplog.set_level(logging.ERROR)

    with patch.object(threats_store, 'execute', side_effect=ConnectionError('redis down')):
        with pytest.raises(ConnectionError):
            get_all_threats_data()

    assert "Failed to read threat data from Redis" in caplog.text


def test_get_all_threats_data_queries_every_table_and_oblast(threats_store):
    get_all_threats_data()

    keys = threats_store.requested_keys
    assert len(keys) == len(set(keys)), "duplicate keys requested"
    for table in ("alerts", "explosions", "shellings"):
        assert f"threat:{table}:kyiv" in keys
        assert f"threat:{table}:nikopol" in keys
        assert f"threat:{table}:kherson" in keys


def test_get_all_threats_data_normalises_status(threats_store):
    result = get_all_threats_data()

    assert result['kyiv']['alert'] == {'status': 1, 'time': '10:00', 'source': 'telegram'}
    assert result['lviv_oblast']['alert'] == {'status': 0, 'time': '09:00', 'source': 'tg-lviv'}


def test_get_all_threats_data_defaults_missing_keys(threats_store):
    result = get_all_threats_data()

    assert result['crimea']['alert'] == {'status': 0, 'time': 'None', 'source': 'None'}
    assert result['crimea']['explosion'] == {'status': 0, 'time': 'None', 'source': 'None'}


@pytest.mark.parametrize("city, parent_oblast", [
    ('nikopol', 'dnipropetrovsk_oblast'),
    ('kherson', 'kherson_oblast'),
])
def test_get_all_threats_data_maps_cities_to_parent_oblast(threats_store, city, parent_oblast):
    result = get_all_threats_data()

    assert result[city]['alert'] == result[parent_oblast]['alert']
    assert result[city]['explosion'] == result[parent_oblast]['explosion']


def test_get_all_threats_data_attaches_shelling_to_cities_only(threats_store):
    result = get_all_threats_data()

    assert result['nikopol']['shelling'] == {'status': 1, 'time': '11:45', 'source': 'sh-nikopol'}
    assert result['kherson']['shelling'] == {'status': 0, 'time': '12:15', 'source': 'sh-kherson'}
    assert 'shelling' not in result['kyiv']
    assert 'shelling' not in result['dnipropetrovsk_oblast']


