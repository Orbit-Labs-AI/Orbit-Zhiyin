// Honest states while data is on its way (F08 / F21 / D9 / A1 guide / F23 tip). Stub gateway, fixtures in
// prototypes/shared/fixtures/core.
// Test flow (mac-14):
//  1 computing   facts answers 202 (analysis running): every page of both editions, the widgets and the menubar popover say
//                the data is being analysed — never 「没有会话 / 还没有接入 / 都已处理」, no 导入会话 entry
//  2 empty       facts answers no rows: 还没有会话 is said, but never 「建议都已处理」 (there were no recommendations)
//  3 agents      an installed Gemini CLI (no session connector) is not a sidebar agent nor an 「导入会话」 choice; demo lists
//                only agents with a connector
//  4 guide       the overview guide names the badge the top card wears (规则解读 in live without a model narrative)
//  5 heat tip    the activity heatmap tip holds its rows (纠偏 label inside the box)
import { test, expect } from '@playwright/test';
import { pathToFileURL } from 'node:url';
import { stubGateway, openLive, collectErrors, fx, ADV_FILE } from './live-helpers.mjs';
import { openDemo } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const FALSE_CLAIMS = /没有会话|还没有接入|都已处理|查看 0 条建议/;
// numbers nothing has measured yet (F08): 「0 个会话」「0 次」「全部 0」「▲ 0%」, and error fallbacks standing in for the busy state
const FAKE_ZERO = /\b0(\.0)? ?(个会话|次|条|会话|h\b)|全部 0\b|▲ 0%|暂无数据|暂时不可用|样本不足/;
const zeroTiles = (page, sel) => page.locator(sel + ' .vz-kpi .v').evaluateAll((els) => els.map((e) => e.textContent.trim()).filter((t) => /^0(\.0)?$/.test(t)));
const ADV = ['overview', 'persona', 'sentiment', 'projects', 'sessions', 'tools', 'recs'];
const LITE = ['l-home', 'l-persona', 'l-sessions', 'l-recs'];

test('computing: titles and cards say the data is being analysed on every page, both editions', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core'], { 'GET /v1/uiview/facts': { status: 202, body: fx('core/facts-computing.json') } });
  await openLive(page, 'overview');
  expect(await page.evaluate(() => [LV.state, ALL.length, !!dataBusy()])).toEqual(['computing', 0, true]);
  await expect(page.locator('#main .tbar .meta')).toContainText('已导入 26 个会话');
  await expect(page.locator('#main .tbar .meta')).toContainText('分析中');
  for (const ed of ['advance', 'lite']) {
    await page.evaluate((e) => { if (S.ed !== e) edSet(e); }, ed);
    await expect.poll(() => page.evaluate(() => S.ed)).toBe(ed);
    for (const r of ed === 'lite' ? LITE : ADV) {
      await page.evaluate((x) => go(x), r);
      await expect.poll(() => page.evaluate(() => S.route)).toBe(r);
      const txt = await page.locator('#main').innerText();
      expect(txt, ed + ' ' + r).not.toMatch(FALSE_CLAIMS);
      expect(txt, ed + ' ' + r).not.toMatch(FAKE_ZERO);
      expect(await zeroTiles(page, '#main'), ed + ' ' + r).toEqual([]);
      await expect(page.locator('#main [data-act="liteImport"]'), ed + ' ' + r).toHaveCount(0);
    }
  }
  // sidebar, widgets and the menubar popover
  expect(await page.locator('#side').innerText()).not.toMatch(FALSE_CLAIMS);
  await page.evaluate(() => { S.widgets = true; S.pop = true; render(); });
  for (const sz of ['s', 'm', 'l']) {
    await page.evaluate((x) => { S.wgSize = x; render(); }, sz);
    const wt = await page.locator('#widgets').innerText();
    expect(wt, 'widgets ' + sz).not.toMatch(FALSE_CLAIMS);
    expect(wt, 'widgets ' + sz).not.toMatch(FAKE_ZERO);
    expect(wt, 'widgets ' + sz).toContain('计算中');
  }
  const pt = await page.locator('#pop').innerText();
  expect(pt).not.toMatch(FALSE_CLAIMS);
  expect(pt).not.toMatch(FAKE_ZERO);
  expect(errors).toEqual([]);
});

test('empty: 还没有会话 is said, never 建议都已处理', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core'], { 'GET /v1/uiview/facts': fx('core/facts-empty.json') });
  await openLive(page, 'overview');
  expect(await page.evaluate(() => [LV.state, !!dataBusy()])).toEqual(['empty', false]);
  expect(await page.evaluate(() => recNone().k)).toBe('none');   // no sessions is the reason, before any rec-service state
  const txt = await page.locator('#main').innerText();
  expect(txt).not.toMatch(/都已处理|查看 0 条建议/);
  await page.evaluate(() => { edSet('lite'); go('l-home'); });
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  expect(await page.locator('#main').innerText()).not.toMatch(/都已处理|查看已应用的建议/);
  expect(errors).toEqual([]);
});

test('agents: no session connector → not listed in live; demo lists only importable agents', async ({ page }) => {
  const env = fx('core/install-environment.json');
  env.agents = env.agents.map((a) => (a.agent === 'gemini' ? Object.assign({}, a, { installed: true }) : a));
  await stubGateway(page, ['core'], { 'GET /v1/install/environment': env });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  expect(await page.evaluate(() => AG.map((a) => a.id))).not.toContain('gm');
  await expect(page.locator('#side .ag[data-a="gm"]')).toHaveCount(0);
  expect(await page.evaluate(() => [LV.importable('gemini'), LV.importable('copilot'), LV.importable('kimi'), LV.importable('claude_code')])).toEqual([false, false, true, true]);
  // demo: the sample agents all have a session connector
  await page.goto(pathToFileURL(ADV_FILE).href);
  const names = await page.evaluate(() => AG.map((a) => a.name));
  expect(names.join(' ')).not.toMatch(/Gemini|Copilot|Cursor/);
  expect(names).toEqual(['Claude Code', 'Codex', 'Kimi CLI', 'DeepSeek Harness', 'OpenCode']);
});

test('guide: the overview hint names the badge actually shown', async ({ page }) => {
  await stubGateway(page, ['core']);
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await page.evaluate(() => { store.set('guideOff', false); render(); });
  const badge = await page.locator('#aiCard .ov-aih').first().innerText();
  const guide = await page.locator('.pg-guide').innerText();
  if (/AI 解读/.test(badge)) expect(guide).toContain('「AI 解读」');
  else if (/规则解读/.test(badge)) expect(guide).toContain('「规则解读」');
  else expect(guide).not.toMatch(/AI 解读|规则解读/);
});

test('heat tip: rows stay inside the box', async ({ page }) => {
  await openDemo(page);
  for (const mode of ['msgs', 'corr']) {
    await page.evaluate((m) => { go('overview'); ACT.heatMode({ dataset: { v: m } }); }, mode);
    const cell = page.locator('[data-vz="ov-heat"] .vz-cell').nth(2 * 24 + 22);
    await cell.scrollIntoViewIfNeeded();
    const b = await cell.boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.move(b.x + b.width / 2 + 1, b.y + b.height / 2);
    const tip = page.locator('[data-vz="ov-heat"] .vz-tip');
    await expect(tip).toBeVisible();
    const over = await tip.evaluate((t) => { const r = t.getBoundingClientRect(); return Array.from(t.querySelectorAll('.vz-tr > *, .vz-th > *')).filter((e) => e.getBoundingClientRect().right > r.right + 0.5).map((e) => e.textContent); });
    expect(over, mode).toEqual([]);
  }
});
