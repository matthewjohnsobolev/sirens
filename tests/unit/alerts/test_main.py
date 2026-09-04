"""
Unit tests for alerts.main (alert monitoring, state persistence, and broadcasting).
"""

import argparse
import asyncio
import datetime
import json
import logging
import re
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import AuthKeyDuplicatedError, FloodWaitError
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import (
    InputChatUploadedPhoto,
    MessageActionChatEditPhoto,
    MessageService,
    UpdateNewChannelMessage,
)

from alerts import main as alerts_main
from alerts.cli import get_mode_config
from alerts.main import (
    CHANNEL_PHOTO_PATHS,
    PHOTO_UPDATE_MAX_ATTEMPTS,
    broadcast_reference,
    build_message_handler,
    build_message_link,
    delete_photo_update_service_message,
    log_alert_received,
    log_unrecognised_districts,
    main,
    match_districts,
    process_channel_photo_update,
    record_map_only_alert,
    resolve_channel_username,
    send_alert,
    source_reference,
    split_alert_sections,
    strip_ongoing_notice,
    update_channel_photo,
)
from config import (
    DATABASE_URL,
    REDIS_URL,
    VERSION,
)
from domain import (
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    MESSAGES,
    REGION_CONFIG,
    real_source_channels,
)
from tests.samples.source_messages import (
    ALL_SAMPLES,
    MAP_ONLY_SAMPLES,
    MESSAGES_SAMPLES,
    PARTIAL_CANCELLATION_SAMPLES,
    oblast_message,
)

TIME_RE = re.compile(r"\d{2}:\d{2}")
CHANNEL_ID = 123456


@pytest.fixture(autouse=True)
def _reset_telemetry_state(monkeypatch):
    monkeypatch.setattr(alerts_main, "TELEMETRY_SYNC_DELAY", 0.0)
    alerts_main._telemetry_sync_task = None
    alerts_main.running_tasks.clear()
    yield
    if alerts_main._telemetry_sync_task and not alerts_main._telemetry_sync_task.done():
        try:
            loop = alerts_main._telemetry_sync_task.get_loop()
            if not loop.is_closed():
                alerts_main._telemetry_sync_task.cancel()
        except Exception:
            pass
    alerts_main._telemetry_sync_task = None
    alerts_main.running_tasks.clear()


async def _drain_background_tasks():
    while alerts_main.running_tasks:
        tasks = list(alerts_main.running_tasks)
        await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_spawn_tracked_task_logs_failure(caplog):
    caplog.set_level(logging.ERROR)

    async def boom():
        raise RuntimeError("task blew up")

    alerts_main.spawn_tracked_task(boom(), "Test task")
    await _drain_background_tasks()

    assert "Test task failed" in caplog.text
    assert "task blew up" in caplog.text
    assert alerts_main.running_tasks == set()


@pytest.mark.parametrize(
    "alert_type, expected",
    [
        ("air_raid_alert", "Air raid alert received for Kyiv"),
        ("air_raid_alert_cancelled", "Air raid alert cancellation received for Kyiv"),
        ("threat_of_shelling", "Threat of shelling received for Kyiv"),
        ("threat_of_shelling_cancelled", "Threat of shelling cancelled received for Kyiv"),
    ],
)
def test_log_alert_received(caplog, alert_type, expected):
    caplog.set_level(logging.INFO)
    log_alert_received("kyiv", alert_type)
    assert expected in caplog.text


def test_log_alert_received_falls_back_to_capitalized_region(caplog):
    caplog.set_level(logging.INFO)
    log_alert_received("atlantis", "air_raid_alert")
    assert "Air raid alert received for Atlantis" in caplog.text


@pytest.mark.asyncio
async def test_update_channel_photo_sends_edit_photo_request(mock_telegram_client):
    mock_telegram_client.upload_file.return_value = "mock_uploaded_file"
    mock_entity = MagicMock()

    result = await update_channel_photo(mock_entity, "test/path.png")

    mock_telegram_client.upload_file.assert_awaited_once_with(file="test/path.png")
    mock_telegram_client.assert_awaited_once()
    request = mock_telegram_client.call_args.args[0]
    assert isinstance(request, EditPhotoRequest)
    assert request.channel is mock_entity
    assert isinstance(request.photo, InputChatUploadedPhoto)
    assert request.photo.file == "mock_uploaded_file"
    assert result is mock_telegram_client.return_value


def _photo_service_update(message_id=123):
    message = MessageService(
        id=message_id,
        peer_id=MagicMock(),
        date=MagicMock(),
        action=MessageActionChatEditPhoto(photo=MagicMock()),
    )
    return UpdateNewChannelMessage(message=message, pts=1, pts_count=1)


@pytest.mark.asyncio
async def test_delete_photo_update_service_message(mock_telegram_client):
    edit_result = MagicMock(updates=[_photo_service_update(123)])
    mock_entity = MagicMock(id=456)

    await delete_photo_update_service_message(mock_entity, edit_result)

    mock_telegram_client.delete_messages.assert_awaited_once_with(
        entity=mock_entity, message_ids=[123]
    )


@pytest.mark.asyncio
async def test_delete_photo_update_service_message_when_absent(mock_telegram_client, caplog):
    caplog.set_level(logging.WARNING)
    edit_result = MagicMock(updates=[MagicMock()])
    mock_entity = MagicMock(id=456)

    await delete_photo_update_service_message(mock_entity, edit_result)

    mock_telegram_client.delete_messages.assert_not_awaited()
    assert "Service message about photo update not found" in caplog.text


@pytest.mark.asyncio
async def test_process_channel_photo_update_skips_when_state_changed(
    mock_redis, mock_telegram_client, caplog
):
    caplog.set_level(logging.WARNING)
    mock_redis.get.return_value = "threat_of_shelling"

    with (
        patch("alerts.main.update_channel_photo", new_callable=AsyncMock) as mock_update_photo,
        patch(
            "alerts.main.delete_photo_update_service_message", new_callable=AsyncMock
        ) as mock_delete,
    ):
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    mock_redis.get.assert_awaited_once_with(f"channel_state:{CHANNEL_ID}")
    mock_update_photo.assert_not_awaited()
    mock_delete.assert_not_awaited()
    mock_telegram_client.get_entity.assert_not_awaited()
    assert "Photo update skipped for Kyiv" in caplog.text


@pytest.mark.asyncio
async def test_process_channel_photo_update_success(mock_redis, mock_telegram_client):
    mock_redis.get.return_value = "air_raid_alert"
    mock_entity = MagicMock()
    mock_telegram_client.get_entity.return_value = mock_entity

    with (
        patch("alerts.main.update_channel_photo", new_callable=AsyncMock) as mock_update_photo,
        patch(
            "alerts.main.delete_photo_update_service_message", new_callable=AsyncMock
        ) as mock_delete,
    ):
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    mock_telegram_client.get_entity.assert_awaited_once_with(CHANNEL_ID)
    mock_update_photo.assert_awaited_once_with(mock_entity, CHANNEL_PHOTO_PATHS["air_raid_alert"])
    mock_delete.assert_awaited_once_with(mock_entity, mock_update_photo.return_value)


