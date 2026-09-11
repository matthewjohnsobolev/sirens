"""
Unit tests for web.db (database schema, threat state caching, and rehydration).
"""

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
    test_channels,
)
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
    rehydrate_state_from_db,
    reset_threat_status,
    update_alert_source,
    update_alert_status,
    update_explosion_source,
    update_shelling_source,
    update_threat_status,
)

TIME_RE = re.compile(r"\d{2}:\d{2}")
KYIV_CHANNEL = real_channels["kyiv"]


def test_get_region_by_channel_id():
    assert get_region_by_channel_id(real_channels["kyiv"]) == "kyiv"
    assert get_region_by_channel_id(real_channels["lviv"]) == "lviv"
    assert get_region_by_channel_id(test_channels["poltava"]) == "poltava"
    assert get_region_by_channel_id(12345) is None


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
    for column in ("recorded_at", "event_type", "level", "district", "channel_id", "message_id", "source"):
        assert column in sql
    mock_conn.commit.assert_called_once()


def test_ensure_pg_tables_creates_subscribers(mock_web_pg):
    _, mock_cursor = mock_web_pg

    ensure_pg_tables()

    sql = "\n".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS subscriber_snapshots" in sql
    for column in ("channel", "channel_id", "subscriber_count", "collected_at"):
        assert column in sql
    assert "PRIMARY KEY (channel_id, collected_at)" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_subscriber_snapshots_collected_at" in sql


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


@pytest.mark.parametrize("table", sorted(THREAT_TABLES))
def test_validate_table_accepts_known_tables(table):
    _validate_table(table)


@pytest.mark.parametrize(
    "func, args",
    [
        (get_threat_status, ("bad_table", "kyiv")),
        (get_threat_time, ("bad_table", "kyiv")),
        (get_threat_source, ("bad_table", "kyiv")),
        (update_threat_status, ("bad_table", "kyiv")),
        (reset_threat_status, ("bad_table", "kyiv")),
    ],
)
def test_threat_helpers_reject_unknown_table(mock_web_redis, func, args):
    with pytest.raises(ValueError, match="Invalid threat table: bad_table"):
        func(*args)

    mock_web_redis.hget.assert_not_called()
    mock_web_redis.hset.assert_not_called()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("active", True),
        ("Active", True),
        ("0", False),
        ("false", False),
        ("", False),
        ("nonsense", False),
        (None, False),
    ],
)
def test_get_threat_status_normalisation(mock_web_redis, raw, expected):
    mock_web_redis.hget.return_value = raw

    assert get_threat_status("alerts", "kyiv") is expected
    mock_web_redis.hget.assert_called_once_with("threat:alerts:kyiv", "status")


def test_get_threat_time_returns_stored_value(mock_web_redis):
    mock_web_redis.hget.return_value = "12:30"

    assert get_threat_time("alerts", "kyiv") == "12:30"
    mock_web_redis.hget.assert_called_once_with("threat:alerts:kyiv", "time")


def test_get_threat_source_defaults_to_none_string(mock_web_redis):
    mock_web_redis.hget.return_value = None

    assert get_threat_source("explosions", "kyiv") == "None"
    mock_web_redis.hget.assert_called_once_with("threat:explosions:kyiv", "source")


def test_update_threat_status(mock_web_redis):
    update_threat_status("alerts", "kyiv", status=True, time_val="12:00")

    mock_web_redis.hset.assert_called_once()
    key = mock_web_redis.hset.call_args.args[0]
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert key == "threat:alerts:kyiv"
    assert mapping["status"] == "true"
    assert mapping["time"] == "12:00"
    assert "updated_at" in mapping


def test_update_threat_status_includes_source_when_given(mock_web_redis):
    update_threat_status(
        "explosions", "kyiv", status=True, time_val="12:00", source_val="https://t.me/x/1"
    )

    mock_web_redis.hset.assert_called_once()
    key = mock_web_redis.hset.call_args.args[0]
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert key == "threat:explosions:kyiv"
    assert mapping["status"] == "true"
    assert mapping["time"] == "12:00"
    assert mapping["source"] == "https://t.me/x/1"
    assert "updated_at" in mapping


