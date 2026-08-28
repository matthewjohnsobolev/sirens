#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REF="${1:-origin/main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api}"
SESSION_FILE="data/sessions/sirens.session"
BI_SESSION_FILE="data/sessions/bi.session"

step() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

step "Checking environment"
[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

set -a
# shellcheck disable=SC1091
source ./.env
set +a

# POSTGRES_* are what compose builds DATABASE_URL from. Missing, they used to
# surface 90 seconds later as an unexplained "service is not responding".
for var in TELEGRAM_API_ID TELEGRAM_API_HASH POSTGRES_USER POSTGRES_PASSWORD; do
    [[ -n "${!var:-}" ]] || die "$var is not set in .env (see .env.example)"
done

case "${APP_ENV:-}" in
    prod|production) ;;
    *) die "APP_ENV must be 'prod' (or 'production') in .env, got '${APP_ENV:-<unset>}'" ;;
esac

[[ -f "$SESSION_FILE" ]] || die "no Telegram session - run ./deploy/setup.sh first"

# The snapshot is optional infrastructure: missing stats must never hold up a
# deploy of the alerts themselves.
[[ -f "$BI_SESSION_FILE" ]] \
    || printf '\033[1;33mwarning:\033[0m no snapshot session - run ./deploy/setup.sh bi to enable channel stats\n'

step "Updating code to $REF"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] \
    || die "working tree has local modifications - commit or discard them"
git fetch --prune --tags origin
TARGET="$(git rev-parse --verify "${REF}^{commit}")" || die "unknown revision: $REF"

if [[ "$TARGET" == "$(git rev-parse HEAD)" && "${FORCE:-0}" != "1" ]]; then
    step "Already at $(git rev-parse --short HEAD), nothing to deploy"
    exit 0
fi

git reset --hard "$TARGET"
git --no-pager log -1 --format='Deploying: %h %s'

step "Building images"
# --profile tools so the one-shot `bi` image is rebuilt too. Without it the
# snapshot keeps running whatever code was current when its image was first
# built, however many deploys go by. The profile is deliberately absent from
# `up` below: bi must still never start as a daemon.
docker compose --profile tools build --pull

step "Restarting services"
docker compose up -d --remove-orphans

step "Waiting for $HEALTH_URL"
for i in $(seq 1 30); do
    if curl -fsS --max-time 10 -o /dev/null "$HEALTH_URL"; then
        step "Done. Deployed revision $(git rev-parse --short HEAD)"
        docker compose ps
        docker image prune -f >/dev/null
        exit 0
    fi
    sleep 3
done

docker compose ps
docker compose logs --tail 60 web alerts
die "service is not responding. Roll back with: ./deploy/deploy.sh <previous-SHA>  (git log --oneline -10)"
