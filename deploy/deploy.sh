#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

REF="${1:-origin/main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api}"
SESSION_FILE="data/sessions/sirens.session"
BI_SESSION_FILE="data/sessions/bi.session"
SELF="deploy/deploy.sh"

step() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Only what must hold before the checkout moves. Anything that depends on the
# shape of .env is checked further down, by the script this one hands over to:
# the copy that starts a deploy comes from the revision the server is already
# on, so its idea of the .env contract is exactly that old. A stale check here
# is a deadlock - it exits before the update that would have replaced it.
step "Checking prerequisites"
[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

step "Updating code to $REF"
# core.fileMode=false: a lost exec bit is noise, never a change worth blocking on.
DIRTY="$(git -c core.fileMode=false status --porcelain --untracked-files=no)"
if [[ -n "$DIRTY" && "${DISCARD_LOCAL:-0}" != "1" ]]; then
    printf '%s\n' "$DIRTY" >&2
    die "working tree has local modifications (listed above) - commit them, or re-run with DISCARD_LOCAL=1 to discard"
fi

git -c http.version=HTTP/1.1 fetch --prune --tags origin
TARGET="$(git rev-parse --verify "${REF}^{commit}")" || die "unknown revision: $REF"

if [[ "$TARGET" == "$(git rev-parse HEAD)" && "${FORCE:-0}" != "1" ]]; then
    step "Already at $(git rev-parse --short HEAD), nothing to deploy"
    exit 0
fi

SELF_BEFORE="$(git rev-parse "HEAD:$SELF" 2>/dev/null || echo none)"
git reset --hard "$TARGET"
git --no-pager log -1 --format='Deploying: %h %s'
SELF_AFTER="$(git rev-parse "HEAD:$SELF" 2>/dev/null || echo none)"

# FORCE, or the fresh copy would see HEAD already at TARGET and skip the build.
if [[ "$SELF_BEFORE" != "$SELF_AFTER" && "${REEXECED:-0}" != "1" ]]; then
    step "$SELF changed in this revision - continuing with the updated script"
    export REEXECED=1 FORCE=1
    exec bash "$SELF" "$REF"
fi

step "Checking environment"
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
