// Live surfaces (branch ui/p-live): menu-bar panel, floating HUD, desktop widgets, the simulated-event state machine and
// the settings sections that drive them. Flow:
//  1. matrix channels   notify matrix columns act independently: a「会话完成」with only 悬浮组件 ticked changes S.hudSim and
//                       leaves the menu-bar badge (S.sim) alone, and vice versa (BUG-40); muting blocks the HUD channel but
//                       the badge still updates (BUG-44)
//  2. settle / idle     stuck + ctx then ignoring stuck falls back to ctx, ignoring ctx to the resting state (BUG-74);
//                       from idle, an alert that is ignored (or a「完成」after its 8 s) returns to idle and the HUD stays hidden
//                       (BUG-41); the demo menu's idle / running entries reflect S.simBase
//  3. done → trajectory 「查看」after a「完成」opens the finished session, not the running one (BUG-42)
//  4. newsrc twice      two「发现新的数据来源」banners both clicked add Cursor once (BUG-43)
//  5. panel             running: live card with the shared context bar, 7-day columns with counts and「今」; idle: yesterday's
//                       metrics carry a 30-day baseline; 预览 / Codex row close the panel before jumping (BUG-82)
//  6. HUD               density band and pill bars come from the running session's trajectory (same numbers as liveBuckets),
//                       not random; the metric grid uses the context bar; a render() during a drag does not strand it (BUG-45)
//  7. widgets           three sizes change the card count and column height; the week chart has 7 weekday labels and only the
//                       top segment is rounded; size persists in localStorage
//  8. settings          默认时间范围 persists across reload (BUG-51); 不再提示此类 can be undone in 设置 › 通知 (BUG-83);
//                       the matrix shows per-column counts; AI 通道 switches follow the engine; settings window and its
//                       controls stay inside the viewport at the compact size and in full screen (BUG-78)
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');

test('notification matrix columns drive the badge and the HUD independently; mute blocks only the HUD', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  const st = () => page.evaluate(() => [S.sim, S.hudSim]);
  await page.evaluate(() => { S.notif.done = [0, 1, 0]; simEvent('done'); });
  expect(await st()).toEqual(['running', 'done']);
  await expect(page.locator('#hudPill')).toContainText('完成');
  await expect(page.locator('#mbar .badge')).toHaveClass(/live/);
  await page.evaluate(() => { simClear('done'); S.notif.done = [0, 0, 1]; simEvent('done'); });
  expect(await st()).toEqual(['done', 'running']);
  await expect(page.locator('#hudPill')).not.toContainText('完成');
  await page.evaluate(() => { simClear('done'); setHudMuted(true, 60000); S.notif.stuck = [1, 1, 1]; simEvent('stuck'); });
  expect(await st()).toEqual(['stuck', 'running']);
  expect(await page.locator('#notes .nt').filter({ hasText: '连续失败' }).count()).toBe(0);
  expect(errors).toEqual([]);
});

test('clearing alerts falls back to the next open item, then to the resting state, including idle', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  const st = () => page.evaluate(() => [S.sim, S.hudSim, $('#hud').hidden]);
  await page.evaluate(() => { S.notif.stuck = [0, 1, 1]; S.notif.ctx = [0, 1, 1]; simEvent('stuck'); simEvent('ctx'); });
  expect(await st()).toEqual(['ctx', 'ctx', false]);
  await page.evaluate(() => ACT.popIgnore({ dataset: { k: 'ctx' } }));
  expect(await st()).toEqual(['stuck', 'stuck', false]);
  await page.evaluate(() => ACT.popIgnore({ dataset: { k: 'stuck' } }));
  expect(await st()).toEqual(['running', 'running', false]);
  // idle → alert → ignore returns to idle and the HUD stays hidden (BUG-41)
  await page.evaluate(() => { simEvent('idle'); });
  expect(await st()).toEqual(['idle', 'idle', true]);
  await page.evaluate(() => { simEvent('stuck'); });
  expect(await page.evaluate(() => [S.sim, S.simBase])).toEqual(['stuck', 'idle']);
  await page.evaluate(() => ACT.popIgnore({ dataset: { k: 'stuck' } }));
  expect(await st()).toEqual(['idle', 'idle', true]);
  // a「完成」while idle shows for 8 s then returns to idle
  await page.evaluate(() => { S.notif.done = [0, 1, 1]; simEvent('done'); });
  expect(await st()).toEqual(['done', 'done', false]);
  await page.evaluate(() => { clearTimeout(SIMT); simClear('done'); render(); });
  expect(await st()).toEqual(['idle', 'idle', true]);
  const demo = await page.evaluate(() => MENUS.demo().filter((x) => x.t && /空闲|运行中/.test(x.t)).map((x) => [x.t, !!x.on]));
  expect(demo).toEqual([['空闲（没有运行中的会话）', true], ['有会话运行中', false]]);
  expect(errors).toEqual([]);
});

