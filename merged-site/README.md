# Merged site — CP.Shop (سی‌پی شاپ)

This folder contains a unified static site built by merging:
- **cpshop** (main/most complete): RTL Persian storefront UI + game drawer + MCP-aware UI
- **cp.shop** (contributions): `logos.html` (same as cpshop), extra deploy/run docs + `project-id` (icons are identical)

## Contents
- `index.html` — merged storefront (use cpshop as the base)
- `logos.html` — logo picker page
- `robots.txt`, `sitemap.xml` — SEO helpers
- `assets/` — shared icon assets (favicon/OG/apple-touch)
- `DEPLOY.md`, `run.md` — deployment notes from cpshop/cp.shop

## Run locally (preview)
Since this is plain static HTML, you can preview it with any static server.

Option A (Python):
1. `cd "C:\Users\Mr laptop\Desktop\merge-sites\merged-site"`
2. `python -m http.server 8080`
3. Open: `http://localhost:8080/`

Option B: double-click `index.html` (some features like fetch/MCP won’t run, but UI renders).

## Deploy
Use Netlify / GitHub Pages for static hosting.

1. Upload the whole `merged-site/` directory.
2. **Open `index.html` and replace** every occurrence of `cpshop.example` with your real domain (canonical, og:url, JSON-LD URL, sitemap loc, etc.).

See `DEPLOY.md` for the full step-by-step guide.
