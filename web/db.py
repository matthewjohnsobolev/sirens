"""
Database access and state management for Sirens.
Handles PostgreSQL schema/storage and Redis threat state caching.
"""

import datetime
import logging
import time
from functools import partial
from typing import Any

import psycopg2
import redis

from config import DATABASE_URL, REDIS_URL
from domain import (
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    OBLAST_NAMES,
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
                        id BIGSERIAL PRIMARY KEY,
                        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        event_type VARCHAR(32) NOT NULL,
                        level VARCHAR(10),
                        district TEXT NOT NULL,
                        channel_id BIGINT,
                        message_id BIGINT,
                        source TEXT
                    )
                """)
                cur.execute("""
                    DO $$
                    BEGIN
                        -- Migrate alert_history to new schema
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'recorded_at'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN recorded_at TIMESTAMPTZ;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'alert_history' AND column_name = 'datetime'
                            ) THEN
                                UPDATE alert_history SET recorded_at = datetime AT TIME ZONE 'Europe/Kyiv'
                                WHERE recorded_at IS NULL AND datetime IS NOT NULL;
                            END IF;
                            UPDATE alert_history SET recorded_at = NOW() WHERE recorded_at IS NULL;
                            ALTER TABLE alert_history ALTER COLUMN recorded_at SET NOT NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'event_type'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN event_type VARCHAR(32);
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'alert_history' AND column_name = 'type'
                            ) THEN
                                UPDATE alert_history
                                SET event_type = SPLIT_PART(type, ':', 1)
                                WHERE event_type IS NULL AND type IS NOT NULL;
                            END IF;
                            UPDATE alert_history SET event_type = 'air_raid_alert' WHERE event_type IS NULL;
                            ALTER TABLE alert_history ALTER COLUMN event_type SET NOT NULL;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'level'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN level VARCHAR(10);
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'alert_history' AND column_name = 'type'
                            ) THEN
                                UPDATE alert_history
                                SET level = CASE
                                    WHEN type LIKE '%:yellow' OR type LIKE 'yellow_%' THEN 'yellow'
                                    WHEN type LIKE '%:red' OR type LIKE 'red_%' THEN 'red'
                                    WHEN event_type = 'air_raid_alert' THEN 'red'
                                    ELSE NULL
                                END
                                WHERE level IS NULL;
                            END IF;
                        END IF;

                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'alert_history' AND column_name = 'district'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN district TEXT;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'alert_history' AND column_name = 'district_key'
                            ) THEN
                                UPDATE alert_history SET district = district_key WHERE district IS NULL AND district_key IS NOT NULL;
                            END IF;
                            UPDATE alert_history SET district = 'unknown' WHERE district IS NULL;
                            ALTER TABLE alert_history ALTER COLUMN district SET NOT NULL;
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
                            WHERE table_name = 'alert_history' AND column_name = 'source'
                        ) THEN
                            ALTER TABLE alert_history ADD COLUMN source TEXT;
                            IF EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'alert_history' AND column_name = 'message_link'
                            ) THEN
                                UPDATE alert_history SET source = message_link WHERE source IS NULL AND message_link IS NOT NULL;
                            END IF;
                        END IF;

                        -- Drop legacy columns if present
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'datetime') THEN
                            ALTER TABLE alert_history DROP COLUMN datetime;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'date') THEN
                            ALTER TABLE alert_history DROP COLUMN date;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'time') THEN
                            ALTER TABLE alert_history DROP COLUMN time;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'type') THEN
                            ALTER TABLE alert_history DROP COLUMN type;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'district_key') THEN
                            ALTER TABLE alert_history DROP COLUMN district_key;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'oblast_key') THEN
                            ALTER TABLE alert_history DROP COLUMN oblast_key;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'oblast') THEN
                            ALTER TABLE alert_history DROP COLUMN oblast;
                        END IF;
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_history' AND column_name = 'message_link') THEN
                            ALTER TABLE alert_history DROP COLUMN message_link;
                        END IF;

                        -- Normalize event_type and level to satisfy constraints
                        UPDATE alert_history
                        SET event_type = SPLIT_PART(event_type, ':', 1)
                        WHERE event_type LIKE '%:%';

                        UPDATE alert_history
                        SET event_type = 'air_raid_alert'
                        WHERE event_type NOT IN (
                            'air_raid_alert',
                            'air_raid_alert_cancelled',
                            'threat_of_shelling',
                            'threat_of_shelling_cancelled'
                        );

                        UPDATE alert_history
                        SET level = NULL
                        WHERE level IS NOT NULL AND level NOT IN ('yellow', 'red');

                        -- Constraints
                        ALTER TABLE alert_history DROP CONSTRAINT IF EXISTS chk_event_type;
                        ALTER TABLE alert_history ADD CONSTRAINT chk_event_type CHECK (
                            event_type IN (
                                'air_raid_alert',
                                'air_raid_alert_cancelled',
                                'threat_of_shelling',
                                'threat_of_shelling_cancelled'
                            )
                        );

                        ALTER TABLE alert_history DROP CONSTRAINT IF EXISTS chk_level;
                        ALTER TABLE alert_history ADD CONSTRAINT chk_level CHECK (
                            level IN ('yellow', 'red') OR level IS NULL
                        );
                    END $$;
                """)
                cur.execute("DROP INDEX IF EXISTS alert_history_district_dt_idx")
                cur.execute("DROP INDEX IF EXISTS alert_history_oblast_dt_idx")
                cur.execute("DROP INDEX IF EXISTS alert_history_datetime_idx")
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alert_history_district_recorded ON alert_history (district, recorded_at DESC)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alert_history_recorded_at ON alert_history (recorded_at DESC)"
                )
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subscriber_snapshots (
                        channel_id BIGINT NOT NULL,
                        channel TEXT NOT NULL,
                        collected_at TIMESTAMPTZ NOT NULL,
                        subscriber_count INTEGER NOT NULL CHECK (subscriber_count >= 0),
                        PRIMARY KEY (channel_id, collected_at)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_subscriber_snapshots_collected_at ON subscriber_snapshots (collected_at DESC)"
                )
                cur.execute("""
                    DO $$
                    BEGIN
                        -- Rename channel_code to channel if it exists in subscriber_snapshots
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'subscriber_snapshots' AND column_name = 'channel_code'
                        ) THEN
                            ALTER TABLE subscriber_snapshots RENAME COLUMN channel_code TO channel;
                        END IF;

                        -- Drop legacy view if it was created previously
                        IF EXISTS (
                            SELECT 1 FROM information_schema.views
                            WHERE table_name = 'subscribers'
                        ) THEN
                            DROP VIEW subscribers CASCADE;
                        END IF;
                    END $$;
                """)

                # Check if channel_stats or subscribers table exists for legacy migration
                cur.execute("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'channel_stats' AND table_type = 'BASE TABLE'
                """)
                if cur.fetchone() is not None:
                    cur.execute("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'subscribers' AND table_type = 'BASE TABLE'
                    """)
                    if cur.fetchone() is None:
                        cur.execute("ALTER TABLE channel_stats RENAME TO subscribers")

                cur.execute("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'subscribers' AND table_type = 'BASE TABLE'
                """)
                if cur.fetchone() is not None:
                    cur.execute("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'subscribers'
                    """)
                    cols = {r[0] for r in cur.fetchall()}

                    if "time" in cols and "date" in cols:
                        ts_expr = "COALESCE(time, (date::text || ' 00:00:00')::timestamp) AT TIME ZONE 'Europe/Kyiv'"
                    elif "time" in cols:
                        ts_expr = "time AT TIME ZONE 'Europe/Kyiv'"
                    elif "collected_at" in cols:
                        ts_expr = "collected_at"
                    elif "date" in cols:
                        ts_expr = (
                            "(date::text || ' 00:00:00')::timestamp AT TIME ZONE 'Europe/Kyiv'"
                        )
                    else:
                        ts_expr = "NOW()"

                    if "channel_key" in cols:
                        ch_expr = "COALESCE(channel_key, '')"
                    elif "channel" in cols:
                        ch_expr = "COALESCE(channel, '')"
                    else:
                        ch_expr = "''"

                    if "subscribers" in cols:
                        cnt_expr = "GREATEST(COALESCE(subscribers, 0), 0)"
                    elif "subscriber_count" in cols:
                        cnt_expr = "GREATEST(COALESCE(subscriber_count, 0), 0)"
                    else:
                        cnt_expr = "0"

                    ch_id_expr = "channel_id" if "channel_id" in cols else "0"

                    cur.execute(f"""
                        INSERT INTO subscriber_snapshots (channel_id, channel, collected_at, subscriber_count)
                        SELECT {ch_id_expr}, {ch_expr}, {ts_expr}, {cnt_expr}
                        FROM subscribers WHERE channel_id IS NOT NULL
                        ON CONFLICT (channel_id, collected_at) DO UPDATE
                            SET subscriber_count = EXCLUDED.subscriber_count,
                                channel = EXCLUDED.channel
                    """)
                    cur.execute("DROP TABLE subscribers CASCADE")
            conn.commit()
    except Exception:
        log.exception("Failed to ensure the database schema exists")
        raise

    log.info("PostgreSQL schema ready")


THREAT_TABLES = {"alerts", "explosions", "shellings"}


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


update_explosion_status = partial(update_threat_status, "explosions", status=True)
reset_explosion_status = partial(reset_threat_status, "explosions")
update_shelling_status = partial(update_threat_status, "shellings", status=True)
reset_shelling_status = partial(reset_threat_status, "shellings")

get_alert_status = partial(get_threat_status, "alerts")
get_explosion_status = partial(get_threat_status, "explosions")
get_shelling_status = partial(get_threat_status, "shellings")

get_alert_time = partial(get_threat_time, "alerts")
get_explosion_time = partial(get_threat_time, "explosions")
get_shelling_time = partial(get_threat_time, "shellings")

get_alert_source = partial(get_threat_source, "alerts")
get_explosion_source = partial(get_threat_source, "explosions")
get_shelling_source = partial(get_threat_source, "shellings")


def update_explosion_source(target: str, link: str) -> None:
    update_threat_status("explosions", target, source_val=link)


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
    level: str | None = None,
) -> None:
    district_key = get_region_by_channel_id(channel_id)
    if not district_key or district_key not in DISTRICT_CONFIG:
        return

    oblast_key = DISTRICT_CONFIG[district_key]["oblast"]

    now = datetime.datetime.now(datetime.timezone.utc)
    current_time = now.strftime("%H:%M")
    now_epoch = str(int(time.time()))
    source = message_link or DEFAULT_SOURCE

    event_type = None
    is_active: bool | None = None
    status_str = str(status)
    if ":" in status_str and not level:
        base_st, lvl_part = status_str.split(":", 1)
        status_str = base_st
        level = lvl_part

    if status_str in ("Повітряна тривога", "air_raid_alert"):
        is_active = True
        event_type = "air_raid_alert"
    elif status_str in ("Відбій повітряної тривоги", "air_raid_alert_cancelled"):
        is_active = False
        event_type = "air_raid_alert_cancelled"
    elif status_str in ("Загроза артилерійського обстрілу", "threat_of_shelling"):
        is_active = True
        event_type = "threat_of_shelling"
    elif status_str in ("Відбій загрози артобстрілу", "threat_of_shelling_cancelled"):
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
            if is_active and level:
                updates["level"] = level
            elif not is_active:
                redis_client.hdel(city_key, "level")

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
                           (recorded_at, district, event_type, level,
                            channel_id, message_id, source)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (
                            now,
                            district_key,
                            event_type,
                            level if event_type == "air_raid_alert" else None,
                            channel_id,
                            message_id,
                            source,
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
                    SELECT DISTINCT ON (district)
                        COALESCE(district, '') as district,
                        event_type,
                        level,
                        recorded_at,
                        source
                    FROM alert_history
                    WHERE district IS NOT NULL
                    ORDER BY district, recorded_at DESC
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
        d_key, alert_type, alert_level, dt, message_link = row
        source = message_link or DEFAULT_SOURCE
        o_key = DISTRICT_CONFIG.get(d_key, {}).get("oblast", d_key)
        alert_time = dt.strftime("%H:%M") if (dt and hasattr(dt, "strftime")) else "None"
        dt_epoch = (
            str(int(dt.timestamp())) if (dt and hasattr(dt, "timestamp")) else str(int(time.time()))
        )

        if "shelling" in str(alert_type).lower():
            is_active = str(alert_type).lower() in ("threat_of_shelling", "1", "true")
            st_str = "true" if is_active else "false"
            if d_key:
                pipeline.hset(
                    f"threat:shellings:{d_key}",
                    mapping={
                        "status": st_str,
                        "time": alert_time,
                        "source": source,
                        "updated_at": dt_epoch,
                    },
                )
        else:
            alert_str = str(alert_type).lower()
            is_active = (
                alert_str.startswith("air_raid_alert") and not alert_str.endswith("_cancelled")
            ) or alert_str in ("start", "1", "true")
            st_str = "true" if is_active else "false"

            level = alert_level
            if not level:
                if ":" in str(alert_type):
                    level = str(alert_type).split(":", 1)[1]
                elif is_active:
                    level = "red"

            if d_key:
                city_mapping = {
                    "status": st_str,
                    "time": alert_time,
                    "source": source,
                    "type": alert_type
                    or ("air_raid_alert" if is_active else "air_raid_alert_cancelled"),
                    "updated_at": dt_epoch,
                }
                if is_active and level:
                    city_mapping["level"] = level
                pipeline.hset(
                    f"threat:alerts:city:{d_key}",
                    mapping=city_mapping,
                )
                if is_active and o_key:
                    pipeline.sadd(f"threat:alerts:active:{o_key}", d_key)

    pipeline.set("system:state_initialized", "true")
    pipeline.execute()
    log.info("Redis state rehydrated successfully from PostgreSQL (%d records)", len(rows))


def _clean_source(source_val: Any) -> str | None:
    if not source_val:
        return None
    s = str(source_val).strip()
    if s in ("None", "telegram", ""):
        return None
    return s


def _clean_updated_at(val: Any) -> int | None:
    try:
        ts = int(float(val))
        return ts if ts > 0 else None
    except (ValueError, TypeError):
        return None


def _resolve_alert_level(data: dict[str, Any]) -> str:
    lvl = data.get("level")
    if lvl in ("yellow", "red"):
        return str(lvl)
    alert_type = str(data.get("type", ""))
    if ":" in alert_type:
        candidate = alert_type.split(":", 1)[1]
        if candidate in ("yellow", "red"):
            return candidate
    return "red"


ALL_OBLASTS = list(OBLAST_NAMES.keys())


def get_all_threats_data() -> dict[str, Any]:
    districts = list(DISTRICT_CONFIG.keys())

    try:
        pipeline = redis_client.pipeline()
        for district in districts:
            pipeline.hgetall(f"threat:alerts:city:{district}")
        for district in districts:
            pipeline.hgetall(f"threat:shellings:{district}")
        results = pipeline.execute()
    except Exception:
        log.exception("Failed to read threat data from Redis; /api cannot be served")
        raise

    n = len(districts)
    alerts_results = results[:n]
    shellings_results = results[n:]

    district_map: dict[str, dict[str, Any]] = {}
    for district, alert_raw, shelling_raw in zip(
        districts, alerts_results, shellings_results, strict=False
    ):
        alert_raw = alert_raw or {}
        shelling_raw = shelling_raw or {}

        alert_type = alert_raw.get("type", "")
        if alert_type.endswith("_cancelled") or alert_type in (
            "threat_of_shelling",
            "threat_of_shelling_cancelled",
        ):
            alert_active = False
        else:
            alert_active = _normalize_status(alert_raw.get("status", False))

        alert_dict = {
            "status": alert_active,
            "level": _resolve_alert_level(alert_raw) if alert_active else None,
            "updated_at": _clean_updated_at(alert_raw.get("updated_at")),
            "source": _clean_source(alert_raw.get("source")),
        }

        shelling_active = _normalize_status(shelling_raw.get("status", False))
        shelling_dict = {
            "status": shelling_active,
            "updated_at": _clean_updated_at(shelling_raw.get("updated_at")),
            "source": _clean_source(shelling_raw.get("source")),
        }

        district_map[district] = {
            "title": DISTRICT_CONFIG[district]["name"],
            "alert": alert_dict,
            "shelling": shelling_dict,
        }

    result: dict[str, Any] = {}
    for oblast in ALL_OBLASTS:
        oblast_districts = DISTRICTS_BY_OBLAST.get(oblast, [])
        districts_dict = {d: district_map[d] for d in oblast_districts if d in district_map}
        result[oblast] = {
            "title": OBLAST_NAMES.get(oblast, oblast),
            "districts": districts_dict,
        }

    return result