@pytest.mark.asyncio
async def test_process_channel_photo_update_retries_after_flood_wait(
    mock_redis, mock_telegram_client
):
    mock_redis.get.return_value = "air_raid_alert"
    mock_entity = MagicMock()
    mock_telegram_client.get_entity.side_effect = [
        FloodWaitError(request=MagicMock(), capture=2),
        mock_entity,
    ]

    with (
        patch("alerts.main.update_channel_photo", new_callable=AsyncMock) as mock_update_photo,
        patch(
            "alerts.main.delete_photo_update_service_message", new_callable=AsyncMock
        ) as mock_delete,
        patch("alerts.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    mock_sleep.assert_awaited_once_with(2)
    assert mock_telegram_client.get_entity.await_count == 2
    mock_update_photo.assert_awaited_once_with(mock_entity, CHANNEL_PHOTO_PATHS["air_raid_alert"])
    mock_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_channel_photo_update_gives_up_after_max_attempts(
    mock_redis, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)
    mock_redis.get.return_value = "air_raid_alert"
    mock_telegram_client.get_entity.side_effect = Exception("boom")

    with patch("alerts.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    assert mock_telegram_client.get_entity.await_count == PHOTO_UPDATE_MAX_ATTEMPTS
    assert [c.args[0] for c in mock_sleep.await_args_list] == [5, 10, 20]
    assert "Aborting photo update for Kyiv after 3 attempts" in caplog.text


@pytest.mark.asyncio
async def test_process_channel_photo_update_ignores_unknown_alert_type(
    mock_redis, mock_telegram_client
):
    await process_channel_photo_update(CHANNEL_ID, "kyiv", "unknown_type")

    mock_redis.get.assert_not_awaited()
    mock_telegram_client.get_entity.assert_not_awaited()


@pytest.fixture(autouse=True)
def _clear_username_cache():
    alerts_main.channel_usernames.clear()
    yield
    alerts_main.channel_usernames.clear()


@pytest.mark.parametrize(
    "channel_id, message_id, username, expected",
    [
        (-1001712561448, 42, "kyiv_alert", "https://t.me/kyiv_alert/42"),
        (-1001712561448, 42, None, "https://t.me/c/1712561448/42"),
        (-4242, 7, None, "https://t.me/c/4242/7"),
    ],
)
def test_build_message_link(channel_id, message_id, username, expected):
    assert build_message_link(channel_id, message_id, username) == expected


@pytest.mark.asyncio
async def test_resolve_channel_username_caches_the_lookup(mock_telegram_client):
    mock_telegram_client.get_entity.return_value = MagicMock(username="kyiv_alert")

    assert await resolve_channel_username(CHANNEL_ID) == "kyiv_alert"
    assert await resolve_channel_username(CHANNEL_ID) == "kyiv_alert"

    mock_telegram_client.get_entity.assert_awaited_once_with(CHANNEL_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity",
    [
        pytest.param(MagicMock(username=None), id="private-channel"),
        pytest.param(MagicMock(username=""), id="empty-username"),
    ],
)
async def test_resolve_channel_username_returns_none_without_username(mock_telegram_client, entity):
    mock_telegram_client.get_entity.return_value = entity

    assert await resolve_channel_username(CHANNEL_ID) is None
    assert alerts_main.channel_usernames == {}


@pytest.mark.asyncio
async def test_resolve_channel_username_survives_lookup_failure(mock_telegram_client, caplog):
    caplog.set_level(logging.WARNING)
    mock_telegram_client.get_entity.side_effect = ConnectionError("no route")

    assert await resolve_channel_username(CHANNEL_ID) is None
    assert f"Failed to resolve username for channel {CHANNEL_ID}" in caplog.text


@pytest.mark.asyncio
async def test_broadcast_reference_uses_the_public_username(mock_telegram_client):
    mock_telegram_client.get_entity.return_value = MagicMock(username="kyiv_alert")

    assert await broadcast_reference(CHANNEL_ID, MagicMock(id=77)) == (
        77,
        "https://t.me/kyiv_alert/77",
    )


@pytest.mark.asyncio
async def test_broadcast_reference_without_message_id(mock_telegram_client, caplog):
    caplog.set_level(logging.WARNING)

    assert await broadcast_reference(CHANNEL_ID, None) == (None, None)
    assert f"Broadcast to channel {CHANNEL_ID} returned no message id" in caplog.text
    mock_telegram_client.get_entity.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_alert_stores_the_broadcast_message_link(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    _, mock_conn = mock_pg_pool
    mock_telegram_client.send_message.return_value = MagicMock(id=321)
    mock_telegram_client.get_entity.return_value = MagicMock(username="kyiv_alert")
    link = "https://t.me/kyiv_alert/321"

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    for key in ("threat:alerts:city:kyiv", "threat:alerts:kyiv"):
        calls = [c for c in mock_redis.hset.call_args_list if c.args and c.args[0] == key]
        assert calls[0].kwargs["mapping"]["source"] == link

    _, *params = mock_conn.execute.call_args.args
    assert params[6] == CHANNEL_ID
    assert params[7] == 321
    assert params[8] == link


@pytest.mark.asyncio
async def test_send_alert_stores_the_shelling_message_link(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_telegram_client.send_message.return_value = MagicMock(id=15)
    mock_telegram_client.get_entity.return_value = MagicMock(username="nikopol_alert")

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "nikopol", "threat_of_shelling")
        await _drain_background_tasks()

    calls = [
        c
        for c in mock_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:shellings:nikopol"
    ]
    assert calls[0].kwargs["mapping"]["source"] == "https://t.me/nikopol_alert/15"


@pytest.mark.asyncio
async def test_send_alert_falls_back_to_a_private_link_without_username(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_telegram_client.send_message.return_value = MagicMock(id=9)
    mock_telegram_client.get_entity.return_value = MagicMock(username=None)

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(-1001712561448, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    calls = [
        c
        for c in mock_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:kyiv"
    ]
    assert calls[0].kwargs["mapping"]["source"] == "https://t.me/c/1712561448/9"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "region, alert_type, expected_status",
    [
        ("kyiv", "air_raid_alert", "true"),
        ("kyiv", "air_raid_alert_cancelled", "false"),
        ("nikopol", "threat_of_shelling", "true"),
        ("nikopol", "threat_of_shelling_cancelled", "false"),
    ],
)
async def test_send_alert_writes_state_history_and_broadcasts(
    mock_redis, mock_pg_pool, mock_telegram_client, region, alert_type, expected_status
):
    _, mock_conn = mock_pg_pool
    oblast = REGION_CONFIG[region]["oblast"]

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, region, alert_type)
        await _drain_background_tasks()

    mock_redis.set.assert_any_await(f"channel_state:{CHANNEL_ID}", alert_type)
    mock_redis.set.assert_any_await(
        alerts_main.LAST_BROADCAST_AT_KEY, str(int(alerts_main.last_broadcast_at))
    )
    assert alerts_main.last_broadcast_at is not None

    if "shelling" in alert_type:
        mock_redis.hset.assert_any_call(
            f"threat:shellings:{region}",
            mapping={
                "status": expected_status,
                "time": mock_redis.hset.call_args_list[0].kwargs["mapping"]["time"],
                "source": "telegram",
                "updated_at": mock_redis.hset.call_args_list[0].kwargs["mapping"]["updated_at"],
            },
        )
    else:
        mock_redis.hset.assert_any_call(
            f"threat:alerts:city:{region}",
            mapping={
                "status": expected_status,
                "time": mock_redis.hset.call_args_list[0].kwargs["mapping"]["time"],
                "source": "telegram",
                "type": alert_type,
                "updated_at": mock_redis.hset.call_args_list[0].kwargs["mapping"]["updated_at"],
            },
        )

    mock_conn.execute.assert_awaited_once()
    sql, *params = mock_conn.execute.call_args.args
    assert "INSERT INTO alert_history" in sql
    assert params[3] == region
    assert params[4] == oblast
    assert params[5] == alert_type

    mock_telegram_client.send_message.assert_awaited_once_with(CHANNEL_ID, MESSAGES[alert_type])

    mock_photo.assert_awaited_once_with(CHANNEL_ID, region, alert_type)
    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_send_alert_skips_duplicate_when_state_unchanged(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.INFO)
    mock_redis.set.return_value = "air_raid_alert"

    await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")

    mock_redis.set.assert_awaited_once_with(
        f"channel_state:{CHANNEL_ID}", "air_raid_alert", get=True
    )
    mock_redis.hset.assert_not_awaited()
    mock_telegram_client.send_message.assert_not_awaited()
    assert "Duplicate air_raid_alert ignored for Nikopol" in caplog.text


@pytest.mark.asyncio
async def test_send_alert_processes_state_change_after_duplicate_suppression(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_redis.set.return_value = "air_raid_alert"

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert_cancelled")
        await _drain_background_tasks()

    mock_redis.set.assert_any_await(f"channel_state:{CHANNEL_ID}", "air_raid_alert_cancelled")
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES["air_raid_alert_cancelled"]
    )


@pytest.mark.asyncio
async def test_send_alert_broadcasts_when_redis_is_down(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)
    mock_redis.set.side_effect = ConnectionError("Redis is down")

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")
        await _drain_background_tasks()

    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES["air_raid_alert"]
    )
    assert "Redis unavailable for Nikopol" in caplog.text


@pytest.mark.asyncio
async def test_send_alert_unknown_type_does_nothing(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)

    await send_alert(CHANNEL_ID, "kyiv", "unknown_type")

    assert "Unknown alert type: unknown_type" in caplog.text
    mock_redis.set.assert_not_awaited()
    mock_redis.hset.assert_not_awaited()
    mock_telegram_client.send_message.assert_not_awaited()
    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_send_alert_still_broadcasts_when_pg_insert_fails(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)
    _, mock_conn = mock_pg_pool
    mock_conn.execute.side_effect = Exception("DB Error")

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    assert "Failed to insert alert history into PG: DB Error" in caplog.text
    mock_redis.hset.assert_called()
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES["air_raid_alert"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alert_type, expected_log",
    [
        ("air_raid_alert", "Failed to send air raid alert to Kyiv"),
        ("air_raid_alert_cancelled", "Failed to send air raid alert cancellation to Kyiv"),
        ("threat_of_shelling", "Failed to send threat of shelling to Kyiv"),
    ],
)
async def test_send_alert_logs_but_survives_send_failure(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog, alert_type, expected_log
):
    caplog.set_level(logging.ERROR)
    mock_telegram_client.send_message.side_effect = Exception("network down")

    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, "kyiv", alert_type)
        await _drain_background_tasks()

    assert expected_log in caplog.text
    mock_photo.assert_not_awaited()
    assert alerts_main.last_broadcast_at is None

    # The claim goes in before the send, so a failed send has to hand it back
    # rather than leave the channel holding a state nobody heard announced.
    mock_redis.set.assert_awaited_once_with(f"channel_state:{CHANNEL_ID}", alert_type, get=True)
    restore_args = mock_redis.eval.await_args.args
    assert restore_args[2:4] == (f"channel_state:{CHANNEL_ID}", alert_type)


@pytest.mark.asyncio
async def test_send_alert_skips_photo_update_without_mapping(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.DEBUG)

    with (
        patch.dict("alerts.main.CHANNEL_PHOTO_PATHS", clear=True),
        patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock) as mock_photo,
    ):
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    mock_telegram_client.send_message.assert_awaited_once()
    mock_photo.assert_not_awaited()
    assert "No photo mapping for 'air_raid_alert'" in caplog.text
    assert alerts_main.running_tasks == set()


ALL_REGION_CHANNELS = {region: 9000 + i for i, region in enumerate(REGION_CONFIG)}

SOURCE_CHANNEL = real_source_channels["primary"]
SOURCE_USERNAME = "air_alert_ua"
SOURCE_MESSAGE_ID = 500
SOURCE_LINK = f"https://t.me/{SOURCE_USERNAME}/{SOURCE_MESSAGE_ID}"


class Dispatched(NamedTuple):
    """Two parser outputs: broadcast to channels and map-only records."""

    broadcast: list
    recorded: list


async def _dispatch(message_text, region_channels=ALL_REGION_CHANNELS):
    handler = build_message_handler(region_channels)
    event = MagicMock()
    event.message.message = message_text
    event.message.id = SOURCE_MESSAGE_ID
    event.chat_id = SOURCE_CHANNEL

    with (
        patch("alerts.main.send_alert", new_callable=AsyncMock) as mock_send_alert,
        patch("alerts.main.record_map_only_alert", new_callable=AsyncMock) as mock_record,
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock) as mock_username,
    ):
        mock_username.return_value = SOURCE_USERNAME
        await handler(event)
        await _drain_background_tasks()

    assert alerts_main.running_tasks == set()
    return Dispatched(
        [call.args for call in mock_send_alert.await_args_list],
        [call.args for call in mock_record.await_args_list],
    )


