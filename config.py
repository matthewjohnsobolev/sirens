import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
IMAGES_PATH = PROJECT_ROOT / "assets" / "img"
SESSION_PATH = PROJECT_ROOT / "data" / "sessions"
LOGS_PATH = PROJECT_ROOT / "logs"
VERSION = "1.1.0"

load_dotenv()

# APP_ENV is both the 12-factor environment name and the run mode the workers
# take on the command line (docker-compose passes it straight to `-m`), so the
# long spellings have to collapse onto the two the CLI accepts.
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

CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_R2_ACCESS_KEY_ID = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "")
CLOUDFLARE_R2_SECRET_ACCESS_KEY = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "")
CLOUDFLARE_R2_BI_DATA_BUCKET = os.getenv("CLOUDFLARE_R2_BI_DATA_BUCKET", "sirens-bi-data")
CLOUDFLARE_R2_BI_WEB_BUCKET = os.getenv("CLOUDFLARE_R2_BI_WEB_BUCKET", "sirens-bi-web")
CLOUDFLARE_R2_S3_ENDPOINT = os.getenv("CLOUDFLARE_R2_S3_ENDPOINT", "")
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

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
OCI_PAR_URL = os.getenv("OCI_PAR_URL", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
_raw_repo = os.getenv("GITHUB_REPO", "matthewjohnsobolev/sirens")
GITHUB_REPO = (
    _raw_repo.replace("https://github.com/", "")
    .replace("http://github.com/", "")
    .replace("git@github.com:", "")
    .strip("/")
)
