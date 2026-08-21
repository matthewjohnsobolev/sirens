"""
Unit tests for alerts.main (alert monitoring, state persistence, and broadcasting).
"""

import argparse
import asyncio
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
    strip_ongoing_notice,
    update_channel_photo,
)
from config import (
    DATABASE_URL,
    DISTRICT_CONFIG,
    DISTRICTS_BY_OBLAST,
    MESSAGES,
    REDIS_URL,
    REGION_CONFIG,
    VERSION,
    real_channels,
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


async def _drain_background_tasks():
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


@pytest.mark.parametrize("alert_type, expected", [
    ("air_raid_alert", "Air raid alert received for Kyiv"),
    ("air_raid_alert_cancelled", "Air raid alert cancellation received for Kyiv"),
    ("threat_of_shelling", "Threat of shelling received for Kyiv"),
    ("threat_of_shelling_cancelled", "Threat of shelling cancelled received for Kyiv"),
])
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

    with patch('alerts.main.update_channel_photo', new_callable=AsyncMock) as mock_update_photo, \
         patch('alerts.main.delete_photo_update_service_message', new_callable=AsyncMock) as mock_delete:
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

    with patch('alerts.main.update_channel_photo', new_callable=AsyncMock) as mock_update_photo, \
         patch('alerts.main.delete_photo_update_service_message', new_callable=AsyncMock) as mock_delete:
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    mock_telegram_client.get_entity.assert_awaited_once_with(CHANNEL_ID)
    mock_update_photo.assert_awaited_once_with(
        mock_entity, CHANNEL_PHOTO_PATHS["air_raid_alert"]
    )
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

    with patch('alerts.main.update_channel_photo', new_callable=AsyncMock) as mock_update_photo, \
         patch('alerts.main.delete_photo_update_service_message', new_callable=AsyncMock) as mock_delete, \
         patch('alerts.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
        await process_channel_photo_update(CHANNEL_ID, "kyiv", "air_raid_alert")

    mock_sleep.assert_awaited_once_with(2)
    assert mock_telegram_client.get_entity.await_count == 2
    mock_update_photo.assert_awaited_once_with(
        mock_entity, CHANNEL_PHOTO_PATHS["air_raid_alert"]
    )
    mock_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_channel_photo_update_gives_up_after_max_attempts(
    mock_redis, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)
    mock_redis.get.return_value = "air_raid_alert"
    mock_telegram_client.get_entity.side_effect = Exception("boom")

    with patch('alerts.main.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
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


@pytest.mark.parametrize("channel_id, message_id, username, expected", [
    (-1001712561448, 42, "kyiv_alert", "https://t.me/kyiv_alert/42"),
    (-1001712561448, 42, None, "https://t.me/c/1712561448/42"),
    (-4242, 7, None, "https://t.me/c/4242/7"),
])
def test_build_message_link(channel_id, message_id, username, expected):
    assert build_message_link(channel_id, message_id, username) == expected


@pytest.mark.asyncio
async def test_resolve_channel_username_caches_the_lookup(mock_telegram_client):
    mock_telegram_client.get_entity.return_value = MagicMock(username="kyiv_alert")

    assert await resolve_channel_username(CHANNEL_ID) == "kyiv_alert"
    assert await resolve_channel_username(CHANNEL_ID) == "kyiv_alert"

    mock_telegram_client.get_entity.assert_awaited_once_with(CHANNEL_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", [
    pytest.param(MagicMock(username=None), id="private-channel"),
    pytest.param(MagicMock(username=""), id="empty-username"),
])
async def test_resolve_channel_username_returns_none_without_username(
    mock_telegram_client, entity
):
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
        77, "https://t.me/kyiv_alert/77"
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

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
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

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "nikopol", "threat_of_shelling")
        await _drain_background_tasks()

    calls = [
        c for c in mock_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:shellings:nikopol"
    ]
    assert calls[0].kwargs["mapping"]["source"] == "https://t.me/nikopol_alert/15"


@pytest.mark.asyncio
async def test_send_alert_falls_back_to_a_private_link_without_username(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_telegram_client.send_message.return_value = MagicMock(id=9)
    mock_telegram_client.get_entity.return_value = MagicMock(username=None)

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
        await send_alert(-1001712561448, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    calls = [
        c for c in mock_redis.hset.call_args_list
        if c.args and c.args[0] == "threat:alerts:city:kyiv"
    ]
    assert calls[0].kwargs["mapping"]["source"] == "https://t.me/c/1712561448/9"


@pytest.mark.asyncio
@pytest.mark.parametrize("region, alert_type, expected_status", [
    ("kyiv", "air_raid_alert", "true"),
    ("kyiv", "air_raid_alert_cancelled", "false"),
    ("nikopol", "threat_of_shelling", "true"),
    ("nikopol", "threat_of_shelling_cancelled", "false"),
])
async def test_send_alert_writes_state_history_and_broadcasts(
    mock_redis, mock_pg_pool, mock_telegram_client, region, alert_type, expected_status
):
    _, mock_conn = mock_pg_pool
    oblast = REGION_CONFIG[region]["oblast"]

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, region, alert_type)
        await _drain_background_tasks()

    mock_redis.set.assert_awaited_once_with(f"channel_state:{CHANNEL_ID}", alert_type)

    if "shelling" in alert_type:
        mock_redis.hset.assert_any_call(
            f"threat:shellings:{region}",
            mapping={
                "status": expected_status,
                "time": mock_redis.hset.call_args_list[0].kwargs["mapping"]["time"],
                "source": "telegram",
                "updated_at": mock_redis.hset.call_args_list[0].kwargs["mapping"]["updated_at"],
            }
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
            }
        )

    mock_conn.execute.assert_awaited_once()
    sql, *params = mock_conn.execute.call_args.args
    assert "INSERT INTO alert_history" in sql
    assert params[3] == region
    assert params[4] == oblast
    assert params[5] == alert_type
 
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES[alert_type]
    )

    mock_photo.assert_awaited_once_with(CHANNEL_ID, region, alert_type)
    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_send_alert_skips_duplicate_when_state_unchanged(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.INFO)
    mock_redis.get.return_value = "air_raid_alert"

    await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert")

    mock_redis.get.assert_awaited_once_with(f"channel_state:{CHANNEL_ID}")
    mock_redis.set.assert_not_awaited()
    mock_redis.hset.assert_not_awaited()
    mock_telegram_client.send_message.assert_not_awaited()
    assert "Duplicate air_raid_alert ignored for Nikopol" in caplog.text


