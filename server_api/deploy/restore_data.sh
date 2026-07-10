#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"
archive="${1:-}"
APP_DIR="$(realpath -m "$APP_DIR")"
API_DIR="$(realpath -m "$API_DIR")"
for managed_path in "$APP_DIR" "$API_DIR"; do
  case "$managed_path" in
    /srv/*) ;;
    *) echo "Refusing unsafe managed path: $managed_path" >&2; exit 1 ;;
  esac
done
if [ -z "$archive" ] || [ ! -f "$archive" ]; then
  echo "Usage: $0 /path/to/ign-daily-backup.tar.gz" >&2
  exit 1
fi

tmp="$(mktemp -d)"
api_stopped=0
cleanup() {
  rm -rf "$tmp"
  if [ "$api_stopped" = "1" ]; then
    sudo systemctl start ign-daily-api || true
  fi
}
trap cleanup EXIT

python3 - "$archive" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

with tarfile.open(sys.argv[1], "r:gz") as archive:
    for member in archive.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise SystemExit(f"Unsafe backup member: {member.name}")
PY

# Preserve the current state before replacing anything.
APP_DIR="$APP_DIR" API_DIR="$API_DIR" "$(dirname "$0")/backup_data.sh" >/dev/null
tar --no-same-owner --no-same-permissions -C "$tmp" -xzf "$archive"
if [ -d "$tmp/app/data" ]; then
  staged_data="$APP_DIR/.data-restore-$$"
  previous_data="$APP_DIR/.data-before-restore-$$"
  cp -a "$tmp/app/data" "$staged_data"
  if [ -d "$APP_DIR/data" ]; then
    mv "$APP_DIR/data" "$previous_data"
  fi
  if mv "$staged_data" "$APP_DIR/data"; then
    rm -rf "$previous_data"
  else
    [ -d "$previous_data" ] && mv "$previous_data" "$APP_DIR/data"
    exit 1
  fi
fi
[ -f "$tmp/app/exchange_rates.json" ] && cp "$tmp/app/exchange_rates.json" "$APP_DIR/exchange_rates.json"
[ -f "$tmp/app/ign_rss_new.json" ] && cp "$tmp/app/ign_rss_new.json" "$APP_DIR/ign_rss_new.json"
if [ -f "$tmp/api/auth.sqlite3" ]; then
  if systemctl is-active --quiet ign-daily-api; then
    sudo systemctl stop ign-daily-api
    api_stopped=1
  fi
  install -m 600 "$tmp/api/auth.sqlite3" "$API_DIR/auth.sqlite3"
fi
[ -f "$tmp/app/.env" ] && cp "$tmp/app/.env" "$APP_DIR/.env" && chmod 600 "$APP_DIR/.env"
[ -f "$tmp/api/.env" ] && cp "$tmp/api/.env" "$API_DIR/.env" && chmod 600 "$API_DIR/.env"
if [ "$api_stopped" = "1" ]; then
  sudo systemctl start ign-daily-api
  api_stopped=0
else
  sudo systemctl restart ign-daily-api
fi
trap - EXIT
rm -rf "$tmp"
echo "Restore complete."

