#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
ENV_FILE="$APP_DIR/.env"
BASE_URL="${TRANSLATOR_BASE_URL:-https://api.apikey.fun/v1}"

if [ ! -d "$APP_DIR" ]; then
  echo "Application directory does not exist: $APP_DIR" >&2
  exit 1
fi

read -r -s -p "APIKEY.FUN external-script API key: " api_key
echo >&2
if [ -z "$api_key" ]; then
  echo "No key entered; nothing changed." >&2
  exit 1
fi

# Send the secret through stdin so it is absent from the command line, shell
# history and normal output. Python replaces the env file atomically while
# preserving every unrelated setting.
printf '%s' "$api_key" | python3 -c '
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
base_url = sys.argv[2]
api_key = sys.stdin.read()
if not api_key or "\n" in api_key or "\r" in api_key:
    raise SystemExit("Invalid translator API key")

updates = {
    "TRANSLATOR_API_KEY": api_key,
    "TRANSLATOR_BASE_URL": base_url,
}
lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
output = []
seen = set()
for line in lines:
    stripped = line.lstrip()
    replaced = False
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
            replaced = True
    if not replaced:
        output.append(line)
for key, value in updates.items():
    if key not in seen:
        output.append(f"{key}={value}")

path.parent.mkdir(parents=True, exist_ok=True)
temp = path.with_name(path.name + ".tmp")
temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
os.chmod(temp, 0o600)
os.replace(temp, path)
' "$ENV_FILE" "$BASE_URL"

unset api_key
echo "Translator secret updated in $ENV_FILE (mode 0600)."
echo "No article, queue or automation state was changed."