test('「查看」after a completion opens the finished session; two newsrc banners add Cursor once', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => { S.notif.done = [1, 1, 1]; simEvent('done'); });
  await page.locator('#hudPill button', { hasText: '查看' }).click();
  expect(await page.evaluate(() => [S.route, S.sess.sel, BYID[S.sess.sel].live, S.sim, S.hudSim])).toEqual(['sessions', 'sess-0930-1402', undefined, 'running', 'running']);
  await page.evaluate(() => { $$('#notes .nt').forEach((n) => n.remove()); simEvent('newsrc'); simEvent('newsrc'); });
  await expect(page.locator('#notes .nt')).toHaveCount(2);
  for (const b of await page.locator('#notes [data-act="noteAct"][data-k="1"]').all()) await b.evaluate((el) => el.click());
  expect(await page.evaluate(() => S.extraSrc.filter((x) => /cursor/i.test(x.name)).length)).toBe(1);
  expect(errors).toEqual([]);
});

test('menu-bar panel: live card with context bar, 7-day columns, idle baseline, closes before jumping', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => { S.pop = true; render(); });
  const pop = page.locator('#pop');
  await expect(pop.locator('.ctxbar')).toHaveCount(1);
  await expect(pop.locator('.ctxbar-th')).toHaveCSS('left', /px/);
  await expect(pop.locator('.pwk-c')).toHaveCount(7);
  await expect(pop.locator('.pwk-c.today')).toContainText('今');
  const counts = await pop.locator('.pwk-c b').allTextContents();
  expect(counts.every((c) => /^\d+$/.test(c))).toBe(true);
  await expect(pop).toContainText('日均');
  // 预览 closes the panel and opens the recommendation (BUG-82)
  const recId = await pop.locator('[data-act="popRec"]').getAttribute('data-id');
  await pop.locator('[data-act="popRec"]').click();
  expect(await page.evaluate(() => [S.pop, S.route, S.recs.sel])).toEqual([false, 'recs', recId]);
  await page.evaluate(() => { S.pop = true; render(); });
  await pop.locator('[data-act="popSess"]').first().click();
  expect(await page.evaluate(() => [S.pop, S.route])).toEqual([false, 'sessions']);
  // idle: yesterday's metrics carry the 30-day baseline
  await page.evaluate(() => { simEvent('idle'); S.pop = true; render(); });
  await expect(pop.locator('.pm-base')).toHaveCount(3);
  await expect(pop).toContainText('基线 = 近 30 天均值');
  const nonLive = await page.evaluate(() => String(ALL.filter((s) => s.d === 120 && !s.live && sourceEnabled(s)).length));
  await expect(pop.locator('.pwk-c.today b')).toHaveText(nonLive);
  expect(errors).toEqual([]);
});

