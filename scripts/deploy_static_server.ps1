param(
  [string]$HostName = "81.71.155.51",
  [string]$User = "ubuntu",
  [string]$KeyPath = ".codex-server-access/ign_daily_server_key",
  [string]$ServerPath = "/srv/ign-daily"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$archive = Join-Path $env:TEMP "ign-daily-static-$([guid]::NewGuid().ToString('N')).tar"

Push-Location $repoRoot
try {
  git archive --format=tar -o $archive HEAD
  scp -i $KeyPath -o StrictHostKeyChecking=no -o ConnectTimeout=15 $archive "${User}@${HostName}:/tmp/ign-daily-static.tar"
  ssh -i $KeyPath -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=15 "${User}@${HostName}" @"
set -euo pipefail
deploy_dir="/tmp/ign-daily-static-deploy"
rm -rf "`$deploy_dir"
mkdir -p "`$deploy_dir"
tar -xf /tmp/ign-daily-static.tar -C "`$deploy_dir"
sudo rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude 'exchange_rates.json' \
  --exclude 'server_api/.env' \
  "`$deploy_dir"/ "$ServerPath"/
sudo chown -R ${User}:${User} "$ServerPath"
sudo find "$ServerPath" -type d -exec chmod 755 {} +
sudo find "$ServerPath" -type f -exec chmod 644 {} +
rm -rf "`$deploy_dir" /tmp/ign-daily-static.tar
"@
}
finally {
  Pop-Location
  if (Test-Path $archive) {
    Remove-Item $archive -Force
  }
}
