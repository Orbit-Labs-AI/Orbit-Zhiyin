// Page-content fixes (fix-ui-pages): empty-range widening (A), agent labels (B), project menu (C), persona copy (D/E),
// copyable page text (G). Stub gateway with the core fixtures, then re-hydrate with hand-made rows where a case needs them.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const oldRow = { id: 'session_old1', d: '2026-08-10', h: 10, mi: 5, a: 'claude_code', p: 'proj_a', title: 'Old session', dur: 12, msgs: 8, tools: 3, errors: 0, out: 'ok' };
// one session older than 30 days, as on a first import of only older history
const landOld = (page, range) => page.evaluate(([row, r]) => {
  S.range = r; LV.autoRanged = false;
  LV.hydrate({ rows: [row], projects: [{ id: 'proj_a', name: 'proj-a' }], agents: [] });
  lvAutoRange(); render();
}, [oldRow, range]);

test('A: a lone old session widens the default range once and empty pages offer the wider range', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 'core');
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  await landOld(page, 30);
  expect(await page.evaluate(() => S.range)).toBe(90);
  await expect(page.locator('.srow')).toHaveCount(1);
  // the user narrows back to 7 days: no second auto switch, every page shows the widen note instead
  await page.locator('.frow [data-act="range"][data-v="7"]').click();
  expect(await page.evaluate(() => S.range)).toBe(7);
  for (const r of ['overview', 'sessions', 'projects']) {
    await page.evaluate((x) => go(x), r);
    const note = page.locator('[data-range-note]');
    await expect(note).toBeVisible();
    await expect(note.locator('[data-act="range"]')).toHaveText(['扩大到 90 天', '看全部历史']);
  }
  await page.locator('[data-range-note] [data-act="range"][data-v="0"]').click();
  expect(await page.evaluate(() => S.range)).toBe(0);
  await expect(page.locator('[data-range-note]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('G: page text is selectable, controls are not', async ({ page }) => {
  await stubGateway(page, 'core');
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => LV.state)).toBe('ready');
  const us = await page.evaluate(() => {
    const c = document.querySelector('#content');
    const btn = c.querySelector('button');
    const txt = c.querySelector('h2, h3, .ct, .cap');
    return [getComputedStyle(c).userSelect, getComputedStyle(btn).userSelect, txt && getComputedStyle(txt).userSelect, getComputedStyle(document.querySelector('.tbar')).userSelect];
  });
  expect(us[0]).toBe('text'); expect(us[1]).toBe('none'); expect(us[2]).toBe('text'); expect(us[3]).toBe('none');
});
