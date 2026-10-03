// Capture the UI pieces the showcase boards need from the checked-in Orbit prototype (sample data, no backend).
// Static pieces are taken after their entry animation; motion frames freeze the page at fixed times.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const args = process.argv.slice(2);
const opt = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const out = path.resolve(root, opt('--out', 'output/playwright/orbit-showcase/ui'));
const only = opt('--only', '').split(',').filter(Boolean);
const scale = Number(opt('--scale', '2'));
const want = (k) => !only.length || only.includes(k);
const req = createRequire(import.meta.url);
const runtime = process.env.PLAYWRIGHT_MODULE ? req(process.env.PLAYWRIGHT_MODULE)
  : createRequire(createRequire(path.join(root, 'prototypes/advance/package.json')).resolve('@playwright/test'))('playwright');
const ROUNDED = '/System/Library/Fonts/SFNSRounded.ttf';
const rounded = await fs.readFile(ROUNDED).catch(() => null);
if (!rounded) console.warn('未找到 SF Pro Rounded：类型码会退回系统无衬线字体');

const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
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
const errors = [];
const shots = [];

async function openPage(theme, motion = false) {
  const ctx = await browser.newContext({ viewport: { width: 1720, height: 1300 }, deviceScaleFactor: scale, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: motion ? 'no-preference' : 'reduce' });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript((b64) => {
    Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
    document.startViewTransition = undefined;
    try { localStorage.setItem('orbit.guideOff', 'true'); } catch {}
    if (b64) {
      const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const face = new FontFace('SF Pro Rounded', bin.buffer, { weight: '1 1000' });
      face.load().then(() => document.fonts.add(face));
    }
  }, rounded ? rounded.toString('base64') : null);
  await page.goto(base + '/prototypes/advance/orbit-demo.html', { waitUntil: 'networkidle' });
  if (await page.evaluate(() => LV.live)) throw new Error('Expected the standalone sample-data UI.');
  await page.addStyleTag({ content: 'html,body{background:transparent!important} #notes,#tip{display:none!important} *{caret-color:transparent!important}' });
  await page.evaluate((theme) => {
    closeOverlay(); closeModal(); closeDD(); closeSettings();
    S.win = { x: 140, y: 100, w: 1440, h: 1040, zoom: false, full: false };
    S.hud.show = false; S.widgets = false; S.pop = false;
    store.set('guideOff', true); setTheme(theme);
  }, theme);
  if (rounded) await page.waitForFunction(() => document.fonts.check('700 22px "SF Pro Rounded"'));
  return page;
}
const settle = (page) => page.evaluate(async () => {
  await document.fonts.ready;
  for (const a of document.getAnimations()) { const t = a.effect?.getComputedTiming(); if (t && Number.isFinite(t.endTime)) { try { a.finish(); } catch {} } else a.pause(); }
  await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
});
const frame = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
async function shoot(page, sel, name, pad = 0, blur = true) {
  if (blur) await page.evaluate(() => { const a = document.activeElement; if (a && a !== document.body) a.blur(); });
  const loc = page.locator(sel).first();
  if (!(await loc.count())) throw new Error(name + ': no element for ' + sel);
  const b = await loc.boundingBox();
  const vp = page.viewportSize();
  const clip = { x: Math.max(0, b.x - pad), y: Math.max(0, b.y - pad) };
  clip.width = Math.min(vp.width - clip.x, b.width + pad * 2); clip.height = Math.min(vp.height - clip.y, b.height + pad * 2);
  const file = path.join(out, name + '.png');
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, await page.screenshot({ clip, omitBackground: true }));
  shots.push({ name, w: Math.round(clip.width), h: Math.round(clip.height), pad: { l: Math.round(b.x - clip.x), t: Math.round(b.y - clip.y), r: Math.round(clip.x + clip.width - b.x - b.width), b: Math.round(clip.y + clip.height - b.y - b.height) } });
}
// isolate one element: hide everything else so the transparent capture holds only it
const isolate = (page, sel) => page.evaluate((sel) => {
  document.querySelectorAll('.sc-iso').forEach((e) => e.classList.remove('sc-iso'));
  let st = document.getElementById('sc-iso-css');
  if (!st) { st = document.createElement('style'); st.id = 'sc-iso-css'; document.head.appendChild(st); }
  st.textContent = 'html.sc-on body, html.sc-on body *:not(.sc-iso):not(.sc-iso *){visibility:hidden!important} html.sc-on body .sc-iso{visibility:visible!important}';
  const el = document.querySelector(sel); if (!el) return; el.classList.add('sc-iso'); document.documentElement.classList.add('sc-on');
}, sel);
const unisolate = (page) => page.evaluate(() => { document.documentElement.classList.remove('sc-on'); document.querySelectorAll('.sc-iso').forEach((e) => e.classList.remove('sc-iso')); });
async function card(page, title, name) {
  // top-level card in #content whose heading contains `title`
  const idx = await page.evaluate((title) => {
    const cs = Array.from(document.querySelectorAll('#content .card')).filter((e) => !e.parentElement.closest('.card'));
    const i = cs.findIndex((e) => e.textContent.includes(title));
    cs.forEach((e) => delete e.dataset.sc); if (i >= 0) { cs[i].dataset.sc = '1'; cs[i].scrollIntoView({ block: 'center', behavior: 'instant' }); }
    return i;
  }, title);
  if (idx < 0) throw new Error('card not found: ' + title);
  await settle(page);
  await isolate(page, '[data-sc="1"]');
  await shoot(page, '[data-sc="1"]', name, 16);
  await unisolate(page);
}