test('HUD density band and pill bars follow the running session; a render mid-drag does not strand the drag', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => { S.hud.open = true; renderHud(); });
  const exp = await page.evaluate(() => { const d = liveBuckets(20, 30); return { cols: d.b.filter((x) => x.tool).length, dots: d.b.filter((x) => x.user).length, err: d.b.filter((x) => x.err).length, tools: d.b.reduce((a, x) => a + x.tool, 0) }; });
  expect(exp.tools).toBeGreaterThan(10);
  const band = page.locator('#hud .hband');
  await expect(band.locator('circle')).toHaveCount(exp.dots);
  await expect(band.locator('rect')).toHaveCount(exp.cols + exp.err);
  await expect(band).toContainText('工具 ' + exp.tools);
  await expect(page.locator('#hud .hgrid .ctxbar.dk')).toHaveCount(1);
  await expect(page.locator('#hud .hcard .serif')).toHaveText('设计 Tandem Mac App 视觉案例');
  // two renders give the same band (derived, not random)
  const svg1 = await band.locator('svg').innerHTML();
  await page.evaluate(() => renderHud());
  expect(await page.locator('#hud .hband svg').innerHTML()).toBe(svg1);
  await expect(page.locator('#hudPill svg rect')).toHaveCount(5);
  // drag, render() in the middle, release: no snap dots left behind, the pill snapped
  await page.evaluate(() => { S.hud.open = false; renderHud(); });
  const r = await page.locator('#hudPill').boundingBox(); const vw = page.viewportSize();
  await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2); await page.mouse.down();
  await page.mouse.move(vw.width / 2, vw.height / 2, { steps: 6 });
  await expect(page.locator('.snap')).toHaveCount(6);
  await page.evaluate(() => render());
  await page.mouse.move(vw.width / 2 + 30, vw.height / 2 - 20, { steps: 4 });
  await page.mouse.up();
  await expect(page.locator('.snap')).toHaveCount(0);
  expect(await page.evaluate(() => [HDRAG, !!S.hud.snap, S.hud.user])).toEqual([null, true, true]);
  // hovering afterwards must not move the pill
  const r2 = await page.locator('#hudPill').boundingBox();
  await page.mouse.move(r2.x - 100, r2.y + 100);
  expect(await page.locator('#hudPill').boundingBox()).toEqual(r2);
  expect(errors).toEqual([]);
});

test('desktop widgets come in three sizes, the week chart is labelled, size persists', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await expect(page.locator('#widgets')).toBeVisible();
  const h = {};
  for (const z of ['s', 'm', 'l']) {
    await page.evaluate((v) => ACT.wgSize({ dataset: { v } }), z);
    await expect(page.locator('#widgets')).toHaveAttribute('data-size', z);
    h[z] = { n: await page.locator('#widgets .wg').count(), h: (await page.locator('#widgets').boundingBox()).height };
  }
  expect(h.s.n).toBe(2); expect(h.m.n).toBeGreaterThan(h.s.n); expect(h.l.n).toBeGreaterThan(h.m.n);
  expect(h.s.h).toBeLessThan(h.m.h); expect(h.m.h).toBeLessThan(h.l.h);
  await expect(page.locator('#widgets .wk .wg-col')).toHaveCount(7);
  await expect(page.locator('#widgets .wk .wg-col > span.cap')).toHaveText(['四', '五', '六', '日', '一', '二', '三']);
  const radii = await page.locator('#widgets .wg-stack').first().evaluate((el) => [...el.children].map((c) => getComputedStyle(c).borderTopLeftRadius + '/' + getComputedStyle(c).borderBottomLeftRadius));
  expect(radii[0]).toBe('2px/0px'); radii.slice(1).forEach((r) => expect(r).toBe('0px/0px'));
  await expect(page.locator('#widgets .wg-trend')).toHaveCount(2);
  await expect(page.locator('#widgets [data-act="wgLive"] .ctxbar')).toHaveCount(1);
  // the ⋯ menu lists the sizes; the choice survives a reload
  await page.locator('#widgets [data-act="wgMenu"]').click({ force: true });
  await expect(page.locator('#dd button')).toHaveCount(3);
  await page.locator('#dd button', { hasText: '小' }).click();
  expect(await page.evaluate(() => [S.wgSize, localStorage.getItem('tandem-demo:wgSize')])).toEqual(['s', '"s"']);
  await page.reload(); await expect(page.locator('#main')).not.toBeEmpty();
  await expect(page.locator('#widgets')).toHaveAttribute('data-size', 's');
  await page.evaluate(() => localStorage.removeItem('tandem-demo:wgSize'));
  expect(errors).toEqual([]);
});

