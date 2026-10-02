// Round 2 scale fixes + J11 / B12 (live): TL changes render once per frame and only when the live state changed; render()
// lays the window out once against a cached stage size; picking an A3 session swaps the detail pane only; A4 rows show
// the original spellings (aliases) and drill down by key; A5 workflow chips never repeat a raw name.
// Fixtures: prototypes/shared/fixtures/core + s3 (synthetic), with J11-shaped overrides built here.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const frames = (page, n) => page.evaluate((k) => new Promise((r) => { let i = 0; const f = () => (++i >= k ? r() : requestAnimationFrame(f)); requestAnimationFrame(f); }), n || 3);
async function countRenders(page) {
  await page.evaluate(() => {
    window.__R = { render: 0, applyWin: 0 };
    const r0 = window.render; window.render = function () { window.__R.render++; return r0.apply(this, arguments); };
    const a0 = window.applyWin; window.applyWin = function () { window.__R.applyWin++; return a0.apply(this, arguments); };
  });
}

test('TL changes coalesce into one render per frame and an unchanged live state renders nothing', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await expect.poll(() => page.evaluate(() => LV.ready('tools'))).toBe(true);
  await frames(page, 4);
  await countRenders(page);
  // scheduling without any state change: the frame flushes, sees the same signature, skips render()
  await page.evaluate(() => { lvSchedule(); lvSchedule(); lvSchedule(); });
  await frames(page);
  expect(await page.evaluate(() => window.__R.render)).toBe(0);
  // an explicit TL.changed() (LV.detail arrival, ops frame…) is a change: several of them in one frame → one render
  await page.evaluate(() => { TL.changed(); setTimeout(() => TL.changed(), 0); });
  await frames(page);
  expect(await page.evaluate(() => window.__R.render)).toBe(1);
  // render() lays the window out once (the second applyWin() is gone)
  await page.evaluate(() => { window.__R.applyWin = 0; render(); });
  expect(await page.evaluate(() => window.__R.applyWin)).toBe(1);
  expect(errors).toEqual([]);
});

test('a 304 / identical feed body does not re-apply the feed', async ({ page }) => {
  await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await expect.poll(() => page.evaluate(() => LV.ready('tools'))).toBe(true);
  const n = await page.evaluate(() => {
    const f = LV.feeds.tools[0]; let applied = 0; const a0 = f.apply; f.apply = function () { applied++; return a0.apply(this, arguments); };
    // same data objects, newer updatedAt (what a 304 leaves behind)
    lvFeedRes(f).forEach((x) => { x.r.updatedAt = (x.r.updatedAt || 0) + 1000; });
    LV.pump('tools');
    const sameSkipped = applied;
    lvFeedRes(f).forEach((x) => { x.r.data = Object.assign({}, x.r.data); x.r.updatedAt += 1000; });
    LV.pump('tools');
    f.apply = a0;
    return [sameSkipped, applied];
  });
  expect(n).toEqual([0, 1]);
});

test('stage size is cached and follows viewport resizes', async ({ page }) => {
  await stubGateway(page, ['core']);
  await openLive(page, 'overview');
  const a = await page.evaluate(() => [stageSize() === stageSize(), stageSize().w]);
  expect(a[0]).toBe(true);
  const vp = page.viewportSize();
  await page.setViewportSize({ width: vp.width - 120, height: vp.height });
  await expect.poll(() => page.evaluate(() => [stageSize().w, document.getElementById('desk').clientWidth])).toEqual([a[1] - 120, a[1] - 120]);
  await expect.poll(() => page.evaluate(() => parseFloat($('#win').style.width) <= stageSize().w)).toBe(true);
  await page.setViewportSize(vp);
});

