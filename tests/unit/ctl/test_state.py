from unittest.mock import MagicMock

from ctl.state import (
    apply_threat_change,
    get_district_status,
    get_history,
    resolve_district,
)


def test_resolve_district_exact_key():
    resolved = resolve_district("kyiv")
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


def test_resolve_district_unknown():
    assert resolve_district("unknown_place_123") is None


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

    history = get_history(district_key="bucha", limit=5, pg_conn=mock_pg)
    assert len(history) == 1
    assert history[0]["district_key"] == "bucha"
    assert history[0]["type"] == "air_raid_alert"


def test_parse_kyiv_datetime():
    from ctl.state import parse_kyiv_datetime

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

    # Test default (omitted date and time uses current Kyiv datetime)
    dt3, date_obj3, time_str3, epoch3 = parse_kyiv_datetime(None, None)
    assert date_obj3 is not None
    assert len(time_str3) == 5
    assert ":" in time_str3
