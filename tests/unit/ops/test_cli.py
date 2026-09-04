import time
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ops.cli import (
    cli,
    format_elapsed,
    print_history_list,
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
    assert "ALERT" in result.output


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
    assert "CLEAR" in result.output


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
    assert "https://t.me/test/1" in result.output


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
    assert "SHELLING ON" in res_on.output

    res_off = runner.invoke(cli, ["shelling", "nikopol", "off"])
    assert res_off.exit_code == 0
    assert "SHELLING OFF" in res_off.output


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

    # JSON output
    res_json = runner.invoke(cli, ["status", "--json"])
    assert res_json.exit_code == 0
    assert '"key": "bucha"' in res_json.output

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

    res_json = runner.invoke(cli, ["show", "kyiv", "--json"])
    assert res_json.exit_code == 0
    assert '"key": "kyiv"' in res_json.output

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


def test_entrypoints_importable():
    import ops.__main__  # noqa: F401
    import run_alerts  # noqa: F401
    import run_bi  # noqa: F401
    import run_ops  # noqa: F401

