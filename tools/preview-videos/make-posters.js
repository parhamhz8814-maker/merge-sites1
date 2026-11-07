/**
 * Builds one promo poster per game, using that game's real products from
 * merged-site/index.html (biggest discounts first).
 *
 *   node make-posters.js            -> every game
 *   node make-posters.js codm clash -> just those keys
 *
 * Output: merged-site/assets/posters/<gameKey>.jpg  (1080x1350, portrait)
 */
const fs = require('fs');
const path = require('path');
const { createCanvas } = require('@napi-rs/canvas');
const {
  SITE, GAME_DETAILS, LATIN, EMBLEM, faNum, faPrice, accentFromArt, hslCss,
  roundRect, fitFont, ellipsize, discountPct, featuredItems, gameStats,
} = require('./lib');

const W = 1080;
const H = 1350;
const M = 72; // page margin
const OUT_DIR = path.join(SITE, 'assets', 'posters');

function drawBrandPill(ctx, x, y, accent) {
  const label = 'سی‌پی شاپ';
  ctx.font = '700 24px "Vazirmatn Bold"';
  const w = ctx.measureText(label).width + 62;
  ctx.fillStyle = 'rgba(255,255,255,0.06)';
  ctx.strokeStyle = 'rgba(255,255,255,0.16)';
  ctx.lineWidth = 1.5;
  roundRect(ctx, x - w, y, w, 50, 25);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = accent(0.95);
  ctx.beginPath();
  ctx.arc(x - w + 26, y + 25, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = '#F1F5F9';
  ctx.textAlign = 'right';
  ctx.fillText(label, x - 15, y + 33);
}

function drawPoster(key) {
  const detail = GAME_DETAILS[key] || { title: key, kicker: '' };
  const { hsl } = accentFromArt(key);
  const accent = a => hslCss(hsl[0], hsl[1], hsl[2], a);
  const stats = gameStats(key);
  const picks = featuredItems(key, 3);

  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext('2d');

  // background
  const bg = ctx.createLinearGradient(0, 0, W * 0.4, H);
  bg.addColorStop(0, '#0A0A18');
  bg.addColorStop(0.5, '#0F0F23');
  bg.addColorStop(1, '#141230');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  for (const g of [
    { x: 900, y: 120, r: 620, a: 0.32 },
    { x: 120, y: 1180, r: 560, a: 0.2 },
    { x: 540, y: 700, r: 480, a: 0.1 },
  ]) {
    const rg = ctx.createRadialGradient(g.x, g.y, 0, g.x, g.y, g.r);
    rg.addColorStop(0, accent(g.a));
    rg.addColorStop(1, accent(0));
    ctx.fillStyle = rg;
    ctx.fillRect(0, 0, W, H);
  }

  ctx.fillStyle = 'rgba(226,232,240,0.05)';
  for (let y = 30; y < H; y += 40) {
    for (let x = (y / 40) % 2 ? 20 : 0; x < W; x += 40) ctx.fillRect(x, y, 2, 2);
  }

  const vg = ctx.createRadialGradient(W / 2, H / 2, 260, W / 2, H / 2, 900);
  vg.addColorStop(0, 'rgba(0,0,0,0)');
  vg.addColorStop(1, 'rgba(0,0,0,0.6)');
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, W, H);

  // header
  ctx.textBaseline = 'alphabetic';
  drawBrandPill(ctx, W - M, 64, accent);
  ctx.textAlign = 'left';
  ctx.font = '700 20px "Vazirmatn Bold"';
  ctx.fillStyle = 'rgba(148,163,184,0.8)';
  ctx.fillText('C P . S H O P', M, 96);

  // kicker
  ctx.textAlign = 'right';
  ctx.font = '500 24px "Vazirmatn Medium"';
  ctx.fillStyle = accent(0.95);
  ctx.fillText('پیشنهاد ویژه · تحویل آنی', W - M, 190);

  // title
  const titleSize = fitFont(ctx, detail.title, 900, W - M * 2, 88, 'Vazirmatn Black');
  ctx.font = `900 ${titleSize}px "Vazirmatn Black"`;
  ctx.fillStyle = '#FFFFFF';
  ctx.fillText(detail.title, W - M, 278);

  // latin
  ctx.font = '500 20px "Vazirmatn Medium"';
  ctx.fillStyle = accent(0.85);
  ctx.fillText((LATIN[key] || key.toUpperCase()).split('').join('\u200a'), W - M, 332);

  /* ---- emblem panel ---- */
  const panelY = 364;
  const panelH = 250;
  const panelW = W - M * 2;
  ctx.save();
  roundRect(ctx, M, panelY, panelW, panelH, 28);
  ctx.clip();
  const panelGrad = ctx.createLinearGradient(M, panelY, M + panelW, panelY + panelH);
  panelGrad.addColorStop(0, 'rgba(30,28,53,0.95)');
  panelGrad.addColorStop(1, accent(0.3));
  ctx.fillStyle = panelGrad;
  ctx.fillRect(M, panelY, panelW, panelH);
  for (const r of [120, 180, 240]) {
    ctx.beginPath();
    ctx.arc(M + 128, panelY + panelH / 2, r, 0, Math.PI * 2);
    ctx.strokeStyle = accent(0.16);
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
  ctx.restore();
  ctx.strokeStyle = accent(0.45);
  ctx.lineWidth = 1.5;
  roundRect(ctx, M, panelY, panelW, panelH, 28);
  ctx.stroke();

  // monogram
  const emblem = EMBLEM[key] || (LATIN[key] || key).slice(0, 3);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.shadowColor = accent(0.8);
  ctx.shadowBlur = 46;
  ctx.fillStyle = '#FFFFFF';
  ctx.font = `900 ${emblem.length > 3 ? 82 : emblem.length > 2 ? 100 : 122}px "Vazirmatn Black"`;
  ctx.fillText(emblem, M + 128, panelY + panelH / 2 + 4);
  ctx.shadowBlur = 0;

  // divider inside panel
  ctx.fillStyle = accent(0.35);
  ctx.fillRect(M + 300, panelY + 46, 2, panelH - 92);

  // panel stats (RTL)
  const rightEdge = M + panelW - 40;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'alphabetic';
  ctx.font = '500 22px "Vazirmatn Medium"';
  ctx.fillStyle = 'rgba(148,163,184,0.95)';
  ctx.fillText('شروع قیمت', rightEdge, panelY + 92);
  ctx.font = '900 46px "Vazirmatn Black"';
  ctx.fillStyle = '#FFFFFF';
  ctx.fillText(`از ${faPrice(stats.min)} تومان`, rightEdge, panelY + 152);
  ctx.font = '500 22px "Vazirmatn Medium"';
  ctx.fillStyle = accent(0.95);
  const sub = stats.maxDiscount
    ? `${faNum(stats.count)} محصول · تا ${faNum(stats.maxDiscount)}٪ تخفیف`
    : `${faNum(stats.count)} محصول`;
  ctx.fillText(sub, rightEdge, panelY + 200);

  /* ---- featured items ---- */
  const listLabelY = panelY + panelH + 62;
  ctx.textAlign = 'right';
  ctx.font = '700 28px "Vazirmatn Bold"';
  ctx.fillStyle = '#FFFFFF';
  ctx.fillText('منتخب محصولات', W - M, listLabelY);
  const labelW = ctx.measureText('منتخب محصولات').width;
  const lineGrad = ctx.createLinearGradient(M, 0, W - M - labelW - 28, 0);
  lineGrad.addColorStop(0, 'rgba(255,255,255,0.02)');
  lineGrad.addColorStop(1, 'rgba(255,255,255,0.16)');
  ctx.fillStyle = lineGrad;
  ctx.fillRect(M, listLabelY + 22, W - M * 2 - labelW - 28, 1.5);

  // Games with only one or two offers get taller rows so the poster stays balanced.
  const rowH = picks.length >= 3 ? 104 : 138;
  const rowGap = 14;
  let y = listLabelY + 44;
  const rowW = W - M * 2;

  for (const p of picks) {
    ctx.fillStyle = 'rgba(255,255,255,0.045)';
    roundRect(ctx, M, y, rowW, rowH, 20);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    const right = M + rowW - 28;
    const innerLeft = M + 28;

    // title (first line)
    const titleY = rowH > 120 ? y + 52 : y + 42;
    const priceY = rowH > 120 ? y + 100 : y + 78;
    ctx.textAlign = 'right';
    ctx.font = '700 27px "Vazirmatn Bold"';
    ctx.fillStyle = '#F8FAFC';
    const titleMax = rowW - 96;
    ctx.fillText(ellipsize(ctx, p.title, titleMax), right, titleY);

    // price line, right to left: current price, struck-through old price, discount chip
    ctx.font = '700 24px "Vazirmatn Bold"';
    ctx.fillStyle = accent(1);
    const priceTxt = `${faPrice(p.price)} تومان`;
    ctx.fillText(priceTxt, right, priceY);
    let cursor = right - ctx.measureText(priceTxt).width - 18;

    if (p.old) {
      ctx.textAlign = 'right';
      ctx.font = '500 20px "Vazirmatn Medium"';
      const oldTxt = `${faPrice(p.old)} تومان`;
      const w = ctx.measureText(oldTxt).width;
      ctx.fillStyle = 'rgba(148,163,184,0.75)';
      ctx.fillText(oldTxt, cursor, priceY - 2);
      ctx.strokeStyle = 'rgba(148,163,184,0.55)';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(cursor - w, priceY - 8);
      ctx.lineTo(cursor, priceY - 8);
      ctx.stroke();
      cursor -= w + 16;
    }

    const pct = discountPct(p);
    if (pct) {
      ctx.font = '700 18px "Vazirmatn Bold"';
      const chipTxt = `${faNum(pct)}٪`;
      const chipW = ctx.measureText(chipTxt).width + 26;
      ctx.fillStyle = accent(0.16);
      roundRect(ctx, cursor - chipW, priceY - 22, chipW, 30, 15);
      ctx.fill();
      ctx.strokeStyle = accent(0.5);
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.fillStyle = accent(1);
      ctx.textAlign = 'center';
      ctx.fillText(chipTxt, cursor - chipW / 2, priceY);
    }

    y += rowH + rowGap;
  }

  /* ---- trust chips (anchored so 2-item games still balance) ---- */
  const trust = ['تحویل آنی', 'بدون رمز اکانت', 'پشتیبانی ۲۴/۷'];
  const trustY = H - 260;
  ctx.textAlign = 'center';
  ctx.font = '500 20px "Vazirmatn Medium"';
  let cx = W - M;
  for (const label of trust) {
    const w = ctx.measureText(label).width + 42;
    ctx.fillStyle = 'rgba(255,255,255,0.05)';
    roundRect(ctx, cx - w, trustY, w, 44, 22);
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.fillStyle = 'rgba(226,232,240,0.9)';
    ctx.fillText(label, cx - w / 2, trustY + 29);
    cx -= w + 12;
  }

  /* ---- CTA ---- */
  const ctaY = H - 196;
  const ctaW = 640;
  const ctaH = 78;
  ctx.save();
  ctx.shadowColor = accent(0.35);
  ctx.shadowBlur = 40;
  ctx.fillStyle = '#F8FAFC';
  roundRect(ctx, (W - ctaW) / 2, ctaY, ctaW, ctaH, 39);
  ctx.fill();
  ctx.restore();
  ctx.fillStyle = '#0B0B1A';
  ctx.font = '700 28px "Vazirmatn Bold"';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('خرید آنی از سی‌پی شاپ', W / 2 + 26, ctaY + ctaH / 2 - 2);
  ctx.strokeStyle = '#0B0B1A';
  ctx.lineWidth = 2.8;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(232, ctaY + ctaH / 2);
  ctx.lineTo(206, ctaY + ctaH / 2);
  ctx.moveTo(218, ctaY + ctaH / 2 - 9);
  ctx.lineTo(206, ctaY + ctaH / 2);
  ctx.lineTo(218, ctaY + ctaH / 2 + 9);
  ctx.stroke();

  // footer
  ctx.textBaseline = 'alphabetic';
  ctx.font = '500 18px "Vazirmatn Medium"';
  ctx.fillStyle = 'rgba(148,163,184,0.7)';
  ctx.textAlign = 'right';
  ctx.fillText('پرداخت ریالی · درگاه امن بانکی', W - M, H - 54);
  ctx.textAlign = 'left';
  ctx.fillText('CP.SHOP', M, H - 54);

  return canvas;
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const keys = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(GAME_DETAILS);
  for (const key of keys) {
    const canvas = drawPoster(key);
    const file = path.join(OUT_DIR, `${key}.jpg`);
    fs.writeFileSync(file, canvas.toBuffer('image/jpeg', 90));
    console.log(`${key.padEnd(16)} ${Math.round(fs.statSync(file).size / 1024)} KB`);
  }
  console.log(`done: ${keys.length} poster(s)`);
})().catch(err => { console.error(err); process.exit(1); });
