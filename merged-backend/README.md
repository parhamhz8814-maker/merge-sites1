# merged-backend (CP.Shop + MCP)

This folder contains the backend for the merged CP.Shop store:
- MCP tools (stdio JSON-RPC) for catalog/search/cart estimation
- HTTP server (Starlette) that serves the site static assets and provides:
  - POST `/api/order` to create a pending order (priced from SQLite)
  - POST `/api/order/pay` to mark an order as paid (token-gated)
  - GET `/api/order/{tracking}` to read order status

## Files
- `cpshop_mcp.py` — MCP server exposing catalog tools
- `cpshop_http.py` — HTTP app wiring MCP + order endpoints + static serving
- `store_db.py` — SQLite persistence + `create_order()` / `pay_order()`
- `security.py` — rate limiting + security headers
- `catalog.json` — product catalog seed data
- `shopping_cart.py` — helper ShoppingCart used to build order items

## Requirements
Python packages needed by the backend:
- pydantic
- mcp
- starlette
- uvicorn

## Setup
From this directory:

1) Install dependencies (if missing):
   - `python -m pip install pydantic mcp starlette uvicorn`

2) (Optional) First run will create `cpshop.db` automatically when you call
   `store_db.init_db()`.

## Run HTTP server

`python cpshop_http.py 8765`

Then use:
- `GET  http://localhost:8765/health`
- `POST http://localhost:8765/api/order`
  Body: `{ "items": [{"product_id":"codm-80","quantity":2,"player_id":"12345678"}] }`
- `POST http://localhost:8765/api/order/pay`
  Body: `{ "tracking":"CPS-...", "pay_token":"..." }`

Static files are served from the sibling `gametop/` directory (the repository frontend assets).

## Database schema (SQLite)

Tables:
- products
  - id (TEXT PRIMARY KEY)
  - game_key (TEXT)
  - game (TEXT)
  - title (TEXT)
  - category (TEXT)
  - price (INTEGER)
  - old_price (INTEGER)
  - badge (TEXT)
- customers
  - id (INTEGER PRIMARY KEY AUTOINCREMENT)
  - name (TEXT)
  - phone (TEXT)
  - email (TEXT)
  - game_player_id (TEXT)
  - created_at (TEXT)
- orders
  - id (INTEGER PRIMARY KEY AUTOINCREMENT)
  - tracking (TEXT UNIQUE NOT NULL)
  - status (pending/paid/canceled)
  - customer_id (FK → customers.id, ON DELETE SET NULL)
  - total (INTEGER)
  - item_count (INTEGER)
  - created_at (TEXT)
  - paid_at (TEXT)
  - pay_token (TEXT)
- order_items
  - id (INTEGER PRIMARY KEY AUTOINCREMENT)
  - order_id (FK → orders.id, ON DELETE CASCADE)
  - product_id (TEXT)
  - title (TEXT)
  - game (TEXT)
  - quantity (INTEGER)
  - unit_price (INTEGER)
  - player_id (TEXT)

Indexes:
- idx_orders_tracking, idx_orders_status, idx_orders_customer_id, idx_orders_created_at
- idx_order_items_order, idx_order_items_product, idx_order_items_player

Backup endpoint:
- CLI export: `python db_tool.py export`
  - writes `db_backup_orders.json` with orders + items.

## Tests / verification

1) Import + SQLite order-flow smoke test:
   - `python check_imports.py`

2) ShoppingCart + create_order + pay_order test:
   - `python test_shopping_cart.py`

3) MCP lifecycle test (stdio JSON-RPC):
   - `python test_server.py`

4) Production DB flow test (fresh reset + seed + order lifecycle):
   - `python test_db_production_flow.py`

All should exit with code 0.

## API endpoints
- POST `/api/order`
  - Body: {"items":[{"product_id","quantity","player_id"}, ...], "customer_name":..., "customer_contact":...} (player_id per item)
- POST `/api/order/pay`
  - Body: {"tracking":"CPS-...", "pay_token":"..."}
- GET `/api/order/{tracking}`
- GET `/api/db-stats`

