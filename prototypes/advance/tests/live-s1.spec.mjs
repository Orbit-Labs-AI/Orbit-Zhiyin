// Slice 1 (A1 overview / A2 persona / Lite): live mode keeps the polished components and only swaps the data.
// Fixtures: prototypes/shared/fixtures/s1 — bodies captured from r4 on a synthetic home (2026-10-03, Asia/Shanghai).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const OV = { 7: fx('s1/overview-7.json'), 30: fx('s1/overview-30.json'), 90: fx('s1/overview-90.json'), 0: fx('s1/overview-0.json') };
const UI = { claude_code: 'cc', codex: 'cx', dsh: 'ds', pi: 'pi', kimi: 'km', hermes: 'hm', opencode: 'oc' };
const MOCK = /Confluo|latentskill|Gemini CLI|Copilot CLI|9\/30 23:10|2,416/;

function routes(o) {
  o = o || {};
  return {
    'GET /v1/uiview/overview': (req, u) => { const r = u.searchParams.get('range'); return OV[r] ? OV[r] : { status: 404 }; },
    'GET /v1/uiview/persona': (req, u) => { const p = u.searchParams.get('period') || '90'; return o.persona ? o.persona(p) : p === '30' ? fx('s1/persona-30.json') : p === '90' ? fx('s1/persona-90.json') : { status: 404 }; },
    'GET /v1/uiview/persona/reveal': () => (o.reveal || fx('s1/reveal.json'))
  };
}
test.use({ timezoneId: 'Asia/Shanghai' });
test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

async function noPlain(page) { expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0); }

test('A1 parity: client-derived tiles, trend and heat equal /v1/uiview/overview for 7 / 30 / 90 / all', async ({ page }) => {
  test.skip(!!PASS, 'fixture parity');
  const errors = collectErrors(page);
  await stubGateway(page, 's1', routes());
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  for (const r of [7, 30, 90, 0]) {
    const sv = OV[r];
    const c = await page.evaluate((range) => {
      S.range = range; render();
      const L = sel(); const st = stats(L); const end = win(range)[1];
      const fns = { n: (x) => x.length, h: (x) => stats(x).hours, m: (x) => stats(x).msgs, a: (x) => stats(x).auto, f: (x) => stats(x).fric };
      const tiles = {}; Object.keys(fns).forEach((k) => { tiles[k] = ovTrend(fns[k], end); });
      const ser = series(L, range, 'n');
      return { n: st.n, h: st.hours, m: st.msgs, a: st.auto, f: st.fric, tiles,
        ser: ser.map((b) => ({ a: b.a, b: b.b, v: AG.map((ag, j) => [ag.key, b.v[j]]) })), heat: heat(L), day0: DAY0, last: LASTDAY };
    }, r);
    const T = Object.fromEntries(sv.tiles.map((t) => [t.k, t]));
    expect(c.n).toBe(T.n.value); expect(+c.h.toFixed(1)).toBe(T.h.value); expect(c.m).toBe(T.m.value);
    expect(+c.a.toFixed(1)).toBe(T.a.value); expect(+c.f.toFixed(1)).toBe(T.f.value);
    // the server rounds trend values to 2 decimals (Python round-half-even); counts must be exact
    for (const k of ['n', 'm']) expect(c.tiles[k]).toEqual(T[k].trend);
    for (const k of ['h', 'a', 'f']) c.tiles[k].forEach((v, i) => expect(Math.abs(v - T[k].trend[i])).toBeLessThan(0.0051));
    expect(c.heat.H).toEqual(sv.heat.H); expect(c.heat.C).toEqual(sv.heat.C);
    // trend: same buckets by calendar date (the client's 'all' axis starts at DAY0 = today − 119, the server's at the
    // first data day, so the client may have extra empty leading buckets); per agent values must match
    const iso = (d) => new Date(c.day0 + d * 86400000).toISOString().slice(0, 10);
    const byEnd = Object.fromEntries(c.ser.map((b) => [iso(b.b), b]));
    sv.trend.x.forEach((x, i) => {
      const b = byEnd[x.b]; expect(b, 'bucket ending ' + x.b).toBeTruthy();
      const vals = Object.fromEntries(b.v);
      sv.trend.series.forEach((s) => expect(vals[s.agent] || 0).toBe(s.values[i] || 0));
    });
    const extra = c.ser.filter((b) => iso(b.b) < sv.trend.x[0].b);
    extra.forEach((b) => expect(b.v.every((x) => !x[1])).toBe(true));
  }
  expect(errors).toEqual([]);
});

