const CACHE_NAME = "uconnect-shell-v2";
const STATIC_ASSETS = [
    "./",
    "./index.html",
    "./learn.html",
    "./admin.html",
    "./admin.js",
    "./dashboard.js",
    "./learn.css",
    "./learn.js",
    "./auth.js",
    "./manifest.json"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(
                names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (
        request.method !== "GET"
        || url.origin !== self.location.origin
        || url.pathname.startsWith("/api/")
    ) {
        return;
    }

    event.respondWith(
        caches.match(request).then((cached) => cached || fetch(request).then((response) => {
            if (response.ok && response.type === "basic") {
                const copy = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            }
            return response;
        }))
    );
});

self.addEventListener("push", (event) => {
    if (!event.data) return;
    const data = event.data.json();
    event.waitUntil(self.registration.showNotification(data.title || "U-CONNECT", {
        body: data.body || "You have a new U-CONNECT notification.",
        tag: data.tag || "uconnect-notification",
        data: data.data || {}
    }));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
            const existing = clients.find((client) => new URL(client.url).origin === self.location.origin);
            return existing ? existing.focus() : self.clients.openWindow("./");
        })
    );
});
