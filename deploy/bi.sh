#!/usr/bin/env bash
#
# Sirens subscriber snapshot. Non-interactive - designed for cron, never waits
# for input: either records today's subscriber counts or exits non-zero.
#
# Starts the one-shot `bi` container, which counts subscribers across the
# network channels and writes one row per channel per day into channel_stats.
# The container is removed afterwards, so nothing stays resident between runs.
#
# Requires:
#
#   data/sessions/bi.session           # create once with ./deploy/setup.sh bi
#
# Optional in .env:
#
#   HEALTHCHECKS_PING_URL_BI           # healthchecks.io monitor for this job
#
# Usage (run on the VPS from the project directory):
#
#   ./deploy/bi.sh                 # count and store
#   MODE=dev ./deploy/bi.sh        # count test channels instead
#
# Install as a cron job (daily; the exact hour only matters in that the count
# should be taken at the same time every day):
#
#   crontab -e
#   0 9 * * * cd /sirens && ./deploy/bi.sh >> logs/bi.log 2>&1
#
# Re-running on the same day is safe: it overwrites the day's rows rather than
# adding duplicates.
#
set -euo pipefail

# cron hands a job a nearly empty environment - commonly just PATH=/usr/bin:/bin.
# docker and curl usually sit in there, but "usually" is a poor thing to hang a
# nightly job on, and a PATH miss under cron fails silently at 6am.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v docker >/dev/null || {
    printf '\n\033[1;31mERROR:\033[0m docker not found in PATH (%s)\n' "$PATH" >&2
    exit 1
}

MODE="${MODE:-prod}"
SESSION_FILE="data/sessions/bi.session"
LOCK_FILE="logs/.bi.lock"

step() { printf '\n\033[1;32m==>\033[0m %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; ping_healthcheck /fail; exit 1; }

ping_healthcheck() {
    [[ -n "${HEALTHCHECKS_PING_URL_BI:-}" ]] || return 0
    curl -fsS -m 10 -o /dev/null "${HEALTHCHECKS_PING_URL_BI}${1:-}" || true
}

step "Checking environment"
[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

set -a
# shellcheck disable=SC1091
source ./.env
set +a

[[ -f "$SESSION_FILE" ]] || die "no snapshot session - run ./deploy/setup.sh bi first"

mkdir -p logs

# The snapshot talks to Telegram over a session that tolerates exactly one user.
# Two overlapping runs would fight over it.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "another snapshot is still running"
else
    echo "warning: flock not available, skipping overlap protection" >&2
fi

ping_healthcheck /start

step "Counting subscribers ($MODE)"
# -T is required: without a TTY attached, `run` refuses to start under cron.
docker compose run --rm -T bi python run_bi.py -m "$MODE" \
    || die "snapshot failed (see the output above; is the db container running?)"

ping_healthcheck
step "Done"
