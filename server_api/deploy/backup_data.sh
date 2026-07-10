#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"
BACKUP_DIR="${BACKUP_DIR:-/srv/ign-daily-backups}"
INCLUDE_SECRETS="${INCLUDE_SECRETS:-0}"
stamp="$(date +%Y%m%d-%H%M%S)"
archive="$BACKUP_DIR/ign-daily-$stamp.tar.gz"
archive_tmp="$BACKUP_DIR/.ign-daily-$stamp.tar.gz.tmp"
tmp=""

cleanup() {
  [ -n "$tmp" ] && rm -rf "$tmp"
  rm -f "$archive_tmp"
}
trap cleanup EXIT
umask 077

mkdir -p "$BACKUP_DIR"
tmp="$(mktemp -d)"
mkdir -p "$tmp/app" "$tmp/api"
if command -v flock >/dev/null 2>&1; then
  exec 9>/var/lock/ign-daily-write.lock
  flock -w 120 9
fi
if [ ! -d "$APP_DIR/data" ]; then
  echo "Runtime data directory is missing: $APP_DIR/data" >&2
  exit 1
fi
cp -a "$APP_DIR/data" "$tmp/app/data"
[ -f "$APP_DIR/exchange_rates.json" ] && cp "$APP_DIR/exchange_rates.json" "$tmp/app/exchange_rates.json"
[ -f "$APP_DIR/ign_rss_new.json" ] && cp "$APP_DIR/ign_rss_new.json" "$tmp/app/ign_rss_new.json"
if [ -f "$API_DIR/auth.sqlite3" ]; then
  python3 - "$API_DIR/auth.sqlite3" "$tmp/api/auth.sqlite3" <<'PY'
import sqlite3
import sys

source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
target = sqlite3.connect(sys.argv[2])
try:
    with target:
        source.backup(target)
finally:
    target.close()
    source.close()
PY
fi
if [ "$INCLUDE_SECRETS" = "1" ]; then
  [ -f "$APP_DIR/.env" ] && cp "$APP_DIR/.env" "$tmp/app/.env"
  [ -f "$API_DIR/.env" ] && cp "$API_DIR/.env" "$tmp/api/.env"
fi
tar -C "$tmp" -czf "$archive_tmp" .
mv "$archive_tmp" "$archive"
chmod 600 "$archive"
trap - EXIT
rm -rf "$tmp"
echo "$archive"

