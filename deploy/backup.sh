#!/usr/bin/env bash
#
# Sirens database backup. Non-interactive — designed for cron, never waits
# for input: either uploads a verified dump or exits non-zero with a reason.
#
# Dumps the Postgres database from the running `db` container, gzips it,
# verifies the archive, uploads it to OCI Object Storage through a
# Pre-Authenticated Request (PAR) URL, and prunes old local copies.
#
# Requires in .env:
#
#   POSTGRES_USER, POSTGRES_PASSWORD   # already needed by docker-compose
#   OCI_PAR_URL                        # PAR with "Object write" on the bucket
#
# Optional in .env:
#
#   HEALTHCHECKS_PING_URL_BACKUP       # healthchecks.io monitor for this job
#
# Usage (run on the VPS from the project directory):
#
#   ./deploy/backup.sh                 # dump -> upload -> prune
#   SKIP_UPLOAD=1 ./deploy/backup.sh   # local dump only (for testing)
#   KEEP_LOCAL=12 ./deploy/backup.sh   # keep 12 local dumps instead of 6
#
# Install as a cron job (every 4 hours — 24 is divisible by 4, so the gaps
# stay even; with KEEP_LOCAL=6 the local copies cover exactly one day):
#
#   crontab -e
#   0 */4 * * * cd /sirens && ./deploy/backup.sh >> logs/backup.log 2>&1
#
# Restore a dump into a fresh database:
#
#   gunzip -c backups/sirens-20260814-030000Z.sql.gz \
#     | docker compose exec -T db psql -U "$POSTGRES_USER" -d sirens
#
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:${PATH:-}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v docker >/dev/null || {
    printf '\n\033[1;31mERROR:\033[0m docker not found in PATH (%s)\n' "$PATH" >&2
    exit 1
}

BACKUP_DIR="${BACKUP_DIR:-backups}"
KEEP_LOCAL="${KEEP_LOCAL:-6}"
LOCK_FILE="${BACKUP_DIR}/.lock"

step() { printf '\n\033[1;32m==>\033[0m %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; ping_healthcheck /fail; exit 1; }

ping_healthcheck() {
    [[ -n "${HEALTHCHECKS_BACKUP_PING_URL:-}" ]] || return 0
    curl -fsS -m 10 -o /dev/null "${HEALTHCHECKS_BACKUP_PING_URL}${1:-}" || true
}

step "Checking environment"
[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

set -a
# shellcheck disable=SC1091
source ./.env
set +a

POSTGRES_DB="${POSTGRES_DB:-sirens}"

for var in POSTGRES_USER POSTGRES_PASSWORD; do
    [[ -n "${!var:-}" ]] || die "$var is not set in .env"
done

if [[ "${SKIP_UPLOAD:-0}" != "1" ]]; then
    [[ -n "${OCI_PAR_URL:-}" ]] || die "OCI_PAR_URL is not set in .env (create a PAR with 'Object write' on the backup bucket)"
fi

mkdir -p "$BACKUP_DIR"

# Never let a slow upload overlap with the next cron tick.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "another backup is still running"
else
    echo "warning: flock not available, skipping overlap protection" >&2
fi

ping_healthcheck /start

NAME="sirens-$(date -u +%Y%m%d-%H%M%SZ).sql.gz"
ARCHIVE="${BACKUP_DIR}/${NAME}"
TMP="${ARCHIVE}.part"

cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

step "Dumping database '$POSTGRES_DB'"
docker compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" db \
    pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges \
    | gzip -9 > "$TMP" \
    || die "pg_dump failed (is the db container running? 'docker compose ps')"

step "Verifying archive"
gzip -t "$TMP" || die "archive is corrupt"
# A dump that produced no schema means pg_dump silently wrote nothing useful.
# grep -c (not -q) so it drains the stream instead of killing gunzip with SIGPIPE.
TABLES="$(gunzip -c "$TMP" | grep -c '^CREATE TABLE' || true)"
[[ "$TABLES" -gt 0 ]] || die "dump contains no tables - refusing to upload"

mv "$TMP" "$ARCHIVE"
step "Created $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1), $TABLES tables)"

if [[ "${SKIP_UPLOAD:-0}" == "1" ]]; then
    step "SKIP_UPLOAD=1, keeping local copy only"
else
    step "Uploading to OCI Object Storage"
    curl -fsS --retry 3 --retry-delay 5 --max-time 600 \
        -X PUT -T "$ARCHIVE" "${OCI_PAR_URL%/}/${NAME}" \
        || die "upload failed (check OCI_PAR_URL - a PAR expires and must be recreated)"
    step "Uploaded $NAME"
fi

step "Pruning local copies (keeping $KEEP_LOCAL)"
ls -1t "$BACKUP_DIR"/sirens-*.sql.gz 2>/dev/null \
    | tail -n "+$((KEEP_LOCAL + 1))" \
    | while read -r old; do
        echo "removing $old"
        rm -f "$old"
    done

ping_healthcheck
step "Done"
