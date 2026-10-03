// Agent filter default (bug 5): the top-bar Agent filter starts as every imported agent ("Agent · 全部 N", every menu row
// checked) and stays that way after live hydrates; only an explicit uncheck is remembered, new agents join the filter
// unless unchecked, and a stale single selection (agents that no longer exist) heals back to all. Stub gateway, fixtures
// in prototypes/shared/fixtures/core.
// Test flow (mac-14, live mode):
//  1 default      live spine hydrates → title 「Agent · 全部 N」, every dropdown row has ✓, project filter 「全部 M」
//  2 explicit     uncheck one agent → it stays unchecked after a re-hydrate; an agent that appears later joins the filter
//  3 heal         a selection of ids that no longer exist (stale single pick) → hydrate restores all agents
//  4 lite         Lite has no filter row: no 「筛选」 chip by default, and one appears only after an explicit uncheck
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const title = (page) => page.locator('.frow [data-act="agentMenu"]');
const checks = async (page) => {
  await title(page).click();
  const marks = await page.locator('#dd .ck').evaluateAll((els) => els.map((e) => e.textContent));
  await page.keyboard.press('Escape');
  return marks;
};
// re-runs the spine hydrate with the current rows, optionally without one agent's rows
const rehydrate = (page, dropAgent) => page.evaluate((drop) => {
  window.__rows = window.__rows || ALL.map((s) => s.raw);
  const rows = window.__rows.filter((r) => !drop || LV.AGENTS[String(r.a).toLowerCase()].id !== drop);
  LV.hydrate({ rows, projects: [], agents: [] }); render();
}, dropAgent || null);

test('default: every imported agent is checked and the title reads 全部 N', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const [ag, pj] = await page.evaluate(() => [AG.length, PJ.length]);
  expect(ag).toBeGreaterThan(1);
  await expect(title(page)).toHaveText('Agent · 全部 ' + ag);
  await expect(page.locator('.frow [data-act="projectMenu"]')).toHaveText('项目 · 全部 ' + pj);
  expect(await checks(page)).toEqual(Array(ag).fill('✓').concat(['']));   // the trailing 「全部 Agent」 row has no mark
  await rehydrate(page);
  await expect(title(page)).toHaveText('Agent · 全部 ' + ag);
  expect(errors).toEqual([]);
});

test('explicit uncheck survives hydrates; a new agent joins the filter', async ({ page }) => {
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const ids = await page.evaluate(() => AG.map((a) => a.id));
  const [off, gone] = [ids[0], ids[ids.length - 1]];
  await title(page).click();
  await page.locator('#dd button[data-i="1"]').click();                  // row 0 is the hint, row 1 the first agent
  await expect(title(page)).toHaveText('Agent · ' + (ids.length - 1) + ' 个');
  await rehydrate(page);
  expect(await page.evaluate((o) => S.agents.has(o), off)).toBe(false);
  await rehydrate(page, gone);                                           // the last agent disappears …
  await rehydrate(page);                                                 // … and comes back as a new one: joins the filter
  const st = await page.evaluate(([o, g]) => ({ off: S.agents.has(o), gone: S.agents.has(g), n: S.agents.size, ag: AG.length }), [off, gone]);
  expect(st).toEqual({ off: false, gone: true, n: ids.length - 1, ag: ids.length });
});

test('a stale selection of agents that no longer exist heals to all', async ({ page }) => {
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const ag = await page.evaluate(() => { S.agents = new Set(['ghost']); S.agentOff = new Set(AG.map((a) => a.id)); return AG.length; });
  await rehydrate(page);
  await expect(title(page)).toHaveText('Agent · 全部 ' + ag);
  expect(await page.evaluate(() => S.agentOff.size)).toBe(0);
});

test('Lite shows no filter chip by default and one after an explicit uncheck', async ({ page }) => {
  await stubGateway(page, 'core');
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await page.evaluate(() => { go('overview'); edSet('lite'); });
  await expect.poll(() => page.evaluate(() => S.ed)).toBe('lite');
  await expect(page.locator('.l-fchip')).toHaveCount(0);
  await page.evaluate(() => { S.agents.delete(AG[0].id); render(); });
  await expect(page.locator('.l-fchip')).toHaveCount(1);
  await rehydrate(page);
  await expect(page.locator('.l-fchip')).toHaveCount(1);
  await page.locator('.l-fchip').click();
  await expect(page.locator('.l-fchip')).toHaveCount(0);
  expect(await page.evaluate(() => [S.agents.size === AG.length, S.agentOff.size])).toEqual([true, 0]);
});
