#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"
archive="${1:-}"
if [ -z "$archive" ] || [ ! -f "$archive" ]; then
  echo "Usage: $0 /path/to/ign-daily-backup.tar.gz" >&2
  exit 1
fi

tmp="$(mktemp -d)"
tar -C "$tmp" -xzf "$archive"
if [ -d "$tmp/app/data" ]; then
  rm -rf "$APP_DIR/data"
  cp -a "$tmp/app/data" "$APP_DIR/data"
fi
[ -f "$tmp/app/exchange_rates.json" ] && cp "$tmp/app/exchange_rates.json" "$APP_DIR/exchange_rates.json"
[ -f "$tmp/app/ign_rss_new.json" ] && cp "$tmp/app/ign_rss_new.json" "$APP_DIR/ign_rss_new.json"
[ -f "$tmp/api/auth.sqlite3" ] && cp "$tmp/api/auth.sqlite3" "$API_DIR/auth.sqlite3"
[ -f "$tmp/app/.env" ] && cp "$tmp/app/.env" "$APP_DIR/.env" && chmod 600 "$APP_DIR/.env"
[ -f "$tmp/api/.env" ] && cp "$tmp/api/.env" "$API_DIR/.env" && chmod 600 "$API_DIR/.env"
rm -rf "$tmp"
sudo systemctl restart ign-daily-api
echo "Restore complete."

