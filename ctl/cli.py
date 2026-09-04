"""
Minimalist CLI for sirens-ctl.
Direct emergency threat status management: alert on/off, shelling on/off, ls, show, history.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.table import Table

from config import APP_ENV
from ctl import state

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(force_terminal=True, legacy_windows=False)


def format_elapsed(epoch: int | float | None, time_str: str | None = None) -> str:
    """Format elapsed time into a compact string like '12m ago' or '2h 15m ago'."""
    now = time.time()
    if epoch and epoch > 0:
        diff = max(0, int(now - epoch))
    elif time_str and time_str != "None" and ":" in time_str:
        try:
            parts = time_str.split(":")
            today = datetime.datetime.now()
            event_dt = today.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
            if event_dt > today:
                event_dt -= datetime.timedelta(days=1)
            diff = max(0, int((today - event_dt).total_seconds()))
        except Exception:
            return time_str or ""
    else:
        return ""

    if diff < 60:
        return "just now"
    minutes = diff // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    rem_min = minutes % 60
    if rem_min > 0:
        return f"{hours}h {rem_min}m ago"
    return f"{hours}h ago"


def render_ls_table(districts: list[dict[str, Any]]) -> Table:
    """Render compact status list matching dot style:
    ● bucha       Kyiv       alert     19:15 (24m ago)  chan:-1001754447620
    ○ nikopol     Dnipro     clear     17:05            chan:-1001754447620
    """
    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        pad_edge=False,
        show_edge=False,
    )

    table.add_column("St", justify="center", width=2)
    table.add_column("District", style="bold white", min_width=14)
    table.add_column("Oblast", style="dim", min_width=12)
    table.add_column("Air Raid", min_width=10)
    table.add_column("Shelling", min_width=10)
    table.add_column("Updated", style="dim", min_width=16)
    table.add_column("Channel", style="dim")

    for d in districts:
        is_alert = d["alert"]["status"]
        is_shelling = d["shelling"]["status"]

        if is_alert or is_shelling:
            dot = "[bold red]●[/]"
        else:
            dot = "[dim green]○[/]"

        if is_alert:
            alert_str = "[bold red]alert[/]"
        else:
            alert_str = "[dim green]clear[/]"

        if is_shelling:
            shelling_str = "[bold yellow]shelling[/]"
        else:
            shelling_str = "[dim]none[/]"

        time_val = d["alert"].get("time") if is_alert else d["shelling"].get("time")
        if not time_val or time_val == "None":
            time_val = d["alert"].get("time", "")
        updated_epoch = d["alert"].get("updated_at") or d["shelling"].get("updated_at")
        elapsed = format_elapsed(updated_epoch, time_val)
        updated_str = (
            f"{time_val} ({elapsed})"
            if (time_val and elapsed and elapsed != time_val)
            else (time_val or "-")
        )

        chan = str(d["channel_id"]) if d.get("has_channel") and d.get("channel_id") else "map-only"

        table.add_row(
            dot,
            d["key"],
            d["oblast_key"].replace("_oblast", "").capitalize(),
            alert_str,
            shelling_str,
            updated_str,
            chan,
        )

    return table


def print_show_detail(data: dict[str, Any]) -> None:
    """Compact key-value inspection output."""
    alert = data["alert"]
    shelling = data["shelling"]

    alert_dot = "[bold red]● active[/]" if alert["status"] else "[dim green]○ clear[/]"
    alert_time = alert.get("time", "-")
    alert_elapsed = format_elapsed(alert.get("updated_at"), alert_time)
    alert_time_fmt = f"{alert_time} ({alert_elapsed})" if alert_time != "-" else "-"

    shelling_dot = "[bold yellow]● active[/]" if shelling["status"] else "[dim]○ none[/]"
    shelling_time = shelling.get("time", "-")

    disp_name = data.get("display_name")
    name_str = (
        f"{data['name']} / {disp_name}" if disp_name and disp_name != data["name"] else data["name"]
    )
    channel_info = (
        str(data["channel_id"])
        if data.get("has_channel") and data.get("channel_id")
        else "map-only (no channel)"
    )
    console.print(f"[bold white]{data['key']}[/] ({name_str}) · [dim]{data['oblast_key']}[/]")
    console.print(
        f"  air raid:  {alert_dot} since {alert_time_fmt}  [dim]type: {alert.get('type')}[/]"
    )
    console.print(f"  shelling:  {shelling_dot} since {shelling_time}")
    console.print(f"  channel:   [dim]{channel_info}[/]")
    if alert.get("source") and alert.get("source") != "None":
        console.print(f"  source:    [dim]{alert['source']}[/]")


def print_history_list(history: list[dict[str, Any]], district: str | None = None) -> None:
    """Print history in compact log format."""
    if not history:
        console.print("[dim]No alert history records found.[/]")
        return

    table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold dim",
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("Time", style="bold white", min_width=16)
    table.add_column("District", min_width=12)
    table.add_column("Event", min_width=10)
    table.add_column("Channel", style="dim", min_width=14)
    table.add_column("Source / Reason", style="dim")

    for h in history:
        ev_type = h.get("type", "")
        if "cancelled" in ev_type:
            badge = "[dim green]○ clear[/]"
        elif "shelling" in ev_type:
            badge = "[bold yellow]● shelling[/]"
        else:
            badge = "[bold red]● alert[/]"

        dt_str = f"{h.get('date')} {h.get('time')}"
        table.add_row(
            dt_str,
            h.get("district_key") or "-",
            badge,
            str(h.get("channel_id") or "-"),
            h.get("message_link") or "-",
        )

    console.print(table)


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
            from ctl.broadcast import run_broadcast_sync

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

    console.print(render_ls_table(districts))


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

    print_show_detail(data)


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

    print_history_list(rows, district=district_key)
