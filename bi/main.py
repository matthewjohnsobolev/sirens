"""
Sirens - Subscriber Count Snapshot.

Takes a daily snapshot of the subscriber count of every channel in the Sirens
network and stores one row per channel per day.

This is a one-shot process: it counts, writes, and exits. Scheduling lives in
cron (deploy/bi.sh), which runs it every morning at 09:00 Kyiv time. A process
that instead slept until the next morning would hold ~100 MB on a server with
under 200 MB to spare, and would tie the snapshot to a daemon that must never
go down for reasons of its own.
"""

import asyncio
import datetime
import logging
import os
import sys
from typing import NamedTuple

import asyncpg
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

from bi import cli

from config import (
    api_id, api_hash, SESSION_PATH, DATABASE_URL, SENTRY_DSN, VERSION
)
from web.db import ensure_pg_tables

# Logging goes to stdout only. The container is started by deploy/bi.sh, which
# owns logs/bi.log - a second writer with its own rotation would interleave
# badly with the shell's own output.
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
logging.getLogger("telethon").setLevel(logging.WARNING)

# The alerts worker holds data/sessions/sirens.session. Sharing one session file
# between two processes means SQLite lock contention and a real risk of
# AuthKeyDuplicatedError, which alerts treats as fatal - so the snapshot logs
# in as its own session. Several sessions per account is normal for Telegram.
SESSION_NAME = "bi"

# The source channel is somebody else's: we read alerts from it, it is not part
# of the network we publish to.
SOURCE_KEY = "source"

MAX_ATTEMPTS = 3
CHANNEL_DELAY = 1  # seconds; 35 calls once a day is nowhere near any limit,
                   # but pacing them costs nothing on a job with no deadline

INSERT_SQL = """
    INSERT INTO channel_stats (channel_key, channel_id, participants, date, collected_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (channel_key, date) DO UPDATE
        SET participants = EXCLUDED.participants,
            channel_id   = EXCLUDED.channel_id,
            collected_at = EXCLUDED.collected_at
"""


class ChannelCount(NamedTuple):
    channel_key: str
    channel_id: int
    participants: int


async def fetch_participants(client: TelegramClient, channel_id: int) -> int | None:
    """Subscriber count for one channel, or None if it could not be read.

    Only FloodWaitError is retried: it says exactly how long to wait and then
    succeeds. Anything else (channel gone, lost admin rights) will not fix
    itself within seconds, and the snapshot runs again tomorrow anyway.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            full = await client(GetFullChannelRequest(channel=channel_id))
            return full.full_chat.participants_count
        except FloodWaitError as e:
            log.warning(
                "Rate-limited on channel %d (attempt %d/%d), waiting %ds",
                channel_id, attempt, MAX_ATTEMPTS, e.seconds
            )
            await asyncio.sleep(e.seconds)
        except Exception:
            log.exception("Failed to read subscriber count for channel %d", channel_id)
            return None

    log.error("Giving up on channel %d after %d attempts", channel_id, MAX_ATTEMPTS)
    return None


async def collect(client: TelegramClient, channels: dict) -> list[ChannelCount]:
    """Count every network channel. One unreadable channel does not stop the run."""
    counts: list[ChannelCount] = []
    seen: set[int] = set()

    for channel_key, channel_id in channels.items():
        if channel_key == SOURCE_KEY:
            continue

        if channel_id in seen:
            # In dev mode most keys point at the same test channel; counting it
            # once per key would report a network thirty times its real size.
            log.debug("Skipping %s: channel %d already counted", channel_key, channel_id)
            continue

        seen.add(channel_id)

        participants = await fetch_participants(client, channel_id)
        if participants is None:
            continue

        counts.append(ChannelCount(channel_key, channel_id, participants))
        await asyncio.sleep(CHANNEL_DELAY)

    return counts


async def store(pool, counts: list[ChannelCount]) -> None:
    now = datetime.datetime.now()
    rows = [
        (c.channel_key, c.channel_id, c.participants, now.date(), now)
        for c in counts
    ]

    async with pool.acquire() as conn:
        await conn.executemany(INSERT_SQL, rows)


async def run_snapshot(client: TelegramClient, pool, channels: dict) -> int:
    """Collect and store, returning the process exit code."""
    expected = len([key for key in channels if key != SOURCE_KEY])

    counts = await collect(client, channels)

    if not counts:
        # Storing nothing is not a quiet no-op: it means the session died or
        # Telegram is unreachable, and the dashboard would silently show
        # yesterday's numbers as if they were today's.
        log.error("Snapshot collected no channels at all")
        return 1

    await store(pool, counts)

    total = sum(c.participants for c in counts)
    log.info(
        "Snapshot done: %d/%d channels, %d subscribers in total",
        len(counts), expected, total
    )
    return 0


async def main() -> int:
    args = cli.get_args()
    channels = cli.get_mode_config(args)

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.WARNING)],
        environment=args.mode,
        release=VERSION,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", "bi")

    os.makedirs(SESSION_PATH, exist_ok=True)
    session_file = os.path.join(SESSION_PATH, SESSION_NAME)

    try:
        # Entering the client logs in, prompting for a phone number and code
        # when the session is missing - that is how ./deploy/setup.sh bi creates
        # it. Under cron there is no stdin, so the prompt raises instead of
        # hanging forever. Telegram comes before the database deliberately:
        # creating the session must not also require a healthy db container.
        async with TelegramClient(session_file, api_id, api_hash) as client:
            await asyncio.to_thread(ensure_pg_tables)
            pool = await asyncpg.create_pool(DATABASE_URL)
            try:
                return await run_snapshot(client, pool, channels)
            finally:
                await pool.close()
    except EOFError:
        log.error(
            "Telegram session '%s' is missing or expired; create it with "
            "./deploy/setup.sh %s", SESSION_NAME, SESSION_NAME
        )
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
