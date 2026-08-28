#!/usr/bin/env bash
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
