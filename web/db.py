"""PostgreSQL schema and Redis threat-state access."""

import logging
import time
from typing import Any

import psycopg2
import redis

from config import DATABASE_URL, REDIS_URL
from domain import DISTRICT_CONFIG, DISTRICTS_BY_OBLAST

log = logging.getLogger(__name__)

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


def _normalize_status(val: Any) -> bool:
    if val is None:
        return False
    return str(val).lower() in ["true", "1", "active"]


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


DEFAULT_THREAT: dict[str, Any] = {
    "status": False,
    "time": "None",
    "source": "None",
    "updated_at": 0,
}


def _aggregate_shelling(districts: dict[str, Any]) -> dict[str, Any]:
    active_shellings = [
        d["shelling"]
        for d in districts.values()
        if d.get("shelling") and d["shelling"].get("status")
    ]
    if not active_shellings:
        return DEFAULT_THREAT.copy()

    latest = max(active_shellings, key=lambda s: s.get("updated_at", 0))
    return {
        "status": True,
        "time": latest.get("time", "None"),
        "source": latest.get("source", "None"),
        "updated_at": latest.get("updated_at", 0),
    }


def get_all_threats_data() -> dict[str, Any]:
    tables = ["alerts", "explosions", "shellings"]
    oblasts = [
        "cherkasy_oblast",
        "chernihiv_oblast",
        "chernivtsi_oblast",
        "crimea",
        "dnipropetrovsk_oblast",
        "donetsk_oblast",
        "ivanofrankivsk_oblast",
        "kharkiv_oblast",
        "kherson_oblast",
        "khmelnytskyi_oblast",
        "kirovohrad_oblast",
        "kyiv",
        "kyiv_oblast",
        "luhansk_oblast",
        "lviv_oblast",
        "mykolaiv_oblast",
        "odesa_oblast",
        "poltava_oblast",
        "rivne_oblast",
        "sevastopol",
        "sumy_oblast",
        "ternopil_oblast",
        "vinnytsia_oblast",
        "volyn_oblast",
        "zakarpattia_oblast",
        "zaporizhzhia_oblast",
        "zhytomyr_oblast",
    ]

    districts = list(DISTRICT_CONFIG.keys())

    keys_order = []

    try:
        pipeline = redis_client.pipeline()

        for table in tables:
            for oblast in oblasts:
                key = f"threat:{table}:{oblast}"
                pipeline.hgetall(key)
                keys_order.append((table, oblast))

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
        "explosions": {},
        "shellings": {},
        "city_alerts": {},
        "city_shellings": {},
        "active_districts": {},
    }

    for (category, target), data in zip(keys_order, results, strict=False):
        if category == "active_districts":
            raw_data["active_districts"][target] = list(data) if data else []
        elif not data:
            entry = DEFAULT_THREAT.copy()
            if category == "city_alerts":
                entry["type"] = "None"
            raw_data[category][target] = entry
        else:
            raw_status = data.get("status", False)
            try:
                updated_at_val = int(data.get("updated_at", 0))
            except (ValueError, TypeError):
                updated_at_val = 0

            entry = {
                "status": _normalize_status(raw_status),
                "time": data.get("time", "None"),
                "source": data.get("source", "None"),
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

        oblast_alert = raw_data["alerts"].get(oblast, DEFAULT_THREAT).copy()
        oblast_alert["active_districts"] = active
        oblast_alert["tracked_districts"] = tracked
        if active:
            oblast_alert["status"] = True
            oblast_alert["coverage"] = "full" if len(active) >= len(tracked) else "partial"
        else:
            oblast_alert["coverage"] = "none"

        districts_map = {
            d: {
                "name": DISTRICT_CONFIG[d]["name"],
                "alert": raw_data["city_alerts"].get(d, DEFAULT_THREAT),
                "shelling": raw_data["city_shellings"].get(d, DEFAULT_THREAT),
            }
            for d in tracked
        }

        return {
            "alert": oblast_alert,
            "explosion": raw_data["explosions"].get(oblast, DEFAULT_THREAT),
            "shelling": _aggregate_shelling(districts_map),
            "districts": districts_map,
        }

    for o in oblasts:
        result[o] = build_oblast_entry(o)

    for city, parent_oblast in [
        ("nikopol", "dnipropetrovsk_oblast"),
        ("kherson", "kherson_oblast"),
    ]:
        entry = build_oblast_entry(parent_oblast)
        entry["shelling"] = raw_data["city_shellings"].get(city, DEFAULT_THREAT)
        result[city] = entry

    return result