def _expected_calls(regions, alert_type):
    return [
        (ALL_REGION_CHANNELS[region], region, alert_type)
        for region in REGION_CONFIG
        if region in regions
    ]


def _expected_records(districts, alert_type):
    return [
        (district, alert_type, SOURCE_MESSAGE_ID, SOURCE_LINK)
        for district in DISTRICT_CONFIG
        if district in districts
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message_text, expected_calls",
    [
        pytest.param(
            "м. Київ Повітряна тривога",
            [(1111, "kyiv", "air_raid_alert")],
            id="kyiv-fallback-alert",
        ),
        pytest.param(
            "Київ Повітряна тривога",
            [(1111, "kyiv", "air_raid_alert")],
            id="kyiv-without-m-alert",
        ),
        pytest.param(
            "м. Київ Відбій тривоги",
            [(1111, "kyiv", "air_raid_alert_cancelled")],
            id="kyiv-fallback-cancellation",
        ),
        pytest.param(
            "м. Нікополь артилерійський обстріл",
            [(2222, "nikopol", "threat_of_shelling")],
            id="nikopol-alert-triggers",
        ),
        pytest.param(
            "м. Нікополь Відбій загрози артобстрілу",
            [(2222, "nikopol", "threat_of_shelling_cancelled")],
            id="nikopol-shelling-cancellation",
        ),
        pytest.param(
            "🚨 Нікополь (Дніпропетровська обл.)\nПовітряна тривога. Прямуйте в укриття",
            [(2222, "nikopol", "air_raid_alert")],
            id="nikopol-without-m-with-oblast-abbr",
        ),
        pytest.param("Some random text", [], id="no-region-match"),
        pytest.param("м. Київ погода сьогодні гарна", [], id="region-without-alert-keyword"),
    ],
)
async def test_build_message_handler_dispatches_correct_alert(message_text, expected_calls):
    assert (
        await _dispatch(message_text, {"kyiv": 1111, "nikopol": 2222})
    ).broadcast == expected_calls


@pytest.mark.asyncio
async def test_build_message_handler_maps_a_region_without_a_channel():
    """Without a broadcast channel, the alert is not sent to Telegram but is still recorded on the map."""
    dispatched = await _dispatch("м. Київ Повітряна тривога", {"nikopol": 2222})

    assert dispatched.broadcast == []
    assert dispatched.recorded == _expected_records(("kyiv",), "air_raid_alert")


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", ALL_SAMPLES, ids=lambda sample: sample.id)
async def test_build_message_handler_on_real_channel_messages(sample):
    assert (await _dispatch(sample.alert_message)).broadcast == _expected_calls(
        sample.regions, "air_raid_alert"
    )
    assert (await _dispatch(sample.cancellation_message)).broadcast == _expected_calls(
        sample.regions, "air_raid_alert_cancelled"
    )


def test_every_configured_region_has_a_message_sample():
    sampled = {region for sample in MESSAGES_SAMPLES for region in sample.regions}
    assert sampled == set(REGION_CONFIG)


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", PARTIAL_CANCELLATION_SAMPLES, ids=lambda sample: sample.id)
async def test_build_message_handler_ignores_still_ongoing_places(sample):
    assert (await _dispatch(sample.message)).broadcast == _expected_calls(
        sample.regions, "air_raid_alert_cancelled"
    )


@pytest.mark.parametrize("sample", PARTIAL_CANCELLATION_SAMPLES, ids=lambda sample: sample.id)
def test_partial_cancellation_samples_name_the_silenced_channels(sample):
    assert sample.silenced

    note = sample.message.split("ще триває", 1)[1]
    for region in sample.silenced:
        assert any(trigger in note for trigger in REGION_CONFIG[region]["triggers"]), (
            f"note does not name anything {region} listens for"
        )


@pytest.mark.asyncio
async def test_build_message_handler_reads_alert_type_from_the_announcement():
    message = (
        "🟡 08:01 Відбій тривоги в м. Нікополь та Нікопольська територіальна громада.\n"
        "Зверніть увагу, Повітряна тривога ще триває у:\n"
        "- Нікопольський район"
    )

    assert (await _dispatch(message, {"nikopol": 2222})).broadcast == [
        (2222, "nikopol", "air_raid_alert_cancelled")
    ]


@pytest.mark.parametrize(
    "message_text, expected",
    [
        pytest.param(
            "Відбій тривоги в м. Нікополь.\nЗверніть увагу, тривога ще триває у:\n- Нікопольський район\n#м_Нікополь",
            "Відбій тривоги в м. Нікополь.\n",
            id="drops-the-note-and-everything-after-it",
        ),
        pytest.param(
            "Відбій тривоги в м. Нікополь.\nЗверніть увагу, тривоги ще тривають в:\n- Нікопольський район",
            "Відбій тривоги в м. Нікополь.\n",
            id="tolerates-plural-and-в-wording",
        ),
        pytest.param(
            "🔴 12:00 Повітряна тривога в Нікопольський район\nСлідкуйте за подальшими повідомленнями.\n#Нікопольський_район",
            "🔴 12:00 Повітряна тривога в Нікопольський район\nСлідкуйте за подальшими повідомленнями.\n#Нікопольський_район",
            id="leaves-a-post-without-a-note-untouched",
        ),
    ],
)
def test_strip_ongoing_notice(message_text, expected):
    assert strip_ongoing_notice(message_text) == expected


@pytest.mark.asyncio
async def test_main_wires_up_clients_and_handler():
    _, expected_source, expected_fallback = get_mode_config(argparse.Namespace(mode="dev"))

    with (
        patch("alerts.main.redis.from_url") as mock_redis_from_url,
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool,
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="dev")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_redis_from_url.assert_called_once_with(REDIS_URL, decode_responses=True)
    mock_create_pool.assert_awaited_once_with(DATABASE_URL)
    mock_client_instance.start.assert_not_awaited()
    mock_client_instance.add_event_handler.assert_called_once()
    _, event_filter = mock_client_instance.add_event_handler.call_args.args
    assert set(event_filter.chats) == {cid for cid in (expected_source, expected_fallback) if cid}
    mock_client_instance.run_until_disconnected.assert_awaited_once()
    assert alerts_main.client is mock_client_instance


@pytest.mark.asyncio
async def test_main_initializes_sentry_with_mode_as_environment(monkeypatch):
    monkeypatch.setattr(alerts_main, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    with (
        patch("alerts.main.redis.from_url"),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock),
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
        patch("alerts.main.sentry_sdk.init") as mock_sentry_init,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="prod")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_sentry_init.assert_called_once()
    _, kwargs = mock_sentry_init.call_args
    assert kwargs["dsn"] == "https://examplePublicKey@o0.ingest.sentry.io/0"
    assert kwargs["environment"] == "prod"
    assert kwargs["release"] == VERSION
    assert kwargs["send_default_pii"] is False


@pytest.mark.asyncio
async def test_main_tags_events_with_its_service_name(monkeypatch):
    monkeypatch.setattr(alerts_main, "SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")

    with (
        patch("alerts.main.redis.from_url"),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock),
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
        patch("alerts.main.sentry_sdk.init"),
        patch("alerts.main.sentry_sdk.set_tag") as mock_set_tag,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="prod")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_set_tag.assert_called_once_with("service", "alerts")


@pytest.mark.asyncio
async def test_main_starts_interactive_login_when_not_authorized():
    with (
        patch("alerts.main.redis.from_url"),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock),
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="dev")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = False
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_client_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_survives_backend_connection_failures(caplog):
    caplog.set_level(logging.ERROR)

    with (
        patch("alerts.main.redis.from_url", side_effect=Exception("redis down")),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock) as mock_create_pool,
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
    ):
        mock_create_pool.side_effect = Exception("pg down")
        mock_get_args.return_value = argparse.Namespace(mode="dev")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    assert "Failed to connect to Redis: redis down" in caplog.text
    assert "Failed to connect to PostgreSQL: pg down" in caplog.text
    mock_client_instance.run_until_disconnected.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_logs_critical_on_fatal_session_error(caplog):
    caplog.set_level(logging.CRITICAL)

    with (
        patch("alerts.main.redis.from_url"),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock),
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="dev")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()
        mock_client_instance.run_until_disconnected.side_effect = AuthKeyDuplicatedError(
            request=MagicMock()
        )

        with patch("alerts.main._ping_healthcheck") as mock_ping:
            with pytest.raises(AuthKeyDuplicatedError):
                await main()

    assert "Telegram session is invalid" in caplog.text
    assert "./deploy/setup.sh" in caplog.text
    mock_ping.assert_called_once_with("/fail")


