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

`trigger_workflow` is optional (default `null`). Omit it in native clients so the
server reads its live `data/automation-config.json`: `fulltext_translator: "api"`
starts the API worker; other owners (including `codex`) queue jobs for their
consumer. Explicit `true`/`false` retain the browser's legacy override behavior.

Native clients should also send optional `expected_urls`, an object mapping every
requested ID (as a string key) to the URL the user selected, for example
`{"2": "https://www.ign.com/articles/example"}`. Under the same write lock as
request/job creation, the server verifies that all requested IDs still exist and
match those URLs. A missing mapping entry, removed article/day or changed URL
returns HTTP 409 without writing requests or creating jobs. The client must
refresh and reselect instead of blindly resubmitting IDs. Omitting this field
(or sending `null`) preserves the legacy ID-only behavior.

Only newly created jobs trigger execution; repeating an active request reuses
its jobs and does not launch another worker. Dates must be real `YYYY-MM-DD`
calendar dates and IDs must be positive.

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
  "job_ids": ["translation-..."],
  "created_job_ids": ["translation-..."],
  "reused_job_ids": [],
  "deduplicated": false,
  "job_batch_size": 2,
  "triggered": false
}
```

Active `queued` or `running` jobs are idempotent by date and article ID. A
repeated request reuses the existing job instead of creating duplicate work;
mixed requests create jobs only for article IDs that are not already active.

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
    "estimate_kind": "range",
    "eta_min_seconds": 480,
    "eta_max_seconds": 1200,
    "results": [
      { "id": 2, "status": "running", "step": "model", "estimate_kind": "range", "eta_min_seconds": 480, "eta_max_seconds": 1200 }
    ],
    "errors": []
  }
}
```

Status values are `queued`, `running`, `done`, and `failed`.

Completion estimates are intentionally coarse and stage-based. `estimate_kind`
is `scheduled` while queued, `range` during normal processing, `uncertain`
during repair, and `complete` after completion. Clients should display the
`eta_min_seconds`–`eta_max_seconds` range instead of treating `eta_seconds` as
a precise countdown; the legacy midpoint remains only for older clients.

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

Translation requests are split into jobs containing at most two articles.
`POST /codex/jobs/{job_id}/complete` marks a job complete only after every
translation file exists, its index state is consistent, required model/prompt
metadata is present, and the independent coverage/quote/numeric review gate has
passed. The same gate applies to `progress` requests with `status: "done"` and
to inferred completion. Empty/malformed files, URL drift, empty paragraphs, and
paragraphs not aligned with the source cache cannot complete a job. New jobs
store the selected URLs, so reassigning an ID does not complete the old job.

Local workers persist their PID identity, start time and associated jobs in
SQLite. Exit without valid output or timeout marks unfinished jobs failed so
resubmission can create fresh work. `IGN_DAILY_JOB_TIMEOUT_SECONDS` defaults to
3600. Logs are private files under the API directory `job-logs/` (mode 0600);
API responses do not expose raw logs. Startup reconnects to matching Linux
process identities rather than blindly restarting a still-running worker.

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


## Native article polishing

Authenticated `GET /articles/{date}/{article_id}/polish` and
`PUT /articles/{date}/{article_id}/polish` require local server storage.
Both return the same envelope:

```json
{
  "ok": true,
  "exists": false,
  "revision": null,
  "draft": {"title": "", "subtitle": "", "summary": "", "body": ""}
}
```

An existing draft includes its content revision and `draft.updated_at`. GET reads
`polished/_index.json` and accepts an indexed file only when its URL matches the
current article. Otherwise it prefills from a matching translation (falling back
to article metadata); it never returns another article's old draft after ID drift.
PUT requires every field below, including an explicit `expected_revision`:

```json
{
  "url": "https://www.ign.com/articles/example",
  "expected_revision": null,
  "title": "润色标题",
  "subtitle": "副标题",
  "summary": "摘要",
  "body": "第一段\n第二段"
}
```

Use `null` only to create an absent draft. To edit, send the exact revision from
GET or the preceding PUT. The server verifies URL identity and revision under
its shared write lock; stale saves and concurrent creates return HTTP 409.
Clients must keep their unsaved text and reload/resolve the conflict rather than
silently retrying against the new revision. Invalid dates, IDs and indexed paths
return 400; missing articles return 404; non-local storage returns 501.

PUT preserves unrelated document metadata and index entries. It writes the
existing browser-compatible polished schema (`id`, `url`, `cn_title`, `en_title`,
`category`, four editable text fields, nonempty line-split `paragraphs`, and
`updated_at`), then updates `_index.json`. Unindexed or unrelated old files are
preserved. Two JSON files are serialized but are not a crash-atomic transaction.
This saves a user polish draft only: no translation quality approval, job, Docs
sync or style-profile update is triggered.


## Browser concurrency contracts

- `GET /files/data/dict.json` returns `content` and its SHA-1 `sha`.
  `PUT /dict` now requires `expected_revision` containing that SHA in addition
  to `dictionary` and optional `message`; stale snapshots return 409.
- `PUT /dict/terms` edits or moves one entry. Send `original_category`,
  `original_en`, `expected_entry` (the complete original JSON value), `category`,
  `en`, `cn`, and optional `note`. It preserves other metadata and unrelated
  entries; a changed original or occupied destination returns 409. Response:
  `{ok, entry, revision}`. Existing `GET /dict` and `POST /dict/terms` remain
  compatible with native clients.
- `PUT /files/{path}` accepts `sha` for an existing-file compare-and-swap.
  For creation, send `expected_absent: true`; an intervening create returns
  409. Successful writes also return the new `sha`. Legacy omitted guards
  remain supported; new browser editors must explicitly send a guard.
- `POST /translations/approve` requires `date`, `article_id`, the selected
  `url`, and `expected_revision` from the translation file read. The entire
  read/modify/write is locked; changed content or identity returns 409.
  Human approval still requires valid source alignment and nonempty output.
- `DELETE /articles/{date}/{article_id}/polish` takes `{url, expected_revision}`.
  It validates both under the write lock, removes the mapping and then the
  unreferenced draft, returning `{ok:true, exists:false, revision:null}`.
  A stale/missing draft returns 409. Other historical or unindexed drafts are
  preserved. As with saving, mapping and file are not a crash-atomic transaction;
  deleting the mapping first ensures interruption only leaves an unindexed file.
