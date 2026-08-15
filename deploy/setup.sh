#!/usr/bin/env bash
#
# Sirens one-time server setup. Interactive — run manually once when first
# setting up the VPS (or after the Telegram session is revoked).
#
# Prerequisite: .env filled in (copy from .env.example).
#
# Usage:
#
#   ./deploy/setup.sh          # sirens.session, used by the alerts worker
#   ./deploy/setup.sh bi       # bi.session, used by the subscriber snapshot
#
# Logs in to Telegram via Telethon: enter phone number and login code when
# prompted, then Ctrl+C once logs start streaming. Session is written to
# data/sessions/<name>.session on the host, so it survives rebuilds.
#
# The two sessions are separate on purpose: one session file cannot be shared
# by two running processes without risking AuthKeyDuplicatedError, and Telegram
# is perfectly happy to hold several sessions for one account.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SESSION_NAME="${1:-sirens}"

case "$SESSION_NAME" in
    sirens) SERVICE=alerts; ENTRYPOINT=run_alerts.py ;;
    bi)     SERVICE=bi;     ENTRYPOINT=run_bi.py ;;
    *)      printf 'ERROR: unknown session "%s" (expected: sirens, bi)\n' "$SESSION_NAME" >&2; exit 1 ;;
esac

SESSION_FILE="data/sessions/${SESSION_NAME}.session"

step() { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

[[ -f docker-compose.yml ]] || die "run this from the project directory"
[[ -f .env ]] || die "no .env file (copy .env.example and fill it in)"

for var in TELEGRAM_API_ID TELEGRAM_API_HASH; do
    grep -Eq "^[[:space:]]*${var}=.+" .env || die "$var is not set in .env"
done

if [[ -f "$SESSION_FILE" ]]; then
    read -r -p "Session already exists. Replace it? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }
    mv "$SESSION_FILE" "$SESSION_FILE.bak-$(date +%Y%m%d-%H%M%S)"
fi

mkdir -p data/sessions

step "Building the $SERVICE image"
docker compose build "$SERVICE"

# The instructions go here, after the build, not before it: printed earlier they
# invite typing into a terminal that nothing is reading yet, and compose's
# progress renderer then scrambles the echoed characters.
step "Logging in to Telegram ($SESSION_NAME)"
cat <<'EOF'

Wait for the prompt below before typing anything:

    Please enter your phone (or bot token):

Enter your phone number, then the login code Telegram sends you.
Once log lines start streaming, press Ctrl+C - the session is saved by then.

EOF
docker compose run --rm "$SERVICE" python "$ENTRYPOINT" -m prod || true

[[ -f "$SESSION_FILE" ]] || die "login was not completed"
chmod 600 "$SESSION_FILE"

if [[ "$SESSION_NAME" == "bi" ]]; then
    step "Session saved. Schedule the snapshot with a cron entry - see deploy/bi.sh"
else
    step "Session saved. Deploy with ./deploy/deploy.sh"
fi
