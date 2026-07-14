#!/usr/bin/env bash
set -euo pipefail

SITE_CONFIG="${SITE_CONFIG:-/etc/nginx/sites-available/ign-daily}"
SNIPPET="${SNIPPET:-/etc/nginx/snippets/ign-daily-private-data.conf}"

if [ ! -f "$SITE_CONFIG" ]; then
  echo "Nginx site config is missing: $SITE_CONFIG" >&2
  exit 1
fi

backup="$(mktemp)"
cp "$SITE_CONFIG" "$backup"
restore() {
  cp "$backup" "$SITE_CONFIG"
  rm -f "$backup"
}
trap restore ERR

install -d -m 0755 "$(dirname "$SNIPPET")"
cat >"$SNIPPET" <<'EOF'
# Internal runtime state is available only through the authenticated API.
location = /data/agent-worklog.jsonl { return 404; }
location = /data/automation-config.json { return 404; }
location = /data/google-polish-config.json { return 404; }
location = /data/tencent-polish-config.json { return 404; }
location = /data/translation-memory.json { return 404; }
location = /data/rss-filter-config.json { return 404; }
location ^~ /data/learning/ { return 404; }
location ^~ /data/learning_log/ { return 404; }
location ^~ /data/usage/ { return 404; }
EOF
chmod 0644 "$SNIPPET"

python3 - "$SITE_CONFIG" "$SNIPPET" <<'PY'
from pathlib import Path
import sys

site = Path(sys.argv[1])
snippet = sys.argv[2]
include = f"    include {snippet};"
text = site.read_text(encoding="utf-8")
if include not in text:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("server_name "):
            lines.insert(index + 1, "")
            lines.insert(index + 2, include)
            break
    else:
        raise SystemExit("server_name directive not found")
    site.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY

nginx -t
systemctl reload nginx
trap - ERR
rm -f "$backup"
echo "NGINX_PRIVATE_DATA_OK"
