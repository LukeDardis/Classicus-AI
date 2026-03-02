const CACHE_NAME = 'academia-classica-v3';
const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json'
];

// URLs whose requests should go network-first (APIs and external resources)
const NETWORK_FIRST_PATTERNS = [
  '/api/',
  'perseus.tufts.edu',
  'universalis.com',
  'en.wiktionary.org',
  'allorigins.win'
];

function isNetworkFirst(url) {
  return NETWORK_FIRST_PATTERNS.some(p => url.includes(p));
}

// Install: cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: remove old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: cache-first for static, network-first for APIs
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = event.request.url;

  if (isNetworkFirst(url)) {
    // Network-first: try network, fall back to cache
    event.respondWith(
      fetch(event.request)
        .then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  } else {
    // Cache-first: serve from cache, update in background
    event.respondWith(
      caches.match(event.request).then(cached => {
        const networkFetch = fetch(event.request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
        return cached || networkFetch;
      })
    );
  }
});
