"""
Sirens - Air Raid Alert Monitoring System.

This module monitors a source Telegram channel for air raid alerts
and broadcasts them to Sirens network channels.
"""

import asyncio
import datetime
import json
import logging
import os
import re
import sys
import time
from logging.handlers import RotatingFileHandler

import asyncpg
import redis.asyncio as redis
import requests
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from telethon import TelegramClient, events
from telethon.errors import (
    AuthKeyDuplicatedError,
    AuthKeyNotFound,
    FloodWaitError,
    UnauthorizedError,
)
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import (
    InputChatUploadedPhoto,
    MessageActionChatEditPhoto,
    MessageService,
    UpdateNewChannelMessage,
)

from alerts import cli
from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_TELEMETRY_NAMESPACE_ID,
    DATABASE_URL,
    HEALTHCHECKS_ALERTS_BROADCAST_PING_URL,
    HEALTHCHECKS_ALERTS_SOURCE_PING_URL,
    IMAGES_PATH,
    LOGS_PATH,
    REDIS_URL,
    SENTRY_DSN,
    SESSION_PATH,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    VERSION,
)
from domain import (
    BROADCAST_CITIES,
    BROADCAST_DISTRICTS,
    DISTRICT_CONFIG,
    MESSAGES,
    OBLAST_TRIGGERS,
)
from web.db import DEFAULT_SOURCE, ensure_pg_tables, rehydrate_state_from_db

