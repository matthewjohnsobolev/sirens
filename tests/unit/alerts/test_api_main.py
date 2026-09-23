"""
Unit tests for alerts.main integration with Ukraine Alert API 3.0.
"""

import asyncio
import datetime
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from alerts import main as alerts_main
from alerts.api_client import (
    UkraineAlarmAuthError,
    UkraineAlarmClient,
    UkraineAlarmNetworkError,
    UkraineAlarmRateLimitError,
)


@pytest.fixture(autouse=True)
def _clean_alerts_state():
    alerts_main.last_action_index = None
    alerts_main.last_api_poll_at = None
    alerts_main._last_source_redis_sync_at = 0.0
    alerts_main.active_threats_by_district.clear()
    alerts_main.running_tasks.clear()
    yield
    alerts_main.last_action_index = None
    alerts_main.last_api_poll_at = None
    alerts_main._last_source_redis_sync_at = 0.0
    alerts_main.active_threats_by_district.clear()
    alerts_main.running_tasks.clear()


@pytest.mark.asyncio
async def test_restore_stored_alert_payload_redis():
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = lambda key: {
        "service:alerts:last_broadcast_at": "1700000000",
        "service:alerts:last_alert_info": json.dumps(
            {"district": "kyiv", "type": "air_raid_alert"}
        ),
        "service:alerts:active_source": "api",
    }.get(key)

    with patch.object(alerts_main, "redis_client", mock_redis):
        with patch.object(alerts_main, "pg_pool", None):
            await alerts_main._restore_stored_alert_payload()
            assert alerts_main.last_broadcast_at == 1700000000.0
            assert alerts_main.active_source_name == "api"
            assert alerts_main.last_alert_payload["district"] == "kyiv"


@pytest.mark.asyncio
async def test_restore_stored_alert_payload_pg_fallback():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    fake_row = {
        "recorded_at": datetime.datetime(2026, 9, 23, 12, 0, 0, tzinfo=datetime.timezone.utc),
        "district": "bucha",
        "event_type": "air_raid_alert",
        "level": "red",
        "message_id": 123,
        "source": "api",
    }
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = fake_row
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch.object(alerts_main, "redis_client", mock_redis):
        with patch.object(alerts_main, "pg_pool", mock_pool):
            alerts_main.last_alert_payload = None
            await alerts_main._restore_stored_alert_payload()
            assert alerts_main.last_alert_payload is not None
            assert alerts_main.last_alert_payload["district"] == "bucha"
            assert alerts_main.last_alert_payload["level"] == "red"


@pytest.mark.asyncio
async def test_prime_api_state_success():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_regions = AsyncMock(return_value={"states": []})
    mock_api.get_status = AsyncMock(return_value=100)
    mock_api.get_active_alerts = AsyncMock(
        return_value=[
            {
                "regionId": "31",
                "regionType": "State",
                "activeAlerts": [{"type": "AIR", "activeAlertLevels": [{"alertLevel": "Red"}]}],
            }
        ]
    )

    with patch.object(alerts_main, "redis_client", AsyncMock()):
        with patch.object(
            alerts_main, "spawn_tracked_task", side_effect=lambda c, d: c.close()
        ) as mock_spawn:
            await alerts_main._prime_api_state(mock_api)
            assert alerts_main.last_action_index == 100
            assert "kyiv" in alerts_main.active_threats_by_district
            assert alerts_main.last_api_poll_at is not None
            mock_spawn.assert_called_once()


@pytest.mark.asyncio
async def test_prime_api_state_clears_stuck_alerts():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_regions = AsyncMock(return_value={"states": []})
    mock_api.get_status = AsyncMock(return_value=100)
    mock_api.get_active_alerts = AsyncMock(return_value=[])

    fake_row = {
        "district": "bucha",
        "event_type": "air_raid_alert",
        "level": "red",
        "recorded_at": datetime.datetime(2026, 9, 23, 12, 0, tzinfo=datetime.timezone.utc),
    }
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [fake_row]
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    spawned_tasks = []

    def mock_spawn(coro, desc):
        spawned_tasks.append(desc)
        coro.close()

    with patch.object(alerts_main, "redis_client", AsyncMock()):
        with patch.object(alerts_main, "pg_pool", mock_pool):
            with patch.object(alerts_main, "spawn_tracked_task", side_effect=mock_spawn):
                await alerts_main._prime_api_state(mock_api, region_channels={"bucha": 12345})

                assert any(
                    "Startup clearance of air_raid_alert_cancelled" in desc
                    for desc in spawned_tasks
                )


