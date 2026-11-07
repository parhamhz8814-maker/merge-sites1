// Shared helpers for the clip and poster generators: site data, palette, type.
const fs = require('fs');
const path = require('path');
const { GlobalFonts } = require('@napi-rs/canvas');

const ROOT = path.join(__dirname, '..', '..');
const SITE = path.join(ROOT, 'merged-site');
const HTML = fs.readFileSync(path.join(SITE, 'index.html'), 'utf8');

/** Parses `const X = {...}` / `= [...]` literals out of the page's inline script. */
function readJsonLiteral(src, marker) {
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`cannot find ${marker}`);
  const from = src.slice(start).search(/[[{]/) + start;
  const open = src[from];
  const close = open === '{' ? '}' : ']';
  let depth = 0;
  let str = false;
  let esc = false;
  for (let i = from; i < src.length; i++) {
    const c = src[i];
    if (str) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') str = false;
      continue;
    }
    if (c === '"') str = true;
    else if (c === open) depth++;
    else if (c === close && --depth === 0) return JSON.parse(src.slice(from, i + 1));
  }
  throw new Error(`unterminated literal for ${marker}`);
}

const GAME_DETAILS = readJsonLiteral(HTML, 'const GAME_DETAILS =');
const PRODUCTS = readJsonLiteral(HTML, 'const PRODUCTS =');

for (const w of ['Regular', 'Medium', 'Bold', 'Black']) {
  GlobalFonts.registerFromPath(path.join(__dirname, 'fonts', `Vazirmatn-${w}.ttf`), `Vazirmatn ${w}`);
}

const LATIN = {
  premium: 'PREMIUM & SUBSCRIPTIONS',
  codm: 'CALL OF DUTY MOBILE',
  freefire: 'FREE FIRE',
  pubg: 'PUBG MOBILE',
  football: 'FOOTBALL STRIKE',
  plato: 'PLATO',
  soccerstars: 'SOCCER STARS',
  eightball: '8 BALL POOL',
  'gift-adidas': 'ADIDAS GIFT CARD',
  'gift-amazon': 'AMAZON GIFT CARD',
  'gift-steam': 'STEAM WALLET',
  'gift-skype': 'SKYPE CREDIT',
  'gift-xbox': 'XBOX GIFT CARD',
  'gift-psn': 'PLAYSTATION GIFT CARD',
  'gift-roblox': 'ROBLOX GIFT CARD',
  'gift-razer': 'RAZER GOLD',
  'gift-freefire': 'FREE FIRE GIFT CARD',
  'gift-nike': 'NIKE GIFT CARD',
  'gift-netflix': 'NETFLIX GIFT CARD',
  'gift-nintendo': 'NINTENDO eSHOP',
  clashmini: 'CLASH MINI',
  brawlstars: 'BRAWL STARS',
  clash: 'CLASH OF CLANS',
  clashroyale: 'CLASH ROYALE',
};

const EMBLEM = {
  premium: 'PRO', codm: 'CP', freefire: 'DM', pubg: 'UC', football: 'FC', plato: 'PLT',
  soccerstars: 'SS', eightball: '8B', clashmini: 'GEM', brawlstars: 'GEM', clash: 'GEM',
  clashroyale: 'GEM',
  'gift-adidas': 'AD', 'gift-amazon': 'AZ', 'gift-steam': 'ST', 'gift-skype': 'SK',
  'gift-xbox': 'XB', 'gift-psn': 'PS', 'gift-roblox': 'RB', 'gift-razer': 'RZ',
  'gift-freefire': 'FF', 'gift-nike': 'NK', 'gift-netflix': 'NF', 'gift-nintendo': 'NT',
};

const faDigits = '۰۱۲۳۴۵۶۷۸۹';
const faNum = n => String(n).replace(/\d/g, d => faDigits[+d]);
const faPrice = n => faNum(String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, '٬'));

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let h = 0;
  let s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h, s, l];
}
function hslToRgb([h, s, l]) {
  const f = n => {
    const k = (n + h * 12) % 12;
    const a = s * Math.min(l, 1 - l);
    return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1))));
  };
  return [f(0), f(8), f(4)];
}
const rgbCss = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const hslCss = (h, s, l, a = 1) => rgbCss(hslToRgb([h, s, l]), a);

/** Most vivid, mid-light colour found in the game's own artwork. */
function accentFromArt(key) {
  const product = PRODUCTS.find(p => p.gameKey === key);
  let file = product && path.join(SITE, 'assets', 'products', `${product.id}.svg`);
  if (!file || !fs.existsSync(file)) {
    const found = fs.readdirSync(path.join(SITE, 'assets', 'products')).find(f => f.startsWith(`${key}-`));
    file = found ? path.join(SITE, 'assets', 'products', found) : null;
  }
  const fallback = [265, 0.55, 0.62];
  if (!file) return { hsl: fallback };
  const svg = fs.readFileSync(file, 'utf8');
  const hexes = [...new Set((svg.match(/#[0-9a-fA-F]{6}/g) || []).map(h => h.toLowerCase()))];
  let best = null;
  let bestScore = -1;
  for (const hex of hexes) {
    const hsl = rgbToHsl(hexToRgb(hex));
    if (hsl[1] < 0.18) continue;
    const score = hsl[1] * 1.6 - Math.abs(hsl[2] - 0.58);
    if (score > bestScore) { bestScore = score; best = hsl; }
  }
  const hsl = best
    ? [best[0], Math.max(0.55, Math.min(0.9, best[1])), Math.max(0.58, Math.min(0.7, best[2]))]
    : fallback;
  return { hsl };
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function fitFont(ctx, text, weight, maxWidth, startSize, family = 'Vazirmatn Black') {
  let size = startSize;
  do {
    ctx.font = `${weight} ${size}px "${family}"`;
    if (ctx.measureText(text).width <= maxWidth) return size;
    size -= 2;
  } while (size > 16);
  return size;
}

/** Cuts a string to fit maxWidth, appending an ellipsis. */
function ellipsize(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let out = text;
  while (out.length > 4 && ctx.measureText(out + '…').width > maxWidth) out = out.slice(0, -1);
  return out.trimEnd() + '…';
}

const discountPct = p => (p.old && p.old > p.price ? Math.round((1 - p.price / p.old) * 100) : 0);

/** The game's most compelling offers: biggest discount first, then best sellers. */
function featuredItems(key, count = 3) {
  const items = PRODUCTS.filter(p => p.gameKey === key);
  const score = p => discountPct(p) + (p.badge ? 6 : 0) + (p.badgeCls === 'hot' ? 4 : 0);
  return [...items].sort((a, b) => score(b) - score(a)).slice(0, count);
}

function gameStats(key) {
  const items = PRODUCTS.filter(p => p.gameKey === key);
  return {
    items,
    count: items.length,
    min: items.length ? Math.min(...items.map(p => p.price)) : 0,
    maxDiscount: items.length ? Math.max(...items.map(discountPct)) : 0,
  };
}

module.exports = {
  ROOT, SITE, GAME_DETAILS, PRODUCTS, LATIN, EMBLEM,
  faNum, faPrice, accentFromArt, hslCss, rgbCss,
  roundRect, fitFont, ellipsize, discountPct, featuredItems, gameStats,
};