os.makedirs(LOGS_PATH, exist_ok=True)
LOG_FILE = os.path.join(LOGS_PATH, "alerts.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)
logging.getLogger("telethon").setLevel(logging.WARNING)

running_tasks: set[asyncio.Task] = set()

redis_client = None
pg_pool = None
client: TelegramClient = None

last_source_message_at: float | None = None
last_broadcast_at: float | None = None
last_alert_payload: dict | None = None
source_silence_reported: bool = False
broadcast_silence_reported: bool = False

CHANNEL_PHOTO_PATHS = {
    "air_raid_alert": f"{IMAGES_PATH}/air-raid-alert.png",
    "air_raid_alert_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
    "threat_of_shelling": f"{IMAGES_PATH}/threat-of-shelling.png",
    "threat_of_shelling_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
}

channel_usernames: dict[int, str] = {}


def build_message_link(channel_id: int, message_id: int, username: str | None = None) -> str:
    if username:
        return f"https://t.me/{username}/{message_id}"

    internal_id = str(channel_id)
    internal_id = internal_id[4:] if internal_id.startswith("-100") else internal_id.lstrip("-")
    return f"https://t.me/c/{internal_id}/{message_id}"


async def resolve_channel_username(channel_id: int) -> str | None:
    cached = channel_usernames.get(channel_id)
    if cached:
        return cached

    try:
        entity = await client.get_entity(channel_id)
    except Exception:
        log.warning("Failed to resolve username for channel %d", channel_id, exc_info=True)
        return None

    username = getattr(entity, "username", None)
    if not isinstance(username, str) or not username:
        return None

    channel_usernames[channel_id] = username
    return username


async def broadcast_reference(channel_id: int, message) -> tuple[int | None, str | None]:
    message_id = getattr(message, "id", None)
    if not isinstance(message_id, int):
        log.warning("Broadcast to channel %d returned no message id; link not stored", channel_id)
        return None, None

    username = await resolve_channel_username(channel_id)
    return message_id, build_message_link(channel_id, message_id, username)


async def source_reference(event) -> tuple[int | None, str | None]:
    """Source message ID and link for map-only updates."""
    message_id = getattr(event.message, "id", None)
    chat_id = getattr(event, "chat_id", None)
    if not isinstance(message_id, int) or not isinstance(chat_id, int):
        log.warning("Source message has no id; map-only districts recorded without a link")
        return None, None

    username = await resolve_channel_username(chat_id)
    return message_id, build_message_link(chat_id, message_id, username)


def spawn_tracked_task(coro, description: str):
    task = asyncio.create_task(coro)
    running_tasks.add(task)

    def _on_done(finished: asyncio.Task):
        running_tasks.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            log.error("%s failed", description, exc_info=finished.exception())

    task.add_done_callback(_on_done)


def district_label(district_key: str) -> str:
    """Label for logging: latin for broadcast channels, Ukrainian for the rest."""
    conf = DISTRICT_CONFIG.get(district_key)
    if not conf:
        return district_key.capitalize()
    return conf.get("display_name") or conf["name"]


LOCATION_LOCATIVE = {
    "bilatserkva": "у Білій Церкві",
    "bucha": "у Бучі",
    "cherkasy": "у Черкасах",
    "chernihiv": "у Чернігові",
    "chernivtsi": "у Чернівцях",
    "dnipro": "у Дніпрі",
    "fastiv": "у Фастові",
    "ivanofrankivsk": "в Івано-Франківську",
    "izmail": "в Ізмаїлі",
    "kamianske": "у Кам'янському",
    "kharkiv": "у Харкові",
    "kherson": "у Херсоні",
    "khmelnytskyi": "у Хмельницькому",
    "kovel": "у Ковелі",
    "kremenchuk": "у Кременчуці",
    "kropyvnytskyi": "у Кропивницькому",
    "kryvyirih": "у Кривому Розі",
    "kyiv": "у Києві",
    "lutsk": "у Луцьку",
    "lviv": "у Львові",
    "mykolaiv": "у Миколаєві",
    "nikopol": "у Нікополі",
    "odesa": "в Одесі",
    "pervomaisk": "у Первомайську",
    "poltava": "у Полтаві",
    "rivne": "у Рівному",
    "sumy": "у Сумах",
    "ternopil": "у Тернополі",
    "uman": "в Умані",
    "uzhhorod": "в Ужгороді",
    "vinnytsia": "у Вінниці",
    "zaporizhzhia": "у Запоріжжі",
    "zhytomyr": "у Житомирі",
    "zolotonosha": "у Золотоноші",
    "zvenyhorodka": "у Звенигородці",
    "boryspil": "у Борисполі",
    "brovary": "у Броварах",
    "vyshhorod": "у Вишгороді",
    "obukhiv": "в Обухові",
}


def city_or_district_name(district_key: str) -> str:
    """Ukrainian city name (if broadcast) or district name for telemetry."""
    if district_key in BROADCAST_CITIES:
        return BROADCAST_CITIES[district_key]
    conf = DISTRICT_CONFIG.get(district_key)
    if conf:
        return conf.get("city") or conf.get("name") or district_key
    return district_key.capitalize()


def location_locative(district_key: str) -> str:
    """Locative case form of the location title."""
    if district_key in LOCATION_LOCATIVE:
        return LOCATION_LOCATIVE[district_key]
    conf = DISTRICT_CONFIG.get(district_key, {})
    name = conf.get("name", "")
    if name.endswith(" район"):
        base = name[:-6]
        adj = (base[:-2] + "ому") if (base.endswith("ий") or base.endswith("ій")) else base
        prep = "в" if name[0].lower() in "аеєиіїоуюя" else "у"
        return f"{prep} {adj} районі"
    city = conf.get("city") or conf.get("display_name") or district_key
    prep = "в" if city[0].lower() in "аеєиіїоуюя" else "у"
    return f"{prep} {city}"


def log_alert_received(region: str, alert_type: str):
    display_name = district_label(region)

    if alert_type == "air_raid_alert":
        log.info("Air raid alert received for %s", display_name)
    elif alert_type == "air_raid_alert_cancelled":
        log.info("Air raid alert cancellation received for %s", display_name)
    else:
        log.info("%s received for %s", alert_type.replace("_", " ").capitalize(), display_name)


async def update_channel_photo(channel_entity, file_path):
    uploaded_file = await client.upload_file(file=file_path)
    input_photo = InputChatUploadedPhoto(uploaded_file)
    return await client(EditPhotoRequest(channel=channel_entity, photo=input_photo))


async def delete_photo_update_service_message(channel_entity, edit_result):
    for update in edit_result.updates:
        if isinstance(update, UpdateNewChannelMessage):
            message = update.message
            if isinstance(message, MessageService) and isinstance(
                message.action, MessageActionChatEditPhoto
            ):
                await client.delete_messages(entity=channel_entity, message_ids=[message.id])
                log.debug(
                    "Service message %d deleted for channel %d", message.id, channel_entity.id
                )
                return

    log.warning(
        "Service message about photo update not found in API response for channel %d",
        channel_entity.id,
    )


PHOTO_UPDATE_MAX_ATTEMPTS = 3
PHOTO_UPDATE_DELAY = 5


async def process_channel_photo_update(channel_id, region, alert_type):
    file_path = CHANNEL_PHOTO_PATHS.get(alert_type)
    if not file_path:
        return

    display_name = district_label(region)

    for attempt in range(1, PHOTO_UPDATE_MAX_ATTEMPTS + 1):
        current_state = (
            await redis_client.get(f"channel_state:{channel_id}") if redis_client else None
        )
        if current_state != alert_type:
            log.warning(
                "Photo update skipped for %s: state changed from %s to %s",
                display_name,
                alert_type,
                current_state,
            )
            return

        try:
            channel_entity = await client.get_entity(channel_id)
            result = await update_channel_photo(channel_entity, file_path)
            await delete_photo_update_service_message(channel_entity, result)
            return
        except FloodWaitError as e:
            log.warning(
                "Photo update rate-limited for %s (attempt %d/%d), retrying in %ds",
                display_name,
                attempt,
                PHOTO_UPDATE_MAX_ATTEMPTS,
                e.seconds,
            )
            await asyncio.sleep(e.seconds)
        except Exception:
            log.exception(
                "Error changing photo for %s (attempt %d/%d)",
                display_name,
                attempt,
                PHOTO_UPDATE_MAX_ATTEMPTS,
            )
            await asyncio.sleep(PHOTO_UPDATE_DELAY * (2 ** (attempt - 1)))

    log.error(
        "Aborting photo update for %s after %d attempts", display_name, PHOTO_UPDATE_MAX_ATTEMPTS
    )


async def _record_alert_state(
    channel_id: int | None,
    region: str,
    alert_type: str,
    message_id: int | None = None,
    message_link: str | None = None,
):
    global last_alert_payload

    district_key = region
    oblast_key = DISTRICT_CONFIG.get(region, {}).get("oblast", region)
    now = datetime.datetime.now()
    current_time = now.strftime("%H:%M")
    now_epoch = str(int(time.time()))
    now_utc_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    source = message_link or DEFAULT_SOURCE

    if channel_id is not None:
        loc_name = city_or_district_name(district_key)
        loc_title = location_locative(district_key)
        last_alert_payload = {
            "type": alert_type,
            "region": oblast_key,
            "district": district_key,
            "district_name": loc_name,
            "city_name": loc_name,
            "location_title": loc_title,
            "timestamp": now_utc_iso,
            "message_id": message_id,
            "message_link": message_link,
        }

        if redis_client:
            try:
                await redis_client.set(LAST_ALERT_INFO_KEY, json.dumps(last_alert_payload))
            except Exception:
                log.warning("Failed to store last alert info in Redis", exc_info=True)

    if redis_client:
        try:
            state_key = (
                f"channel_state:{channel_id}"
                if channel_id is not None
                else f"district_state:{district_key}"
            )
            await redis_client.set(state_key, alert_type)

            if "shelling" in alert_type:
                is_shelling_active = alert_type == "threat_of_shelling"
                status_str = "true" if is_shelling_active else "false"
                await redis_client.hset(
                    f"threat:shellings:{district_key}",
                    mapping={
                        "status": status_str,
                        "time": current_time,
                        "source": source,
                        "updated_at": now_epoch,
                    },
                )
            else:
                is_alert_active = alert_type == "air_raid_alert"
                status_str = "true" if is_alert_active else "false"
                await redis_client.hset(
                    f"threat:alerts:city:{district_key}",
                    mapping={
                        "status": status_str,
                        "time": current_time,
                        "source": source,
                        "type": alert_type,
                        "updated_at": now_epoch,
                    },
                )

                active_key = f"threat:alerts:active:{oblast_key}"
                if is_alert_active:
                    await redis_client.sadd(active_key, district_key)
                else:
                    await redis_client.srem(active_key, district_key)

                active_count = await redis_client.scard(active_key)
                try:
                    is_oblast_active = int(active_count or 0) > 0
                except (ValueError, TypeError):
                    is_oblast_active = bool(active_count)

                await redis_client.hset(
                    f"threat:alerts:{oblast_key}",
                    mapping={
                        "status": "true" if is_oblast_active else "false",
                        "time": current_time,
                        "source": source,
                        "updated_at": now_epoch,
                    },
                )
        except Exception:
            log.exception("Failed to update Redis state for %s", district_key)

    request_telemetry_sync()

    if pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO alert_history
                       (datetime, date, time, district_key, oblast_key, type,
                        channel_id, message_id, message_link)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                    now,
                    now.date(),
                    current_time,
                    district_key,
                    oblast_key,
                    alert_type,
                    channel_id,
                    message_id,
                    message_link,
                )
        except Exception as e:
            log.error("Failed to insert alert history into PG: %s", e)


