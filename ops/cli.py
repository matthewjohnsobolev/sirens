"""
Minimalist CLI for sirens-ops.
Emergency threat and maintenance management: alert on/off, shelling on/off, maintenance on/off, status, show, history.
"""

from __future__ import annotations

import datetime
import sys
import time
from typing import Any

import click
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from config import APP_ENV
from ops import state

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(force_terminal=True, legacy_windows=False)


def format_source_by(source: str | None, default: str = "manual") -> str:
    """Normalize source string to 'manual' or 'auto'."""
    if not source or source == "None":
        return default
    s_low = str(source).lower()
    if any(k in s_low for k in ("manual", "cli", "operator")):
        return "manual"
    if any(k in s_low for k in ("mon_channel", "telegram", "tg", "auto", "t.me", "channel")):
        return "auto"
    return default


def format_duration(epoch: int | float | None, time_str: str | None = None) -> str:
    """Format duration into a compact string like '45m' or '1h 19m'."""
    now = time.time()
    diff = 0
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
            return "--"
    else:
        return "--"

    if diff < 60:
        return "1m"
    minutes = diff // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    rem_min = minutes % 60
    if rem_min > 0:
        return f"{hours}h {rem_min}m"
    return f"{hours}h"


def format_oblast_title(oblast_key: str) -> str:
    """Format oblast key to uppercase header title e.g. DNIPROPETROVSK OBLAST."""
    if not oblast_key:
        return "OTHER"
    if oblast_key == "kyiv":
        return "KYIV CITY"
    if oblast_key.endswith("_oblast"):
        base = oblast_key[: -len("_oblast")].replace("_", " ").upper()
        return f"{base} OBLAST"
    return oblast_key.replace("_", " ").upper()


def format_target_type(district_key: str, conf: dict[str, Any] | None = None) -> str:
    """Identify whether a target is a city or a district."""
    name = (conf or {}).get("name", "")
    oblast = (conf or {}).get("oblast", "")
    if district_key == "kyiv" or "м. Київ" in name or oblast == "kyiv":
        return "city"
    return "district"


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


