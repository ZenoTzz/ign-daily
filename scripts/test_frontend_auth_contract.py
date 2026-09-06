from __future__ import annotations

import unittest
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendAuthContractTest(unittest.TestCase):
    def test_browser_actions_do_not_require_legacy_readable_token(self) -> None:
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")

        self.assertNotIn(
            "ServerAPI.token()",
            app_js,
            "Browser authentication uses an HttpOnly cookie; checking the old readable token blocks valid sessions.",
        )

    def test_translation_submit_has_double_click_guard_and_busy_state(self) -> None:
        app_js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
        index_html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn("this.selected.length === 0 || this.translationSubmitting", app_js)
        self.assertIn("finally {\n        this.translationSubmitting = false;", app_js)
        self.assertIn("正在提交…", index_html)
        self.assertIn(":disabled=\"selected.length === 0 || translationSubmitting\"", index_html)

    def test_service_worker_never_intercepts_private_api_or_caches_private_json(self) -> None:
        node = os.environ.get("NODE_BINARY") or shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for service worker behavior tests (set NODE_BINARY)")
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const handlers = {};
const cached = [], deleted = [];
const self = {
  location: {pathname: '/sw.js', origin: 'https://igndaily.site'},
  addEventListener: (name, fn) => handlers[name] = fn,
  skipWaiting() {}, clients: {claim() {}},
};
const response = {ok: true, clone() {return this;}};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  self, URL, Response,
  fetch: async () => response,
  caches: {
    open: async () => ({put: async request => cached.push(request), addAll: async () => {}}),
    match: async () => undefined,
    keys: async () => ['ign-daily-v12', 'ign-daily-v13', 'ign-daily-v14'],
    delete: async key => deleted.push(key),
  },
});
async function request(path, mode = 'cors') {
  let intercepted = false, promise;
  cached.length = 0;
  handlers.fetch({request: {method: 'GET', mode, url: new URL(path, self.location.origin).href},
    respondWith(value) {intercepted = true; promise = value;}});
  if (promise) await promise;
  return intercepted;
}
(async () => {
  for (const path of ['/api', '/api/me', '/api/files/data/automation-config.json', '/api/files/data/dict.json']) {
    for (const mode of ['cors', 'navigate']) {
      assert.equal(await request(path, mode), false, path);
      assert.equal(cached.length, 0);
    }
  }
  assert.equal(await request('https://external.test/data/index.json'), false);
  for (const path of ['/data/dict.json', '/data/index-list.json', '/data/2026-09-06/index.json', '/data/2026-09-06/translations/01.json']) {
    assert.equal(await request(path), true);
    assert.ok(cached.length > 0, path);
  }
  for (const path of ['/data/automation-config.json', '/data/usage/deepseek-balance.json', '/other/data/dict.json', '/data/dict_candidates.json']) {
    await request(path);
    assert.equal(cached.length, 0, path);
  }
  let activated;
  handlers.activate({waitUntil(promise) {activated = promise;}});
  await activated;
  assert.deepEqual(deleted, ['ign-daily-v12', 'ign-daily-v13']);
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
        result = subprocess.run([node, "-e", script, str(ROOT / "sw.js")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