@pytest.mark.asyncio
async def test_send_alert_processes_state_change_after_duplicate_suppression(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_redis.get.return_value = "air_raid_alert"

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "nikopol", "air_raid_alert_cancelled")
        await _drain_background_tasks()

    mock_redis.set.assert_awaited_once_with(f"channel_state:{CHANNEL_ID}", "air_raid_alert_cancelled")
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES["air_raid_alert_cancelled"]
    )


@pytest.mark.asyncio
async def test_send_alert_broadcasts_when_redis_is_down(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.ERROR)
    mock_redis.get.side_effect = ConnectionError("Redis is down")

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
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

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock):
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    assert "Failed to insert alert history into PG: DB Error" in caplog.text
    mock_redis.hset.assert_called()
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES["air_raid_alert"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("alert_type, expected_log", [
    ("air_raid_alert", "Failed to send air raid alert to Kyiv"),
    ("air_raid_alert_cancelled", "Failed to send air raid alert cancellation to Kyiv"),
    ("threat_of_shelling", "Failed to send threat of shelling to Kyiv"),
])
async def test_send_alert_logs_but_survives_send_failure(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog, alert_type, expected_log
):
    caplog.set_level(logging.ERROR)
    mock_telegram_client.send_message.side_effect = Exception("network down")

    with patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, "kyiv", alert_type)
        await _drain_background_tasks()

    assert expected_log in caplog.text
    mock_photo.assert_not_awaited()
    mock_redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_alert_skips_photo_update_without_mapping(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.DEBUG)

    with patch.dict('alerts.main.CHANNEL_PHOTO_PATHS', clear=True), \
         patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    mock_telegram_client.send_message.assert_awaited_once()
    mock_photo.assert_not_awaited()
    assert "No photo mapping for 'air_raid_alert'" in caplog.text
    assert alerts_main.running_tasks == set()


