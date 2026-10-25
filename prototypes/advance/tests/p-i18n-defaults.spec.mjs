// New merged-edition defaults: a fresh install opens in Lite with English UI (no stored prefs), and the language can be
// switched from the View menu / Settings › 通用 › 语言 with the choice persisted. These tests deliberately do not seed
// prefs (openDemo's { lang: null, edition: null }) so they see the real first-run state.
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

test('fresh install: Lite layout and English UI by default', async ({ page }) => {
  const errors = await openDemo(page, '', { lang: null, edition: null, range: null });
  expect(await page.evaluate(() => [S.ed, S.range, I18N.lang])).toEqual(['lite', 7, 'en']);   // no stored prefs: new defaults
  // the document language follows the UI language (99-init must not overwrite what 02-i18n set)
  expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
  await expect(page.locator('#content .lite')).toBeVisible();
  // the shell and the Lite page are translated, not left in Chinese
  await expect(page.locator('#main .tbar h1')).toHaveText('Overview');
  await expect(page.locator('#side .sect .sh').first()).toContainText('Insights');
  await expect(page.locator('#side .nav button[data-act="go"]').first()).toContainText('Overview');
  await expect(page.locator('#side .nav button[data-act="go"]').nth(2)).toContainText('Session traces');
  expect(await page.evaluate(() => store.get('lang', null))).toBe(null);   // nothing written until the user switches
  expect(errors).toEqual([]);
});

test('language switch: View menu entries and Settings › 通用 › 语言 swap zh/en and persist', async ({ page }) => {
  const errors = await openDemo(page, '', { lang: null, edition: null, range: null });
  await expect(page.locator('#main .tbar h1')).toHaveText('Overview');
  // the View menu carries both languages; each item calls the same i18nSet as the settings segment
  const langs = await page.evaluate(() => MENUS.view().filter((i) => i.t === '中文' || i.t === 'English').map((i) => i.t));
  expect(langs).toEqual(['中文', 'English']);
  await page.evaluate(() => MENUS.view().find((i) => i.t === '中文').v());
  await expect(page.locator('#main .tbar h1')).toHaveText('概览');
  expect(await page.evaluate(() => [I18N.lang, document.documentElement.lang, store.get('lang', null)])).toEqual(['zh', 'zh-CN', 'zh']);
  await page.reload();
  await expect(page.locator('#main .tbar h1')).toHaveText('概览');   // stored language survives a reload
  // Settings › 通用 › 语言 switches back to English
  await page.evaluate(() => openSettings('general'));
  const en = page.locator('#set [data-act="setLang"][data-v="en"]');
  await expect(en).toBeVisible();
  await en.click();
  await expect(page.locator('#main .tbar h1')).toHaveText('Overview');
  expect(await page.evaluate(() => [I18N.lang, store.get('lang', null)])).toEqual(['en', 'en']);
  expect(errors).toEqual([]);
});
