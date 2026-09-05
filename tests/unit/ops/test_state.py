from unittest.mock import MagicMock, patch

import pytest

from ops.state import (
    add_maintenance_window,
    apply_threat_change,
    complete_maintenance_window,
    format_components_uk,
    format_window_status,
    format_window_time,
    get_all_districts_statuses,
    get_district_status,
    get_history,
    get_kyiv_now,
    get_kyiv_timezone,
    get_maintenance,
    get_pg_connection,
    get_redis_client,
    list_maintenance_windows,
    normalize_components,
    parse_duration,
    parse_kyiv_datetime,
    parse_maintenance_window,
    push_maintenance_to_kv,
    resolve_district,
    set_maintenance,
    sync_maintenance_state,
)


def test_resolve_district_exact_key():
    resolved = resolve_district("kyiv")
    assert resolved is not None
    assert resolved[0] == "kyiv"


def test_resolve_district_empty_and_unknown():
    assert resolve_district("") is None
    assert resolve_district("   ") is None
    assert resolve_district("unknown_place_123") is None


def test_resolve_district_display_name():
    resolved = resolve_district("Київ")
    assert resolved is not None
    assert resolved[0] == "kyiv"


def test_resolve_district_ukrainian_name():
    resolved = resolve_district("Бучанський район")
    assert resolved is not None
    assert resolved[0] == "bucha"


def test_resolve_district_city():
    resolved = resolve_district("Біла Церква")
    assert resolved is not None
    assert resolved[0] == "bilatserkva"


def test_resolve_district_broadcast_cities():
    resolved = resolve_district("Нікополь")
    assert resolved is not None
    assert resolved[0] == "nikopol"


def test_resolve_district_fuzzy():
    # Unique prefix/substring match
    resolved = resolve_district("бровар")
    assert resolved is not None
    assert resolved[0] == "brovary"

    # Ambiguous match (e.g. single letter that matches multiple districts)
    assert resolve_district("а") is None


def test_get_district_status():
    mock_redis = MagicMock()
    mock_redis.hgetall.side_effect = lambda key: {
        "threat:alerts:city:bucha": {"status": "true", "time": "12:00", "source": "tg"},
        "threat:shellings:bucha": {"status": "false", "time": "None"},
        "threat:alerts:kyiv_oblast": {"status": "true", "time": "12:00"},
    }.get(key, {})
    mock_redis.smembers.return_value = {"bucha"}

    data = get_district_status("bucha", redis_conn=mock_redis, env="dev")
    assert data["key"] == "bucha"
    assert data["alert"]["status"] is True
    assert data["alert"]["time"] == "12:00"
    assert data["shelling"]["status"] is False
    assert data["has_channel"] is True


def test_get_district_status_unknown_district():
    with pytest.raises(ValueError, match="Unknown district key"):
        get_district_status("non_existent_district")


def test_get_all_districts_statuses():
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    # Mock execute returning alternating alert and shelling dicts
    mock_pipe.execute.return_value = [
        {"status": "true", "time": "10:00", "updated_at": "12345"},
        {"status": "false", "time": "None"},
    ] * 200

    # With filter_oblast and active_only=True
    res = get_all_districts_statuses(
        redis_conn=mock_redis, filter_oblast="kyiv_oblast", active_only=True, env="dev"
    )
    assert len(res) > 0
    assert all(d["oblast_key"] == "kyiv_oblast" for d in res)
    assert all(d["alert"]["status"] is True for d in res)

    # With active_only=False (all)
    mock_pipe.execute.return_value = [
        {"status": "false", "time": "None"},
        {"status": "false", "time": "None"},
    ] * 200
    res_all = get_all_districts_statuses(
        redis_conn=mock_redis, filter_oblast="kyiv_oblast", active_only=False, env="dev"
    )
    assert len(res_all) > 0


