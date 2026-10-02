import { test, expect } from '@playwright/test';
import { openDemo, go, closeAll } from './helpers.mjs';

test('disabled sources hide live sessions across entry points', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await go(page, 'sessions');
  const live = page.locator('.srow[data-id="sess-1001-1512"]');
  await expect(live).toBeVisible();
  await page.evaluate(() => { S.widgets = true; openSettings('sources'); });
  await page.locator('#set [data-act="setSrc"][data-a="cc"]').click();
  await closeAll(page);
  await expect(live).toHaveCount(0);
  await expect(page.locator('#hud')).toBeHidden();
  await expect(page.locator('#widgets [data-r="sessions"]')).not.toContainText('Hackathon');
  await page.evaluate(() => renderPop());
  await expect(page.locator('#pop')).not.toContainText('设计 Tandem Mac App 视觉案例');
  expect(await page.evaluate(() => palItems('设计 Tandem Mac App 视觉案例').filter((x) => x.g === '会话' && x.sub.startsWith('Claude Code ·')))).toEqual([]);
  await closeAll(page);
  await page.evaluate(() => openSettings('sources'));
  await page.locator('#set [data-act="setSrc"][data-a="cc"]').click();
  await closeAll(page);
  await expect(live).toBeVisible();
  await expect(page.locator('#hud')).toBeVisible();
  await expect(page.locator('#widgets [data-r="sessions"]')).toContainText('Hackathon');
  expect(errors).toEqual([]);
});

test('mute expiration honors thirty minutes and manual overrides', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const time = new Date('2026-10-02T04:00:00Z');
  await page.clock.install({ time });
  // pause a second later: the installed clock may already have ticked past `time`, and pauseAt never moves backwards
  await page.clock.pauseAt(new Date(time.getTime() + 1000));
  const errors = await openDemo(page);
  const muted = () => page.evaluate(() => S.hud.mute);
  await page.evaluate(() => ACT.hudMute());
  await page.clock.fastForward(30 * 60 * 1000 - 1);
  expect(await muted()).toBe(true);
  await page.clock.fastForward(1);
  expect(await muted()).toBe(false);

  await page.evaluate(() => ACT.hudMute());
  await page.clock.fastForward(10 * 60 * 1000);
  await page.evaluate(() => { ACT.hudMute(); ACT.hudMute(); });
  await page.clock.fastForward(20 * 60 * 1000);
  expect(await muted()).toBe(true);
  await page.clock.fastForward(10 * 60 * 1000);
  expect(await muted()).toBe(false);

  await page.evaluate(() => ACT.hudMute());
  await page.evaluate(() => { ACT.setMute(); ACT.setMute(); });
  await page.clock.fastForward(31 * 60 * 1000);
  expect(await muted()).toBe(true);
  await page.evaluate(() => ACT.setMute());
  expect(await muted()).toBe(false);
  expect(errors).toEqual([]);
});

test('session details and comparison honor active filters', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await page.evaluate(() => { S.agents = new Set(['cx']); render(); });
  await expect(page.locator('#main .band')).toContainText('Codex');
  await expect(page.locator('#main .band')).not.toContainText('Claude Code');
  await page.evaluate(() => { S.sess.cmp = FEAT_ID; S.sess.mode = 'cmp'; render(); });
  await expect(page.locator('#main')).toContainText('再选一个会话作为 B');
  await page.evaluate(() => { S.agents.clear(); render(); });
  await expect(page.locator('#main')).toContainText('没有会话');
  await expect(page.locator('#main .band')).toHaveCount(0);
  await page.locator('#main [data-act="sessMode"][data-v="cmp"]').click();
  await expect(page.locator('#main')).toContainText('没有会话');
  expect(errors).toEqual([]);
});

