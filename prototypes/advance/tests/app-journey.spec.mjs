// End-to-end user journey of the Orbit App against a REAL gateway (run through scripts/check-app-journey.sh).
// The page is loaded from the gateway's own /app (same origin, as in the WKWebView) with an init script that emulates the
// native host: __TANDEM_TOKEN__/__TANDEM_ENDPOINT__/__ORBIT_NATIVE__ plus a fake webkit.messageHandlers.tandem that records
// every message and answers chooseFolder (synthetic source folders) and save (ok).
// Every step screenshots into $JOURNEY_SHOTS/live/<nn>-<step>.png and logs console/page errors, failed requests (≥400) and
// timings into $JOURNEY_SHOTS/journey-report.json. Steps never abort the journey: a failing step is recorded and the next
// one runs, so a single run lists every defect. The mock test shoots the same routes from file:// into shots/mock/.
// Env: LIVE_GATEWAY, TANDEM_TOKEN (required for the live test), JOURNEY_SRC (fx-src), JOURNEY_SHOTS, JOURNEY_FAKE_HOME.
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '@playwright/test';
import { ADV_FILE } from './live-helpers.mjs';

const GW = process.env.LIVE_GATEWAY ? process.env.LIVE_GATEWAY.replace(/\/+$/, '') : null;
const TOKEN = process.env.TANDEM_TOKEN || '';
const SRC = process.env.JOURNEY_SRC || '';
const SHOTS = process.env.JOURNEY_SHOTS || path.resolve('test-results', 'journey-shots');
const FAKE_HOME = process.env.JOURNEY_FAKE_HOME || '';
const VIEW = { width: 1440, height: 900 };
const FEATURES = ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'];
const SOURCES = ['claude_code', 'codex', 'dsh', 'hermes', 'kimi', 'opencode', 'pi'];
const pad = (n) => String(n).padStart(2, '0');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test.use({ viewport: VIEW, deviceScaleFactor: 1, actionTimeout: 8000, navigationTimeout: 20000 });
test.describe.configure({ mode: 'serial' });

// ---- fake WKWebView host ----
function hostInit([endpoint, token, features, native]) {
  if (endpoint) { window.__TANDEM_ENDPOINT__ = endpoint; window.__TANDEM_TOKEN__ = token; }
  if (!native) return;
  window.__ORBIT_NATIVE__ = { v: 1, app: '0.0.1', platform: 'macos', features };
  window.__nativeMsgs = []; window.__folders = [];
  const fire = (name, detail) => setTimeout(() => window.dispatchEvent(new CustomEvent(name, { detail })), 30);
  window.webkit = { messageHandlers: { tandem: { postMessage(m) {
    const rec = Object.assign({}, m);
    if (rec.base64 != null) { rec.bytes = Math.floor(rec.base64.length * 3 / 4); delete rec.base64; }
    if (rec.text != null) { rec.bytes = new Blob([rec.text]).size; rec.head = String(rec.text).slice(0, 160); delete rec.text; }
    rec.at = Date.now();
    window.__nativeMsgs.push(rec);
    if (m.type === 'chooseFolder') { const p = window.__folders.shift(); fire('tandem:folder', { id: m.id, path: p || null, cancelled: !p }); }
    if (m.type === 'save') fire('tandem:saved', { id: m.id, ok: true, path: '/tmp/orbit-journey/' + (m.filename || 'export') });
  } } } };
}

// ---- step recorder ----
function recorder(page, mode) {
  const dir = path.join(SHOTS, mode); fs.mkdirSync(dir, { recursive: true });
  const rep = { mode, steps: [], console: [], pageErrors: [], failed: [], native: [] };
  let cur = null, n = 0;
  page.on('pageerror', (e) => { const x = { step: cur, msg: String(e && e.stack || e).slice(0, 600) }; rep.pageErrors.push(x); });
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') rep.console.push({ step: cur, type: m.type(), msg: m.text().slice(0, 400), url: (m.location() || {}).url || '' }); });
  page.on('requestfailed', (r) => { if (!/fonts\.(googleapis|gstatic)/.test(r.url())) rep.failed.push({ step: cur, method: r.method(), url: r.url().replace(GW || '', ''), status: 0, body: (r.failure() || {}).errorText || '' }); });
  page.on('response', async (r) => {
    if (r.status() < 400) return;
    const x = { step: cur, method: r.request().method(), url: r.url().replace(GW || '', ''), status: r.status(), body: '' };
    rep.failed.push(x);
    try { x.body = (await r.text()).slice(0, 300); } catch (e) { /* body gone */ }
  });
  async function step(name, fn, o) {
    o = o || {};
    const id = pad(++n) + '-' + name; cur = id;
    const t0 = Date.now(); const s = { id, name, ok: true, ms: 0, notes: [], url: null, shot: null };
    rep.steps.push(s);
    try { await fn(s); } catch (e) { s.ok = false; s.error = String(e && e.message || e).split('\n').slice(0, 4).join(' | ').slice(0, 500); }
    s.ms = Date.now() - t0;
    if (act.blocked && act.blocked.length) { s.notes.push('pointer-blocked (DOM click used): ' + act.blocked.join('; ')); act.blocked = []; }
    if (o.shot !== false) {
      await sleep(o.settle != null ? o.settle : 450);
      const file = path.join(dir, id + '.png');
      try { await page.screenshot({ path: file }); s.shot = path.relative(SHOTS, file); } catch (e) { s.notes.push('screenshot failed: ' + e.message); }
    }
    s.url = page.url().replace(GW || '', '');
    try { s.route = await page.evaluate(() => (typeof S !== 'undefined' ? S.route : null)); } catch (e) { /* page gone */ }
    return s;
  }
  rep.step = step;
  rep.save = async () => {
    try { rep.native = await page.evaluate(() => window.__nativeMsgs || []); } catch (e) { /* closed */ }
    fs.writeFileSync(path.join(SHOTS, 'journey-' + mode + '.json'), JSON.stringify(rep, null, 1));
  };
  return rep;
}