test('A3: picking a session swaps the detail pane only and moves the selection', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core']);
  await openLive(page, 'sessions');
  await expect(page.locator('#slist .srow').nth(2)).toBeVisible();
  await page.evaluate(() => { $('#slist').__keep = 1; $('#sessQ').__keep = 1; });
  await countRenders(page);
  const id = await page.locator('#slist .srow').nth(2).getAttribute('data-id');
  // checked in the same task as the click: a later detail arrival may still re-render the page
  const st = await page.evaluate((x) => { $('#slist .srow[data-id="' + x + '"]').click(); return {
    keep: $('#slist').__keep === 1 && $('#sessQ').__keep === 1, sel: S.sess.sel,
    on: $$('#slist .srow.sel').map((b) => b.dataset.id), pressed: $$('#slist .srow[aria-pressed="true"]').map((b) => b.dataset.id),
    title: ($('#main .sb-title') || {}).textContent, want: BYID[x].title, renders: window.__R.render }; }, id);
  expect(st.keep).toBe(true);
  expect(st.sel).toBe(id);
  expect(st.on).toEqual([id]); expect(st.pressed).toEqual([id]);
  expect(st.title).toBe(st.want);
  expect(st.renders).toBe(0);
  // compare mode still renders the whole page
  await page.locator('[data-act="sessMode"][data-v="cmp"]').click();
  await expect(page.locator('.tl-cmp')).toHaveCount(2);
  expect(errors).toEqual([]);
});

const J11_TOOLS = () => {
  const b = JSON.parse(JSON.stringify(fx('s3/tools.json')));
  b.tools = b.tools.filter((t) => t.kind !== 'shell');
  b.tools.unshift(
    { key: 'bash', name: 'Bash', kind: 'shell', mcp_server: null, n: 40, failed: 2, known: 40, approval_rate: 0, p50_ms: 900, p95_ms: 4000, daily: [], aliases: [{ name: 'Bash', agents: ['claude_code'], n: 30 }, { name: 'bash', agents: ['codex', 'pi'], n: 10 }] },
    { key: 'exec_command', name: 'exec_command', kind: 'shell', mcp_server: null, n: 12, failed: 1, known: 12, approval_rate: 0, p50_ms: 800, p95_ms: 3000, daily: [], aliases: [{ name: 'exec_command', agents: ['codex'], n: 12 }] },
    { key: 'notebookedit', name: 'NotebookEdit', kind: 'notebook', mcp_server: null, n: 30, failed: 0, known: 30, approval_rate: 0, p50_ms: 300, p95_ms: 900, daily: [], aliases: [{ name: 'NotebookEdit', agents: ['claude_code'], n: 25 }, { name: 'notebook_edit', agents: ['kimi'], n: 5 }] }
  );
  return b;
};

test('J11: A4 rows list the original spellings per agent and drill down by key', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/tools': J11_TOOLS() });
  await openLive(page, 'tools');
  const bash = page.locator('#main tr[data-t="Bash"]');
  await expect(bash).toBeVisible();
  const tip = await bash.locator('td.tt-name').getAttribute('data-tip');
  expect(tip).toContain('Bash（Claude Code） ×30');
  expect(tip).toContain('bash（Codex · Pi） ×10');
  expect(tip).toContain('exec_command（Codex） ×12');
  // a row outside the kind map is keyed by the normalised name: the drill-down sends that key
  const nb = page.locator('#main tr[data-t="NotebookEdit"]');
  await nb.click();
  await expect(page.locator('[data-lv="tool-aliases"]')).toContainText('notebook_edit（Kimi CLI） ×5');
  await expect.poll(() => gw.seen.filter((x) => x.path === '/v1/analytics/tool_calls').length).toBe(1);
  const q = gw.seen.find((x) => x.path === '/v1/analytics/tool_calls').query;
  expect(q).toMatch(/[?&]name=notebookedit(&|$)/);
  expect(errors).toEqual([]);
});

test('B12: A5 workflow chips dedupe identical neighbours and never show a raw name twice', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/projects': fx('s3/projects.json') });
  const key = Object.keys(gw.map).find((k) => /^GET \/v1\/uiview\/projects\/./.test(k));
  const det = JSON.parse(JSON.stringify(gw.map[key]));
  det.workflows[0].steps = [{ name: 'Edit', head: null }, { name: 'MultiEdit', head: null }, { name: 'NotebookEdit', head: null }, { name: 'exec_command', head: 'cat' }];
  gw.set(key, det);
  await openLive(page, 'projects');
  await expect(page.locator('#main .pj-step').first()).toBeVisible();
  const chips = await page.locator('#main .pj-step').evaluateAll((els) => els.map((e) => [e.querySelector('b').textContent, (e.querySelector('.mono') || { textContent: '' }).textContent]));
  expect(chips).toEqual([['修改文件', 'Edit'], ['NotebookEdit', ''], ['查看文件', 'cat']]);
  expect(errors).toEqual([]);
});