async def send_alert(channel_id: int, region: str, alert_type: str):
    message_text = MESSAGES.get(alert_type)
    if not message_text:
        log.error("Unknown alert type: %s", alert_type)
        return

    display_name = district_label(region)

    if redis_client:
        try:
            previous_alert_type = await redis_client.get(f"channel_state:{channel_id}")
            if previous_alert_type == alert_type:
                log.info(
                    "Duplicate %s ignored for %s: already in this state", alert_type, display_name
                )
                return
        except Exception:
            log.exception(
                "Redis unavailable for %s; broadcasting %s without dedup check",
                display_name,
                alert_type,
            )

    send_succeeded = False
    sent_message = None
    try:
        sent_message = await client.send_message(channel_id, message_text)
        send_succeeded = True
        if alert_type == "air_raid_alert":
            log.info("Air raid alert sent to %s", display_name)
        elif alert_type == "air_raid_alert_cancelled":
            log.info("Air raid alert cancellation sent to %s", display_name)
        else:
            log.info("%s sent to %s", alert_type.replace("_", " ").capitalize(), display_name)
    except Exception:
        if alert_type == "air_raid_alert":
            log.exception("Failed to send air raid alert to %s", display_name)
        elif alert_type == "air_raid_alert_cancelled":
            log.exception("Failed to send air raid alert cancellation to %s", display_name)
        else:
            log.exception("Failed to send %s to %s", alert_type.replace("_", " "), display_name)

    await record_broadcast(send_succeeded)

    if send_succeeded:
        message_id, message_link = await broadcast_reference(channel_id, sent_message)
        await _record_alert_state(
            channel_id,
            region,
            alert_type,
            message_id=message_id,
            message_link=message_link,
        )

        if CHANNEL_PHOTO_PATHS.get(alert_type):
            spawn_tracked_task(
                process_channel_photo_update(channel_id, region, alert_type),
                f"Photo update for {display_name}",
            )
        else:
            log.debug("No photo mapping for '%s', skipping photo update", alert_type)


