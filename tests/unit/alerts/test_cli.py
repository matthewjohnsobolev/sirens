import argparse
from unittest.mock import patch

import pytest

from alerts.cli import FULL_HELP, CustomHelpFormatter, get_args, get_mode_config
from config import VERSION
from domain import (
    real_channels,
    real_source_channels,
    test_channels,
    test_source_channels,
)


@pytest.mark.parametrize(
    "argv, expected_mode",
    [
        (["sirens.py"], "dev"),
        (["sirens.py", "-m", "dev"], "dev"),
        (["sirens.py", "--mode", "dev"], "dev"),
        (["sirens.py", "-m", "prod"], "prod"),
        (["sirens.py", "--mode", "prod"], "prod"),
        (["sirens.py", "-m", "production"], "prod"),
        (["sirens.py", "-m", "development"], "dev"),
        (["sirens.py", "-m", "PROD"], "prod"),
    ],
)
def test_get_args_parses_mode(argv, expected_mode):
    with patch("sys.argv", argv):
        assert get_args().mode == expected_mode


def test_get_args_rejects_unknown_mode(capsys):
    with patch("sys.argv", ["sirens.py", "-m", "staging"]):
        with pytest.raises(SystemExit):
            get_args()


def test_get_args_version_prints_version_and_exits(capsys):
    with patch("sys.argv", ["sirens.py", "--version"]):
        with pytest.raises(SystemExit) as exc_info:
            get_args()

    out = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert VERSION in out
    assert FULL_HELP not in out


def test_get_args_help_prints_full_help(capsys):
    with patch("sys.argv", ["sirens.py", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            get_args()

    assert exc_info.value.code == 0
    assert FULL_HELP in capsys.readouterr().out


def test_custom_help_formatter_returns_full_help():
    assert CustomHelpFormatter("sirens.py").format_help() == FULL_HELP


def test_get_mode_config_dev_uses_test_channels(monkeypatch):
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_CHANNEL_ID", None)
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID", None)
    channels, source, fallback = get_mode_config(argparse.Namespace(mode="dev"))

    assert channels is test_channels
    assert source == test_source_channels["primary"] == -1001843473515
    assert fallback is None


def test_get_mode_config_prod_uses_real_channels(monkeypatch):
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_CHANNEL_ID", None)
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID", None)
    channels, source, fallback = get_mode_config(argparse.Namespace(mode="prod"))

    assert channels is real_channels
    assert source == real_source_channels["primary"]
    assert fallback == real_source_channels["fallback"]


def test_get_mode_config_defaults_to_test_channels_for_unknown_mode(monkeypatch):
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_CHANNEL_ID", None)
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID", None)
    channels, source, fallback = get_mode_config(argparse.Namespace(mode="something-else"))

    assert channels is test_channels
    assert source == test_source_channels["primary"]
    assert fallback is None


def test_get_mode_config_respects_env_overrides(monkeypatch):
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_CHANNEL_ID", 111111)
    monkeypatch.setattr("alerts.cli.TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID", 222222)
    channels, source, fallback = get_mode_config(argparse.Namespace(mode="prod"))

    assert source == 111111
    assert fallback == 222222
