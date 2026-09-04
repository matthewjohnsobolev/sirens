from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.tl.types import MessageActionChatEditPhoto, MessageService, UpdateNewChannelMessage

from ops.broadcast import (
    broadcast_alert_to_telegram,
    build_message_link,
    run_broadcast_sync,
)


def test_build_message_link():
    # With username
    link = build_message_link(-1001234567, 42, username="sirens_kyiv")
    assert link == "https://t.me/sirens_kyiv/42"

    # Without username, -100 prefix
    link = build_message_link(-1001234567, 42)
    assert link == "https://t.me/c/1234567/42"

    # Without username, standard negative prefix
    link = build_message_link(-987654, 10)
    assert link == "https://t.me/c/987654/10"


@pytest.mark.asyncio
async def test_broadcast_missing_credentials():
    with patch("ops.broadcast.TELEGRAM_API_ID", None):
        with pytest.raises(ValueError, match="TELEGRAM_API_ID or TELEGRAM_API_HASH is not set"):
            await broadcast_alert_to_telegram(-100123, "air_raid_alert")


@pytest.mark.asyncio
async def test_broadcast_unknown_alert_type():
    with (
        patch("ops.broadcast.TELEGRAM_API_ID", "12345"),
        patch("ops.broadcast.TELEGRAM_API_HASH", "hash123"),
    ):
        with pytest.raises(ValueError, match="No message template configured"):
            await broadcast_alert_to_telegram(-100123, "unknown_type")


@pytest.mark.asyncio
async def test_broadcast_success_with_photo_update():
    mock_client = AsyncMock()
    mock_client.is_user_authorized.return_value = True

    mock_entity = MagicMock()
    mock_entity.username = "sirens_channel"
    mock_client.get_entity.return_value = mock_entity

    mock_msg = MagicMock()
    mock_msg.id = 777
    mock_client.send_message.return_value = mock_msg

    # Mock photo edit response with a service message
    mock_service_msg = MagicMock(spec=MessageService)
    mock_service_msg.id = 888
    mock_service_msg.action = MagicMock(spec=MessageActionChatEditPhoto)

    mock_update = MagicMock(spec=UpdateNewChannelMessage)
    mock_update.message = mock_service_msg

    mock_edit_res = MagicMock()
    mock_edit_res.updates = [mock_update]
    mock_client.return_value = mock_edit_res

    with (
        patch("ops.broadcast.TELEGRAM_API_ID", "12345"),
        patch("ops.broadcast.TELEGRAM_API_HASH", "hash123"),
        patch("ops.broadcast.TelegramClient", return_value=mock_client),
    ):
        res = await broadcast_alert_to_telegram(-1001234567, "air_raid_alert", update_photo=True)

        assert res["message_id"] == 777
        assert res["message_link"] == "https://t.me/sirens_channel/777"
        assert res["photo_updated"] is True
        mock_client.send_message.assert_called_once()
        mock_client.delete_messages.assert_called_once_with(mock_entity, [888])
        mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_broadcast_fallback_session_authorization():
    # First client is not authorized, second (fallback) is
    client_primary = AsyncMock()
    client_primary.is_user_authorized.return_value = False

    client_fallback = AsyncMock()
    client_fallback.is_user_authorized.return_value = True
    mock_entity = MagicMock()
    mock_entity.username = None
    client_fallback.get_entity.return_value = mock_entity
    mock_msg = MagicMock()
    mock_msg.id = 123
    client_fallback.send_message.return_value = mock_msg

    clients = [client_primary, client_fallback]

    with (
        patch("ops.broadcast.TELEGRAM_API_ID", "12345"),
        patch("ops.broadcast.TELEGRAM_API_HASH", "hash123"),
        patch("ops.broadcast.TelegramClient", side_effect=clients),
    ):
        res = await broadcast_alert_to_telegram(
            -1001234567, "air_raid_alert_cancelled", update_photo=False
        )
        assert res["message_id"] == 123
        assert res["message_link"] == "https://t.me/c/1234567/123"
        assert res["photo_updated"] is False


@pytest.mark.asyncio
async def test_broadcast_unauthorized_error():
    client_primary = AsyncMock()
    client_primary.is_user_authorized.return_value = False

    client_fallback = AsyncMock()
    client_fallback.is_user_authorized.return_value = False

    clients = [client_primary, client_fallback]

    with (
        patch("ops.broadcast.TELEGRAM_API_ID", "12345"),
        patch("ops.broadcast.TELEGRAM_API_HASH", "hash123"),
        patch("ops.broadcast.TelegramClient", side_effect=clients),
    ):
        with pytest.raises(RuntimeError, match="Telegram client is not authorized"):
            await broadcast_alert_to_telegram(-1001234567, "air_raid_alert")


@pytest.mark.asyncio
async def test_broadcast_photo_upload_failure_handled():
    mock_client = AsyncMock()
    mock_client.is_user_authorized.return_value = True

    mock_entity = MagicMock()
    mock_entity.username = None
    mock_client.get_entity.return_value = mock_entity

    mock_msg = MagicMock()
    mock_msg.id = 999
    mock_client.send_message.return_value = mock_msg
    mock_client.upload_file.side_effect = Exception("Upload failed")

    with (
        patch("ops.broadcast.TELEGRAM_API_ID", "12345"),
        patch("ops.broadcast.TELEGRAM_API_HASH", "hash123"),
        patch("ops.broadcast.TelegramClient", return_value=mock_client),
    ):
        res = await broadcast_alert_to_telegram(-1001234567, "air_raid_alert", update_photo=True)
        assert res["photo_updated"] is False
        assert "Upload failed" in res["photo_error"]


def test_run_broadcast_sync():
    with patch(
        "ops.broadcast.broadcast_alert_to_telegram",
        new_callable=AsyncMock,
        return_value={"message_id": 1},
    ) as mock_async:
        res = run_broadcast_sync(-100123, "air_raid_alert", update_photo=False)
        assert res["message_id"] == 1
        mock_async.assert_called_once_with(-100123, "air_raid_alert", False)
