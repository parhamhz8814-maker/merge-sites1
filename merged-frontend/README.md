# merged-frontend (Dark monochrome CP.Shop)

This folder contains the merged frontend built for the **CP.Shop** store.

## Base
- Used `cpshop/index.html` as the base (full storefront: RTL, products grid, search, cart, game drawer).

## Theme changes (dark monochrome)
- Added a final CSS override block (near the bottom of `index.html`) to force a dark monochrome palette:
  - Background: `#0A0A0A`
  - Text: `#F0F0F0`
  - Cards: `#1A1A1A`
  - Borders: `#333333`
- Neutralized the previously visible purple/rose UI accents by replacing occurrences of:
  - `#7C3AED`
  - `#F43F5E`
  - and related dependent vars/usages
  with gray/white equivalents.

## Assets
- Copied referenced icon assets into this folder:
  - `apple-touch-icon.png`
  - `icon-64.png`
  - `og-icon.png`

## Notes
- RTL layout (`lang="fa" dir="rtl"`) and store functionality are preserved (products, games, game drawer, search, cart).

## How to preview
Open `index.html` directly in the browser:
- `C:\Users\Mr laptop\Desktop\merge-sites\merged-frontend\index.html`
