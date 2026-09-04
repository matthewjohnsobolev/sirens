from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ctl.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Sirens Control" in result.output
    assert "alert" in result.output
    assert "shelling" in result.output
    assert "ls" in result.output
    assert "show" in result.output
    assert "history" in result.output
    assert "done" not in result.output


@patch("ctl.state.apply_threat_change")
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
    assert "19:40" in result.output
    mock_apply.assert_called_once_with(
        district_key="bucha",
        alert_active=True,
        shelling_active=None,
        source=None,
        date_str=None,
        time_str=None,
        dry_run=False,
        env="dev",
    )


@patch("ctl.state.apply_threat_change")
def test_alert_off_command(mock_apply, runner):
    mock_apply.return_value = {
        "district_key": "bucha",
        "time": "19:45",
        "date": "2026-09-04",
        "channel_id": -1001754447620,
    }

    result = runner.invoke(cli, ["alert", "bucha", "off"])
    assert result.exit_code == 0
    assert "bucha" in result.output
    assert "CLEAR" in result.output
    mock_apply.assert_called_once_with(
        district_key="bucha",
        alert_active=False,
        shelling_active=None,
        source=None,
        date_str=None,
        time_str=None,
        dry_run=False,
        env="dev",
    )


@patch("ctl.state.apply_threat_change")
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
    mock_apply.assert_called_once_with(
        district_key="bucha",
        alert_active=True,
        shelling_active=None,
        source="https://t.me/test/1",
        date_str="04.09",
        time_str="14:30",
        dry_run=False,
        env="dev",
    )


@patch("ctl.state.apply_threat_change")
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


@patch("ctl.state.get_all_districts_statuses")
def test_ls_active_only(mock_get_all, runner):
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

    result = runner.invoke(cli, ["ls"])
    assert result.exit_code == 0
    assert "bucha" in result.output
    assert "alert" in result.output


@patch("ctl.state.get_district_status")
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

    result = runner.invoke(cli, ["show", "kyiv"])
    assert result.exit_code == 0
    assert "kyiv" in result.output
    assert "Kyiv" in result.output


@patch("ctl.state.get_history")
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

    result = runner.invoke(cli, ["history", "bucha"])
    assert result.exit_code == 0
    assert "bucha" in result.output
    assert "alert" in result.output
