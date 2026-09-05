"""
State manager for Sirens Operations CLI (sirens-ops).
Handles querying and mutating Redis live state and PostgreSQL alert history.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from config import (
    APP_ENV,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_TELEMETRY_NAMESPACE_ID,
    DATABASE_URL,
    REDIS_URL,
)
from domain import (
    BROADCAST_CITIES,
    DISTRICT_CONFIG,
    real_channels,
    test_channels,
)


def get_redis_client():
    """Lazily import and initialize Redis client."""
    import redis

    return redis.from_url(REDIS_URL, decode_responses=True)


def get_pg_connection():
    """Lazily import and initialize PostgreSQL connection."""
    import psycopg2

    return psycopg2.connect(DATABASE_URL)


def get_channels_map(env: str | None = None) -> dict[str, int]:
    current_env = env or APP_ENV
    return real_channels if current_env == "prod" else test_channels


def resolve_district(query: str) -> tuple[str, dict[str, Any]] | None:
    """Resolve a query string to (district_key, district_config).

    Supports exact key, translit, Ukrainian name, and aliases.
    """
    cleaned = query.strip().lower()
    if not cleaned:
        return None

    # 1. Exact key match
    if cleaned in DISTRICT_CONFIG:
        return cleaned, DISTRICT_CONFIG[cleaned]

    # 2. Check by display_name
    for key, conf in DISTRICT_CONFIG.items():
        disp = (conf.get("display_name") or "").lower()
        if disp == cleaned:
            return key, conf

    # 3. Check by Ukrainian name and aliases
    for key, conf in DISTRICT_CONFIG.items():
        name = (conf.get("name") or "").lower()
        if name == cleaned:
            return key, conf

        aliases = [a.lower() for a in conf.get("aliases", [])]
        if cleaned in aliases:
            return key, conf

        city = (conf.get("city") or "").lower()
        if city == cleaned:
            return key, conf

    # 4. Check broadcast cities map
    for key, name in BROADCAST_CITIES.items():
        if name.lower() == cleaned:
            return key, DISTRICT_CONFIG[key]

    # 5. Fuzzy prefix / substring match if unique
    candidates = []
    for key, conf in DISTRICT_CONFIG.items():
        candidates_pool = [
            key,
            (conf.get("display_name") or "").lower(),
            (conf.get("name") or "").lower(),
            (conf.get("city") or "").lower(),
            *[a.lower() for a in conf.get("aliases", [])],
        ]
        if any(cleaned in c for c in candidates_pool if c):
            candidates.append((key, conf))

    if len(candidates) == 1:
        return candidates[0]

    return None


def get_district_status(
    district_key: str,
    redis_conn=None,
    env: str | None = None,
) -> dict[str, Any]:
    """Fetch the live status of a single district."""
    if district_key not in DISTRICT_CONFIG:
        raise ValueError(f"Unknown district key: {district_key}")

    conf = DISTRICT_CONFIG[district_key]
    oblast_key = conf.get("oblast", "")
    channels = get_channels_map(env)
    channel_id = channels.get(district_key)

    client = redis_conn or get_redis_client()

    alert_raw = client.hgetall(f"threat:alerts:city:{district_key}")
    shelling_raw = client.hgetall(f"threat:shellings:{district_key}")
    oblast_raw = client.hgetall(f"threat:alerts:{oblast_key}")
    active_districts = list(client.smembers(f"threat:alerts:active:{oblast_key}"))

    alert_status = str(alert_raw.get("status", "")).lower() in ("true", "1", "active")
    shelling_status = str(shelling_raw.get("status", "")).lower() in ("true", "1", "active")
    oblast_alert_status = str(oblast_raw.get("status", "")).lower() in ("true", "1", "active")

    return {
        "key": district_key,
        "name": conf.get("name", district_key),
        "display_name": conf.get("display_name") or conf.get("name", district_key),
        "oblast_key": oblast_key,
        "channel_id": channel_id,
        "has_channel": channel_id is not None,
        "alert": {
            "status": alert_status,
            "type": alert_raw.get(
                "type", "air_raid_alert" if alert_status else "air_raid_alert_cancelled"
            ),
            "time": alert_raw.get("time", "None"),
            "source": alert_raw.get("source", "None"),
            "updated_at": int(alert_raw.get("updated_at", 0) or 0),
        },
        "shelling": {
            "status": shelling_status,
            "time": shelling_raw.get("time", "None"),
            "source": shelling_raw.get("source", "None"),
            "updated_at": int(shelling_raw.get("updated_at", 0) or 0),
        },
        "oblast_alert": {
            "status": oblast_alert_status,
            "time": oblast_raw.get("time", "None"),
            "active_districts": active_districts,
        },
    }


def get_all_districts_statuses(
    redis_conn=None,
    filter_oblast: str | None = None,
    active_only: bool = False,
    env: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch status for all districts using pipelined Redis queries."""
    client = redis_conn or get_redis_client()
    channels = get_channels_map(env)

    target_keys = []
    for d_key, d_conf in DISTRICT_CONFIG.items():
        if filter_oblast and d_conf.get("oblast") != filter_oblast:
            continue
        target_keys.append(d_key)

    pipeline = client.pipeline()
    for d_key in target_keys:
        pipeline.hgetall(f"threat:alerts:city:{d_key}")
        pipeline.hgetall(f"threat:shellings:{d_key}")

    results = pipeline.execute()

    districts = []
    for i, d_key in enumerate(target_keys):
        alert_raw = results[i * 2] or {}
        shelling_raw = results[i * 2 + 1] or {}

        alert_status = str(alert_raw.get("status", "")).lower() in ("true", "1", "active")
        shelling_status = str(shelling_raw.get("status", "")).lower() in ("true", "1", "active")

        if active_only and not (alert_status or shelling_status):
            continue

        conf = DISTRICT_CONFIG[d_key]
        districts.append(
            {
                "key": d_key,
                "name": conf.get("name", d_key),
                "display_name": conf.get("display_name") or conf.get("name", d_key),
                "oblast_key": conf.get("oblast", ""),
                "channel_id": channels.get(d_key),
                "has_channel": d_key in channels,
                "alert": {
                    "status": alert_status,
                    "time": alert_raw.get("time", "None"),
                    "source": alert_raw.get("source", "None"),
                    "updated_at": int(alert_raw.get("updated_at", 0) or 0),
                },
                "shelling": {
                    "status": shelling_status,
                    "time": shelling_raw.get("time", "None"),
                    "source": shelling_raw.get("source", "None"),
                    "updated_at": int(shelling_raw.get("updated_at", 0) or 0),
                },
            }
        )

    return districts