def test_apply_threat_change_validations():
    with pytest.raises(ValueError, match="Unknown district key"):
        apply_threat_change("invalid_district", alert_active=True)

    with pytest.raises(ValueError, match="At least one of alert_active or shelling_active"):
        apply_threat_change("bucha", alert_active=None, shelling_active=None)


def test_apply_threat_change_dry_run():
    mock_redis = MagicMock()
    result = apply_threat_change(
        district_key="bucha",
        alert_active=True,
        shelling_active=False,
        dry_run=True,
        redis_conn=mock_redis,
        env="dev",
    )
    assert result["dry_run"] is True
    assert len(result["changes"]) == 2
    mock_redis.hset.assert_not_called()


def test_apply_threat_change_execution():
    mock_redis = MagicMock()
    mock_redis.scard.return_value = 1
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur

    result = apply_threat_change(
        district_key="bucha",
        alert_active=True,
        shelling_active=None,
        dry_run=False,
        redis_conn=mock_redis,
        pg_conn=mock_pg,
        env="dev",
    )

    assert result["dry_run"] is False
    assert result["history_recorded"] is True
    assert mock_redis.hset.call_count >= 2
    mock_redis.sadd.assert_called_once_with("threat:alerts:active:kyiv_oblast", "bucha")
    mock_cur.execute.assert_called_once()
    mock_pg.commit.assert_called_once()


def test_apply_threat_change_alert_off_and_shelling():
    mock_redis = MagicMock()
    mock_redis.scard.return_value = 0
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur

    result = apply_threat_change(
        district_key="bucha",
        alert_active=False,
        shelling_active=True,
        dry_run=False,
        redis_conn=mock_redis,
        pg_conn=mock_pg,
        env="dev",
    )

    assert result["history_recorded"] is True
    mock_redis.srem.assert_called_once_with("threat:alerts:active:kyiv_oblast", "bucha")
    assert mock_redis.hset.call_count >= 3  # alert city, alert oblast, shelling city


def test_apply_threat_change_pg_failures():
    mock_redis = MagicMock()

    # Case 1: PG connection fails
    with patch("ops.state.get_pg_connection", side_effect=Exception("DB Down")):
        res1 = apply_threat_change(
            district_key="bucha",
            alert_active=True,
            redis_conn=mock_redis,
            pg_conn=None,
        )
        assert res1["history_recorded"] is False

    # Case 2: PG execution raises exception
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    mock_cur.execute.side_effect = Exception("Query error")
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur
    res2 = apply_threat_change(
        district_key="bucha",
        alert_active=True,
        redis_conn=mock_redis,
        pg_conn=mock_pg,
    )
    assert "Query error" in res2["history_error"]


def test_get_history():
    mock_pg = MagicMock()
    mock_cur = MagicMock()
    mock_pg.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = [
        (
            1,
            "2026-09-04 12:00:00",
            "2026-09-04",
            "12:00",
            "bucha",
            "kyiv_oblast",
            "air_raid_alert",
            -1001754447620,
            123,
            "manual:cli",
        ),
    ]

    # Filtered by district
    history = get_history(district_key="bucha", limit=5, pg_conn=mock_pg)
    assert len(history) == 1
    assert history[0]["district_key"] == "bucha"
    assert history[0]["type"] == "air_raid_alert"

    # All districts (district_key=None)
    history_all = get_history(district_key=None, limit=5, pg_conn=mock_pg)
    assert len(history_all) == 1


