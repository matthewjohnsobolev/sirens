import time
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ops.cli import (
    cli,
    format_elapsed,
    print_history_list,
    print_metrics,
    print_show_detail,
    render_ls_table,
)


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Sirens Operations" in result.output
    assert "alert" in result.output
    assert "shelling" in result.output
    assert "status" in result.output
    assert "ls" not in result.output.split()
    assert "show" in result.output
    assert "history" in result.output
    assert "metrics" in result.output
    assert "maintenance" in result.output
    assert "mnt" in result.output

    # Check metrics help
    metrics_help = runner.invoke(cli, ["metrics", "--help"])
    assert metrics_help.exit_code == 0
    assert "USAGE" in metrics_help.output

    # Check mnt help has status
    mnt_help = runner.invoke(cli, ["mnt", "--help"])
    assert mnt_help.exit_code == 0
    assert "status" in mnt_help.output
    assert "add" in mnt_help.output
    assert "done" in mnt_help.output


def test_format_elapsed():
    now = time.time()
    # Just now
    assert format_elapsed(now - 10) == "just now"
    # Minutes
    assert format_elapsed(now - 120) == "2m ago"
    # Hours exact
    assert format_elapsed(now - 7200) == "2h ago"
    # Hours and minutes
    assert format_elapsed(now - 7260) == "2h 1m ago"
    # Time string format
    res_time = format_elapsed(0, "12:00")
    assert isinstance(res_time, str)
    # Invalid string with colon
    assert format_elapsed(None, "invalid:time") == "invalid:time"
    # String without colon
    assert format_elapsed(None, "invalid") == ""
    # Empty
    assert format_elapsed(None, None) == ""


def test_render_ls_table_and_detail():
    districts = [
        {
            "key": "bucha",
            "name": "Бучанський район",
            "display_name": "Bucha",
            "oblast_key": "kyiv_oblast",
            "channel_id": -1001754447620,
            "has_channel": True,
            "alert": {"status": True, "time": "19:15", "source": "tg", "updated_at": 12345},
            "shelling": {"status": False, "time": "None", "source": "None", "updated_at": 0},
        },
        {
            "key": "nikopol",
            "name": "Нікопольський район",
            "display_name": "Nikopol",
            "oblast_key": "dnipropetrovsk_oblast",
            "channel_id": None,
            "has_channel": False,
            "alert": {"status": False, "time": "None", "source": "None", "updated_at": 0},
            "shelling": {"status": True, "time": "18:00", "source": "tg", "updated_at": 12345},
        },
    ]
    table = render_ls_table(districts)
    assert table is not None

    # Print show detail
    print_show_detail(districts[0])
    print_show_detail(districts[1])


def test_print_history_list():
    # Empty history
    print_history_list([])

    # Populated history with clear, shelling and alert events
    history = [
        {
            "date": "2026-09-04",
            "time": "19:15",
            "district_key": "bucha",
            "type": "air_raid_alert",
            "channel_id": -100123,
            "message_link": "manual:cli",
        },
        {
            "date": "2026-09-04",
            "time": "18:00",
            "district_key": "nikopol",
            "type": "threat_of_shelling",
            "channel_id": None,
            "message_link": None,
        },
        {
            "date": "2026-09-04",
            "time": "17:30",
            "district_key": "bucha",
            "type": "air_raid_alert_cancelled",
            "channel_id": -100123,
            "message_link": None,
        },
    ]
    print_history_list(history)


@patch("ops.state.apply_threat_change")
def test_alert_on_command(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }

    result = runner.invoke(cli, ["alert", "bucha", "on"])
    assert result.exit_code == 0
    assert "bucha" in result.output
    assert "air raid alert on" in result.output


