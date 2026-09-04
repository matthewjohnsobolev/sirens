"""
State manager for Sirens CLI (sirens-ctl).
Handles querying and mutating Redis live state and PostgreSQL alert history.
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from config import APP_ENV, DATABASE_URL, REDIS_URL
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


def find_districts_matching(query: str) -> list[tuple[str, dict[str, Any]]]:
    """Find all matching districts for suggestions."""
    cleaned = query.strip().lower()
    if not cleaned:
        return list(DISTRICT_CONFIG.items())

    results = []
    for key, conf in DISTRICT_CONFIG.items():
        pool = [
            key,
            (conf.get("display_name") or "").lower(),
            (conf.get("name") or "").lower(),
            (conf.get("city") or "").lower(),
            *[a.lower() for a in conf.get("aliases", [])],
        ]
        if any(cleaned in item for item in pool if item):
            results.append((key, conf))
    return results


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
