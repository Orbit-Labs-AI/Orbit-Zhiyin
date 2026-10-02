// Screenshot every page at several window sizes for visual review (not a test).
//   node tools/shoot.mjs [--html file] [--out dir] [--sizes mac-14,small] [--routes overview,sessions]
//                        [--theme light|dark] [--full]
// Writes <out>/<size>-<theme>-<route>.png. Default html is ../tandem-demo.html, default out is ../shots.
// Sizes are the Playwright projects in playwright.config.mjs; routes default to every page the demo defines.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import config from '../playwright.config.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const SIZES = Object.fromEntries(config.projects.map((p) => [p.name, p.use]));

const html = path.resolve(opt('--html', path.join(here, '..', 'tandem-demo.html')));
const out = path.resolve(opt('--out', path.join(here, '..', 'shots')));
const sizes = opt('--sizes', 'mac-14').split(',');
const unknown = sizes.filter((s) => !SIZES[s]);
if (unknown.length) { console.error('unknown size(s): ' + unknown.join(', ') + ' (known: ' + Object.keys(SIZES).join(', ') + ')'); process.exit(1); }
const theme = opt('--theme', 'light');
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
for (const s of sizes) {
  const { viewport, deviceScaleFactor } = SIZES[s];
  const ctx = await browser.newContext({ viewport, deviceScaleFactor, colorScheme: theme, locale: 'zh-CN' });
  const page = await ctx.newPage();
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  page.on('pageerror', (e) => console.error('[pageerror]', s, e.message));
  await page.goto(pathToFileURL(html).href);
  // The welcome notification is posted 800 ms after load (src/js/99-init.js); let it arrive, then clear it.
  await page.waitForTimeout(900);
  await page.evaluate((t) => { setTheme(t); $$('#notes .nt').forEach((n) => n.remove()); }, theme);
  const routes = opt('--routes', null)?.split(',') ?? await page.evaluate(() => ROUTES.map((r) => r[0]));
  for (const r of routes) {
    await page.evaluate((x) => { go(x); const c = document.querySelector('#main .content'); if (c) c.scrollTop = 0; }, r);
    await page.waitForTimeout(700);   // let the page-enter cascade and count-ups settle
    const file = path.join(out, `${s}-${theme}-${r}.png`);
    if (args.includes('--full')) {
      // Capture the content pane's full scroll height by temporarily growing the viewport.
      const h = await page.evaluate(() => { const c = document.querySelector('#main .content'); return c ? c.scrollHeight - c.clientHeight : 0; });
      await page.setViewportSize({ width: viewport.width, height: viewport.height + Math.min(h, 6000) });
      await page.waitForTimeout(150);
      await page.screenshot({ path: file });
      await page.setViewportSize(viewport);
    } else {
      await page.screenshot({ path: file });
    }
    console.log(file);
  }
  await ctx.close();
}
await browser.close();
