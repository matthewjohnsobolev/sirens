import argparse

import pytest
from unittest.mock import patch

from bi.cli import FULL_HELP, CustomHelpFormatter, get_args, get_mode_config
from config import VERSION, real_channels, test_channels


@pytest.mark.parametrize("argv, expected_mode", [
    (['run_bi.py'], 'dev'),
    (['run_bi.py', '-m', 'dev'], 'dev'),
    (['run_bi.py', '--mode', 'dev'], 'dev'),
    (['run_bi.py', '-m', 'prod'], 'prod'),
    (['run_bi.py', '--mode', 'prod'], 'prod'),
])
def test_get_args_parses_mode(argv, expected_mode):
    with patch('sys.argv', argv):
        assert get_args().mode == expected_mode


def test_get_args_rejects_unknown_mode():
    with patch('sys.argv', ['run_bi.py', '-m', 'staging']):
        with pytest.raises(SystemExit):
            get_args()


def test_get_args_version_prints_version_and_exits(capsys):
    with patch('sys.argv', ['run_bi.py', '--version']):
        with pytest.raises(SystemExit) as exc_info:
            get_args()

    out = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert VERSION in out
    assert FULL_HELP not in out


def test_get_args_help_prints_full_help(capsys):
    with patch('sys.argv', ['run_bi.py', '--help']):
        with pytest.raises(SystemExit) as exc_info:
            get_args()

    assert exc_info.value.code == 0
    assert FULL_HELP in capsys.readouterr().out


def test_custom_help_formatter_returns_full_help():
    assert CustomHelpFormatter('run_bi.py').format_help() == FULL_HELP


def test_get_mode_config_dev_uses_test_channels():
    assert get_mode_config(argparse.Namespace(mode='dev')) is test_channels


def test_get_mode_config_prod_uses_real_channels():
    assert get_mode_config(argparse.Namespace(mode='prod')) is real_channels


def test_get_mode_config_defaults_to_test_channels_for_unknown_mode():
    assert get_mode_config(argparse.Namespace(mode='something-else')) is test_channels
