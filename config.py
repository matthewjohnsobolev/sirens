import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGES_PATH = PROJECT_ROOT / "assets" / "img"
SESSION_PATH = PROJECT_ROOT / "data" / "sessions"
LOGS_PATH = PROJECT_ROOT / "logs"
VERSION = "1.7.0"

load_dotenv()


APP_ENV_ALIASES = {
    "dev": "dev",
    "development": "dev",
    "prod": "prod",
    "production": "prod",
}
_raw_app_env = os.getenv("APP_ENV", "").strip().lower() or "dev"
if _raw_app_env not in APP_ENV_ALIASES:
    raise ValueError(f"APP_ENV must be one of {sorted(APP_ENV_ALIASES)}, got {_raw_app_env!r}")
APP_ENV = APP_ENV_ALIASES[_raw_app_env]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://sirens:sirens@localhost:5432/sirens")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SOURCE_CHANNEL_ID = (
    int(os.getenv("TELEGRAM_SOURCE_CHANNEL_ID"))
    if os.getenv("TELEGRAM_SOURCE_CHANNEL_ID")
    else None
)
TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID = (
    int(os.getenv("TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID"))
    if os.getenv("TELEGRAM_SOURCE_FALLBACK_CHANNEL_ID")
    else None
)
ALERT_BROADCAST_SOURCES = frozenset(
    part.strip()
    for part in os.getenv("ALERT_BROADCAST_SOURCES", "fallback").split(",")
    if part.strip()
)

UKRAINE_ALARM_API_KEY = os.getenv("UKRAINE_ALARM_API_KEY", "")
UKRAINE_ALARM_API_URL = os.getenv("UKRAINE_ALARM_API_URL", "https://api.ukrainealarm.com").rstrip(
    "/"
)
try:
    UKRAINE_ALARM_POLL_INTERVAL = float(os.getenv("UKRAINE_ALARM_POLL_INTERVAL", "2.5"))
except ValueError:
    UKRAINE_ALARM_POLL_INTERVAL = 2.5
try:
    UKRAINE_ALARM_RESYNC_INTERVAL = float(os.getenv("UKRAINE_ALARM_RESYNC_INTERVAL", "300"))
except ValueError:
    UKRAINE_ALARM_RESYNC_INTERVAL = 300.0
UKRAINE_ALARM_MAP_SOURCE_URL = os.getenv(
    "UKRAINE_ALARM_MAP_SOURCE_URL", "https://map.ukrainealarm.com"
)


CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_R2_ACCESS_KEY_ID = (
    os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
    or os.getenv("R2_ACCESS_KEY_ID")
    or os.getenv("CLOUDFLARE_ACCESS_KEY_ID")
    or ""
)
CLOUDFLARE_R2_SECRET_ACCESS_KEY = (
    os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
    or os.getenv("R2_SECRET_ACCESS_KEY")
    or os.getenv("CLOUDFLARE_SECRET_ACCESS_KEY")
    or ""
)
CLOUDFLARE_R2_BI_DATA_BUCKET = (
    os.getenv("CLOUDFLARE_R2_BI_DATA_BUCKET")
    or os.getenv("CLOUDFLARE_R2_DATA_BUCKET")
    or os.getenv("R2_DATA_BUCKET")
    or os.getenv("CLOUDFLARE_R2_BUCKET")
    or os.getenv("R2_BUCKET")
    or "sirens-bi-data"
)
CLOUDFLARE_R2_BI_WEB_BUCKET = (
    os.getenv("CLOUDFLARE_R2_BI_WEB_BUCKET")
    or os.getenv("CLOUDFLARE_R2_WEB_BUCKET")
    or os.getenv("R2_WEB_BUCKET")
    or "sirens-bi-web"
)
CLOUDFLARE_R2_S3_ENDPOINT = os.getenv("CLOUDFLARE_R2_S3_ENDPOINT") or os.getenv("R2_ENDPOINT") or ""
if not CLOUDFLARE_R2_S3_ENDPOINT and CLOUDFLARE_ACCOUNT_ID:
    CLOUDFLARE_R2_S3_ENDPOINT = f"https://{CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com"


CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_TELEMETRY_NAMESPACE_ID = os.getenv("CLOUDFLARE_TELEMETRY_NAMESPACE_ID", "")

HEALTHCHECKS_API_KEY = os.getenv("HEALTHCHECKS_API_KEY", "")
HEALTHCHECKS_ALERTS_SOURCE_PING_URL = os.getenv("HEALTHCHECKS_ALERTS_SOURCE_PING_URL", "")
HEALTHCHECKS_ALERTS_BROADCAST_PING_URL = os.getenv("HEALTHCHECKS_ALERTS_BROADCAST_PING_URL", "")
HEALTHCHECKS_WEB_PING_URL = os.getenv("HEALTHCHECKS_WEB_PING_URL", "")
HEALTHCHECKS_BACKUP_PING_URL = os.getenv("HEALTHCHECKS_BACKUP_PING_URL", "")
HEALTHCHECKS_BI_PING_URL = os.getenv("HEALTHCHECKS_BI_PING_URL", "")
HEALTHCHECKS_ALERTS_SOURCE_SLUG = os.getenv(
    "HEALTHCHECKS_ALERTS_SOURCE_SLUG", "sirens-alerts-source"
)
HEALTHCHECKS_ALERTS_BROADCAST_SLUG = os.getenv(
    "HEALTHCHECKS_ALERTS_BROADCAST_SLUG", "sirens-alerts-broadcast"
)

UPTIMEROBOT_API_MONITOR_KEY = os.getenv("UPTIMEROBOT_API_MONITOR_KEY", "")
UPTIMEROBOT_WEB_MONITOR_KEY = os.getenv("UPTIMEROBOT_WEB_MONITOR_KEY", "")


def _with_api_key(url: str, key: str) -> str:
    """Adds the key to the tile URL, unless the URL already carries one."""
    if not key or "key=" in url or "api_key=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}key={key}"


MAP_TILES_API_KEY = os.getenv("MAP_TILES_API_KEY", "").strip()
MAP_TILES_URL = _with_api_key(
    os.getenv(
        "MAP_TILES_URL",
        "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
    ).strip(),
    MAP_TILES_API_KEY,
)
MAP_TILES_ATTRIBUTION = os.getenv(
    "MAP_TILES_ATTRIBUTION",
    '&copy;&nbsp;<a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    '<span class="map-attribution-divider" aria-hidden="true">&middot;</span>'
    '&copy;&nbsp;<a href="https://carto.com/attributions">CARTO</a>',
).strip()

SENTRY_DSN = os.getenv("SENTRY_DSN", "")


GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "G-JC48ZJGBHM").strip()


SITE_URL = os.getenv("SITE_URL", "https://sirens.live").strip().rstrip("/")
STATUS_URL = os.getenv("STATUS_URL", "https://status.sirens.live").strip().rstrip("/")
GEO_DISTRICTS_URL = os.getenv(
    "GEO_DISTRICTS_URL", "https://geo.sirens.live/districts.geojson"
).strip()
GEO_OBLASTS_URL = os.getenv("GEO_OBLASTS_URL", "https://geo.sirens.live/oblasts.geojson").strip()
OCI_PAR_URL = os.getenv("OCI_PAR_URL", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
_raw_repo = os.getenv("GITHUB_REPO", "matthewjohnsobolev/sirens")
GITHUB_REPO = (
    _raw_repo.replace("https://github.com/", "")
    .replace("http://github.com/", "")
    .replace("git@github.com:", "")
    .strip("/")
)
