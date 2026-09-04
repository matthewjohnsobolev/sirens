"""
Database access and state management for Sirens.
Handles PostgreSQL schema/storage and Redis threat state caching.
"""

import datetime
import logging
import time
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo

import psycopg2
import redis

from config import DATABASE_URL, REDIS_URL
from domain import (
    DISTRICT_CONFIG,
    DISTRICT_NAMES_EN,
    DISTRICTS_BY_OBLAST,
    REGIONS,
    real_channels,
    test_channels,
)

log = logging.getLogger(__name__)


def get_region_by_channel_id(channel_id: int) -> str | None:
    for name, cid in real_channels.items():
        if cid == channel_id:
            return name
    for name, cid in test_channels.items():
        if cid == channel_id:
            return name
    return None


redis_client = redis.from_url(REDIS_URL, decode_responses=True)
DEFAULT_SOURCE = "telegram"


def get_pg_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DATABASE_URL)


SCHEMA_LOCK_KEY = 8110921


def ensure_pg_tables() -> None:
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_history (
                        id SERIAL PRIMARY KEY,
                        datetime TIMESTAMP NOT NULL,
                        date DATE NOT NULL,
                        time TEXT NOT NULL,
                        district_key TEXT,
                        oblast_key TEXT,
                        type TEXT NOT NULL,
                        channel_id BIGINT,
                        message_id BIGINT,
                        message_link TEXT
                    )
                """)
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'district_key'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN district_key TEXT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'oblast_key'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN oblast_key TEXT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'time'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN time TEXT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'date'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN date DATE;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'datetime'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN datetime TIMESTAMP;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'type'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN type TEXT;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'oblast'
                        ) THEN
                            ALTER TABLE alert_history DROP COLUMN oblast;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'channel_id'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN channel_id BIGINT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'message_id'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN message_id BIGINT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'message_link'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN message_link TEXT;
                        END IF;
                    END $$;
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS alert_history_district_dt_idx ON alert_history (district_key, datetime DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS alert_history_oblast_dt_idx ON alert_history (oblast_key, datetime DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS alert_history_datetime_idx ON alert_history (datetime DESC)"
                )
                cur.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'channel_stats'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.tables
                            WHERE table_name = 'subscribers'
                        ) THEN
                            ALTER TABLE channel_stats RENAME TO subscribers;
                        END IF;
                    END $$;
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscribers (
                        id SERIAL PRIMARY KEY,
                        channel_key TEXT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        subscribers INTEGER NOT NULL,
                        date DATE NOT NULL,
                        time TIMESTAMP NOT NULL,
                        UNIQUE (channel_key, time)
                    )
                """)
                cur.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'participants'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'subscribers'
                        ) THEN
                            ALTER TABLE subscribers RENAME COLUMN participants TO subscribers;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'collected_at'
                        ) AND NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'time'
                        ) THEN
                            ALTER TABLE subscribers RENAME COLUMN collected_at TO time;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'time'
                        ) THEN
                            ALTER TABLE subscribers ADD COLUMN time TIMESTAMP;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'channel_key'
                        ) THEN
                            ALTER TABLE subscribers ADD COLUMN channel_key TEXT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'channel_id'
                        ) THEN
                            ALTER TABLE subscribers ADD COLUMN channel_id BIGINT;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'subscribers'
                        ) THEN
                            ALTER TABLE subscribers ADD COLUMN subscribers INTEGER;
                        END IF;
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscribers' AND column_name = 'date'
                        ) THEN
                            ALTER TABLE subscribers ADD COLUMN date DATE;
                        END IF;
                        ALTER TABLE subscribers DROP CONSTRAINT IF EXISTS subscribers_channel_key_date_key;
                        ALTER TABLE subscribers DROP CONSTRAINT IF EXISTS subscribers_channel_key_collected_at_key;
                        ALTER TABLE subscribers DROP CONSTRAINT IF EXISTS channel_stats_channel_key_date_key;
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'subscribers_channel_key_time_key'
                              AND conrelid = 'subscribers'::regclass
                        ) THEN
                            ALTER TABLE subscribers ADD CONSTRAINT subscribers_channel_key_time_key UNIQUE (channel_key, time);
                        END IF;
                    END $$;
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS subscribers_date_idx ON subscribers (date)")
                cur.execute("CREATE INDEX IF NOT EXISTS subscribers_time_idx ON subscribers (time)")
            conn.commit()
    except Exception:
        log.exception("Failed to ensure the database schema exists")
        raise

    log.info("PostgreSQL schema ready")


THREAT_TABLES = {"alerts", "shellings"}


