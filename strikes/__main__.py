"""
python -m strikes --region kyiv "<post text>"   (or the text on stdin)
"""

import json
import sys

import click

from strikes.parser import StrikeParser


@click.command()
@click.option("--region", default=None, help="District or oblast key the channel covers.")
@click.argument("text", required=False)
def main(region: str | None, text: str | None) -> None:
    result = StrikeParser().parse(text if text is not None else sys.stdin.read(), region)
    click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