@pytest.mark.asyncio
async def test_main_logs_error_on_transient_connection_error(caplog):
    caplog.set_level(logging.ERROR)

    with (
        patch("alerts.main.redis.from_url"),
        patch("alerts.main.asyncpg.create_pool", new_callable=AsyncMock),
        patch("alerts.main.ensure_pg_tables"),
        patch("alerts.main.rehydrate_state_from_db"),
        patch("alerts.main.TelegramClient") as MockClient,
        patch("alerts.main.cli.get_args") as mock_get_args,
    ):
        mock_get_args.return_value = argparse.Namespace(mode="dev")

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()
        mock_client_instance.run_until_disconnected.side_effect = ConnectionRefusedError(
            "connection refused"
        )

        with pytest.raises(ConnectionRefusedError):
            await main()

    assert "Telegram connection lost and could not be recovered" in caplog.text


def test_ping_healthcheck_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "")

    with patch("alerts.main.requests.get") as mock_get:
        alerts_main._ping_healthcheck()

    mock_get.assert_not_called()


def test_ping_healthcheck_sends_get_with_suffix(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/test-uuid"
    )

    with patch("alerts.main.requests.get") as mock_get:
        alerts_main._ping_healthcheck("/fail")

    mock_get.assert_called_once_with(
        "https://hc-ping.com/test-uuid/fail", timeout=alerts_main.HEALTHCHECK_PING_TIMEOUT
    )


def test_ping_tg_healthcheck_uses_its_own_url(monkeypatch):
    """Two ends of the pipeline have separate healthchecks and cannot swap URLs."""
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/source"
    )
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "https://hc-ping.com/broadcast"
    )

    with patch("alerts.main.requests.get") as mock_get:
        alerts_main._ping_tg_healthcheck("/fail")

    mock_get.assert_called_once_with(
        "https://hc-ping.com/broadcast/fail", timeout=alerts_main.HEALTHCHECK_PING_TIMEOUT
    )


def test_ping_healthcheck_logs_but_survives_request_failure(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/test-uuid"
    )

    with patch("alerts.main.requests.get", side_effect=Exception("network down")):
        alerts_main._ping_healthcheck()

    assert "Failed to ping healthchecks.io" in caplog.text


@pytest.mark.asyncio
async def test_record_source_message_prefers_the_post_time(mock_redis):
    posted_at = datetime.datetime(2026, 8, 23, 10, 0, tzinfo=datetime.timezone.utc)

    await alerts_main.record_source_message(posted_at)

    assert alerts_main.last_source_message_at == posted_at.timestamp()
    assert alerts_main.last_primary_message_at == posted_at.timestamp()
    mock_redis.set.assert_any_await(
        alerts_main.LAST_SOURCE_MESSAGE_KEY, str(int(posted_at.timestamp()))
    )
    mock_redis.set.assert_any_await(
        alerts_main.LAST_PRIMARY_MESSAGE_KEY, str(int(posted_at.timestamp()))
    )
    mock_redis.set.assert_any_await(alerts_main.ACTIVE_SOURCE_KEY, "primary")


@pytest.mark.asyncio
async def test_record_source_message_falls_back_to_now(mock_redis):
    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main.record_source_message(None)

    assert alerts_main.last_source_message_at == 1_700_000_000.0


@pytest.mark.asyncio
async def test_record_source_message_survives_unreachable_redis(mock_redis, caplog):
    caplog.set_level(logging.WARNING)
    mock_redis.set.side_effect = Exception("redis down")

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main.record_source_message(None)

    assert alerts_main.last_source_message_at == 1_700_000_000.0
    assert "Failed to store the source message timestamp" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "",
        "Доброго вечора, ми з України",
    ],
)
async def test_handler_marks_the_source_alive_before_both_early_exits(
    mock_redis, mock_pg_pool, mock_telegram_client, message
):
    handler = build_message_handler(ALL_REGION_CHANNELS)
    event = MagicMock()
    event.message.message = message

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await handler(event)

    assert alerts_main.last_source_message_at == 1_700_000_000.0
    mock_telegram_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_silence_seconds_is_none_without_a_mark():
    assert await alerts_main._source_silence_seconds() is None


def test_silence_is_reported_once_per_episode(caplog):
    caplog.set_level(logging.INFO)
    silence = alerts_main.SOURCE_SILENCE_THRESHOLD + 60

    alerts_main._report_source_silence(silence)
    alerts_main._report_source_silence(silence + 300)

    assert caplog.text.count("No message from the source channel") == 1
    assert alerts_main.source_silence_reported is True


def test_returning_source_closes_the_episode(caplog):
    caplog.set_level(logging.INFO)
    alerts_main._report_source_silence(alerts_main.SOURCE_SILENCE_THRESHOLD + 60)
    caplog.clear()

    alerts_main._report_source_silence(10)

    assert "The source channel is posting again" in caplog.text
    assert alerts_main.source_silence_reported is False


class _StopLoop(Exception):
    """Exit from the infinite loop on the second iteration."""


async def _run_one_cycle(coro):
    """Run exactly one loop iteration using a mocked sleep."""
    with patch("alerts.main.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_sleep.side_effect = [None, _StopLoop]
        with pytest.raises(_StopLoop):
            await coro


@pytest.mark.asyncio
async def test_healthcheck_loop_keeps_watching_without_a_ping_url(monkeypatch, caplog):
    """The loop continues running when healthchecks ping URL is absent."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "")
    alerts_main.last_source_message_at = 0.0
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    await _run_one_cycle(alerts_main._healthcheck_loop(mock_client))

    assert "HEALTHCHECKS_ALERTS_SOURCE_PING_URL not set" in caplog.text
    assert "No message from the source channel" in caplog.text


@pytest.mark.asyncio
async def test_healthcheck_loop_pings_while_the_source_is_fresh(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/test-uuid"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        alerts_main.last_source_message_at = 1_700_000_000.0 - 60
        with patch("alerts.main._ping_healthcheck") as mock_ping:
            await _run_one_cycle(alerts_main._healthcheck_loop(mock_client))

    assert mock_ping.call_args_list
    assert all(call.args == () for call in mock_ping.call_args_list)


@pytest.mark.asyncio
async def test_healthcheck_loop_fails_the_check_on_silence(monkeypatch):
    """Extended silence triggers an explicit /fail ping."""
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/test-uuid"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        alerts_main.last_source_message_at = (
            1_700_000_000.0 - alerts_main.SOURCE_SILENCE_THRESHOLD - 1
        )
        with patch("alerts.main._ping_healthcheck") as mock_ping:
            await _run_one_cycle(alerts_main._healthcheck_loop(mock_client))

    assert mock_ping.call_args_list
    assert all(call.args == ("/fail",) for call in mock_ping.call_args_list)


@pytest.mark.asyncio
async def test_healthcheck_loop_skips_ping_when_disconnected(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/test-uuid"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = False

    with patch("alerts.main._ping_healthcheck") as mock_ping:
        await _run_one_cycle(alerts_main._healthcheck_loop(mock_client))

    mock_ping.assert_not_called()


@pytest.mark.asyncio
async def test_record_broadcast_stores_timestamp_on_success(mock_redis):
    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main.record_broadcast(True)

    assert alerts_main.last_broadcast_at == 1_700_000_000.0
    mock_redis.set.assert_awaited_once_with(alerts_main.LAST_BROADCAST_AT_KEY, "1700000000")


@pytest.mark.asyncio
async def test_record_broadcast_ignores_failure(mock_redis):
    alerts_main.last_broadcast_at = 1_700_000_000.0

    await alerts_main.record_broadcast(False)

    assert alerts_main.last_broadcast_at == 1_700_000_000.0
    mock_redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_broadcast_keeps_timestamp_without_redis():
    """The broadcast timestamp is preserved in memory even if Redis is completely unavailable."""
    alerts_main.redis_client = None

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main.record_broadcast(True)

    assert alerts_main.last_broadcast_at == 1_700_000_000.0


@pytest.mark.asyncio
async def test_record_broadcast_survives_unreachable_redis(mock_redis, caplog):
    caplog.set_level(logging.WARNING)
    mock_redis.set.side_effect = Exception("redis down")

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main.record_broadcast(True)

    assert alerts_main.last_broadcast_at == 1_700_000_000.0
    assert "Failed to store the broadcast timestamp in Redis" in caplog.text


@pytest.mark.asyncio
async def test_broadcast_watchdog_keeps_watching_without_a_ping_url(monkeypatch, caplog):
    """The watchdog loop continues running when healthchecks ping URL is absent."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(alerts_main, "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "")
    alerts_main.last_broadcast_at = 0.0
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    await _run_one_cycle(alerts_main._broadcast_watchdog_loop(mock_client))

    assert "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL not set" in caplog.text
    assert "No alerts broadcasted" in caplog.text


