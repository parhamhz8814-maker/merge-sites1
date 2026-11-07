#!/usr/bin/env python3
"""
cpshop_http — serves the CP.Shop static site AND the catalog MCP server
over one HTTP origin.

  GET  /              → gametop static files (index.html, logos.html, ...)
  POST /mcp           → MCP streamable-HTTP transport (stateless JSON mode)
  GET  /health        → liveness probe
  POST /api/order     → create order (server-priced from SQLite, returns tracking)
  POST /api/order/pay → mark order paid (demo payment-gateway callback)
  GET  /api/order/{tracking} → order status + items
  GET  /api/db-stats  → database summary (products / orders / paid revenue)

Security layer (security.py): CSP + security headers, per-IP rate limiting on
/api & /mcp, request body cap. Orders priced ONLY from the SQLite products
table — client-sent prices are ignored (store_db.py). /api/order returns a
per-order pay_token that /api/order/pay requires, so the publicly visible
tracking code alone can never mark an order paid.

Run:
  mcp-server/.venv/Scripts/python mcp-server/cpshop_http.py [port]

The MCP tools live in cpshop_mcp.py; this file only wires transport + static.
"""

import sys
from pathlib import Path

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

HERE = Path(__file__).resolve().parent
SITE_ROOT = HERE.parent          # gametop/ — index.html, logos.html, assets

# Import the FastMCP app (tools defined there; do not run its __main__).
from cpshop_mcp import mcp  # noqa: E402
import store_db  # noqa: E402
from store_db import OrderError, create_order, db_stats, get_order, pay_order  # noqa: E402
from security import (  # noqa: E402
    BodyLimitMiddleware, RateLimitMiddleware, SecurityHeadersMiddleware)

# Stateless streamable-HTTP app (no session tracking; every POST is standalone).
mcp_app = mcp.streamable_http_app()


async def health(request: Request):
    return JSONResponse({"ok": True, "server": "cpshop_http"})


async def static_file(request: Request):
    rel = request.path_params.get("rest", "index.html").strip("/")
    if not rel:
        rel = "index.html"
    # Static surface is the store frontend ONLY: block server code, database,
    # dotfiles, and any path escaping the site root.
    first = rel.split("/")[0]
    if first in ("mcp-server", ".freebuff") or first.startswith("."):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    target = (SITE_ROOT / rel).resolve()
    # path traversal guard
    if not str(target).startswith(str(SITE_ROOT.resolve())):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    if target.is_dir():
        target = target / "index.html"
    if not target.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(target)


async def _json_body(request: Request) -> dict | None:
    """Parsed JSON object from the request, or None if absent/not an object."""
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


async def api_order_create(request: Request):
    """Create a pending order. Body: {items: [{product_id, quantity, player_id}]}.
    Pricing comes from the DB only; unknown ids, bad quantities, or a game pack
    without a ≥4-char player_id → 400. Response carries the one-order pay_token
    that /api/order/pay demands."""
    body = await _json_body(request)
    items = body.get("items") if body else None
    try:
        order = create_order(items)
    except OrderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "خطای داخلی سرور."}, status_code=500)
    return JSONResponse(order, status_code=201)


async def api_order_pay(request: Request):
    """Mark an order paid: {tracking, pay_token}. Gated: the token is issued at
    order creation and is the only key besides it — 403 on mismatch."""
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


async def api_order_get(request: Request):
    try:
        order = get_order(request.path_params["tracking"])
    except OrderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if order is None:
        return JSONResponse({"error": "سفارش یافت نشد."}, status_code=404)
    return JSONResponse(order)


async def api_db_stats(request: Request):
    return JSONResponse(db_stats())


@contextlib.asynccontextmanager
async def lifespan(app):
    store_db.init_db()                      # create schema + seed products
    async with mcp.session_manager.run():   # MCP session manager (FastMCP contract)
        yield


def build_app():
    # Route order: specific GET routes first, then static files (GET),
    # then the MCP app mounted at root — FastMCP's streamable transport
    # serves POST /mcp itself, so mounting it at /mcp would double the path.
    # Lifespan: same contract FastMCP uses — start/stop its session manager.
    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/api/order/pay", api_order_pay, methods=["POST"]),
            Route("/api/order", api_order_create, methods=["POST"]),
            Route("/api/order/{tracking}", api_order_get, methods=["GET"]),
            Route("/api/db-stats", api_db_stats, methods=["GET"]),
            Route("/{rest:path}", static_file, methods=["GET"]),
            Mount("/", mcp_app),
        ],
        lifespan=lifespan,
    )
    # CORS: the API is same-origin only — no cross-origin site may call it.
    # (MCP stays same-origin too; the site's chat client is same-origin.)
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8765"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
                       expose_headers=["Mcp-Session-Id"])
    # Middleware wrap order (last added runs first):
    #   body limit → rate limit → security headers → CORS → app
    app.add_middleware(BodyLimitMiddleware, max_bytes=64 * 1024)
    app.add_middleware(RateLimitMiddleware, limit=60, window_seconds=60)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    # 0.0.0.0: reachable from the LAN — "security lan" deployment.
    uvicorn.run(build_app(), host="0.0.0.0", port=port, log_level="warning")