try {
  // ---- static pieces, light (and dark where a board needs it) ----
  for (const theme of ['light', 'dark']) {
    const page = await openPage(theme);
    const T = (n) => n + '-' + theme;
    // windows: Advance persona, Lite persona, overview (pipeline + edition board)
    for (const r of ['persona', 'l-persona', 'overview', 'recs', 'sessions']) {
      if (theme === 'dark' && !['persona', 'l-persona'].includes(r)) continue;
      await page.evaluate((r) => { S.ed = r.startsWith('l-') ? 'lite' : 'advance'; document.querySelector('#win').dataset.ed = S.ed; go(r); }, r);
      await settle(page);
      await isolate(page, '#win'); await shoot(page, '#win', 'win/' + T(r), 96); await unisolate(page);
    }
    if (theme === 'light') {
      await page.evaluate(() => { S.ed = 'advance'; document.querySelector('#win').dataset.ed = 'advance'; go('persona'); });
      await settle(page);
      await isolate(page, '.edsw'); await shoot(page, '.edsw', 'ctl/edition-switch-advance', 6); await unisolate(page);
      await page.evaluate(() => { S.ed = 'lite'; document.querySelector('#win').dataset.ed = 'lite'; go('l-persona'); });
      await settle(page);
      await isolate(page, '.edsw'); await shoot(page, '.edsw', 'ctl/edition-switch-lite', 6); await unisolate(page);
      await page.evaluate(() => { S.ed = 'advance'; document.querySelector('#win').dataset.ed = 'advance'; go('overview'); });
      await settle(page);
      for (const [t, n] of [['AI 解读', 'ai-read'], ['协作人格', 'persona-card'], ['本周建议', 'week-recs']]) await card(page, t, 'ov/' + n).catch((e) => console.warn(e.message));
      // persona page cards
      await page.evaluate(() => go('persona')); await settle(page);
      for (const [t, n] of [['四个维度', 'axes'], ['优势与盲点', 'strengths'], ['与 Agent 的契合度', 'fit']]) await card(page, t, 'pe/' + n).catch((e) => console.warn(e.message));
      // sessions: trajectory with the playhead part-way
      await page.evaluate(() => go('sessions')); await settle(page);
      await page.evaluate(() => { const s = CUR && CUR.sess ? CUR.sess : null; const box = document.querySelector('#tlBox'); if (typeof tlSeek === 'function') { const T = typeof sessList === 'function' ? traj(sessList().find((x) => x.id === S.sess.id) || sessList()[0]).T : 100; tlSeek(T * 0.58); } });
      await settle(page);
      for (const [t, n] of [['折叠工具泳道', 'trajectory'], ['在 Claude 中继续', 'summary'], ['关键时刻', 'moments']]) await card(page, t, 'se/' + n).catch((e) => console.warn(e.message));
      // recs: list card + detail
      await page.evaluate(() => go('recs')); await settle(page);
      const rc = '#content .rcard[data-id="ro-allow"]';
      await page.evaluate((rc) => document.querySelector(rc).scrollIntoView({ block: 'center', behavior: 'instant' }), rc); await settle(page);
      await isolate(page, rc); await shoot(page, rc, 'rc/card', 16); await unisolate(page);
      // install loop
      await page.evaluate(() => { openInstall('ro-allow'); });
      await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'in/1-preview', 64); await unisolate(page);
      await page.evaluate(() => { INST.t = 0; ACT.instNext({ dataset: {} }); });
      await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'in/2-confirm', 64); await unisolate(page);
      await page.evaluate(() => { INST.t = 0; ACT.instDo(); INST.at = Date.now() - 3000; });
      await page.waitForTimeout(1100); await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'in/3-written', 64); await unisolate(page);
      await page.evaluate(() => { INST.t = 0; ACT.instClose(); });
      await page.waitForTimeout(400); await settle(page);
      await isolate(page, '#toast > *'); await shoot(page, '#toast > *', 'in/3-toast', 44).catch((e) => console.warn(e.message)); await unisolate(page);
      await page.evaluate(() => { const i = S.installed.get('ro-allow'); if (i) i.days = 7; ACT.openRec({ dataset: { id: 'ro-allow', tab: 'track' } }); });
      await settle(page);
      await card(page, '效果追踪', 'in/4-track').catch((e) => console.warn(e.message));
      // desktop surfaces
      await page.evaluate(() => { go('overview'); S.widgets = true; S.wgSize = 'l'; renderWidgets(); });
      await settle(page);
      const nw = await page.locator('#widgets .wg').count();
      for (let i = 0; i < nw; i++) {
        await page.evaluate((i) => { document.querySelectorAll('#widgets .wg').forEach((e, j) => { e.dataset.sc = j === i ? 'w' : ''; }); }, i);
        await isolate(page, '[data-sc="w"]'); await shoot(page, '[data-sc="w"]', 'dk/widget-' + (i + 1), 44); await unisolate(page);
      }
      for (const st of ['running', 'done', 'waiting', 'stuck', 'ctx']) {
        await page.evaluate((st) => { S.widgets = false; renderWidgets(); S.sim = 'running'; S.hudSim = st; S.hud.show = true; S.hud.open = false; renderHud(); }, st);
        await settle(page);
        await isolate(page, '#hud'); await shoot(page, '#hud', 'dk/hud-' + st, 72); await unisolate(page);
      }
      await page.evaluate(() => { S.sim = 'running'; S.hudSim = 'running'; S.hud.open = true; renderHud(); });
      await settle(page);
      await isolate(page, '#hud'); await shoot(page, '#hud', 'dk/hud-open', 80); await unisolate(page);
      await page.evaluate(() => { S.hud.show = false; renderHud(); S.pop = true; renderPop(); });
      await settle(page);
      await isolate(page, '#pop'); await shoot(page, '#pop', 'dk/menubar-panel', 64); await unisolate(page);
      await isolate(page, '#mbar'); await shoot(page, '#mbar', 'dk/menubar', 0).catch((e) => console.warn(e.message)); await unisolate(page);
      await page.evaluate(() => { S.pop = false; render(); });
      // onboarding steps
      for (const step of [0, 1]) {
        await page.evaluate((s) => openOnboarding(s), step); await settle(page);
        await isolate(page, '#overlay .obox'); await shoot(page, '#overlay .obox', 'ob/step-' + step, 96); await unisolate(page);
      }
      await page.evaluate(() => openOnboarding(3)); await settle(page);
      await isolate(page, '#overlay .obox'); await shoot(page, '#overlay .obox', 'ob/final', 96); await unisolate(page);
      await page.evaluate(() => closeOverlay());
      // share cards, one per span
      await page.evaluate(() => { S.shareDark = false; openShare(); }); await settle(page);
      const spans = await page.evaluate(() => shareSpans());
      for (const k of spans) for (const dark of [false, true]) {
        await page.evaluate(([k, dark]) => { S.shareSpan = k; S.shareDark = dark; shareRefresh(); }, [k, dark]);
        await settle(page);
        await isolate(page, '.sharecard'); await shoot(page, '.sharecard', 'sh/card-' + k + (dark ? '-dark' : ''), 0); await unisolate(page);
      }
      await page.evaluate(() => { S.shareDark = false; S.shareSpan = '30'; shareRefresh(); }); await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'sh/dialog', 64); await unisolate(page);
      await page.evaluate(() => closeModal());
      // command palette + ask
      await page.evaluate(() => openPalette()); await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'fl/palette', 64, false); await unisolate(page);
      await page.evaluate(() => { closeModal(); openAsk(); }); await settle(page);
      await isolate(page, '#modal'); await shoot(page, '#modal', 'fl/ask', 64, false); await unisolate(page);
      await page.evaluate(() => closeModal());
    }
    await page.context().close();
    console.log(theme + ': static pieces done');
  }

  // ---- bloom switch frames: 9 月 DIMV → 6 月 SIFV, frozen on the WAAPI clock ----
  if (want('bloom')) {
    const page = await openPage('light', true);
    await page.evaluate(() => { S.ed = 'advance'; go('persona'); });
    await page.waitForTimeout(3500); await settle(page);
    const times = [0, 140, 280, 380, 520, 680, 1000];
    for (const t of times) {
      await page.evaluate(() => { const b = document.querySelector('[data-act="period"][data-v="sep"]') ? null : null; S.persona.period = 'sep'; S.persona.fpType = null; render(); });
      await page.waitForTimeout(1600); await settle(page);
      await page.evaluate(() => { S.persona.period = 'jun'; S.persona.fpType = null; render(); document.getAnimations().forEach((a) => a.pause()); });
      await page.evaluate((t) => { document.getAnimations().forEach((a) => { try { a.currentTime = t; } catch {} }); }, t);
      await frame(page); await frame(page);
      await isolate(page, '#main svg.fp2'); await shoot(page, '#main svg.fp2', 'bm/dial-' + String(t).padStart(4, '0'), 4); await unisolate(page);
      await isolate(page, '[data-hero="code"]'); await shoot(page, '[data-hero="code"]', 'bm/code-' + String(t).padStart(4, '0'), 4).catch((e) => console.warn(e.message)); await unisolate(page);
    }
    await page.context().close();
    console.log('bloom frames done');
  }

  // ---- Genesis frames: first launch, frozen at fixed times (each frame is its own run) ----
  if (want('genesis')) {
    const page = await openPage('light', true);
    for (const t of [500, 1300, 2300, 3000, 4200, 5600]) {
      await page.evaluate(() => { openOnboarding(1); });
      await settle(page);
      await page.evaluate(() => ACT.obStart());
      await page.waitForTimeout(t);
      await page.evaluate(() => {
        const g = GNS; if (g) { g.timers.forEach(clearTimeout); cancelAnimationFrame(g.raf); g.raf = 0; const tick = window.genTick; window.genTick = () => {}; g._tick = tick; }
        document.getAnimations().forEach((a) => a.pause());
      });
      await isolate(page, '#overlay .obox'); await shoot(page, '#overlay .obox', 'gn/t-' + String(t).padStart(4, '0'), 2, false); await unisolate(page);
      await page.evaluate(() => { if (GNS && GNS._tick) window.genTick = GNS._tick; closeOverlay(); });
    }
    await page.context().close();
    console.log('genesis frames done');
  }
} finally {
  await browser.close(); server.close();
}
await fs.writeFile(path.join(out, 'shots.json'), JSON.stringify(shots, null, 1));
if (errors.length) { console.error('page errors:\n' + [...new Set(errors)].join('\n')); process.exitCode = 1; }
console.log(shots.length + ' captures → ' + path.relative(root, out));
