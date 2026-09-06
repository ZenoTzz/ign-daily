# Web reliability checks

The web workbench and native client share URL identity and revision-protected
editing APIs. See `server_api/API.md` for the contract and
`server_api/DEPLOYMENT.md` for worker locks, release rollback and data restore.

## Automated verification

From the repository root:

```sh
PYTHONPATH=scripts python3 -m unittest discover -s scripts -p 'test_*.py'
PYTHONPATH=scripts IGN_DAILY_WRITE_LOCK=/tmp/ign-daily-api-test.lock python3 -m unittest discover -s server_api -p 'test_*.py'
node --test tests/*.test.cjs
# Requires the FastAPI/uvicorn packages from server_api/requirements.txt:
python3 tests/api-http-integration.py
```

`NODE_BINARY` can point Python's service-worker check to an installed Node binary.
The repository exchange-rate snapshot can lag behind production; only for offline
code checks use `ALLOW_STALE_EXCHANGE_RATES=1 python3 scripts/agent_doctor.py`.
Production must keep its current rates and runtime data.

## Browser regression

Install Playwright in a development environment and its Chromium browser, then:

```sh
node tests/web-browser.cjs
node tests/article-browser.cjs
```

If Playwright or the browser is installed elsewhere, set `PLAYWRIGHT_MODULE` to
its module path and/or `BROWSER_EXECUTABLE` to its browser executable. Both suites
intercept API and external requests, use test fixtures, and never submit real
translation jobs or edit production content.

Checks cover selection across ID reorder, cookie login on the same page,
dictionary single-entry updates, historical string-schema compatibility,
nonzero usage, authentication/loading failures, and desktop/mobile layout.
Article checks cover slow save with continued input, conflict preservation,
reset failure/success, and paired English/Chinese paragraphs. Worker tests use
separate processes to verify the data lock is available during model work,
concurrent article/request preservation, missing-source rejection, and complete
release/restore rollback including permissions and unrelated API services.

## Deliberate limits

Private usage remains authenticated. Failed reads never represent zero spending.
Legacy title-only archive previews link to their news day until an index rebuild
supplies article IDs. No historical translations are rewritten by a code deploy.
Existing historical quality failures are exposed by the common quality gate;
they are not silently approved or retried. Offsite backup credentials and a
provider-specific disaster recovery destination remain deployment concerns.