@pytest.mark.asyncio
async def test_prime_api_state_api_errors_graceful():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_regions = AsyncMock(side_effect=Exception("network down"))
    mock_api.get_status = AsyncMock(side_effect=Exception("network down"))
    mock_api.get_active_alerts = AsyncMock(side_effect=Exception("network down"))

    with patch.object(alerts_main, "redis_client", AsyncMock()):
        with patch.object(alerts_main, "spawn_tracked_task", side_effect=lambda c, d: c.close()):
            await alerts_main._prime_api_state(mock_api)


@pytest.mark.asyncio
async def test_api_poll_loop_trigger_and_cancel():
    mock_api = MagicMock(spec=UkraineAlarmClient)

    mock_api.get_status = AsyncMock(side_effect=[101, 102, asyncio.CancelledError()])

    alerts_1 = [
        {
            "regionId": "101",
            "regionType": "District",
            "regionName": "Бучанський район",
            "activeAlerts": [{"type": "AIR"}],
        }
    ]
    alerts_2 = []
    mock_api.get_active_alerts = AsyncMock(side_effect=[alerts_1, alerts_2])

    region_channels = {"bucha": 12345}

    with patch.object(alerts_main, "UKRAINE_ALARM_POLL_INTERVAL", 0.001):
        with patch.object(alerts_main, "send_alert", new_callable=AsyncMock) as mock_send_alert:
            with patch.object(alerts_main, "record_map_only_alert", new_callable=AsyncMock):
                with patch.object(alerts_main, "record_source_message", new_callable=AsyncMock):
                    await alerts_main._api_poll_loop(mock_api, region_channels)

                    assert mock_send_alert.call_count >= 2
                    call_types = [call.args[2] for call in mock_send_alert.call_args_list]
                    assert "air_raid_alert" in call_types
                    assert "air_raid_alert_cancelled" in call_types


@pytest.mark.asyncio
async def test_api_poll_loop_map_only():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(side_effect=[101, asyncio.CancelledError()])

    alerts_1 = [
        {
            "regionId": "999",
            "regionType": "District",
            "regionName": "Вараський район",
            "activeAlerts": [{"type": "AIR"}],
        }
    ]
    mock_api.get_active_alerts = AsyncMock(return_value=alerts_1)
    region_channels = {}

    with patch.object(alerts_main, "UKRAINE_ALARM_POLL_INTERVAL", 0.001):
        with patch.object(
            alerts_main, "record_map_only_alert", new_callable=AsyncMock
        ) as mock_map_alert:
            with patch.object(alerts_main, "record_source_message", new_callable=AsyncMock):
                await alerts_main._api_poll_loop(mock_api, region_channels)
                assert mock_map_alert.call_count >= 1
                assert mock_map_alert.call_args.args[0] == "varash"
                assert mock_map_alert.call_args.args[1] == "air_raid_alert"


@pytest.mark.asyncio
async def test_api_poll_loop_auth_error_pings_fail():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(
        side_effect=[UkraineAlarmAuthError("401"), asyncio.CancelledError()]
    )

    with patch.object(alerts_main, "UKRAINE_ALARM_POLL_INTERVAL", 0.001):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch.object(alerts_main, "_ping_healthcheck") as mock_ping_hc:
                await alerts_main._api_poll_loop(mock_api, {})
                mock_ping_hc.assert_called_with("/fail")


