"""
Sirens - Air Raid Alert Monitoring System.

This module monitors a source Telegram channel for air raid alerts
and broadcasts them to Sirens network channels.
"""

import asyncio
import logging
import os
import sys
import datetime
from logging.handlers import RotatingFileHandler

import redis.asyncio as redis
import asyncpg
import requests
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    AuthKeyDuplicatedError,
    AuthKeyNotFound,
    UnauthorizedError,
)
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import (
    InputChatUploadedPhoto, 
    UpdateNewChannelMessage, 
    MessageService, 
    MessageActionChatEditPhoto
)

from alerts import cli

from config import (
    api_id, api_hash, REGION_CONFIG, MESSAGES, IMAGES_PATH,
    LOGS_PATH, SESSION_PATH,
    REDIS_URL, DATABASE_URL, HEALTHCHECKS_PING_URL_ALERTS, SENTRY_DSN_ALERTS
)

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


CHANNEL_PHOTO_PATHS = {
    "air_raid_alert": f"{IMAGES_PATH}/air-raid-alert.png",
    "air_raid_alert_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
    "threat_of_shelling": f"{IMAGES_PATH}/threat-of-shelling.png",
    "threat_of_shelling_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
}


def log_alert_received(region: str, alert_type: str):
    display_name = REGION_CONFIG.get(region, {}).get('display_name', region.capitalize())
    
    if alert_type == "air_raid_alert":
        log.info("Air raid alert received for %s", display_name)
    elif alert_type == "air_raid_alert_cancelled":
        log.info("Air raid alert cancellation received for %s", display_name)
    else:
        log.info("%s received for %s", alert_type.replace('_', ' ').capitalize(), display_name)


async def update_channel_photo(channel_entity, file_path):
    uploaded_file = await client.upload_file(file=file_path)
    input_photo = InputChatUploadedPhoto(uploaded_file)
    return await client(EditPhotoRequest(channel=channel_entity, photo=input_photo))


async def delete_photo_update_service_message(channel_entity, edit_result):
    for update in edit_result.updates:
        if isinstance(update, UpdateNewChannelMessage):
            message = update.message
            if isinstance(message, MessageService) and isinstance(message.action, MessageActionChatEditPhoto):
                await client.delete_messages(entity=channel_entity, message_ids=[message.id])
                log.debug("Service message %d deleted for channel %d", message.id, channel_entity.id)
                return
    
    log.warning("Service message about photo update not found in API response for channel %d", channel_entity.id)


PHOTO_UPDATE_MAX_ATTEMPTS = 3
PHOTO_UPDATE_DELAY = 5


async def process_channel_photo_update(channel_id, region, alert_type):
    file_path = CHANNEL_PHOTO_PATHS.get(alert_type)
    if not file_path:
        return

    display_name = REGION_CONFIG.get(region, {}).get('display_name', region.capitalize())

    for attempt in range(1, PHOTO_UPDATE_MAX_ATTEMPTS + 1):
        current_state = await redis_client.get(f"channel_state:{channel_id}") if redis_client else None
        if current_state != alert_type:
            log.warning(
                "Photo update skipped for %s: state changed from %s to %s",
                display_name, alert_type, current_state
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
                display_name, attempt, PHOTO_UPDATE_MAX_ATTEMPTS, e.seconds
            )
            await asyncio.sleep(e.seconds)

        except Exception:
            log.exception(
                "Error changing photo for %s (attempt %d/%d)",
                display_name, attempt, PHOTO_UPDATE_MAX_ATTEMPTS
            )
            await asyncio.sleep(PHOTO_UPDATE_DELAY * (2 ** (attempt - 1)))

    log.error(
        "Aborting photo update for %s after %d attempts",
        display_name, PHOTO_UPDATE_MAX_ATTEMPTS
    )


async def send_alert(channel_id: int, region: str, alert_type: str):
    message_text = MESSAGES.get(alert_type)
    if not message_text:
        log.error("Unknown alert type: %s", alert_type)
        return

    display_name = REGION_CONFIG.get(region, {}).get('display_name', region.capitalize())

    if redis_client:
        previous_alert_type = await redis_client.get(f"channel_state:{channel_id}")
        if previous_alert_type == alert_type:
            log.info(
                "Duplicate %s ignored for %s: already in this state",
                alert_type, display_name
            )
            return

        await redis_client.set(f"channel_state:{channel_id}", alert_type)

        status = 1 if alert_type in ("air_raid_alert", "threat_of_shelling") else 0
        event_type = "start" if status == 1 else "end"
        oblast = REGION_CONFIG.get(region, {}).get('oblast', region)
        now = datetime.datetime.now()
        current_time = now.strftime("%H:%M")

        await redis_client.hset(
            f"threat:alerts:{oblast}",
            mapping={
                "status": status,
                "time": current_time,
                "source": "telegram"
            }
        )

        if pg_pool:
            try:
                async with pg_pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO alert_history (datetime, date, time, oblast, type) VALUES ($1, $2, $3, $4, $5)",
                        now, now.date(), current_time, oblast, alert_type
                    )
            except Exception as e:
                log.error("Failed to insert alert history into PG: %s", e)

    try:
        await client.send_message(channel_id, message_text)
        if alert_type == "air_raid_alert":
            log.info("Air raid alert sent to %s", display_name)
        elif alert_type == "air_raid_alert_cancelled":
            log.info("Air raid alert cancellation sent to %s", display_name)
        else:
            log.info("%s sent to %s", alert_type.replace('_', ' ').capitalize(), display_name)
    except Exception:
        if alert_type == "air_raid_alert":
            log.exception("Failed to send air raid alert to %s", display_name)
        elif alert_type == "air_raid_alert_cancelled":
            log.exception("Failed to send air raid alert cancellation to %s", display_name)
        else:
            log.exception("Failed to send %s to %s", alert_type.replace('_', ' '), display_name)

    if CHANNEL_PHOTO_PATHS.get(alert_type):
        task = asyncio.create_task(process_channel_photo_update(channel_id, region, alert_type))
        running_tasks.add(task)
        task.add_done_callback(running_tasks.discard)
    else:
        log.debug("No photo mapping for '%s', skipping photo update", alert_type)


