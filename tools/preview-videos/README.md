# Game preview clips and posters

Renders the assets used by the game drawer in `merged-site/index.html`, plus a
share-ready poster for every game.

```bash
npm install
node make-videos.js              # every game key (~3 min, 3 in parallel)
node make-videos.js codm clash   # only the given keys
node make-posters.js             # one 1080x1350 poster per game
node make-posters.js codm clash  # only the given keys
node verify.js                   # check every key has clips and posters
```

Videos go to `merged-site/assets/videos/<gameKey>.mp4` (1280x800, H.264, 30 fps,
5.5 s, no audio) plus a `<gameKey>.jpg` poster frame.

Posters go to `merged-site/assets/posters/<gameKey>.jpg` (1080x1350 portrait) and
feature that game's three best offers — biggest discount first — with their real
prices, struck-through old prices and discount percentages.

## How it works

- `lib.js` parses `GAME_DETAILS` and `PRODUCTS` straight out of
  `merged-site/index.html`, so titles, prices, product counts and discount
  percentages never drift from the page.
- `make-videos.js` draws the animated clips; `make-posters.js` draws the still
  posters — both use the same palette and type rules.
- Frames are drawn with `@napi-rs/canvas` (Skia) and piped as raw RGBA into the
  `ffmpeg-static` binary, which encodes H.264.
- Each game's accent colour is sampled from its own product SVG
  (`merged-site/assets/products/<id>.svg`), so palettes match the artwork.
- Vazirmatn (SIL OFL) lives in `fonts/`; it is only used at render time and is
  not shipped with the site.

Re-run after changing game titles, prices or the product list.
