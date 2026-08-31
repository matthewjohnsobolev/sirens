#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin:${PATH:-}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v docker >/dev/null || {
    printf '\n\033[1;31mERROR:\033[0m docker not found in PATH (%s)\n' "$PATH" >&2
    exit 1
}

SESSION_FILE="data/sessions/bi.session"
LOCK_FILE="logs/.bi.lock"

step() { printf '\n\033[1;32m==>\033[0m %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; ping_healthcheck /fail; exit 1; }

ping_healthcheck() {
    [[ -n "${HEALTHCHECKS_BI_PING_URL:-}" ]] || return 0
    curl -fsS -m 10 -o /dev/null "${HEALTHCHECKS_BI_PING_URL}${1:-}" || true
}

step "Checking environment"
[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

set -a
# shellcheck disable=SC1091
source ./.env
set +a

MODE="${MODE:-${APP_ENV:-prod}}"

[[ -f "$SESSION_FILE" ]] || die "no snapshot session - run ./deploy/setup.sh bi first"

mkdir -p logs

if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -n 9 || die "another snapshot is still running"
else
    echo "warning: flock not available, skipping overlap protection" >&2
fi

ping_healthcheck /start

step "Counting subscribers ($MODE)"
docker compose run --rm -T bi python run_bi.py -m "$MODE" \
    || die "snapshot failed (see the output above; is the db container running?)"

ping_healthcheck
step "Done"
