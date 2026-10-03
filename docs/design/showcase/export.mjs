// Render every board in boards.html to PNG (2× by default). Run capture.mjs first: the boards read its UI captures.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const args = process.argv.slice(2);
const opt = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const out = path.resolve(root, opt('--out', 'output/playwright/orbit-showcase'));
const ui = path.resolve(root, opt('--ui', path.join(path.relative(root, out), 'ui')));
const only = opt('--only', '').split(',').filter(Boolean);
const scale = Number(opt('--scale', '2'));
if (!(await fs.stat(path.join(ui, 'shots.json')).catch(() => null))) throw new Error('先运行 capture.mjs：缺少 ' + path.relative(root, ui) + '/shots.json');
const req = createRequire(import.meta.url);
const runtime = process.env.PLAYWRIGHT_MODULE ? req(process.env.PLAYWRIGHT_MODULE)
  : createRequire(createRequire(path.join(root, 'prototypes/advance/package.json')).resolve('@playwright/test'))('playwright');
const rounded = await fs.readFile('/System/Library/Fonts/SFNSRounded.ttf').catch(() => null);
if (!rounded) console.warn('未找到 SF Pro Rounded：类型码会退回系统无衬线字体');

const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.json': 'application/json' };
const server = http.createServer(async (rq, rs) => {
  try {
    const file = path.resolve(root, '.' + decodeURIComponent(new URL(rq.url, 'http://local').pathname));
    if (path.relative(root, file).startsWith('..')) { rs.writeHead(403).end(); return; }
    rs.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    rs.end(await fs.readFile(file));
  } catch { rs.writeHead(404).end(); }
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await runtime.chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
const errors = [], made = [];
try {
  const page = await browser.newPage({ viewport: { width: 2000, height: 1200 }, deviceScaleFactor: scale, locale: 'zh-CN' });
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('requestfailed', (r) => errors.push('加载失败 ' + r.url()));
  page.on('response', (r) => { if (r.status() >= 400) errors.push(r.status() + ' ' + r.url()); });
  await page.addInitScript((b64) => {
    if (!b64) return;
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const face = new FontFace('SF Pro Rounded', bin.buffer, { weight: '1 1000' });
    face.load().then(() => document.fonts.add(face));
  }, rounded ? rounded.toString('base64') : null);
  await page.goto(base + '/docs/design/showcase/boards.html?ui=/' + path.relative(root, ui).split(path.sep).join('/') + '/', { waitUntil: 'networkidle' });
  await page.waitForFunction(() => window.BOARDS_READY === true, null, { timeout: 30000 });
  if (rounded) await page.waitForFunction(() => document.fonts.check('700 22px "SF Pro Rounded"'));
  const ids = await page.$$eval('.board', (bs) => bs.map((b) => [b.id, b.dataset.title]));
  await fs.mkdir(out, { recursive: true });
  for (const [id, title] of ids) {
    if (only.length && !only.includes(id)) continue;
    const file = path.join(out, 'orbit-' + id + '.png');
    await page.locator('[id="' + id + '"]').screenshot({ path: file, animations: 'disabled' });
    made.push({ id, title, file: path.basename(file) });
  }
  const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
  await fs.writeFile(path.join(out, 'manifest.json'), JSON.stringify({ product: 'Orbit', generator: 'docs/design/showcase/export.mjs', sourceCommit: commit, scale, data: 'Demo 示例数据与示例界面，不代表真实统计', boards: made }, null, 1) + '\n');
} finally {
  await browser.close(); server.close();
}
if (errors.length) { console.error([...new Set(errors)].join('\n')); process.exitCode = 1; }
console.log(made.length + ' 张 → ' + path.relative(root, out));
