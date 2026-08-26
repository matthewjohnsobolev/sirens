"""
Sirens - Simulate Dev Alert & Update Telemetry.

Usage:
    python simulate_alert.py
    python simulate_alert.py --district bucha --type air_raid_alert
    python simulate_alert.py --district bila_tserkva --type air_raid_alert_cancelled
    python simulate_alert.py --district lviv --type air_raid_alert
"""

import argparse
import asyncio
import datetime
import json
import logging
import sys
import time

import redis.asyncio as redis

from alerts.main import (
    LAST_ALERT_INFO_KEY,
    LAST_BROADCAST_AT_KEY,
    district_label,
    push_telemetry_to_kv,
)
import alerts.main as alerts_main
from config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_KV_STATUS_NAMESPACE_ID,
    DISTRICT_CONFIG,
    REDIS_URL,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate an alert in dev mode and push telemetry to KV")
    parser.add_argument(
        "-d", "--district",
        default="bila_tserkva",
        help="District key (e.g. bila_tserkva, bucha, lviv, cherkasy, brovary). Default: bila_tserkva"
    )
    parser.add_argument(
        "-t", "--type",
        choices=["air_raid_alert", "air_raid_alert_cancelled", "threat_of_shelling", "threat_of_shelling_cancelled"],
        default="air_raid_alert",
        help="Alert type. Default: air_raid_alert"
    )
    parser.add_argument(
        "-m", "--message-id",
        type=int,
        default=99999,
        help="Message ID. Default: 99999"
    )
    parser.add_argument(
        "-l", "--link",
        default="https://t.me/sirens_kyiv_obl/99999",
        help="Message link"
    )
    return parser.parse_args()


async def run_simulation():
    args = parse_args()
    district_key = args.district.lower()

    if district_key not in DISTRICT_CONFIG:
        print(f"[!] Warning: '{district_key}' not found in DISTRICT_CONFIG.")
        oblast_key = district_key
        d_name = district_key.capitalize()
    else:
        oblast_key = DISTRICT_CONFIG[district_key].get("oblast", district_key)
        d_name = district_label(district_key)

    now = datetime.datetime.now()
    now_utc_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    now_ts = time.time()

    alert_payload = {
        "type": args.type,
        "region": oblast_key,
        "district": district_key,
        "district_name": d_name,
        "timestamp": now_utc_iso,
        "message_id": args.message_id,
        "message_link": args.link,
    }

    alerts_main.last_alert_payload = alert_payload
    alerts_main.last_broadcast_at = now_ts
    alerts_main.last_source_message_at = now_ts

    # Connect to Redis if running
    try:
        r_client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0
        )
        alerts_main.redis_client = r_client
        await r_client.set(LAST_ALERT_INFO_KEY, json.dumps(alert_payload))
        await r_client.set(LAST_BROADCAST_AT_KEY, str(int(now_ts)))
        
        # Also update district threat state in Redis
        is_active = args.type in ("air_raid_alert", "threat_of_shelling")
        if "shelling" in args.type:
            await r_client.hset(
                f"threat:shellings:{district_key}",
                mapping={
                    "status": "true" if is_active else "false",
                    "time": now.strftime("%H:%M"),
                    "source": args.link,
                    "updated_at": str(int(now_ts)),
                }
            )
        else:
            await r_client.hset(
                f"threat:alerts:city:{district_key}",
                mapping={
                    "status": "true" if is_active else "false",
                    "time": now.strftime("%H:%M"),
                    "source": args.link,
                    "type": args.type,
                    "updated_at": str(int(now_ts)),
                }
            )
            active_key = f"threat:alerts:active:{oblast_key}"
            if is_active:
                await r_client.sadd(active_key, district_key)
            else:
                await r_client.srem(active_key, district_key)

        print("[+] Redis state updated successfully.")
    except Exception as e:
        print(f"[-] Redis connection skipped: {e}")

    print("\n--- Telemetry Snapshot ---")
    print(f"  Alert Type   : {args.type}")
    print(f"  District     : {d_name} ({district_key})")
    print(f"  Region       : {oblast_key}")
    print(f"  Time (Local) : {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Time (UTC)   : {now_utc_iso}")
    print(f"  Message Link : {args.link}")
    print("--------------------------\n")

    # Push to Cloudflare KV
    if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_KV_STATUS_NAMESPACE_ID and CLOUDFLARE_API_TOKEN:
        print(f"[*] Pushing telemetry to Cloudflare KV namespace '{CLOUDFLARE_KV_STATUS_NAMESPACE_ID}'...")
        await push_telemetry_to_kv()
        print("[+] Telemetry pushed to Cloudflare KV!")
    else:
        print("[!] Cloudflare KV credentials not set in .env:")
        print("    CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, CLOUDFLARE_KV_STATUS_NAMESPACE_ID")
        print("    (Set them in .env to push directly to remote Cloudflare KV)")

    print("\n[OK] Ready! Check http://localhost:8788 or /status.json")


if __name__ == "__main__":
    asyncio.run(run_simulation())
