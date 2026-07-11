#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ZenoTzz/ign-daily.git}"
APP_DIR="${APP_DIR:-/srv/ign-daily}"
APP_VENV="${APP_VENV:-/srv/ign-daily-venv}"
API_DIR="${API_DIR:-/srv/ign-daily-api}"
API_PORT="${API_PORT:-8010}"
SERVER_NAME="${SERVER_NAME:-_}"
RUN_USER="${RUN_USER:-${SUDO_USER:-ubuntu}}"

APP_DIR="$(realpath -m "$APP_DIR")"
APP_VENV="$(realpath -m "$APP_VENV")"
API_DIR="$(realpath -m "$API_DIR")"

for managed_path in "$APP_DIR" "$API_DIR" "$APP_VENV"; do
  case "$managed_path" in
    /srv/*) ;;
    *) echo "Refusing unsafe managed path: $managed_path" >&2; exit 1 ;;
  esac
done

if ! id "$RUN_USER" >/dev/null 2>&1; then
  RUN_USER="$(id -un)"
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y git nginx python3 python3-venv python3-pip curl unzip

sudo mkdir -p "$APP_DIR" "$APP_VENV" "$API_DIR" /var/log/ign-daily /srv/ign-daily-ops
sudo chown -R "$RUN_USER:$RUN_USER" "$APP_DIR" "$APP_VENV" "$API_DIR" /var/log/ign-daily /srv/ign-daily-ops

if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$RUN_USER" git -C "$APP_DIR" pull --ff-only origin main
else
  if find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "Refusing to replace non-empty directory without a Git repository: $APP_DIR" >&2
    exit 1
  fi
  sudo -u "$RUN_USER" git clone "$REPO_URL" "$APP_DIR"
fi

sudo -u "$RUN_USER" python3 -m venv "$APP_VENV"
sudo -u "$RUN_USER" "$APP_VENV/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$APP_VENV/bin/pip" install requests beautifulsoup4 lxml python-dotenv openpyxl

sudo -u "$RUN_USER" cp "$APP_DIR/server_api/ign_daily_api.py" "$API_DIR/ign_daily_api.py"
sudo -u "$RUN_USER" cp "$APP_DIR/server_api/requirements.txt" "$API_DIR/requirements.txt"
sudo -u "$RUN_USER" python3 -m venv "$API_DIR/venv"
sudo -u "$RUN_USER" "$API_DIR/venv/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$API_DIR/venv/bin/pip" install -r "$API_DIR/requirements.txt"

if [ ! -f "$API_DIR/.env" ]; then
  admin_password="$(python3 - <<'PY'
import secrets, string
alphabet = string.ascii_letters + string.digits
print("".join(secrets.choice(alphabet) for _ in range(24)))
PY
)"
  sudo -u "$RUN_USER" tee "$API_DIR/.env" >/dev/null <<EOF
IGN_DAILY_ADMIN_USER=admin
IGN_DAILY_ADMIN_PASSWORD=$admin_password
IGN_DAILY_STORAGE_MODE=local
IGN_DAILY_COOKIE_SECURE=0
IGN_DAILY_CORS_ORIGINS=
IGN_DAILY_WECHAT_APPID=
IGN_DAILY_WECHAT_APP_SECRET=
EOF
  sudo chmod 600 "$API_DIR/.env"
  echo "Generated temporary API admin password: $admin_password"
  echo "Run server_api/deploy/configure_secrets.sh to replace it."
fi

cat >/tmp/ign-daily-api.service <<EOF
[Unit]
Description=IGN Daily Private API
After=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$API_DIR
EnvironmentFile=-$API_DIR/.env
ExecStart=$API_DIR/venv/bin/uvicorn ign_daily_api:app --host 127.0.0.1 --port $API_PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo mv /tmp/ign-daily-api.service /etc/systemd/system/ign-daily-api.service

cat >/tmp/ign-daily-nginx <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name $SERVER_NAME;

    root $APP_DIR;
    index index.html;
    charset utf-8;
    client_max_body_size 20m;

    location /api/ {
        proxy_pass http://127.0.0.1:$API_PORT/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location ^~ /.well-known/acme-challenge/ {
        root /var/www/html;
        default_type text/plain;
    }

    location ~ /\\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    location = /sw.js {
        add_header Cache-Control "no-store";
        try_files \$uri =404;
    }

    location ~* \\.(?:html|json)$ {
        add_header Cache-Control "no-store";
        try_files \$uri =404;
    }

    location /data/ {
        add_header Cache-Control "no-store";
        try_files \$uri =404;
    }

    location ~* \\.(?:js|css|png|jpg|jpeg|webp|gif|svg|ico|xlsx)$ {
        expires 7d;
        add_header Cache-Control "public";
        try_files \$uri =404;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
sudo mv /tmp/ign-daily-nginx /etc/nginx/sites-available/ign-daily
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/ign-daily /etc/nginx/sites-enabled/ign-daily

cat >/tmp/ign-daily-config-env.sh <<EOF
#!/usr/bin/env bash
APP_DIR=$APP_DIR
PY=$APP_VENV/bin/python
export APP_DIR PY
export PYTHONUNBUFFERED=1
export IGN_DAILY_SKIP_GIT=1
load_automation_config() {
  eval "\$(\$PY - <<'PYCONF'
import json, shlex
from pathlib import Path
path = Path('$APP_DIR/data/automation-config.json')
data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
def emit(key, value):
    print(f"export {key}={shlex.quote(str(value if value is not None else ''))}")
emit('TITLE_TRANSLATOR', data.get('title_translator', 'openclaw'))
emit('FULLTEXT_TRANSLATOR', data.get('fulltext_translator', 'openclaw'))
emit('API_BASE_URL', data.get('api_base_url') or 'https://api.deepseek.com')
emit('API_TITLE_MODEL', data.get('api_title_model') or data.get('api_model') or 'deepseek-v4-flash')
emit('API_FULLTEXT_MODEL', data.get('api_fulltext_model') or data.get('api_model') or 'deepseek-v4-pro')
emit('API_TITLE_THINKING', data.get('api_title_thinking') or 'disabled')
emit('API_FULLTEXT_THINKING', data.get('api_fulltext_thinking') or 'disabled')
batch = str(data.get('api_fulltext_batch') or '5').strip().lower()
emit('API_FULLTEXT_LIMIT', '999' if batch == 'all' else batch)
PYCONF
)"
}
api_key_available() {
  \$PY - <<'PYKEY'
from pathlib import Path
keys = {}
p = Path('$APP_DIR/.env')
if p.exists():
    for line in p.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
print('1' if any(keys.get(k) for k in ['TRANSLATOR_API_KEY', 'DEEPSEEK_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY']) else '0')
PYKEY
}
with_write_lock() {
  exec 9>/var/lock/ign-daily-write.lock
  flock -n 9 || { echo "IGN_DAILY_LOCKED: another write job is running"; exit 0; }
}
EOF
sudo -u "$RUN_USER" mv /tmp/ign-daily-config-env.sh /srv/ign-daily-ops/config-env.sh

cat >/tmp/ign-daily-run-rss.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source /srv/ign-daily-ops/config-env.sh
with_write_lock
load_automation_config
cd "$APP_DIR"
$PY scripts/ign_rss_incremental.py --lookback-days 2
$PY scripts/article_cache.py --all --queued --missing --limit 20 || true
if [[ "$(api_key_available)" == "1" && ( "$TITLE_TRANSLATOR" == "api" || "$TITLE_TRANSLATOR" == "deepseek" ) ]]; then
  export TRANSLATOR_BASE_URL="$API_BASE_URL"
  export TRANSLATOR_MODEL="$API_TITLE_MODEL"
  export TRANSLATOR_TITLE_LIMIT=30
  export TRANSLATOR_THINKING_MODE="$API_TITLE_THINKING"
  $PY scripts/fetch_exchange_rates.py
  $PY scripts/translate_titles_deepseek.py --all
fi
$PY scripts/agent_doctor.py
EOF

cat >/tmp/ign-daily-run-api-translation.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source /srv/ign-daily-ops/config-env.sh
with_write_lock
load_automation_config
cd "$APP_DIR"
if [[ "$(api_key_available)" != "1" ]]; then
  echo "API_TRANSLATION_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY/GEMINI_API_KEY is not set"
  exit 0
fi
if [[ "$TITLE_TRANSLATOR" == "api" || "$TITLE_TRANSLATOR" == "deepseek" ]]; then
  export TRANSLATOR_BASE_URL="$API_BASE_URL"
  export TRANSLATOR_MODEL="$API_TITLE_MODEL"
  export TRANSLATOR_TITLE_LIMIT=30
  export TRANSLATOR_THINKING_MODE="$API_TITLE_THINKING"
  $PY scripts/article_cache.py --all --queued --missing --limit 30 || true
  $PY scripts/translate_titles_deepseek.py --all
fi
if [[ "$FULLTEXT_TRANSLATOR" == "api" || "$FULLTEXT_TRANSLATOR" == "deepseek" ]]; then
  export TRANSLATOR_BASE_URL="$API_BASE_URL"
  export TRANSLATOR_MODEL="$API_FULLTEXT_MODEL"
  export TRANSLATOR_FULLTEXT_LIMIT="$API_FULLTEXT_LIMIT"
  export TRANSLATOR_FULLTEXT_TIME_BUDGET_SECONDS=1200
  export TRANSLATOR_FULLTEXT_MAX_TOKENS=12000
  export TRANSLATOR_THINKING_MODE="$API_FULLTEXT_THINKING"
  $PY scripts/fetch_exchange_rates.py
  $PY scripts/article_cache.py --all --queued --missing --limit "$TRANSLATOR_FULLTEXT_LIMIT" || true
  $PY scripts/translate_fulltext_api.py --all
fi
$PY scripts/agent_doctor.py
EOF

cat >/tmp/ign-daily-run-exchange.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source /srv/ign-daily-ops/config-env.sh
with_write_lock
cd "$APP_DIR"
$PY scripts/fetch_exchange_rates.py
$PY scripts/agent_doctor.py
EOF

cat >/tmp/ign-daily-run-balance.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source /srv/ign-daily-ops/config-env.sh
with_write_lock
load_automation_config
cd "$APP_DIR"
if [[ "$(api_key_available)" != "1" ]]; then
  echo "BALANCE_SKIP: TRANSLATOR_API_KEY/DEEPSEEK_API_KEY/GEMINI_API_KEY is not set"
  exit 0
fi
export TRANSLATOR_BASE_URL="$API_BASE_URL"
$PY scripts/deepseek_balance.py
EOF

sudo -u "$RUN_USER" mv /tmp/ign-daily-run-rss.sh /srv/ign-daily-ops/run-rss.sh
sudo -u "$RUN_USER" mv /tmp/ign-daily-run-api-translation.sh /srv/ign-daily-ops/run-api-translation.sh
sudo -u "$RUN_USER" mv /tmp/ign-daily-run-exchange.sh /srv/ign-daily-ops/run-exchange.sh
sudo -u "$RUN_USER" mv /tmp/ign-daily-run-balance.sh /srv/ign-daily-ops/run-balance.sh
chmod +x /srv/ign-daily-ops/*.sh

cat >/tmp/ign-daily-cron <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

17,47 * * * * /srv/ign-daily-ops/run-rss.sh >> /var/log/ign-daily/rss.log 2>&1
20,50 * * * * /srv/ign-daily-ops/run-api-translation.sh >> /var/log/ign-daily/api-translation.log 2>&1
20 8 * * * /srv/ign-daily-ops/run-exchange.sh >> /var/log/ign-daily/exchange.log 2>&1
*/30 * * * * /srv/ign-daily-ops/run-balance.sh >> /var/log/ign-daily/balance.log 2>&1
35 3 * * * $APP_DIR/server_api/deploy/backup_data.sh >> /var/log/ign-daily/backup.log 2>&1
EOF
sudo -u "$RUN_USER" crontab /tmp/ign-daily-cron
rm -f /tmp/ign-daily-cron

sudo tee /etc/logrotate.d/ign-daily >/dev/null <<'EOF'
/var/log/ign-daily/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
}
EOF

sudo systemctl daemon-reload
sudo systemctl enable ign-daily-api
sudo systemctl restart ign-daily-api
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx

echo "Install complete."
echo "Visit: http://$SERVER_NAME/"
echo "API health: http://$SERVER_NAME/api/health"