async def record_map_only_alert(
    district_key: str,
    alert_type: str,
    message_id: int | None = None,
    message_link: str | None = None,
):
    """Records state for a non-broadcast district on the map."""
    if alert_type not in MESSAGES:
        log.error("Unknown alert type: %s", alert_type)
        return

    label = district_label(district_key)

    if redis_client:
        try:
            previous_alert_type = await redis_client.get(f"district_state:{district_key}")
            if previous_alert_type == alert_type:
                log.info("Duplicate %s ignored for %s: already in this state", alert_type, label)
                return
        except Exception:
            log.exception(
                "Redis unavailable for %s; recording %s without dedup check", label, alert_type
            )

    await _record_alert_state(
        None,
        district_key,
        alert_type,
        message_id=message_id,
        message_link=message_link,
    )
    log.info("%s recorded for %s (map only)", alert_type.replace("_", " ").capitalize(), label)


ONGOING_NOTICE_RE = re.compile(r"^[^\n]*ще трива[^\n]*$", re.MULTILINE)


def strip_ongoing_notice(message_text: str) -> str:
    if not message_text:
        return ""
    notice = ONGOING_NOTICE_RE.search(message_text)
    return message_text[: notice.start()] if notice else message_text


def _trigger_pattern(trigger: str) -> re.Pattern:
    """Matches word boundaries accounting for apostrophes and hyphens."""
    return re.compile(rf"(?<![\w'\u2019-]){re.escape(trigger)}(?![\w'\u2019])")


DISTRICT_PATTERNS = {
    key: [_trigger_pattern(trigger) for trigger in conf["triggers"]]
    for key, conf in DISTRICT_CONFIG.items()
}

