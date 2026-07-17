#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${1:-/srv/ign-daily/data}"
DATA_DIR="$(realpath -m "$DATA_DIR")"
case "$DATA_DIR" in
  /srv/*/data|/srv/*/data/) ;;
  *) echo "Refusing unsafe data directory: $DATA_DIR" >&2; exit 2 ;;
esac

[ -d "$DATA_DIR" ] || exit 0
find "$DATA_DIR" -type d -exec chmod 0755 {} +
find "$DATA_DIR" -type f -name '*.json' -exec chmod 0644 {} +
