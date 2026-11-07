/**
 * Renders short branded preview clips for every game on the CP.Shop storefront.
 *
 *   node make-videos.js            -> all game keys
 *   node make-videos.js codm clash -> just those keys
 *
 * Output (consumed by the game drawer in merged-site/index.html):
 *   merged-site/assets/videos/<gameKey>.mp4   1280x800 (16:10), H.264, muted, ~5.5s
 *   merged-site/assets/videos/<gameKey>.jpg   poster frame
 */
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { createCanvas, GlobalFonts, loadImage } = require('@napi-rs/canvas');
const ffmpegPath = require('ffmpeg-static');

const ROOT = path.join(__dirname, '..', '..');
const SITE = path.join(ROOT, 'merged-site');
const HTML = fs.readFileSync(path.join(SITE, 'index.html'), 'utf8');
const OUT_DIR = path.join(SITE, 'assets', 'videos');

const W = 1280;
const H = 800;
const FPS = 30;
const DURATION = 5.5;
const FRAMES = Math.round(FPS * DURATION);

for (const w of ['Regular', 'Medium', 'Bold', 'Black']) {
  GlobalFonts.registerFromPath(path.join(__dirname, 'fonts', `Vazirmatn-${w}.ttf`), `Vazirmatn ${w}`);
}

/* ---------- data pulled straight from the page ---------- */

function readJsonLiteral(src, marker) {
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`cannot find ${marker}`);
  const from = src.slice(start).search(/[[{]/) + start;
  const openCh = src[from];
  const closeCh = openCh === '{' ? '}' : ']';
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = from; i < src.length; i++) {
    const c = src[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === '\\') esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') inStr = true;
    else if (c === openCh) depth++;
    else if (c === closeCh) {
      depth--;
      if (!depth) return JSON.parse(src.slice(from, i + 1));
    }
  }
  throw new Error(`unterminated literal for ${marker}`);
}

const GAME_DETAILS = readJsonLiteral(HTML, 'const GAME_DETAILS =');
const PRODUCTS = readJsonLiteral(HTML, 'const PRODUCTS =');

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

/* ---------- colour helpers ---------- */

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
  if (!file) return { hsl: fallback, art: null };
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
  const hsl = best ? [best[0], Math.max(0.55, Math.min(0.9, best[1])), Math.max(0.58, Math.min(0.7, best[2]))] : fallback;
  return { hsl, art: file };
}

/* ---------- drawing primitives ---------- */

const easeOut = t => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3);
const clamp01 = t => Math.max(0, Math.min(1, t));
const appear = (t, start, dur) => easeOut(clamp01((t - start) / dur));

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
  } while (size > 20);
  return size;
}

/* ---------- frame renderer ---------- */

const faDigits = '۰۱۲۳۴۵۶۷۸۹';
const faNum = n => String(n).replace(/\d/g, d => faDigits[+d]);
const faPrice = n => faNum(String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, '٬'));

const EMBLEM = {
  premium: 'PRO', codm: 'CP', freefire: 'DM', pubg: 'UC', football: 'FC', plato: 'PLT',
  soccerstars: 'SS', eightball: '8B', clashmini: 'GEM', brawlstars: 'GEM', clash: 'GEM',
  clashroyale: 'GEM',
  'gift-adidas': 'AD', 'gift-amazon': 'AZ', 'gift-steam': 'ST', 'gift-skype': 'SK',
  'gift-xbox': 'XB', 'gift-psn': 'PS', 'gift-roblox': 'RB', 'gift-razer': 'RZ',
  'gift-freefire': 'FF', 'gift-nike': 'NK', 'gift-netflix': 'NF', 'gift-nintendo': 'NT',
};

