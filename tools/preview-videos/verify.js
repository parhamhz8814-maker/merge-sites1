// Verifies that every game the drawer knows about has a preview clip + poster.
const fs = require('fs');
const path = require('path');

const SITE = path.join(__dirname, '..', '..', 'merged-site');
const html = fs.readFileSync(path.join(SITE, 'index.html'), 'utf8');

function literal(src, marker) {
  const from = src.slice(src.indexOf(marker)).search(/[[{]/) + src.indexOf(marker);
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
  throw new Error('unterminated ' + marker);
}

const keys = Object.keys(literal(html, 'const GAME_DETAILS ='));
const checks = [
  { dir: path.join(SITE, 'assets', 'videos'), ext: ['.mp4', '.jpg'] },
  { dir: path.join(SITE, 'assets', 'posters'), ext: ['.jpg'] },
];
let missing = [];
let bytes = 0;
for (const { dir, ext } of checks) {
  for (const k of keys) {
    for (const e of ext) {
      const f = path.join(dir, k + e);
      if (!fs.existsSync(f)) missing.push(path.relative(SITE, f));
      else bytes += fs.statSync(f).size;
    }
  }
}
console.log(`${keys.length} game keys`);
console.log(`missing: ${missing.length ? missing.join(', ') : 'none'}`);
console.log(`total assets: ${(bytes / 1024 / 1024).toFixed(1)} MB`);