test('A1 binds tools top 6 and the insight from /v1/uiview/overview; persona card from /v1/uiview/persona; no mock text', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 's1', routes());
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.feedState('overview'))).toBe('ready');
  const ov = OV[30];
  await expect(page.locator('.ov-tool')).toHaveCount(ov.tools.top.length);
  await expect(page.locator('.ov-tool .nm').first()).toHaveText(ov.tools.top[0].name);
  await expect(page.locator('[data-act="go"][data-r="tools"].lnk')).toHaveText('全部 ' + ov.tools.kinds_total + ' 种');
  await expect(page.locator('#aiLead')).toHaveText(ov.insight.lede);
  await expect(page.locator('.ov-aip').first()).toHaveText(ov.insight.good.text);
  await expect(page.locator('[data-aigen]')).toHaveText(ov.insight.when);
  // persona card: the code and axes of /v1/uiview/persona?period=30 (same scope as the sidebar)
  const p30 = fx('s1/persona-30.json');
  await expect(page.locator('.ov-pers .ov-code-l')).toHaveText(p30.code);
  expect(gw.seen.some((x) => x.path === '/v1/uiview/persona' && /period=30/.test(x.query))).toBe(true);
  // polished components are there, plain tables are not
  for (const sel of ['#ovTiles .kpi, #ovTiles [data-k]', '[data-vz="ov-trend"] svg', '[data-vz="ov-heat"] svg', '[data-vz="ov-axes"] svg']) await expect(page.locator(sel).first()).toBeVisible();
  await noPlain(page);
  expect(await page.locator('#main').innerText()).not.toMatch(MOCK);
  // trend legend names are real agents
  const legend = await page.locator('[data-vz="ov-trend"]').innerText();
  expect(legend).toMatch(/Claude Code/); expect(legend).toMatch(/Kimi CLI|Hermes Agent|OpenCode/);
  expect(errors).toEqual([]);
});

test('A2: code, axes and evidence equal /v1/uiview/persona; months from LASTDAY calendar; no population baseline', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 's1', routes());
  await openLive(page, 'persona');
  const P = fx('s1/persona-90.json');
  await expect(page.locator('.persona-hero .letters')).toBeVisible();
  const st = await page.evaluate(() => ({ period: S.persona.period, keys: Object.keys(PERIODS), cur: CUR.persona && { code: CUR.persona.code, v: CUR.persona.v, axes: CUR.persona.axes.map((a) => [a.k, a.letter, a.value]) } }));
  expect(st.period).toBe('90');
  expect(st.keys.sort()).toEqual(['2026-07', '2026-08', '2026-09', '2026-10', '90', 'all'].sort());
  expect(st.cur.code).toBe(P.code);
  expect(st.cur.axes).toEqual(P.axes.map((a) => [a.k, a.letter, a.value]));
  expect(st.cur.v).toEqual(P.v);
  await expect(page.locator('.persona-hero .letters .L')).toHaveText(P.code.split(''));
  // evolution row: the server months (2026-09 settled, the others 样本不足)
  const evo = page.locator('.pe-evrow button');
  await expect(evo).toHaveCount(4);
  await expect(evo.nth(2)).toContainText(P.months[2].code);
  await expect(evo.nth(0)).toContainText('样本不足');
  // evidence text per axis is the server's
  await expect(page.locator('.pe-evt').first()).toHaveText(P.axes[0].evidence.txt);
  // compass: the unsettled M axis prints '?', rose and planets are drawn for real agents only
  await expect(page.locator('svg.fp2 .fp-ax[data-k="M"] text').first()).toHaveText('?');
  const pl = await page.locator('svg.fp2 .fp-pl').evaluateAll((els) => els.map((e) => e.dataset.a));
  expect(pl.length).toBeGreaterThan(3); expect(pl.every((a) => ['cc', 'cx', 'ds', 'pi', 'km', 'hm', 'oc'].includes(a))).toBe(true);
  await expect(page.locator('[data-act="vs"][data-v="pop"]')).toHaveCount(0);
  await expect(page.locator('.pe-sw')).toContainText(P.strengths[0].text);
  await expect(page.locator('.pe-sw')).toContainText(P.blind_spots[0].type);
  await noPlain(page);
  expect(await page.locator('#main').innerText()).not.toMatch(MOCK);
  // switching to the current calendar month (few sessions) is honest: 样本不足, not a mock code
  await page.locator('.tbar [data-act="period"][data-v="2026-10"]').click();
  await expect(page.locator('.pe-low')).toBeVisible();
  expect(errors).toEqual([]);
});