function makeRenderer(key) {
  const detail = GAME_DETAILS[key] || { title: key, kicker: '', tips: [] };
  const items = PRODUCTS.filter(p => p.gameKey === key);
  const stats = {
    count: items.length,
    min: items.length ? Math.min(...items.map(p => p.price)) : 0,
  };
  const { hsl } = accentFromArt(key);
  const accent = c => hslCss(hsl[0], hsl[1], hsl[2], c);

  return async function render(ctx, t) {
    const p = t / DURATION;

    // background
    const bg = ctx.createLinearGradient(0, 0, W, H);
    bg.addColorStop(0, '#0B0B1A');
    bg.addColorStop(0.55, '#0F0F23');
    bg.addColorStop(1, '#161430');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // drifting accent glows
    const glows = [
      { x: 300 + Math.sin(p * Math.PI * 2) * 40, y: 210 + Math.cos(p * Math.PI * 2) * 30, r: 460, a: 0.3 },
      { x: 1010 + Math.cos(p * Math.PI * 2 + 1) * 60, y: 650 + Math.sin(p * Math.PI * 2) * 40, r: 520, a: 0.2 },
      { x: 760 + Math.sin(p * Math.PI * 2 + 2) * 70, y: 120, r: 340, a: 0.12 },
    ];
    for (const g of glows) {
      const rg = ctx.createRadialGradient(g.x, g.y, 0, g.x, g.y, g.r);
      rg.addColorStop(0, accent(g.a));
      rg.addColorStop(1, accent(0));
      ctx.fillStyle = rg;
      ctx.fillRect(0, 0, W, H);
    }

    // faint dot grid
    ctx.fillStyle = 'rgba(226,232,240,0.05)';
    for (let y = 40; y < H; y += 44) {
      for (let x = (y / 44) % 2 ? 22 : 0; x < W; x += 44) ctx.fillRect(x, y, 2, 2);
    }

    // soft vignette
    const vg = ctx.createRadialGradient(W / 2, H / 2, 220, W / 2, H / 2, 820);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,0.55)');
    ctx.fillStyle = vg;
    ctx.fillRect(0, 0, W, H);

    /* ---- emblem tile (left, floating) ---- */
    const enter = appear(t, 0.05, 0.75);
    const cardW = 430;
    const cardH = 269;
    const cx = 60 + (1 - enter) * -70;
    const cy = 268 + Math.sin(t * 1.6) * 9;
    const tilt = Math.sin(t * 1.15) * 0.018;

    ctx.save();
    ctx.translate(cx + cardW / 2, cy + cardH / 2);
    ctx.rotate(tilt);
    ctx.globalAlpha = enter;

    // glow under card
    ctx.shadowColor = accent(0.55);
    ctx.shadowBlur = 60;
    ctx.fillStyle = 'rgba(10,10,24,0.9)';
    roundRect(ctx, -cardW / 2, -cardH / 2, cardW, cardH, 20);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.save();
    roundRect(ctx, -cardW / 2, -cardH / 2, cardW, cardH, 20);
    ctx.clip();

    const tile = ctx.createLinearGradient(-cardW / 2, -cardH / 2, cardW / 2, cardH / 2);
    tile.addColorStop(0, accent(0.34));
    tile.addColorStop(0.55, 'rgba(30,28,53,0.95)');
    tile.addColorStop(1, 'rgba(12,12,28,1)');
    ctx.fillStyle = tile;
    ctx.fillRect(-cardW / 2, -cardH / 2, cardW, cardH);

    // concentric rings echoing the storefront's orbit motif
    for (const r of [150, 205, 262]) {
      ctx.beginPath();
      ctx.arc(0, -8, r, 0, Math.PI * 2);
      ctx.strokeStyle = accent(0.16);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // emblem monogram
    const emblem = EMBLEM[key] || (LATIN[key] || key).slice(0, 4);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = accent(0.85);
    ctx.shadowBlur = 42;
    ctx.fillStyle = '#FFFFFF';
    const emblemSize = emblem.length > 3 ? 74 : emblem.length > 2 ? 88 : 108;
    ctx.font = `900 ${emblemSize}px "Vazirmatn Black"`;
    ctx.fillText(emblem, 0, -34);
    ctx.shadowBlur = 0;

    // starting price
    ctx.font = '700 22px "Vazirmatn Bold"';
    ctx.fillStyle = accent(0.95);
    ctx.fillText(`از ${faPrice(stats.min)} تومان`, 0, 66);

    // product count pill, top-right of tile
    ctx.font = '500 16px "Vazirmatn Medium"';
    const countLabel = `${faNum(stats.count)} محصول`;
    const pillW = ctx.measureText(countLabel).width + 30;
    ctx.fillStyle = 'rgba(9,9,22,0.55)';
    roundRect(ctx, cardW / 2 - 18 - pillW, -cardH / 2 + 16, pillW, 34, 17);
    ctx.fill();
    ctx.strokeStyle = accent(0.35);
    ctx.lineWidth = 1;
    ctx.stroke();
    ctx.fillStyle = 'rgba(241,245,249,0.92)';
    ctx.fillText(countLabel, cardW / 2 - 18 - pillW / 2, -cardH / 2 + 33);

    // brand mark, bottom-left of tile
    ctx.textAlign = 'left';
    ctx.font = '700 14px "Vazirmatn Bold"';
    ctx.fillStyle = 'rgba(226,232,240,0.55)';
    ctx.fillText('C P . S H O P', -cardW / 2 + 20, cardH / 2 - 26);
    ctx.restore();

    // card border
    ctx.strokeStyle = accent(0.55);
    ctx.lineWidth = 2;
    roundRect(ctx, -cardW / 2, -cardH / 2, cardW, cardH, 20);
    ctx.stroke();

    // light sweep across the card
    const sweepT = ((t - 0.9) % 3) / 3;
    if (t > 0.9) {
      const sx = -cardW / 2 + sweepT * (cardW * 1.6) - cardW * 0.3;
      const sw = ctx.createLinearGradient(sx, -cardH / 2, sx + 150, cardH / 2);
      sw.addColorStop(0, 'rgba(255,255,255,0)');
      sw.addColorStop(0.5, 'rgba(255,255,255,0.16)');
      sw.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.save();
      roundRect(ctx, -cardW / 2, -cardH / 2, cardW, cardH, 20);
      ctx.clip();
      ctx.fillStyle = sw;
      ctx.fillRect(-cardW / 2, -cardH / 2, cardW, cardH);
      ctx.restore();
    }
    ctx.restore();

    /* ---- right column copy (RTL) ---- */
    const RE = W - 64;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'alphabetic';

    // brand pill
    const brandA = appear(t, 0.15, 0.5);
    ctx.globalAlpha = brandA;
    ctx.font = '700 22px "Vazirmatn Bold"';
    const brandLabel = 'سی‌پی شاپ';
    const brandW = ctx.measureText(brandLabel).width + 58;
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    ctx.strokeStyle = 'rgba(255,255,255,0.16)';
    ctx.lineWidth = 1.5;
    roundRect(ctx, RE - brandW, 78, brandW, 46, 23);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = accent(0.95);
    ctx.beginPath();
    ctx.arc(RE - brandW + 24, 101, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#F1F5F9';
    ctx.fillText(brandLabel, RE - 14, 110);
    ctx.globalAlpha = 1;

    // latin subtitle
    const latin = LATIN[key] || key.toUpperCase();
    const latinA = appear(t, 0.4, 0.6);
    ctx.globalAlpha = latinA;
    ctx.fillStyle = accent(0.85);
    ctx.font = '500 17px "Vazirmatn Medium"';
    ctx.save();
    ctx.translate(RE, 190);
    ctx.fillText(latin.split('').join(String.fromCharCode(8202)), 0, 0);
    ctx.restore();
    ctx.globalAlpha = 1;

    // title
    const titleA = appear(t, 0.22, 0.7);
    const titleY = 268 + (1 - titleA) * 24;
    ctx.globalAlpha = titleA;
    ctx.fillStyle = '#FFFFFF';
    const titleSize = fitFont(ctx, detail.title, 900, 620, 66, 'Vazirmatn Black');
    ctx.font = `900 ${titleSize}px "Vazirmatn Black"`;
    ctx.fillText(detail.title, RE, titleY);
    ctx.globalAlpha = 1;

    // kicker
    const kickerA = appear(t, 0.42, 0.6);
    ctx.globalAlpha = kickerA;
    ctx.font = '500 26px "Vazirmatn Medium"';
    ctx.fillStyle = 'rgba(148,163,184,0.95)';
    ctx.fillText(detail.kicker || 'تحویل آنی و امن', RE, 318 + (1 - kickerA) * 16);
    ctx.globalAlpha = 1;

    // divider
    const divA = appear(t, 0.55, 0.5);
    ctx.globalAlpha = divA;
    const divGrad = ctx.createLinearGradient(RE - 560, 0, RE, 0);
    divGrad.addColorStop(0, accent(0));
    divGrad.addColorStop(1, accent(0.5));
    ctx.fillStyle = divGrad;
    ctx.fillRect(RE - 560, 348, 560, 2);
    ctx.globalAlpha = 1;

    // tips
    (detail.tips || []).forEach((tip, i) => {
      const a = appear(t, 0.62 + i * 0.16, 0.55);
      const y = 404 + i * 54 + (1 - a) * 14;
      ctx.globalAlpha = a;
      ctx.fillStyle = '#E2E8F0';
      ctx.font = '500 25px "Vazirmatn Medium"';
      ctx.fillText(tip, RE - 44, y);
      // check dot
      ctx.beginPath();
      ctx.arc(RE - 20, y - 8, 13, 0, Math.PI * 2);
      ctx.fillStyle = accent(0.18);
      ctx.fill();
      ctx.strokeStyle = accent(0.75);
      ctx.lineWidth = 1.6;
      ctx.stroke();
      ctx.strokeStyle = accent(1);
      ctx.lineWidth = 2.6;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(RE - 25, y - 8);
      ctx.lineTo(RE - 21, y - 3);
      ctx.lineTo(RE - 14, y - 14);
      ctx.stroke();
      ctx.globalAlpha = 1;
    });

    // CTA pill
    const ctaA = appear(t, 1.05, 0.6);
    const pulse = 1 + Math.sin(t * 3) * 0.012;
    ctx.save();
    ctx.globalAlpha = ctaA;
    ctx.translate(RE, 600 + (1 - ctaA) * 18);
    ctx.scale(pulse, pulse);
    const ctaW = 300;
    const ctaH = 66;
    ctx.shadowColor = accent(0.4);
    ctx.shadowBlur = 34;
    ctx.fillStyle = '#F8FAFC';
    roundRect(ctx, -ctaW, -ctaH / 2, ctaW, ctaH, 33);
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#0B0B1A';
    ctx.font = '700 25px "Vazirmatn Bold"';
    ctx.textAlign = 'center';
    ctx.fillText('خرید آنی', -ctaW / 2 + 18, 9);
    // arrow
    ctx.strokeStyle = '#0B0B1A';
    ctx.lineWidth = 2.6;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(-56, 0);
    ctx.lineTo(-76, 0);
    ctx.moveTo(-68, -8);
    ctx.lineTo(-76, 0);
    ctx.lineTo(-68, 8);
    ctx.stroke();
    ctx.restore();
    ctx.textAlign = 'right';

    // support line
    const noteA = appear(t, 1.3, 0.6);
    ctx.globalAlpha = noteA;
    ctx.fillStyle = 'rgba(148,163,184,0.9)';
    ctx.font = '500 19px "Vazirmatn Medium"';
    ctx.fillText('پرداخت ریالی · تحویل خودکار · پشتیبانی تمام روزهای هفته', RE, 668);
    ctx.globalAlpha = 1;

    /* ---- footer + progress ---- */
    ctx.fillStyle = 'rgba(226,232,240,0.1)';
    ctx.fillRect(64, H - 52, W - 128, 3);
    const prog = clamp01(t / DURATION);
    const pgGrad = ctx.createLinearGradient(64, 0, W - 64, 0);
    pgGrad.addColorStop(0, accent(0.35));
    pgGrad.addColorStop(1, accent(0.95));
    ctx.fillStyle = pgGrad;
    ctx.fillRect(64, H - 52, (W - 128) * prog, 3);

    ctx.fillStyle = 'rgba(148,163,184,0.75)';
    ctx.font = '500 17px "Vazirmatn Medium"';
    ctx.textAlign = 'left';
    ctx.fillText('CP.SHOP', 64, H - 24);
    ctx.textAlign = 'right';
    ctx.fillText('پیش‌نمایش بازی', W - 64, H - 24);

    return p;
  };
}

/* ---------- encode ---------- */

function encode(key) {
  return new Promise(async (resolve, reject) => {
    const render = await makeRenderer(key);
    const canvas = createCanvas(W, H);
    const ctx = canvas.getContext('2d');
    const mp4 = path.join(OUT_DIR, `${key}.mp4`);
    const jpg = path.join(OUT_DIR, `${key}.jpg`);

    const ff = spawn(ffmpegPath, [
      '-y', '-loglevel', 'error',
      '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', `${W}x${H}`, '-framerate', String(FPS), '-i', 'pipe:0',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '30', '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart', '-an', mp4,
    ], { stdio: ['pipe', 'ignore', 'pipe'] });

    let stderr = '';
    ff.stderr.on('data', d => { stderr += d.toString(); });
    ff.on('error', reject);
    ff.on('close', code => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}: ${stderr}`))));

    const posterAt = Math.round(FPS * 2.1);
    for (let i = 0; i < FRAMES; i++) {
      await render(ctx, i / FPS);
      if (i === posterAt) fs.writeFileSync(jpg, canvas.toBuffer('image/jpeg', 88));
      const buf = Buffer.from(canvas.data());
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    }
    ff.stdin.end();
  });
}

/* ---------- main ---------- */

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const all = Object.keys(GAME_DETAILS);
  const requested = process.argv.slice(2);
  const keys = requested.length ? requested : all;

  // 3 at a time keeps the machine responsive
  const queue = [...keys];
  const workers = Array.from({ length: 3 }, async () => {
    while (queue.length) {
      const key = queue.shift();
      const started = Date.now();
      await encode(key);
      const kb = Math.round(fs.statSync(path.join(OUT_DIR, `${key}.mp4`)).size / 1024);
      console.log(`${key.padEnd(16)} ${kb} KB  ${((Date.now() - started) / 1000).toFixed(1)}s`);
    }
  });
  await Promise.all(workers);
  console.log(`done: ${keys.length} clip(s)`);
})().catch(err => { console.error(err); process.exit(1); });
