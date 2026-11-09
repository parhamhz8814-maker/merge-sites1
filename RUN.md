# CP.Shop — Run & Deploy

## Start the shop (one command, shop + API on one origin)

```bash
cd Desktop/merge-sites/merged-backend
python -c "import cpshop_http, uvicorn; uvicorn.run(cpshop_http.build_app(), host='127.0.0.1', port=8000)"
```

Open **http://127.0.0.1:8000/**

That single server does everything:

| Route | What it does |
|---|---|
| `GET /` | serves the storefront from `../dist/` |
| `GET /assets/*` | product images, videos, posters |
| `POST /api/order` | creates a real order in SQLite, returns tracking + pay token |
| `POST /api/order/pay` | marks the order paid |
| `GET /api/order/{tracking}` | order status lookup |
| `GET /api/db-stats` | products / orders / revenue |
| `GET /health` | liveness |

Orders are priced **server-side** from the SQLite `products` table — the browser
cannot send a price. The `pay_token` returned at creation is required to mark an
order paid, so a tracking code alone can't fake a payment.

## Static-only mode (no orders)

If you only want to look at the site:

```bash
cd Desktop/merge-sites/dist
python -m http.server 8894
```

Cart and checkout still work, but the order falls back to a demo tracking code
because `/api/order` doesn't exist on a plain static server.

## Database

`merged-backend/cpshop.db` — SQLite.

- 201 products, seeded from `catalog.json` (ids match the frontend exactly)
- Re-seed after changing `catalog.json`:

```bash
cd Desktop/merge-sites/merged-backend
python reseed.py
```

`reseed.py` clears the products table and reloads it; orders are left intact.

## Editing the site

Edit `Desktop/merge-sites/dist/index.html` (the file the server actually serves).
Then copy it to the other copies so they don't drift:

```bash
cd Desktop/merge-sites
cp dist/index.html merged-site/index.html
cp dist/index.html merged-frontend/index.html
```

Current fixed copies are all **232,129 bytes**. `cp.shop/` and `cpshop/` are the
original source repos and are intentionally left untouched.

## Deploying publicly

See `dist/README-DEPLOY.md` for GitHub Pages / Cloudflare / Netlify. Those hosts
serve static files only — the API needs a Python host (Render, Railway, Fly) to
keep real orders working.

## Known limits

- Payment gateway is a **simulated** OTP screen — no real money moves.
- Prices are a snapshot scraped from a competitor; re-scrape periodically.
- Videos are ~190 KB each; total `dist` is ~8.2 MB.