// click the first visible [data-act=name] (optionally matching attrs / text); returns false when there is none
async function act(page, name, o) {
  o = o || {};
  let sel = '[data-act="' + name + '"]';
  Object.keys(o.attr || {}).forEach((k) => { sel += '[' + k + '="' + o.attr[k] + '"]'; });
  let loc = page.locator((o.within ? o.within + ' ' : '') + sel).filter({ visible: true });
  if (o.text) loc = loc.filter({ hasText: o.text });
  const n = await loc.count();
  if (!n) return false;
  const el = loc.nth(Math.min(o.nth || 0, n - 1));
  try { await el.click({ modifiers: o.modifiers, timeout: 5000 }); }
  catch (e) {   // covered / never stable: record it and fall back to a DOM click so the journey goes on
    (act.blocked = act.blocked || []).push(name + ': ' + String(e.message).split('\n')[0]);
    await el.evaluate((x) => x.click());
  }
  if (o.wait !== false) await sleep(o.wait || 300);
  return true;
}
const need = async (page, name, o) => { if (!(await act(page, name, o))) throw new Error('no visible [data-act=' + name + ']' + (o && o.attr ? ' ' + JSON.stringify(o.attr) : '')); };
const ev = (page, fn, arg) => page.evaluate(fn, arg);
const goRoute = (page, r) => page.evaluate((r) => { if (typeof closeOverlay === 'function' && typeof OVL !== 'undefined' && OVL) closeOverlay(); if (typeof closeModal === 'function') closeModal(); go(r); }, r);
const closeAll = (page) => page.evaluate(() => { try { if (OVL) closeOverlay(); } catch (e) { /* none */ } try { closeModal(); } catch (e) { /* none */ } try { closeSettings(); } catch (e) { /* none */ } });
const feedSettled = (page, r, ms) => expect.poll(() => page.evaluate((r) => (LV.live ? LV.feedState(r) : 'ready'), r), { timeout: ms || 20_000 }).not.toBe('pending').catch(() => null);
// 'Gemini CLI' / 'Copilot' are real catalog agent labels: fine on the library page, and on personal-data pages
// only a leak when the synthetic data has no such agent.
const mockLeak = (page) => page.evaluate(() => {
  const t = document.querySelector('#win') ? document.querySelector('#win').innerText : document.body.innerText;
  const route = typeof S !== 'undefined' ? S.route : '';
  const agents = (typeof AG !== 'undefined' ? AG : []).map((a) => [a.id, a.name, a.short].join(' ')).join(' ');
  const catalogLabel = (w) => (w === 'Gemini CLI' || w === 'Copilot') && (route === 'library' || agents.indexOf(w) >= 0);
  return ['confluo', 'latentskill', 'Auto Finance', 'FHGS Website', 'Tweet Card', 'Gemini CLI', 'Copilot', 'yhyfhgs', '欢迎体验 Orbit 交互 Demo'].filter((w) => t.indexOf(w) >= 0 && !catalogLabel(w));
});

// ---- route table shared by live and mock screenshots ----
const ADV_ROUTES = ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment', 'recs', 'library', 'studio'];
const LITE_ROUTES = ['l-home', 'l-persona', 'l-sessions', 'l-recs'];