@pytest.mark.asyncio
async def test_broadcast_watchdog_pings_while_broadcast_is_fresh(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "https://hc-ping.com/tg"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        alerts_main.last_broadcast_at = 1_700_000_000.0 - 60
        with patch("alerts.main._ping_tg_healthcheck") as mock_ping:
            await _run_one_cycle(alerts_main._broadcast_watchdog_loop(mock_client))

    assert mock_ping.call_args_list
    assert all(call.args == () for call in mock_ping.call_args_list)


@pytest.mark.asyncio
async def test_broadcast_watchdog_fails_the_check_on_silence(monkeypatch):
    """Broadcast silence triggers an explicit /fail ping."""
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "https://hc-ping.com/tg"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        alerts_main.last_broadcast_at = (
            1_700_000_000.0 - alerts_main.BROADCAST_SILENCE_THRESHOLD - 1
        )
        with patch("alerts.main._ping_tg_healthcheck") as mock_ping:
            await _run_one_cycle(alerts_main._broadcast_watchdog_loop(mock_client))

    assert mock_ping.call_args_list
    assert all(call.args == ("/fail",) for call in mock_ping.call_args_list)


@pytest.mark.asyncio
async def test_broadcast_watchdog_skips_ping_when_disconnected(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "https://hc-ping.com/tg"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = False

    with patch("alerts.main._ping_tg_healthcheck") as mock_ping:
        await _run_one_cycle(alerts_main._broadcast_watchdog_loop(mock_client))

    mock_ping.assert_not_called()


@pytest.mark.asyncio
async def test_prime_restores_the_clock_from_redis(mock_redis, mock_telegram_client):
    """Worker restarts should restore the silence timer from Redis."""
    mock_redis.get.side_effect = lambda key: {
        alerts_main.LAST_SOURCE_MESSAGE_KEY: "1700000000",
        alerts_main.LAST_BROADCAST_AT_KEY: "1699990000",
    }.get(key)

    await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_source_message_at == 1_700_000_000.0
    assert alerts_main.last_broadcast_at == 1_699_990_000.0
    mock_telegram_client.get_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_prime_starts_broadcast_clock_from_now_when_redis_is_empty(
    mock_redis, mock_telegram_client
):
    mock_redis.get.return_value = None
    mock_telegram_client.get_messages.return_value = []

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_broadcast_at == 1_700_000_000.0
    assert alerts_main.last_source_message_at == 1_700_000_000.0


@pytest.mark.asyncio
async def test_prime_asks_telegram_when_redis_is_empty(mock_redis, mock_telegram_client):
    posted_at = datetime.datetime(2026, 8, 23, 10, 0, tzinfo=datetime.timezone.utc)
    mock_redis.get.return_value = None
    mock_telegram_client.get_messages.return_value = [MagicMock(date=posted_at)]

    await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_source_message_at == posted_at.timestamp()
    mock_telegram_client.get_messages.assert_awaited_once_with(SOURCE_CHANNEL, limit=1)


@pytest.mark.asyncio
async def test_prime_starts_the_clock_from_now_as_a_last_resort(
    mock_redis, mock_telegram_client, caplog
):
    """Initializes the clock from current time if no persisted timestamp is found."""
    caplog.set_level(logging.WARNING)
    mock_redis.get.return_value = None
    mock_telegram_client.get_messages.side_effect = Exception("telegram down")

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_source_message_at == 1_700_000_000.0
    assert "Starting the silence clock from now" in caplog.text


@pytest.mark.asyncio
async def test_prime_ignores_a_malformed_stored_mark(mock_redis, mock_telegram_client, caplog):
    caplog.set_level(logging.WARNING)
    mock_redis.get.side_effect = lambda key: (
        "не число" if key == alerts_main.LAST_SOURCE_MESSAGE_KEY else None
    )
    mock_telegram_client.get_messages.return_value = []

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert "malformed" in caplog.text
    assert alerts_main.last_source_message_at == 1_700_000_000.0


@pytest.mark.asyncio
async def test_prime_survives_unreachable_redis(mock_redis, mock_telegram_client, caplog):
    caplog.set_level(logging.WARNING)
    mock_redis.get.side_effect = Exception("redis down")
    mock_telegram_client.get_messages.return_value = []

    with patch("alerts.main.time.time", return_value=1_700_000_000.0):
        await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert "Redis unreachable while restoring monitoring state" in caplog.text
    assert alerts_main.last_source_message_at == 1_700_000_000.0


@pytest.mark.asyncio
async def test_prime_restores_last_alert_from_redis_for_broadcast_district(
    mock_redis, mock_telegram_client
):
    saved_alert = {
        "type": "air_raid_alert",
        "region": "kyiv",
        "district": "kyiv",
        "location_name": "Київ",
        "locative": "у Києві",
        "timestamp": "2026-08-27T12:00:00+00:00",
        "message_id": 100,
        "message_link": "https://t.me/sirens_kyiv/100",
    }
    mock_redis.get.side_effect = lambda key: {
        alerts_main.LAST_ALERT_INFO_KEY: json.dumps(saved_alert),
    }.get(key)

    alerts_main.last_alert_payload = None
    await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_alert_payload == saved_alert


@pytest.mark.asyncio
async def test_prime_ignores_map_only_district_in_redis_and_falls_back_to_pg(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    _, mock_conn = mock_pg_pool
    map_only_alert = {
        "type": "air_raid_alert",
        "region": "kyiv_oblast",
        "district": "vyshhorod",
        "location_name": "Вишгородський район",
    }
    mock_redis.get.side_effect = lambda key: {
        alerts_main.LAST_ALERT_INFO_KEY: json.dumps(map_only_alert),
    }.get(key)

    posted_dt = datetime.datetime(2026, 8, 27, 10, 0, tzinfo=datetime.timezone.utc)
    mock_conn.fetchrow.return_value = {
        "datetime": posted_dt,
        "district_key": "bilatserkva",
        "oblast_key": "kyiv_oblast",
        "type": "air_raid_alert",
        "message_id": 555,
        "message_link": "https://t.me/sirens_bc/555",
    }

    alerts_main.last_alert_payload = None
    await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    sql = mock_conn.fetchrow.call_args[0][0]
    assert "WHERE channel_id IS NOT NULL" in sql
    assert alerts_main.last_alert_payload["district"] == "bilatserkva"
    assert alerts_main.last_alert_payload["location_name"] == "Біла Церква"


@pytest.mark.asyncio
async def test_prime_pg_query_filters_only_broadcast_alerts(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    _, mock_conn = mock_pg_pool
    mock_redis.get.return_value = None
    posted_dt = datetime.datetime(2026, 8, 27, 11, 0)
    mock_conn.fetchrow.return_value = {
        "datetime": posted_dt,
        "district_key": "kharkiv",
        "oblast_key": "kharkiv_oblast",
        "type": "air_raid_alert_cancelled",
        "message_id": 777,
        "message_link": "https://t.me/sirens_kh/777",
    }

    alerts_main.last_alert_payload = None
    await alerts_main._prime_monitoring_state(SOURCE_CHANNEL)

    assert alerts_main.last_alert_payload["district"] == "kharkiv"
    assert alerts_main.last_alert_payload["location_name"] == "Харків"
    assert alerts_main.last_alert_payload["locative"] == "у Харкові"


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", MAP_ONLY_SAMPLES, ids=lambda sample: sample.id)
async def test_build_message_handler_records_districts_without_a_channel(sample):
    alert = await _dispatch(sample.alert_message)
    assert alert.recorded == _expected_records(sample.recorded, "air_raid_alert")
    assert alert.broadcast == _expected_calls(sample.broadcast, "air_raid_alert")

    cancellation = await _dispatch(sample.cancellation_message)
    assert cancellation.recorded == _expected_records(sample.recorded, "air_raid_alert_cancelled")
    assert cancellation.broadcast == _expected_calls(sample.broadcast, "air_raid_alert_cancelled")


@pytest.mark.asyncio
async def test_build_message_handler_points_map_only_districts_at_the_source_post():
    """Map-only districts reference the original source message."""
    dispatched = await _dispatch("Вишгородський район Повітряна тривога")

    assert dispatched.recorded == [("vyshhorod", "air_raid_alert", SOURCE_MESSAGE_ID, SOURCE_LINK)]


@pytest.mark.asyncio
async def test_build_message_handler_skips_the_source_lookup_when_all_districts_broadcast():
    """Broadcast districts use their own message links and skip resolving source username."""
    handler = build_message_handler(ALL_REGION_CHANNELS)
    event = MagicMock()
    event.message.message = "Бучанський район Повітряна тривога"
    event.message.id = SOURCE_MESSAGE_ID
    event.chat_id = SOURCE_CHANNEL

    with (
        patch("alerts.main.send_alert", new_callable=AsyncMock),
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock) as mock_username,
    ):
        await handler(event)
        await _drain_background_tasks()

    mock_username.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "oblast_key, oblast_name",
    [
        ("poltava_oblast", "Полтавська область"),
        ("kyiv_oblast", "Київська область"),
    ],
)
async def test_build_message_handler_raises_the_whole_oblast_from_its_name(oblast_key, oblast_name):
    """An oblast-level alert activates all constituent districts."""
    dispatched = await _dispatch(oblast_message(oblast_name))

    touched = {call[1] for call in dispatched.broadcast} | {call[0] for call in dispatched.recorded}
    assert touched == set(DISTRICTS_BY_OBLAST[oblast_key])


@pytest.mark.asyncio
async def test_source_reference_builds_a_public_link(mock_telegram_client):
    mock_telegram_client.get_entity.return_value = MagicMock(username=SOURCE_USERNAME)
    event = MagicMock(chat_id=SOURCE_CHANNEL)
    event.message.id = SOURCE_MESSAGE_ID

    assert await source_reference(event) == (SOURCE_MESSAGE_ID, SOURCE_LINK)


@pytest.mark.asyncio
async def test_source_reference_without_an_id(caplog, mock_telegram_client):
    caplog.set_level(logging.WARNING)

    assert await source_reference(MagicMock(chat_id=None)) == (None, None)
    assert "Source message has no id" in caplog.text
    mock_telegram_client.get_entity.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_map_only_alert_writes_state_without_broadcasting(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    _, mock_conn = mock_pg_pool

    await record_map_only_alert("vyshhorod", "air_raid_alert", SOURCE_MESSAGE_ID, SOURCE_LINK)
    await _drain_background_tasks()

    mock_telegram_client.send_message.assert_not_awaited()
    mock_redis.set.assert_any_await("district_state:vyshhorod", "air_raid_alert")

    city = [
        call
        for call in mock_redis.hset.call_args_list
        if call.args and call.args[0] == "threat:alerts:city:vyshhorod"
    ]
    assert city[0].kwargs["mapping"]["status"] == "true"
    assert city[0].kwargs["mapping"]["source"] == SOURCE_LINK
    mock_redis.sadd.assert_awaited_once_with("threat:alerts:active:kyiv_oblast", "vyshhorod")

    _, *params = mock_conn.execute.call_args.args
    assert params[3:6] == ["vyshhorod", "kyiv_oblast", "air_raid_alert"]
    assert params[6] is None
    assert params[7] == SOURCE_MESSAGE_ID
    assert params[8] == SOURCE_LINK

    assert not any(
        call.args and call.args[0] == alerts_main.LAST_ALERT_INFO_KEY
        for call in mock_redis.set.call_args_list
    )

    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_record_map_only_alert_skips_duplicates(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.INFO)
    mock_redis.set.return_value = "air_raid_alert"

    await record_map_only_alert("vyshhorod", "air_raid_alert")

    mock_redis.set.assert_awaited_once_with("district_state:vyshhorod", "air_raid_alert", get=True)
    mock_redis.hset.assert_not_awaited()
    assert "Duplicate air_raid_alert ignored for Вишгородський район" in caplog.text


@pytest.mark.asyncio
async def test_record_map_only_alert_records_after_duplicate_suppression(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_redis.set.return_value = "air_raid_alert"

    await record_map_only_alert("vyshhorod", "air_raid_alert_cancelled")

    mock_redis.set.assert_any_await("district_state:vyshhorod", "air_raid_alert_cancelled")
    mock_redis.srem.assert_awaited_once_with("threat:alerts:active:kyiv_oblast", "vyshhorod")


@pytest.mark.asyncio
async def test_record_map_only_alert_unknown_type_does_nothing(mock_redis, mock_pg_pool, caplog):
    caplog.set_level(logging.ERROR)

    await record_map_only_alert("vyshhorod", "unknown_type")

    assert "Unknown alert type: unknown_type" in caplog.text
    mock_redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_map_only_alert_survives_a_redis_outage(mock_redis, mock_pg_pool, caplog):
    caplog.set_level(logging.ERROR)
    mock_redis.set.side_effect = ConnectionError("Redis is down")
    _, mock_conn = mock_pg_pool

    await record_map_only_alert("vyshhorod", "air_raid_alert")

    assert "Redis unavailable for Вишгородський район" in caplog.text
    mock_conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_alert_updates_telemetry_payload_and_redis(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    alerts_main.last_alert_payload = None
    with patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "bilatserkva", "air_raid_alert")
        await _drain_background_tasks()

    assert alerts_main.last_alert_payload is not None
    assert alerts_main.last_alert_payload["district"] == "bilatserkva"
    assert alerts_main.last_alert_payload["location_name"] == "Біла Церква"
    assert alerts_main.last_alert_payload["locative"] == "у Білій Церкві"
    assert alerts_main.last_alert_payload["type"] == "air_raid_alert"

    redis_alert_calls = [
        call
        for call in mock_redis.set.call_args_list
        if call.args and call.args[0] == alerts_main.LAST_ALERT_INFO_KEY
    ]
    assert len(redis_alert_calls) == 1
    saved_data = json.loads(redis_alert_calls[0].args[1])
    assert saved_data["district"] == "bilatserkva"
    assert saved_data["location_name"] == "Біла Церква"


@pytest.mark.asyncio
async def test_record_map_only_alert_does_not_update_telemetry_payload_or_redis(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    initial_payload = {
        "type": "air_raid_alert",
        "region": "kyiv",
        "district": "kyiv",
        "location_name": "Київ",
        "locative": "у Києві",
        "timestamp": "2026-08-27T10:00:00+00:00",
    }
    alerts_main.last_alert_payload = initial_payload

    await record_map_only_alert("vyshhorod", "air_raid_alert", SOURCE_MESSAGE_ID, SOURCE_LINK)
    await _drain_background_tasks()

    assert alerts_main.last_alert_payload == initial_payload
    assert not any(
        call.args and call.args[0] == alerts_main.LAST_ALERT_INFO_KEY
        for call in mock_redis.set.call_args_list
    )


@pytest.mark.parametrize(
    "message_text, expected",
    [
        pytest.param(
            "Повітряна тривога в Бучанський район",
            {"bucha": "air_raid_alert"},
            id="single-district",
        ),
        pytest.param(
            "Відбій тривоги в Бучанський район",
            {"bucha": "air_raid_alert_cancelled"},
            id="cancellation",
        ),
        pytest.param(
            "Повітряна тривога в\n• Бучанський район\n• Вишгородський район",
            {"bucha": "air_raid_alert", "vyshhorod": "air_raid_alert"},
            id="two-districts",
        ),
        pytest.param("Бучанський район", {}, id="no-alert-keyword"),
        pytest.param("Повітряна тривога в Атлантида", {}, id="unknown-place"),
    ],
)
def test_match_districts(message_text, expected):
    assert match_districts(message_text) == expected


@pytest.mark.parametrize(
    "name, expected_key",
    [
        pytest.param("Кам'янський район", "kamianske", id="straight-apostrophe"),
        pytest.param("Кам’янський район", "kamianske", id="curly-apostrophe"),
        pytest.param("Новоград-Волинський район", "zviahel", id="former-name"),
        pytest.param("Звягельський район", "zviahel", id="current-name"),
        pytest.param("Новомосковський район", "samar", id="former-name-samar"),
        pytest.param("Харків", "kharkiv", id="kharkiv-without-m"),
        pytest.param("м. Харків", "kharkiv", id="kharkiv-with-m"),
        pytest.param("Запоріжжя", "zaporizhzhia", id="zaporizhzhia-without-m"),
        pytest.param("м. Запоріжжя", "zaporizhzhia", id="zaporizhzhia-with-m"),
        pytest.param("Нікополь", "nikopol", id="nikopol-without-m"),
        pytest.param("м. Нікополь", "nikopol", id="nikopol-with-m"),
        pytest.param("Київ", "kyiv", id="kyiv-without-m"),
        pytest.param("м. Київ", "kyiv", id="kyiv-with-m"),
    ],
)
def test_match_districts_accepts_every_spelling(name, expected_key):
    assert match_districts(f"Повітряна тривога в {name}") == {expected_key: "air_raid_alert"}


@pytest.mark.parametrize(
    "name, expected_key",
    [
        pytest.param(
            "Кам'янець-Подільський район", "kamianetspodilskyi", id="kamianets-not-podilsk"
        ),
        pytest.param("Могилів-Подільський район", "mohylivpodilskyi", id="mohyliv-not-podilsk"),
        pytest.param("Подільський район", "podilsk", id="podilsk-itself"),
        pytest.param(
            "Білгород-Дністровський район", "bilhoroddnistrovskyi", id="bilhorod-not-dnistrovskyi"
        ),
        pytest.param("Дністровський район", "dnistrovskyi", id="dnistrovskyi-itself"),
    ],
)
def test_match_districts_does_not_match_inside_a_longer_name(name, expected_key):
    """District matching respects word boundaries to avoid substring false positives."""
    assert match_districts(f"Повітряна тривога в {name}") == {expected_key: "air_raid_alert"}


def test_match_districts_from_the_oblast_name():
    assert match_districts(oblast_message("Полтавська область")) == {
        key: "air_raid_alert" for key in DISTRICTS_BY_OBLAST["poltava_oblast"]
    }


STACKED_HEADERS_MESSAGE = (
    "🚨 Повітряна тривога\n"
    "Бучанський район (Київська обл.)\n"
    "\n"
    "🟢 Відбій тривоги\n"
    "Охтирський район (Сумська обл.)\n"
    "Кам'янський район (Дніпропетровська обл.)\n"
    "Самарівський район (Дніпропетровська обл."
)


def test_split_alert_sections_splits_on_standalone_header_lines():
    sections = split_alert_sections(STACKED_HEADERS_MESSAGE)

    assert len(sections) == 2
    assert "Повітряна тривога" in sections[0]
    assert "Бучанський район" in sections[0]
    assert "Відбій тривоги" not in sections[0]
    assert "Відбій тривоги" in sections[1]
    assert "Охтирський район" in sections[1]
    assert "Кам'янський район" in sections[1]
    assert "Самарівський район" in sections[1]


def test_split_alert_sections_leaves_a_single_section_message_untouched():
    message = "🔴 04:31 Повітряна тривога в м. Київ\nСлідкуйте за подальшими повідомленнями."
    assert split_alert_sections(message) == [message]


def test_match_districts_keeps_stacked_sections_apart():
    """A post stacking a standalone alert header and a standalone cancellation
    header must not let 'Повітряна тривога' (found first in the whole text)
    leak its alert type onto the districts listed under 'Відбій тривоги'."""
    assert match_districts(STACKED_HEADERS_MESSAGE) == {
        "bucha": "air_raid_alert",
        "okhtyrka": "air_raid_alert_cancelled",
        "kamianske": "air_raid_alert_cancelled",
        "samar": "air_raid_alert_cancelled",
    }


@pytest.mark.asyncio
async def test_build_message_handler_dispatches_stacked_sections_separately():
    dispatched = await _dispatch(
        STACKED_HEADERS_MESSAGE,
        {"bucha": 1111, "okhtyrka": 2222, "kamianske": 3333, "samar": 4444},
    )

    assert set(dispatched.broadcast) == {
        (1111, "bucha", "air_raid_alert"),
        (2222, "okhtyrka", "air_raid_alert_cancelled"),
        (3333, "kamianske", "air_raid_alert_cancelled"),
        (4444, "samar", "air_raid_alert_cancelled"),
    }


@pytest.fixture(autouse=True)
def _forget_reported_districts():
    alerts_main.reported_unknown_districts.clear()
    yield
    alerts_main.reported_unknown_districts.clear()


def test_log_unrecognised_districts_names_the_stranger(caplog):
    caplog.set_level(logging.WARNING)

    log_unrecognised_districts("Повітряна тривога в Бучанський район, Вигаданий район")

    assert "Вигаданий район" in caplog.text
    assert "Бучанський район" not in caplog.text


def test_log_unrecognised_districts_reports_each_name_once(caplog):
    """Unrecognised district names are logged and reported to Sentry only once."""
    caplog.set_level(logging.WARNING)
    log_unrecognised_districts("Повітряна тривога в Бахчисарайський район")
    caplog.clear()

    log_unrecognised_districts("Відбій тривоги в Бахчисарайський район")

    assert caplog.text == ""


def test_log_unrecognised_districts_stays_quiet_on_a_known_post(caplog):
    caplog.set_level(logging.WARNING)

    log_unrecognised_districts("Повітряна тривога в Кам'янець-Подільський район")

    assert caplog.text == ""


@pytest.mark.asyncio
async def test_push_telemetry_to_kv_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_ACCOUNT_ID", "")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_API_TOKEN", "")

    with patch("requests.put") as mock_put:
        await alerts_main.push_telemetry_to_kv()
        mock_put.assert_not_called()


@pytest.mark.asyncio
async def test_push_telemetry_to_kv_sends_correct_payload(monkeypatch, mock_redis):
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_ACCOUNT_ID", "acc_123")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "ns_456")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_API_TOKEN", "token_789")

    alerts_main.last_broadcast_at = 1700000000.0
    alerts_main.last_source_message_at = 1699999000.0
    alerts_main.last_alert_payload = {
        "type": "air_raid_alert",
        "region": "kyiv_oblast",
        "district": "bila_tserkva",
        "location_name": "Білоцерківський район",
        "timestamp": "2026-08-26T18:00:00+00:00",
        "message_id": 123,
        "message_link": "https://t.me/sirens_kyiv_obl/123",
    }

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    alerts_main.client = mock_client

    with patch("requests.put") as mock_put:
        await alerts_main.push_telemetry_to_kv()

        mock_put.assert_called_once()
        url, kwargs = mock_put.call_args
        assert (
            url[0]
            == "https://api.cloudflare.com/client/v4/accounts/acc_123/storage/kv/namespaces/ns_456/values/telemetry:latest"
        )
        assert kwargs["headers"]["Authorization"] == "Bearer token_789"
        assert kwargs["headers"]["Content-Type"] == "application/json"

        body = json.loads(kwargs["data"])
        assert body["last_alert"]["district"] == "bila_tserkva"
        assert body["last_alert"]["location_name"] == "Білоцерківський район"
        assert body["source_connected"] is True
        assert "updated_at" in body


@pytest.mark.asyncio
async def test_push_telemetry_to_kv_survives_network_error(monkeypatch, caplog):
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_ACCOUNT_ID", "acc_123")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "ns_456")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_API_TOKEN", "token_789")

    caplog.set_level(logging.WARNING)

    with patch("requests.put", side_effect=Exception("Connection failed")):
        await alerts_main.push_telemetry_to_kv()

    assert "Failed to push telemetry snapshot to Cloudflare KV" in caplog.text


@pytest.mark.asyncio
async def test_request_telemetry_sync_coalesces_multiple_triggers():
    with patch.object(alerts_main, "push_telemetry_to_kv", new_callable=AsyncMock) as mock_push:
        for _ in range(35):
            alerts_main.request_telemetry_sync(delay=0.05)

        await asyncio.sleep(0.1)
        mock_push.assert_awaited_once()
        assert alerts_main._telemetry_sync_task.done()


@pytest.mark.asyncio
async def test_request_telemetry_sync_cancels_previous_pending():
    with patch.object(alerts_main, "push_telemetry_to_kv", new_callable=AsyncMock) as mock_push:
        alerts_main.request_telemetry_sync(delay=5.0)
        first_task = alerts_main._telemetry_sync_task
        assert not first_task.done()

        alerts_main.request_telemetry_sync(delay=0.02)
        await asyncio.sleep(0)
        assert first_task.cancelled()

        await asyncio.sleep(0.05)
        mock_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_telemetry_sync_uses_default_delay():
    with patch.object(alerts_main, "push_telemetry_to_kv", new_callable=AsyncMock) as mock_push:
        alerts_main.request_telemetry_sync()
        await asyncio.sleep(0.05)
        mock_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_telemetry_sync_logs_error_on_exception(caplog):
    caplog.set_level(logging.ERROR)
    with patch.object(
        alerts_main, "push_telemetry_to_kv", side_effect=RuntimeError("telemetry crash")
    ):
        alerts_main.request_telemetry_sync(delay=0.01)
        await asyncio.sleep(0.05)

    assert "Telemetry sync task failed" in caplog.text
    assert "telemetry crash" in caplog.text


def test_city_or_district_name_returns_city_for_broadcast_channels():
    assert alerts_main.city_or_district_name("bilatserkva") == "Біла Церква"
    assert alerts_main.city_or_district_name("bucha") == "Буча"
    assert alerts_main.city_or_district_name("kyiv") == "Київ"
    assert alerts_main.city_or_district_name("lviv") == "Львів"
    assert alerts_main.city_or_district_name("nikopol") == "Нікополь"


def test_city_or_district_name_falls_back_to_district_for_map_only():
    assert alerts_main.city_or_district_name("vyshhorod") == "Вишгородський район"
    assert alerts_main.city_or_district_name("boryspil") == "Бориспільський район"


def test_location_locative_formats_proper_ukrainian_cases():
    assert alerts_main.location_locative("bilatserkva") == "у Білій Церкві"
    assert alerts_main.location_locative("bucha") == "у Бучі"
    assert alerts_main.location_locative("kyiv") == "у Києві"
    assert alerts_main.location_locative("lviv") == "у Львові"
    assert alerts_main.location_locative("odesa") == "в Одесі"
    assert alerts_main.location_locative("vyshhorod") == "у Вишгороді"
    assert alerts_main.location_locative("obukhiv") == "в Обухові"


def test_location_locative_unconfigured_fallback():
    assert alerts_main.location_locative("unknown") == "у unknown"
    assert alerts_main.location_locative("unconfigured") == "у unconfigured"


@pytest.mark.asyncio
async def test_build_message_handler_handles_fallback_source(mock_redis, mock_telegram_client):
    primary_id = 111111
    fallback_id = 222222
    handler = build_message_handler(
        {"kyiv": 9001}, primary_source=primary_id, fallback_source=fallback_id
    )

    event = MagicMock()
    event.chat_id = fallback_id
    event.message.message = "м. Київ Повітряна тривога"
    event.message.id = 55
    event.message.date = datetime.datetime(2026, 8, 29, 12, 0, tzinfo=datetime.timezone.utc)

    with (
        patch("alerts.main.send_alert", new_callable=AsyncMock) as mock_send,
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock) as mock_uname,
    ):
        mock_uname.return_value = "fallback_channel"
        await handler(event)
        await _drain_background_tasks()

    assert alerts_main.last_fallback_message_at == event.message.date.timestamp()
    assert alerts_main.active_source_name == "fallback"
    mock_send.assert_awaited_once_with(9001, "kyiv", "air_raid_alert", source_type="fallback")


@pytest.mark.asyncio
async def test_dual_source_deduplication_between_primary_and_fallback(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    primary_id = 111111
    fallback_id = 222222
    handler = build_message_handler(
        {"kyiv": 9001}, primary_source=primary_id, fallback_source=fallback_id
    )

    # Message from fallback arrives first
    event_fb = MagicMock()
    event_fb.chat_id = fallback_id
    event_fb.message.message = "м. Київ Повітряна тривога"
    event_fb.message.id = 100
    mock_redis.set.return_value = None

    with (
        patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock),
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock),
    ):
        await handler(event_fb)
        await _drain_background_tasks()

    assert mock_telegram_client.send_message.await_count == 1

    # Message from primary arrives shortly after for the same alert
    mock_redis.set.return_value = "air_raid_alert"
    event_prim = MagicMock()
    event_prim.chat_id = primary_id
    event_prim.message.message = "м. Київ Повітряна тривога"
    event_prim.message.id = 200

    with (
        patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock),
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock),
    ):
        await handler(event_prim)
        await _drain_background_tasks()

    # send_message should NOT be called a second time
    assert mock_telegram_client.send_message.await_count == 1