def render_status_table(districts: list[dict[str, Any]]) -> Group:
    """Render status list grouped by Oblast:
    DNIPROPETROVSK OBLAST
      DISTRICT         STATUS      SINCE   FOR
      ● synelnykove    alert       23:14   45m
      ○ nikopol        clear       21:00   --
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in districts:
        grouped.setdefault(d.get("oblast_key", "other"), []).append(d)

    renderables: list[Any] = []

    for oblast_key, o_districts in grouped.items():
        title = format_oblast_title(oblast_key)
        renderables.append(Text(title, style="bold white"))

        sub_table = Table(
            box=None,
            show_header=True,
            header_style="bold dim",
            pad_edge=False,
            show_edge=False,
        )
        sub_table.add_column("  DISTRICT", style="bold white", min_width=18)
        sub_table.add_column("STATUS", min_width=12)
        sub_table.add_column("SINCE", min_width=8)
        sub_table.add_column("FOR", min_width=8)

        for d in o_districts:
            is_alert = d["alert"]["status"]
            is_shelling = d["shelling"]["status"]

            if is_alert and is_shelling:
                a_time = d["alert"].get("time", "-")
                a_for = format_duration(d["alert"].get("updated_at"), a_time)
                sub_table.add_row(
                    f"  [bold red]●[/] {d['key']}",
                    "[bold red]alert[/]",
                    a_time if a_time != "None" else "-",
                    a_for,
                )
                s_time = d["shelling"].get("time", "-")
                s_for = format_duration(d["shelling"].get("updated_at"), s_time)
                sub_table.add_row(
                    f"  [bold yellow]●[/] {d['key']}",
                    "[bold yellow]shelling[/]",
                    s_time if s_time != "None" else "-",
                    s_for,
                )
            elif is_alert:
                a_time = d["alert"].get("time", "-")
                a_for = format_duration(d["alert"].get("updated_at"), a_time)
                sub_table.add_row(
                    f"  [bold red]●[/] {d['key']}",
                    "[bold red]alert[/]",
                    a_time if a_time != "None" else "-",
                    a_for,
                )
            elif is_shelling:
                s_time = d["shelling"].get("time", "-")
                s_for = format_duration(d["shelling"].get("updated_at"), s_time)
                sub_table.add_row(
                    f"  [bold yellow]●[/] {d['key']}",
                    "[bold yellow]shelling[/]",
                    s_time if s_time != "None" else "-",
                    s_for,
                )
            else:
                time_val = d["alert"].get("time") or d["shelling"].get("time") or "-"
                if time_val == "None":
                    time_val = "-"
                sub_table.add_row(
                    f"  [dim green]○[/] {d['key']}",
                    "[dim green]clear[/]",
                    time_val,
                    "--",
                )

        renderables.append(sub_table)
        renderables.append(Text(""))

    if renderables and isinstance(renderables[-1], Text) and renderables[-1].plain == "":
        renderables.pop()

    return Group(*renderables)


render_ls_table = render_status_table


def print_show_detail(data: dict[str, Any]) -> None:
    """Compact key-value inspection output matching unified style:
    TARGET      bucha (Бучанський район)
    OBLAST      Kyiv Oblast
    STATUS      ● air raid alert (since 23:14, 45m ago)
                ● threat of shelling (since 23:14, 45m ago)
    CHANNEL     -1001754447620
    UPDATED     2026-09-05 23:14:02 (manual)
    """
    alert = data.get("alert", {})
    shelling = data.get("shelling", {})

    target_name = data.get("name") or data.get("display_name") or ""
    target_val = (
        f"{data['key']} ({target_name})"
        if target_name and target_name != data["key"]
        else data["key"]
    )

    oblast_raw = data.get("oblast_key", "")
    oblast_formatted = format_oblast_title(oblast_raw).title()

    status_lines: list[str] = []
    if alert.get("status"):
        a_time = alert.get("time", "-")
        a_elapsed = format_elapsed(alert.get("updated_at"), a_time)
        since_str = f"(since {a_time}, {a_elapsed})" if a_time != "-" else f"({a_elapsed})" if a_elapsed else ""
        status_lines.append(f"[bold red]● air raid alert[/] {since_str}".strip())
    if shelling.get("status"):
        s_time = shelling.get("time", "-")
        s_elapsed = format_elapsed(shelling.get("updated_at"), s_time)
        since_str = f"(since {s_time}, {s_elapsed})" if s_time != "-" else f"({s_elapsed})" if s_elapsed else ""
        status_lines.append(f"[bold yellow]● threat of shelling[/] {since_str}".strip())
    if not status_lines:
        status_lines.append("[dim green]○ all clear[/]")

    channel_info = (
        str(data["channel_id"])
        if data.get("has_channel") and data.get("channel_id")
        else "map-only (no channel)"
    )

    updated_epoch = alert.get("updated_at") or shelling.get("updated_at")
    source_val = alert.get("source") or shelling.get("source")
    by_val = format_source_by(source_val)
    if updated_epoch and updated_epoch > 0:
        try:
            dt = datetime.datetime.fromtimestamp(updated_epoch, tz=state.get_kyiv_timezone())
            up_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            up_time_str = str(updated_epoch)
    else:
        t_fallback = alert.get("time") if alert.get("time") != "None" else shelling.get("time", "-")
        up_time_str = f"{datetime.date.today()} {t_fallback}" if t_fallback != "-" else "-"
    updated_str = f"{up_time_str} ({by_val})"

    console.print(f"{'TARGET':<12}{target_val}")
    console.print(f"{'OBLAST':<12}{oblast_formatted}")
    console.print(f"{'STATUS':<12}{status_lines[0]}")
    for extra_line in status_lines[1:]:
        console.print(f"{'':<12}{extra_line}")
    console.print(f"{'CHANNEL':<12}{channel_info}")
    console.print(f"{'UPDATED':<12}{updated_str}")


def print_history_list(history: list[dict[str, Any]], district: str | None = None) -> None:
    """Print history in unified borderless table:
    DATE         TIME    DISTRICT       STATUS                        BY
    2026-09-05   23:14   synelnykove    ● air raid alert              manual
    2026-09-05   21:00   nikopol        ○ air raid alert cancelled    manual
    2026-09-05   20:15   bucha          ● threat of shelling          auto
    """
    if not history:
        console.print("[dim]No alert history records found.[/]")
        return

    table = Table(
        box=None,
        show_header=True,
        header_style="bold dim",
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("DATE", style="bold white", min_width=12)
    table.add_column("TIME", style="bold white", min_width=8)
    table.add_column("DISTRICT", min_width=15)
    table.add_column("STATUS", min_width=30)
    table.add_column("BY", style="dim", min_width=8)

    for h in history:
        ev_type = str(h.get("type", "")).lower()
        if "cancelled" in ev_type:
            if "shelling" in ev_type:
                badge = "[dim]○ threat of shelling cancelled[/]"
            else:
                badge = "[dim green]○ air raid alert cancelled[/]"
        elif "shelling" in ev_type:
            badge = "[bold yellow]● threat of shelling[/]"
        else:
            badge = "[bold red]● air raid alert[/]"

        by_val = format_source_by(h.get("message_link"))

        table.add_row(
            str(h.get("date") or "-"),
            str(h.get("time") or "-"),
            str(h.get("district_key") or "-"),
            badge,
            by_val,
        )

    console.print(table)


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


class SirensOpsGroup(click.Group):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "Sirens Operations (sirens-ops) - Emergency threat status management.\n\n"
            "USAGE\n"
            "  sirens-ops [options] <command> [args]\n\n"
            "COMMANDS\n"
            "  status       Show threat status overview grouped by oblast\n"
            "  show         Inspect detailed status and metadata for a district or city\n"
            "  alert        Set air raid alert state (on/off) for a district or city\n"
            "  shelling     Set shelling threat state (on/off) for a district or city\n"
            "  history      Show recent threat event history log from PostgreSQL\n"
            "  mnt          Manage scheduled maintenance windows (планові роботи)\n"
            "  maintenance  Alias for mnt\n\n"
            "OPTIONS\n"
            "  -m, --mode   Run mode: dev | prod (default: dev)\n"
            "  -y, --yes    Skip confirmation prompt before broadcast on prod\n"
            "  -h, --help   Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops status\n"
            "  sirens-ops alert kyiv on\n"
            "  sirens-ops shelling nikopol on -b\n"
            "  sirens-ops show bucha\n"
            "  sirens-ops history\n"
            "  sirens-ops mnt status\n"
        )
        formatter.write(help_text)


class AlertCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops alert <district> <on|off> [options]\n\n"
            "ARGUMENTS\n"
            "  DISTRICT         District key or city name (e.g. bucha, kyiv, nikopol)\n"
            "  STATE            Alert state: on | off\n\n"
            "OPTIONS\n"
            "  -s, --source     Source link, operator, or label (default: manual)\n"
            "  -d, --date       Event date in Kyiv timezone (DD.MM or YYYY-MM-DD, default: today)\n"
            "  -t, --time       Event time in Kyiv timezone (HH:MM, default: now)\n"
            "  -b, --broadcast  Broadcast alert to Telegram channel\n"
            "  -y, --yes        Skip confirmation prompt on prod\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops alert kyiv on\n"
            "  sirens-ops alert bucha off\n"
            "  sirens-ops alert bucha on -b\n"
            "  sirens-ops alert nikopol on -t 14:30 -d 04.09\n"
        )
        formatter.write(help_text)


class ShellingCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops shelling <district> <on|off> [options]\n\n"
            "ARGUMENTS\n"
            "  DISTRICT         District key or city name (e.g. nikopol, berdiansk)\n"
            "  STATE            Threat state: on | off\n\n"
            "OPTIONS\n"
            "  -s, --source     Source link, operator, or label (default: manual)\n"
            "  -d, --date       Event date in Kyiv timezone (DD.MM or YYYY-MM-DD, default: today)\n"
            "  -t, --time       Event time in Kyiv timezone (HH:MM, default: now)\n"
            "  -b, --broadcast  Broadcast shelling threat to Telegram channel\n"
            "  -y, --yes        Skip confirmation prompt on prod\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops shelling nikopol on\n"
            "  sirens-ops shelling nikopol off\n"
            "  sirens-ops shelling nikopol on -b\n"
        )
        formatter.write(help_text)


class StatusCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops status [options]\n\n"
            "OPTIONS\n"
            "  -a, --all        Show all districts (default: active threats only)\n"
            "      --oblast     Filter by oblast key (e.g. dnipropetrovsk_oblast)\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops status\n"
            "  sirens-ops status -a\n"
            "  sirens-ops status --oblast kyiv_oblast\n"
        )
        formatter.write(help_text)


class ShowCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops show <district> [options]\n\n"
            "ARGUMENTS\n"
            "  DISTRICT         District key or city name (e.g. bucha, kyiv, nikopol)\n\n"
            "OPTIONS\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops show bucha\n"
            "  sirens-ops show kyiv\n"
        )
        formatter.write(help_text)


class HistoryCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops history [district] [options]\n\n"
            "ARGUMENTS\n"
            "  DISTRICT         Filter events by district key or city (optional)\n\n"
            "OPTIONS\n"
            "  -n, --limit      Number of recent records to display (default: 10)\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops history\n"
            "  sirens-ops history bucha\n"
            "  sirens-ops history -n 25\n"
        )
        formatter.write(help_text)


class MntGroup(click.Group):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt <command> [options]\n\n"
            "COMMANDS\n"
            "  status       Show scheduled maintenance windows and active status\n"
            "  on           Immediately start maintenance\n"
            "  off          Complete active maintenance window (alias for mnt done)\n"
            "  add          Schedule a new maintenance window (планові роботи)\n"
            "  done         Complete active maintenance window early (зняти достроково)\n\n"
            "OPTIONS\n"
            "  -h, --help   Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt status\n"
            "  sirens-ops mnt on --for 2h -m \"Планові роботи\"\n"
            "  sirens-ops mnt off\n"
            "  sirens-ops mnt add --from \"23:00\" --for 2h -c map,api -n \"Оновлення\"\n"
            "  sirens-ops mnt done\n"
        )
        formatter.write(help_text)


class MntStatusCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt status [options]\n\n"
            "OPTIONS\n"
            "  -a, --all        Show completed windows as well\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt status\n"
            "  sirens-ops mnt status -a\n"
        )
        formatter.write(help_text)


class MntAddCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt add <components> [options]\n\n"
            "ARGUMENTS\n"
            "  COMPONENTS       Target components (e.g. map, api, alerts, or all)\n\n"
            "OPTIONS\n"
            "      --from       Start time in Kyiv timezone (e.g. \"02:00\", \"now\", default: now)\n"
            "      --for        Duration (e.g. 60m, 2h, default: 60m)\n"
            "  -n, -m, --note   Notice description (планові роботи)\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt add map,api --from \"02:00\" --for 90m -n \"Оновлення БД\"\n"
            "  sirens-ops mnt add all --for 2h\n"
        )
        formatter.write(help_text)


class MntDoneCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt done [window_id] [options]\n\n"
            "ARGUMENTS\n"
            "  WINDOW_ID        Maintenance window ID (optional, defaults to active window)\n\n"
            "OPTIONS\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt done\n"
            "  sirens-ops mnt done mnt_1725573600\n"
        )
        formatter.write(help_text)


class MntOnCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt on [components] [options]\n\n"
            "ARGUMENTS\n"
            "  COMPONENTS       Target components (default: all)\n\n"
            "OPTIONS\n"
            "      --for        Duration (default: 60m)\n"
            "  -m, -n, --note   Notice description\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt on\n"
            "  sirens-ops mnt on map,api --for 2h -m \"Термінові роботи\"\n"
        )
        formatter.write(help_text)


class MntOffCommand(click.Command):
    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        help_text = (
            "USAGE\n"
            "  sirens-ops mnt off [window_id] [options]\n\n"
            "ARGUMENTS\n"
            "  WINDOW_ID        Maintenance window ID (optional, defaults to active window)\n\n"
            "OPTIONS\n"
            "  -h, --help       Show this help message and exit\n\n"
            "EXAMPLES\n"
            "  sirens-ops mnt off\n"
        )
        formatter.write(help_text)


@click.group(cls=SirensOpsGroup, context_settings=CONTEXT_SETTINGS, no_args_is_help=True)
@click.option(
    "-m",
    "--mode",
    type=click.Choice(["dev", "prod"], case_sensitive=False),
    default=APP_ENV,
    help="Run mode: dev or prod (default: dev)",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Do not prompt for confirmation before broadcast on prod",
)
@click.pass_context
def cli(ctx: click.Context, mode: str, yes: bool):
    """Sirens Operations (sirens-ops) - Emergency threat status management."""
    ctx.ensure_object(dict)
    ctx.obj["mode"] = mode.lower()
    ctx.obj["yes"] = yes


def _apply_and_print(
    ctx: click.Context,
    district_query: str,
    alert_active: bool | None,
    shelling_active: bool | None,
    source: str | None = None,
    date_str: str | None = None,
    time_str: str | None = None,
    broadcast: bool = False,
    yes: bool = False,
) -> None:
    env = ctx.obj["mode"]
    resolved = state.resolve_district(district_query)
    if not resolved:
        console.print(f"[red]district '{district_query}' not found[/]")
        sys.exit(1)

    district_key, _ = resolved

    skip_prompt = yes or ctx.obj.get("yes", False)
    if broadcast and env == "prod" and not skip_prompt:
        click.confirm(
            f"Broadcast to {district_key} Telegram channel?",
            default=False,
            abort=True,
        )

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
            broadcast_msg = "[yellow]broadcast skipped (channel not configured)[/]"
        else:
            from ops.broadcast import run_broadcast_sync

            target_event = "air_raid_alert" if alert_active else "air_raid_alert_cancelled"
            if shelling_active is not None:
                target_event = (
                    "threat_of_shelling" if shelling_active else "threat_of_shelling_cancelled"
                )

            try:
                tg_res = run_broadcast_sync(target_cid, target_event)
                link = tg_res.get("message_link")
                link_str = f" [dim]({link})[/]" if link else ""
                broadcast_msg = f"[cyan]broadcast sent[/] ({target_cid}){link_str}"
            except Exception as e:
                console.print(f"[red]error broadcasting to Telegram:[/] {e}")
                sys.exit(1)

    # Clean Key-Value card format
    conf = resolved[1] if resolved else None
    target_type = format_target_type(district_key, conf)
    target_val = f"{district_key} ({target_type})"

    if alert_active is True:
        status_val = "[bold red]● air raid alert on[/]"
    elif alert_active is False:
        status_val = "[dim green]○ air raid alert off[/]"
    elif shelling_active is True:
        status_val = "[bold yellow]● threat of shelling on[/]"
    else:
        status_val = "[dim]○ threat of shelling off[/]"

    time_val = res.get("time", "")
    since_val = time_val or "now"
    by_val = format_source_by(source or res.get("source"))

    console.print(f"{'TARGET':<12}{target_val}")
    console.print(f"{'STATUS':<12}{status_val}")
    console.print(f"{'SINCE':<12}{since_val}")
    console.print(f"{'BY':<12}{by_val}")
    if broadcast:
        console.print(f"{'BROADCAST':<12}{broadcast_msg}")


# --- Threat commands: alert on/off, shelling on/off ---


@cli.command(name="alert", cls=AlertCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("district")
@click.argument("state_val", type=click.Choice(["on", "off"], case_sensitive=False))
@click.option("-s", "--source", default=None, help="Source link, operator, or label (default: manual)")
@click.option(
    "-d",
    "--date",
    "date_str",
    default=None,
    help="Event date in Kyiv timezone (DD.MM or YYYY-MM-DD; default: today)",
)
@click.option(
    "-t", "--time", "time_str", default=None, help="Event time in Kyiv timezone (HH:MM; default: now)"
)
@click.option(
    "-b", "--broadcast", is_flag=True, default=False, help="Broadcast alert to Telegram channel"
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Do not prompt for confirmation before broadcast on prod",
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
    yes: bool,
):
    """Set air raid alert state (on/off) for a district or city."""
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
        yes=yes,
    )


@cli.command(name="shelling", cls=ShellingCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("district")
@click.argument("state_val", type=click.Choice(["on", "off"], case_sensitive=False))
@click.option("-s", "--source", default=None, help="Source link, operator, or label (default: manual)")
@click.option(
    "-d",
    "--date",
    "date_str",
    default=None,
    help="Event date in Kyiv timezone (DD.MM or YYYY-MM-DD; default: today)",
)
@click.option(
    "-t", "--time", "time_str", default=None, help="Event time in Kyiv timezone (HH:MM; default: now)"
)
@click.option(
    "-b",
    "--broadcast",
    is_flag=True,
    default=False,
    help="Broadcast shelling threat to Telegram channel",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Do not prompt for confirmation before broadcast on prod",
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
    yes: bool,
):
    """Set shelling threat state (on/off) for a district or city."""
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
        yes=yes,
    )


# --- Inspection and query commands ---


@cli.command(name="status", cls=StatusCommand, context_settings=CONTEXT_SETTINGS)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show all districts (default: active threats only)",
)
@click.option("--oblast", default=None, help="Filter by oblast key (e.g. dnipropetrovsk_oblast)")
@click.pass_context
def status_cmd(ctx: click.Context, show_all: bool, oblast: str | None):
    """Show threat status overview grouped by oblast (active threats by default; use -a for all)."""
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

    try:
        mnt = state.get_maintenance()
        if mnt and mnt.get("active"):
            comps_str = ", ".join(mnt.get("components") or ["all"])
            msg = mnt.get("subtitle") or "Тривають планові технічні роботи."
            console.print(
                f"  [bold blue]●[/] [bold white]MAINTENANCE ACTIVE:[/] {msg} [dim](components: {comps_str})[/]\n"
            )
    except Exception:
        pass

    if not districts:
        if not show_all:
            console.print(
                "  [dim green]○ No active alerts or shellings.[/]  (use 'status -a' to view all districts)"
            )
        else:
            console.print("  [dim]No districts found.[/]")
        return

    console.print(render_status_table(districts))


@cli.command(name="show", cls=ShowCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("district")
@click.pass_context
def show_cmd(ctx: click.Context, district: str):
    """Inspect detailed status and metadata for a district or city."""
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

    print_show_detail(data)


@cli.command(name="history", cls=HistoryCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("district", required=False, default=None)
@click.option("-n", "--limit", default=10, help="Number of recent records to display (default: 10)")
@click.pass_context
def history_cmd(ctx: click.Context, district: str | None, limit: int):
    """Show recent threat event history log from PostgreSQL."""
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


# --- Maintenance (planned works) commands ---


def print_mnt_schedule(windows: list[dict[str, Any]]) -> None:
    """Render scheduled maintenance windows list matching compact style."""
    if not windows:
        console.print("  [dim green]○ Немає запланованих робіт.[/]")
        return

    table = Table(box=None, show_header=True, header_style="bold dim", pad_edge=False, show_edge=False)
    table.add_column("  STATUS", min_width=14)
    table.add_column("TIME", min_width=14)
    table.add_column("COMPONENTS", min_width=14)
    table.add_column("NOTE", min_width=20)
    table.add_column("REMAINING", style="dim")

    for w in windows:
        st_code = w.get("status_code", "")
        st_lbl = w.get("status_label", "")
        if st_code == "active":
            dot_str = f"  [bold blue]●[/] {st_lbl}"
        else:
            dot_str = f"  [dim]○[/] {st_lbl}"

        note_val = w.get("note", "")
        if note_val and not (note_val.startswith("«") and note_val.endswith("»")):
            note_formatted = f"«{note_val}»"
        else:
            note_formatted = note_val

        table.add_row(
            dot_str,
            w.get("time_text", ""),
            w.get("components_uk", ""),
            note_formatted,
            w.get("remaining_str", ""),
        )

    console.print(Text("SCHEDULED MAINTENANCE", style="bold white"))
    console.print(table)


@cli.group(name="mnt", cls=MntGroup, context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.pass_context
def mnt_group(ctx: click.Context):
    """Manage scheduled maintenance windows (планові роботи)."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(mnt_status_cmd)


