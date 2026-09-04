"""Subscriber-count snapshot, one row per channel per day.

One-shot by design: scheduling is cron's job (deploy/bi.sh), so nothing stays
resident on a server with under 200 MB to spare.
"""

import asyncio
import csv
import datetime
import io
import logging
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
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_R2_ACCESS_KEY_ID,
    CLOUDFLARE_R2_BI_DATA_BUCKET,
    CLOUDFLARE_R2_S3_ENDPOINT,
    CLOUDFLARE_R2_SECRET_ACCESS_KEY,
    DATABASE_URL,
    GITHUB_PAT,
    GITHUB_REPO,
    SENTRY_DSN,
    SESSION_PATH,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    VERSION,
)
from domain import REGION_CONFIG
from web.db import ensure_pg_tables

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)
logging.getLogger("telethon").setLevel(logging.WARNING)

SESSION_NAME = "bi"
MAX_ATTEMPTS = 3
CHANNEL_DELAY = 1
MAX_FLOOD_WAIT = 300
MIN_COVERAGE = 0.9

INSERT_SQL = """
    INSERT INTO subscribers (channel_key, channel_id, subscribers, date, time)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (channel_key, time) DO UPDATE
        SET subscribers = EXCLUDED.subscribers,
            channel_id   = EXCLUDED.channel_id,
            date         = EXCLUDED.date
"""


class ChannelCount(NamedTuple):
    channel_key: str
    channel_id: int
    subscribers: int


def targets(channels: dict) -> list[tuple[str, int]]:
    seen: set[int] = set()
    picked: list[tuple[str, int]] = []

    for channel_key, channel_id in channels.items():
        if channel_id in seen:
            continue
        seen.add(channel_id)
        picked.append((channel_key, channel_id))

    return picked


async def fetch_subscribers(client: TelegramClient, channel_id: int) -> int | None:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            full = await client(GetFullChannelRequest(channel=channel_id))
            return full.full_chat.participants_count
        except FloodWaitError as e:
            if e.seconds > MAX_FLOOD_WAIT:
                log.error(
                    "Rate-limited on channel %d for %ds, past the %ds cap; skipping it",
                    channel_id,
                    e.seconds,
                    MAX_FLOOD_WAIT,
                )
                return None
            log.warning(
                "Rate-limited on channel %d (attempt %d/%d), waiting %ds",
                channel_id,
                attempt,
                MAX_ATTEMPTS,
                e.seconds,
            )
            await asyncio.sleep(e.seconds)
        except Exception:
            log.exception("Failed to read subscriber count for channel %d", channel_id)
            return None

    log.error("Giving up on channel %d after %d attempts", channel_id, MAX_ATTEMPTS)
    return None



async def collect(client: TelegramClient, channels: dict) -> list[ChannelCount]:
    counts: list[ChannelCount] = []

    for channel_key, channel_id in targets(channels):
        subscribers = await fetch_subscribers(client, channel_id)
        if subscribers is None:
            continue

        counts.append(ChannelCount(channel_key, channel_id, subscribers))
        await asyncio.sleep(CHANNEL_DELAY)

    return counts


async def store(pool, counts: list[ChannelCount]) -> None:
    now = datetime.datetime.now().replace(microsecond=0)
    rows = [(c.channel_key, c.channel_id, c.subscribers, now.date(), now) for c in counts]

    async with pool.acquire() as conn:
        await conn.executemany(INSERT_SQL, rows)


SELECT_ALL_STATS_SQL = """
    SELECT channel_key, time, date, subscribers
    FROM subscribers
    ORDER BY time, channel_key
"""

STATS_CSV_COLUMNS = ("channel_key", "display_name", "date", "subscribers")


async def export_stats_csv(pool) -> str:
    async with pool.acquire() as conn:
        rows = await conn.fetch(SELECT_ALL_STATS_SQL)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(STATS_CSV_COLUMNS)

    for record in rows:
        channel_key = record["channel_key"]
        date_val = record["time"] if "time" in record else record["date"]
        subscribers = record["subscribers"]
        display_name = REGION_CONFIG.get(channel_key, {}).get("display_name", channel_key)
        if isinstance(date_val, datetime.datetime):
            date_str = date_val.strftime("%Y-%m-%d %H:%M:%S")
        elif hasattr(date_val, "isoformat"):
            date_str = date_val.isoformat()
        else:
            date_str = str(date_val)
        writer.writerow([channel_key, display_name, date_str, subscribers])

    return buffer.getvalue()



def upload_to_r2(csv_content: str) -> None:
    if not (
        CLOUDFLARE_R2_ACCESS_KEY_ID
        and CLOUDFLARE_R2_SECRET_ACCESS_KEY
        and (CLOUDFLARE_R2_S3_ENDPOINT or CLOUDFLARE_ACCOUNT_ID)
    ):
        log.warning("R2 credentials not set; skipping upload to R2")
        return

    endpoint = (
        CLOUDFLARE_R2_S3_ENDPOINT or f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"
    )
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=CLOUDFLARE_R2_ACCESS_KEY_ID,
        aws_secret_access_key=CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    bucket = CLOUDFLARE_R2_BI_DATA_BUCKET
    key = "subscribers.csv"
    log.info(
        "Uploading subscribers CSV to s3://%s/%s (%d bytes)",
        bucket,
        key,
        len(csv_content.encode("utf-8")),
    )
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_content.encode("utf-8"),
        ContentType="text/csv; charset=utf-8",
    )
    log.info("Successfully uploaded subscribers CSV to R2 data bucket %s", bucket)


def trigger_dashboard_build() -> None:
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
            log.warning(
                "Failed to trigger dashboard workflow (HTTP %d): %s", resp.status_code, resp.text
            )
    except Exception:
        log.exception("Exception while triggering GitHub Actions dashboard workflow")


async def run_snapshot(client: TelegramClient, pool, channels: dict) -> int:
    expected = len(targets(channels))

    counts = await collect(client, channels)

    if not counts:
        log.error("Snapshot collected no channels at all")
        return 1

    if len(counts) < expected * MIN_COVERAGE:
        log.error(
            "Snapshot reached only %d of %d channels; discarding it rather than "
            "storing a day that reads as a subscriber collapse. Re-running fills "
            "the day in once the cause is fixed",
            len(counts),
            expected,
        )
        return 1

    await store(pool, counts)

    total = sum(c.subscribers for c in counts)
    log.info("Snapshot done: %d/%d channels, %d subscribers in total", len(counts), expected, total)

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
        async with TelegramClient(session_file, TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            await asyncio.to_thread(ensure_pg_tables)
            pool = await asyncpg.create_pool(DATABASE_URL)
            try:
                return await run_snapshot(client, pool, channels)
            finally:
                await pool.close()
    except EOFError:
        log.error(
            "Telegram session '%s' is missing or expired; create it with ./deploy/setup.sh %s",
            SESSION_NAME,
            SESSION_NAME,
        )
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
