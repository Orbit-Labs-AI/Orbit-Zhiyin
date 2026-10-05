// Print the promo's real length without rendering it:
//   node prototypes/advance/promo/tools/duration.mjs [checkout]   ->  "<seconds> s = <beats> beats"
// checkout defaults to the repo this file is in (pass another worktree to measure that one).
import { createRequire } from 'node:module';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), '../../../..'));
const { chromium } = createRequire(path.join(root, 'prototypes/advance/promo/render.mjs'))('@playwright/test');
const server = http.createServer((req, res) => {
  const p = path.join(root, decodeURIComponent(new URL(req.url, 'http://x').pathname));
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  const ext = path.extname(p);
  res.writeHead(200, { 'content-type': { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.json': 'application/json' }[ext] || 'application/octet-stream' });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
await ctx.clock.install({ time: new Date('2026-10-01T15:30:00+08:00') });
await ctx.clock.pauseAt(new Date('2026-10-01T15:30:01+08:00'));
const page = await ctx.newPage();
await page.goto('http://127.0.0.1:' + server.address().port + '/prototypes/advance/promo/promo.html?render');
for (let i = 0; i < 400 && !(await page.evaluate(() => !!window.PROMO && PROMO.ready)); i++) await ctx.clock.runFor(16);
const [d, bpm] = await page.evaluate(() => [PROMO.duration, BPM]);
console.log(`${d.toFixed(3)} s = ${(d * bpm / 60).toFixed(2)} beats${d > 60 ? '  OVER 60 s' : ''}`);
await browser.close(); server.close();
