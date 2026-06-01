# Agent Title Translator

This file is the startup guide for the OpenClaw isolated cron named
`IGN Title Summary Translator`.

## Purpose

Translate RSS queue items created by GitHub Actions. Do not fetch RSS here.
GitHub Actions owns RSS ingestion through `.github/workflows/hourly-rss.yml`.

## Schedule

- Suggested cadence: every hour at minute 30.
- Run in an isolated agent session, not the user's main chat session.
- If another run is still active, skip or stop. Never run two translators at once.

## Required Steps

1. Pull the latest main branch.

```bash
git pull --rebase origin main
```

1.5. Read `data/automation-config.json`.

If `title_translator` is `api` or `deepseek`, exit quietly with `HEARTBEAT_OK`.
GitHub Actions will handle title/summary translation in API mode. Do not also
edit `need_titles.json`.

Recommended guard command:

```bash
python3 scripts/automation_guard.py title
```

If it prints `AUTOMATION_GUARD SKIP`, stop immediately and return `HEARTBEAT_OK`.

2. Find the target date.

Check recent folders under `data/` and process any `need_titles.json` that exists
and is non-empty. Usually this is today's publishing window date.

3. Load:

- `data/{date}/index.json`
- `data/{date}/need_titles.json`
- `data/dict.json`
- `TRANSLATION_GUIDE.md`
- `STYLE_PROFILE.md` if present

4. For each queue item, match the article by URL, not by stale ID.

IDs can move when RSS inserts new articles. URL is the stable key.

5. Fetch the original article page with `web_fetch`.

Use the queue item's `url`. If fetching fails, leave the item in
`need_titles.json`, do not invent details, and notify the user.

6. Translate only the homepage metadata:

- `cn_title`
- `summary`
- `category`
- `emoji`

Do not translate the full article body. Do not write `translations/NN.json` here.

7. Follow dictionary rules.

- Use `data/dict.json` translations when an English term appears.
- Unknown names should usually remain in English.
- New guessed terms go to `pending_dict`; do not silently add them to the main dictionary.

8. Keep publish-time fields intact.

Every article must keep `publish_time_cn`. Do not remove or rename it. Existing
`pub_date` is compatibility data and may remain.

9. Remove only successfully translated queue items.

After updating the matching article in `index.json`, remove that URL from
`need_titles.json`. Leave failed or unfetched items in the queue.

10. Validate before pushing.

```bash
python3 scripts/pre_push_check.py {date}
python3 scripts/agent_doctor.py
```

If validation fails, do not push. Report the failure.

11. Commit and push only relevant files.

Expected changed files:

- `data/{date}/index.json`
- `data/{date}/need_titles.json`
- possibly `data/index-list.json`

Never commit `.env`, `scripts/.env`, `__pycache__`, logs, or local cache files.

Suggested commit message:

```text
feat: translate queued titles for {date}
```

## Safety Rules

- Do not run `scripts/ign_rss_incremental.py`.
- Do not delete historical `data/{date}/` folders.
- Do not force-push.
- Do not overwrite remote changes. If `git pull --rebase` conflicts, stop and notify the user.
- If there are no queued titles, exit quietly.
- If queue processing takes too long, process a small batch and leave the rest for the next run.
- For full-article translation requests, always match `requests.json.requested_articles[].url` to the current `index.json` article. Do not trust `requested_ids` alone.
- Respect the 8:00 CST publishing window: `data/YYYY-MM-DD` covers the previous day 08:00 through that date 08:00.

## Completion Report

When the cron finishes, report only if something changed or failed:

- date processed
- number of titles translated
- validation result
- commit hash or push failure
