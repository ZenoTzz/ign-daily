#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${1:-/srv/ign-daily/data}"
RUN_USER="${2:-ubuntu}"
DATA_DIR="$(realpath -m "$DATA_DIR")"
case "$DATA_DIR" in
  /srv/*/data|/srv/*/data/) ;;
  *) echo "Refusing unsafe data directory: $DATA_DIR" >&2; exit 2 ;;
esac

[ -d "$DATA_DIR" ] || exit 0
id "$RUN_USER" >/dev/null 2>&1 || {
  echo "Unknown runtime user: $RUN_USER" >&2
  exit 2
}
RUN_GROUP="$(id -gn "$RUN_USER")"

chown -R "$RUN_USER:$RUN_GROUP" "$DATA_DIR"
find "$DATA_DIR" -type d -exec chmod 0755 {} +
find "$DATA_DIR" -type f -name '*.json' -exec chmod 0644 {} +

EXCHANGE_RATES="$(dirname "$DATA_DIR")/exchange_rates.json"
if [ -f "$EXCHANGE_RATES" ]; then
  chown "$RUN_USER:$RUN_GROUP" "$EXCHANGE_RATES"
  chmod 0644 "$EXCHANGE_RATES"
fi
