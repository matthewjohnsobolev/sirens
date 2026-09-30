import asyncio
import datetime
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon.errors import FloodWaitError

from alerts import views
from alerts.views import (
    CHECKPOINTS,
    OPEN_ALERT_KEY,
    SCHEDULE_KEY,
    Collector,
    Sample,
    max_lateness,
    posted_epoch,
    schedule,
    views_loop,
)

CHANNEL_ID = -1001234567890
OTHER_CHANNEL_ID = -1009876543210
POSTED_AT = 1_790_000_000.0


class FakeRedis:
    """Just enough of redis.asyncio for the schedule: strings and one sorted set."""

    def __init__(self):
        self.strings: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    async def set(self, key, value, ex=None):
        self.strings[key] = value

    async def get(self, key):
        return self.strings.get(key)

    async def delete(self, key):
        self.strings.pop(key, None)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    async def zrangebyscore(self, key, low, high, start=0, num=None):
        members = sorted(self.zsets.get(key, {}).items(), key=lambda item: item[1])
        due = [m for m, score in members if score <= high]
        return due[start : start + num if num else None]

    async def zrem(self, key, *members):
        for member in members:
            self.zsets.get(key, {}).pop(member, None)

    def pending(self) -> list[Sample]:
        return sorted(
            (Sample.parse(m) for m in self.zsets.get(SCHEDULE_KEY, {})),
            key=lambda s: (s.message_id, s.checkpoint),
        )


def views_result(*counts):
    return MagicMock(views=[MagicMock(views=c) for c in counts])


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def tg_client():
    client = AsyncMock()
    client.is_connected = MagicMock(return_value=True)
    return client


@pytest.fixture
def collector(tg_client, fake_redis, bi_pool):
    pool, _ = bi_pool
    return Collector(tg_client, fake_redis, pool)


def test_sample_round_trips_through_its_member():
    sample = Sample(CHANNEL_ID, 42, "air_raid_alert", 300, POSTED_AT)

    assert Sample.parse(sample.member) == sample
    assert sample.due_at == POSTED_AT + 300


def test_sample_parse_rejects_malformed_members():
    assert Sample.parse("garbage") is None
    assert Sample.parse("a|b|c|d|e") is None


def test_max_lateness_scales_with_checkpoint():
    assert max_lateness(15) == 5.0
    assert max_lateness(1800) == 360.0


def test_posted_epoch_uses_telegram_date():
    aware = datetime.datetime(2026, 9, 30, 12, 0, tzinfo=datetime.timezone.utc)
    naive = datetime.datetime(2026, 9, 30, 12, 0)

    assert posted_epoch(MagicMock(date=aware)) == aware.timestamp()
    assert posted_epoch(MagicMock(date=naive)) == aware.timestamp()


def test_posted_epoch_falls_back_to_now():
    with patch("alerts.views.time.time", return_value=123.0):
        assert posted_epoch(MagicMock(date=None)) == 123.0


@pytest.mark.asyncio
async def test_schedule_alert_queues_every_checkpoint_and_opens_it(fake_redis):
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)

    assert [s.checkpoint for s in fake_redis.pending()] == list(CHECKPOINTS)
    assert fake_redis.strings[OPEN_ALERT_KEY.format(channel_id=CHANNEL_ID)] == "42"


@pytest.mark.asyncio
async def test_schedule_all_clear_closes_the_open_alert(fake_redis):
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)
    await schedule(fake_redis, CHANNEL_ID, 43, "air_raid_alert_cancelled", POSTED_AT + 100)

    assert OPEN_ALERT_KEY.format(channel_id=CHANNEL_ID) not in fake_redis.strings
    assert len(fake_redis.pending()) == 2 * len(CHECKPOINTS)


@pytest.mark.asyncio
async def test_schedule_ignores_untracked_events_and_missing_redis(fake_redis):
    await schedule(fake_redis, CHANNEL_ID, 42, "threat_of_shelling", POSTED_AT)
    await schedule(None, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)

    assert fake_redis.pending() == []


