#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"

update_env() {
  local file="$1"
  local key="$2"
  local value="$3"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  chmod 600 "$file"
  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
out = []
done = False
for line in lines:
    if line.strip().startswith(key + "="):
        out.append(f"{key}={value}")
        done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={value}")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
PY
}

prompt_value() {
  local label="$1"
  local secret="${2:-0}"
  local value
  if [ "$secret" = "1" ]; then
    read -r -s -p "$label: " value
    echo >&2
  else
    read -r -p "$label: " value
  fi
  printf '%s' "$value"
}

admin_user="$(prompt_value 'Admin username, default admin' 0)"
admin_user="${admin_user:-admin}"
admin_password="$(prompt_value 'Admin password, min 12 chars' 1)"
if [ "${#admin_password}" -lt 12 ]; then
  echo "Admin password must be at least 12 characters." >&2
  exit 1
fi

api_key="$(prompt_value 'DeepSeek/Translator API key, leave blank to skip' 1)"
base_url="$(prompt_value 'Translator base URL, default https://api.deepseek.com' 0)"
base_url="${base_url:-https://api.deepseek.com}"
cookie_secure="$(prompt_value 'Use secure cookies? 1 for HTTPS, 0 for HTTP, default 0' 0)"
cookie_secure="${cookie_secure:-0}"

update_env "$API_DIR/.env" IGN_DAILY_ADMIN_USER "$admin_user"
update_env "$API_DIR/.env" IGN_DAILY_ADMIN_PASSWORD "$admin_password"
update_env "$API_DIR/.env" IGN_DAILY_STORAGE_MODE "local"
update_env "$API_DIR/.env" IGN_DAILY_COOKIE_SECURE "$cookie_secure"

python_bin="$API_DIR/venv/bin/python"
if [ ! -x "$python_bin" ]; then
  python_bin="python3"
fi

sudo "$python_bin" - "$API_DIR" <<'PY'
import os
import sys
import time
from pathlib import Path

api_dir = Path(sys.argv[1])
env_path = api_dir / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key] = value

sys.path.insert(0, str(api_dir))
import ign_daily_api as api

username = os.environ.get("IGN_DAILY_ADMIN_USER", "admin")
password = os.environ.get("IGN_DAILY_ADMIN_PASSWORD", "")
if password:
    api.init_db()
    with api.db() as conn:
        rows = conn.execute("SELECT id FROM users ORDER BY id").fetchall()
        password_hash = api.hash_password(password)
        if rows:
            primary_id = rows[0]["id"]
            conn.execute(
                "UPDATE users SET username = ?, password_hash = ? WHERE id = ?",
                (username, password_hash, primary_id),
            )
            for row in rows[1:]:
                conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, int(time.time())),
            )
        conn.execute("DELETE FROM sessions")
        conn.commit()
PY

if [ -n "$api_key" ]; then
  update_env "$APP_DIR/.env" TRANSLATOR_API_KEY "$api_key"
  update_env "$APP_DIR/.env" DEEPSEEK_API_KEY "$api_key"
  update_env "$APP_DIR/.env" TRANSLATOR_BASE_URL "$base_url"
fi

sudo systemctl restart ign-daily-api
echo "Secrets configured. API service restarted."
