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
preserve_dir="/tmp/ign-daily-static-preserve-`$`$"
restore_preserved() {
  if [ -d "`$preserve_dir/data" ]; then
    sudo rm -rf "$ServerPath/data"
    sudo mv "`$preserve_dir/data" "$ServerPath/data"
  fi
  if [ -f "`$preserve_dir/exchange_rates.json" ]; then
    sudo mv "`$preserve_dir/exchange_rates.json" "$ServerPath/exchange_rates.json"
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
tar -xf /tmp/ign-daily-static.tar -C "`$deploy_dir"
sudo rsync -a --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'server_api/.env' \
  "`$deploy_dir"/ "$ServerPath"/
restore_preserved
trap - EXIT
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
