const CACHE_NAME = 'ign-daily-v2';
const STATIC_ASSETS = [
  '/ign-daily/',
  '/ign-daily/index.html',
  '/ign-daily/article.html',
  '/ign-daily/calendar.html',
  '/ign-daily/assets/style.css',
  '/ign-daily/assets/app.js',
];

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

// Fetch: network-first for JSON data, cache-first for static assets
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

  // Static assets: cache-first
  if (STATIC_ASSETS.some((a) => url.pathname.endsWith(a.replace('/ign-daily', '')))) {
    e.respondWith(
      caches.match(e.request).then((cached) => {
        const networkFetch = fetch(e.request).then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(e.request, clone));
          return res;
        });
        return cached || networkFetch;
      })
    );
    return;
  }

  // Everything else: network with fallback
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