def test_update_threat_status_defaults_time_to_now(mock_web_redis):
    update_threat_status("alerts", "kyiv", status=True)

    assert mock_web_redis.hset.call_args.args[0] == "threat:alerts:kyiv"
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert mapping["status"] == "true"
    assert TIME_RE.fullmatch(mapping["time"])
    assert "source" not in mapping
    assert "updated_at" in mapping


def test_reset_threat_status(mock_web_redis):
    reset_threat_status("alerts", "kyiv")

    mock_web_redis.hset.assert_called_once()
    key = mock_web_redis.hset.call_args.args[0]
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert key == "threat:alerts:kyiv"
    assert mapping["status"] == "false"
    assert mapping["time"] == "None"
    assert mapping["source"] == "None"
    assert "updated_at" in mapping


@pytest.mark.parametrize(
    "func, table",
    [
        (update_explosion_source, "explosions"),
        (update_shelling_source, "shellings"),
    ],
)
def test_update_threat_source_marks_threat_active(mock_web_redis, func, table):
    func("kyiv", "https://t.me/channel/1")

    assert mock_web_redis.hset.call_args.args[0] == f"threat:{table}:kyiv"
    mapping = mock_web_redis.hset.call_args.kwargs["mapping"]
    assert mapping["source"] == "https://t.me/channel/1"
    assert mapping["status"] == "true"
    assert TIME_RE.fullmatch(mapping["time"])
    assert "updated_at" in mapping


def test_update_alert_source_writes_single_field(mock_web_redis):
    update_alert_source(KYIV_CHANNEL, "https://t.me/channel/1")

    assert mock_web_redis.hset.call_count == 2
    mock_web_redis.hset.assert_any_call("threat:alerts:kyiv", "source", "https://t.me/channel/1")
    mock_web_redis.hset.assert_any_call(
        "threat:alerts:city:kyiv", "source", "https://t.me/channel/1"
    )


@pytest.mark.parametrize(
    "channel_id",
    [
        pytest.param(12345, id="unknown-channel"),
        pytest.param(999999999, id="region-missing-from-region-config"),
    ],
)
def test_update_alert_source_ignores_unmapped_channels(mock_web_redis, channel_id):
    update_alert_source(channel_id, "https://t.me/channel/1")

    mock_web_redis.hset.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_text, expected_status, expected_event",
    [
        ("Повітряна тривога", "true", "air_raid_alert"),
        ("Відбій повітряної тривоги", "false", "air_raid_alert_cancelled"),
        ("Загроза артилерійського обстрілу", "true", "threat_of_shelling"),
        ("Відбій загрози артобстрілу", "false", "threat_of_shelling_cancelled"),
    ],
)
async def test_update_alert_status_writes_redis_and_history(
    mock_web_redis, mock_web_pg, status_text, expected_status, expected_event
):
    mock_conn, mock_cursor = mock_web_pg

    await update_alert_status(KYIV_CHANNEL, status_text)

    if "shelling" in expected_event:
        city_calls = [
            c
            for c in mock_web_redis.hset.call_args_list
            if c.args and c.args[0] == "threat:shellings:kyiv"
        ]
        assert len(city_calls) == 1
        mapping = city_calls[0].kwargs["mapping"]
        assert mapping["status"] == expected_status
        assert "updated_at" in mapping
    else:
        city_calls = [
            c
            for c in mock_web_redis.hset.call_args_list
            if c.args and c.args[0] == "threat:alerts:city:kyiv"
        ]
        assert len(city_calls) == 1
        mapping = city_calls[0].kwargs["mapping"]
        assert mapping["status"] == expected_status
        assert mapping["type"] == expected_event
        assert "updated_at" in mapping

    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args.args
    assert "INSERT INTO alert_history" in sql
    assert params[1] == "kyiv"
    assert params[2] == expected_event
    mock_conn.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_alert_status_stores_broadcast_link(mock_web_redis, mock_web_pg):
    _, mock_cursor = mock_web_pg
    link = "https://t.me/kyiv_alert/512"

    await update_alert_status(KYIV_CHANNEL, "Повітряна тривога", message_id=512, message_link=link)

    for key in ("threat:alerts:city:kyiv", "threat:alerts:kyiv"):
        calls = [c for c in mock_web_redis.hset.call_args_list if c.args and c.args[0] == key]
        assert calls[0].kwargs["mapping"]["source"] == link

    _, params = mock_cursor.execute.call_args.args
    assert params[4] == KYIV_CHANNEL
    assert params[5] == 512
    assert params[6] == link