def build_message_handler(region_channels: dict):
    async def handle_incoming_message(event):
        message_text = event.message.message

        for region_key, region_config in REGION_CONFIG.items():
            channel_id = region_channels.get(region_key)
            if not channel_id:
                continue

            if not any(trigger in message_text for trigger in region_config['triggers']):
                continue

            alert_type = None

            if 'alert_triggers' in region_config:
                for a_type, keywords in region_config['alert_triggers'].items():
                    if any(keyword in message_text for keyword in keywords):
                        alert_type = a_type
                        break
            
            if not alert_type:
                if "Повітряна тривога" in message_text:
                    alert_type = "air_raid_alert"
                elif "Відбій тривоги" in message_text:
                    alert_type = "air_raid_alert_cancelled"

            if alert_type:
                log_alert_received(region_key, alert_type)
                task = asyncio.create_task(send_alert(channel_id, region_key, alert_type))
                running_tasks.add(task)
                task.add_done_callback(running_tasks.discard)

    return handle_incoming_message


FATAL_SESSION_ERRORS = (AuthKeyDuplicatedError, AuthKeyNotFound, UnauthorizedError)
TRANSIENT_CONNECTION_ERRORS = (OSError,)

HEALTHCHECK_PING_INTERVAL = 60  # seconds; pair with a ~3min period on the healthchecks.io check
HEALTHCHECK_PING_TIMEOUT = 10  # seconds


def _ping_healthcheck(suffix: str = "") -> None:
    if not HEALTHCHECKS_PING_URL_ALERTS:
        return
    try:
        requests.get(f"{HEALTHCHECKS_PING_URL_ALERTS}{suffix}", timeout=HEALTHCHECK_PING_TIMEOUT)
    except Exception:
        log.warning("Failed to ping healthchecks.io", exc_info=True)


async def _healthcheck_loop(client: TelegramClient) -> None:
    if not HEALTHCHECKS_PING_URL_ALERTS:
        log.warning("HEALTHCHECKS_PING_URL_ALERTS not set; skipping healthcheck pings")
        return
    while True:
        await asyncio.sleep(HEALTHCHECK_PING_INTERVAL)
        if client.is_connected():
            await asyncio.to_thread(_ping_healthcheck)


async def main():
    global client, redis_client, pg_pool

    args = cli.get_args()

    sentry_sdk.init(
        dsn=SENTRY_DSN_ALERTS,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.WARNING)],
        environment=args.mode,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )

    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("Failed to connect to Redis: %s", e)

    try:
        pg_pool = await asyncpg.create_pool(DATABASE_URL)
    except Exception as e:
        log.error("Failed to connect to PostgreSQL: %s", e)

    region_channels, source_channel = cli.get_mode_config(args)
    os.makedirs(SESSION_PATH, exist_ok=True)
    session_file = os.path.join(SESSION_PATH, "sirens")

    try:
        async with TelegramClient(session_file, api_id, api_hash) as tg_client:
            client = tg_client
            if not await client.is_user_authorized():
                await client.start(
                    phone=lambda: input('Please enter phone number: '),
                    code_callback=lambda: input('Please enter a login code: ')
                )
            log.info("Sirens started in %s mode", args.mode)

            client.add_event_handler(
                build_message_handler(region_channels),
                events.NewMessage(chats=[source_channel])
            )

            healthcheck_task = asyncio.create_task(_healthcheck_loop(client))
            try:
                await client.run_until_disconnected()
            finally:
                healthcheck_task.cancel()
                await asyncio.gather(healthcheck_task, return_exceptions=True)

    except FATAL_SESSION_ERRORS:
        log.critical(
            "Telegram session is invalid; manual re-auth required via ./deploy/setup.sh",
            exc_info=True
        )
        await asyncio.to_thread(_ping_healthcheck, "/fail")
        raise

    except TRANSIENT_CONNECTION_ERRORS:
        log.error("Telegram connection lost and could not be recovered", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())