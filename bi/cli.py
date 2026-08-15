import argparse
from config import real_channels, test_channels, VERSION

FULL_HELP = f'''Sirens BI - subscriber counts across the network

Takes a snapshot of how many subscribers every Sirens channel has and stores
one row per channel per day. Runs once and exits - scheduling is cron's job,
see deploy/bi.sh.

Usage:
  run_bi.py [OPTIONS]

Examples:
  run_bi.py -m dev          Count test channels (safe for testing)
  run_bi.py -m prod         Count the real network channels
  run_bi.py --version       Display version information

Options:
  -m, --mode MODE     Set running mode: dev (test channels) or prod (real channels)
  -h, --help          Show this help message and exit
  --version           Show program version and exit

Re-running on the same day is safe: each day holds one row per channel, and a
second run updates it instead of adding a duplicate.

Requires its own Telegram session (data/sessions/bi.session), created with
./deploy/setup.sh bi - the alerts worker holds the sirens.session file.

For support and more information:
  GitHub: https://github.com/matthewjohnsobolev/sirens'''


class CustomHelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog):
        super().__init__(prog, max_help_position=50, width=100)

    def format_help(self):
        return FULL_HELP


def get_args():
    parser = argparse.ArgumentParser(
        formatter_class=CustomHelpFormatter,
        add_help=False
    )

    parser.add_argument(
        '-m', '--mode',
        choices=['prod', 'dev'],
        default='dev',
        help='Run mode: dev (test channels) or prod (real channels)'
    )

    parser.add_argument(
        '--version',
        action='store_true',
        help='Show program version and exit'
    )

    parser.add_argument(
        '-h', '--help',
        action='help',
        help='Show this help message'
    )

    args = parser.parse_args()

    if args.version:
        print(f'Sirens BI {VERSION}')
        raise SystemExit(0)

    return args


def get_mode_config(args):
    return real_channels if args.mode == 'prod' else test_channels