@pytest.mark.asyncio
async def test_schedule_survives_redis_errors(caplog):
    caplog.set_level(logging.WARNING)
    broken = AsyncMock()
    broken.set.side_effect = ConnectionError("down")

    await schedule(broken, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)

    assert "Failed to schedule view sampling for message 42" in caplog.text


@pytest.mark.asyncio
async def test_collector_samples_due_checkpoints_only(collector, fake_redis, tg_client, bi_pool):
    _, conn = bi_pool
    tg_client.return_value = views_result(120)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)

    assert await collector.run_once(now=POSTED_AT + 14) == 0
    tg_client.assert_not_awaited()

    assert await collector.run_once(now=POSTED_AT + 16) == 1
    request = tg_client.call_args.args[0]
    assert request.id == [42]
    assert request.increment is False
    assert tg_client.call_args.kwargs == {"flood_sleep_threshold": 0}
    (row,) = conn.executemany.call_args.args[1]
    assert row[:4] == (CHANNEL_ID, 42, "air_raid_alert", 15)
    assert row[4] == datetime.datetime.fromtimestamp(POSTED_AT, datetime.timezone.utc)
    assert row[6] == 120
    assert [s.checkpoint for s in fake_redis.pending()] == [30, 60, 300, 900, 1800]


@pytest.mark.asyncio
async def test_collector_stops_sampling_an_alert_after_its_all_clear(
    collector, fake_redis, tg_client, bi_pool
):
    _, conn = bi_pool
    tg_client.return_value = views_result(80)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)
    for offset in (15, 30):
        await collector.run_once(now=POSTED_AT + offset)
    await schedule(fake_redis, CHANNEL_ID, 43, "air_raid_alert_cancelled", POSTED_AT + 45)

    await collector.run_once(now=POSTED_AT + 60)

    assert tg_client.call_args.args[0].id == [43]
    rows = conn.executemany.call_args.args[1]
    assert [(r[1], r[3]) for r in rows] == [(43, 15)]

    for checkpoint in (300, 900, 1800):
        await collector.run_once(now=POSTED_AT + checkpoint)
    assert all(s.message_id == 43 for s in fake_redis.pending())
    assert [c.args[0].id for c in tg_client.call_args_list] == [[42], [42], [43]]


@pytest.mark.asyncio
async def test_collector_stops_sampling_a_replaced_alert(collector, fake_redis, tg_client):
    tg_client.return_value = views_result(10)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert", POSTED_AT)
    await schedule(fake_redis, CHANNEL_ID, 44, "air_raid_alert", POSTED_AT + 45)

    await collector.run_once(now=POSTED_AT + 60)

    assert tg_client.call_args.args[0].id == [44]
    assert 42 not in {s.message_id for s in fake_redis.pending() if s.checkpoint <= 60}


@pytest.mark.asyncio
async def test_collector_batches_one_request_per_channel(collector, fake_redis, tg_client):
    tg_client.side_effect = [views_result(5, 7), views_result(9)]
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)
    await schedule(fake_redis, CHANNEL_ID, 43, "air_raid_alert_cancelled", POSTED_AT + 2)
    await schedule(fake_redis, OTHER_CHANNEL_ID, 7, "air_raid_alert_cancelled", POSTED_AT)

    with patch("alerts.views.asyncio.sleep", new_callable=AsyncMock) as sleep:
        stored = await collector.run_once(now=POSTED_AT + 17)

    assert stored == 3
    assert [c.args[0].id for c in tg_client.call_args_list] == [[42, 43], [7]]
    sleep.assert_awaited_once_with(views.CHANNEL_DELAY)


