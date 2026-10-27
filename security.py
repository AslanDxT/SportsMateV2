"""
Security helpers: login checks, CSRF protection, rate limiting and HTTP headers.
"""

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, current_app, g, redirect, request, session, url_for

CSRF_SESSION_KEY = "_csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


# --------------------------------------------------
# Login
# --------------------------------------------------

def login_required(view):
    """Send visitors who are not logged in to the login page."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            next_url = request.full_path if request.method == "GET" else None
            if next_url and next_url.endswith("?"):
                next_url = next_url[:-1]
            return redirect(url_for("auth.login", next=next_url))
        return view(*args, **kwargs)

    return wrapped


def is_safe_next_url(target):
    """Only allow redirects to pages on this site (prevents open redirects)."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    if "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


# --------------------------------------------------
# CSRF protection
# --------------------------------------------------

def csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def verify_csrf():
    """Reject state-changing requests that do not carry this session's token."""
    if request.method in SAFE_METHODS or not current_app.config.get("CSRF_ENABLED", True):
        return

    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    expected = session.get(CSRF_SESSION_KEY, "")

    if not sent or not expected or not hmac.compare_digest(str(sent), str(expected)):
        abort(400, description="csrf")


# --------------------------------------------------
# Rate limiting (in memory, per process)
# --------------------------------------------------

class RateLimiter:
    """
    Small sliding-window limiter.

    It lives in memory, so limits reset when the app restarts and are not
    shared between several server processes. That is fine for one process;
    a bigger deployment should use a shared store such as Redis.
    """

    def __init__(self):
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, window, now):
        events = self._events[key]
        while events and events[0] <= now - window:
            events.popleft()
        return events

    def is_limited(self, key, limit, window):
        if not current_app.config.get("RATELIMIT_ENABLED", True):
            return False
        now = time.monotonic()
        with self._lock:
            return len(self._prune(key, window, now)) >= limit

    def add(self, key):
        with self._lock:
            self._events[key].append(time.monotonic())

    def hit(self, key, limit, window):
        """Record an event and return True when the limit is exceeded."""
        if not current_app.config.get("RATELIMIT_ENABLED", True):
            return False
        now = time.monotonic()
        with self._lock:
            events = self._prune(key, window, now)
            if len(events) >= limit:
                return True
            events.append(now)
            return False

    def reset(self, key):
        with self._lock:
            self._events.pop(key, None)


limiter = RateLimiter()


def client_ip():
    return request.remote_addr or "unknown"


# --------------------------------------------------
# HTTP security headers
# --------------------------------------------------

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "img-src 'self' data:",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "script-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def apply_security_headers(response):
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "same-origin")
    headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")

    if current_app.config.get("SESSION_COOKIE_SECURE"):
        headers.setdefault("Strict-Transport-Security", "max-age=31536000")

    # Pages with personal data must not be stored by the browser or a proxy,
    # so they cannot be shown again after logging out on a shared computer.
    if g.get("user") is not None and response.mimetype == "text/html":
        headers["Cache-Control"] = "no-store"

    return response
