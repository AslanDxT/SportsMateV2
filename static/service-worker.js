/*
 * SportsMate service worker.
 *
 * Privacy rule: only public files from /static/ are cached. Pages are never
 * stored, because they can contain messages and other personal data that must
 * not stay on a shared device after logging out. Without a connection, page
 * visits show a simple offline page instead.
 */
const CACHE_NAME = "sportsmate-static-v4";
const OFFLINE_URL = "/static/offline.html";

const PRECACHE = [
    OFFLINE_URL,
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/Images/logo.svg",
    "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    // Remove every older cache, including caches of the previous version
    // that stored complete pages.
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request).catch(() => caches.match(OFFLINE_URL))
        );
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        // Stale-while-revalidate: answer from cache fast, refresh in the background.
        event.respondWith(
            caches.open(CACHE_NAME).then((cache) =>
                cache.match(request).then((cached) => {
                    const network = fetch(request)
                        .then((response) => {
                            if (response && response.ok) {
                                cache.put(request, response.clone());
                            }
                            return response;
                        })
                        .catch(() => cached);
                    return cached || network;
                })
            )
        );
    }
});
