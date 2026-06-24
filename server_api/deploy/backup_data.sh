#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"
BACKUP_DIR="${BACKUP_DIR:-/srv/ign-daily-backups}"
INCLUDE_SECRETS="${INCLUDE_SECRETS:-0}"
stamp="$(date +%Y%m%d-%H%M%S)"
archive="$BACKUP_DIR/ign-daily-$stamp.tar.gz"

mkdir -p "$BACKUP_DIR"
tmp="$(mktemp -d)"
mkdir -p "$tmp/app" "$tmp/api"
cp -a "$APP_DIR/data" "$tmp/app/data"
[ -f "$APP_DIR/exchange_rates.json" ] && cp "$APP_DIR/exchange_rates.json" "$tmp/app/exchange_rates.json"
[ -f "$APP_DIR/ign_rss_new.json" ] && cp "$APP_DIR/ign_rss_new.json" "$tmp/app/ign_rss_new.json"
[ -f "$API_DIR/auth.sqlite3" ] && cp "$API_DIR/auth.sqlite3" "$tmp/api/auth.sqlite3"
if [ "$INCLUDE_SECRETS" = "1" ]; then
  [ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$tmp/app/.env"
  [ -f "$API_DIR/.env" ] && cp "$API_DIR/.env" "$tmp/api/.env"
fi
tar -C "$tmp" -czf "$archive" .
rm -rf "$tmp"
chmod 600 "$archive"
echo "$archive"

