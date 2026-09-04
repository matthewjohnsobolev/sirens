"""
Minimalist CLI for sirens-ctl.
Direct emergency threat status management: alert on/off, shelling on/off, ls, show, history.
"""

from __future__ import annotations

import json
import sys

import click

from config import APP_ENV
from ctl import state, ui
from ctl.ui import console


@click.group()
@click.option(
    "-m",
    "--mode",
    type=click.Choice(["dev", "prod"], case_sensitive=False),
    default=APP_ENV,
    help="Run mode: dev or prod",
)
@click.pass_context
def cli(ctx: click.Context, mode: str):
    """Sirens Control (sirens-ctl) - Emergency threat status management."""
    ctx.ensure_object(dict)
    ctx.obj["mode"] = mode.lower()


def _apply_and_print(
    ctx: click.Context,
    district_query: str,
    alert_active: bool | None,
    shelling_active: bool | None,
    source: str | None = None,
    date_str: str | None = None,
    time_str: str | None = None,
    broadcast: bool = False,
) -> None:
    env = ctx.obj["mode"]
    resolved = state.resolve_district(district_query)
    if not resolved:
        console.print(f"[red]district '{district_query}' not found[/]")
        sys.exit(1)

    district_key, _ = resolved

    try:
        res = state.apply_threat_change(
            district_key=district_key,
            alert_active=alert_active,
            shelling_active=shelling_active,
            source=source,
            date_str=date_str,
            time_str=time_str,
            dry_run=False,
            env=env,
        )
    except Exception as e:
        console.print(f"[red]error updating status:[/] {e}")
        sys.exit(1)

    # Optional Telegram broadcast
    broadcast_msg = ""
    if broadcast:
        target_cid = res.get("channel_id")
        if not target_cid:
            broadcast_msg = " [yellow](channel not configured; broadcast skipped)[/]"
        else:
            from ctl.telegram import run_broadcast_sync

            target_event = "air_raid_alert" if alert_active else "air_raid_alert_cancelled"
            if shelling_active is not None:
                target_event = (
                    "threat_of_shelling" if shelling_active else "threat_of_shelling_cancelled"
                )

            try:
                tg_res = run_broadcast_sync(target_cid, target_event)
                broadcast_msg = f" [cyan](broadcast sent: {tg_res.get('message_link')})[/]"
            except Exception as e:
                console.print(f"[red]error broadcasting to Telegram:[/] {e}")
                sys.exit(1)

    # Clean dot output format
    if alert_active is True:
        dot = "[bold red]●[/] " + f"[bold white]{district_key}[/]: [bold red]ALERT[/]"
    elif alert_active is False:
        dot = "[dim green]○[/] " + f"[bold white]{district_key}[/]: [dim green]CLEAR[/]"
    elif shelling_active is True:
        dot = "[bold yellow]●[/] " + f"[bold white]{district_key}[/]: [bold yellow]SHELLING ON[/]"
    else:
        dot = "[dim]○[/] " + f"[bold white]{district_key}[/]: [dim]SHELLING OFF[/]"

    date_val = res.get("date", "")
    time_val = res.get("time", "")
    ts_formatted = f"{date_val} {time_val}".strip()
    source_msg = f"  source: {source}" if source else ""

    console.print(f"  {dot}   {ts_formatted}{source_msg}{broadcast_msg}")


# --- Threat commands: alert on/off, shelling on/off ---


@cli.command(name="alert")
@click.argument("district")
@click.argument("state_val", type=click.Choice(["on", "off"], case_sensitive=False))
@click.option("-s", "--source", default=None, help="Source link or label")
@click.option(
    "-d",
    "--date",
    "date_str",
    default=None,
    help="Event date (Kyiv timezone, DD.MM or YYYY-MM-DD; default: today)",
)
@click.option(
    "-t", "--time", "time_str", default=None, help="Event time (Kyiv timezone, HH:MM; default: now)"
)
@click.option(
    "-b", "--broadcast", is_flag=True, default=False, help="Broadcast alert to Telegram channel"
)
@click.pass_context
def alert_cmd(
    ctx: click.Context,
    district: str,
    state_val: str,
    source: str | None,
    date_str: str | None,
    time_str: str | None,
    broadcast: bool,
):
    """Air raid alert on or off (Europe/Kyiv datetime)."""
    active = state_val.lower() == "on"
    _apply_and_print(
        ctx,
        district,
        alert_active=active,
        shelling_active=None,
        source=source,
        date_str=date_str,
        time_str=time_str,
        broadcast=broadcast,
    )


