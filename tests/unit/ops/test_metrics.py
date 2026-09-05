from unittest.mock import MagicMock, mock_open, patch

from ops.metrics import (
    _fallback_system_metrics,
    collect_all_metrics,
    format_bytes,
    get_container_metrics,
    get_message_metrics,
    get_service_metrics,
    get_system_metrics,
)


def test_format_bytes():
    assert format_bytes(None) == "N/A"
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1 KB"
    assert format_bytes(1024 * 1024 * 5.5) == "5.50 MB"
    assert format_bytes(1024 * 1024 * 1024 * 2.25) == "2.25 GB"
    assert format_bytes(1024 * 1024 * 1024 * 1024 * 1.5) == "1.50 TB"


def test_get_message_metrics_success():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # row: broadcast_24h, alert_24h, alert_cancel_24h, shelling_24h, shelling_cancel_24h,
    # auto_24h, manual_24h, map_only_24h, total_events_24h, broadcast_today, map_only_today, total_events_today
    mock_cur.fetchone.return_value = (48, 22, 22, 4, 0, 42, 6, 10, 58, 30, 5, 35)

    res = get_message_metrics(pg_conn=mock_conn)
    assert res["error"] is None
    assert res["broadcast_24h"] == 48
    assert res["alert_24h"] == 22
    assert res["alert_cancel_24h"] == 22
    assert res["shelling_24h"] == 4
    assert res["shelling_cancel_24h"] == 0
    assert res["auto_24h"] == 42
    assert res["manual_24h"] == 6
    assert res["map_only_24h"] == 10
    assert res["broadcast_today"] == 30


def test_get_message_metrics_empty_and_errors():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Empty fetchone
    mock_cur.fetchone.return_value = None
    res_empty = get_message_metrics(pg_conn=mock_conn)
    assert "error" in res_empty
    assert "No data" in res_empty["error"]

    # Query exception
    mock_cur.execute.side_effect = Exception("DB query failed")
    res_err = get_message_metrics(pg_conn=mock_conn)
    assert "error" in res_err
    assert "DB query failed" in res_err["error"]

    # pg_error passed
    res_pg_err = get_message_metrics(pg_error="connection refused")
    assert "connection refused" in res_pg_err["error"]


@patch("ops.metrics._get_pg_conn")
def test_get_message_metrics_connection_fail(mock_get_conn):
    mock_get_conn.side_effect = Exception("Auth fail")
    res = get_message_metrics()
    assert "Failed to connect to PostgreSQL" in res["error"]


def test_get_system_metrics_psutil():
    with (
        patch("psutil.cpu_percent", return_value=15.5),
        patch("psutil.getloadavg", return_value=(0.5, 0.4, 0.3)),
        patch("psutil.cpu_count", return_value=4),
        patch("psutil.virtual_memory") as mock_vm,
        patch("psutil.swap_memory") as mock_sw,
    ):
        mock_vm.return_value = MagicMock(
            total=8000000000, used=4000000000, available=4000000000, percent=50.0
        )
        mock_sw.return_value = MagicMock(
            total=2000000000, used=500000000, free=1500000000, percent=25.0
        )

        res = get_system_metrics()
        assert res["source"] == "psutil"
        assert res["cpu_percent"] == 15.5
        assert res["load_avg"] == (0.5, 0.4, 0.3)
        assert res["cpu_count"] == 4
        assert res["ram"]["percent"] == 50.0
        assert res["swap"]["percent"] == 25.0


def test_fallback_system_metrics():
    meminfo_content = (
        "MemTotal:        8000000 kB\n"
        "MemAvailable:    4000000 kB\n"
        "SwapTotal:       2000000 kB\n"
        "SwapFree:        1500000 kB\n"
    )
    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=meminfo_content)),
    ):
        res = _fallback_system_metrics()
        assert res["source"] == "fallback"
        assert res["ram"] is not None
        assert res["ram"]["percent"] == 50.0
        assert res["swap"] is not None
        assert res["swap"]["percent"] == 25.0


def test_get_container_metrics():
    # Docker not found
    with patch("shutil.which", return_value=None):
        assert get_container_metrics() == []

    # Docker stats success
    with patch("shutil.which", return_value="/usr/bin/docker"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="sirens-alerts\t1.5%\t120MiB / 3.8GiB\t3.1%\nsirens-web\t0.8%\t210MiB / 3.8GiB\t5.5%\nother-container\t0.1%\t10MiB\t0.2%\n",
        )
        res = get_container_metrics()
        assert len(res) == 2
        assert res[0]["name"] == "sirens-alerts"
        assert res[0]["cpu"] == "1.5%"
        assert res[1]["name"] == "sirens-web"

    # Docker stats failure
    with patch("shutil.which", return_value="/usr/bin/docker"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert get_container_metrics() == []


def test_get_service_metrics():
    mock_redis = MagicMock()
    mock_redis.info.side_effect = lambda section: {
        "memory": {"used_memory_human": "15.4M", "used_memory_peak_human": "22.1M"},
        "clients": {"connected_clients": 4},
    }.get(section, {})

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = ("sirens", "84 MB", 5)

    res = get_service_metrics(redis_client=mock_redis, pg_conn=mock_conn)
    assert res["redis"]["used_memory_human"] == "15.4M"
    assert res["redis"]["connected_clients"] == 4
    assert res["postgres"]["database"] == "sirens"
    assert res["postgres"]["size"] == "84 MB"
    assert res["postgres"]["connections"] == 5

    # With passed errors
    res_err = get_service_metrics(redis_error="redis down", pg_error="pg down")
    assert "redis down" in res_err["redis"]["error"]
    assert "pg down" in res_err["postgres"]["error"]


def test_collect_all_metrics():
    with (
        patch("ops.metrics.get_message_metrics", return_value={"broadcast_24h": 10}),
        patch("ops.metrics.get_system_metrics", return_value={"cpu_percent": 12.0}),
        patch("ops.metrics.get_container_metrics", return_value=[]),
        patch("ops.metrics.get_service_metrics", return_value={}),
    ):
        all_metrics = collect_all_metrics()
        assert "timestamp" in all_metrics
        assert all_metrics["messages"]["broadcast_24h"] == 10
        assert all_metrics["system"]["cpu_percent"] == 12.0