def test_parse_kyiv_datetime():
    # Test explicit date and time
    dt, date_obj, time_str, epoch = parse_kyiv_datetime("2026-09-04", "14:30")
    assert str(date_obj) == "2026-09-04"
    assert time_str == "14:30"
    assert int(epoch) > 0

    # Test DD.MM date format
    dt2, date_obj2, time_str2, epoch2 = parse_kyiv_datetime("04.09", "10:15")
    assert date_obj2.day == 4
    assert date_obj2.month == 9
    assert time_str2 == "10:15"

    # Test date formats: DD/MM and DD/MM/YYYY
    dt3, date_obj3, _, _ = parse_kyiv_datetime("04/09", "10:15")
    assert date_obj3.day == 4
    dt4, date_obj4, _, _ = parse_kyiv_datetime("04/09/2026", "10:15")
    assert date_obj4.year == 2026

    # Test default (omitted date and time uses current Kyiv datetime)
    dt5, date_obj5, time_str5, epoch5 = parse_kyiv_datetime(None, None)
    assert date_obj5 is not None
    assert len(time_str5) == 5
    assert ":" in time_str5

    # Test invalid date
    with pytest.raises(ValueError, match="Invalid date format"):
        parse_kyiv_datetime("invalid-date", "12:00")

    # Test invalid time
    with pytest.raises(ValueError, match="Invalid time format"):
        parse_kyiv_datetime("2026-09-04", "invalid-time")


def test_timezone_and_connection_helpers():
    tz = get_kyiv_timezone()
    assert tz is not None
    now = get_kyiv_now()
    assert now is not None

    with patch("redis.from_url") as mock_r:
        get_redis_client()
        mock_r.assert_called_once()

    with patch("psycopg2.connect") as mock_pg:
        get_pg_connection()
        mock_pg.assert_called_once()


def test_set_and_get_maintenance():
    mock_redis = MagicMock()
    mock_redis.hgetall.return_value = {}

    # Initial / empty
    empty = get_maintenance(redis_conn=mock_redis)
    assert empty["active"] is False
    assert empty["components"] == ["all"]

    # Set maintenance on
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        res = set_maintenance(
            active=True,
            components=["map", "api"],
            message="Upgrading servers",
            redis_conn=mock_redis,
            operator="alice",
            sync_cf=True,
        )
    assert res["active"] is True
    assert res["components"] == ["map", "api"]
    assert res["subtitle"] == "Upgrading servers"
    assert res["cf_synced"] is True
    assert res["operator"] == "alice"
    mock_redis.hset.assert_called_once()

    # Get populated maintenance
    mock_redis.hgetall.return_value = {
        "active": "true",
        "components": '["map", "api"]',
        "headline": "Планові роботи",
        "subtitle": "Upgrading servers",
        "updated_at": "12345678",
        "operator": "alice",
    }
    loaded = get_maintenance(redis_conn=mock_redis)
    assert loaded["active"] is True
    assert loaded["components"] == ["map", "api"]
    assert loaded["subtitle"] == "Upgrading servers"
    assert loaded["operator"] == "alice"
    assert loaded["updated_at"] == 12345678

    # Set maintenance off with default component
    with patch("ops.state.push_maintenance_to_kv", return_value=False):
        res_off = set_maintenance(
            active=False,
            components=None,
            redis_conn=mock_redis,
            sync_cf=False,
        )
    assert res_off["active"] is False
    assert res_off["components"] == ["all"]
    assert res_off["cf_synced"] is False


def test_set_maintenance_invalid_component():
    mock_redis = MagicMock()
    with pytest.raises(ValueError, match="Unknown component: 'unknown_comp'"):
        set_maintenance(active=True, components=["unknown_comp"], redis_conn=mock_redis)


