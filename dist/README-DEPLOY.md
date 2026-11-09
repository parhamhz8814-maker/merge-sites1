# CP.Shop — Deploy Guide

Static site. **No build step.** Upload the folder as-is.

## Contents (256 files, ~8.2 MB)

| Path | Files | Size |
|---|---|---|
| `index.html` | 1 | 230 KB |
| `privacy.html` | 1 | 17 KB |
| `logos.html` | 1 | 18 KB |
| `robots.txt`, `sitemap.xml`, `.nojekyll` | 3 | < 1 KB |
| `assets/products/` | 201 SVG | 884 KB |
| `assets/videos/` | 24 MP4 | 4.1 MB |
| `assets/posters/` | 24 JPG | 3.0 MB |

Largest single file: `assets/videos/premium.mp4` at **191 KB** — well under any host limit (GitHub's is 100 MB).

## GitHub Pages

```bash
cd dist
git init
git add -A
git commit -m "CP.Shop static site"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

Then **Settings → Pages → Source: Deploy from a branch → `main` / `/ (root)` → Save**.
Live at `https://<user>.github.io/<repo>/` in about a minute.

> `.nojekyll` is already included — it stops Jekyll from mangling the `assets` paths.

## Cloudflare Pages

1. **Workers & Pages → Create → Pages → Connect to Git**
2. Pick the repo
3. **Build command:** leave empty · **Build output directory:** `/` (or `dist` if the repo root holds the parent folder)
4. **Save and Deploy**

## Netlify

1. **Add new site → Import an existing project**
2. Pick the repo
3. **Build command:** empty · **Publish directory:** `dist` (or `.`)
4. **Deploy**

Or drag the `dist` folder straight onto the Netlify dashboard — no git needed.

## Custom domain

1. Buy the domain (`.ir` via an Iranian registrar is cheapest and avoids the `.com` payment/geo blocks).
2. At the host, add the domain under **Custom domains**.
3. At the registrar's DNS panel, point it where the host says:
   - **Cloudflare Pages / Netlify:** `CNAME` → `<your-site>.pages.dev` / `<your-site>.netlify.app`
   - **GitHub Pages:** four `A` records → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`, plus `CNAME` for `www`
4. Add a `CNAME` file at the deploy root containing only the bare domain (e.g. `cpshop.ir`) — **GitHub Pages only**.
5. SSL is automatic on all three hosts. Allow up to 24 h for DNS propagation.

## Post-deploy checklist

- [ ] Homepage loads, RTL Persian renders correctly
- [ ] Product grid shows 24 game cards
- [ ] Clicking a card opens the tab and the video plays in the left rail
- [ ] `assets/videos/*.mp4` returns 200 (not 404) — check one in devtools Network
- [ ] `privacy.html` and `logos.html` load
- [ ] HTTPS padlock present

## Notes

- The site is currently **front-end only**. The cart works in-page (localStorage); order submission is not wired to a server.
- To add a real order backend, deploy `../merged-backend/` to Render/Railway/Fly and point the cart's fetch at it. It is stdlib HTTP + SQLite, no Flask.
- Re-scrape prices periodically — they are a snapshot, not live.
