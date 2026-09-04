import datetime
import sys
import time
from typing import Any

from rich import box
from rich.console import Console
from rich.table import Table

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
    """Print history in compact log format:
    19:15  bucha  ● alert   manual:cli:operator
    18:40  bucha  ○ clear   https://t.me/c/...
    """
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
