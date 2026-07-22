#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/ign-daily}"
RUN_USER="${RUN_USER:-ubuntu}"

sudo tee /etc/systemd/system/ign-daily-runtime-permissions.service >/dev/null <<EOF
[Unit]
Description=Repair IGN Daily runtime data permissions

[Service]
Type=oneshot
User=root
ExecStart=$APP_DIR/server_api/deploy/fix_runtime_permissions.sh $APP_DIR/data $RUN_USER
EOF

sudo tee /etc/systemd/system/ign-daily-runtime-permissions.path >/dev/null <<EOF
[Unit]
Description=Watch IGN Daily runtime data permissions

[Path]
PathChanged=$APP_DIR/data
PathChanged=$APP_DIR/exchange_rates.json
Unit=ign-daily-runtime-permissions.service

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now ign-daily-runtime-permissions.path
sudo systemctl start ign-daily-runtime-permissions.service