@mnt_group.command(name="add", cls=MntAddCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("components")
@click.option(
    "--from",
    "from_str",
    default="now",
    help='Start time in Kyiv timezone (e.g. "05.09 02:00", "02:00", or "now")',
)
@click.option("--for", "for_str", default="60m", help='Duration (e.g. "90m", "2h", "1h30m"; default: 60m)')
@click.option(
    "-n",
    "--note",
    "-m",
    "--message",
    "note",
    default=None,
    help='Maintenance notice (e.g. "Оновлюємо базу")',
)
@click.pass_context
def mnt_add_cmd(
    ctx: click.Context,
    components: str,
    from_str: str,
    for_str: str,
    note: str | None,
):
    """Schedule a new maintenance window (планові роботи)."""
    try:
        win = state.add_maintenance_window(
            components=components,
            from_str=from_str,
            for_str=for_str,
            note=note,
        )
    except Exception as e:
        console.print(f"[red]error scheduling maintenance:[/] {e}")
        sys.exit(1)

    comps_uk = state.format_components_uk(win["components"])
    note_txt = f"«{win['note']}»" if win.get("note") else ""
    console.print(f"{'TARGET':<12}maintenance ({comps_uk})")
    console.print(f"{'STATUS':<12}[bold blue]● scheduled[/] (Заплановано)")
    console.print(f"{'PERIOD':<12}{win['time_text']}")
    if note_txt:
        console.print(f"{'NOTE':<12}{note_txt}")


@mnt_group.command(name="status", cls=MntStatusCommand, context_settings=CONTEXT_SETTINGS)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show completed windows as well",
)
@click.pass_context
def mnt_status_cmd(ctx: click.Context, show_all: bool):
    """Show scheduled maintenance windows and active status."""
    try:
        windows = state.list_maintenance_windows(include_completed=show_all)
    except Exception as e:
        console.print(f"[red]error loading maintenance schedule:[/] {e}")
        sys.exit(1)

    print_mnt_schedule(windows)