@pytest.mark.asyncio
async def test_collector_drops_samples_that_are_too_late(collector, fake_redis, tg_client, caplog):
    caplog.set_level(logging.WARNING)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    stored = await collector.run_once(now=POSTED_AT + 45)

    assert stored == 0
    tg_client.assert_not_awaited()
    assert [s.checkpoint for s in fake_redis.pending()] == [60, 300, 900, 1800]
    assert "Dropping 15s view sample of message 42" in caplog.text


@pytest.mark.asyncio
async def test_collector_drops_malformed_members(collector, fake_redis, caplog):
    caplog.set_level(logging.WARNING)
    await fake_redis.zadd(SCHEDULE_KEY, {"garbage": 0})

    await collector.run_once(now=POSTED_AT)

    assert fake_redis.zsets[SCHEDULE_KEY] == {}
    assert "Dropping malformed view sample" in caplog.text


@pytest.mark.asyncio
async def test_collector_skips_messages_without_views(collector, fake_redis, tg_client, bi_pool):
    _, conn = bi_pool
    tg_client.return_value = views_result(None)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    assert await collector.run_once(now=POSTED_AT + 15) == 0
    conn.executemany.assert_not_awaited()
    assert fake_redis.pending()[0].checkpoint == 30


@pytest.mark.asyncio
async def test_collector_pauses_on_flood_wait(collector, fake_redis, tg_client):
    tg_client.side_effect = FloodWaitError(request=None, capture=30)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    with patch("alerts.views.time.time", return_value=POSTED_AT + 15):
        assert await collector.run_once(now=POSTED_AT + 15) == 0
        assert collector.paused_until == POSTED_AT + 45
        assert await collector.run_once(now=POSTED_AT + 16) == 0

    assert tg_client.await_count == 1
    assert fake_redis.pending()[0].checkpoint == 15


@pytest.mark.asyncio
async def test_collector_retries_after_request_errors(collector, fake_redis, tg_client, caplog):
    caplog.set_level(logging.WARNING)
    tg_client.side_effect = [RuntimeError("boom"), views_result(3)]
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    assert await collector.run_once(now=POSTED_AT + 15) == 0
    assert "Failed to read views in channel" in caplog.text
    assert await collector.run_once(now=POSTED_AT + 16) == 1


@pytest.mark.asyncio
async def test_collector_retries_after_store_errors(
    collector, fake_redis, tg_client, bi_pool, caplog
):
    caplog.set_level(logging.WARNING)
    _, conn = bi_pool
    conn.executemany.side_effect = [RuntimeError("db down"), None]
    tg_client.return_value = views_result(3)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    assert await collector.run_once(now=POSTED_AT + 15) == 0
    assert "Failed to store view samples" in caplog.text
    assert await collector.run_once(now=POSTED_AT + 16) == 1


@pytest.mark.asyncio
async def test_collector_without_pool_still_consumes_samples(fake_redis, tg_client):
    tg_client.return_value = views_result(3)
    await schedule(fake_redis, CHANNEL_ID, 42, "air_raid_alert_cancelled", POSTED_AT)

    assert await Collector(tg_client, fake_redis, None).run_once(now=POSTED_AT + 15) == 1
    assert fake_redis.pending()[0].checkpoint == 30


@pytest.mark.asyncio
async def test_collector_is_idle_without_redis_or_due_samples(tg_client, fake_redis):
    assert await Collector(tg_client, None, None).run_once() == 0
    assert await Collector(tg_client, fake_redis, None).run_once() == 0
    tg_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_views_loop_runs_the_collector_while_connected(tg_client, caplog):
    tg_client.is_connected.side_effect = [False, True, True]
    run_once = AsyncMock(side_effect=[RuntimeError("boom"), asyncio.CancelledError()])

    with (
        patch("alerts.views.asyncio.sleep", new_callable=AsyncMock),
        patch.object(Collector, "run_once", run_once),
        pytest.raises(asyncio.CancelledError),
    ):
        await views_loop(tg_client, FakeRedis(), None)

    assert run_once.await_count == 2
    assert "View sampling iteration failed" in caplog.text