def _validate_table(table_name: str) -> None:
    if table_name not in THREAT_TABLES:
        raise ValueError(f"Invalid threat table: {table_name}")


def _normalize_status(val: Any) -> bool:
    if val is None:
        return False
    return str(val).lower() in ["true", "1", "active"]


def _get_threat_field(table_name: str, target: str, field_name: str) -> bool | str:
    _validate_table(table_name)
    key = f"threat:{table_name}:{target}"
    val = redis_client.hget(key, field_name)
    if field_name == "status":
        return _normalize_status(val)
    return str(val) if val is not None else "None"


def get_threat_status(table_name: str, target: str) -> bool:
    return bool(_get_threat_field(table_name, target, "status"))


def get_threat_time(table_name: str, target: str) -> str:
    return str(_get_threat_field(table_name, target, "time"))


def get_threat_source(table_name: str, target: str) -> str:
    return str(_get_threat_field(table_name, target, "source"))


def update_threat_status(
    table_name: str,
    target: str,
    status: bool | int | str = True,
    time_val: str | None = None,
    source_val: str | None = None,
) -> None:
    _validate_table(table_name)
    key = f"threat:{table_name}:{target}"
    if time_val is None:
        time_val = datetime.datetime.now().strftime("%H:%M")

    st_bool = _normalize_status(status)
    updates = {
        "status": "true" if st_bool else "false",
        "time": time_val,
        "updated_at": str(int(time.time())),
    }
    if source_val is not None:
        updates["source"] = source_val

    redis_client.hset(key, mapping=updates)


def reset_threat_status(table_name: str, target: str) -> None:
    _validate_table(table_name)
    key = f"threat:{table_name}:{target}"
    redis_client.hset(
        key,
        mapping={
            "status": "false",
            "time": "None",
            "source": "None",
            "updated_at": str(int(time.time())),
        },
    )


update_shelling_status = partial(update_threat_status, "shellings", status=True)
reset_shelling_status = partial(reset_threat_status, "shellings")

get_alert_status = partial(get_threat_status, "alerts")
get_shelling_status = partial(get_threat_status, "shellings")

get_alert_time = partial(get_threat_time, "alerts")
get_shelling_time = partial(get_threat_time, "shellings")

get_alert_source = partial(get_threat_source, "alerts")
get_shelling_source = partial(get_threat_source, "shellings")


def update_shelling_source(target: str, link: str) -> None:
    update_threat_status("shellings", target, source_val=link)


def update_alert_source(channel_id: int, link: str) -> None:
    district_key = get_region_by_channel_id(channel_id)
    if district_key and district_key in DISTRICT_CONFIG:
        oblast_key = DISTRICT_CONFIG[district_key]["oblast"]
        redis_client.hset(f"threat:alerts:{oblast_key}", "source", link)
        redis_client.hset(f"threat:alerts:city:{district_key}", "source", link)


async def update_alert_status(
    channel_id: int,
    status: str,
    message_id: int | None = None,
    message_link: str | None = None,
) -> None:
    district_key = get_region_by_channel_id(channel_id)
    if not district_key or district_key not in DISTRICT_CONFIG:
        return

    oblast_key = DISTRICT_CONFIG[district_key]["oblast"]

    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M")
    now_epoch = str(int(time.time()))
    source = message_link or DEFAULT_SOURCE

    event_type = None
    is_active: bool | None = None
    if status in ("Повітряна тривога", "air_raid_alert"):
        is_active = True
        event_type = "air_raid_alert"
    elif status in ("Відбій повітряної тривоги", "air_raid_alert_cancelled"):
        is_active = False
        event_type = "air_raid_alert_cancelled"
    elif status in ("Загроза артилерійського обстрілу", "threat_of_shelling"):
        is_active = True
        event_type = "threat_of_shelling"
    elif status in ("Відбій загрози артобстрілу", "threat_of_shelling_cancelled"):
        is_active = False
        event_type = "threat_of_shelling_cancelled"

    if "shelling" in (event_type or ""):
        if is_active is not None:
            redis_client.hset(
                f"threat:shellings:{district_key}",
                mapping={
                    "status": "true" if is_active else "false",
                    "time": current_time,
                    "source": source,
                    "updated_at": now_epoch,
                },
            )
    else:
        city_key = f"threat:alerts:city:{district_key}"
        updates = {"time": current_time, "updated_at": now_epoch}
        if is_active is not None:
            updates["status"] = "true" if is_active else "false"
            updates["source"] = source
            if event_type:
                updates["type"] = event_type

        redis_client.hset(city_key, mapping=updates)

        if is_active is not None:
            active_set_key = f"threat:alerts:active:{oblast_key}"
            if is_active:
                redis_client.sadd(active_set_key, district_key)
            else:
                redis_client.srem(active_set_key, district_key)

            active_count = redis_client.scard(active_set_key)
            try:
                is_active_oblast = int(active_count or 0) > 0
            except (ValueError, TypeError):
                is_active_oblast = bool(active_count)

            redis_client.hset(
                f"threat:alerts:{oblast_key}",
                mapping={
                    "status": "true" if is_active_oblast else "false",
                    "time": current_time,
                    "source": source,
                    "updated_at": now_epoch,
                },
            )

    if event_type:
        try:
            with get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO alert_history
                           (datetime, date, time, district_key, oblast_key, type,
                            channel_id, message_id, message_link)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            now,
                            now.date(),
                            current_time,
                            district_key,
                            oblast_key,
                            event_type,
                            channel_id,
                            message_id,
                            message_link,
                        ),
                    )
                conn.commit()
        except Exception:
            log.exception("Failed to record alert %s for %s in history", event_type, district_key)
            raise