ALL_REGION_CHANNELS = {region: 9000 + i for i, region in enumerate(REGION_CONFIG)}

SOURCE_CHANNEL = real_channels['source']
SOURCE_USERNAME = "air_alert_ua"
SOURCE_MESSAGE_ID = 500
SOURCE_LINK = f"https://t.me/{SOURCE_USERNAME}/{SOURCE_MESSAGE_ID}"


class Dispatched(NamedTuple):
    """Дві гілки парсера: що пішло в канали і що лише на карту."""

    broadcast: list
    recorded: list


async def _dispatch(message_text, region_channels=ALL_REGION_CHANNELS):
    handler = build_message_handler(region_channels)
    event = MagicMock()
    event.message.message = message_text
    event.message.id = SOURCE_MESSAGE_ID
    event.chat_id = SOURCE_CHANNEL

    with patch('alerts.main.send_alert', new_callable=AsyncMock) as mock_send_alert, \
         patch('alerts.main.record_map_only_alert', new_callable=AsyncMock) as mock_record, \
         patch('alerts.main.resolve_channel_username', new_callable=AsyncMock) as mock_username:
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
@pytest.mark.parametrize("message_text, expected_calls", [
    pytest.param(
        "м. Київ Повітряна тривога",
        [(1111, "kyiv", "air_raid_alert")],
        id="kyiv-fallback-alert",
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
    pytest.param("Some random text", [], id="no-region-match"),
    pytest.param("м. Київ погода сьогодні гарна", [], id="region-without-alert-keyword"),
])
async def test_build_message_handler_dispatches_correct_alert(message_text, expected_calls):
    assert (await _dispatch(message_text, {"kyiv": 1111, "nikopol": 2222})).broadcast == expected_calls


@pytest.mark.asyncio
async def test_build_message_handler_maps_a_region_without_a_channel():
    """Без каналу тривога не мовиться, але карта про неї все одно дізнається."""
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
@pytest.mark.parametrize(
    "sample", PARTIAL_CANCELLATION_SAMPLES, ids=lambda sample: sample.id
)
async def test_build_message_handler_ignores_still_ongoing_places(sample):
    assert (await _dispatch(sample.message)).broadcast == _expected_calls(
        sample.regions, "air_raid_alert_cancelled"
    )


@pytest.mark.parametrize(
    "sample", PARTIAL_CANCELLATION_SAMPLES, ids=lambda sample: sample.id
)
def test_partial_cancellation_samples_name_the_silenced_channels(sample):
    assert sample.silenced

    note = sample.message.split("ще триває", 1)[1]
    for region in sample.silenced:
        assert any(
            trigger in note for trigger in REGION_CONFIG[region]['triggers']
        ), f"note does not name anything {region} listens for"


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


@pytest.mark.parametrize("message_text, expected", [
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
])
def test_strip_ongoing_notice(message_text, expected):
    assert strip_ongoing_notice(message_text) == expected


@pytest.mark.asyncio
async def test_main_wires_up_clients_and_handler():
    _, expected_source = get_mode_config(argparse.Namespace(mode='dev'))

    with patch('alerts.main.redis.from_url') as mock_redis_from_url, \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock) as mock_create_pool, \
         patch('alerts.main.ensure_pg_tables') as mock_ensure, \
         patch('alerts.main.rehydrate_state_from_db') as mock_rehydrate, \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args:

        mock_get_args.return_value = argparse.Namespace(mode='dev')

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
    assert event_filter.chats == [expected_source]
    mock_client_instance.run_until_disconnected.assert_awaited_once()
    assert alerts_main.client is mock_client_instance


