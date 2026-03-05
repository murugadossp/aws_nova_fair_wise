/**
 * FareWise Service Worker
 * Strategy: Cache-first for app shell, Network-first for API calls
 * Live prices should NEVER be served from cache.
 */

const CACHE_NAME = 'farewise-v1';
const OFFLINE_URL = '/offline.html';

// App shell — these are cached on install
const SHELL_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  'https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500;600&display=swap'
];

// API endpoints — NEVER cache these (live prices)
const NO_CACHE_PATTERNS = [
  '/api/',
  '/ws/',
  'amazon.in',
  'flipkart.com',
  'makemytrip.com',
  'goibibo.com',
  'cleartrip.com'
];

// ── INSTALL: cache app shell ──────────────────────────────────
self.addEventListener('install', event => {
  console.log('[FareWise SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(SHELL_ASSETS.filter(url => !url.startsWith('http')));
    }).then(() => {
      console.log('[FareWise SW] Shell cached');
      return self.skipWaiting();
    })
  );
});

// ── ACTIVATE: clean old caches ────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames
          .filter(name => name !== CACHE_NAME)
          .map(name => {
            console.log('[FareWise SW] Deleting old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// ── FETCH: routing strategy ───────────────────────────────────
self.addEventListener('fetch', event => {
  const url = event.request.url;

  // Never cache API calls or price data
  const shouldNotCache = NO_CACHE_PATTERNS.some(pattern => url.includes(pattern));
  if (shouldNotCache) {
    event.respondWith(
      fetch(event.request).catch(() => {
        // Offline during a price search — return a helpful JSON error
        if (url.includes('/api/')) {
          return new Response(
            JSON.stringify({ error: 'offline', message: 'Connect to internet to search prices' }),
            { headers: { 'Content-Type': 'application/json' } }
          );
        }
      })
    );
    return;
  }

  // Cache-first for app shell assets
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;

      return fetch(event.request).then(response => {
        // Cache successful GET responses for shell assets
        if (response.ok && event.request.method === 'GET') {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, cloned));
        }
        return response;
      }).catch(() => {
        // Offline — return cached homepage if available
        if (event.request.destination === 'document') {
          return caches.match('/index.html');
        }
      });
    })
  );
});

// ── SHARE TARGET: handle WhatsApp image shares ────────────────
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  if (url.pathname === '/share' && event.request.method === 'POST') {
    event.respondWith(
      (async () => {
        const formData = await event.request.formData();
        const image = formData.get('image');
        const title = formData.get('title') || '';
        const text  = formData.get('text')  || '';

        // Store the shared image in IndexedDB for the app to pick up
        if (image) {
          const clients = await self.clients.matchAll({ type: 'window' });
          clients.forEach(client => {
            client.postMessage({ type: 'SHARED_IMAGE', title, text });
          });
        }

        // Redirect to app with products mode active
        return Response.redirect('/?mode=products&shared=true', 303);
      })()
    );
  }
});

// ── PUSH: future notification support ────────────────────────
self.addEventListener('push', event => {
  // Reserved for future: price drop alerts
  if (event.data) {
    const data = event.data.json();
    self.registration.showNotification('FareWise', {
      body: data.message,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: data.url }
    });
  }
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.notification.data?.url) {
    clients.openWindow(event.notification.data.url);
  }
});

console.log('[FareWise SW] Service worker loaded');
