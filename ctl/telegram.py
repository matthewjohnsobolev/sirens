"""
Telegram broadcaster for sirens-ctl.
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
    "air_raid_alert_cancelled": f"{IMAGES_PATH}/air-raid-alert-cancelled.png",
    "threat_of_shelling": f"{IMAGES_PATH}/threat-of-shelling.png",
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
) -> dict[str, Any]:
    """Connect to Telegram, post alert message and optionally update avatar."""
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise ValueError("TELEGRAM_API_ID or TELEGRAM_API_HASH is not set in config.")

    message_text = MESSAGES.get(alert_type)
    if not message_text:
        raise ValueError(f"No message template configured for alert type: {alert_type}")

    session_file = str(SESSION_PATH / "sirens_ctl")
    client = TelegramClient(session_file, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)

    result = {
        "channel_id": channel_id,
        "alert_type": alert_type,
        "message_id": None,
        "message_link": None,
        "photo_updated": False,
    }

    await client.connect()
    try:
        if not await client.is_user_authorized():
            # Try fallback to alerts session if authorized there
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

        # 1. Send text message
        msg = await client.send_message(entity, message_text)
        result["message_id"] = msg.id
        result["message_link"] = build_message_link(channel_id, msg.id, username)

        # 2. Update channel photo if required and available
        photo_path = CHANNEL_PHOTO_PATHS.get(alert_type)
        if update_photo and photo_path:
            try:
                uploaded = await client.upload_file(file=photo_path)
                edit_res = await client(EditPhotoRequest(channel=entity, photo=InputChatUploadedPhoto(uploaded)))
                result["photo_updated"] = True

                # Clean up photo service message
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


def run_broadcast_sync(channel_id: int, alert_type: str, update_photo: bool = True) -> dict[str, Any]:
    """Synchronous runner for the async broadcast function."""
    return asyncio.run(broadcast_alert_to_telegram(channel_id, alert_type, update_photo))