test('A2 reveal: unsettled code names the closest candidates; a settled one plays the compass + genesis reveal', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 's1', routes());
  await openLive(page, 'persona');
  await expect(page.locator('.persona-hero .letters')).toBeVisible();
  await page.locator('[data-act="reveal"]').first().click();
  await expect(page.locator('#toast, .toast').first()).toContainText('最接近 SIMT');
  expect(gw.count('/v1/uiview/persona/reveal')).toBe(1);
  // settle the M axis (synthetic edit) and replay with animations on
  gw.set('GET /v1/uiview/persona', fx('s1/persona-90-settled.json'));
  gw.set('GET /v1/uiview/persona/reveal', fx('s1/reveal-settled.json'));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  await page.evaluate(() => { LVP.full.clear(); LV.rev++; render(); });
  await expect.poll(() => page.evaluate(() => CUR.persona && CUR.persona.code)).toBe('SIMT');
  await page.locator('[data-act="reveal"]').first().click();
  await expect.poll(() => page.evaluate(() => OVL)).toBe('reveal');
  await expect(page.locator('#overlay svg.fp2, #overlay .fp2').first()).toBeVisible({ timeout: 5000 });
  const anims = await page.evaluate(() => document.getAnimations().length);
  expect(anims).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test('Lite: home, persona, sessions and recs run on the real agents; persona months from the calendar', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 's1', routes());
  await openLive(page, 'overview');
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await expect.poll(() => page.evaluate(() => LV.feedState('l-home'))).toBe('ready');
  await expect(page.locator('.l-hero .l-say')).toHaveText(OV[30].insight.lede);
  await expect(page.locator('.l-code [data-hero="code"]')).toHaveText(fx('s1/persona-30.json').code);
  await expect(page.locator('.l-strip i')).toHaveCount(30);
  await page.evaluate(() => go('l-persona'));
  await expect(page.locator('.l-phero .letters')).toBeVisible();
  await expect(page.locator('.l-evo .evo button')).toHaveCount(4);
  await expect(page.locator('.l-evo .evo button.on')).toContainText('10 月 · 本月');
  await page.evaluate(() => go('l-sessions'));
  await expect(page.locator('.l-slist-c .srow').first()).toBeVisible();
  const dots = await page.locator('.l-slist-c .srow .dot').evaluateAll((els) => els.map((e) => e.getAttribute('style')));
  expect(dots.every((s) => /var\(--a[1-9]\)/.test(s))).toBe(true);
  await page.evaluate(() => go('l-recs'));
  await expect(page.locator('.l-rhero')).toBeVisible();
  for (const r of ['l-home', 'l-persona', 'l-sessions', 'l-recs']) {
    await page.evaluate((x) => go(x), r);
    await noPlain(page);
    expect(await page.locator('#main').innerText()).not.toMatch(MOCK);
  }
  expect(errors).toEqual([]);
});

test('empty spine and missing endpoints: owned routes render honest empty states, zero page errors', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's1'], {
    'GET /v1/uiview/facts': fx('core/facts-empty.json'), 'GET /v1/uiview/overview': { status: 404 }, 'GET /v1/uiview/persona': { status: 404 }, 'GET /v1/uiview/persona/reveal': { status: 404 }
  });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('empty');
  for (const r of ['overview', 'persona']) {
    await page.evaluate((x) => go(x), r);
    await expect(page.locator('#main')).not.toBeEmpty();
    await noPlain(page);
    expect(await page.locator('#main').innerText()).not.toMatch(MOCK);
  }
  await page.evaluate(() => go('overview'));
  await expect(page.locator('.ov-tools [data-lv="na"]')).toBeVisible();
  await page.evaluate(() => edSet('lite'));
  for (const r of ['l-home', 'l-persona', 'l-sessions', 'l-recs']) {
    await page.evaluate((x) => go(x), r);
    await expect(page.locator('#main')).not.toBeEmpty();
    await noPlain(page);
  }
  expect(errors).toEqual([]);
});

test('G1 port: rows with unit counts compute the persona client-side (Wilson axes) without a server round trip', async ({ page }) => {
  test.skip(!!PASS, 'synthetic rows');
  await stubGateway(page, 's1', routes());
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const p = await page.evaluate(() => {
    // 40 synthetic rows over 20 days, two agents a day: D 委托 (most turns ≥ 5 steps), P (structured openings), M, V
    const L = Array.from({ length: 40 }, (_, i) => ({ id: 's' + i, d: Math.floor(i / 2), h: 10, mi: 0, a: i % 2 ? 'cc' : 'cx', p: '_none', dur: 10, msgs: 4, tools: 8, corr: 0, errors: 0, steps: 20, out: 'ok', verify: true,
      dk: 4, dn: 4, vk: 4, op: 1, t0: i * 1000, t1: i * 1000 + 500 }));
    const r = persona(L); return { ok: r.ok, code: r.code, zh: r.zh, axes: r.axes.map((a) => [a.k, a.state, a.value]) };
  });
  expect(p.ok).toBe(true);
  expect(p.code).toBe('DPMV');
  expect(p.zh).toBe('总设计师');
  expect(p.axes).toEqual([['D', 'settled', 100], ['I', 'settled', 0], ['M', 'settled', 100], ['V', 'settled', 100]]);
});