test('live journey: first run → every route → Lite → surfaces', async ({ page, context }) => {
  test.skip(!GW || !TOKEN, 'needs LIVE_GATEWAY + TANDEM_TOKEN (scripts/check-app-journey.sh)');
  test.setTimeout(20 * 60_000);
  await context.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.addInitScript(hostInit, [GW, TOKEN, FEATURES, true]);
  const R = recorder(page, 'live');
  const step = R.step;
  const index = [];
  const mark = (s, key) => { index.push({ step: key || s.name, id: s.id, live: s.shot, url: s.url, route: s.route }); };

  // ---------- first run ----------
  mark(await step('first-run-onboarding', async (s) => {
    await page.goto(GW + '/app');
    await expect(page.locator('#main')).not.toBeEmpty();
    await expect.poll(() => ev(page, () => LV.state), { timeout: 15_000 }).not.toBe('connecting');
    await expect.poll(() => ev(page, () => OVL), { timeout: 10_000 }).toBe('ob');
    const leak = await mockLeak(page); if (leak.length) s.notes.push('mock text on empty home: ' + leak.join(', '));
    s.notes.push('state=' + await ev(page, () => LV.state) + ' AG=' + await ev(page, () => AG.map((a) => a.id).join(',')) + ' PJ=' + await ev(page, () => PJ.length));
  }, { settle: 1200 }));
  mark(await step('onboarding-discovery', async (s) => {
    await need(page, 'obNext');
    await expect.poll(() => ev(page, () => OB && OB.live && OB.live.state), { timeout: 10_000 }).toBe('ready');
    s.notes.push('discovered=' + await ev(page, () => OB.live.sources.length));
  }));
  mark(await step('onboarding-add-folders', async (s) => {
    const ids = [];
    for (const ag of SOURCES) {
      const dir = path.join(SRC, ag); if (!fs.existsSync(dir)) { s.notes.push('missing ' + dir); continue; }
      await ev(page, (p) => window.__folders.push(p), dir);
      await page.locator('select.ob-agent').selectOption(ag).catch(() => s.notes.push('agent option missing: ' + ag));
      await need(page, 'obAddFolder');
      await expect.poll(() => ev(page, () => OB.live.adding), { timeout: 10_000 }).toBeFalsy();
      const err = await ev(page, () => OB.live.err);
      if (err) s.notes.push(ag + ': ' + err);
      ids.push(ag);
    }
    const n = await ev(page, () => ({ sources: OB.live.sources.map((x) => x.agent + ':' + x.status + ':' + (OB.live.sel.has(x.id) ? 'on' : 'off')), src: Array.from(OB.src) }));
    s.notes.push(JSON.stringify(n));
    const folderMsgs = await ev(page, () => window.__nativeMsgs.filter((m) => m.type === 'chooseFolder').length);
    if (folderMsgs !== ids.length) throw new Error('chooseFolder posted ' + folderMsgs + ' times for ' + ids.length + ' adds');
  }));
  // auto-detect from path only (agent = auto): pi's folder name has no dot
  await step('onboarding-add-folder-autodetect', async (s) => {
    await ev(page, (p) => window.__folders.push(p), path.join(SRC, 'pi'));
    await page.locator('select.ob-agent').selectOption('auto').catch(() => null);
    await need(page, 'obAddFolder');
    await expect.poll(() => ev(page, () => OB.live.adding), { timeout: 10_000 }).toBeFalsy();
    const err = await ev(page, () => OB.live.err); if (err) s.notes.push('auto agent: ' + err);
  });
  mark(await step('onboarding-import-progress', async (s) => {
    await ev(page, () => { OB.live.err = null; });
    await need(page, 'obStart', { wait: 1500 });
    const st = await ev(page, () => ({ err: OB.live.err, stages: (OB.live.stages || []).map((x) => x.id + ':' + x.status + (x.note ? '(' + x.note + ')' : '')), job: OB.live.job }));
    s.notes.push(JSON.stringify(st));
    if (st.err) throw new Error(st.err);
  }, { settle: 200 }));
  const tImp = Date.now();
  mark(await step('onboarding-stages-mid', async (s) => {
    await expect.poll(() => ev(page, () => (OB && OB.live && OB.live.stages || []).some((x) => x.id === 'stats' && x.status !== 'pending') || OVL !== 'ob' || (OB && OB.step >= 2)), { timeout: 240_000, intervals: [500] }).toBeTruthy();
    s.notes.push(JSON.stringify(await ev(page, () => OB && OB.live && (OB.live.stages || []).map((x) => x.id + ':' + x.status + (x.note ? '(' + x.note + ')' : '')))));
  }, { settle: 100 }));
  mark(await step('genesis-reveal', async (s) => {
    await expect.poll(() => ev(page, () => OB && OB.step >= 2), { timeout: 240_000, intervals: [500] }).toBeTruthy();
    s.notes.push('import→genesis ' + Math.round((Date.now() - tImp) / 1000) + 's; reveal=' + JSON.stringify(await ev(page, () => OB.revealP && OB.revealP.p)));
    await sleep(2500);
  }, { settle: 0 }));
  mark(await step('genesis-final', async () => {
    await expect.poll(() => ev(page, () => { const b = document.querySelector('[data-act="obDone"]'); return !!(b && b.offsetParent && getComputedStyle(b).visibility !== 'hidden' && +getComputedStyle(b).opacity > 0.5); }), { timeout: 90_000 }).toBeTruthy();
  }));
  mark(await step('land-a1', async (s) => {
    await need(page, 'obDone', { wait: 1500 });
    await expect.poll(() => ev(page, () => OVL), { timeout: 10_000 }).toBeFalsy();
    s.notes.push('route=' + await ev(page, () => S.route) + ' state=' + await ev(page, () => LV.state) + ' ALL=' + await ev(page, () => ALL.length) + ' AG=' + await ev(page, () => AG.map((a) => a.id + ':' + a.all).join(',')) + ' PJ=' + await ev(page, () => PJ.length));
    const st = await (await page.request.get(GW + '/v1/app/settings', { headers: { authorization: 'Bearer ' + TOKEN } }).catch(() => null));
    if (st) s.notes.push('settings ' + st.status() + ' ' + (await st.text()).slice(0, 200));
    if (await ev(page, () => ALL.length) === 0) throw new Error('landed on A1 with an empty spine');
  }, { settle: 1500 }), 'overview');

  // ---------- A1 ----------
  for (const r of ['7', '30', '90', 'all']) {
    mark(await step('a1-range-' + r, async (s) => {
      if (await ev(page, () => S.route) !== 'overview') await goRoute(page, 'overview');   // 查看完整画像 lands on persona
      await need(page, 'range', { attr: { 'data-v': r === 'all' ? '0' : r } });   // 全部 is data-v="0"
      await feedSettled(page, 'overview');
      s.notes.push('S.range=' + await ev(page, () => S.range) + ' tiles=' + await ev(page, () => Array.from(document.querySelectorAll('#main .kpi .v, #main .tile .v, #main [class*=kpi] .mono')).slice(0, 5).map((e) => e.textContent.trim()).join('|')));
    }));
  }
  mark(await step('a1-agent-filter', async (s) => {
    const first = await ev(page, () => AG[0] && AG[0].id);
    await need(page, 'agentToggle', { attr: { 'data-a': first } });
    s.notes.push('agents=' + await ev(page, () => Array.from(S.agents).join(',')) + ' n=' + await ev(page, () => sel().length));
    await act(page, 'agentMenu');
    await sleep(300);
  }));
  await step('a1-agent-filter-reset', async () => { await closeAll(page); await ev(page, () => { S.agents = new Set(AG.map((a) => a.id)); render(); }); }, { shot: false });
  mark(await step('a1-ai-insight-regen', async (s) => { if (!(await act(page, 'regen', { wait: 1500 }))) s.notes.push('no regen button'); }));
  mark(await step('a1-heat-table-view', async (s) => {
    if (!(await act(page, 'heatMode'))) s.notes.push('no heatMode');
    if (!(await act(page, 'view'))) s.notes.push('no view toggle');
  }));

  // ---------- A2 ----------
  mark(await step('a2-persona', async () => { await goRoute(page, 'persona'); await feedSettled(page, 'persona'); }, { settle: 1500 }), 'persona');
  for (const p of ['30', '90', 'all']) {
    mark(await step('a2-period-' + p, async (s) => { if (!(await act(page, 'period', { attr: { 'data-v': p } }))) s.notes.push('no period ' + p); await feedSettled(page, 'persona'); }));
  }
  mark(await step('a2-compass-axis', async (s) => { if (!(await act(page, 'axisJump'))) s.notes.push('no axisJump'); }));
  mark(await step('a2-reveal', async (s) => {
    await goRoute(page, 'persona');
    if (!(await act(page, 'reveal', { wait: 3000 }))) throw new Error('no reveal button');
    s.notes.push('OVL=' + await ev(page, () => OVL));
  }, { settle: 0 }));
  await step('a2-reveal-close', async () => { await page.keyboard.press('Escape'); await sleep(300); await page.keyboard.press('Escape'); await closeAll(page); }, { shot: false });

  // ---------- A3 ----------
  mark(await step('a3-sessions', async () => { await goRoute(page, 'sessions'); await feedSettled(page, 'sessions'); }, { settle: 1500 }), 'sessions');
  mark(await step('a3-search', async (s) => {
    const q = page.locator('#sessQ');
    const t = await ev(page, () => { const x = ALL[ALL.length - 1]; return x ? String(x.title).split(/\s+/)[0].slice(0, 6) : 'test'; });
    await q.fill(t); await sleep(1500);
    s.notes.push('q=' + t + ' rows=' + await ev(page, () => document.querySelectorAll('#main [data-act="pickSession"]').length));
    await q.fill(''); await sleep(600);
  }));
  mark(await step('a3-select-session', async (s) => {
    await need(page, 'pickSession', { nth: 2, wait: 1500 });
    s.notes.push('sel=' + await ev(page, () => S.sess.sel));
  }));
  mark(await step('a3-play', async (s) => {
    if (!(await act(page, 'playToggle', { wait: 2000 }))) s.notes.push('no playToggle');
    await act(page, 'playToggle', { wait: 200 });
  }));
  mark(await step('a3-scrub', async (s) => {
    const lane = page.locator('#main .tl-lanes, #main [class*=lane]').first();
    if (await lane.count()) { const b = await lane.boundingBox(); if (b) await page.mouse.click(b.x + b.width * 0.6, b.y + b.height / 2); }
    else s.notes.push('no lane element');
    if (!(await act(page, 'tlStep'))) s.notes.push('no tlStep');
  }));
  mark(await step('a3-compare', async (s) => { if (!(await act(page, 'sessMode', { attr: { 'data-v': 'compare' }, wait: 2000 })) && !(await act(page, 'sessMode', { wait: 2000 }))) s.notes.push('no sessMode'); s.notes.push('mode=' + await ev(page, () => S.sess.mode) + ' cmp=' + await ev(page, () => S.sess.cmp)); }));
  await step('a3-compare-exit', async () => { await ev(page, () => { S.sess.mode = 'detail'; render(); }); }, { shot: false });
  mark(await step('a3-messages', async (s) => {
    if (!(await act(page, 'lvsMsgs', { wait: 2500 }))) s.notes.push('no lvsMsgs button');
  }));
  await step('a3-messages-close', async () => { await page.keyboard.press('Escape'); await closeAll(page); await goRoute(page, 'sessions'); }, { shot: false });
  mark(await step('a3-more-menu', async (s) => { if (!(await act(page, 'sessMore'))) s.notes.push('no sessMore'); }));
  mark(await step('a3-exclude', async (s) => {
    const before = await ev(page, () => ({ sel: S.sess.sel, n: ALL.length }));
    const it = page.locator('#dd button, .tmore-pop button').filter({ hasText: /排除|不计入/ }).filter({ visible: true });
    if (await it.count()) { await it.first().click(); await sleep(2500); } else throw new Error('no 排除 item in the session menu');
    const after = await ev(page, () => ({ n: ALL.length, ex: (LV.excluded || []).length }));
    s.notes.push(JSON.stringify({ before, after }));
    R.excluded = before.sel;
  }));
  mark(await step('a3-restore', async (s) => {
    const btn = page.locator('[data-act="setRestoreEx"], button').filter({ hasText: /恢复|撤销/ }).filter({ visible: true });
    if (await btn.count()) { await btn.first().click(); await sleep(2500); } else s.notes.push('no restore control on the page');
    s.notes.push('ALL=' + await ev(page, () => ALL.length) + ' excluded=' + await ev(page, () => (LV.excluded || []).length));
  }));
  mark(await step('a3-resume', async (s) => {
    await closeAll(page); await goRoute(page, 'sessions');
    if (!(await act(page, 'resume', { wait: 1500 }))) s.notes.push('no resume');
    s.notes.push('modal=' + await ev(page, () => (document.querySelector('#modal:not([hidden])') || {}).innerText || '').then((t) => String(t).slice(0, 200)));
  }));
  await step('a3-resume-close', async () => { await closeAll(page); }, { shot: false });
  mark(await step('a3-locate-log', async (s) => {
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    if (!(await act(page, 'tlOpenLog', { wait: 1500 }))) {
      await act(page, 'sessMore'); const it = page.locator('#dd button, .tmore-pop button').filter({ hasText: /定位|日志/ }).filter({ visible: true });
      if (await it.count()) { await it.first().click(); await sleep(1500); } else throw new Error('no locate-log control');
    }
    const msgs = await ev(page, (n0) => window.__nativeMsgs.slice(n0), n0);
    s.notes.push(JSON.stringify(msgs));
    if (!msgs.some((m) => m.type === 'reveal' && m.path)) throw new Error('no reveal message with a path');
  }));

  // ---------- A4 ----------
  mark(await step('a4-tools', async () => { await goRoute(page, 'tools'); await feedSettled(page, 'tools'); }, { settle: 1500 }), 'tools');
  mark(await step('a4-sort', async (s) => { if (!(await act(page, 'sortTools'))) s.notes.push('no sortTools'); }));
  mark(await step('a4-drill-calls', async (s) => {
    if (!(await act(page, 'toggleTool', { wait: 2500 }))) s.notes.push('no toggleTool');
  }));
  mark(await step('a4-matrix', async (s) => {
    const m = page.locator('#main [class*=matrix], #main [class*=mx]').first();
    if (await m.count()) await m.scrollIntoViewIfNeeded(); else s.notes.push('no matrix element');
  }));
  mark(await step('a4-failures', async (s) => { if (!(await act(page, 'failOnly'))) s.notes.push('no failOnly'); if (!(await act(page, 'openFail', { wait: 1200 }))) s.notes.push('no openFail'); }));
  await step('a4-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- A5 ----------
  mark(await step('a5-projects', async () => { await goRoute(page, 'projects'); await feedSettled(page, 'projects'); }, { settle: 1500 }), 'projects');
  mark(await step('a5-select', async (s) => { if (!(await act(page, 'pickProject', { nth: 1, wait: 1500 }))) s.notes.push('no pickProject'); }));
  mark(await step('a5-compare', async (s) => { if (!(await act(page, 'projCompare', { wait: 1500 }))) s.notes.push('no projCompare'); }));
  mark(await step('a5-finder', async (s) => {
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    if (!(await act(page, 'finder', { wait: 800 }))) s.notes.push('no finder');
    s.notes.push(JSON.stringify(await ev(page, (n0) => window.__nativeMsgs.slice(n0), n0)));
  }));

  // ---------- A6 ----------
  mark(await step('a6-sentiment', async () => { await goRoute(page, 'sentiment'); await feedSettled(page, 'sentiment'); }, { settle: 1500 }), 'sentiment');
  mark(await step('a6-mood-view', async (s) => { if (!(await act(page, 'moodView'))) s.notes.push('no moodView'); }));
  mark(await step('a6-friction', async (s) => { if (!(await act(page, 'fricGo', { wait: 1200 }))) s.notes.push('no fricGo'); s.notes.push('route=' + await ev(page, () => S.route)); }));
  mark(await step('a6-topics', async (s) => { await goRoute(page, 'sentiment'); if (!(await act(page, 'topicSet', { wait: 1200 }))) s.notes.push('no topicSet'); }));
  await step('a6-reset', async () => { await ev(page, () => { if (typeof ACT.clearFilter === 'function') { S.topic = null; } render(); }); }, { shot: false });

  // ---------- A7 recs + install ----------
  mark(await step('a7-recs', async (s) => {
    await goRoute(page, 'recs'); await feedSettled(page, 'recs', 30_000);
    s.notes.push('cards=' + await ev(page, () => document.querySelectorAll('#main [data-act="selRec"]').length));
  }, { settle: 1500 }), 'recs');
  mark(await step('a7-recalc', async (s) => {
    if (!(await act(page, 'recalc', { wait: 4000 }))) s.notes.push('no recalc');
    await feedSettled(page, 'recs', 30_000);
    s.notes.push('cards=' + await ev(page, () => document.querySelectorAll('#main [data-act="selRec"]').length));
  }));
  mark(await step('a7-open-detail', async (s) => { if (!(await act(page, 'selRec', { wait: 1500 }))) throw new Error('no rec card'); s.notes.push('sel=' + await ev(page, () => S.recs.sel)); }));
  mark(await step('a7-label-useful', async (s) => {
    const b = page.locator('#main button').filter({ hasText: /有用/ }).filter({ visible: true });
    if (await b.count()) { await b.first().click(); await sleep(800); } else if (!(await act(page, 'keepRec'))) s.notes.push('no 有用 / keepRec');
  }));
  mark(await step('a7-not-interested', async (s) => {
    if (!(await act(page, 'dismissRec', { wait: 1200 }))) s.notes.push('no dismissRec');
    if (!(await act(page, 'restoreRecs', { wait: 1200 }))) s.notes.push('no restoreRecs');
  }));
  const installs = [];
  page.on('response', async (r) => {
    if (!/\/v1\/install\//.test(r.url()) || r.request().method() === 'GET') return;
    try { installs.push({ url: r.url().replace(GW, ''), status: r.status(), body: (await r.text()).slice(0, 4000) }); } catch (e) { /* gone */ }
  });
  mark(await step('a7-install-preview', async (s) => {
    await goRoute(page, 'recs');
    if (!(await act(page, 'install', { wait: 2500 }))) throw new Error('no install button on recs');
    s.notes.push('modal=' + (await ev(page, () => (document.querySelector('#modal:not([hidden]) .mh, #modal:not([hidden]) h2') || {}).textContent || null)));
    for (let i = 0; i < 3 && await act(page, 'instNext', { wait: 1500 }); i++);
  }));
  mark(await step('a7-install-apply', async (s) => {
    if (!(await act(page, 'instDo', { wait: 4000 }))) throw new Error('no instDo');
    s.notes.push(JSON.stringify(installs.map((x) => x.url + ' ' + x.status)));
  }));
  await step('a7-install-paths', async (s) => {
    const bad = [];
    installs.forEach((x) => { (x.body.match(/"(\/[^"]+)"/g) || []).map((p) => p.slice(1, -1)).filter((p) => /^\/(Users|home|private|var|tmp)\//.test(p)).forEach((p) => { if (!FAKE_HOME || p.indexOf(FAKE_HOME) !== 0 && p.indexOf(fs.realpathSync(FAKE_HOME)) !== 0) bad.push(x.url + ' → ' + p); }); });
    s.notes.push('fake home ' + FAKE_HOME);
    if (bad.length) throw new Error('install paths outside the redirected HOME: ' + bad.slice(0, 5).join('; '));
    if (FAKE_HOME) s.notes.push('fake home files: ' + walk(FAKE_HOME).slice(0, 20).join(', '));
  }, { shot: false });
  mark(await step('a7-install-revert', async (s) => {
    if (!(await act(page, 'instUndo', { wait: 3000 }))) {
      await closeAll(page);
      if (!(await act(page, 'uninstall', { wait: 2500 })) && !(await act(page, 'doUninstall', { wait: 2500 }))) s.notes.push('no revert control');
      await act(page, 'doUninstall', { wait: 2500 });
    }
    s.notes.push(JSON.stringify(installs.slice(-3).map((x) => x.url + ' ' + x.status)));
  }));
  await step('a7-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- A8 ----------
  mark(await step('a8-library', async () => { await goRoute(page, 'library'); await feedSettled(page, 'library', 30_000); }, { settle: 1500 }), 'library');
  mark(await step('a8-search', async (s) => {
    const q = page.locator('#libQ'); if (!(await q.count())) throw new Error('no #libQ');
    await q.fill('git'); await sleep(1500);
    s.notes.push('items=' + await ev(page, () => document.querySelectorAll('#main [data-act="getLib"]').length));
  }));
  mark(await step('a8-facets', async (s) => { await page.locator('#libQ').fill(''); if (!(await act(page, 'libKind', { nth: 1, wait: 1200 }))) s.notes.push('no libKind'); if (!(await act(page, 'libSort'))) s.notes.push('no libSort'); }));
  mark(await step('a8-detail', async (s) => {
    const card = page.locator('#main [data-act="getLib"], #main [data-act="libTab"]').filter({ visible: true });
    if (!(await card.count())) throw new Error('no library item');
    await card.first().click(); await sleep(1500);
  }));
  mark(await step('a8-install', async (s) => {
    for (let i = 0; i < 3 && await act(page, 'instNext', { wait: 1200 }); i++);
    if (!(await act(page, 'instDo', { wait: 3000 }))) s.notes.push('no instDo from library');
  }));
  await step('a8-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- A9 + ask ----------
  mark(await step('a9-studio', async () => { await goRoute(page, 'studio'); await feedSettled(page, 'studio'); }, { settle: 1500 }), 'studio');
  mark(await step('a9-preview', async (s) => {
    const g = page.locator('[data-in="studioGoal"]').filter({ visible: true });
    if (await g.count()) await g.first().fill('给我的仓库写一个提交前检查技能');
    if (!(await act(page, 'ctxPreview', { wait: 2500 }))) s.notes.push('no ctxPreview');
    s.notes.push('engine=' + await ev(page, () => S.engine) + ' (not running studioStart: would call a local AI engine)');
  }));
  await step('a9-close', async () => { await closeAll(page); }, { shot: false });
  mark(await step('ask-presets', async (s) => {
    await goRoute(page, 'overview');
    if (!(await act(page, 'ask', { wait: 1500 }))) throw new Error('no ask button');
    s.notes.push('presets=' + await ev(page, () => document.querySelectorAll('[data-act="askPick"]').length) + ' (not sending: would call a local AI engine)');
  }));
  await step('ask-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- palette ----------
  mark(await step('palette-search', async (s) => {
    await page.keyboard.press('Meta+k'); await sleep(400);
    const q = page.locator('[data-in="palQ"]'); if (!(await q.count())) throw new Error('palette did not open on ⌘K');
    const t = await ev(page, () => (ALL[ALL.length - 1] || {}).title || 'tools');
    await q.fill(String(t).slice(0, 8)); await sleep(1500);
    s.notes.push('items=' + await ev(page, () => (PAL && PAL.items || []).length));
  }));
  mark(await step('palette-navigate', async (s) => {
    await page.locator('[data-in="palQ"]').fill('工具调用'); await sleep(800);
    await page.keyboard.press('Enter'); await sleep(800);
    s.notes.push('route=' + await ev(page, () => S.route));
    if (await ev(page, () => S.route) !== 'tools') throw new Error('palette Enter on 工具调用 did not navigate to tools');
  }));

  // ---------- settings ----------
  const TABS = ['general', 'sources', 'privacy', 'analysis', 'notify', 'about'];
  // one real enabled write control per tab; each click must send the expected non-GET request
  const SET_WRITES = {
    general: { sel: '#set [data-act="setRange"]:not(.on):not([disabled])', method: 'PATCH', path: /\/v1\/app\/settings(\?|$)/ },
    sources: { sel: '#set [data-act="setPause"]:not([disabled])', method: 'POST', path: /\/v1\/platform\/collection\/(pause|resume)(\?|$)/, revert: true },
    privacy: { sel: '#set [data-act="setRule"]:not([disabled])', method: 'PUT', path: /\/v1\/privacy\/rules(\?|$)/, revert: true },
    analysis: { sel: '#set [data-act="setWeekly"]:not([disabled])', method: 'PATCH', path: /\/v1\/app\/settings(\?|$)/, revert: true },
    notify: { sel: '#set [data-act="setNotifPreset"][data-v="all"]:not([disabled])', method: 'PUT', path: /\/v1\/notifications\/policy(\?|$)/ },
    about: { sel: '#set [data-act="tlsTel"]:not([disabled])', method: 'PUT', path: /\/v1\/platform\/telemetry(\?|$)/, revert: true },
  };
  const settingsWrite = async (page, w) => {
    const loc = page.locator(w.sel).filter({ visible: true });
    if (!(await loc.count())) throw new Error('no enabled write control ' + w.sel);
    const reqP = page.waitForRequest((q) => q.method() === w.method && w.path.test(q.url().split('#')[0]), { timeout: 8000 });
    const respP = reqP.then((q) => q.response());
    await loc.first().click({ timeout: 5000 });
    const q = await reqP.catch(() => null);
    if (!q) throw new Error('clicking ' + w.sel + ' sent no ' + w.method + ' ' + w.path);
    const r = await respP.catch(() => null);
    if (!r || r.status() >= 400) throw new Error(w.method + ' ' + q.url() + ' → ' + (r ? r.status() : 'no response'));
    await sleep(600);
    return [w.method + ' ' + q.url().replace(/^https?:\/\/[^/]+/, '') + ' ' + r.status() + ' ' + (q.postData() || '').slice(0, 120)];
  };
  for (const t of TABS) {
    mark(await step('settings-' + t, async (s) => {
      await ev(page, (t) => { openSettings(t); }, t); await sleep(1200);
      const txt = await ev(page, () => (document.querySelector('#set') || {}).innerText || '');
      s.notes.push(String(txt).replace(/\s+/g, ' ').slice(0, 240));
      if (t === 'about' && !/0\.0\.1/.test(txt)) throw new Error('about tab does not show 0.0.1');
    }));
    await step('settings-' + t + '-write', async (s) => {
      const n0 = R.failed.length;
      const w = SET_WRITES[t];
      await expect.poll(() => page.locator(w.sel).filter({ visible: true }).count(), { timeout: 8000 }).toBeGreaterThan(0).catch(() => null);
      const reqs = await settingsWrite(page, w);
      s.notes.push(t + ' writes: ' + reqs.join(' | '));
      if (w.revert) {
        const back = await settingsWrite(page, w); s.notes.push('revert: ' + back.join(' | '));
        if (back[0].replace(/ \d{3} /, ' ') === reqs[0].replace(/ \d{3} /, ' ')) throw new Error(t + ' toggle sent the same write twice: ' + back[0]);
      }
      await sleep(800);
      const bad = R.failed.slice(n0);
      s.notes.push('new failures: ' + JSON.stringify(bad.map((x) => x.method + ' ' + x.url + ' ' + x.status)));
      if (bad.some((x) => w.path.test(x.url))) throw new Error(t + ' write failed: ' + JSON.stringify(bad));
    }, { shot: t !== 'about' });
  }
  await step('settings-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- exports ----------
  const saves = async (n0) => ev(page, (n0) => window.__nativeMsgs.slice(n0).filter((m) => m.type === 'save'), n0);
  mark(await step('export-report', async (s) => {
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    await page.keyboard.press('Meta+Shift+e'); await sleep(1500);
    if (!(await act(page, 'repSave', { wait: 2500 }))) {
      const b = page.locator('#modal button').filter({ hasText: /保存|导出|下载/ }).filter({ visible: true });
      if (await b.count()) { await b.last().click(); await sleep(2500); } else throw new Error('no report save button');
    }
    const sv = await saves(n0); s.notes.push(JSON.stringify(sv));
    if (!sv.length || !sv[0].filename || !sv[0].mime || !sv[0].bytes) throw new Error('report save message missing filename/mime/bytes');
  }));
  await step('export-report-close', async () => { await closeAll(page); }, { shot: false });
  mark(await step('export-csv', async (s) => {
    await goRoute(page, 'tools'); await feedSettled(page, 'tools');
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    if (!(await act(page, 'csv', { wait: 1500 }))) throw new Error('no csv button on tools');
    if (!(await act(page, 'csvSave', { wait: 2500 }))) { const b = page.locator('#modal button').filter({ hasText: /保存|导出|下载/ }).filter({ visible: true }); if (await b.count()) { await b.last().click(); await sleep(2500); } }
    const sv = await saves(n0); s.notes.push(JSON.stringify(sv));
    if (!sv.length || !sv[0].bytes) throw new Error('csv save message missing or empty');
  }));
  await step('export-csv-close', async () => { await closeAll(page); }, { shot: false });
  mark(await step('export-share-card', async (s) => {
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    await page.keyboard.press('Meta+Shift+s'); await sleep(1500);
    if (!(await act(page, 'shareSave', { wait: 3500 }))) throw new Error('no shareSave');
    const sv = await saves(n0); s.notes.push(JSON.stringify(sv));
    if (!sv.length || sv[0].mime !== 'image/png' || !sv[0].bytes) throw new Error('share card save missing / not png');
  }));
  await step('export-share-close', async () => { await closeAll(page); }, { shot: false });

  // ---------- keyboard + about ----------
  mark(await step('keys-sheet', async (s) => { await page.keyboard.press('Escape'); await page.keyboard.press('?'); await sleep(800); s.notes.push('modal=' + await ev(page, () => MODAL_KEY)); }));
  await step('keys-nav', async (s) => {
    await closeAll(page);
    const got = [];
    for (let i = 1; i <= 9; i++) { await page.keyboard.press('Meta+Digit' + i); await sleep(250); got.push(await ev(page, () => S.route)); }
    s.notes.push('⌘1–9 → ' + got.join(','));
    if (new Set(got).size < 9) throw new Error('⌘1–9 did not visit 9 routes: ' + got.join(','));
    await page.keyboard.press('Meta+BracketLeft'); await sleep(300); s.notes.push('⌘[ → ' + await ev(page, () => S.route));
    const n0 = await ev(page, () => window.__nativeMsgs.length);
    await page.keyboard.press('Meta+m'); await sleep(300);
    s.notes.push('⌘M → ' + JSON.stringify(await ev(page, (n0) => window.__nativeMsgs.slice(n0).map((m) => m.type), n0)));
  }, { shot: false });
  mark(await step('about', async (s) => {
    await ev(page, () => openAbout()); await sleep(800);
    const t = await ev(page, () => (document.querySelector('#modal:not([hidden])') || document.querySelector('#set:not([hidden])') || {}).innerText || '');
    s.notes.push(String(t).replace(/\s+/g, ' ').slice(0, 200));
    if (!/0\.0\.1/.test(t)) throw new Error('about does not show 0.0.1');
  }));
  await step('about-close', async () => { await closeAll(page); }, { shot: false });
  await step('native-commands', async (s) => {
    for (const d of [{ cmd: 'route', route: 'projects' }, { cmd: 'palette' }, { cmd: 'settings', tab: 'privacy' }, { cmd: 'refresh' }]) {
      await ev(page, (d) => window.dispatchEvent(new CustomEvent('tandem:command', { detail: d })), d); await sleep(500);
    }
    s.notes.push('route=' + await ev(page, () => S.route));
    await closeAll(page);
  }, { shot: false });

  // ---------- Lite ----------
  await step('lite-switch', async (s) => {
    await goRoute(page, 'overview');
    await need(page, 'edition', { attr: { 'data-v': 'lite' }, wait: 1500 });
    s.notes.push('ed=' + await ev(page, () => S.ed) + ' route=' + await ev(page, () => S.route));
    if (await ev(page, () => S.ed) !== 'lite') throw new Error('edition did not switch to lite');
  }, { shot: false });
  for (const r of LITE_ROUTES) {
    mark(await step('lite-' + r.slice(2), async (s) => {
      await goRoute(page, r); await sleep(1500);
      const leak = await mockLeak(page); if (leak.length) s.notes.push('mock text: ' + leak.join(', '));
      if (await ev(page, () => S.route) !== r) throw new Error('route is ' + await ev(page, () => S.route));
    }, { settle: 800 }), r);
  }
  mark(await step('lite-period', async (s) => { if (!(await act(page, 'litePeriod', { nth: 1 }))) s.notes.push('no litePeriod'); }));
  mark(await step('lite-session', async (s) => { await goRoute(page, 'l-sessions'); if (!(await act(page, 'liteSess', { wait: 1500 }))) s.notes.push('no liteSess'); }));
  await step('lite-back-to-advance', async () => { await closeAll(page); await ev(page, () => edSet('advance')); await sleep(800); }, { shot: false });

  // ---------- leaks on every Advance route ----------
  await step('advance-mock-leak-scan', async (s) => {
    const out = {};
    for (const r of ADV_ROUTES) { await goRoute(page, r); await sleep(1200); const l = await mockLeak(page); if (l.length) out[r] = l; }
    s.notes.push(JSON.stringify(out));
    if (Object.keys(out).length) throw new Error('mock/personal demo text in live: ' + JSON.stringify(out));
  }, { shot: false });

  // ---------- surfaces ----------
  for (const sf of ['panel', 'hud', 'widgets']) {
    mark(await step('surface-' + sf, async (s) => {
      await page.goto(GW + '/app?surface=' + sf); await sleep(3000);
      const st = await ev(page, () => ({ body: document.body.className, ovl: typeof OVL !== 'undefined' ? OVL : null, txt: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200) }));
      s.notes.push(JSON.stringify(st));
      if (st.ovl) throw new Error('surface ' + sf + ' opened overlay ' + st.ovl);
    }, { settle: 600 }), 'surface-' + sf);
  }

  await R.save();
  fs.writeFileSync(path.join(SHOTS, 'index-live.json'), JSON.stringify(index, null, 1));
  const bad = R.steps.filter((x) => !x.ok);
  console.log('\njourney: ' + R.steps.length + ' steps, ' + bad.length + ' failed, ' + R.pageErrors.length + ' page errors, ' + R.failed.length + ' failed requests');
  bad.forEach((x) => console.log('  FAIL ' + x.id + ': ' + x.error));
});

function walk(dir, base) {
  base = base || dir; const out = [];
  let ents = []; try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return out; }
  ents.forEach((e) => { const p = path.join(dir, e.name); if (e.isDirectory()) out.push(...walk(p, base)); else out.push(path.relative(base, p)); });
  return out;
}

// ---------- mock mode: same routes from file:// (unchanged prototype) for visual comparison ----------
test('mock screenshots of the same routes', async ({ page }) => {
  test.setTimeout(5 * 60_000);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  const R = recorder(page, 'mock'); const step = R.step;
  const index = [];
  const mark = (s, key) => index.push({ step: key || s.name, id: s.id, mock: s.shot, url: 'file://' + ADV_FILE + (s.route ? '#' + s.route : '') });
  await page.goto('file://' + ADV_FILE + '#overview'); await sleep(1500);
  await ev(page, () => { document.querySelectorAll('.note').forEach((n) => n.remove()); });
  mark(await step('first-run-onboarding', async () => { await ev(page, () => openOnboarding(0)); }, { settle: 800 }));
  mark(await step('onboarding-discovery', async () => { await need(page, 'obNext'); }));
  await step('close-ob', async () => { await closeAll(page); }, { shot: false });
  const shots = [['overview', 'overview'], ['persona', 'persona'], ['sessions', 'sessions'], ['tools', 'tools'], ['projects', 'projects'], ['sentiment', 'sentiment'], ['recs', 'recs'], ['library', 'library'], ['studio', 'studio']];
  for (const [k, r] of shots) mark(await step(k, async () => { await goRoute(page, r); await sleep(900); }, { settle: 800 }), k);
  for (const t of ['general', 'sources', 'privacy', 'analysis', 'notify', 'about']) mark(await step('settings-' + t, async () => { await ev(page, (t) => openSettings(t), t); await sleep(600); }));
  await step('settings-close', async () => { await closeAll(page); }, { shot: false });
  mark(await step('about', async () => { await ev(page, () => openAbout()); await sleep(600); }));
  await step('about-close', async () => { await closeAll(page); }, { shot: false });
  await ev(page, () => edSet('lite')); await sleep(800);
  for (const r of LITE_ROUTES) mark(await step('lite-' + r.slice(2), async () => { await goRoute(page, r); await sleep(900); }, { settle: 800 }), r);
  await R.save();
  fs.writeFileSync(path.join(SHOTS, 'index-mock.json'), JSON.stringify(index, null, 1));
  // merge index: step → live/mock
  const live = fs.existsSync(path.join(SHOTS, 'index-live.json')) ? JSON.parse(fs.readFileSync(path.join(SHOTS, 'index-live.json'), 'utf8')) : [];
  const m = {};
  live.forEach((x) => { m[x.step] = Object.assign(m[x.step] || {}, { live: x.live, liveUrl: x.url, liveId: x.id }); });
  index.forEach((x) => { m[x.step] = Object.assign(m[x.step] || {}, { mock: x.mock, mockUrl: x.url, mockId: x.id }); });
  fs.writeFileSync(path.join(SHOTS, 'index.json'), JSON.stringify(m, null, 1));
});
