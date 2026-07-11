const CACHE_NAME = 'ign-daily-v12';
const BASE_PATH = self.location.pathname.replace(/sw\.js$/, '');
const STATIC_ASSETS = [
  '',
  'index.html',
  'article.html',
  'calendar.html',
  'assets/style.css',
  'assets/home.css',
  'assets/workspace-ui.css',
  'assets/app.js',
].map((path) => `${BASE_PATH}${path}`);

const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8' };
const HTML_HEADERS = { 'Content-Type': 'text/html; charset=utf-8' };

function jsonFallback(message) {
  return new Response(JSON.stringify({ ok: false, error: message }), {
    status: 503,
    headers: JSON_HEADERS,
  });
}

function htmlFallback(message) {
  return new Response(`<!doctype html><meta charset="utf-8"><title>IGN Daily</title><body>${message}</body>`, {
    status: 503,
    headers: HTML_HEADERS,
  });
}

async function cacheFresh(request, response) {
  if (response && response.ok) {
    const cache = await caches.open(CACHE_NAME);
    const canonicalUrl = new URL(request.url);
    canonicalUrl.search = '';
    await Promise.all([
      cache.put(request, response.clone()),
      cache.put(canonicalUrl.toString(), response.clone()),
    ]);
  }
  return response;
}

async function matchCached(request) {
  const exact = await caches.match(request);
  if (exact) return exact;
  const canonicalUrl = new URL(request.url);
  canonicalUrl.search = '';
  return caches.match(canonicalUrl.toString());
}

// Install: cache static shell
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-first for JSON data and static shell, but never return null.
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET') return;

  const url = new URL(e.request.url);

  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request)
        .then((res) => cacheFresh(e.request, res))
        .catch(async () =>
          (await matchCached(e.request)) ||
          (await caches.match(`${BASE_PATH}index.html`)) ||
          (await caches.match(`${BASE_PATH}`)) ||
          htmlFallback('IGN Daily 暂时无法连接，请稍后刷新。')
        )
    );
    return;
  }

  // JSON data files: always try network first (fresh data)
  if (url.pathname.endsWith('.json') && url.pathname.includes('/data/')) {
    e.respondWith(
      fetch(e.request)
        .then((res) => cacheFresh(e.request, res))
        .catch(async () => (await matchCached(e.request)) || jsonFallback('数据暂时无法连接，请稍后刷新。'))
    );
    return;
  }

  // Static assets: prefer fresh network copy, then fall back to cache.
  if (STATIC_ASSETS.some((asset) => url.pathname === new URL(asset, self.location.origin).pathname)) {
    e.respondWith(
      fetch(e.request)
        .then((res) => cacheFresh(e.request, res))
        .catch(async () =>
          (await matchCached(e.request)) ||
          (url.pathname.endsWith('.html') ? htmlFallback('页面暂时无法连接，请稍后刷新。') : new Response('', { status: 503 }))
        )
    );
    return;
  }

  // Everything else: network with fallback
  e.respondWith(
    fetch(e.request).catch(async () => (await matchCached(e.request)) || new Response('', { status: 503 }))
  );
});