def get_kyiv_timezone():
    """Resolve Europe/Kyiv timezone with robust fallback."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Kyiv")
    except Exception:
        return datetime.timezone(datetime.timedelta(hours=3))


def get_kyiv_now() -> datetime.datetime:
    """Current datetime in Europe/Kyiv timezone."""
    tz = get_kyiv_timezone()
    return datetime.datetime.now(tz)


def parse_kyiv_datetime(
    date_str: str | None = None,
    time_str: str | None = None,
) -> tuple[datetime.datetime, datetime.date, str, str]:
    """Parse date and time in Europe/Kyiv timezone.

    If date_str is omitted, defaults to today in Kyiv.
    If time_str is omitted, defaults to current time in Kyiv.
    Returns: (combined_datetime, date_obj, 'HH:MM', epoch_string).
    """
    now_kyiv = get_kyiv_now()

    # 1. Parse date
    target_date = now_kyiv.date()
    if date_str:
        clean_date = date_str.strip()
        matched = False
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                target_date = datetime.datetime.strptime(clean_date, fmt).date()
                matched = True
                break
            except ValueError:
                pass
        if not matched:
            for fmt in ("%d.%m", "%d/%m"):
                try:
                    parsed = datetime.datetime.strptime(
                        f"{clean_date}.{now_kyiv.year}", f"{fmt}.%Y"
                    )
                    target_date = parsed.date()
                    matched = True
                    break
                except ValueError:
                    pass
        if not matched:
            raise ValueError(
                f"Invalid date format: '{date_str}'. Expected 'YYYY-MM-DD' or 'DD.MM'."
            )

    # 2. Parse time
    target_time = now_kyiv.time()
    if time_str:
        clean_time = time_str.strip()
        matched = False
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                target_time = datetime.datetime.strptime(clean_time, fmt).time()
                matched = True
                break
            except ValueError:
                pass
        if not matched:
            raise ValueError(f"Invalid time format: '{time_str}'. Expected 'HH:MM'.")

    time_hh_mm = target_time.strftime("%H:%M")
    combined = datetime.datetime.combine(target_date, target_time)
    if hasattr(now_kyiv, "tzinfo") and now_kyiv.tzinfo is not None:
        combined = combined.replace(tzinfo=now_kyiv.tzinfo)

    now_epoch = str(int(combined.timestamp()))
    return combined, target_date, time_hh_mm, now_epoch


def apply_threat_change(
    district_key: str,
    alert_active: bool | None = None,
    shelling_active: bool | None = None,
    source: str | None = None,
    date_str: str | None = None,
    time_str: str | None = None,
    dry_run: bool = False,
    redis_conn=None,
    pg_conn=None,
    env: str | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    """Apply manual status change to Redis and PostgreSQL."""
    if district_key not in DISTRICT_CONFIG:
        raise ValueError(f"Unknown district key: {district_key}")

    if alert_active is None and shelling_active is None:
        raise ValueError("At least one of alert_active or shelling_active must be provided.")

    conf = DISTRICT_CONFIG[district_key]
    oblast_key = conf.get("oblast", district_key)
    channels = get_channels_map(env)
    channel_id = channels.get(district_key)

    now, target_date, current_time, now_epoch = parse_kyiv_datetime(date_str, time_str)
    operator_name = operator or os.getenv("USER") or os.getenv("USERNAME") or "operator"
    source_tag = source if source is not None else f"manual:cli:{operator_name}"

    client = redis_conn or get_redis_client()

    changes_plan: list[dict[str, Any]] = []

    if alert_active is not None:
        event_type = "air_raid_alert" if alert_active else "air_raid_alert_cancelled"
        changes_plan.append(
            {
                "component": "alert",
                "to": alert_active,
                "event_type": event_type,
                "redis_keys": [
                    f"threat:alerts:city:{district_key}",
                    f"threat:alerts:active:{oblast_key}",
                    f"threat:alerts:{oblast_key}",
                ],
            }
        )

    if shelling_active is not None:
        event_type = "threat_of_shelling" if shelling_active else "threat_of_shelling_cancelled"
        changes_plan.append(
            {
                "component": "shelling",
                "to": shelling_active,
                "event_type": event_type,
                "redis_keys": [
                    f"threat:shellings:{district_key}",
                ],
            }
        )

    result = {
        "district_key": district_key,
        "name": conf.get("name", district_key),
        "oblast_key": oblast_key,
        "channel_id": channel_id,
        "dry_run": dry_run,
        "changes": changes_plan,
        "time": current_time,
        "date": str(target_date),
        "source": source_tag,
    }

    if dry_run:
        return result

    # 1. Apply to Redis
    for change in changes_plan:
        if change["component"] == "alert":
            st_str = "true" if alert_active else "false"
            client.hset(
                f"threat:alerts:city:{district_key}",
                mapping={
                    "status": st_str,
                    "time": current_time,
                    "source": source_tag,
                    "type": change["event_type"],
                    "updated_at": now_epoch,
                },
            )

            active_key = f"threat:alerts:active:{oblast_key}"
            if alert_active:
                client.sadd(active_key, district_key)
            else:
                client.srem(active_key, district_key)

            active_count = client.scard(active_key)
            try:
                is_oblast_active = int(active_count or 0) > 0
            except (ValueError, TypeError):
                is_oblast_active = bool(active_count)

            client.hset(
                f"threat:alerts:{oblast_key}",
                mapping={
                    "status": "true" if is_oblast_active else "false",
                    "time": current_time,
                    "source": source_tag,
                    "updated_at": now_epoch,
                },
            )

            # Update channel state key
            state_key = (
                f"channel_state:{channel_id}"
                if channel_id is not None
                else f"district_state:{district_key}"
            )
            client.set(state_key, change["event_type"])

        elif change["component"] == "shelling":
            st_str = "true" if shelling_active else "false"
            client.hset(
                f"threat:shellings:{district_key}",
                mapping={
                    "status": st_str,
                    "time": current_time,
                    "source": source_tag,
                    "updated_at": now_epoch,
                },
            )

    # 2. Record to PostgreSQL alert_history
    conn = pg_conn
    owns_conn = False
    if conn is None:
        try:
            conn = get_pg_connection()
            owns_conn = True
        except Exception:
            conn = None

    if conn is not None:
        try:
            with conn.cursor() as cur:
                for change in changes_plan:
                    cur.execute(
                        """
                        INSERT INTO alert_history
                        (datetime, date, time, district_key, oblast_key, type,
                         channel_id, message_id, message_link)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            now,
                            target_date,
                            current_time,
                            district_key,
                            oblast_key,
                            change["event_type"],
                            channel_id,
                            None,
                            source_tag,
                        ),
                    )
            conn.commit()
            result["history_recorded"] = True
        except Exception as e:
            result["history_error"] = str(e)
        finally:
            if owns_conn:
                conn.close()
    else:
        result["history_recorded"] = False

    return result