def test_push_maintenance_to_kv():
    # When unconfigured
    with (
        patch("ops.state.CLOUDFLARE_ACCOUNT_ID", ""),
        patch("ops.state.CLOUDFLARE_TELEMETRY_NAMESPACE_ID", ""),
        patch("ops.state.CLOUDFLARE_API_TOKEN", ""),
    ):
        assert push_maintenance_to_kv({"active": True}) is False

    # When configured and succeeds
    with (
        patch("ops.state.CLOUDFLARE_ACCOUNT_ID", "acc123"),
        patch("ops.state.CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "ns123"),
        patch("ops.state.CLOUDFLARE_API_TOKEN", "tok123"),
        patch("requests.put") as mock_put,
    ):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp
        assert push_maintenance_to_kv({"active": True}) is True

    # When configured and fails
    with (
        patch("ops.state.CLOUDFLARE_ACCOUNT_ID", "acc123"),
        patch("ops.state.CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "ns123"),
        patch("ops.state.CLOUDFLARE_API_TOKEN", "tok123"),
        patch("requests.put") as mock_put,
    ):
        mock_put.side_effect = Exception("network error")
        assert push_maintenance_to_kv({"active": True}) is False


def test_normalize_components():
    assert normalize_components(None) == ["all"]
    assert normalize_components("") == ["all"]
    assert normalize_components([]) == ["all"]
    assert normalize_components("all") == ["all"]
    assert normalize_components("усі") == ["all"]
    assert normalize_components("всі") == ["all"]
    assert normalize_components("map,api") == ["map", "api"]
    assert normalize_components("мапа, апі") == ["map", "api"]
    assert normalize_components(["broadcast", "source"]) == ["broadcast", "source"]
    assert normalize_components("розсилка, джерело") == ["broadcast", "source"]

    with pytest.raises(ValueError, match="Unknown component: 'unknown_comp'"):
        normalize_components("unknown_comp")


def test_format_components_uk():
    assert format_components_uk(["all"]) == "усі"
    assert format_components_uk(["map", "api"]) == "мапа, API"
    assert format_components_uk(["broadcast", "source"]) == "розсилка, джерело"


def test_parse_duration():
    assert parse_duration("90m") == 5400
    assert parse_duration("2h") == 7200
    assert parse_duration("1h30m") == 5400
    assert parse_duration("1.5h") == 5400
    assert parse_duration("60") == 3600
    assert parse_duration("") == 3600

    with pytest.raises(ValueError, match="Invalid duration format"):
        parse_duration("invalid")
    with pytest.raises(ValueError, match="Invalid duration format"):
        parse_duration("0m")


def test_parse_maintenance_window():
    # Test "now"
    start_dt, end_dt, start_epoch, end_epoch = parse_maintenance_window("now", "90m")
    assert end_epoch - start_epoch == 5400

    # Test "зараз"
    s_dt, e_dt, s_ep, e_ep = parse_maintenance_window("зараз", "30m")
    assert e_ep - s_ep == 1800

    # Test "DD.MM HH:MM"
    start_dt, end_dt, start_epoch, end_epoch = parse_maintenance_window("05.09 02:00", "90m")
    assert start_dt.month == 9
    assert start_dt.day == 5
    assert start_dt.hour == 2
    assert start_dt.minute == 0
    assert end_epoch - start_epoch == 5400

    # Test "HH:MM"
    start_dt, end_dt, start_epoch, end_epoch = parse_maintenance_window("14:30", "1h")
    assert start_dt.hour == 14
    assert start_dt.minute == 30
    assert end_epoch - start_epoch == 3600

    # Test invalid
    with pytest.raises(ValueError, match="Invalid --from time format"):
        parse_maintenance_window("invalid_time", "1h")


def test_format_window_time():
    import datetime

    tz = get_kyiv_timezone()
    dt1 = datetime.datetime(2026, 9, 5, 2, 0, tzinfo=tz)
    dt2 = datetime.datetime(2026, 9, 5, 3, 30, tzinfo=tz)
    assert format_window_time(dt1, dt2) == "02:00–03:30"

    dt3 = datetime.datetime(2026, 9, 6, 1, 0, tzinfo=tz)
    assert format_window_time(dt1, dt3) == "05.09 02:00–06.09 01:00"


def test_format_window_status():
    import datetime

    tz = get_kyiv_timezone()
    now = 100000

    # Completed
    assert format_window_status(90000, 110000, completed=True, now_epoch=now) == (
        "completed",
        "завершено",
        "",
    )

    # Active - less than 1 min
    code, lbl, rem = format_window_status(90000, 100030, completed=False, now_epoch=now)
    assert code == "active"
    assert lbl == "зараз"
    assert rem == "ще <1 хв"

    # Active - 47 min
    code, lbl, rem = format_window_status(90000, 100000 + 47 * 60, completed=False, now_epoch=now)
    assert code == "active"
    assert lbl == "зараз"
    assert rem == "ще 47 хв"

    # Active - 2h 15m
    code, lbl, rem = format_window_status(
        90000, 100000 + 2 * 3600 + 15 * 60, completed=False, now_epoch=now
    )
    assert rem == "ще 2 год 15 хв"

    # Scheduled - wait 45m
    dt = datetime.datetime(2026, 9, 6, 23, 0, tzinfo=tz)
    code, lbl, wait = format_window_status(
        now + 45 * 60, now + 105 * 60, completed=False, now_epoch=now, start_dt=dt
    )
    assert code == "scheduled"
    assert lbl == "06.09"
    assert wait == "через 45 хв"

    # Scheduled - wait 10h
    code, lbl, wait = format_window_status(
        now + 10 * 3600, now + 12 * 3600, completed=False, now_epoch=now, start_dt=dt
    )
    assert wait == "через 10 год"

    # Scheduled - wait 2 days
    code, lbl, wait = format_window_status(
        now + 49 * 3600, now + 50 * 3600, completed=False, now_epoch=now, start_dt=dt
    )
    assert wait == "через 2 дн."

    # Past
    assert format_window_status(80000, 90000, completed=False, now_epoch=now) == (
        "completed",
        "завершено",
        "",
    )


def test_schedule_management():
    import json

    mock_redis = MagicMock()
    mock_redis.get.return_value = None

    # Add window
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        win = add_maintenance_window(
            components="map,api",
            from_str="now",
            for_str="90m",
            note="Оновлюємо базу",
            redis_conn=mock_redis,
            operator="tester",
        )
    assert win["id"].startswith("mnt_")
    assert win["components"] == ["map", "api"]
    assert win["note"] == "Оновлюємо базу"
    assert win["operator"] == "tester"
    assert mock_redis.set.called

    # List windows
    saved_schedule = [win]
    mock_redis.get.return_value = json.dumps(saved_schedule)
    windows = list_maintenance_windows(include_completed=False, redis_conn=mock_redis)
    assert len(windows) == 1
    assert windows[0]["id"] == win["id"]
    assert windows[0]["components_uk"] == "мапа, API"
    assert windows[0]["status_code"] in ("active", "scheduled")

    # Complete window by id
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        completed = complete_maintenance_window(window_id=win["id"], redis_conn=mock_redis)
    assert completed is not None
    assert completed["completed"] is True

    # Complete when none active
    mock_redis.get.return_value = json.dumps([])
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        none_win = complete_maintenance_window(redis_conn=mock_redis)
    assert none_win is None


def test_sync_maintenance_state():
    import json

    mock_redis = MagicMock()
    now = int(get_kyiv_now().timestamp())

    # When active window exists
    mock_redis.get.return_value = json.dumps(
        [
            {
                "id": "mnt_active",
                "components": ["map"],
                "note": "Testing active window sync",
                "start_epoch": now - 60,
                "end_epoch": now + 3600,
                "start_iso": "2026-09-05T12:00:00+03:00",
                "end_iso": "2026-09-05T13:00:00+03:00",
                "completed": False,
            }
        ]
    )
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        active_res = sync_maintenance_state(redis_conn=mock_redis)
    assert active_res["id"] == "mnt_active"

    # When no active window exists
    mock_redis.get.return_value = json.dumps([])
    with patch("ops.state.push_maintenance_to_kv", return_value=True):
        inactive_res = sync_maintenance_state(redis_conn=mock_redis)
    assert inactive_res.get("active") is False
