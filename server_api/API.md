# IGN Daily Private API

Base URL: `https://igndaily.site/api`

All private endpoints accept the browser session cookie or:

```http
Authorization: Bearer <token>
```

The token is returned by `POST /auth/login`. This header-based auth is suitable for iOS apps and WeChat mini programs.

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

`POST /auth/account` updates username and/or password. It requires the current password.

## Translation Jobs

`POST /translations/request`

```json
{
  "date": "2026-06-25",
  "ids": [2],
  "trigger_workflow": true
}
```

Response:

```json
{
  "ok": true,
  "date": "2026-06-25",
  "requested_ids": [2],
  "job_id": "translation-...",
  "triggered": true
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