@pytest.mark.asyncio
async def test_update_alert_status_falls_back_to_default_source(mock_web_redis, mock_web_pg):
    _, mock_cursor = mock_web_pg

    await update_alert_status(KYIV_CHANNEL, "Повітряна тривога")

    calls = [
        c
        for c in mock_web_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:kyiv"
    ]
    assert calls[0].kwargs["mapping"]["source"] == "telegram"

    _, params = mock_cursor.execute.call_args.args
    assert params[4] == KYIV_CHANNEL
    assert params[5] is None
    assert params[6] == "telegram"


@pytest.mark.asyncio
async def test_update_alert_status_keeps_stored_link_on_unknown_text(mock_web_redis, mock_web_pg):
    await update_alert_status(KYIV_CHANNEL, "Щось незрозуміле")

    calls = [
        c
        for c in mock_web_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:kyiv"
    ]
    assert "source" not in calls[0].kwargs["mapping"]


@pytest.mark.asyncio
async def test_update_alert_status_stores_shelling_link(mock_web_redis, mock_web_pg):
    link = "https://t.me/kyiv_alert/900"

    await update_alert_status(
        KYIV_CHANNEL, "Загроза артилерійського обстрілу", message_id=900, message_link=link
    )

    calls = [
        c
        for c in mock_web_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:shellings:kyiv"
    ]
    assert calls[0].kwargs["mapping"]["source"] == link


@pytest.mark.asyncio
async def test_update_alert_status_raises_and_logs_when_history_write_fails(
    mock_web_redis, mock_web_pg, caplog
):
    caplog.set_level(logging.ERROR)

    with patch("web.db.get_pg_conn", side_effect=OSError("connection refused")):
        with pytest.raises(OSError):
            await update_alert_status(KYIV_CHANNEL, "Повітряна тривога")

    assert "Failed to record alert air_raid_alert for kyiv in history" in caplog.text


@pytest.mark.asyncio
async def test_update_alert_status_unknown_text_updates_time_only(mock_web_redis, mock_web_pg):
    _, mock_cursor = mock_web_pg

    await update_alert_status(KYIV_CHANNEL, "Щось незрозуміле")

    mock_cursor.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel_id",
    [
        pytest.param(12345, id="unknown-channel"),
        pytest.param(999999999, id="region-missing-from-region-config"),
    ],
)
async def test_update_alert_status_ignores_unmapped_channels(
    mock_web_redis, mock_web_pg, channel_id
):
    _, mock_cursor = mock_web_pg

    await update_alert_status(channel_id, "Повітряна тривога")

    mock_web_redis.hset.assert_not_called()
    mock_cursor.execute.assert_not_called()