@pytest.mark.asyncio
async def test_main_initializes_sentry_with_mode_as_environment(monkeypatch):
    monkeypatch.setattr(alerts_main, 'SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args, \
         patch('alerts.main.sentry_sdk.init') as mock_sentry_init:

        mock_get_args.return_value = argparse.Namespace(mode='prod')

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_sentry_init.assert_called_once()
    _, kwargs = mock_sentry_init.call_args
    assert kwargs['dsn'] == 'https://examplePublicKey@o0.ingest.sentry.io/0'
    assert kwargs['environment'] == 'prod'
    assert kwargs['release'] == VERSION
    assert kwargs['send_default_pii'] is False


@pytest.mark.asyncio
async def test_main_tags_events_with_its_service_name(monkeypatch):
    monkeypatch.setattr(alerts_main, 'SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args, \
         patch('alerts.main.sentry_sdk.init'), \
         patch('alerts.main.sentry_sdk.set_tag') as mock_set_tag:

        mock_get_args.return_value = argparse.Namespace(mode='prod')

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_set_tag.assert_called_once_with("service", "alerts")


@pytest.mark.asyncio
async def test_main_starts_interactive_login_when_not_authorized():
    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args:

        mock_get_args.return_value = argparse.Namespace(mode='dev')

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = False
        mock_client_instance.add_event_handler = MagicMock()

        await main()

    mock_client_instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_survives_backend_connection_failures(caplog):
    caplog.set_level(logging.ERROR)

    with patch('alerts.main.redis.from_url', side_effect=Exception("redis down")), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock) as mock_create_pool, \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args:

        mock_create_pool.side_effect = Exception("pg down")
        mock_get_args.return_value = argparse.Namespace(mode='dev')

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

    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args:

        mock_get_args.return_value = argparse.Namespace(mode='dev')

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()
        mock_client_instance.run_until_disconnected.side_effect = AuthKeyDuplicatedError(request=MagicMock())

        with patch('alerts.main._ping_healthcheck') as mock_ping:
            with pytest.raises(AuthKeyDuplicatedError):
                await main()

    assert "Telegram session is invalid" in caplog.text
    assert "./deploy/setup.sh" in caplog.text
    mock_ping.assert_called_once_with("/fail")


@pytest.mark.asyncio
async def test_main_logs_error_on_transient_connection_error(caplog):
    caplog.set_level(logging.ERROR)

    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
         patch('alerts.main.ensure_pg_tables'), \
         patch('alerts.main.rehydrate_state_from_db'), \
         patch('alerts.main.TelegramClient') as MockClient, \
         patch('alerts.main.cli.get_args') as mock_get_args:

        mock_get_args.return_value = argparse.Namespace(mode='dev')

        mock_client_instance = AsyncMock()
        MockClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.is_user_authorized.return_value = True
        mock_client_instance.add_event_handler = MagicMock()
        mock_client_instance.run_until_disconnected.side_effect = ConnectionRefusedError("connection refused")

        with pytest.raises(ConnectionRefusedError):
            await main()

    assert "Telegram connection lost and could not be recovered" in caplog.text


def test_ping_healthcheck_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', '')

    with patch('alerts.main.requests.get') as mock_get:
        alerts_main._ping_healthcheck()

    mock_get.assert_not_called()


def test_ping_healthcheck_sends_get_with_suffix(monkeypatch):
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', 'https://hc-ping.com/test-uuid')

    with patch('alerts.main.requests.get') as mock_get:
        alerts_main._ping_healthcheck('/fail')

    mock_get.assert_called_once_with(
        'https://hc-ping.com/test-uuid/fail', timeout=alerts_main.HEALTHCHECK_PING_TIMEOUT
    )


def test_ping_healthcheck_logs_but_survives_request_failure(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', 'https://hc-ping.com/test-uuid')

    with patch('alerts.main.requests.get', side_effect=Exception('network down')):
        alerts_main._ping_healthcheck()

    assert "Failed to ping healthchecks.io" in caplog.text


@pytest.mark.asyncio
async def test_healthcheck_loop_skips_when_unconfigured(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', '')
    mock_client = MagicMock()

    await alerts_main._healthcheck_loop(mock_client)

    assert "HEALTHCHECKS_PING_URL_ALERTS not set" in caplog.text
    mock_client.is_connected.assert_not_called()


@pytest.mark.asyncio
async def test_healthcheck_loop_pings_while_connected(monkeypatch):
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', 'https://hc-ping.com/test-uuid')
    monkeypatch.setattr(alerts_main, 'HEALTHCHECK_PING_INTERVAL', 0.01)
    mock_client = MagicMock()
    mock_client.is_connected.return_value = True

    with patch('alerts.main._ping_healthcheck') as mock_ping:
        task = asyncio.create_task(alerts_main._healthcheck_loop(mock_client))
        await asyncio.sleep(0.03)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    mock_ping.assert_called()


@pytest.mark.asyncio
async def test_healthcheck_loop_skips_ping_when_disconnected(monkeypatch):
    monkeypatch.setattr(alerts_main, 'HEALTHCHECKS_PING_URL_ALERTS', 'https://hc-ping.com/test-uuid')
    monkeypatch.setattr(alerts_main, 'HEALTHCHECK_PING_INTERVAL', 0.01)
    mock_client = MagicMock()
    mock_client.is_connected.return_value = False

    with patch('alerts.main._ping_healthcheck') as mock_ping:
        task = asyncio.create_task(alerts_main._healthcheck_loop(mock_client))
        await asyncio.sleep(0.03)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    mock_ping.assert_not_called()


# --- Districts without a channel: map state only -----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", MAP_ONLY_SAMPLES, ids=lambda sample: sample.id)
async def test_build_message_handler_records_districts_without_a_channel(sample):
    alert = await _dispatch(sample.alert_message)
    assert alert.recorded == _expected_records(sample.recorded, "air_raid_alert")
    assert alert.broadcast == _expected_calls(sample.broadcast, "air_raid_alert")

    cancellation = await _dispatch(sample.cancellation_message)
    assert cancellation.recorded == _expected_records(
        sample.recorded, "air_raid_alert_cancelled"
    )
    assert cancellation.broadcast == _expected_calls(
        sample.broadcast, "air_raid_alert_cancelled"
    )


@pytest.mark.asyncio
async def test_build_message_handler_points_map_only_districts_at_the_source_post():
    """Свого повідомлення в такого району немає, тож джерелом стає пост першоджерела."""
    dispatched = await _dispatch("Вишгородський район Повітряна тривога")

    assert dispatched.recorded == [
        ("vyshhorod", "air_raid_alert", SOURCE_MESSAGE_ID, SOURCE_LINK)
    ]


@pytest.mark.asyncio
async def test_build_message_handler_skips_the_source_lookup_when_all_districts_broadcast():
    """У районів із каналом джерело своє, тож зайвий resolve їм ні до чого."""
    handler = build_message_handler(ALL_REGION_CHANNELS)
    event = MagicMock()
    event.message.message = "Бучанський район Повітряна тривога"
    event.message.id = SOURCE_MESSAGE_ID
    event.chat_id = SOURCE_CHANNEL

    with patch('alerts.main.send_alert', new_callable=AsyncMock), \
         patch('alerts.main.resolve_channel_username', new_callable=AsyncMock) as mock_username:
        await handler(event)
        await _drain_background_tasks()

    mock_username.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("oblast_key, oblast_name", [
    ("poltava_oblast", "Полтавська область"),
    ("kyiv_oblast", "Київська область"),
])
async def test_build_message_handler_raises_the_whole_oblast_from_its_name(
    oblast_key, oblast_name
):
    """Тривога по області - це тривога в усіх її районах, а не лише в моїх каналах."""
    dispatched = await _dispatch(oblast_message(oblast_name))

    touched = (
        {call[1] for call in dispatched.broadcast}
        | {call[0] for call in dispatched.recorded}
    )
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
    mock_redis.set.assert_awaited_once_with("district_state:vyshhorod", "air_raid_alert")

    city = [
        call for call in mock_redis.hset.call_args_list
        if call.args and call.args[0] == "threat:alerts:city:vyshhorod"
    ]
    assert city[0].kwargs["mapping"]["status"] == "true"
    assert city[0].kwargs["mapping"]["source"] == SOURCE_LINK
    mock_redis.sadd.assert_awaited_once_with("threat:alerts:active:kyiv_oblast", "vyshhorod")

    _, *params = mock_conn.execute.call_args.args
    assert params[3:6] == ["vyshhorod", "kyiv_oblast", "air_raid_alert"]
    assert params[6] is None          # каналу немає - нема й channel_id
    assert params[7] == SOURCE_MESSAGE_ID
    assert params[8] == SOURCE_LINK

    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_record_map_only_alert_skips_duplicates(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.INFO)
    mock_redis.get.return_value = "air_raid_alert"

    await record_map_only_alert("vyshhorod", "air_raid_alert")

    mock_redis.get.assert_awaited_once_with("district_state:vyshhorod")
    mock_redis.set.assert_not_awaited()
    mock_redis.hset.assert_not_awaited()
    assert "Duplicate air_raid_alert ignored for Вишгородський район" in caplog.text


@pytest.mark.asyncio
async def test_record_map_only_alert_records_after_duplicate_suppression(
    mock_redis, mock_pg_pool, mock_telegram_client
):
    mock_redis.get.return_value = "air_raid_alert"

    await record_map_only_alert("vyshhorod", "air_raid_alert_cancelled")

    mock_redis.set.assert_awaited_once_with(
        "district_state:vyshhorod", "air_raid_alert_cancelled"
    )
    mock_redis.srem.assert_awaited_once_with("threat:alerts:active:kyiv_oblast", "vyshhorod")


@pytest.mark.asyncio
async def test_record_map_only_alert_unknown_type_does_nothing(
    mock_redis, mock_pg_pool, caplog
):
    caplog.set_level(logging.ERROR)

    await record_map_only_alert("vyshhorod", "unknown_type")

    assert "Unknown alert type: unknown_type" in caplog.text
    mock_redis.get.assert_not_awaited()
    mock_redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_map_only_alert_survives_a_redis_outage(
    mock_redis, mock_pg_pool, caplog
):
    caplog.set_level(logging.ERROR)
    mock_redis.get.side_effect = ConnectionError("Redis is down")
    _, mock_conn = mock_pg_pool

    await record_map_only_alert("vyshhorod", "air_raid_alert")

    assert "Redis unavailable for Вишгородський район" in caplog.text
    mock_conn.execute.assert_awaited_once()


# --- match_districts ---------------------------------------------------------


@pytest.mark.parametrize("message_text, expected", [
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
])
def test_match_districts(message_text, expected):
    assert match_districts(message_text) == expected


@pytest.mark.parametrize("name, expected_key", [
    pytest.param("Кам'янський район", "kamianske", id="straight-apostrophe"),
    pytest.param("Кам’янський район", "kamianske", id="curly-apostrophe"),
    pytest.param("Новоград-Волинський район", "zviahel", id="former-name"),
    pytest.param("Звягельський район", "zviahel", id="current-name"),
    pytest.param("Новомосковський район", "samar", id="former-name-samar"),
])
def test_match_districts_accepts_every_spelling(name, expected_key):
    assert match_districts(f"Повітряна тривога в {name}") == {
        expected_key: "air_raid_alert"
    }


@pytest.mark.parametrize("name, expected_key", [
    pytest.param("Кам'янець-Подільський район", "kamianetspodilskyi", id="kamianets-not-podilsk"),
    pytest.param("Могилів-Подільський район", "mohylivpodilskyi", id="mohyliv-not-podilsk"),
    pytest.param("Подільський район", "podilsk", id="podilsk-itself"),
    pytest.param("Білгород-Дністровський район", "bilhoroddnistrovskyi", id="bilhorod-not-dnistrovskyi"),
    pytest.param("Дністровський район", "dnistrovskyi", id="dnistrovskyi-itself"),
])
def test_match_districts_does_not_match_inside_a_longer_name(name, expected_key):
    """Назва одного району буває підрядком іншої - збіг має бути по межах слова."""
    assert match_districts(f"Повітряна тривога в {name}") == {
        expected_key: "air_raid_alert"
    }


def test_match_districts_from_the_oblast_name():
    assert match_districts(oblast_message("Полтавська область")) == {
        key: "air_raid_alert" for key in DISTRICTS_BY_OBLAST['poltava_oblast']
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
    """Джерело регулярно пише про райони поза конфігом - Sentry не має тонути."""
    caplog.set_level(logging.WARNING)
    log_unrecognised_districts("Повітряна тривога в Бахчисарайський район")
    caplog.clear()

    log_unrecognised_districts("Відбій тривоги в Бахчисарайський район")

    assert caplog.text == ""


def test_log_unrecognised_districts_stays_quiet_on_a_known_post(caplog):
    caplog.set_level(logging.WARNING)

    log_unrecognised_districts("Повітряна тривога в Кам'янець-Подільський район")

    assert caplog.text == ""