def get_history(
    district_key: str | None = None,
    limit: int = 15,
    pg_conn=None,
) -> list[dict[str, Any]]:
    """Retrieve recent alert history records from PostgreSQL."""
    conn = pg_conn
    owns_conn = False
    if conn is None:
        conn = get_pg_connection()
        owns_conn = True

    try:
        with conn.cursor() as cur:
            if district_key:
                cur.execute(
                    """
                    SELECT id, datetime, date, time, district_key, oblast_key, type,
                           channel_id, message_id, message_link
                    FROM alert_history
                    WHERE district_key = %s
                    ORDER BY datetime DESC, id DESC
                    LIMIT %s
                    """,
                    (district_key, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, datetime, date, time, district_key, oblast_key, type,
                           channel_id, message_id, message_link
                    FROM alert_history
                    ORDER BY datetime DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = cur.fetchall()
            history = []
            for row in rows:
                history.append(
                    {
                        "id": row[0],
                        "datetime": row[1],
                        "date": str(row[2]),
                        "time": row[3],
                        "district_key": row[4],
                        "oblast_key": row[5],
                        "type": row[6],
                        "channel_id": row[7],
                        "message_id": row[8],
                        "message_link": row[9],
                    }
                )
            return history
    finally:
        if owns_conn:
            conn.close()


MAINTENANCE_COMPONENTS = ("all", "broadcast", "source", "map", "api")
CANONICAL_COMPONENTS = MAINTENANCE_COMPONENTS

COMPONENT_ALIASES = {
    "all": "all",
    "всі": "all",
    "усі": "all",
    "map": "map",
    "мапа": "map",
    "карта": "map",
    "api": "api",
    "апі": "api",
    "broadcast": "broadcast",
    "розсилка": "broadcast",
    "тг": "broadcast",
    "telegram": "broadcast",
    "source": "source",
    "джерело": "source",
    "потік": "source",
}

UK_COMPONENT_NAMES = {
    "all": "усі",
    "broadcast": "розсилка",
    "source": "джерело",
    "map": "мапа",
    "api": "API",
}

SCHEDULE_KEY = "system:maintenance:schedule"


def normalize_components(comps: list[str] | str | None) -> list[str]:
    """Normalize component names supporting Ukrainian and aliases."""
    if comps is None or comps == "all" or comps == ["all"]:
        return ["all"]
    if isinstance(comps, str):
        raw_items = [c.strip().lower() for c in comps.split(",") if c.strip()]
    else:
        raw_items = [str(c).strip().lower() for c in comps if str(c).strip()]

    normalized = []
    for item in raw_items:
        canon = COMPONENT_ALIASES.get(item)
        if not canon:
            raise ValueError(
                f"Unknown component: '{item}'. Valid components: {', '.join(CANONICAL_COMPONENTS)}"
            )
        if canon not in normalized:
            normalized.append(canon)

    return normalized or ["all"]


def format_components_uk(comps: list[str]) -> str:
    """Format components into Ukrainian string, e.g. 'мапа, API'."""
    if "all" in comps:
        return "усі"
    return ", ".join(UK_COMPONENT_NAMES.get(c, c) for c in comps)


def parse_duration(for_str: str) -> int:
    """Parse duration string like '90m', '2h', '1h30m', '1.5h' into seconds."""
    s = for_str.strip().lower()
    if not s:
        return 3600

    if s.isdigit():
        return int(s) * 60

    import re

    total_seconds = 0
    h_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|год|hours?|hour)", s)
    if h_match:
        total_seconds += int(float(h_match.group(1)) * 3600)

    m_match = re.search(r"(\d+)\s*(?:m|хв|min|minutes?|minute)", s)
    if m_match:
        total_seconds += int(m_match.group(1)) * 60

    if total_seconds <= 0:
        raise ValueError(
            f"Invalid duration format: '{for_str}'. Examples: '90m', '2h', '1h30m'."
        )

    return total_seconds


def parse_maintenance_window(
    from_str: str = "now",
    for_str: str = "60m",
) -> tuple[datetime.datetime, datetime.datetime, int, int]:
    """Parse maintenance window start and end datetime in Europe/Kyiv timezone.

    Returns (start_dt, end_dt, start_epoch, end_epoch).
    """
    now_kyiv = get_kyiv_now()
    clean_from = (from_str or "now").strip()
    clean_lower = clean_from.lower()

    if clean_lower in ("now", "зараз"):
        start_dt = now_kyiv
    else:
        matched = False
        for fmt in ("%d.%m %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
            try:
                if fmt == "%d.%m %H:%M":
                    parsed = datetime.datetime.strptime(
                        f"{clean_from} {now_kyiv.year}", f"{fmt} %Y"
                    )
                else:
                    parsed = datetime.datetime.strptime(clean_from, fmt)
                start_dt = parsed.replace(tzinfo=now_kyiv.tzinfo)
                matched = True
                break
            except ValueError:
                pass

        if not matched:
            for fmt in ("%H:%M", "%H:%M:%S"):
                try:
                    t_val = datetime.datetime.strptime(clean_from, fmt).time()
                    start_dt = datetime.datetime.combine(now_kyiv.date(), t_val).replace(
                        tzinfo=now_kyiv.tzinfo
                    )
                    matched = True
                    break
                except ValueError:
                    pass

        if not matched:
            raise ValueError(
                f"Invalid --from time format: '{from_str}'. Expected 'now', 'HH:MM', or 'DD.MM HH:MM'."
            )

    duration_sec = parse_duration(for_str)
    end_dt = start_dt + datetime.timedelta(seconds=duration_sec)
    start_epoch = int(start_dt.timestamp())
    end_epoch = int(end_dt.timestamp())
    return start_dt, end_dt, start_epoch, end_epoch


def format_window_time(start_dt: datetime.datetime, end_dt: datetime.datetime) -> str:
    """Format time range: '02:00–03:30' or '05.09 23:00–06.09 01:00'."""
    if start_dt.date() == end_dt.date():
        return f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"
    return f"{start_dt.strftime('%d.%m %H:%M')}–{end_dt.strftime('%d.%m %H:%M')}"


def format_window_status(
    start_epoch: int,
    end_epoch: int,
    completed: bool = False,
    now_epoch: int | None = None,
    start_dt: datetime.datetime | None = None,
) -> tuple[str, str, str]:
    """Determine status badge, state label, and relative remaining string.

    Returns (status_code, status_label, remaining_str)
    e.g. ('active', 'зараз', 'ще 47 хв')
         ('scheduled', '06.09', 'через 10 год')
         ('completed', 'завершено', '')
    """
    now = now_epoch if now_epoch is not None else int(get_kyiv_now().timestamp())

    if completed:
        return "completed", "завершено", ""

    if start_epoch <= now <= end_epoch:
        rem_sec = max(0, end_epoch - now)
        rem_min = rem_sec // 60
        if rem_min < 1:
            rem_str = "ще <1 хв"
        elif rem_min < 60:
            rem_str = f"ще {rem_min} хв"
        else:
            h = rem_min // 60
            m = rem_min % 60
            rem_str = f"ще {h} год {m} хв" if m > 0 else f"ще {h} год"
        return "active", "зараз", rem_str

    if now < start_epoch:
        wait_sec = start_epoch - now
        wait_min = wait_sec // 60
        if wait_min < 60:
            wait_str = f"через {wait_min} хв"
        else:
            h = wait_min // 60
            m = wait_min % 60
            if h < 24:
                wait_str = f"через {h} год" if m == 0 else f"через {h} год {m} хв"
            else:
                d = h // 24
                wait_str = f"через {d} дн."

        date_lbl = start_dt.strftime("%d.%m") if start_dt else "заплановано"
        return "scheduled", date_lbl, wait_str

    return "completed", "завершено", ""


def push_maintenance_to_kv(maintenance_payload: dict[str, Any]) -> bool:
    """Push maintenance state to Cloudflare KV."""
    if not (CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_TELEMETRY_NAMESPACE_ID and CLOUDFLARE_API_TOKEN):
        return False

    import json

    import requests

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
        f"/storage/kv/namespaces/{CLOUDFLARE_TELEMETRY_NAMESPACE_ID}/values/maintenance"
    )
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        res = requests.put(url, data=json.dumps(maintenance_payload), headers=headers, timeout=5)
        res.raise_for_status()
        return True
    except Exception:
        return False


def _load_schedule(client) -> list[dict[str, Any]]:
    import json

    raw = client.get(SCHEDULE_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_schedule(client, schedule: list[dict[str, Any]]) -> None:
    import json

    client.set(SCHEDULE_KEY, json.dumps(schedule))


def sync_maintenance_state(redis_conn=None) -> dict[str, Any]:
    """Sync currently active window from schedule to system:maintenance and Cloudflare KV."""
    client = redis_conn or get_redis_client()
    import json

    now = int(get_kyiv_now().timestamp())
    schedule = _load_schedule(client)

    active_win = None
    for w in schedule:
        if not w.get("completed") and w["start_epoch"] <= now <= w["end_epoch"]:
            active_win = w
            break

    if active_win:
        note_val = active_win.get("note") or "Тривають планові технічні роботи."
        state_data = {
            "active": "true",
            "id": active_win["id"],
            "components": json.dumps(active_win["components"]),
            "headline": "Планові роботи",
            "subtitle": note_val,
            "start_iso": active_win["start_iso"],
            "end_iso": active_win["end_iso"],
            "updated_at": str(now),
            "operator": active_win.get("operator", ""),
        }
        cf_payload = {
            "active": True,
            "id": active_win["id"],
            "components": active_win["components"],
            "headline": "Планові роботи",
            "subtitle": note_val,
            "start_iso": active_win["start_iso"],
            "end_iso": active_win["end_iso"],
            "updated_at": get_kyiv_now().isoformat(),
            "operator": active_win.get("operator", ""),
        }
    else:
        state_data = {
            "active": "false",
            "id": "",
            "components": json.dumps(["all"]),
            "headline": "Планові роботи",
            "subtitle": "Тривають планові технічні роботи.",
            "updated_at": str(now),
            "operator": "",
        }
        cf_payload = {
            "active": False,
            "components": ["all"],
            "headline": "Планові роботи",
            "subtitle": "Тривають планові технічні роботи.",
            "updated_at": get_kyiv_now().isoformat(),
            "operator": "",
        }

    client.hset("system:maintenance", mapping=state_data)
    push_maintenance_to_kv(cf_payload)
    return active_win or {"active": False}


def add_maintenance_window(
    components: list[str] | str,
    from_str: str = "now",
    for_str: str = "60m",
    note: str | None = None,
    redis_conn=None,
    operator: str | None = None,
    sync_cf: bool = True,
) -> dict[str, Any]:
    """Add a new scheduled maintenance window."""
    client = redis_conn or get_redis_client()
    now_kyiv = get_kyiv_now()
    comps_list = normalize_components(components)
    start_dt, end_dt, start_epoch, end_epoch = parse_maintenance_window(from_str, for_str)
    operator_name = operator or os.getenv("USER") or os.getenv("USERNAME") or "operator"
    note_val = note.strip() if note and note.strip() else "Тривають планові технічні роботи."

    import uuid

    window_id = f"mnt_{start_epoch}_{uuid.uuid4().hex[:6]}"

    window = {
        "id": window_id,
        "components": comps_list,
        "note": note_val,
        "start_epoch": start_epoch,
        "end_epoch": end_epoch,
        "start_iso": start_dt.isoformat(),
        "end_iso": end_dt.isoformat(),
        "time_text": format_window_time(start_dt, end_dt),
        "created_at": int(now_kyiv.timestamp()),
        "operator": operator_name,
        "completed": False,
    }

    schedule = _load_schedule(client)
    schedule.append(window)
    _save_schedule(client, schedule)

    sync_maintenance_state(client)
    return window


def list_maintenance_windows(
    include_completed: bool = False,
    redis_conn=None,
) -> list[dict[str, Any]]:
    """List scheduled maintenance windows."""
    client = redis_conn or get_redis_client()
    schedule = _load_schedule(client)
    now = int(get_kyiv_now().timestamp())
    tz = get_kyiv_timezone()

    results = []
    for w in sorted(schedule, key=lambda x: x["start_epoch"]):
        is_completed = bool(w.get("completed"))
        if not include_completed and is_completed:
            continue

        try:
            start_dt = datetime.datetime.fromtimestamp(w["start_epoch"], tz=tz)
            end_dt = datetime.datetime.fromtimestamp(w["end_epoch"], tz=tz)
        except Exception:
            start_dt = None
            end_dt = None

        status_code, status_label, remaining_str = format_window_status(
            w["start_epoch"],
            w["end_epoch"],
            completed=is_completed,
            now_epoch=now,
            start_dt=start_dt,
        )

        time_text = w.get("time_text") or (
            format_window_time(start_dt, end_dt) if start_dt and end_dt else ""
        )

        item = dict(w)
        item["status_code"] = status_code
        item["status_label"] = status_label
        item["remaining_str"] = remaining_str
        item["time_text"] = time_text
        item["components_uk"] = format_components_uk(w["components"])
        results.append(item)

    return results


def complete_maintenance_window(
    window_id: str | None = None,
    redis_conn=None,
) -> dict[str, Any] | None:
    """Complete / early-finish an active or scheduled maintenance window."""
    client = redis_conn or get_redis_client()
    now = int(get_kyiv_now().timestamp())
    schedule = _load_schedule(client)

    target_win = None
    if window_id:
        for w in schedule:
            if w["id"] == window_id:
                target_win = w
                break
    else:
        # First, search for currently active window
        for w in schedule:
            if not w.get("completed") and w["start_epoch"] <= now <= w["end_epoch"]:
                target_win = w
                break
        # If no currently active, find nearest upcoming
        if not target_win:
            for w in sorted(schedule, key=lambda x: x["start_epoch"]):
                if not w.get("completed") and w["start_epoch"] > now:
                    target_win = w
                    break

    if not target_win:
        set_maintenance(active=False, redis_conn=client)
        return None

    target_win["completed"] = True
    target_win["completed_at"] = now
    _save_schedule(client, schedule)

    sync_maintenance_state(client)
    return target_win


def set_maintenance(
    active: bool,
    components: list[str] | str | None = None,
    message: str | None = None,
    redis_conn=None,
    operator: str | None = None,
    sync_cf: bool = True,
) -> dict[str, Any]:
    """Apply planned works (maintenance mode) state to Redis and Cloudflare KV."""
    client = redis_conn or get_redis_client()
    now_kyiv = get_kyiv_now()
    now_epoch = str(int(now_kyiv.timestamp()))
    operator_name = operator or os.getenv("USER") or os.getenv("USERNAME") or "operator"

    comps_list = normalize_components(components)
    default_msg = "Тривають планові технічні роботи."
    subtitle_msg = message.strip() if message and message.strip() else default_msg

    import json

    redis_data = {
        "active": "true" if active else "false",
        "components": json.dumps(comps_list),
        "headline": "Планові роботи",
        "subtitle": subtitle_msg,
        "updated_at": now_epoch,
        "operator": operator_name,
    }
    client.hset("system:maintenance", mapping=redis_data)

    cf_payload = {
        "active": active,
        "components": comps_list,
        "headline": "Планові роботи",
        "subtitle": subtitle_msg,
        "updated_at": now_kyiv.isoformat(),
        "operator": operator_name,
    }

    cf_synced = False
    if sync_cf:
        cf_synced = push_maintenance_to_kv(cf_payload)

    if not active:
        # Also mark any active window in schedule as completed
        schedule = _load_schedule(client)
        now_int = int(now_epoch)
        changed = False
        for w in schedule:
            if not w.get("completed") and w["start_epoch"] <= now_int <= w["end_epoch"]:
                w["completed"] = True
                w["completed_at"] = now_int
                changed = True
        if changed:
            _save_schedule(client, schedule)

    return {
        "active": active,
        "components": comps_list,
        "headline": "Планові роботи",
        "subtitle": subtitle_msg,
        "updated_at": now_epoch,
        "operator": operator_name,
        "cf_synced": cf_synced,
    }


def get_maintenance(redis_conn=None) -> dict[str, Any]:
    """Retrieve current planned works (maintenance mode) state from Redis."""
    client = redis_conn or get_redis_client()
    import json

    raw = client.hgetall("system:maintenance")
    if not raw:
        return {
            "active": False,
            "components": ["all"],
            "headline": "Планові роботи",
            "subtitle": "Тривають планові технічні роботи.",
            "updated_at": 0,
            "operator": "",
        }

    is_active = str(raw.get("active", "")).lower() in ("true", "1", "active")
    comps_raw = raw.get("components", '["all"]')
    try:
        comps = json.loads(comps_raw) if comps_raw else ["all"]
        if not isinstance(comps, list):
            comps = [str(comps)]
    except Exception:
        comps = [comps_raw]

    try:
        updated_epoch = int(raw.get("updated_at", 0) or 0)
    except (ValueError, TypeError):
        updated_epoch = 0

    return {
        "active": is_active,
        "components": comps,
        "headline": raw.get("headline", "Планові роботи"),
        "subtitle": raw.get("subtitle", "Тривають планові технічні роботи."),
        "updated_at": updated_epoch,
        "operator": raw.get("operator", ""),
    }


