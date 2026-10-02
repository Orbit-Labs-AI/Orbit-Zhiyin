// Screenshot every page at several window sizes for visual review (not a test).
//   node tests/shoot.mjs [--html file] [--out dir] [--sizes mac-14,small] [--routes overview,sessions]
//                        [--theme light|dark] [--full] [--hud]
// Writes <out>/<size>-<theme>-<route>.png. Default html is ../tandem-demo.html, default out is ../shots.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const SIZES = { 'mac-14': [1512, 982, 2], 'mac-13': [1280, 800, 2], 'mac-16': [1728, 1117, 2], studio: [2560, 1440, 1], small: [1024, 700, 1], compact: [820, 760, 1] };
const ROUTES = ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment', 'recs', 'library', 'studio'];

const html = path.resolve(opt('--html', path.join(here, '..', 'tandem-demo.html')));
const out = path.resolve(opt('--out', path.join(here, '..', 'shots')));
const sizes = opt('--sizes', 'mac-14').split(',');
const routes = opt('--routes', ROUTES.join(',')).split(',');
const theme = opt('--theme', 'light');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' });
for (const s of sizes) {
  const [width, height, dpr] = SIZES[s];
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: dpr, colorScheme: theme, locale: 'zh-CN' });
  const page = await ctx.newPage();
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  page.on('pageerror', (e) => console.error('[pageerror]', s, e.message));
  await page.goto('file://' + html);
  await page.evaluate((t) => { setTheme(t); }, theme);
  for (const r of routes) {
    // drop notification banners (the welcome banner arrives ~0.8s after load) so shots show the shell, not the toast stack
    await page.evaluate((x) => { go(x); document.querySelector('#main').scrollTop = 0; document.querySelectorAll('.nt').forEach((n) => n.remove()); }, r);
    await page.waitForTimeout(250);
    await page.evaluate(() => document.querySelectorAll('.nt').forEach((n) => n.remove()));
    const file = path.join(out, `${s}-${theme}-${r}.png`);
    if (args.includes('--full')) {
      // Capture the main pane's full scroll height by temporarily growing the viewport.
      const h = await page.evaluate(() => { const m = document.querySelector('#main'); return m.scrollHeight - m.clientHeight; });
      await page.setViewportSize({ width, height: height + Math.min(h, 6000) });
      await page.waitForTimeout(150);
      await page.screenshot({ path: file });
      await page.setViewportSize({ width, height });
    } else {
      await page.screenshot({ path: file });
    }
    console.log(file);
  }
  await ctx.close();
}
await browser.close();
