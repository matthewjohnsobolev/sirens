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
    PG_CONNECT_TIMEOUT,
    REDIS_CONNECT_TIMEOUT,
    REDIS_SOCKET_TIMEOUT,
    SCHEMA_LOCK_KEY,
    STATE_INITIALIZED_KEY,
    THREAT_TABLES,
    _validate_table,
    ensure_pg_tables,
    get_all_threats_data,
    get_pg_conn,
    get_region_by_channel_id,
    get_threat_source,
    get_threat_status,
    get_threat_time,
    redis_client,
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
    mock_connect.assert_called_once_with(DATABASE_URL, connect_timeout=PG_CONNECT_TIMEOUT)


def test_get_pg_conn_gives_up_before_the_kernel_does():
    """A database that never answers must not hold a request for minutes."""
    assert 0 < PG_CONNECT_TIMEOUT <= 10


def test_redis_client_refuses_to_wait_forever():
    kwargs = redis_client.connection_pool.connection_kwargs

    assert kwargs["socket_connect_timeout"] == REDIS_CONNECT_TIMEOUT
    assert kwargs["socket_timeout"] == REDIS_SOCKET_TIMEOUT
    assert kwargs["retry_on_timeout"] is True


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
    assert params[3] == "kyiv"
    assert params[4] == "kyiv"
    assert params[5] == expected_event
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
    assert params[6] == KYIV_CHANNEL
    assert params[7] == 512
    assert params[8] == link


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
    assert params[7] is None
    assert params[8] is None


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
    def __init__(self, store, sets=None, present_keys=(STATE_INITIALIZED_KEY,)):
        self._store = store
        self._sets = sets or {}
        self._present = set(present_keys)
        self.operations = []

    def hgetall(self, key):
        self.operations.append(("hgetall", key))
        return self

    def smembers(self, key):
        self.operations.append(("smembers", key))
        return self

    def exists(self, key):
        self.operations.append(("exists", key))
        return self

    def execute(self):
        results = []
        for op, key in self.operations:
            if op == "hgetall":
                results.append(dict(self._store.get(key, {})))
            elif op == "smembers":
                results.append(set(self._sets.get(key, set())))
            elif op == "exists":
                results.append(1 if key in self._present else 0)
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


def test_get_all_threats_data_reports_the_state_it_found(threats_store):
    result = get_all_threats_data()

    assert result["meta"]["state_known"] is True
    assert result["meta"]["generated_at"] > 0


def test_get_all_threats_data_admits_when_redis_holds_no_state(mock_web_redis):
    """An empty Redis reads as a nationwide all-clear; say so instead."""
    mock_web_redis.pipeline.return_value = _FakePipeline({}, {}, present_keys=())

    result = get_all_threats_data()

    assert result["meta"]["state_known"] is False
    assert result["kyiv"]["alert"]["status"] is False


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
