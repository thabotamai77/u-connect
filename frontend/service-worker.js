// U-CONNECT Service Worker
// Handles offline caching, background sync, and app shell strategy

const CACHE_NAME = 'uconnect-v1';
const STATIC_ASSETS = [
    './',
    './index.html',
    './style.css',
    './app.js',
    './manifest.json'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('Service Worker: Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('Service Worker: Caching static assets');
            return cache.addAll(STATIC_ASSETS).catch((error) => {
                console.warn('Service Worker: Some assets failed to cache', error);
                // Continue even if some assets fail
                return Promise.resolve();
            });
        })
    );
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('Service Worker: Activating...');
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cacheName) => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Service Worker: Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch event - Network First, then Cache strategy
self.addEventListener('fetch', (event) => {
    const { request } = event;

    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }

    // Handle API requests (Network first, fallback to cache)
    if (request.url.includes('/api/') || request.url.includes('localhost:')) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    // Cache successful API responses
                    if (response.ok) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(request, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    // Fallback to cache if network fails
                    return caches.match(request).then((cachedResponse) => {
                        if (cachedResponse) {
                            console.log('Service Worker: Serving from cache (offline)', request.url);
                            return cachedResponse;
                        }
                        // Return offline page or placeholder
                        return new Response('Offline - content not available', {
                            status: 503,
                            statusText: 'Service Unavailable',
                            headers: new Headers({
                                'Content-Type': 'text/plain'
                            })
                        });
                    });
                })
        );
        return;
    }

    // Handle static assets (Cache first, then Network)
    event.respondWith(
        caches.match(request).then((cachedResponse) => {
            if (cachedResponse) {
                return cachedResponse;
            }
            return fetch(request)
                .then((response) => {
                    // Cache successful responses
                    if (!response || response.status !== 200) {
                        return response;
                    }
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(request, responseClone);
                    });
                    return response;
                })
                .catch(() => {
                    console.log('Service Worker: Fetch failed for', request.url);
                    return new Response('Offline', {
                        status: 503,
                        statusText: 'Service Unavailable'
                    });
                });
        })
    );
});

// Background Sync - sync data when connection is restored
self.addEventListener('sync', (event) => {
    console.log('Service Worker: Background sync event', event.tag);
    if (event.tag === 'sync-progress') {
        event.waitUntil(syncProgress());
    }
});

// Sync helper function
async function syncProgress() {
    try {
        // Get pending progress updates from IndexedDB or localStorage
        const pendingUpdates = JSON.parse(
            localStorage.getItem('pendingProgressUpdates') || '[]'
        );

        if (pendingUpdates.length === 0) {
            return;
        }

        // Send all pending updates to the server
        for (const update of pendingUpdates) {
            await fetch('/api/progress', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(update)
            });
        }

        // Clear pending updates after successful sync
        localStorage.removeItem('pendingProgressUpdates');
        console.log('Service Worker: Synced all pending updates');
    } catch (error) {
        console.error('Service Worker: Sync failed', error);
        // Retry later
        throw error;
    }
}

// Push notification handler (for future push features)
self.addEventListener('push', (event) => {
    console.log('Service Worker: Push notification received', event);
    if (event.data) {
        const data = event.data.json();
        const options = {
            body: data.body || 'U-CONNECT notification',
            icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192"><rect fill="%2325b9f3" width="192" height="192" rx="45"/><text x="96" y="96" font-size="120" fill="%23071014" text-anchor="middle" dominant-baseline="central" font-family="sans-serif" font-weight="bold">U</text></svg>',
            badge: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><circle fill="%2325b9f3" cx="48" cy="48" r="48"/></svg>',
            tag: data.tag || 'uconnect-notification',
            requireInteraction: data.requireInteraction || false,
            data: data.data || {}
        };

        event.waitUntil(
            self.registration.showNotification(data.title || 'U-CONNECT', options)
        );
    }
});

// Notification click handler
self.addEventListener('notificationclick', (event) => {
    console.log('Service Worker: Notification clicked', event.notification.tag);
    event.notification.close();

    // Open the app when notification is clicked
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            // Look for an already-open window
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if (client.url === '/' && 'focus' in client) {
                    return client.focus();
                }
            }
            // If not open, open a new window
            if (clients.openWindow) {
                return clients.openWindow('./');
            }
        })
    );
});

// Message handler - for communication with the app
self.addEventListener('message', (event) => {
    console.log('Service Worker: Message received', event.data);
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

console.log('Service Worker: Loaded successfully');