test('settings: range persists, HUD tip can be restored, matrix counts and AI channel follow the engine', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => { openSettings('general'); });
  await page.locator('#set [data-act="setRange"][data-v="7"]').click();
  await page.reload(); await expect(page.locator('#main')).not.toBeEmpty();
  expect(await page.evaluate(() => S.range)).toBe(7);
  await page.evaluate(() => localStorage.removeItem('tandem-demo:range'));
  // 不再提示此类 → restored from settings › 通知 (BUG-83)
  await page.evaluate(() => { S.live.ctx = 70; S.hud.open = true; renderHud(); });
  await page.locator('#hud [data-act="hudTipOff"]').click();
  expect(await page.evaluate(() => S.hud.tipOff)).toBe(true);
  await page.evaluate(() => openSettings('notify'));
  const sw = page.locator('#set [data-act="setTipOn"]');
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  await sw.click();
  expect(await page.evaluate(() => S.hud.tipOff)).toBe(false);
  await expect(page.locator('#set .nmx th')).toHaveCount(4);
  const before = await page.locator('#set .nmx th').nth(1).textContent();
  await page.locator('#set .nmx input[data-e="weekly"][data-c="0"]').click();
  expect(await page.locator('#set .nmx th').nth(1).textContent()).not.toBe(before);
  await page.locator('#set [data-act="setNotifPreset"][data-v="quiet"]').click();
  expect(await page.evaluate(() => S.notif.weekly)).toEqual([0, 0, 0]);
  // AI channel: 完整原文 only with Ollama; nothing with 仅统计
  await page.evaluate(() => openSettings('analysis'));
  await expect(page.locator('#set [data-act="setAiCh"][data-k="raw"]')).toBeDisabled();
  await page.locator('#set [data-act="setEngine"][data-v="ollama"]').click();
  await expect(page.locator('#set [data-act="setAiCh"][data-k="raw"]')).toBeEnabled();
  await page.locator('#set [data-act="setEngine"][data-v="stats"]').click();
  await expect(page.locator('#set .aich.off')).toHaveCount(1);
  await page.locator('#set [data-act="setEngine"][data-v="agent"]').click();
  expect(errors).toEqual([]);
});

test('settings window and its controls stay inside the viewport at the compact size and in full screen', async ({ page }) => {
  test.skip(!['compact', 'small'].includes(test.info().project.name), 'narrow stages only');
  const errors = await openDemo(page);
  const check = async () => {
    const s = await page.locator('#set').boundingBox(); const vw = page.viewportSize();
    expect(s.x).toBeGreaterThanOrEqual(0); expect(s.x + s.width).toBeLessThanOrEqual(vw.width); expect(s.y + s.height).toBeLessThanOrEqual(vw.height);
    for (const sel of ['#set .tabs button', '#set .body .sw', '#set .body .seg']) for (const b of await page.locator(sel).all()) { const bb = await b.boundingBox(); if (!bb) continue; expect(bb.x).toBeGreaterThanOrEqual(s.x - 0.5); expect(bb.x + bb.width).toBeLessThanOrEqual(s.x + s.width + 0.5); }
  };
  for (const tab of ['general', 'sources', 'privacy', 'notify']) { await page.evaluate((t) => openSettings(t), tab); await check(); }
  await page.evaluate(() => { closeSettings(); winFullToggle(); openSettings('notify'); });
  await check();
  await page.evaluate(() => { closeSettings(); winFullToggle(); });
  expect(errors).toEqual([]);
});
