const CACHE_NAME = 'ign-daily-v5';
const BASE_PATH = self.location.pathname.replace(/sw\.js$/, '');
const STATIC_ASSETS = [
  '',
  'index.html',
  'article.html',
  'calendar.html',
  'assets/style.css',
  'assets/app.js',
].map((path) => `${BASE_PATH}${path}`);

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

// Fetch: network-first for JSON data and static shell.
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // JSON data files: always try network first (fresh data)
  if (url.pathname.endsWith('.json') && url.pathname.includes('/data/')) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Static assets: prefer fresh network copy, then fall back to cache.
  if (STATIC_ASSETS.some((asset) => url.pathname === new URL(asset, self.location.origin).pathname)) {
    e.respondWith(
      fetch(e.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Everything else: network with fallback
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