class FakeRedisState:
    """Redis double that actually holds state.

    The claim is only atomic because `SET ... GET` and the restore script run
    as one step on the server, so an AsyncMock handing back a fixed value
    cannot show the race is gone. Every call yields first, the way a round trip
    does, and only then applies its command in one go.
    """

    def __init__(self, initial=None):
        self.store = dict(initial or {})

    async def set(self, key, value, get=False, **kwargs):
        await asyncio.sleep(0)
        previous = self.store.get(key)
        self.store[key] = value
        return previous if get else True

    async def get(self, key):
        await asyncio.sleep(0)
        return self.store.get(key)

    async def eval(self, script, numkeys, *args):
        """Stands in for _RESTORE_STATE_LUA: restore only our own claim."""
        await asyncio.sleep(0)
        key, claimed, previous = args[0], args[1], args[2]
        if self.store.get(key) == claimed:
            if previous == "":
                self.store.pop(key, None)
            else:
                self.store[key] = previous
        return 1

    async def hset(self, *args, **kwargs):
        await asyncio.sleep(0)
        return 1

    async def sadd(self, *args, **kwargs):
        await asyncio.sleep(0)
        return 1

    async def srem(self, *args, **kwargs):
        await asyncio.sleep(0)
        return 1

    async def scard(self, *args, **kwargs):
        await asyncio.sleep(0)
        return 0


