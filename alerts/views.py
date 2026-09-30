"""
View counts of broadcast alerts and all-clears.

Every air raid alert and all-clear the worker posts is sampled at fixed offsets
from its publication (CHECKPOINTS). An alert is only sampled while it is still
the channel's open alert: once the all-clear (or a newer alert that replaces
it) goes out, its remaining checkpoints are dropped, so a row at 1800 s means
the alert really lasted that long. All-clears are sampled on every checkpoint.

The schedule lives in a Redis sorted set scored by due time, so a worker
restart picks up where it left off. A sample that can no longer be taken close
enough to its checkpoint (see max_lateness) is dropped instead of being stored
with a misleading offset.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import NamedTuple

from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetMessagesViewsRequest

log = logging.getLogger(__name__)

CHECKPOINTS = (15, 30, 60, 300, 900, 1800)
TRACKED_EVENTS = ("air_raid_alert", "air_raid_alert_cancelled")

SCHEDULE_KEY = "views:schedule"
OPEN_ALERT_KEY = "views:open_alert:{channel_id}"
OPEN_ALERT_TTL = 7 * 24 * 3600

POLL_INTERVAL = 1.0
CHANNEL_DELAY = 0.2
BATCH_LIMIT = 500

INSERT_SQL = """
    INSERT INTO message_views
        (channel_id, message_id, event_type, checkpoint_s, posted_at, sampled_at, views)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (channel_id, message_id, checkpoint_s) DO NOTHING
"""


class Sample(NamedTuple):
    channel_id: int
    message_id: int
    event_type: str
    checkpoint: int
    posted_at: float

    @property
    def member(self) -> str:
        return (
            f"{self.channel_id}|{self.message_id}|{self.event_type}|"
            f"{self.checkpoint}|{self.posted_at:.3f}"
        )

    @property
    def due_at(self) -> float:
        return self.posted_at + self.checkpoint

    @classmethod
    def parse(cls, member: str) -> Sample | None:
        try:
            channel_id, message_id, event_type, checkpoint, posted_at = member.split("|")
            return cls(
                int(channel_id), int(message_id), event_type, int(checkpoint), float(posted_at)
            )
        except ValueError:
            return None


def max_lateness(checkpoint: int) -> float:
    """How late a sample may be taken and still count for its checkpoint."""
    return max(5.0, checkpoint * 0.2)


def posted_epoch(message) -> float:
    """Publication time from Telegram's own timestamp, falling back to now."""
    date = getattr(message, "date", None)
    if isinstance(date, datetime.datetime):
        if date.tzinfo is None:
            date = date.replace(tzinfo=datetime.timezone.utc)
        return date.timestamp()
    return time.time()


async def schedule(
    redis_client, channel_id: int, message_id: int, event_type: str, posted_at: float
) -> None:
    """Queues every checkpoint for a freshly broadcast message."""
    if not redis_client or event_type not in TRACKED_EVENTS:
        return

    samples = [Sample(channel_id, message_id, event_type, c, posted_at) for c in CHECKPOINTS]
    open_key = OPEN_ALERT_KEY.format(channel_id=channel_id)
    try:
        if event_type == "air_raid_alert":
            await redis_client.set(open_key, str(message_id), ex=OPEN_ALERT_TTL)
        else:
            await redis_client.delete(open_key)
        await redis_client.zadd(SCHEDULE_KEY, {s.member: s.due_at for s in samples})
    except Exception:
        log.warning("Failed to schedule view sampling for message %d", message_id, exc_info=True)


class Collector:
    """Takes the samples that have come due, batching one request per channel."""

    def __init__(self, client, redis_client, pg_pool):
        self.client = client
        self.redis = redis_client
        self.pg_pool = pg_pool
        self.paused_until = 0.0

    async def _is_open_alert(self, sample: Sample) -> bool:
        open_id = await self.redis.get(OPEN_ALERT_KEY.format(channel_id=sample.channel_id))
        return open_id == str(sample.message_id)

    async def _fetch_views(self, channel_id: int, message_ids: list[int]) -> dict[int, int]:
        result = await self.client(
            GetMessagesViewsRequest(peer=channel_id, id=message_ids, increment=False),
            flood_sleep_threshold=0,
        )
        return {
            message_id: item.views
            for message_id, item in zip(message_ids, result.views, strict=False)
            if item.views is not None
        }

    async def _store(self, rows: list[tuple]) -> None:
        if not rows or not self.pg_pool:
            return
        async with self.pg_pool.acquire() as conn:
            await conn.executemany(INSERT_SQL, rows)

    async def run_once(self, now: float | None = None) -> int:
        """Processes due samples; returns how many rows were stored."""
        if not self.redis:
            return 0
        now = time.time() if now is None else now
        if now < self.paused_until:
            return 0

        members = await self.redis.zrangebyscore(
            SCHEDULE_KEY, "-inf", now, start=0, num=BATCH_LIMIT
        )
        if not members:
            return 0

        done: list[str] = []
        by_channel: dict[int, list[Sample]] = {}
        for member in members:
            sample = Sample.parse(member)
            if sample is None:
                log.warning("Dropping malformed view sample %r", member)
                done.append(member)
                continue
            if now - sample.due_at > max_lateness(sample.checkpoint):
                log.warning(
                    "Dropping %ds view sample of message %d in channel %d: %.0fs late",
                    sample.checkpoint,
                    sample.message_id,
                    sample.channel_id,
                    now - sample.due_at,
                )
                done.append(member)
                continue
            if sample.event_type == "air_raid_alert" and not await self._is_open_alert(sample):
                done.append(member)
                continue
            by_channel.setdefault(sample.channel_id, []).append(sample)

        stored = 0
        for index, (channel_id, samples) in enumerate(by_channel.items()):
            if index:
                await asyncio.sleep(CHANNEL_DELAY)
            message_ids = sorted({s.message_id for s in samples})
            try:
                views = await self._fetch_views(channel_id, message_ids)
            except FloodWaitError as e:
                log.warning("View sampling rate-limited for %ds; pausing it", e.seconds)
                self.paused_until = time.time() + e.seconds
                break
            except Exception:
                log.warning("Failed to read views in channel %d", channel_id, exc_info=True)
                continue

            sampled_at = datetime.datetime.now(datetime.timezone.utc)
            rows = [
                (
                    s.channel_id,
                    s.message_id,
                    s.event_type,
                    s.checkpoint,
                    datetime.datetime.fromtimestamp(s.posted_at, datetime.timezone.utc),
                    sampled_at,
                    views[s.message_id],
                )
                for s in samples
                if s.message_id in views
            ]
            try:
                await self._store(rows)
            except Exception:
                log.warning(
                    "Failed to store view samples for channel %d", channel_id, exc_info=True
                )
                continue
            stored += len(rows)
            done.extend(s.member for s in samples)

        if done:
            await self.redis.zrem(SCHEDULE_KEY, *done)
        return stored


async def views_loop(client, redis_client, pg_pool) -> None:
    collector = Collector(client, redis_client, pg_pool)
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        if not client or not client.is_connected():
            continue
        try:
            await collector.run_once()
        except Exception:
            log.exception("View sampling iteration failed")
