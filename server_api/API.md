# IGN Daily Private API

Base URL: `https://igndaily.site/api`

All private endpoints accept the browser session cookie or:

```http
Authorization: Bearer <token>
```

The token is returned by `POST /auth/login`. This header-based auth is suitable for iOS apps and WeChat mini programs.

The generic `/files/{path}` endpoints are intentionally limited to JSON files
under `data/`. They cannot read secrets or modify application code.

Failed logins are limited per client address. Eight failures in a 15-minute
window temporarily block further attempts from that address.

## Auth

`POST /auth/login`

```json
{
  "username": "ZenoT",
  "password": "your-password"
}
```

Response:

```json
{
  "ok": true,
  "token": "...",
  "user": {
    "username": "ZenoT"
  }
}
```

`GET /auth/me` returns the current user.

### WeChat administrator binding

`POST /auth/wechat/login` accepts the temporary `code` returned by `wx.login`.
The server exchanges it with WeChat and never sends the AppSecret to the mini
program. If the OpenID is already bound, the response contains the normal
Bearer token. An unbound OpenID receives a short-lived `bind_token` instead.

`POST /auth/wechat/bind` accepts `bind_token`, `username`, and `password`.
Valid administrator credentials bind that OpenID to the existing server user
and return a Bearer token. The one-time binding challenge expires after ten
minutes. Configure `IGN_DAILY_WECHAT_APPID` and
`IGN_DAILY_WECHAT_APP_SECRET` only in `/srv/ign-daily-api/.env`.

`POST /auth/account` updates username and/or password. It requires the current password.

## Translation Jobs

`POST /translations/request`

```json
{
  "date": "2026-06-25",
  "ids": [2],
  "trigger_workflow": false
}
```

Response:

```json
{
  "ok": true,
  "date": "2026-06-25",
  "requested_ids": [2],
  "job_id": "translation-...",
  "triggered": false
}
```

`GET /jobs/{job_id}` returns progress for one job.

```json
{
  "ok": true,
  "job": {
    "id": "translation-...",
    "kind": "translation",
    "status": "running",
    "date": "2026-06-25",
    "ids": [2],
    "message": "服务器正在翻译",
    "progress": 10,
    "results": [
      { "id": 2, "status": "running" }
    ],
    "errors": []
  }
}
```

Status values are `queued`, `running`, `done`, and `failed`.

`GET /jobs?kind=translation&limit=5` returns recent jobs, useful when a client needs to recover state after reopening.

## Codex Queue

These endpoints are for Codex batch runs. They use the same bearer token as the
web and mini program login.

`GET /codex/jobs/pending?limit=5` returns queued/running translation jobs with
article metadata and cached source payloads.

`POST /codex/jobs/{job_id}/claim` marks a queued job as running.

`POST /codex/jobs/{job_id}/progress`

```json
{
  "article_id": 30,
  "status": "running",
  "step": "codex",
  "step_label": "Codex translating",
  "progress": 45,
  "message": "Drafting paragraphs"
}
```

`POST /codex/jobs/{job_id}/complete` marks a job complete after Codex has written
the translation files.

`POST /codex/jobs/{job_id}/fail` records a job-level failure.

## Filtered RSS

`POST /filtered/restore` restores one article from `data/{date}/filtered_rss.json` into that day's `index.json`, queues it in `need_titles.json`, updates `data/index-list.json`, and removes it from the filtered list.

```json
{
  "date": "2026-06-26",
  "url": "https://www.ign.com/articles/example",
  "trigger_workflow": false
}
```

Response:

```json
{
  "ok": true,
  "date": "2026-06-26",
  "article": { "id": 12 },
  "filtered_count": 3,
  "duplicate": false,
  "queued": true,
  "triggered": false
}
```

## WeChat completion subscriptions

`GET /wechat/config` returns the configured translation-complete template ID.
`POST /wechat/subscriptions` records one accepted one-time subscription credit
for the bound WeChat administrator. Completing a Codex translation job consumes
at most one credit and sends one deduplicated message linking to the task page.
No new-article or general news notifications are sent.

## Dictionary candidates

`POST /dict/candidates` accepts `{en, cn, category, note}` from the mini program.
It writes a pending candidate to `data/dict_candidates.json`; it never changes
the production `data/dict.json` until the candidate is reviewed elsewhere.

`GET /dict/candidates?status=pending` returns candidates with any matching
official entries and a derived `has_conflict` flag. Review actions are explicit:

- `POST /dict/candidates/{id}/approve` accepts optional `{cn, category, note}`,
  writes the reviewed term to `data/dict.json`, and archives the candidate.
- `POST /dict/candidates/{id}/reject` archives the candidate without changing
  the production dictionary.