OBLAST_PATTERNS = {
    oblast: [_trigger_pattern(trigger) for trigger in triggers]
    for oblast, triggers in OBLAST_TRIGGERS.items()
}

DISTRICT_MENTION_RE = re.compile(r"[А-ЯІЇЄҐ][\w'\u2019-]*\s+район")


def _alert_type_for(district_key: str, message_text: str) -> str | None:
    conf = DISTRICT_CONFIG.get(district_key, {})

    for alert_type, keywords in conf.get("alert_triggers", {}).items():
        if any(keyword in message_text for keyword in keywords):
            return alert_type

    if "Повітряна тривога" in message_text:
        return "air_raid_alert"
    if "Відбій тривоги" in message_text:
        return "air_raid_alert_cancelled"
    return None


def match_districts(message_text: str) -> dict[str, str]:
    """Maps mentioned districts to their alert event type."""
    oblast_hit = {
        oblast: any(pattern.search(message_text) for pattern in patterns)
        for oblast, patterns in OBLAST_PATTERNS.items()
    }

    matched: dict[str, str] = {}
    for district_key, conf in DISTRICT_CONFIG.items():
        if not oblast_hit.get(conf["oblast"]) and not any(
            pattern.search(message_text) for pattern in DISTRICT_PATTERNS[district_key]
        ):
            continue

        alert_type = _alert_type_for(district_key, message_text)
        if alert_type:
            matched[district_key] = alert_type

    return matched


KNOWN_DISTRICT_TRIGGERS = frozenset(
    trigger for conf in DISTRICT_CONFIG.values() for trigger in conf["triggers"]
)


reported_unknown_districts: set[str] = set()


def log_unrecognised_districts(message_text: str) -> None:
    """Logs district names present in the post but missing from configuration."""
    unknown = (
        {" ".join(mention.split()) for mention in DISTRICT_MENTION_RE.findall(message_text)}
        - KNOWN_DISTRICT_TRIGGERS
        - reported_unknown_districts
    )

    if unknown:
        reported_unknown_districts.update(unknown)
        log.warning(
            "Districts named in the source message but missing from config: %s",
            ", ".join(sorted(unknown)),
        )


LAST_SOURCE_MESSAGE_KEY = "service:alerts:last_source_message_at"
LAST_BROADCAST_AT_KEY = "service:alerts:last_broadcast_at"
LAST_ALERT_INFO_KEY = "service:alerts:last_alert_info"


async def push_telemetry_to_kv() -> None:
    """Pushes a snapshot of current telemetry state to Cloudflare KV."""
    if not (CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_TELEMETRY_NAMESPACE_ID and CLOUDFLARE_API_TOKEN):
        return

    try:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        last_bcast_iso = (
            datetime.datetime.fromtimestamp(last_broadcast_at, tz=datetime.timezone.utc).isoformat()
            if last_broadcast_at is not None
            else None
        )
        last_src_iso = (
            datetime.datetime.fromtimestamp(
                last_source_message_at, tz=datetime.timezone.utc
            ).isoformat()
            if last_source_message_at is not None
            else None
        )

        active_count = 0
        if redis_client:
            try:
                oblasts_seen = set()
                for conf in DISTRICT_CONFIG.values():
                    o_key = conf.get("oblast")
                    if o_key and o_key not in oblasts_seen:
                        oblasts_seen.add(o_key)
                        cnt = await redis_client.scard(f"threat:alerts:active:{o_key}")
                        active_count += int(cnt or 0)
            except Exception:
                pass

        source_connected = False
        if client:
            try:
                conn_val = client.is_connected()
                if asyncio.iscoroutine(conn_val):
                    source_connected = bool(await conn_val)
                else:
                    source_connected = bool(conn_val)
            except Exception:
                pass

        payload = {
            "last_broadcast_at": last_bcast_iso,
            "last_alert": last_alert_payload,
            "last_source_message_at": last_src_iso,
            "active_alerts_count": active_count,
            "source_connected": source_connected,
            "updated_at": now_dt.isoformat(),
        }

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
            f"/storage/kv/namespaces/{CLOUDFLARE_TELEMETRY_NAMESPACE_ID}/values/telemetry:latest"
        )
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        }

        def _do_put():
            res = requests.put(url, data=json.dumps(payload), headers=headers, timeout=5)
            res.raise_for_status()

        await asyncio.to_thread(_do_put)
        log.debug("Telemetry snapshot pushed to Cloudflare KV successfully")
    except Exception:
        log.warning("Failed to push telemetry snapshot to Cloudflare KV", exc_info=True)


