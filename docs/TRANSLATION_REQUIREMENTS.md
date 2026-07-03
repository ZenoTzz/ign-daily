# IGN Daily Translation Requirements

Last updated: 2026-07-02

This is the compact source of truth for day-to-day translation work. If this
file conflicts with older handoff notes, follow this file, then check
`TRANSLATION_GUIDE.md` and `STYLE_PROFILE.md` for style detail.

## Required Reading

Before handling a translation queue, read:

1. `docs/AGENT_START.md`
2. `AGENT_BOOTSTRAP.md`
3. `AGENT_HANDOFF.md`
4. `TRANSLATION_GUIDE.md`
5. `STYLE_PROFILE.md`
6. `AGENT_NIGHTLY_LEARNER.md`
7. `data/automation-config.json`
8. `data/dict.json`

## Current Automation Ownership

- `title_translator=api`: title and summary translation are handled by Actions/API.
- `fulltext_translator=codex`: full article translation is handled by Codex when
  the user says they submitted or selected articles.
- `nightly_learner=codex`: nightly learning is handled by Codex, using Google
  Docs polish import first and Tencent Docs only as historical fallback.

Do not call DeepSeek, Gemini, or OpenAI APIs from Codex unless the user
explicitly asks for API translation. Do not print or ask for PATs or API keys.

## Queue Handling

When the user says `处理翻译队列`, `我刚刚提交了一批翻译`, or equivalent:

1. Pull or fetch the newest `main` state before trusting local queue files.
2. Read every `data/*/requests.json` that may contain queued requests.
3. Match each requested article by `requested_articles[].url` against the
   current `data/{date}/index.json`. `requested_ids` is only a compatibility
   hint and must not be the only matching key.
4. Read the source article from `data/{date}/sources/NN.json`.
5. Refresh or verify exchange rates before translating any batch:
   `python scripts/fetch_exchange_rates.py`. If the network is unavailable,
   use `exchange_rates.json` only when it is multi-source verified and still
   fresh under the script's freshness rule.
6. Run `python scripts/translate_pipeline.py {date} {id} --prep`.
7. Recreate the reader-facing Chinese title, subtitle, and summary yourself.
   Do not simply reuse existing `index.json.cn_title`, `index.json.summary`, or
   API/DeepSeek V4 Flash output. Those fields may be low-quality placeholders
   and are only references.
8. Write `data/{date}/translations/NN.json`, with two-digit zero padding.
9. Update the matching `index.json` article:
   - `translation_status: "done"`
   - `translation_path: "translations/NN.json"`
   - `cn_title`
   - `summary`
10. Remove completed articles from `requests.json`; keep only unfinished items.
11. Normalize and verify currency before final validation:
   - `python scripts/normalize_currency_files.py {date}`
12. Run:
   - `python scripts/translate_pipeline.py {date} {id} --post`
   - `python scripts/pre_push_check.py {date}`
13. Commit only the queue/translation files touched by this task.
14. Push `main` with `python scripts/git_push.py`.
15. Sync completed articles into the configured Google Doc, newest first.

## Translation Hard Rules

- Be faithful to the original. Do not add motives, certainty, timing, causes,
  evaluations, or background that the source did not state.
- Translate every real body paragraph. Do not merge article paragraphs unless
  the source paragraph itself requires sentence-level restructuring inside the
  same paragraph.
- Delete IGN navigation, ads, author bios, social handles, image credits,
  recommendation cards, and updated-time boilerplate.
- Use Chinese corner quotes `「」` for quoted speech and emphasis. Do not leave
  ASCII double quotes or Chinese curly double quotes in Chinese text.
- Use `《》` for games, films, TV shows, books, and other works.
- Do not insert spaces between Chinese and English/alphanumeric terms:
  `XBOX宣布`, `PS5版本`, `IGN报道`.
- Write Xbox as `XBOX` in user-facing Chinese output.
- Use `PS5`, `Switch 2`, and `PC` where the context is clear.
- Write `Xbox Series X|S` and `Xbox Series X/S` as `XBOX Series` in all
  user-facing translations.
- Unknown people normally keep their Latin names unless `data/dict.json`
  provides a Chinese form or there is a stable widely recognized Chinese name.
- Company names with stable Chinese names may be translated; uncertain studio
  names stay in English.
- Dates and amounts must be accurate. Foreign currency amounts need CNY
  conversion on first body mention. Use freshly fetched multi-source exchange
  rates when possible; otherwise use `exchange_rates.json` only if it is
  verified and not stale. Do not use remembered rates or rough 7:1 estimates.
- For uncertainty, keep uncertainty: `may`, `might`, `reportedly`, `seems`,
  `could`, `expected`, and similar wording must not become confirmed fact.

## Dictionary Rules

`data/dict.json` is the only canonical dictionary.

- Load it before translating titles, summaries, or full text.
- If a term matches the dictionary, use the dictionary value.
- Do not silently add guessed terms to `data/dict.json`.
- New uncertain terms go into the translation file's `pending_dict`.
- User-confirmed corrections use `source: "user"` and have highest priority.
- Dictionary candidates learned from Google Docs polish go into learning
  evidence first; they are not auto-promoted into `data/dict.json`.

## Required Translation JSON Fields

Every `translations/NN.json` must include:

- `id`
- `en_title`
- `cn_title`
- `subtitle`
- `url`
- `category`
- `emoji`
- `publish_time_cn`
- `translated_at`
- `cover`
- `images`
- `opus_summary`
- `paragraphs`
- `translated_terms`
- `pending_dict` when needed

`subtitle` is a short second headline, not `cn_subtitle` and not
`paragraphs[0]`.

When Codex handles fulltext translation, `cn_title`, `subtitle`, and `summary`
must be newly written by Codex. Existing title/summary fields from title-only
automation are not authoritative enough for final publication.

## Google Docs Output

After completed Codex translations are pushed, sync the final translated text to
the Google Doc configured in `data/google-polish-config.json`.

Important distinction:

- Google Docs **sync** means writing newly completed translations into the
  monthly Google Doc tab for the user's editorial workflow.
- Google Docs **import** means reading the user's polished final copy back into
  `data/{date}/polished/` for nightly learning.

Current document requirements:

- Document title: `每日新闻（IGN）七月`
- Tabs: `2026年7月`, `2026年6月`, `2026年5月`
- Sort order: newest to oldest.
- One article per page, separated with page breaks.
- Title line: `YY/MM/DD 标题`, Heading 1, Microsoft YaHei, 18 pt, bold, dark gray.
- Subtitle line: Heading 2, Microsoft YaHei, 15 pt, italic, gray.
- Body: Normal text, Microsoft YaHei, 11 pt, justified, 1.15 line spacing, with
  paragraph spacing matching the user's manually formatted July sample.

Do not overwrite the user's manual edits unless the task explicitly says to
resync or replace a month.

## Validation

Before pushing translation work:

```bash
python scripts/pre_push_check.py YYYY-MM-DD
```

Do not treat `No index.json`, `No translations dir`, dictionary mismatches, or
currency failures as pass conditions.
