param(
  [string]$HostName = "81.71.155.51",
  [string]$User = "ubuntu",
  [string]$KeyPath = ".codex-server-access/ign_daily_server_key",
  [string]$ServerPath = "/srv/ign-daily",
  [string]$ApiPath = "/srv/ign-daily-api"
)

$ErrorActionPreference = "Stop"
if (
  $ServerPath -notmatch '^/srv/[A-Za-z0-9._/-]+$' -or
  $ApiPath -notmatch '^/srv/[A-Za-z0-9._/-]+$' -or
  $ServerPath -match '(^|/)\.\.(/|$)' -or
  $ApiPath -match '(^|/)\.\.(/|$)'
) {
  throw "ServerPath and ApiPath must be absolute paths under /srv."
}
if ($User -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
  throw "User contains unsupported characters."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$archive = Join-Path $env:TEMP "ign-daily-static-$([guid]::NewGuid().ToString('N')).tar"

Push-Location $repoRoot
try {
  git archive --format=tar -o $archive HEAD
  scp -i $KeyPath -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 $archive "${User}@${HostName}:/tmp/ign-daily-static.tar"
  ssh -i $KeyPath -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=15 "${User}@${HostName}" @"
set -euo pipefail
deploy_dir="/tmp/ign-daily-static-deploy"
preserve_dir="/tmp/ign-daily-static-preserve-`$`$"
restore_preserved() {
  if [ -d "`$preserve_dir/data" ]; then
    sudo rm -rf "$ServerPath/data"
    sudo mv "`$preserve_dir/data" "$ServerPath/data"
  fi
  if [ -f "`$preserve_dir/exchange_rates.json" ]; then
    sudo mv "`$preserve_dir/exchange_rates.json" "$ServerPath/exchange_rates.json"
  fi
  if [ -f "`$preserve_dir/ign_rss_new.json" ]; then
    sudo mv "`$preserve_dir/ign_rss_new.json" "$ServerPath/ign_rss_new.json"
  fi
  sudo rm -rf "`$preserve_dir"
}
trap restore_preserved EXIT
rm -rf "`$deploy_dir"
mkdir -p "`$deploy_dir" "`$preserve_dir"
if [ -d "$ServerPath/data" ]; then
  sudo mv "$ServerPath/data" "`$preserve_dir/data"
fi
if [ -f "$ServerPath/exchange_rates.json" ]; then
  sudo mv "$ServerPath/exchange_rates.json" "`$preserve_dir/exchange_rates.json"
fi
if [ -f "$ServerPath/ign_rss_new.json" ]; then
  sudo mv "$ServerPath/ign_rss_new.json" "`$preserve_dir/ign_rss_new.json"
fi
tar -xf /tmp/ign-daily-static.tar -C "`$deploy_dir"
sudo rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'server_api/.env' \
  "`$deploy_dir"/ "$ServerPath"/
restore_preserved
trap - EXIT
if [ ! -f "$ServerPath/data/translation-memory.json" ] && [ -f "`$deploy_dir/data/translation-memory.json" ]; then
  sudo install -o ${User} -g ${User} -m 0644 \
    "`$deploy_dir/data/translation-memory.json" "$ServerPath/data/translation-memory.json"
fi
sudo chown -R ${User}:${User} "$ServerPath"
sudo find "$ServerPath" -path "$ServerPath/.git" -prune -o -type d -exec chmod 755 {} +
sudo find "$ServerPath" -path "$ServerPath/.git" -prune -o -type f ! -name '.env' -exec chmod 644 {} +
if [ -f "$ServerPath/.env" ]; then
  sudo chmod 600 "$ServerPath/.env"
fi
if [ ! -x "$ApiPath/venv/bin/pip" ]; then
  echo "IGN Daily API virtualenv is missing: $ApiPath/venv/bin/pip" >&2
  exit 1
fi
if ! cmp -s "$ServerPath/server_api/requirements.txt" "$ApiPath/requirements.txt"; then
  sudo -u ${User} "$ApiPath/venv/bin/pip" install -r "$ServerPath/server_api/requirements.txt"
  sudo install -o ${User} -g ${User} -m 644 \
    "$ServerPath/server_api/requirements.txt" "$ApiPath/requirements.txt"
fi
api_backup="/tmp/ign-daily-api-backup-`$`$.py"
sudo cp "$ApiPath/ign_daily_api.py" "`$api_backup"
sudo install -o ${User} -g ${User} -m 644 \
  "$ServerPath/server_api/ign_daily_api.py" "$ApiPath/ign_daily_api.py"
if ! sudo systemctl restart ign-daily-api || \
   ! curl --retry 10 --retry-delay 1 --retry-connrefused --max-time 5 -fsS http://127.0.0.1:8010/health >/dev/null; then
  echo 'API health check failed; restoring the previous API module.' >&2
  sudo install -o ${User} -g ${User} -m 644 "`$api_backup" "$ApiPath/ign_daily_api.py"
  sudo systemctl restart ign-daily-api
  exit 1
fi
sudo rm -f "`$api_backup"
rm -rf "`$deploy_dir" /tmp/ign-daily-static.tar
"@
}
finally {
  Pop-Location
  if (Test-Path $archive) {
    Remove-Item $archive -Force
  }
}
