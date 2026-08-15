import csv
import datetime
import io
import logging
from typing import Any, Dict, Optional, Union
from functools import partial

import psycopg2
import redis

from config import REDIS_URL, DATABASE_URL, REGION_CONFIG, real_channels, test_channels

log = logging.getLogger(__name__)

def get_region_by_channel_id(channel_id: int) -> Optional[str]:
    for name, cid in real_channels.items():
        if cid == channel_id:
            return name
    for name, cid in test_channels.items():
        if cid == channel_id:
            return name
    return None

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def get_pg_conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DATABASE_URL)

SCHEMA_LOCK_KEY = 8110921  # arbitrary, shared by every process that runs this DDL


def ensure_pg_tables() -> None:
    try:
        with get_pg_conn() as conn:
            with conn.cursor() as cur:
                # CREATE TABLE IF NOT EXISTS is not atomic against a concurrent
                # creator: both sessions pass the existence check, then one fails
                # creating the sequence ("duplicate key ... pg_class_relname_nsp_index").
                # Several gunicorn workers plus the bi job all call this, so take
                # an advisory lock first and make check-and-create one serialized
                # step. The lock is released when the transaction ends.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS alert_history (
                        id SERIAL PRIMARY KEY,
                        datetime TIMESTAMP NOT NULL,
                        date DATE NOT NULL,
                        time TEXT NOT NULL,
                        oblast TEXT NOT NULL,
                        type TEXT NOT NULL
                    )
                """)
                # One snapshot per channel per day; the UNIQUE constraint is what
                # lets the snapshot re-run safely (INSERT ... ON CONFLICT DO UPDATE).
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS channel_stats (
                        id SERIAL PRIMARY KEY,
                        channel_key TEXT NOT NULL,
                        channel_id BIGINT NOT NULL,
                        participants INTEGER NOT NULL,
                        date DATE NOT NULL,
                        collected_at TIMESTAMP NOT NULL,
                        UNIQUE (channel_key, date)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS channel_stats_date_idx ON channel_stats (date)"
                )
            conn.commit()
    except Exception:
        log.exception("Failed to ensure the database schema exists")
        raise

    log.info("PostgreSQL schema ready")

STATS_CSV_COLUMNS = ("channel_key", "display_name", "date", "participants")


def export_stats_csv() -> str:
    """The whole channel_stats table as CSV, oldest day first.

    Assembled in Python rather than with COPY so the human-readable city names
    from REGION_CONFIG can be folded in - the dashboard has no business knowing
    about internal channel keys. A year of data is ~13k rows, so the cost of
    building it in memory is nil.
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT channel_key, date, participants FROM channel_stats "
                "ORDER BY date, channel_key"
            )
            rows = cur.fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(STATS_CSV_COLUMNS)

    for channel_key, date, participants in rows:
        display_name = REGION_CONFIG.get(channel_key, {}).get('display_name', channel_key)
        writer.writerow([channel_key, display_name, date.isoformat(), participants])

    return buffer.getvalue()


THREAT_TABLES = {"alerts", "explosions", "shellings"}

def _validate_table(table_name: str) -> None:
    if table_name not in THREAT_TABLES:
        raise ValueError(f"Invalid threat table: {table_name}")


def _get_threat_field(table_name: str, oblast: str, field_name: str) -> Union[int, str]:
    _validate_table(table_name)
    key = f"threat:{table_name}:{oblast}"
    val = redis_client.hget(key, field_name)
    if field_name == "status":
        if val is None:
            return 0
        return 1 if str(val).lower() in ['true', '1', 'active'] else 0
    return str(val) if val is not None else "None"


def get_threat_status(table_name: str, oblast: str) -> int:
    return int(_get_threat_field(table_name, oblast, "status"))


def get_threat_time(table_name: str, oblast: str) -> str:
    return str(_get_threat_field(table_name, oblast, "time"))


def get_threat_source(table_name: str, oblast: str) -> str:
    return str(_get_threat_field(table_name, oblast, "source"))


def update_threat_status(table_name: str, oblast: str, status: int = 1, time_val: Optional[str] = None, source_val: Optional[str] = None) -> None:
    _validate_table(table_name)
    key = f"threat:{table_name}:{oblast}"
    if time_val is None:
        time_val = datetime.datetime.now().strftime("%H:%M")
    
    updates = {"status": str(status), "time": time_val}
    if source_val is not None:
        updates["source"] = source_val
        
    redis_client.hset(key, mapping=updates)


def reset_threat_status(table_name: str, oblast: str) -> None:
    _validate_table(table_name)
    key = f"threat:{table_name}:{oblast}"
    redis_client.hset(key, mapping={
        "status": "0",
        "time": "None",
        "source": "None"
    })


