# IGN Daily Agent Start

This is the short handoff. Read this first, then only open deeper docs when the
checklist points you there.

## First Command

```bash
python3 scripts/agent_doctor.py
```

Do not rely on memory. If this fails, fix the failed invariant before editing
workflow data.

## Current Owners

| Area | Source of truth | Notes |
|------|-----------------|-------|
| RSS fetch | `.github/workflows/hourly-rss.yml` | Writes `index.json`, `need_titles.json`, `sources/NN.json`, `filtered_rss.json`. |
| Title/summary | `data/automation-config.json.title_translator` | `api` means Actions; `openclaw` means OpenClaw. |
| Fulltext | `data/automation-config.json.fulltext_translator` | API reuses `sources/NN.json`; never ask a model to scrape the page. |
| Nightly learning | `data/automation-config.json.nightly_learner` | API scans recently changed polished/feedback dates, not just today. |
| OpenClaw guard | `scripts/automation_guard.py` | OpenClaw must run this before touching queues. |
| Validation | `scripts/pre_push_check.py {date}` | Required before pushing translated article data. |

## Canonical Data

- Dictionary: `data/dict.json`
- Article index: `data/{YYYY-MM-DD}/index.json`
- English cache: `data/{date}/sources/NN.json`
- Full translation: `data/{date}/translations/NN.json`
- Manual comparison: `data/{date}/comparisons/NN.json`
- Polish edits: `data/{date}/polished/*.json`
- Learning reports: `data/learning/weekly/*.json`
- API usage: `data/usage/deepseek/*.json`, `data/usage/deepseek-runs.json`

## Do Not

- Do not edit queues when `automation_guard.py` says `SKIP`.
- Do not delete historical `data/{date}/` folders.
- Do not write API keys or PATs into tracked files.
- Do not use whole-page HTML as article body. Use `article_cache.py`.
- Do not update `STYLE_PROFILE.md` directly from a single day of edits.

## Where To Self-Check

| Question | Read |
|----------|------|
| Which script should I use? | `scripts/README.md` |
| What should OpenClaw do? | `AGENT_TITLE_TRANSLATOR.md`, `AGENT_NIGHTLY_STYLE.md` if present |
| What are translation rules? | `TRANSLATION_GUIDE.md`, then `STYLE_PROFILE.md` |
| Why did API/OpenClaw skip? | `data/automation-config.json`, `scripts/automation_guard.py` |
| Why did RSS miss/filter an article? | `data/rss-filter-config.json`, `data/{date}/filtered_rss.json` |
| Why did usage/cost look wrong? | `usage.html`, `scripts/usage_logger.py`, `scripts/record_deepseek_run_cost.py` |

## Script Status

- Production: scripts listed as required in `scripts/README.md`.
- Legacy: `scripts/legacy/` only. Do not wire those into cron or Actions.
- Unsure: run `python3 scripts/agent_doctor.py` and inspect `scripts/README.md`
  before changing or deleting a script.