@pytest.mark.asyncio
async def test_healthcheck_loop_with_api():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(return_value=100)

    call_count = 0

    async def fake_sleep(duration):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with patch.object(alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "http://hc/ping"):
            with patch.object(alerts_main, "_ping_healthcheck") as mock_ping_hc:
                with pytest.raises(asyncio.CancelledError):
                    await alerts_main._healthcheck_loop(api_cli=mock_api)
                assert mock_ping_hc.call_count >= 1


@pytest.mark.asyncio
async def test_healthcheck_loop_with_api_auth_error():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(side_effect=UkraineAlarmAuthError("401"))

    call_count = 0

    async def fake_sleep(duration):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with patch.object(alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "http://hc/ping"):
            with patch.object(alerts_main, "_ping_healthcheck") as mock_ping_hc:
                with pytest.raises(asyncio.CancelledError):
                    await alerts_main._healthcheck_loop(api_cli=mock_api)
                mock_ping_hc.assert_called_with("/fail")


@pytest.mark.asyncio
async def test_healthcheck_loop_with_api_silence_fail():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(side_effect=Exception("api timeout"))

    call_count = 0

    async def fake_sleep(duration):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    alerts_main.last_source_message_at = time.time() - 20000

    with patch("asyncio.sleep", side_effect=fake_sleep):
        with patch.object(alerts_main, "HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "http://hc/ping"):
            with patch.object(alerts_main, "_ping_healthcheck") as mock_ping_hc:
                with pytest.raises(asyncio.CancelledError):
                    await alerts_main._healthcheck_loop(api_cli=mock_api)
                mock_ping_hc.assert_called_with("/fail")


@pytest.mark.asyncio
async def test_api_poll_loop_rate_limit_and_network_error():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(
        side_effect=[
            UkraineAlarmRateLimitError("429", retry_after=0.01),
            UkraineAlarmNetworkError("net err"),
            asyncio.CancelledError(),
        ]
    )

    with patch.object(alerts_main, "UKRAINE_ALARM_POLL_INTERVAL", 0.001):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await alerts_main._api_poll_loop(mock_api, {})
            assert mock_api.get_status.await_count == 3


@pytest.mark.asyncio
async def test_api_poll_loop_alerts_fetch_exception():
    mock_api = MagicMock(spec=UkraineAlarmClient)
    mock_api.get_status = AsyncMock(side_effect=[101, asyncio.CancelledError()])
    mock_api.get_active_alerts = AsyncMock(side_effect=Exception("fetch failed"))

    with patch.object(alerts_main, "UKRAINE_ALARM_POLL_INTERVAL", 0.001):
        with patch.object(alerts_main, "record_source_message", new_callable=AsyncMock):
            await alerts_main._api_poll_loop(mock_api, {})
            mock_api.get_active_alerts.assert_called_once()


@pytest.mark.asyncio
async def test_main_with_ukraine_alarm_api_key():
    mock_tg = AsyncMock()
    mock_tg.is_user_authorized.return_value = True
    mock_tg.run_until_disconnected = AsyncMock(return_value=None)
    mock_tg.__aenter__.return_value = mock_tg
    mock_tg.__aexit__.return_value = None

    with patch.object(alerts_main, "UKRAINE_ALARM_API_KEY", "test_key"):
        with patch("alerts.main.TelegramClient", return_value=mock_tg):
            with patch.object(alerts_main, "redis"):
                with patch.object(alerts_main, "asyncpg"):
                    with patch("alerts.main.ensure_pg_tables"):
                        with patch("alerts.main.rehydrate_state_from_db"):
                            with patch.object(
                                alerts_main, "_prime_api_state", new_callable=AsyncMock
                            ) as mock_prime:
                                with patch.object(
                                    alerts_main, "_api_poll_loop", new_callable=AsyncMock
                                ):
                                    with patch.object(
                                        alerts_main, "_healthcheck_loop", new_callable=AsyncMock
                                    ):
                                        with patch.object(
                                            alerts_main,
                                            "_broadcast_watchdog_loop",
                                            new_callable=AsyncMock,
                                        ):
                                            with patch(
                                                "alerts.main.cli.get_args",
                                                return_value=MagicMock(mode="dev"),
                                            ):
                                                await alerts_main.main()
                                                mock_prime.assert_called_once()
