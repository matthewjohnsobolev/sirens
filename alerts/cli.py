import argparse
from config import real_channels, test_channels, VERSION

FULL_HELP = f'''Sirens - Air Raid Alert Monitoring System

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
        help='Run mode: dev (test channels) or prod (real channels, use with caution)'
    )


    parser.add_argument(
        '--version',
        action='version',
        version=f'Sirens Ukraine v{VERSION}',
        help='Show program version and exit'
    )

    parser.add_argument(
        '-h', '--help',
        action='help',
        help='Show this help message'
    )
    
    return parser.parse_args()

def get_mode_config(args):
    if args.mode == 'prod':
        return real_channels, -1001766138888
    else:
        return test_channels, -1001843473515