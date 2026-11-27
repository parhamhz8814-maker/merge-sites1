#!/usr/bin/env python3
"""
cpshop_http — serves the CP.Shop storefront AND the catalog MCP server over
one HTTP origin (ircodmshop.com).

  GET  /                      → static storefront (dist/)
  POST /mcp                   → MCP streamable-HTTP transport
  GET  /health                → liveness probe
  POST /api/order             → create order (server-priced, returns tracking)
  POST /api/order/pay         → mark order paid (token-gated)
  POST /api/order/cancel      → cancel a pending order (token-gated)
  GET  /api/order/{tracking}  → order status (contact masked without token)
  GET  /api/stats             → public catalog size only

Security (security.py + this file):
  - CSP / HSTS / nosniff / frame-deny headers on every response
  - per-IP rate limiting that honours X-Forwarded-For behind a trusted proxy
  - request body cap
  - Host allow-list so the server cannot be reached via an unexpected domain
  - orders priced ONLY from SQLite; the client can never set an amount
  - per-order pay_token required for pay/cancel/full order details

Run:
  python cpshop_http.py [port]
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

HERE = Path(__file__).resolve().parent
# Serve the deployable build (dist/) so GET / is the real storefront on the
# same origin as /api; fall back to the parent folder for older layouts.
SITE_ROOT = (HERE.parent / "dist") if (HERE.parent / "dist" / "index.html").exists() else HERE.parent

# Import the FastMCP app (tools defined there; do not run its __main__).
from cpshop_mcp import mcp  # noqa: E402
import store_db  # noqa: E402
from store_db import (  # noqa: E402
    OrderError, cancel_order, create_order, get_order, pay_order, public_stats)
from security import (  # noqa: E402
    BodyLimitMiddleware, HostAllowlistMiddleware, RateLimitMiddleware,
    SecurityHeadersMiddleware)

# Stateless streamable-HTTP app (no session tracking; every POST is standalone).
mcp_app = mcp.streamable_http_app()

# Production origin(s). Extra origins can be added without code changes:
#   CPSHOP_ORIGINS="https://ircodmshop.com,https://www.ircodmshop.com"
_DEFAULT_ORIGINS = [
    "https://ircodmshop.com",
    "https://www.ircodmshop.com",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
]
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CPSHOP_ORIGINS", "").split(",") if o.strip()
] or _DEFAULT_ORIGINS

# Files that must never be served from the static surface even if they land in
# the site root by mistake.
_BLOCKED_EXT = {
    ".db", ".sqlite", ".sqlite3", ".py", ".pyc", ".env", ".log", ".json",
    ".bak", ".ini", ".cfg", ".conf", ".pem", ".key", ".crt", ".sh", ".ps1",
}
_BLOCKED_DIRS = {"mcp-server", "merged-backend", "cpshop", ".freebuff", ".git",
                 "__pycache__", "node_modules"}


async def health(request: Request):
    return JSONResponse({"ok": True, "server": "cpshop_http"})


async def static_file(request: Request):
    rel = request.path_params.get("rest", "index.html").strip("/")
    if not rel:
        rel = "index.html"

    parts = rel.split("/")
    if any(p.startswith(".") for p in parts):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if parts[0] in _BLOCKED_DIRS:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if Path(rel).suffix.lower() in _BLOCKED_EXT:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    root = SITE_ROOT.resolve()
    target = (root / rel).resolve()
    # Path-traversal guard: the resolved path must stay inside the site root.
    if target != root and root not in target.parents:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target)


async def _json_body(request: Request) -> dict | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def api_order_create(request: Request):
    """Create a pending order.

    Body: {items:[{product_id, quantity, player_id}],
           customer_name, customer_contact, total?}
    If `total` is supplied it must match the server-computed sum.
    """
    body = await _json_body(request)
    if body is None:
        return JSONResponse({"error": "بدنه درخواست معتبر نیست."}, status_code=400)

    try:
        order = create_order(
            body.get("items"),
            body.get("customer_name"),
            body.get("customer_contact"),
            claimed_total=body.get("total"),
        )
    except OrderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "خطای داخلی سرور."}, status_code=500)
    return JSONResponse(order, status_code=201)


async def api_order_pay(request: Request):
    """Mark an order paid: {tracking, pay_token}."""
    body = await _json_body(request)
    tracking = str(body.get("tracking", "")) if body else ""
    token = str(body.get("pay_token", "")) if body else ""
    try:
        return JSONResponse(pay_order(tracking, token))
    except OrderError as e:
        msg = str(e)
        return JSONResponse({"error": msg}, status_code=403 if "توکن" in msg else 400)
    except Exception:
        return JSONResponse({"error": "خطای داخلی سرور."}, status_code=500)


async def api_order_cancel(request: Request):
    """Cancel a pending order: {tracking, pay_token}."""
    body = await _json_body(request)
    tracking = str(body.get("tracking", "")) if body else ""
    token = str(body.get("pay_token", "")) if body else ""
    try:
        return JSONResponse(cancel_order(tracking, token))
    except OrderError as e:
        msg = str(e)
        return JSONResponse({"error": msg}, status_code=403 if "توکن" in msg else 400)
    except Exception:
        return JSONResponse({"error": "خطای داخلی سرور."}, status_code=500)


async def api_order_get(request: Request):
    """Order status. Pass ?token=... to see unmasked contact details."""
    token = request.query_params.get("token") or None
    try:
        order = get_order(request.path_params["tracking"], token)
    except OrderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if order is None:
        return JSONResponse({"error": "سفارش یافت نشد."}, status_code=404)
    return JSONResponse(order)


async def api_stats(request: Request):
    """Public: catalog size only. Revenue/order counts are admin-only."""
    return JSONResponse(public_stats())


@contextlib.asynccontextmanager
async def lifespan(app):
    store_db.init_db()                      # schema + migrations + catalog seed
    async with mcp.session_manager.run():   # FastMCP session manager contract
        yield


def build_app():
    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/api/order/pay", api_order_pay, methods=["POST"]),
            Route("/api/order/cancel", api_order_cancel, methods=["POST"]),
            Route("/api/order", api_order_create, methods=["POST"]),
            Route("/api/order/{tracking}", api_order_get, methods=["GET"]),
            Route("/api/stats", api_stats, methods=["GET"]),
            Route("/{rest:path}", static_file, methods=["GET"]),
            Mount("/", mcp_app),
        ],
        lifespan=lifespan,
    )
    # CORS: only the store's own origins may call the API from a browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Mcp-Session-Id"],
        allow_credentials=False,
    )
    # Middleware wrap order (last added runs first):
    #   body limit → rate limit → host allow-list → security headers → CORS → app
    app.add_middleware(BodyLimitMiddleware, max_bytes=64 * 1024)
    app.add_middleware(RateLimitMiddleware, limit=60, window_seconds=60)
    app.add_middleware(HostAllowlistMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    host = os.environ.get("CPSHOP_HOST", "0.0.0.0")
    uvicorn.run(build_app(), host=host, port=port, log_level="warning")