@pytest.mark.asyncio
async def test_send_alert_broadcasts_once_when_both_sources_land_together(mock_pg_pool):
    """The duplicate seen in production on 2026-09-01 at 04:08:52.

    The same Nikopol alert reached the worker from both source channels inside
    the same second. Reading the state and only writing it once the message was
    away let both copies through, so subscribers got the alert twice.
    """
    state_key = f"channel_state:{CHANNEL_ID}"
    fake_redis = FakeRedisState({state_key: "air_raid_alert_cancelled"})
    telegram = AsyncMock()

    async def send_that_stays_in_flight(*args, **kwargs):
        await asyncio.sleep(0.01)
        return MagicMock(id=7)

    telegram.send_message.side_effect = send_that_stays_in_flight

    with (
        patch("alerts.main.redis_client", fake_redis),
        patch("alerts.main.client", telegram),
        patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock),
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock),
    ):
        await asyncio.gather(
            send_alert(CHANNEL_ID, "nikopol", "air_raid_alert", source_type="primary"),
            send_alert(CHANNEL_ID, "nikopol", "air_raid_alert", source_type="fallback"),
        )
        await _drain_background_tasks()

    assert telegram.send_message.await_count == 1
    assert fake_redis.store[state_key] == "air_raid_alert"


