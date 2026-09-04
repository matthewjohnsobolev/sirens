from unittest.mock import MagicMock, patch

import pytest

from ops.state import (
    apply_threat_change,
    get_all_districts_statuses,
    get_district_status,
    get_history,
    get_kyiv_now,
    get_kyiv_timezone,
    get_pg_connection,
    get_redis_client,
    parse_kyiv_datetime,
    resolve_district,
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
