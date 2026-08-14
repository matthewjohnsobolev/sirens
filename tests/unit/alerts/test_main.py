import argparse
import asyncio
import logging
import re

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telethon.errors import AuthKeyDuplicatedError, FloodWaitError
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import (
    InputChatUploadedPhoto,
    UpdateNewChannelMessage,
    MessageService,
    MessageActionChatEditPhoto,
)

from alerts import main as alerts_main
from alerts.cli import get_mode_config
from alerts.main import (
    CHANNEL_PHOTO_PATHS,
    PHOTO_UPDATE_MAX_ATTEMPTS,
    build_message_handler,
    delete_photo_update_service_message,
    log_alert_received,
    main,
    process_channel_photo_update,
    send_alert,
    update_channel_photo,
)
from config import DATABASE_URL, MESSAGES, REDIS_URL, REGION_CONFIG, VERSION
from tests.samples.source_messages import ALL_SAMPLES, MESSAGES_SAMPLES

TIME_RE = re.compile(r"\d{2}:\d{2}")

CHANNEL_ID = 123456


async def _drain_background_tasks():
    """Let send_alert's / the handler's fire-and-forget task run to completion.

    The first yield runs the task body, the second lets its done-callback
    (which discards it from running_tasks) fire.
    """
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# --------------------------------------------------------------------------
# spawn_tracked_task
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_tracked_task_logs_failure(caplog):
    """A fire-and-forget task that raises must surface in the log (and so in
    Sentry) rather than vanishing into a task result nobody ever retrieves."""
    caplog.set_level(logging.ERROR)

    async def boom():
        raise RuntimeError("task blew up")

    alerts_main.spawn_tracked_task(boom(), "Test task")
    await _drain_background_tasks()

    assert "Test task failed" in caplog.text
    assert "task blew up" in caplog.text
    assert alerts_main.running_tasks == set()


# --------------------------------------------------------------------------
# log_alert_received
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# update_channel_photo / delete_photo_update_service_message
# --------------------------------------------------------------------------

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
    edit_result = MagicMock(updates=[MagicMock()])  # not an UpdateNewChannelMessage
    mock_entity = MagicMock(id=456)

    await delete_photo_update_service_message(mock_entity, edit_result)

    mock_telegram_client.delete_messages.assert_not_awaited()
    assert "Service message about photo update not found" in caplog.text


# --------------------------------------------------------------------------
# process_channel_photo_update
# --------------------------------------------------------------------------

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
    # exponential backoff: 5, 10, 20
    assert [c.args[0] for c in mock_sleep.await_args_list] == [5, 10, 20]
    assert "Aborting photo update for Kyiv after 3 attempts" in caplog.text


@pytest.mark.asyncio
async def test_process_channel_photo_update_ignores_unknown_alert_type(
    mock_redis, mock_telegram_client
):
    await process_channel_photo_update(CHANNEL_ID, "kyiv", "unknown_type")

    mock_redis.get.assert_not_awaited()
    mock_telegram_client.get_entity.assert_not_awaited()


# --------------------------------------------------------------------------
# send_alert
# --------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("region, alert_type, expected_status", [
    ("kyiv", "air_raid_alert", 1),
    ("kyiv", "air_raid_alert_cancelled", 0),
    ("nikopol", "threat_of_shelling", 1),
    ("nikopol", "threat_of_shelling_cancelled", 0),
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

    mock_redis.hset.assert_awaited_once()
    assert mock_redis.hset.call_args.args[0] == f"threat:alerts:{oblast}"
    mapping = mock_redis.hset.call_args.kwargs["mapping"]
    assert mapping["status"] == expected_status
    assert mapping["source"] == "telegram"
    assert TIME_RE.fullmatch(mapping["time"])

    mock_conn.execute.assert_awaited_once()
    sql, *params = mock_conn.execute.call_args.args
    assert "INSERT INTO alert_history" in sql
    assert params[2] == mapping["time"]
    assert params[3] == oblast
    assert params[4] == alert_type
 
    mock_telegram_client.send_message.assert_awaited_once_with(
        CHANNEL_ID, MESSAGES[alert_type]
    )

    mock_photo.assert_awaited_once_with(CHANNEL_ID, region, alert_type)
    assert alerts_main.running_tasks == set()