TELEMETRY_SYNC_DELAY = 2.0
_telemetry_sync_task: asyncio.Task | None = None


async def _debounced_telemetry_push(delay: float) -> None:
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await push_telemetry_to_kv()
    except asyncio.CancelledError:
        pass


def request_telemetry_sync(delay: float | None = None) -> asyncio.Task:
    """Schedule a coalesced/debounced telemetry push to Cloudflare KV.

    If multiple state changes happen in quick succession (e.g. 35 districts in one post),
    only a single KV PUT request is executed after the burst settles.
    """
    global _telemetry_sync_task

    actual_delay = TELEMETRY_SYNC_DELAY if delay is None else delay

    if _telemetry_sync_task and not _telemetry_sync_task.done():
        try:
            loop = _telemetry_sync_task.get_loop()
            if not loop.is_closed():
                _telemetry_sync_task.cancel()
        except Exception:
            pass

    task = asyncio.create_task(_debounced_telemetry_push(actual_delay))
    _telemetry_sync_task = task
    running_tasks.add(task)

    def _on_done(finished: asyncio.Task):
        running_tasks.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            log.error("Telemetry sync task failed", exc_info=finished.exception())

    task.add_done_callback(_on_done)
    return task


async def record_source_message(moment: datetime.datetime | None = None) -> None:
    """Records the timestamp of the latest source message received."""
    global last_source_message_at

    seen_at = moment.timestamp() if isinstance(moment, datetime.datetime) else time.time()
    last_source_message_at = seen_at

    if not redis_client:
        return

    try:
        await redis_client.set(LAST_SOURCE_MESSAGE_KEY, str(int(seen_at)))
    except Exception:
        log.warning("Failed to store the source message timestamp in Redis", exc_info=True)


async def record_broadcast(succeeded: bool) -> None:
    """Records the timestamp of the latest successful broadcast."""
    global last_broadcast_at

    if not succeeded:
        return

    now_ts = time.time()
    last_broadcast_at = now_ts

    if redis_client:
        try:
            await redis_client.set(LAST_BROADCAST_AT_KEY, str(int(now_ts)))
        except Exception:
            log.warning("Failed to store the broadcast timestamp in Redis", exc_info=True)

    request_telemetry_sync()


