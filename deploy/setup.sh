#!/usr/bin/env bash
#
# Sirens one-time server setup. Interactive — run manually once when first
# setting up the VPS (or after the Telegram session is revoked).
#
# Prerequisite: .env filled in (copy from .env.example).
#
# Usage:
#
#   ./deploy/setup.sh
#
# Logs in to Telegram via Telethon: enter phone number and login code when
# prompted, then Ctrl+C once logs start streaming. Session is written to
# data/sessions/sirens.session on the host, so it survives rebuilds.
#
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SESSION_FILE="data/sessions/sirens.session"

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

step "Logging in to Telegram"
echo "Enter your phone number and the login code, then press Ctrl+C once logs start."
docker compose build alerts
docker compose run --rm alerts python run_alerts.py -m prod || true

[[ -f "$SESSION_FILE" ]] || die "login was not completed"
chmod 600 "$SESSION_FILE"

step "Session saved. Deploy with ./deploy/deploy.sh"