@pytest.mark.asyncio
async def test_send_alert_skips_duplicate_when_state_unchanged(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    """A region can be triggered by more than one wording (e.g. Nikopol's district
    vs. city phrasing), so the source can post two messages for the same event.
    The second one must not be re-broadcast."""
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
    """Once suppressed as a duplicate, a genuine state change (e.g. the
    cancellation, in either wording) must still go through."""
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
    """Redis only backs dedup and the map. If it is unreachable the alert must
    still reach the channel — a duplicate message is far cheaper than a missed
    air raid alert."""
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
    mock_redis.hset.assert_awaited_once()
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
    # a failed broadcast must not block the photo refresh
    mock_photo.assert_awaited_once_with(CHANNEL_ID, "kyiv", alert_type)


@pytest.mark.asyncio
async def test_send_alert_skips_photo_update_without_mapping(
    mock_redis, mock_pg_pool, mock_telegram_client, caplog
):
    caplog.set_level(logging.DEBUG)

    # an alert type that has a message but no channel photo configured
    with patch.dict('alerts.main.CHANNEL_PHOTO_PATHS', clear=True), \
         patch('alerts.main.process_channel_photo_update', new_callable=AsyncMock) as mock_photo:
        await send_alert(CHANNEL_ID, "kyiv", "air_raid_alert")
        await _drain_background_tasks()

    mock_telegram_client.send_message.assert_awaited_once()
    mock_photo.assert_not_awaited()
    assert "No photo mapping for 'air_raid_alert'" in caplog.text
    assert alerts_main.running_tasks == set()


# --------------------------------------------------------------------------
# build_message_handler
# --------------------------------------------------------------------------

ALL_REGION_CHANNELS = {region: 9000 + i for i, region in enumerate(REGION_CONFIG)}


async def _dispatch(message_text, region_channels=ALL_REGION_CHANNELS):
    """Feed one message to the handler and return the send_alert calls it made."""
    handler = build_message_handler(region_channels)
    event = MagicMock()
    event.message.message = message_text

    with patch('alerts.main.send_alert', new_callable=AsyncMock) as mock_send_alert:
        await handler(event)
        await _drain_background_tasks()

    assert alerts_main.running_tasks == set()
    return [call.args for call in mock_send_alert.await_args_list]


def _expected_calls(regions, alert_type):
    """The calls a message about `regions` must produce, in handler order."""
    return [
        (ALL_REGION_CHANNELS[region], region, alert_type)
        for region in REGION_CONFIG
        if region in regions
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
    assert await _dispatch(message_text, {"kyiv": 1111, "nikopol": 2222}) == expected_calls


@pytest.mark.asyncio
async def test_build_message_handler_ignores_regions_without_channel():
    assert await _dispatch("м. Київ Повітряна тривога", {"nikopol": 2222}) == []


# --- real messages from the source channel -------------------------------
# The samples live in tests/samples/source_messages.py; add one there and it is
# picked up by the tests below. ALL_SAMPLES covers both the one-district posts
# and the combined ones that list several districts as bullets.

@pytest.mark.asyncio
@pytest.mark.parametrize("sample", ALL_SAMPLES, ids=lambda sample: sample.id)
async def test_build_message_handler_on_real_channel_messages(sample):
    """A real post reaches every channel it names, and no other."""
    assert await _dispatch(sample.alert_message) == _expected_calls(
        sample.regions, "air_raid_alert"
    )
    assert await _dispatch(sample.cancellation_message) == _expected_calls(
        sample.regions, "air_raid_alert_cancelled"
    )


def test_every_configured_region_has_a_message_sample():
    """A new region in REGION_CONFIG needs a sample in tests/samples/source_messages.py."""
    sampled = {region for sample in MESSAGES_SAMPLES for region in sample.regions}

    assert sampled == set(REGION_CONFIG)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_wires_up_clients_and_handler():
    _, expected_source = get_mode_config(argparse.Namespace(mode='dev'))

    with patch('alerts.main.redis.from_url') as mock_redis_from_url, \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock) as mock_create_pool, \
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
    """Both services share one Sentry project, so the tag is the only thing
    separating alerts errors from web errors in the issue stream."""
    monkeypatch.setattr(alerts_main, 'SENTRY_DSN', 'https://examplePublicKey@o0.ingest.sentry.io/0')

    with patch('alerts.main.redis.from_url'), \
         patch('alerts.main.asyncpg.create_pool', new_callable=AsyncMock), \
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


# --------------------------------------------------------------------------
# healthchecks.io pings
# --------------------------------------------------------------------------

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