@cli.command(name="shelling")
@click.argument("district")
@click.argument("state_val", type=click.Choice(["on", "off"], case_sensitive=False))
@click.option("-s", "--source", default=None, help="Source link or label")
@click.option(
    "-d",
    "--date",
    "date_str",
    default=None,
    help="Event date (Kyiv timezone, DD.MM or YYYY-MM-DD; default: today)",
)
@click.option(
    "-t", "--time", "time_str", default=None, help="Event time (Kyiv timezone, HH:MM; default: now)"
)
@click.option(
    "-b",
    "--broadcast",
    is_flag=True,
    default=False,
    help="Broadcast shelling threat to Telegram channel",
)
@click.pass_context
def shelling_cmd(
    ctx: click.Context,
    district: str,
    state_val: str,
    source: str | None,
    date_str: str | None,
    time_str: str | None,
    broadcast: bool,
):
    """Shelling threat on or off (Europe/Kyiv datetime)."""
    active = state_val.lower() == "on"
    _apply_and_print(
        ctx,
        district,
        alert_active=None,
        shelling_active=active,
        source=source,
        date_str=date_str,
        time_str=time_str,
        broadcast=broadcast,
    )


# --- Inspection and query commands ---


@cli.command(name="ls")
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show all districts (default: active threats only)",
)
@click.option("--oblast", default=None, help="Filter by oblast key")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def ls_cmd(ctx: click.Context, show_all: bool, oblast: str | None, as_json: bool):
    """List district statuses (shows active threats by default; use -a for all)."""
    env = ctx.obj["mode"]
    try:
        districts = state.get_all_districts_statuses(
            filter_oblast=oblast,
            active_only=not show_all,
            env=env,
        )
    except Exception as e:
        console.print(f"[red]error connecting to Redis:[/] {e}")
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(districts, indent=2, ensure_ascii=False))
        return

    if not districts:
        if not show_all:
            console.print(
                "  [dim green]○ No active alerts or shellings.[/]  (use 'ls -a' to view all districts)"
            )
        else:
            console.print("  [dim]No districts found.[/]")
        return

    console.print(ui.render_ls_table(districts))


@cli.command(name="show")
@click.argument("district")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def show_cmd(ctx: click.Context, district: str, as_json: bool):
    """Show details for a district."""
    env = ctx.obj["mode"]
    resolved = state.resolve_district(district)
    if not resolved:
        console.print(f"[red]district '{district}' not found[/]")
        sys.exit(1)

    district_key, _ = resolved
    try:
        data = state.get_district_status(district_key, env=env)
    except Exception as e:
        console.print(f"[red]error fetching status:[/] {e}")
        sys.exit(1)

    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return

    ui.print_show_detail(data)


@cli.command(name="history")
@click.argument("district", required=False, default=None)
@click.option("-n", "--limit", default=10, help="Number of records (default: 10)")
@click.pass_context
def history_cmd(ctx: click.Context, district: str | None, limit: int):
    """Show recent alert history from PostgreSQL."""
    district_key = None
    if district:
        resolved = state.resolve_district(district)
        if not resolved:
            console.print(f"[red]district '{district}' not found[/]")
            sys.exit(1)
        district_key = resolved[0]

    try:
        rows = state.get_history(district_key=district_key, limit=limit)
    except Exception as e:
        console.print(f"[red]error querying PostgreSQL:[/] {e}")
        sys.exit(1)

    ui.print_history_list(rows, district=district_key)