test('unclassified personas retain metrics and cannot be shared or revealed', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await page.evaluate(() => { S.agents = new Set(['cc']); S.range = 30; go('persona'); });
  const p = await page.evaluate(() => sharePersona().p);
  expect(p.n).toBeGreaterThanOrEqual(30);
  expect(p.code).toContain('?');
  await expect(page.locator('#main .letters')).toBeVisible();
  await page.evaluate(() => openShare());
  await expect(page.locator('#modal')).toBeHidden();
  await page.evaluate(() => openReveal());
  await expect(page.locator('#overlay')).toBeHidden();
  expect(errors).toEqual([]);
});

test('statistics-only mode blocks local Agent questions', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await page.evaluate(() => { ACT.setEngine({ dataset: { v: 'stats' } }); openAsk('overview'); });
  await expect(page.locator('#modal')).toBeHidden();
  await page.evaluate(() => { ACT.setEngine({ dataset: { v: 'agent' } }); openAsk('overview'); });
  await expect(page.locator('#modal')).toBeVisible();
  await page.evaluate(() => { ACT.setEngine({ dataset: { v: 'stats' } }); ACT.askPick({ dataset: { i: '0' } }); });
  await expect(page.locator('#askA')).toContainText('选一个问题');
  expect(errors).toEqual([]);
});

test('saving a generated Skill twice creates one library item', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await page.evaluate(() => { S.studio.type = 'Skill'; ACT.studioSave(); ACT.studioSave(); S.lib.tab = 'local'; go('library'); });
  expect(await page.evaluate(() => LIB.filter((x) => x.id === 'my-pr-wrapup').length)).toBe(1);
  await expect(page.locator('#main')).toContainText('本地生成');
  expect(errors).toEqual([]);
});

test('palette session navigation adapts incompatible filters', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  const title = await page.evaluate(() => {
    S.agents = new Set(['cx']); S.project = 'surge'; S.topic = 'net'; S.outcome = 'fail'; S.fric = '方向错误'; S.hour = 0; S.range = 7;
    const item = palItems('Tandem').find((x) => x.g === '会话' && x.sub.startsWith('Claude Code ·'));
    item.run();
    return item.t;
  });
  await expect(page.locator('#main .band')).toContainText(title);
  await expect(page.locator('#main .band')).toContainText('Claude Code');
  const oldTitle = await page.evaluate(() => {
    const old = ALL.find((s) => s.a === 'cc' && !s.live && s.d < 90);
    ACT.openSession({ dataset: { id: old.id } });
    return old.title;
  });
  await expect(page.locator('#main .band')).toContainText(oldTitle);
  expect(errors).toEqual([]);
});

test('expanded HUD hides a disabled secondary source and its alerts', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await page.evaluate(() => { simEvent('stuck'); S.hud.open = true; render(); openSettings('sources'); });
  await page.locator('#set [data-act="setSrc"][data-a="cx"]').click();
  await closeAll(page);
  await page.evaluate(() => { S.hud.open = true; render(); renderPop(); });
  await expect(page.locator('#hud')).toBeVisible();
  await expect(page.locator('#hud')).not.toContainText('Codex');
  await expect(page.locator('#pop')).not.toContainText('Codex');
  await page.evaluate(() => simEvent('waiting'));
  await expect(page.locator('#hud')).not.toContainText('Codex');
  expect(errors).toEqual([]);
});

test('panel and desktop statistics omit excluded sessions', async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'behavior coverage runs once, at the default size');
  const errors = await openDemo(page);
  await page.evaluate(() => { ALL.filter((s) => s.d === 119).forEach((s) => S.excluded.add(s.id)); S.sim = 'idle'; renderPop(); });
  await expect(page.locator('#pop .sec').filter({ hasText: '昨天 · 9 月 30 日' })).toContainText('0 会话');
  await page.evaluate(() => { ALL.filter((s) => s.d === 120).forEach((s) => S.excluded.add(s.id)); S.sim = 'running'; S.widgets = true; render(); });
  await expect(page.locator('#widgets [data-r="sessions"] .mono').first()).toHaveText('0');
  expect(errors).toEqual([]);
});
