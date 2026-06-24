# IGN Daily server deployment

This project is designed so code can move through GitHub while runtime content
and secrets stay on the server.

## What goes where

- Code and framework changes: commit and push to GitHub.
- Runtime content: `data/`, `exchange_rates.json`, API auth database.
- Secrets: `/srv/ign-daily/.env` and `/srv/ign-daily-api/.env`.

Do not put DeepSeek keys, GitHub tokens, or server passwords in Git.

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

Paste the DeepSeek API key only in that server prompt. Do not send it in chat.

## Backup before replacing a server

```bash
bash /srv/ign-daily/server_api/deploy/backup_data.sh
```

This creates a tarball under `/srv/ign-daily-backups`.

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

## Useful checks

```bash
curl http://127.0.0.1:8010/health
curl http://your.domain.com/api/health
systemctl status ign-daily-api
crontab -l
tail -f /var/log/ign-daily/api-translation.log
```