# Backward compatibility alias: mnt ls -> mnt status
mnt_group.add_command(
    click.Command(
        name="ls",
        callback=mnt_status_cmd.callback,
        params=list(mnt_status_cmd.params),
        hidden=True,
        help="Alias for mnt status.",
    ),
    name="ls",
)


@mnt_group.command(name="done", cls=MntDoneCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("window_id", required=False, default=None)
@click.pass_context
def mnt_done_cmd(ctx: click.Context, window_id: str | None):
    """Complete active maintenance window early (зняти достроково)."""
    try:
        res = state.complete_maintenance_window(window_id=window_id)
    except Exception as e:
        console.print(f"[red]error completing maintenance:[/] {e}")
        sys.exit(1)

    if not res:
        console.print("  [dim]Немає активних планових робіт для завершення.[/]")
        return

    comps_uk = state.format_components_uk(res.get("components", ["all"]))
    note_txt = f"«{res.get('note', '')}»" if res.get("note") else ""
    console.print(f"{'TARGET':<12}maintenance ({comps_uk})")
    console.print(f"{'STATUS':<12}[dim green]○ completed[/] (Планові роботи завершено)")
    if note_txt:
        console.print(f"{'NOTE':<12}{note_txt}")


@mnt_group.command(name="on", cls=MntOnCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("components", required=False, default="all")
@click.option("-m", "--message", "-n", "--note", default=None, help="Maintenance notice")
@click.option("--for", "for_str", default="60m", help="Duration (e.g. 60m, 2h; default: 60m)")
@click.pass_context
def mnt_on_cmd(ctx: click.Context, components: str, message: str | None, for_str: str):
    """Immediately start maintenance."""
    ctx.invoke(mnt_add_cmd, components=components, from_str="now", for_str=for_str, note=message)


@mnt_group.command(name="off", cls=MntOffCommand, context_settings=CONTEXT_SETTINGS)
@click.argument("window_id", required=False, default=None)
@click.pass_context
def mnt_off_cmd(ctx: click.Context, window_id: str | None):
    """Complete active maintenance window (alias for mnt done)."""
    ctx.invoke(mnt_done_cmd, window_id=window_id)


# Register maintenance alias for mnt
cli.add_command(mnt_group, name="maintenance")