async def _prime_monitoring_state(source_channel) -> None:
    """Restores the monitoring state for input and output silence clocks on startup."""
    global last_broadcast_at, last_source_message_at, last_alert_payload

    stored_source_seen_at = None
    stored_broadcast_at = None
    if redis_client:
        try:
            raw_seen_at = await redis_client.get(LAST_SOURCE_MESSAGE_KEY)
            raw_bcast_at = await redis_client.get(LAST_BROADCAST_AT_KEY)
            raw_alert_json = await redis_client.get(LAST_ALERT_INFO_KEY)
            if raw_alert_json:
                data = json.loads(raw_alert_json)
                if isinstance(data, dict) and data.get("district") in BROADCAST_DISTRICTS:
                    last_alert_payload = data
        except Exception:
            log.warning("Redis unreachable while restoring monitoring state", exc_info=True)
        else:
            try:
                stored_source_seen_at = float(raw_seen_at) if raw_seen_at else None
            except (TypeError, ValueError):
                log.warning("Stored source message timestamp is malformed: %r", raw_seen_at)
            try:
                stored_broadcast_at = float(raw_bcast_at) if raw_bcast_at else None
            except (TypeError, ValueError):
                log.warning("Stored broadcast timestamp is malformed: %r", raw_bcast_at)

    if not last_alert_payload and pg_pool:
        try:
            async with pg_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT datetime, district_key, oblast_key, type, message_id, message_link
                       FROM alert_history
                       WHERE channel_id IS NOT NULL
                       ORDER BY datetime DESC LIMIT 1"""
                )
                if row:
                    dt = row["datetime"]
                    dt_iso = (
                        dt.astimezone(datetime.timezone.utc).isoformat()
                        if dt.tzinfo
                        else dt.replace(tzinfo=datetime.timezone.utc).isoformat()
                    )
                    d_key = row["district_key"] or ""
                    loc_name = city_or_district_name(d_key) if d_key else ""
                    loc_title = location_locative(d_key) if d_key else ""
                    last_alert_payload = {
                        "type": row["type"],
                        "region": row["oblast_key"],
                        "district": d_key,
                        "district_name": loc_name,
                        "city_name": loc_name,
                        "location_title": loc_title,
                        "timestamp": dt_iso,
                        "message_id": row["message_id"],
                        "message_link": row["message_link"],
                    }
        except Exception:
            log.warning("Failed to restore last_alert_info from PostgreSQL", exc_info=True)

    if stored_broadcast_at is not None:
        last_broadcast_at = stored_broadcast_at
    else:
        last_broadcast_at = time.time()

    if stored_source_seen_at is not None:
        last_source_message_at = stored_source_seen_at
    else:
        moment = None
        try:
            messages = await client.get_messages(source_channel, limit=1)
            moment = getattr(messages[0], "date", None) if messages else None
        except Exception:
            log.warning("Could not read the last source message from Telegram", exc_info=True)

        if moment is None:
            log.warning("Starting the silence clock from now: the last source post is unknown")

        await record_source_message(moment)

    spawn_tracked_task(push_telemetry_to_kv(), "Initial telemetry sync on start")


def build_message_handler(region_channels: dict):
    async def handle_incoming_message(event):
        await record_source_message(getattr(event.message, "date", None))

        if not event.message or not getattr(event.message, "message", None):
            return

        message_text = strip_ongoing_notice(event.message.message)
        matched = match_districts(message_text)
        log_unrecognised_districts(message_text)

        if not matched:
            return

        source_ref: tuple[int | None, str | None] = (None, None)
        if any(not region_channels.get(district_key) for district_key in matched):
            source_ref = await source_reference(event)

        for district_key, alert_type in matched.items():
            log_alert_received(district_key, alert_type)
            channel_id = region_channels.get(district_key)

            if channel_id:
                spawn_tracked_task(
                    send_alert(channel_id, district_key, alert_type),
                    f"Alert broadcast of {alert_type} to {district_key}",
                )
            else:
                spawn_tracked_task(
                    record_map_only_alert(district_key, alert_type, *source_ref),
                    f"Map-only record of {alert_type} for {district_key}",
                )

    return handle_incoming_message


FATAL_SESSION_ERRORS = (AuthKeyDuplicatedError, AuthKeyNotFound, UnauthorizedError)
TRANSIENT_CONNECTION_ERRORS = (OSError,)

HEALTHCHECK_PING_INTERVAL = 60
HEALTHCHECK_PING_TIMEOUT = 10

SOURCE_SILENCE_THRESHOLD = 6 * 3600
BROADCAST_SILENCE_THRESHOLD = 6 * 3600


def _ping_url(base: str, suffix: str = "") -> None:
    if not base:
        return
    try:
        requests.get(f"{base}{suffix}", timeout=HEALTHCHECK_PING_TIMEOUT)
    except Exception:
        log.warning("Failed to ping healthchecks.io", exc_info=True)


def _ping_healthcheck(suffix: str = "") -> None:
    _ping_url(HEALTHCHECKS_ALERTS_SOURCE_PING_URL, suffix)


def _ping_tg_healthcheck(suffix: str = "") -> None:
    _ping_url(HEALTHCHECKS_ALERTS_BROADCAST_PING_URL, suffix)


async def _source_silence_seconds() -> float | None:
    if last_source_message_at is None:
        return None
    return max(0.0, time.time() - last_source_message_at)


async def _broadcast_silence_seconds() -> float | None:
    if last_broadcast_at is None:
        return None
    return max(0.0, time.time() - last_broadcast_at)


def _report_source_silence(silence: float | None) -> None:
    global source_silence_reported

    if silence is None:
        return

    if silence >= SOURCE_SILENCE_THRESHOLD:
        if not source_silence_reported:
            source_silence_reported = True
            log.error(
                "No message from the source channel for %.1f h; alerts are not reaching us",
                silence / 3600,
            )
    elif source_silence_reported:
        source_silence_reported = False
        log.info("The source channel is posting again")


def _report_broadcast_silence(silence: float | None) -> None:
    global broadcast_silence_reported

    if silence is None:
        return

    if silence >= BROADCAST_SILENCE_THRESHOLD:
        if not broadcast_silence_reported:
            broadcast_silence_reported = True
            log.error(
                "No alerts broadcasted to any network channel for %.1f h; outgoing pipeline may be stuck",
                silence / 3600,
            )
    elif broadcast_silence_reported:
        broadcast_silence_reported = False
        log.info("Alerts broadcasting resumed")


async def _healthcheck_loop(client: TelegramClient) -> None:
    if not HEALTHCHECKS_ALERTS_SOURCE_PING_URL:
        log.warning("HEALTHCHECKS_ALERTS_SOURCE_PING_URL not set; skipping healthcheck pings")

    while True:
        await asyncio.sleep(HEALTHCHECK_PING_INTERVAL)
        silence = await _source_silence_seconds()
        _report_source_silence(silence)

        if not client.is_connected():
            continue

        if silence is not None and silence >= SOURCE_SILENCE_THRESHOLD:
            await asyncio.to_thread(_ping_healthcheck, "/fail")
        else:
            await asyncio.to_thread(_ping_healthcheck)


async def _broadcast_watchdog_loop(client: TelegramClient) -> None:
    """Monitors Telegram broadcast pipeline liveness and pings healthchecks."""
    if not HEALTHCHECKS_ALERTS_BROADCAST_PING_URL:
        log.warning(
            "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL not set; skipping broadcast health pings"
        )

    while True:
        await asyncio.sleep(HEALTHCHECK_PING_INTERVAL)
        silence = await _broadcast_silence_seconds()
        _report_broadcast_silence(silence)

        if not client.is_connected():
            continue

        if silence is not None and silence >= BROADCAST_SILENCE_THRESHOLD:
            await asyncio.to_thread(_ping_tg_healthcheck, "/fail")
        else:
            await asyncio.to_thread(_ping_tg_healthcheck)

        spawn_tracked_task(push_telemetry_to_kv(), "Periodic telemetry sync")


async def main():
    global client, redis_client, pg_pool

    args = cli.get_args()

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.WARNING)],
        environment=args.mode,
        release=VERSION,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", "alerts")

    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("Failed to connect to Redis: %s", e)

    try:
        pg_pool = await asyncpg.create_pool(DATABASE_URL)
    except Exception as e:
        log.error("Failed to connect to PostgreSQL: %s", e)

    try:
        await asyncio.to_thread(ensure_pg_tables)
        await asyncio.to_thread(rehydrate_state_from_db)
    except Exception as e:
        log.error("Failed database initialization / rehydration: %s", e)

    region_channels, source_channel = cli.get_mode_config(args)
    os.makedirs(SESSION_PATH, exist_ok=True)
    session_file = os.path.join(SESSION_PATH, "sirens")

    try:
        async with TelegramClient(session_file, TELEGRAM_API_ID, TELEGRAM_API_HASH) as tg_client:
            client = tg_client
            if not await client.is_user_authorized():
                await client.start(
                    phone=lambda: input("Please enter phone number: "),
                    code_callback=lambda: input("Please enter a login code: "),
                )
            log.info("Sirens started in %s mode", args.mode)

            client.add_event_handler(
                build_message_handler(region_channels), events.NewMessage(chats=[source_channel])
            )

            await _prime_monitoring_state(source_channel)

            monitoring_tasks = [
                asyncio.create_task(_healthcheck_loop(client)),
                asyncio.create_task(_broadcast_watchdog_loop(client)),
            ]
            try:
                await client.run_until_disconnected()
            finally:
                for task in monitoring_tasks:
                    task.cancel()
                await asyncio.gather(*monitoring_tasks, return_exceptions=True)

    except FATAL_SESSION_ERRORS:
        log.critical(
            "Telegram session is invalid; manual re-auth required via ./deploy/setup.sh",
            exc_info=True,
        )
        await asyncio.to_thread(_ping_healthcheck, "/fail")
        raise

    except TRANSIENT_CONNECTION_ERRORS:
        log.error("Telegram connection lost and could not be recovered", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