@patch("ops.state.apply_threat_change")
def test_alert_off_command(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:45",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }

    result = runner.invoke(cli, ["alert", "bucha", "off"])
    assert result.exit_code == 0
    assert "air raid alert off" in result.output


@patch("ops.state.apply_threat_change")
def test_alert_with_custom_datetime_and_source(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "14:30",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }

    result = runner.invoke(
        cli,
        [
            "alert",
            "bucha",
            "on",
            "-s",
            "https://t.me/test/1",
            "-d",
            "04.09",
            "-t",
            "14:30",
        ],
    )
    assert result.exit_code == 0
    assert "14:30" in result.output
    assert "auto" in result.output


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_success(mock_apply, mock_broadcast, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.return_value = {"message_link": "https://t.me/c/1754447620/123"}

    result = runner.invoke(cli, ["alert", "bucha", "on", "-b"])
    assert result.exit_code == 0
    assert "broadcast sent" in result.output
    mock_broadcast.assert_called_once_with(-1001754447620, "air_raid_alert")


@patch("ops.state.apply_threat_change")
def test_alert_broadcast_skipped_when_no_channel(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": None,
    }

    result = runner.invoke(cli, ["alert", "bucha", "on", "-b"])
    assert result.exit_code == 0
    assert "broadcast skipped" in result.output


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_error_exits(mock_apply, mock_broadcast, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.side_effect = Exception("TG error")

    result = runner.invoke(cli, ["alert", "bucha", "on", "-b"])
    assert result.exit_code == 1
    assert "error broadcasting to Telegram" in result.output


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_prod_aborted(mock_apply, mock_broadcast, runner):
    result = runner.invoke(
        cli,
        ["-m", "prod", "alert", "bucha", "on", "-b"],
        input="n\n",
    )
    assert result.exit_code == 1
    assert "Aborted" in result.output
    assert "Broadcast to bucha Telegram channel?" in result.output
    mock_apply.assert_not_called()
    mock_broadcast.assert_not_called()


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_prod_confirmed(mock_apply, mock_broadcast, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.return_value = {"message_link": "https://t.me/c/1754447620/123"}

    result = runner.invoke(
        cli,
        ["-m", "prod", "alert", "bucha", "on", "-b"],
        input="y\n",
    )
    assert result.exit_code == 0
    assert "Broadcast to bucha Telegram channel?" in result.output
    assert "broadcast sent" in result.output
    mock_apply.assert_called_once()
    mock_broadcast.assert_called_once_with(-1001754447620, "air_raid_alert")


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_prod_yes_flag(mock_apply, mock_broadcast, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.return_value = {"message_link": "https://t.me/c/1754447620/123"}

    result = runner.invoke(cli, ["-m", "prod", "alert", "bucha", "on", "-b", "-y"])
    assert result.exit_code == 0
    assert "broadcast sent" in result.output
    mock_apply.assert_called_once()
    mock_broadcast.assert_called_once()


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_alert_broadcast_prod_group_yes_flag(mock_apply, mock_broadcast, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.return_value = {"message_link": "https://t.me/c/1754447620/123"}

    result = runner.invoke(cli, ["-y", "-m", "prod", "alert", "bucha", "on", "-b"])
    assert result.exit_code == 0
    assert "broadcast sent" in result.output
    mock_apply.assert_called_once()
    mock_broadcast.assert_called_once()


@patch("ops.broadcast.run_broadcast_sync")
@patch("ops.state.apply_threat_change")
def test_shelling_broadcast_prod_aborted_and_yes(mock_apply, mock_broadcast, runner):
    # Aborted
    res_aborted = runner.invoke(
        cli,
        ["-m", "prod", "shelling", "nikopol", "on", "-b"],
        input="n\n",
    )
    assert res_aborted.exit_code == 1
    assert "Aborted" in res_aborted.output
    assert "Broadcast to nikopol Telegram channel?" in res_aborted.output
    mock_apply.assert_not_called()

    # Confirmed with --yes
    mock_apply.return_value = {
        "district_key": "nikopol",
        "time": "19:40",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }
    mock_broadcast.return_value = {"message_link": "https://t.me/c/1754447620/456"}
    res_yes = runner.invoke(
        cli,
        ["-m", "prod", "shelling", "nikopol", "on", "-b", "--yes"],
    )
    assert res_yes.exit_code == 0
    assert "broadcast sent" in res_yes.output
    mock_apply.assert_called_once()


def test_alert_unknown_district(runner):
    result = runner.invoke(cli, ["alert", "unknown_district_xyz", "on"])
    assert result.exit_code == 1
    assert "not found" in result.output


@patch("ops.state.apply_threat_change")
def test_alert_apply_exception(mock_apply, runner):
    mock_apply.side_effect = Exception("Redis error")
    result = runner.invoke(cli, ["alert", "bucha", "on"])
    assert result.exit_code == 1
    assert "error updating status" in result.output


@patch("ops.state.apply_threat_change")
def test_shelling_on_off_commands(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "nikopol",
        "time": "19:45",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }

    res_on = runner.invoke(cli, ["shelling", "nikopol", "on"])
    assert res_on.exit_code == 0
    assert "threat of shelling on" in res_on.output

    res_off = runner.invoke(cli, ["shelling", "nikopol", "off"])
    assert res_off.exit_code == 0
    assert "threat of shelling off" in res_off.output


@patch("ops.state.get_all_districts_statuses")
def test_status_active_and_all(mock_get_all, runner):
    # With active items
    mock_get_all.return_value = [
        {
            "key": "bucha",
            "name": "Бучанський район",
            "display_name": "Bucha",
            "oblast_key": "kyiv_oblast",
            "channel_id": -1001754447620,
            "has_channel": True,
            "alert": {"status": True, "time": "19:15", "source": "tg", "updated_at": 12345},
            "shelling": {"status": False, "time": "None", "source": "None", "updated_at": 0},
        }
    ]
    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 0
    assert "bucha" in res.output

    # Empty active
    mock_get_all.return_value = []
    res_empty = runner.invoke(cli, ["status"])
    assert res_empty.exit_code == 0
    assert "No active alerts" in res_empty.output

    # Empty all
    res_empty_all = runner.invoke(cli, ["status", "-a"])
    assert res_empty_all.exit_code == 0
    assert "No districts found" in res_empty_all.output


@patch("ops.state.get_all_districts_statuses")
def test_status_error_handling(mock_get_all, runner):
    mock_get_all.side_effect = Exception("Redis error")
    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 1
    assert "error connecting to Redis" in res.output


@patch("ops.state.get_district_status")
def test_show_command(mock_get_status, runner):
    mock_get_status.return_value = {
        "key": "kyiv",
        "name": "м. Київ",
        "display_name": "Kyiv",
        "oblast_key": "kyiv",
        "channel_id": -1001754447620,
        "has_channel": True,
        "alert": {"status": False, "time": "None", "source": "None", "updated_at": 0},
        "shelling": {"status": False, "time": "None", "source": "None", "updated_at": 0},
    }

    res = runner.invoke(cli, ["show", "kyiv"])
    assert res.exit_code == 0
    assert "kyiv" in res.output

    res_unknown = runner.invoke(cli, ["show", "unknown_xyz"])
    assert res_unknown.exit_code == 1

    mock_get_status.side_effect = Exception("State fetch error")
    res_err = runner.invoke(cli, ["show", "kyiv"])
    assert res_err.exit_code == 1


@patch("ops.state.get_history")
def test_history_command(mock_get_hist, runner):
    mock_get_hist.return_value = [
        {
            "id": 1,
            "date": "2026-09-04",
            "time": "19:15",
            "district_key": "bucha",
            "type": "air_raid_alert",
            "channel_id": -1001754447620,
            "message_link": "https://t.me/source/1",
        }
    ]

    res = runner.invoke(cli, ["history", "bucha"])
    assert res.exit_code == 0
    assert "bucha" in res.output

    # Without district
    res_all = runner.invoke(cli, ["history"])
    assert res_all.exit_code == 0

    # Unknown district
    res_unknown = runner.invoke(cli, ["history", "unknown_xyz"])
    assert res_unknown.exit_code == 1

    # Exception in history
    mock_get_hist.side_effect = Exception("DB error")
    res_err = runner.invoke(cli, ["history"])
    assert res_err.exit_code == 1


def test_ls_command_removed(runner):
    res = runner.invoke(cli, ["ls"])
    assert res.exit_code != 0
    assert "No such command 'ls'" in res.output


@patch("ops.metrics.collect_all_metrics")
def test_metrics_command(mock_collect, runner):
    mock_collect.return_value = {
        "timestamp": "2026-09-05 16:30:00",
        "messages": {
            "broadcast_24h": 48,
            "alert_24h": 22,
            "alert_cancel_24h": 22,
            "shelling_24h": 4,
            "shelling_cancel_24h": 0,
            "auto_24h": 42,
            "manual_24h": 6,
            "map_only_24h": 10,
            "broadcast_today": 30,
            "error": None,
        },
        "system": {
            "cpu_percent": 15.5,
            "load_avg": (0.5, 0.4, 0.3),
            "cpu_count": 4,
            "ram": {"total": 8000000000, "used": 4000000000, "percent": 50.0},
            "swap": {"total": 2000000000, "used": 500000000, "percent": 25.0},
            "error": None,
        },
        "containers": [
            {"name": "sirens-alerts", "cpu": "1.5%", "mem_usage": "120MB", "mem_percent": "3.1%"},
            {"name": "sirens-web", "cpu": "0.8%", "mem_usage": "210MB", "mem_percent": "5.5%"},
        ],
        "services": {
            "redis": {
                "used_memory_human": "15.4M",
                "used_memory_peak_human": "22.1M",
                "connected_clients": 4,
                "error": None,
            },
            "postgres": {"database": "sirens", "size": "84 MB", "connections": 5, "error": None},
        },
    }

    res = runner.invoke(cli, ["metrics"])
    assert res.exit_code == 0
    assert "MESSAGES (LAST 24H)" in res.output
    assert "48" in res.output
    assert "SYSTEM RESOURCES (HOST)" in res.output
    assert "15.5" in res.output
    assert "CONTAINERS (DOCKER)" in res.output
    assert "sirens-alerts" in res.output
    assert "SERVICES" in res.output
    assert "redis" in res.output.lower()


def test_print_metrics_with_errors():
    err_data = {
        "messages": {"error": "Failed to connect to PostgreSQL"},
        "system": {
            "error": "Error reading metrics",
            "cpu_percent": None,
            "ram": None,
            "swap": None,
        },
        "containers": [],
        "services": {
            "redis": {"error": "Redis connection refused"},
            "postgres": {"error": "Postgres connection refused"},
        },
    }
    print_metrics(err_data)


def test_entrypoints_importable():
    import ops.__main__  # noqa: F401
    import run_alerts  # noqa: F401
    import run_bi  # noqa: F401
    import run_ops  # noqa: F401
    import status.mnt  # noqa: F401


@patch("ops.state.list_maintenance_windows")
def test_mnt_ls_empty_and_populated(mock_list_mnt, runner):
    from ops.cli import mnt_group

    # Empty
    mock_list_mnt.return_value = []
    res_empty = runner.invoke(cli, ["mnt"])
    assert res_empty.exit_code == 0
    assert "Немає запланованих робіт" in res_empty.output

    # Invoked via maintenance alias
    res_empty_alias = runner.invoke(cli, ["maintenance", "status"])
    assert res_empty_alias.exit_code == 0
    assert "Немає запланованих робіт" in res_empty_alias.output

    # Direct mnt_group invocation
    res_direct = runner.invoke(mnt_group, [])
    assert res_direct.exit_code == 0
    assert "Немає запланованих робіт" in res_direct.output

    # Populated via mnt status
    mock_list_mnt.return_value = [
        {
            "id": "mnt_1",
            "status_code": "active",
            "status_label": "зараз",
            "time_text": "02:00–03:30",
            "components_uk": "мапа, API",
            "note": "Оновлюємо базу",
            "remaining_str": "ще 47 хв",
        },
        {
            "id": "mnt_2",
            "status_code": "scheduled",
            "status_label": "06.09",
            "time_text": "23:00–23:30",
            "components_uk": "API",
            "note": "«Міграція схеми»",
            "remaining_str": "через 10 год",
        },
    ]
    res_pop = runner.invoke(cli, ["mnt", "status"])
    assert res_pop.exit_code == 0
    assert "зараз" in res_pop.output
    assert "02:00–03:30" in res_pop.output
    assert "мапа, API" in res_pop.output
    assert "«Оновлюємо базу»" in res_pop.output
    assert "ще 47 хв" in res_pop.output
    assert "06.09" in res_pop.output

    # Backward compatibility via mnt ls
    res_pop_ls = runner.invoke(cli, ["mnt", "ls"])
    assert res_pop_ls.exit_code == 0
    assert "зараз" in res_pop_ls.output

    # Error handling
    mock_list_mnt.side_effect = Exception("Redis error")
    res_err = runner.invoke(cli, ["mnt", "status"])
    assert res_err.exit_code == 1
    assert "error loading maintenance schedule" in res_err.output


@patch("ops.state.add_maintenance_window")
def test_mnt_add_command(mock_add_win, runner):
    mock_add_win.return_value = {
        "id": "mnt_123",
        "components": ["map", "api"],
        "note": "Оновлюємо базу",
        "time_text": "02:00–03:30",
    }

    res = runner.invoke(
        cli,
        [
            "mnt",
            "add",
            "map,api",
            "--from",
            "05.09 02:00",
            "--for",
            "90m",
            "-n",
            "Оновлюємо базу",
        ],
    )
    assert res.exit_code == 0
    assert "Заплановано" in res.output
    assert "02:00" in res.output
    assert "03:30" in res.output
    assert "мапа, API" in res.output
    assert "«Оновлюємо базу»" in res.output

    # Error handling
    mock_add_win.side_effect = ValueError("Invalid time")
    res_err = runner.invoke(cli, ["mnt", "add", "map", "--from", "invalid"])
    assert res_err.exit_code == 1
    assert "error scheduling maintenance" in res_err.output


@patch("ops.state.complete_maintenance_window")
def test_mnt_done_command(mock_complete, runner):
    # None active
    mock_complete.return_value = None
    res_none = runner.invoke(cli, ["mnt", "done"])
    assert res_none.exit_code == 0
    assert "Немає активних планових робіт для завершення" in res_none.output

    # Completed active window
    mock_complete.return_value = {
        "id": "mnt_123",
        "components": ["map", "api"],
        "note": "Оновлюємо базу",
    }
    res_done = runner.invoke(cli, ["mnt", "done"])
    assert res_done.exit_code == 0
    assert "Планові роботи завершено" in res_done.output
    assert "Оновлюємо базу" in res_done.output
    assert "мапа, API" in res_done.output

    # With window id
    res_id = runner.invoke(cli, ["mnt", "done", "mnt_123"])
    assert res_id.exit_code == 0
    assert "Планові роботи завершено" in res_id.output

    # Error handling
    mock_complete.side_effect = Exception("DB error")
    res_err = runner.invoke(cli, ["mnt", "done"])
    assert res_err.exit_code == 1
    assert "error completing maintenance" in res_err.output


def test_alert_and_shelling_help(runner):
    # Alert help in unified style
    res_alert = runner.invoke(cli, ["alert", "--help"])
    assert res_alert.exit_code == 0
    assert "USAGE" in res_alert.output
    assert "sirens-ops alert <district> <on|off> [options]" in res_alert.output
    assert "ARGUMENTS" in res_alert.output
    assert "DISTRICT" in res_alert.output
    assert "OPTIONS" in res_alert.output
    assert "EXAMPLES" in res_alert.output
    assert "sirens-ops alert kyiv on" in res_alert.output

    # Shelling help in unified style
    res_shelling = runner.invoke(cli, ["shelling", "--help"])
    assert res_shelling.exit_code == 0
    assert "USAGE" in res_shelling.output
    assert "sirens-ops shelling <district> <on|off> [options]" in res_shelling.output
    assert "ARGUMENTS" in res_shelling.output
    assert "OPTIONS" in res_shelling.output
    assert "EXAMPLES" in res_shelling.output
    assert "sirens-ops shelling nikopol on" in res_shelling.output

    # Status, Show, History help
    res_status = runner.invoke(cli, ["status", "--help"])
    assert res_status.exit_code == 0
    assert "sirens-ops status [options]" in res_status.output

    res_show = runner.invoke(cli, ["show", "--help"])
    assert res_show.exit_code == 0
    assert "sirens-ops show <district> [options]" in res_show.output

    res_history = runner.invoke(cli, ["history", "--help"])
    assert res_history.exit_code == 0
    assert "sirens-ops history [district] [options]" in res_history.output


@patch("ops.state.add_maintenance_window")
@patch("ops.state.complete_maintenance_window")
def test_mnt_on_and_off_commands(mock_complete, mock_add, runner):
    mock_add.return_value = {
        "id": "mnt_1",
        "components": ["all"],
        "note": "Emergency maintenance",
        "time_text": "10:00–11:00",
    }
    mock_complete.return_value = {
        "id": "mnt_1",
        "components": ["all"],
        "note": "Emergency maintenance",
    }

    res_on = runner.invoke(cli, ["mnt", "on", "all", "-m", "Emergency maintenance"])
    assert res_on.exit_code == 0
    mock_add.assert_called_once_with(
        components="all",
        from_str="now",
        for_str="60m",
        note="Emergency maintenance",
    )

    res_off = runner.invoke(cli, ["mnt", "off", "mnt_1"])
    assert res_off.exit_code == 0
    mock_complete.assert_called_once_with(window_id="mnt_1")


@patch("ops.state.get_maintenance")
@patch("ops.state.get_all_districts_statuses")
def test_status_with_active_maintenance_banner(mock_get_all, mock_get_mnt, runner):
    mock_get_mnt.return_value = {
        "active": True,
        "components": ["all"],
        "headline": "Планові роботи",
        "subtitle": "Scheduled cluster maintenance",
        "updated_at": 12345,
        "operator": "admin",
    }
    mock_get_all.return_value = []
    res = runner.invoke(cli, ["status"])
    assert res.exit_code == 0
    assert "MAINTENANCE ACTIVE" in res.output
    assert "Scheduled cluster maintenance" in res.output
