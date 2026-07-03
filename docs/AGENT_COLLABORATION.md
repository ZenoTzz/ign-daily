# Agent Collaboration Protocol

Last updated: 2026-07-02

Multiple agents may work in this repository. Treat new local or remote changes
as expected, not surprising.

## Attribution

Every agent should identify its own work in commits and in
`data/agent-worklog.jsonl`.

Use this JSONL shape:

```json
{"timestamp":"2026-07-02T09:26:11+08:00","agent":"codex-gpt5","task":"updated handoff docs","files":["docs/TRANSLATION_REQUIREMENTS.md"],"notes":"short note"}
```

Recommended agent names:

- `codex-gpt5` for this Codex agent.
- `external-agent` for another agent when its exact name is unknown.
- A more specific name if the other agent identifies itself.

## Before Editing

1. Run `git status --short --branch`.
2. Read the files you plan to edit.
3. If a file already has unrelated edits, preserve them and add only scoped
   changes.
4. Fetch `origin/main` before processing translation queues.

## During Editing

- Do not revert work you did not make.
- Do not delete historical `data/{date}/` folders.
- Do not mix unrelated changes into a translation commit.
- Keep generated Google Docs/nightly-learning changes separate from translation
  queue commits when possible.
- If another agent has changed queue files, match requests by URL and work with
  the newest `index.json`.

## Before Commit Or Push

For translation work:

```bash
python scripts/pre_push_check.py YYYY-MM-DD
```

For broader repository changes:

```bash
python scripts/agent_doctor.py
```

Then append a worklog entry to `data/agent-worklog.jsonl` describing the files
you intentionally changed.

## Reviewing Other Agent Work

Codex is responsible for review and validation when asked.

Review priorities:

1. Queue integrity: no lost `requests.json` items, no ID-only mismatches.
2. Translation correctness: dictionary terms, quotes, dates, currency, paragraph
   coverage.
3. Data shape: required fields, zero-padded filenames, `index.json` status.
4. Google Docs sync/import: correct tab, date order, page breaks, title/subtitle
   styles, no accidental overwrite of user edits.
5. Git hygiene: unrelated dirty files not included in task commits.
