"""
Sirens - subscriber count snapshot.

Counts every channel in the network and writes one row per channel per day.
One-shot by design: scheduling lives in cron (deploy/bi.sh), so nothing stays
resident on a server with under 200 MB to spare. See "Channel Statistics" in
README.md.
"""

import asyncio
import datetime
import logging
import csv
import io
import os
import sys
from typing import NamedTuple

import asyncpg
import boto3
import requests
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

from bi import cli

from config import (
    api_id, api_hash, SESSION_PATH, DATABASE_URL, SENTRY_DSN, VERSION,
    REGION_CONFIG, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, CLOUDFLARE_ACCOUNT_ID,
    R2_DATA_BUCKET, R2_BUCKET, R2_ENDPOINT, GITHUB_PAT, GITHUB_REPO
)

from web.db import ensure_pg_tables


# stdout only: deploy/bi.sh owns logs/bi.log, and a second writer with its own
# rotation would interleave badly with the shell's output.
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
logging.getLogger("telethon").setLevel(logging.WARNING)

# The alerts worker holds sirens.session. One session file cannot serve two
# running processes: that means SQLite lock contention and a real risk of
# AuthKeyDuplicatedError, which alerts treats as fatal.
SESSION_NAME = "bi"

# The source channel is somebody else's: we read alerts from it, it is not part
# of the network we publish to.
SOURCE_KEY = "source"

MAX_ATTEMPTS = 3
CHANNEL_DELAY = 1  # seconds; pacing 35 calls costs nothing on a job with no deadline

# A FloodWait this long is Telegram asking for hours, not seconds. Waiting it
# out would hold deploy/bi.sh's lock past the next night's run, so one bad
# evening would silently swallow several days.
MAX_FLOOD_WAIT = 300  # seconds

# A day's total is only meaningful next to the days around it. Below this share
# of the network the run is discarded rather than stored: a gap in the chart is
# obvious, whereas a short day reads as subscribers walking away.
MIN_COVERAGE = 0.9

INSERT_SQL = """
    INSERT INTO subscribers (channel_key, channel_id, subscribers, date, collected_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (channel_key, date) DO UPDATE
        SET subscribers = EXCLUDED.subscribers,
            channel_id   = EXCLUDED.channel_id,
            collected_at = EXCLUDED.collected_at
"""


class ChannelCount(NamedTuple):
    channel_key: str
    channel_id: int
    subscribers: int


def targets(channels: dict) -> list[tuple[str, int]]:
    """The (key, id) pairs worth counting.

    Drops the foreign source channel, and counts an id once however many keys
    point at it - in dev mode nearly every city shares one test channel, which
    would otherwise report a network thirty times its real size.
    """
    seen: set[int] = set()
    picked: list[tuple[str, int]] = []

    for channel_key, channel_id in channels.items():
        if channel_key == SOURCE_KEY or channel_id in seen:
            continue
        seen.add(channel_id)
        picked.append((channel_key, channel_id))

    return picked


async def fetch_subscribers(client: TelegramClient, channel_id: int) -> int | None:
    """Subscriber count for one channel, or None if it could not be read.

    Only a short FloodWaitError is retried: it says exactly how long to wait and
    then succeeds. Anything else (channel gone, lost admin rights) will not fix
    itself within seconds, and the snapshot runs again tomorrow anyway.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            full = await client(GetFullChannelRequest(channel=channel_id))
            return full.full_chat.participants_count
        except FloodWaitError as e:
            if e.seconds > MAX_FLOOD_WAIT:
                log.error(
                    "Rate-limited on channel %d for %ds, past the %ds cap; skipping it",
                    channel_id, e.seconds, MAX_FLOOD_WAIT
                )
                return None
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


fetch_participants = fetch_subscribers


async def collect(client: TelegramClient, channels: dict) -> list[ChannelCount]:
    """Count every network channel. One unreadable channel does not stop the run."""
    counts: list[ChannelCount] = []

    for channel_key, channel_id in targets(channels):
        subscribers = await fetch_subscribers(client, channel_id)
        if subscribers is None:
            continue

        counts.append(ChannelCount(channel_key, channel_id, subscribers))
        await asyncio.sleep(CHANNEL_DELAY)

    return counts


async def store(pool, counts: list[ChannelCount]) -> None:
    now = datetime.datetime.now()
    rows = [
        (c.channel_key, c.channel_id, c.subscribers, now.date(), now)
        for c in counts
    ]

    async with pool.acquire() as conn:
        await conn.executemany(INSERT_SQL, rows)


SELECT_ALL_STATS_SQL = """
    SELECT channel_key, date, subscribers
    FROM subscribers
    ORDER BY date, channel_key
