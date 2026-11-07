#!/usr/bin/env python3
"""
security — HTTP security layer for cpshop_http.

Three middlewares, added so they wrap everything (added LAST = runs FIRST):

  SecurityHeadersMiddleware
      CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy,
      Permissions-Policy. CSP allows only what the site actually loads:
      self + Google Fonts + Wikimedia images.

  RateLimitMiddleware
      Per-IP sliding window (default 60 requests / 60 s), bucketed per second,
      with periodic old-bucket cleanup. Exempts /health and static pages
      (browser asset loading would trip it); applies to /api/* and /mcp.
      Returns 429 with Retry-After.

  BodyLimitMiddleware
      Rejects JSON POSTs over 64 KB before the app sees them. /api/order
      payloads are ~1 KB; /mcp chat calls are smaller.
"""

from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# ----------------------------------------------------------------------- CSP
# Everything the site loads: Google Fonts (css+woff2), Wikimedia logos (img),
# t.me links (connect for the chat links). Scripts stay inline for now —
# index.html's whole app is one inline <script> — so 'unsafe-inline' is
# required; documented honestly instead of silently weakened.
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
]
_CSP = "; ".join(_CSP_PARTS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        h = resp.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "strict-origin-when-cross-origin"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Content-Security-Policy"] = _CSP
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return resp


# ---------------------------------------------------------------- rate limit
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding window over /api/* and /mcp; static pages exempt."""

    def __init__(self, app, limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, dict[int, int]] = {}
        self._cleaned_at = 0.0

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
        ip = request.client.host if request.client else "unknown"
        total = self._register(ip, int(time.time()))
        if total > self.limit:
            return JSONResponse(
                {"error": "تعداد درخواست‌ها بیش از حد مجاز است. کمی بعد دوباره تلاش کنید."},
                status_code=429, headers={"Retry-After": str(self.window)})
        return await call_next(request)


# --------------------------------------------------------------- body limit
class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Cap request bodies (default 64 KB) on POST/PUT/PATCH.

    Enforced by actually consuming the stream and counting bytes, so it holds
    regardless of how the client declares length (Content-Length, chunked, or
    a lying header). Over-limit uploads are cut off and answered 413.
    """

    def __init__(self, app, max_bytes: int = 64 * 1024):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            received = 0
            chunks = []
            async for chunk in request.stream():
                received += len(chunk)
                if received > self.max_bytes:
                    return JSONResponse({"error": "حجم درخواست بیش از حد مجاز است."},
                                        status_code=413)
                chunks.append(chunk)
            if chunks:
                request._body = b"".join(chunks)
        return await call_next(request)
