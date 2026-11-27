# merged-backend — CP.Shop (ircodmshop.com)

Backend for the CP.Shop storefront:
- MCP catalog tools (search / pricing / cart estimation)
- HTTP server (Starlette) that serves the storefront from `../dist/` and exposes
  the order API on the same origin

## Files
| File | Purpose |
|---|---|
| `cpshop_http.py` | HTTP app: static serving, order API, MCP mount |
| `cpshop_mcp.py` | MCP server exposing catalog tools |
| `store_db.py` | SQLite persistence, schema/migrations, order lifecycle, backups |
| `security.py` | Security headers, host allow-list, rate limiting, body cap |
| `catalog.json` | Product catalog (seed source) |
| `shopping_cart.py` | ShoppingCart helper that builds order items |
| `db_tool.py` | CLI: `stats`, `reset`, `export` |
| `schema.sql` | Schema reference for versioning |
| `test_production_security.py` | Full DB + security regression suite |

## Requirements
```
python -m pip install pydantic mcp starlette uvicorn
```

## Run
```
python cpshop_http.py 8765
```
Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `CPSHOP_HOSTS` | `ircodmshop.com,www.ircodmshop.com,127.0.0.1,localhost` | Allowed `Host` headers (421 otherwise) |
| `CPSHOP_ORIGINS` | `https://ircodmshop.com,https://www.ircodmshop.com,...` | CORS allow-list |
| `CPSHOP_TRUST_PROXY` | **unset — leave it unset** | Set to `1` **only** behind nginx/Cloudflare so the real client IP is read from `X-Forwarded-For`. If the app is directly internet-facing, setting it lets clients spoof their IP and bypass rate limiting. |
| `CPSHOP_ALLOW_ANY_HOST` | off | Disable the host allow-list (local debugging only) |
| `CPSHOP_HOST` | `0.0.0.0` | Bind address |

> **Deployment note:** ircodmshop.com is served by GitHub Pages (static files,
> `merge-sites1` repo, `main` branch). This backend is **not** currently deployed
> there. Everything below describes the backend as it runs locally / on a host
> you point at it.

## One command to verify everything
```
python run_tests.py
```
Runs all four suites and exits `0` only if every one passes. It prints a
per-suite PASS/FAIL summary at the end.

Individual suites, if you want to run them separately:
```
python check_imports.py
python test_shopping_cart.py
python test_db_production_flow.py
python test_production_security.py   # 37 assertions: schema, lifecycle, privacy, tokens
```

### Manual verification steps
```bash
# 1. fresh DB + catalog seed (201 products)
python db_tool.py reset
python db_tool.py stats

# 2. start the server
python cpshop_http.py 8765

# 3. in another shell — create an order (note: total must match, or 400)
curl -s -X POST http://127.0.0.1:8765/api/order \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"product_id":"codm-015","quantity":1,"player_id":"12345678"}],
       "customer_name":"Ali","customer_contact":"09121234567","total":199400}'

# 4. total mismatch is rejected with 400
curl -s -X POST http://127.0.0.1:8765/api/order \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"product_id":"codm-015","quantity":1,"player_id":"12345678"}],
       "customer_name":"Ali","customer_contact":"09121234567","total":1}'

# 5. pay with the returned pay_token (single-use, 30 min TTL)
curl -s -X POST http://127.0.0.1:8765/api/order/pay \
  -H 'Content-Type: application/json' \
  -d '{"tracking":"CPS-XXXXXXXX","pay_token":"<token from step 3>"}'

# 6. anonymous read masks the contact; ?token=... reveals it
curl -s http://127.0.0.1:8765/api/order/CPS-XXXXXXXX
curl -s "http://127.0.0.1:8765/api/order/CPS-XXXXXXXX?token=<token>"
```

## API

### `POST /api/order`
Creates a **pending** order. Prices come only from the `products` table — any
client-supplied amount is ignored.

```json
{
  "items": [{"product_id": "codm-015", "quantity": 1, "player_id": "12345678"}],
  "customer_name": "علی رضایی",
  "customer_contact": "09121234567",
  "total": 199400
}
```
`customer_name` and `customer_contact` are **required** (a top-up cannot be
delivered without a way to reach the buyer). `player_id` is required for the
`codm`, `clash` and `other` categories.

`total` is **optional but enforced when present**: it must equal the server's
recomputed sum of `unit_price × quantity`, otherwise the request is rejected
with `400` and a "refresh the page" message. Sending it catches a client whose
displayed price has drifted from the catalog.

Response `201`:
```json
{"tracking":"CPS-XXXXXXXX","total":199400,"item_count":1,
 "status":"pending","currency":"toman","pay_token":"..."}
```
`pay_token` is returned **once** and never stored in raw form.

### `POST /api/order/pay`
`{"tracking":"CPS-...","pay_token":"..."}` → `pending` → `paid`.
Requires the per-order token; a bare tracking code is not enough. The token is
**single-use** (burned on success) and **expires after 30 minutes**. A retried
callback with the same token on the same order returns `paid` (idempotent).

### `POST /api/order/cancel`
Same shape and gate as `/pay`; `pending` → `canceled`.

### `GET /api/order/{tracking}`
Returns status and items. **Contact details are masked** unless the request also
supplies the order's token: `?token=...`.

