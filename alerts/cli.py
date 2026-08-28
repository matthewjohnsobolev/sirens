import argparse

from config import APP_ENV_ALIASES, VERSION
from domain import real_channels, test_channels

FULL_HELP = """Sirens - Air Raid Alert Monitoring System

A Telegram bot that monitors air raid alerts in Ukrainian cities and broadcasts
them to corresponding Telegram channels.

Usage:
  sirens.py [OPTIONS]

Examples:
  sirens.py -m dev          Run in test mode (safe for testing)
  sirens.py -m prod         Run in production mode with real channels
  sirens.py --version       Display version information

Options:
  -m, --mode MODE     Set running mode: dev (test channels) or prod (real channels)
  -h, --help          Show this help message and exit
  --version           Show program version and exit

The bot will:
  • Monitor source channel for air raid alerts
  • Update channel photos based on alert status
  • Send alert messages to appropriate city channels

Mode details:
  dev    Uses test channels, safe for development and testing
  prod   Uses real channels, use with caution in production

For support and more information:
  GitHub: https://github.com/matthewjohnsobolev/sirens"""


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=50, width=100)

    def format_help(self):
        return FULL_HELP


def normalize_mode(value):
    """Fold APP_ENV spellings (development/production) onto the two run modes."""
    return APP_ENV_ALIASES.get(value.strip().lower(), value)


def get_args():
    parser = argparse.ArgumentParser(formatter_class=CustomHelpFormatter, add_help=False)

    parser.add_argument(
        "-m",
        "--mode",
        type=normalize_mode,
        choices=["prod", "dev"],
        default="dev",
        help="Run mode: dev (test channels) or prod (real channels, use with caution)",
    )

    parser.add_argument("--version", action="store_true", help="Show program version and exit")

    parser.add_argument("-h", "--help", action="help", help="Show this help message")

    args = parser.parse_args()

    if args.version:
        print(f"Sirens Ukraine {VERSION}")
        raise SystemExit(0)

    return args


def get_mode_config(args):
    channels = real_channels if args.mode == "prod" else test_channels
    return channels, channels["source"]