update_explosion_status = partial(update_threat_status, "explosions", status=1)
reset_explosion_status = partial(reset_threat_status, "explosions")
update_shelling_status = partial(update_threat_status, "shellings", status=1)
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

def update_explosion_source(oblast: str, link: str) -> None:
    update_threat_status("explosions", oblast, source_val=link)

def update_shelling_source(oblast: str, link: str) -> None:
    update_threat_status("shellings", oblast, source_val=link)

def update_alert_source(channel_id: int, link: str) -> None:
    region_name = get_region_by_channel_id(channel_id)
    if region_name and region_name in REGION_CONFIG:
        oblast = REGION_CONFIG[region_name]['oblast']
        key = f"threat:alerts:{oblast}"
        redis_client.hset(key, "source", link)


async def update_alert_status(channel_id: int, status: str) -> None:
    region_name = get_region_by_channel_id(channel_id)
    if not region_name or region_name not in REGION_CONFIG:
        return
        
    oblast = REGION_CONFIG[region_name]['oblast']
        
    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M")
    
    event_type = None
    st_val = None
    if status == "Повітряна тривога":
        st_val = 1
        event_type = "start"
    elif status == "Відбій повітряної тривоги":
        st_val = 0
        event_type = "end"

    key = f"threat:alerts:{oblast}"
    updates = {"time": current_time}
    if st_val is not None:
        updates["status"] = str(st_val)
        
    redis_client.hset(key, mapping=updates)
    
    if event_type:
        city_ua = REGION_CONFIG[region_name]['triggers'][0]
        try:
            with get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO alert_history (datetime, date, time, oblast, type) VALUES (%s, %s, %s, %s, %s)",
                        (now, now.date(), current_time, city_ua, event_type)
                    )
                conn.commit()
        except Exception:
            log.exception("Failed to record alert %s for %s in history", event_type, oblast)
            raise


def get_all_threats_data() -> Dict[str, Any]:
    """
    Пакетная выборка данных всех угроз для API через Redis pipeline.
    """
    tables = ["alerts", "explosions", "shellings"]
    oblasts = [
        'cherkasy_oblast', 'chernihiv_oblast', 'chernivtsi_oblast', 'crimea',
        'dnipropetrovsk_oblast', 'donetsk_oblast', 'ivanofrankivsk_oblast',
        'kharkiv_oblast', 'kherson_oblast', 'khmelnytskyi_oblast',
        'kirovohrad_oblast', 'kyiv', 'kyiv_oblast', 'luhansk_oblast',
        'lviv_oblast', 'mykolaiv_oblast', 'odesa_oblast', 'poltava_oblast',
        'rivne_oblast', 'sevastopol', 'sumy_oblast', 'ternopil_oblast',
        'vinnytsia_oblast', 'volyn_oblast', 'zakarpattia_oblast',
        'zaporizhzhia_oblast', 'zhytomyr_oblast',
    ]
    
    # adding specific cities for shelling
    fetch_oblasts = oblasts + ['nikopol', 'kherson']
    
    keys_order = []

    try:
        pipeline = redis_client.pipeline()

        for table in tables:
            for oblast in fetch_oblasts:
                key = f"threat:{table}:{oblast}"
                pipeline.hgetall(key)
                keys_order.append((table, oblast))

        results = pipeline.execute()
    except Exception:
        # Deliberately not degrading to empty data: a map rendered from zeros
        # reads as "no alerts anywhere", which is a dangerous lie during a raid.
        # Fail the request loudly instead and let the caller see the 500.
        log.exception("Failed to read threat data from Redis; /api cannot be served")
        raise
    
    raw_data: Dict[str, Dict[str, Any]] = {t: {} for t in tables}
    for (table, oblast), data in zip(keys_order, results):
        if not data:
            data = {'status': 0, 'time': 'None', 'source': 'None'}
        else:
            raw_status = data.get('status', 0)
            data['status'] = 1 if str(raw_status).lower() in ['true', '1', 'active'] else 0
            data['time'] = data.get('time', 'None')
            data['source'] = data.get('source', 'None')
        raw_data[table][oblast] = data
        
    result: Dict[str, Any] = {}
    
    def build_oblast_entry(oblast: str) -> Dict[str, Any]:
        return {
            'alert': raw_data['alerts'].get(oblast, {'status': 0, 'time': 'None', 'source': 'None'}),
            'explosion': raw_data['explosions'].get(oblast, {'status': 0, 'time': 'None', 'source': 'None'}),
        }
        
    for o in oblasts:
        result[o] = build_oblast_entry(o)
        
    for city, parent_oblast in [('nikopol', 'dnipropetrovsk_oblast'), ('kherson', 'kherson_oblast')]:
        entry = build_oblast_entry(parent_oblast)
        entry['shelling'] = raw_data['shellings'].get(city, {'status': 0, 'time': 'None', 'source': 'None'})
        result[city] = entry
        
    return result
