# IGN Daily server deployment

This project is designed so code can move through GitHub while runtime content
and secrets stay on the server.

## What goes where

- Code and framework changes: commit and push to GitHub.
- Runtime content: `data/`, `exchange_rates.json`, API auth database.
- Secrets: `/srv/ign-daily/.env` and `/srv/ign-daily-api/.env`.

Do not put translator API keys, GitHub tokens, or server passwords in Git.

## Fresh server install

Use Ubuntu 22.04 or 24.04.

```bash
curl -fsSL https://raw.githubusercontent.com/ZenoTzz/ign-daily/main/server_api/deploy/install_server.sh | bash
```

Optional variables:

```bash
REPO_URL=https://github.com/ZenoTzz/ign-daily.git \
SERVER_NAME=your.domain.com \
RUN_USER=ubuntu \
bash install_server.sh
```

Then configure secrets interactively:

```bash
bash /srv/ign-daily/server_api/deploy/configure_secrets.sh
```

Paste the translator API key only in that server prompt. For APIKEY.FUN use the
external-script group and `https://api.apikey.fun/v1`; the Codex-only group
cannot be used by the production website. Do not send the key in chat.

To rotate only the translator credential without changing the admin account,
WeChat settings or article data, use the narrower prompt:

```bash
bash /srv/ign-daily/server_api/deploy/configure_translator_secret.sh
```

Its hidden input is passed to the updater through stdin, and only
`TRANSLATOR_API_KEY` plus `TRANSLATOR_BASE_URL` are changed.

## Backup before replacing a server

```bash
bash /srv/ign-daily/server_api/deploy/backup_data.sh
```

This creates a tarball under `/srv/ign-daily-backups`.

Fresh installs also schedule this backup every day at 03:35. The backup uses
SQLite's online backup API and waits for the server write-job lock. Check
`/var/log/ign-daily/backup.log` after installation.

At 04:10 the server creates a data-only GitHub snapshot from an explicit
whitelist. It uses a disposable clone, never deletes historical article files,
and does not copy automation or external-document configuration. Check
`/var/log/ign-daily/snapshot.log` when diagnosing it.

By default, secrets are not included. To include `.env` files:

```bash
INCLUDE_SECRETS=1 bash /srv/ign-daily/server_api/deploy/backup_data.sh
```

Keep secret backups somewhere private.

## Restore on a new server

1. Run the fresh install script.
2. Upload the backup tarball.
3. Restore it:

```bash
bash /srv/ign-daily/server_api/deploy/restore_data.sh /path/to/ign-daily-backup.tar.gz
```

If the backup did not include secrets, run:

```bash
bash /srv/ign-daily/server_api/deploy/configure_secrets.sh
```

## HTTPS after a domain is ready

Install Certbot and issue a certificate:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your.domain.com
```

Then set secure cookies:

```bash
sudo sed -i 's/^IGN_DAILY_COOKIE_SECURE=.*/IGN_DAILY_COOKIE_SECURE=1/' /srv/ign-daily-api/.env
sudo systemctl restart ign-daily-api
```

Static deployments update both the site tree and the independently running
API copy under `/srv/ign-daily-api`. Runtime `data/`, `exchange_rates.json`,
`ign_rss_new.json`, both `.env` files, and the API database are preserved.
The versioned `translation-memory.json` is the one controlled data exception.

Nginx denies anonymous access to automation configuration, translation memory,
learning evidence and usage/balance data. Authenticated pages read those files
through `/api/files/...`. Browser login uses only an HttpOnly same-origin
cookie; bearer tokens remain available for the mini program and native clients.

## Useful checks

```bash
curl http://127.0.0.1:8010/health
curl http://your.domain.com/api/health
systemctl status ign-daily-api
crontab -l
tail -f /var/log/ign-daily/api-translation.log
```


## Runtime locks and maintenance

RSS/title/fulltext workers take a shared maintenance gate plus a separate
nonblocking worker run lock. Exit 75 means another worker or maintenance is
active; missing translation credentials exit 78. Model calls and source fetches
run outside the API data write lock. Individual commits re-read current data,
check article URL, index inputs and source/translation revisions, and preserve
unrelated edits and newly queued requests. A concurrency conflict stops that
commit; reload and resubmit after checking the newer server state. The post
processor only uses cached images and inherits the parent's short write lock.
Fulltext work first ensures a persisted source cache; failure to cache a valid
source stops before calling a paid model, leaving the request available to retry.

Fresh installs generate these wrappers. Existing servers are updated by the
release deployer using `update_worker_wrappers.py`; this does not reinstall the
server or change secrets/crontab. The three lock files under `/var/lock` must be
writable by the runtime user (`ign-daily-write.lock`, `ign-daily-worker.lock`,
`ign-daily-maintenance.lock`). `IGN_DAILY_WRITE_LOCK` overrides the data lock for
isolated testing; production scripts and API must use the same path.

Restore validates the archive JSON and SQLite before entering maintenance. It
then takes the exclusive maintenance gate, stops the API before changing any
runtime files, and holds the data lock while replacing data, SQLite and optional
secrets together. Originals remain on the same filesystem until health succeeds.
An extraction/validation failure changes nothing; a replacement or health failure
restores all original files, including SQLite sidecars, before restarting the API.
Restored files retain the destination owner/group (or its parent for new files);
SQLite and secrets stay mode 0600 so a restore run under sudo remains usable by
the runtime account.
A backup without SQLite is rejected when the destination already has a database.
Keep an independent backup before maintenance; this procedure does not create an
off-host copy. Workers already running finish before maintenance begins.

## Release rollback boundary

The GitHub artifact includes tracked code and the controlled translation-memory
file; article history, other runtime JSON and the iOS project are not uploaded.
Deployment has a 25-minute allowance for dependency installation and waiting for
an in-progress worker. `deploy_release.py` builds changed dependencies in a new
persistent `/srv/ign-daily-releases/<id>/venv` before stopping the service. It
backs up site code, managed API modules/requirements, four worker wrappers and the controlled
memory file, then installs the candidate under maintenance. If the API health
check fails, it restores the complete code snapshot and previous virtualenv,
not only the main API module. Runtime content, both secrets files and the auth
DB remain excluded from code sync. API deployment uses a managed-file manifest,
not directory mirroring: unrelated modules, alternate virtualenvs and private
backup files are neither deleted nor copied into the release rollback snapshot.

Code environments are created with readable/traversable permissions; rollback
code/worker snapshots are stored in mode-0700 directories. Site/API root directory
ownership and modes survive both sync and rollback.

Successful release snapshots and dependency environments are retained under
`/srv/ign-daily-releases`. Do not delete a release while `/srv/ign-daily-api/venv`
points into it. Nginx/security configuration remains owned by the install/security
scripts; ordinary code deployment no longer rewrites it or chmods all historical
data. An isolated regression test exercises deployment health failure and data/DB
restore success/failure without systemd, network access or production files:

```bash
IGN_DAILY_WRITE_LOCK=/tmp/ign-daily-test.lock PYTHONPATH=scripts \
  python3 -m unittest scripts/test_runtime_transactions.py
```