def test_rehydrate_state_from_db(mock_web_pg, mock_web_redis):
    mock_conn, mock_cursor = mock_web_pg
    now = datetime.datetime.now()
    now_1400 = now.replace(hour=14, minute=0, second=0)
    now_1300 = now.replace(hour=13, minute=0, second=0)
    now_1200 = now.replace(hour=12, minute=0, second=0)
    now_1100 = now.replace(hour=11, minute=0, second=0)
    mock_cursor.fetchall.return_value = [
        ("kyiv", "air_raid_alert", None, now_1400, "https://t.me/kyiv_alert/42"),
        ("lviv", "air_raid_alert_cancelled", None, now_1300, None),
        ("odesa", "air_raid_alert", None, now_1200, None),
        (
            "nikopol",
            "threat_of_shelling",
            None,
            now_1100,
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
        "threat:alerts:city:kyiv": {
            "status": "true",
            "time": "10:00",
            "source": "https://t.me/kyiv_alert/123",
            "updated_at": "1000",
            "level": "red",
        },
        "threat:alerts:city:bucha": {
            "status": "true",
            "time": "11:00",
            "source": "https://t.me/bucha_alert/77",
            "updated_at": "1741708800",
            "level": "yellow",
        },
        "threat:alerts:city:boryspil": {
            "status": "true",
            "time": "12:00",
            "source": "https://t.me/boryspil_alert/12",
            "updated_at": "1741708900",
            "level": "red",
        },
        "threat:alerts:city:fastiv": {
            "status": "false",
            "time": "09:00",
            "source": "https://t.me/fastiv_alert/88",
            "updated_at": "1741709500",
        },
        "threat:shellings:nikopol": {
            "status": "true",
            "time": "11:45",
            "source": "https://t.me/nikopol_alert/512",
            "updated_at": "1741709000",
        },
        "threat:shellings:kherson": {
            "status": "false",
            "time": "12:15",
            "source": "telegram",
            "updated_at": "1000",
        },
    }
    pipeline = _FakePipeline(store, {})
    mock_web_redis.pipeline.return_value = pipeline
    return pipeline


def test_get_all_threats_data_raises_and_logs_when_redis_is_down(threats_store, caplog):
    caplog.set_level(logging.ERROR)

    with patch.object(threats_store, "execute", side_effect=ConnectionError("redis down")):
        with pytest.raises(ConnectionError):
            get_all_threats_data()

    assert "Failed to read threat data from Redis" in caplog.text


def test_get_all_threats_data_queries_all_districts(threats_store):
    get_all_threats_data()

    keys = [k for _, k in threats_store.operations]
    assert "threat:alerts:city:kyiv" in keys
    assert "threat:shellings:kyiv" in keys
    assert "threat:alerts:city:bucha" in keys
    assert "threat:shellings:bucha" in keys


def test_get_all_threats_data_schema_and_types(threats_store):
    result = get_all_threats_data()

    assert result["kyiv_oblast"]["title"] == "Київська область"
    bucha = result["kyiv_oblast"]["districts"]["bucha"]
    assert bucha["title"] == "Бучанський район"
    assert bucha["alert"]["status"] is True
    assert bucha["alert"]["level"] == "yellow"
    assert bucha["alert"]["updated_at"] == 1741708800
    assert bucha["alert"]["source"] == "https://t.me/bucha_alert/77"
    assert bucha["shelling"]["status"] is False
    assert bucha["shelling"]["updated_at"] is None
    assert bucha["shelling"]["source"] is None

    boryspil = result["kyiv_oblast"]["districts"]["boryspil"]
    assert boryspil["title"] == "Бориспільський район"
    assert boryspil["alert"]["status"] is True
    assert boryspil["alert"]["level"] == "red"
    assert boryspil["alert"]["updated_at"] == 1741708900
    assert boryspil["alert"]["source"] == "https://t.me/boryspil_alert/12"
    assert boryspil["shelling"]["status"] is False
    assert boryspil["shelling"]["updated_at"] is None
    assert boryspil["shelling"]["source"] is None

    assert result["dnipropetrovsk_oblast"]["title"] == "Дніпропетровська область"
    nikopol = result["dnipropetrovsk_oblast"]["districts"]["nikopol"]
    assert nikopol["title"] == "Нікопольський район"
    assert nikopol["alert"]["status"] is False
    assert nikopol["alert"]["level"] is None
    assert nikopol["alert"]["updated_at"] is None
    assert nikopol["alert"]["source"] is None
    assert nikopol["shelling"]["status"] is True
    assert nikopol["shelling"]["updated_at"] == 1741709000
    assert nikopol["shelling"]["source"] == "https://t.me/nikopol_alert/512"

    fastiv = result["kyiv_oblast"]["districts"]["fastiv"]
    assert fastiv["title"] == "Фастівський район"
    assert fastiv["alert"]["status"] is False
    assert fastiv["alert"]["level"] is None
    assert fastiv["alert"]["updated_at"] == 1741709500
    assert fastiv["alert"]["source"] == "https://t.me/fastiv_alert/88"
    assert fastiv["shelling"]["status"] is False
    assert fastiv["shelling"]["updated_at"] is None
    assert fastiv["shelling"]["source"] is None

    kherson = result["kherson_oblast"]["districts"]["kherson"]
    assert kherson["shelling"]["status"] is False
    assert kherson["shelling"]["updated_at"] == 1000
    assert kherson["shelling"]["source"] is None

    assert result["kyiv"]["title"] == "м. Київ"
    kyiv = result["kyiv"]["districts"]["kyiv"]
    assert kyiv["title"] == "м. Київ"
    assert kyiv["alert"]["status"] is True
    assert kyiv["alert"]["level"] == "red"
    assert kyiv["alert"]["updated_at"] == 1000
    assert kyiv["alert"]["source"] == "https://t.me/kyiv_alert/123"


def test_get_all_threats_data_defaults_empty_and_missing_keys(threats_store):
    result = get_all_threats_data()

    assert result["crimea"] == {"title": "Автономна Республіка Крим", "districts": {}}
    assert result["sevastopol"] == {"title": "м. Севастополь", "districts": {}}
    assert result["donetsk_oblast"] == {"title": "Донецька область", "districts": {}}
    assert result["luhansk_oblast"] == {"title": "Луганська область", "districts": {}}


def test_get_all_threats_data_covers_every_oblast_and_district(mock_web_redis):
    from web.db import ALL_OBLASTS

    mock_web_redis.pipeline.return_value = _FakePipeline({}, {})
    result = get_all_threats_data()

    assert set(result.keys()) == set(ALL_OBLASTS)
    tracked_districts = {
        d_key for obl in result.values() for d_key in obl["districts"].keys()
    }
    assert tracked_districts == set(DISTRICT_CONFIG.keys())
    for obl in result.values():
        assert isinstance(obl["title"], str) and len(obl["title"]) > 0
        for d in obl["districts"].values():
            assert isinstance(d["title"], str) and len(d["title"]) > 0


def test_get_all_threats_data_ignores_shelling_type_in_city_alerts(mock_web_redis):
    store = {
        "threat:alerts:city:nikopol": {
            "status": "true",
            "type": "threat_of_shelling",
            "updated_at": "100",
        },
    }
    mock_web_redis.pipeline.return_value = _FakePipeline(store, {})
    result = get_all_threats_data()

    assert result["dnipropetrovsk_oblast"]["districts"]["nikopol"]["alert"]["status"] is False
    assert result["dnipropetrovsk_oblast"]["districts"]["nikopol"]["alert"]["level"] is None


def test_clean_helpers():
    from web.db import _clean_source, _clean_updated_at, _resolve_alert_level

    assert _clean_source(None) is None
    assert _clean_source("") is None
    assert _clean_source("None") is None
    assert _clean_source("telegram") is None
    assert _clean_source("https://t.me/test/1") == "https://t.me/test/1"

    assert _clean_updated_at(None) is None
    assert _clean_updated_at("invalid") is None
    assert _clean_updated_at(0) is None
    assert _clean_updated_at(-5) is None
    assert _clean_updated_at("1741708800") == 1741708800
    assert _clean_updated_at("1741708800.0") == 1741708800

    assert _resolve_alert_level({"level": "yellow"}) == "yellow"
    assert _resolve_alert_level({"level": "red"}) == "red"
    assert _resolve_alert_level({"type": "air_raid_alert:yellow"}) == "yellow"
    assert _resolve_alert_level({"type": "air_raid_alert:red"}) == "red"
    assert _resolve_alert_level({"type": "air_raid_alert"}) == "red"
    assert _resolve_alert_level({}) == "red"


def test_rehydrate_state_from_db_with_two_level_alerts(mock_web_pg, mock_web_redis):
    _, mock_cursor = mock_web_pg
    now = datetime.datetime.now()
    mock_cursor.fetchall.return_value = [
        ("bucha", "air_raid_alert", "yellow", now, None),
        ("boryspil", "air_raid_alert", "red", now, None),
    ]

    pipeline = MagicMock()
    mock_web_redis.pipeline.return_value = pipeline

    rehydrate_state_from_db()

    bucha_calls = [
        c
        for c in pipeline.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:bucha"
    ]
    assert len(bucha_calls) == 1
    mapping_bucha = bucha_calls[0].kwargs["mapping"]
    assert mapping_bucha["status"] == "true"
    assert mapping_bucha["level"] == "yellow"

    boryspil_calls = [
        c
        for c in pipeline.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:boryspil"
    ]
    assert len(boryspil_calls) == 1
    mapping_boryspil = boryspil_calls[0].kwargs["mapping"]
    assert mapping_boryspil["status"] == "true"
    assert mapping_boryspil["level"] == "red"
