#!/usr/bin/env python3
"""
security — HTTP security layer for cpshop_http (ircodmshop.com).

Middlewares, added so they wrap everything (added LAST = runs FIRST):

  SecurityHeadersMiddleware
      CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
      Permissions-Policy, COOP/CORP. CSP allows only what the site loads:
      self + Google Fonts + Wikimedia images.

  HostAllowlistMiddleware
      Rejects requests whose Host header is not the store's own domain. This
      blocks DNS-rebinding and stray vhost hits that would otherwise reach the
      API with a foreign Host.

  RateLimitMiddleware
      Per-IP sliding window (default 60 req / 60 s) over /api/* and /mcp.
      Honours X-Forwarded-For only when TRUST_PROXY is on, so a reverse proxy
      (nginx/Cloudflare) in front of the app does not collapse every visitor
      into one bucket. Static assets are exempt.

  BodyLimitMiddleware
      Rejects bodies over 64 KB by consuming and counting the stream, so it
      holds regardless of a lying Content-Length.
"""

from __future__ import annotations

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# ------------------------------------------------------------------------ CSP
# Everything the site loads: Google Fonts (css + woff2), Wikimedia logos (img),
# t.me links. The storefront is one inline <script>, so 'unsafe-inline' is
# required for script-src; documented honestly rather than silently weakened.
_CSP_PARTS = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https://*.wikimedia.org https://upload.wikimedia.org",
    "connect-src 'self' https://t.me",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "upgrade-insecure-requests",
]
_CSP = "; ".join(_CSP_PARTS)

# Behind a reverse proxy (nginx / Cloudflare / Caddy) set CPSHOP_TRUST_PROXY=1
# so the real client IP is read from X-Forwarded-For. NEVER enable it when the
# app is directly internet-facing — a client could then spoof its own IP and
# bypass rate limiting.
TRUST_PROXY = os.environ.get("CPSHOP_TRUST_PROXY", "").strip() in ("1", "true", "yes")

_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get(
        "CPSHOP_HOSTS",
        "ircodmshop.com,www.ircodmshop.com,127.0.0.1,localhost",
    ).split(",")
    if h.strip()
}
# When the app is bound to all interfaces and no host list is configured we
# still allow raw IP access for health checks; the domain list is the real gate.
_ALLOW_ANY_HOST = os.environ.get("CPSHOP_ALLOW_ANY_HOST", "").strip() in ("1", "true", "yes")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        h["Content-Security-Policy"] = _CSP
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        h["Cross-Origin-Resource-Policy"] = "same-origin"
        # HSTS only makes sense over HTTPS; harmless over plain HTTP for local dev
        # because browsers ignore it there.
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return resp


class HostAllowlistMiddleware(BaseHTTPMiddleware):
    """Reject requests with a Host header outside the store's domains."""

    async def dispatch(self, request, call_next):
        if _ALLOW_ANY_HOST:
            return await call_next(request)
        host = (request.headers.get("host") or "").split(":")[0].strip().lower()
        if host and host not in _ALLOWED_HOSTS:
            return JSONResponse({"error": "forbidden host"}, status_code=421)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding window over /api/* and /mcp; static assets exempt."""

    def __init__(self, app, limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, dict[int, int]] = {}
        self._cleaned_at = 0.0

    @staticmethod
    def _client_ip(request) -> str:
        if TRUST_PROXY:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                # left-most entry is the original client
                return fwd.split(",")[0].strip() or "unknown"
            real = request.headers.get("x-real-ip", "").strip()
            if real:
                return real
        return request.client.host if request.client else "unknown"

    def _register(self, ip: str, now: int) -> int:
        buckets = self._hits.setdefault(ip, {})
        buckets[now] = buckets.get(now, 0) + 1
        if now - self._cleaned_at > self.window:
            horizon = now - self.window
            for ip_key in list(self._hits):
                b = self._hits[ip_key]
                for t in [t for t in b if t <= horizon]:
                    b.pop(t, None)
                if not b:
                    self._hits.pop(ip_key, None)
            self._cleaned_at = now
        return sum(v for t, v in buckets.items() if t > now - self.window)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not (path.startswith("/api/") or path == "/mcp" or path.startswith("/mcp/")):
            return await call_next(request)
        ip = self._client_ip(request)
        total = self._register(ip, int(time.time()))
        if total > self.limit:
            return JSONResponse(
                {"error": "تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید."},
                status_code=429, headers={"Retry-After": str(self.window)})
        return await call_next(request)


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Cap request bodies (default 64 KB) on POST/PUT/PATCH."""

    def __init__(self, app, max_bytes: int = 64 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_bytes:
                return JSONResponse({"error": "حجم درخواست بیش از حد مجاز است."},
                                    status_code=413)
            received = 0
            chunks = []
            async for chunk in request.stream():
                received += len(chunk)
                if received > self.max_bytes:
                    return JSONResponse(
                        {"error": "حجم درخواست بیش از حد مجاز است."},
                        status_code=413,
                    )
                chunks.append(chunk)
            if chunks:
                request._body = b"".join(chunks)
        return await call_next(request)