def rehydrate_state_from_db() -> None:
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT ON (district_key)
                        COALESCE(district_key, '') as district_key,
                        COALESCE(oblast_key, '') as oblast_key,
                        type,
                        time,
                        datetime,
                        message_link
                    FROM alert_history
                    WHERE district_key IS NOT NULL
                    ORDER BY district_key, datetime DESC
                """)
                rows = cur.fetchall()
    except Exception:
        log.exception("Failed to query alert_history for rehydration")
        raise

    for _d_name, conf in DISTRICT_CONFIG.items():
        o_name = conf["oblast"]
        redis_client.delete(f"threat:alerts:active:{o_name}")

    pipeline = redis_client.pipeline()
    for row in rows:
        d_key, o_key, alert_type, alert_time, dt, message_link = row
        source = message_link or DEFAULT_SOURCE
        if not d_key and o_key:
            d_key = o_key
        if not o_key and d_key in DISTRICT_CONFIG:
            o_key = DISTRICT_CONFIG[d_key]["oblast"]

        if "shelling" in str(alert_type).lower():
            is_active = str(alert_type).lower() in ("threat_of_shelling", "1", "true")
            st_str = "true" if is_active else "false"
            if d_key:
                dt_epoch = (
                    str(int(dt.timestamp()))
                    if (dt and hasattr(dt, "timestamp"))
                    else str(int(time.time()))
                )
                pipeline.hset(
                    f"threat:shellings:{d_key}",
                    mapping={
                        "status": st_str,
                        "time": alert_time or (dt.strftime("%H:%M") if dt else "None"),
                        "source": source,
                        "updated_at": dt_epoch,
                    },
                )
        else:
            is_active = str(alert_type).lower() in ("air_raid_alert", "start", "1", "true")
            st_str = "true" if is_active else "false"

            if d_key:
                dt_epoch = (
                    str(int(dt.timestamp()))
                    if (dt and hasattr(dt, "timestamp"))
                    else str(int(time.time()))
                )
                pipeline.hset(
                    f"threat:alerts:city:{d_key}",
                    mapping={
                        "status": st_str,
                        "time": alert_time or (dt.strftime("%H:%M") if dt else "None"),
                        "source": source,
                        "type": alert_type
                        or ("air_raid_alert" if is_active else "air_raid_alert_cancelled"),
                        "updated_at": dt_epoch,
                    },
                )
                if is_active and o_key:
                    pipeline.sadd(f"threat:alerts:active:{o_key}", d_key)

    pipeline.set("system:state_initialized", "true")
    pipeline.execute()
    log.info("Redis state rehydrated successfully from PostgreSQL (%d records)", len(rows))


KYIV_TZ = ZoneInfo("Europe/Kyiv")

# Internal shape, as read out of Redis. `updated_at` is the epoch the record was
# written at and the only clock worth trusting: the "HH:MM" string stored next
# to it is the same instant with the date and the zone thrown away. The public
# shape below keeps the epoch and spends it on a single ISO-8601 `time`, so the
# response no longer carries one moment twice and no longer asks the reader to
# guess which zone a bare "14:23" was written in.
IDLE_THREAT: dict[str, Any] = {
    "status": False,
    "source": None,
    "updated_at": 0,
}


def _public_threat(entry: dict[str, Any]) -> dict[str, Any]:
    updated_at = entry.get("updated_at") or 0
    source = entry.get("source")
    public: dict[str, Any] = {
        "status": bool(entry.get("status")),
        "time": (
            datetime.datetime.fromtimestamp(updated_at, KYIV_TZ).isoformat() if updated_at else None
        ),
        "source": source if source and source != "None" else None,
    }
    if "type" in entry:
        public["type"] = entry["type"]
    return public


def _aggregate_shelling(districts: dict[str, Any]) -> dict[str, Any]:
    active = [d for d in districts.values() if d.get("status")]
    if not active:
        return IDLE_THREAT.copy()
    return max(active, key=lambda s: s.get("updated_at", 0)).copy()


def get_all_threats_data() -> dict[str, Any]:
    # Alerts are the only threat held at oblast level. Shelling is per district
    # and an oblast's is the latest of theirs, so `threat:shellings:<oblast>`
    # was read 27 times per request and never looked at.
    # The regions and their names come from one registry in the domain layer;
    # this endpoint used to hardcode the id list and ship no names at all.
    oblasts = list(REGIONS)

    districts = list(DISTRICT_CONFIG.keys())

    keys_order = []

    try:
        pipeline = redis_client.pipeline()

        for oblast in oblasts:
            pipeline.hgetall(f"threat:alerts:{oblast}")
            keys_order.append(("alerts", oblast))

        for district in districts:
            pipeline.hgetall(f"threat:alerts:city:{district}")
            keys_order.append(("city_alerts", district))

        for district in districts:
            pipeline.hgetall(f"threat:shellings:{district}")
            keys_order.append(("city_shellings", district))

        for oblast in oblasts:
            pipeline.smembers(f"threat:alerts:active:{oblast}")
            keys_order.append(("active_districts", oblast))

        results = pipeline.execute()
    except Exception:
        log.exception("Failed to read threat data from Redis; /api cannot be served")
        raise

    raw_data: dict[str, dict[str, Any]] = {
        "alerts": {},
        "city_alerts": {},
        "city_shellings": {},
        "active_districts": {},
    }

    for (category, target), data in zip(keys_order, results, strict=False):
        if category == "active_districts":
            raw_data["active_districts"][target] = list(data) if data else []
        elif not data:
            entry = IDLE_THREAT.copy()
            if category == "city_alerts":
                entry["type"] = None
            raw_data[category][target] = entry
        else:
            raw_status = data.get("status", False)
            try:
                updated_at_val = int(data.get("updated_at", 0))
            except (ValueError, TypeError):
                updated_at_val = 0

            entry = {
                "status": _normalize_status(raw_status),
                "source": data.get("source"),
                "updated_at": updated_at_val,
            }
            if category == "city_alerts":
                alert_type = data.get("type", "")
                if alert_type in ("threat_of_shelling", "threat_of_shelling_cancelled"):
                    entry["status"] = False
                    entry["type"] = alert_type
                else:
                    entry["type"] = alert_type or (
                        "air_raid_alert" if entry["status"] else "air_raid_alert_cancelled"
                    )
            raw_data[category][target] = entry

    result: dict[str, Any] = {}

    def build_oblast_entry(oblast: str) -> dict[str, Any]:
        tracked = DISTRICTS_BY_OBLAST.get(oblast, [])
        active = [d for d in raw_data["active_districts"].get(oblast, []) if d in tracked]

        # `status` and `coverage` are one verdict, so they are read off one
        # count. The stored status used to be trusted on its own, and
        # rehydration never rewrites the oblast hash: an oblast whose alerts
        # were all cancelled while the service was down came back reporting
        # status true against coverage "none".
        oblast_alert = raw_data["alerts"].get(oblast, IDLE_THREAT).copy()
        oblast_alert["status"] = bool(active)
        if active:
            oblast_alert["coverage"] = "full" if len(active) >= len(tracked) else "partial"
        else:
            oblast_alert["coverage"] = "none"

        # The district ids behind `coverage` are not listed separately: the
        # keys of `districts` are the tracked set, and the active subset is
        # the ones whose own alert is up.
        shellings = {d: raw_data["city_shellings"].get(d, IDLE_THREAT) for d in tracked}
        districts_map = {
            d: {
                "name": DISTRICT_CONFIG[d]["name"],
                "name_en": DISTRICT_NAMES_EN[d],
                "alert": _public_threat(raw_data["city_alerts"].get(d, IDLE_THREAT)),
                "shelling": _public_threat(shellings[d]),
            }
            for d in tracked
        }

        name, name_en = REGIONS[oblast]
        return {
            "name": name,
            "name_en": name_en,
            "alert": _public_threat(oblast_alert) | {"coverage": oblast_alert["coverage"]},
            "shelling": _public_threat(_aggregate_shelling(shellings)),
            "districts": districts_map,
        }

    for o in oblasts:
        result[o] = build_oblast_entry(o)

    return result