### `GET /api/stats`
Public. Returns catalog size only (`{"products": 201}`). Revenue and order
counts are deliberately **not** exposed.

### `GET /health`
Liveness probe.

## Database schema (SQLite)

### `products`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | catalog id |
| `game_key` | TEXT NOT NULL | e.g. `codm` |
| `game` | TEXT NOT NULL | Persian display name |
| `title` | TEXT NOT NULL | pack title |
| `category` | TEXT NOT NULL | `codm` / `clash` / `other` / `gift` / `premium` |
| `price` | INTEGER NOT NULL | `CHECK(price > 0)` — server truth |
| `old_price` | INTEGER | nullable, `CHECK >= 0` |
| `badge` | TEXT | nullable |
| `currency` | TEXT NOT NULL | default `toman` |
| `stock` | INTEGER NOT NULL | `CHECK(stock >= 0)`, default 999999 |
| `is_active` | INTEGER NOT NULL | `CHECK IN (0,1)` |
| `created_at` | TEXT NOT NULL | default `datetime('now')` |

### `customers`
`id`, `name` (NOT NULL, 1–120 chars), `phone` (UNIQUE), `email` (UNIQUE),
`game_player_id`, `created_at`.

### `orders`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `tracking` | TEXT UNIQUE NOT NULL | `CPS-XXXXXXXX` |
| `status` | TEXT NOT NULL | `CHECK IN ('pending','paid','canceled')` |
| `customer_id` | INTEGER | FK → `customers.id` ON DELETE SET NULL |
| `customer_name` | TEXT NOT NULL | **snapshot** at order time |
| `customer_contact` | TEXT NOT NULL | **snapshot** at order time |
| `total` | INTEGER NOT NULL | `CHECK(total > 0)` |
| `item_count` | INTEGER NOT NULL | `CHECK > 0` |
| `currency` | TEXT NOT NULL | default `toman` |
| `created_at` | TEXT NOT NULL | |
| `paid_at` | TEXT | |
| `pay_token_hash` | TEXT | SHA-256 of the pay token — **the raw token is never stored** |
| `pay_token_expires_at` | TEXT | UTC, `created_at + 30 min` |
| `pay_token_used_at` | TEXT | set when the token is burned (paid or canceled) |

### `order_items`
`id`, `order_id` (FK → `orders.id` ON DELETE CASCADE), `product_id`
(FK → `products.id` ON DELETE RESTRICT), `title`, `game`,
`quantity` (`CHECK BETWEEN 1 AND 99`), `unit_price` (`CHECK > 0`), `player_id`.

### Indexes
`idx_orders_tracking`, `idx_orders_status`, `idx_orders_customer_id`,
`idx_orders_created_at`, `idx_order_items_order_id`, `idx_order_items_product`,
`idx_order_items_player`, plus product lookup indexes.

## Backups
```
python db_tool.py export            # unredacted — production backup, never commit
python db_tool.py stats             # internal stats incl. revenue
python db_tool.py reset             # drop and re-seed (destructive)
```
`store_db.export_orders_json(path, redact=True)` produces a shareable copy with
customer contact and player ids masked. The unredacted export contains PII and
is git-ignored.

## Security model
- **Server-side pricing** — the client cannot influence an order total. If the
  client sends `total`, it must equal the server-computed sum or the order is
  rejected with `400`; the total is also re-verified against the stored lines
  at payment time.
- **Token-gated state changes** — `pay` / `cancel` / unmasked reads require the
  per-order pay token. Only its **SHA-256 hash** is stored, so a leaked database
  file grants no payment authority.
- **Single-use, expiring tokens** — a token is burned on success (or on cancel)
  and expires 30 minutes after creation (`PAY_TOKEN_TTL_MINUTES`). Replaying a
  burned token against another order fails; replaying the token that actually
  paid an order is accepted so a retried gateway callback stays idempotent.
- **PII masking** — the tracking code alone never reveals a phone number.
- **Host allow-list** — requests with a foreign `Host` get `421`.
- **Rate limiting** — 60 req/min per IP on `/api/*` and `/mcp`, proxy-aware
  (proxy trust off by default).
- **Body cap** — 64 KB, enforced by counting the stream.
- **Headers** — CSP, HSTS, `nosniff`, `DENY` framing, Referrer-Policy,
  Permissions-Policy, COOP/CORP.
- **Static surface** — only `dist/` is served; `.db`, `.py`, dotfiles and
  backend directories are blocked by extension and path.

## Tests
```
python run_tests.py                  # all four suites, one command
python test_production_security.py   # 37 checks: schema, lifecycle, privacy, tokens, backups
python test_shopping_cart.py
python test_db_production_flow.py
python check_imports.py
```
All exit `0` on success.

### Live site check
```
python check_https.py
```
Read-only check against the deployed site (no server needed). Verifies the TLS
certificate, that `https://ircodmshop.com/` returns 200, that `http://` **and**
`www.` redirect to the https apex, that the canonical tag is https, and that the
page loads no `http://` subresources. Exits `1` and names the failing check if
HTTPS enforcement regresses.

If `http:// redirects to https` fails, enable **Enforce HTTPS** at
`github.com/parhamhz8814-maker/merge-sites1/settings/pages`. GitHub Pages cannot
set `Strict-Transport-Security` itself — that needs a proxy in front — but
Enforce HTTPS closes the actual plaintext-session hole.