@pytest.mark.asyncio
async def test_record_map_only_alert_records_once_when_both_sources_land_together(mock_pg_pool):
    _, mock_conn = mock_pg_pool
    fake_redis = FakeRedisState()

    with patch("alerts.main.redis_client", fake_redis):
        await asyncio.gather(
            record_map_only_alert("vyshhorod", "air_raid_alert", source_type="primary"),
            record_map_only_alert("vyshhorod", "air_raid_alert", source_type="fallback"),
        )
        await _drain_background_tasks()

    assert mock_conn.execute.await_count == 1
    assert fake_redis.store["district_state:vyshhorod"] == "air_raid_alert"


@pytest.mark.asyncio
async def test_send_alert_restores_the_displaced_state_when_the_send_fails(mock_pg_pool, caplog):
    """A claim that never reaches Telegram has to be given back.

    Otherwise the channel remembers an alert nobody heard, and the same alert
    arriving from the other source is deduplicated away - a dropped alert,
    which is worse than the duplicate this claim exists to prevent.
    """
    caplog.set_level(logging.ERROR)
    state_key = f"channel_state:{CHANNEL_ID}"
    fake_redis = FakeRedisState({state_key: "air_raid_alert_cancelled"})
    telegram = AsyncMock()
    telegram.send_message.side_effect = ConnectionError("Telegram is down")

    with (
        patch("alerts.main.redis_client", fake_redis),
        patch("alerts.main.client", telegram),
    ):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")
        await _drain_background_tasks()

    assert fake_redis.store[state_key] == "air_raid_alert_cancelled"

    telegram.send_message.side_effect = None
    telegram.send_message.return_value = MagicMock(id=11)

    with (
        patch("alerts.main.redis_client", fake_redis),
        patch("alerts.main.client", telegram),
        patch("alerts.main.process_channel_photo_update", new_callable=AsyncMock),
        patch("alerts.main.resolve_channel_username", new_callable=AsyncMock),
    ):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")
        await _drain_background_tasks()

    assert telegram.send_message.await_count == 2
    assert fake_redis.store[state_key] == "air_raid_alert"


@pytest.mark.asyncio
async def test_send_alert_leaves_a_newer_state_alone_when_the_send_fails(mock_pg_pool):
    """The rollback restores our own claim, never a state that moved on.

    If a later event has already claimed the channel, that state is the current
    truth; writing the displaced one back over it would deduplicate the
    announcement that follows.
    """
    state_key = f"channel_state:{CHANNEL_ID}"
    fake_redis = FakeRedisState({state_key: "air_raid_alert_cancelled"})
    telegram = AsyncMock()

    async def overtaken_then_failing(*args, **kwargs):
        fake_redis.store[state_key] = "threat_of_shelling"
        raise ConnectionError("Telegram is down")

    telegram.send_message.side_effect = overtaken_then_failing

    with (
        patch("alerts.main.redis_client", fake_redis),
        patch("alerts.main.client", telegram),
    ):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")
        await _drain_background_tasks()

    assert fake_redis.store[state_key] == "threat_of_shelling"


@pytest.mark.asyncio
async def test_prime_monitoring_state_with_fallback(mock_redis, mock_telegram_client):
    mock_redis.get.side_effect = lambda k: {
        alerts_main.LAST_SOURCE_MESSAGE_KEY: "1700000000",
        alerts_main.LAST_PRIMARY_MESSAGE_KEY: "1700000000",
        alerts_main.LAST_FALLBACK_MESSAGE_KEY: "1700000050",
        alerts_main.LAST_BROADCAST_AT_KEY: "1700000010",
        alerts_main.ACTIVE_SOURCE_KEY: "fallback",
    }.get(k)

    with patch("alerts.main.push_telemetry_to_kv", new_callable=AsyncMock):
        await alerts_main._prime_monitoring_state(111111, fallback_source=222222)

    assert alerts_main.last_source_message_at == 1700000000.0
    assert alerts_main.last_primary_message_at == 1700000000.0
    assert alerts_main.last_fallback_message_at == 1700000050.0
    assert alerts_main.active_source_name == "fallback"


@pytest.mark.asyncio
async def test_prime_monitoring_state_fetches_from_telegram_when_no_redis(mock_telegram_client):
    alerts_main.redis_client = None
    mock_msg1 = MagicMock(date=datetime.datetime(2026, 8, 29, 10, 0, tzinfo=datetime.timezone.utc))
    mock_msg2 = MagicMock(date=datetime.datetime(2026, 8, 29, 10, 5, tzinfo=datetime.timezone.utc))

    mock_telegram_client.get_messages.side_effect = lambda cid, limit: (
        [mock_msg1] if cid == 111111 else [mock_msg2]
    )

    with patch("alerts.main.push_telemetry_to_kv", new_callable=AsyncMock):
        await alerts_main._prime_monitoring_state(111111, fallback_source=222222)

    assert alerts_main.last_primary_message_at == mock_msg1.date.timestamp()
    assert alerts_main.last_fallback_message_at == mock_msg2.date.timestamp()


def test_silence_reporting_for_primary_and_fallback(caplog):
    caplog.set_level(logging.INFO)
    threshold = alerts_main.SOURCE_SILENCE_THRESHOLD

    alerts_main.primary_silence_reported = False
    alerts_main.fallback_silence_reported = False
    alerts_main.source_silence_reported = False

    # 1. Primary is silent, but fallback is active
    alerts_main._report_source_silence(
        primary_silence=threshold + 10,
        fallback_silence=100,
        overall_silence=100,
        has_fallback=True,
    )
    assert "Primary source silent" in caplog.text
    assert "operating via fallback source" in caplog.text
    assert alerts_main.primary_silence_reported is True

    # 2. Fallback becomes silent, primary active
    caplog.clear()
    alerts_main.primary_silence_reported = False
    alerts_main._report_source_silence(
        primary_silence=100,
        fallback_silence=threshold + 10,
        overall_silence=100,
        has_fallback=True,
    )
    assert "Fallback source channel silent" in caplog.text
    assert alerts_main.fallback_silence_reported is True

    # 3. Fallback recovers
    caplog.clear()
    alerts_main._report_source_silence(
        primary_silence=100,
        fallback_silence=50,
        overall_silence=50,
        has_fallback=True,
    )
    assert "Fallback source channel is posting again" in caplog.text
    assert alerts_main.fallback_silence_reported is False


@pytest.mark.asyncio
async def test_healthcheck_loop_pings_fallback_url(monkeypatch):
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "https://hc-ping.com/primary"
    )
    monkeypatch.setattr(
        alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_FALLBACK_PING_URL", "https://hc-ping.com/fallback"
    )
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    alerts_main.last_source_message_at = 1_700_000_000.0
    alerts_main.last_primary_message_at = 1_700_000_000.0
    alerts_main.last_fallback_message_at = (
        1_700_000_000.0 - alerts_main.SOURCE_SILENCE_THRESHOLD - 10
    )

    with (
        patch("alerts.main.time.time", return_value=1_700_000_000.0),
        patch("alerts.main._ping_healthcheck") as mock_primary_ping,
        patch("alerts.main._ping_fb_healthcheck") as mock_fb_ping,
    ):
        await _run_one_cycle(alerts_main._healthcheck_loop(mock_client, has_fallback=True))

    mock_primary_ping.assert_called_once_with()
    mock_fb_ping.assert_called_once_with("/fail")


@pytest.mark.asyncio
async def test_push_telemetry_to_kv_includes_fallback_data(monkeypatch):
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_ACCOUNT_ID", "acc_123")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "ns_456")
    monkeypatch.setattr(alerts_main, "CLOUDFLARE_API_TOKEN", "token_789")

    alerts_main.last_primary_message_at = 1_700_000_100.0
    alerts_main.last_fallback_message_at = 1_700_000_200.0
    alerts_main.last_source_message_at = 1_700_000_200.0
    alerts_main.active_source_name = "fallback"

    mock_client = MagicMock()
    mock_client.is_connected.return_value = True
    alerts_main.client = mock_client

    with patch("requests.put") as mock_put:
        await alerts_main.push_telemetry_to_kv()

    assert mock_put.called
    body = json.loads(mock_put.call_args.kwargs["data"])
    assert body["active_source"] == "fallback"
    # One connection is measured, so one flag is published.
    assert body["source_connected"] is True
    assert "primary_source_connected" not in body
    assert "fallback_source_connected" not in body
    assert "last_primary_message_at" in body
    assert "last_fallback_message_at" in body