"""

STATS_CSV_COLUMNS = ("channel_key", "display_name", "date", "subscribers")


async def export_stats_csv(pool) -> str:
    """The whole subscribers table as CSV, oldest day first.

    Assembled in Python so the human-readable city names from REGION_CONFIG
    can be folded in.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(SELECT_ALL_STATS_SQL)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(STATS_CSV_COLUMNS)

    for record in rows:
        channel_key = record["channel_key"]
        date_val = record["date"]
        subscribers = record["subscribers"]
        display_name = REGION_CONFIG.get(channel_key, {}).get("display_name", channel_key)
        date_str = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        writer.writerow([channel_key, display_name, date_str, subscribers])

    return buffer.getvalue()


export_subscribers_csv = export_stats_csv


def upload_to_r2(csv_content: str) -> None:
    """Uploads the consolidated CSV to the Cloudflare R2 data bucket."""
    if not (R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and (R2_ENDPOINT or CLOUDFLARE_ACCOUNT_ID)):
        log.warning("R2 credentials not set; skipping upload to R2")
        return

    endpoint = R2_ENDPOINT or f"https://{CLOUDFLARE_ACCOUNT_ID}.eu.r2.cloudflarestorage.com"
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    bucket = R2_DATA_BUCKET or R2_BUCKET
    key = "subscribers.csv"
    log.info("Uploading subscribers CSV to s3://%s/%s (%d bytes)", bucket, key, len(csv_content.encode("utf-8")))
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv; charset=utf-8",
    )
    log.info("Successfully uploaded subscribers CSV to R2 data bucket %s", bucket)




def trigger_dashboard_build() -> None:
    """Triggers GitHub Actions workflow_dispatch to build the dashboard immediately."""
    if not GITHUB_PAT or not GITHUB_REPO:
        log.info("GITHUB_PAT or GITHUB_REPO not set; skipping dashboard build trigger")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/dashboard.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data = {"ref": "main"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code in (204, 201, 200):
            log.info("Triggered GitHub Actions dashboard workflow successfully")
        else:
            log.warning("Failed to trigger dashboard workflow (HTTP %d): %s", resp.status_code, resp.text)
    except Exception:
        log.exception("Exception while triggering GitHub Actions dashboard workflow")


async def run_snapshot(client: TelegramClient, pool, channels: dict) -> int:
    """Collect and store, returning the process exit code."""
    expected = len(targets(channels))

    counts = await collect(client, channels)

    if not counts:
        # Not a quiet no-op: it means the session died or Telegram is
        # unreachable, and the dashboard would keep showing yesterday's numbers
        # as if they were today's.
        log.error("Snapshot collected no channels at all")
        return 1

    if len(counts) < expected * MIN_COVERAGE:
        log.error(
            "Snapshot reached only %d of %d channels; discarding it rather than "
            "storing a day that reads as a subscriber collapse. Re-running fills "
            "the day in once the cause is fixed",
            len(counts), expected
        )
        return 1

    await store(pool, counts)

    total = sum(c.subscribers for c in counts)
    log.info(
        "Snapshot done: %d/%d channels, %d subscribers in total",
        len(counts), expected, total
    )


    csv_data = await export_stats_csv(pool)
    await asyncio.to_thread(upload_to_r2, csv_data)
    await asyncio.to_thread(trigger_dashboard_build)

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
        # Entering the client logs in, prompting for a phone number and code when
        # the session is missing - that is how ./deploy/setup.sh bi creates it.
        # Under cron there is no stdin, so the prompt raises instead of hanging.
        # Telegram comes before the database deliberately: creating the session
        # must not also require a healthy db container.
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
