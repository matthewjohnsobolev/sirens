"""
Telegram broadcaster for sirens-ops.
Sends alert messages and updates channel avatars when --broadcast is explicitly requested.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telethon import TelegramClient
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import (
    InputChatUploadedPhoto,
    MessageActionChatEditPhoto,
    MessageService,
    UpdateNewChannelMessage,
)

from config import (
    IMAGES_PATH,
    SESSION_PATH,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
)
from domain import MESSAGES

log = logging.getLogger(__name__)

CHANNEL_PHOTO_PATHS = {
    "air_raid_alert": f"{IMAGES_PATH}/air-raid-alert.png",
    "air_raid_alert:red": f"{IMAGES_PATH}/explosions.png",
    "air_raid_alert:yellow": f"{IMAGES_PATH}/threat-of-shelling.png",
    "air_raid_alert_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
    "threat_of_shelling": f"{IMAGES_PATH}/air-raid-alert.png",
    "threat_of_shelling_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
}


def build_message_link(channel_id: int, message_id: int, username: str | None = None) -> str:
    if username:
        return f"https://t.me/{username}/{message_id}"
    internal_id = str(channel_id)
    internal_id = internal_id[4:] if internal_id.startswith("-100") else internal_id.lstrip("-")
    return f"https://t.me/c/{internal_id}/{message_id}"


async def broadcast_alert_to_telegram(
    channel_id: int,
    alert_type: str,
    update_photo: bool = True,
    level: str | None = None,
) -> dict[str, Any]:
    """Connect to Telegram, post alert message and optionally update avatar."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise ValueError("TELEGRAM_API_ID or TELEGRAM_API_HASH is not set in config.")

    effective_level = level.lower() if level else None
    if ":" in alert_type and not effective_level:
        base_type, effective_level = alert_type.split(":", 1)
        base_type = base_type.strip()
        effective_level = effective_level.strip().lower()
    else:
        base_type = alert_type.strip()

    msg_key = f"{base_type}:{effective_level}" if effective_level else alert_type
    message_text = MESSAGES.get(msg_key) or MESSAGES.get(alert_type) or MESSAGES.get(base_type)
    if not message_text:
        raise ValueError(f"No message template configured for alert type: {alert_type}")

    session_file = str(SESSION_PATH / "sirens_ops")
    client = TelegramClient(session_file, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)

    result: dict[str, Any] = {
        "channel_id": channel_id,
        "alert_type": alert_type,
        "message_id": None,
        "message_link": None,
        "photo_updated": False,
    }
    if effective_level:
        result["level"] = effective_level

    await client.connect()
    try:
        if not await client.is_user_authorized():
            fallback_session = str(SESSION_PATH / "alerts")
            await client.disconnect()
            client = TelegramClient(fallback_session, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Telegram client is not authorized. Please run the alerts worker to authenticate the session."
                )

        entity = await client.get_entity(channel_id)
        username = getattr(entity, "username", None)

        msg = await client.send_message(entity, message_text)
        result["message_id"] = msg.id
        result["message_link"] = build_message_link(channel_id, msg.id, username)

        photo_key = f"{base_type}:{effective_level}" if effective_level else alert_type
        photo_path = (
            CHANNEL_PHOTO_PATHS.get(photo_key)
            or CHANNEL_PHOTO_PATHS.get(alert_type)
            or CHANNEL_PHOTO_PATHS.get(base_type)
        )
        if update_photo and photo_path:
            try:
                uploaded = await client.upload_file(file=photo_path)
                edit_res = await client(
                    EditPhotoRequest(channel=entity, photo=InputChatUploadedPhoto(uploaded))
                )
                result["photo_updated"] = True

                for update in edit_res.updates:
                    if isinstance(update, UpdateNewChannelMessage):
                        update_msg = update.message
                        if isinstance(update_msg, MessageService) and isinstance(
                            update_msg.action, MessageActionChatEditPhoto
                        ):
                            await client.delete_messages(entity, [update_msg.id])
                            break
            except Exception as e:
                log.warning("Failed to update channel photo: %s", e)
                result["photo_error"] = str(e)

        return result
    finally:
        await client.disconnect()


def run_broadcast_sync(
    channel_id: int,
    alert_type: str,
    update_photo: bool = True,
    level: str | None = None,
) -> dict[str, Any]:
    """Synchronous runner for the async broadcast function."""
    if level is not None:
        return asyncio.run(
            broadcast_alert_to_telegram(channel_id, alert_type, update_photo, level=level)
        )
    return asyncio.run(broadcast_alert_to_telegram(channel_id, alert_type, update_photo))
