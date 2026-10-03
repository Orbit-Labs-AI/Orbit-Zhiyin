// Settings ↔ native capabilities (57-settings.js NATV, 97-live-studio-settings.js notify / statusBadge, 20-ui.js setTheme)
// and the settings dialog semantics. The fake host below lists the features of the native-shell contract and answers the
// request/reply messages the way apps/desktop/Orbit.swift does: 'tandem:<type>' (notify: 'tandem:notified') with the same id.
//  1. browser      no native rows (登录时启动 / 系统通知), the simulated menu bar keeps its 角标 column, no console errors
//  2. native       loginItem get/set (+ rollback on failure), notificationStatus denied → 打开系统设置, appearance, no fake lights
//  3. old shell    features missing → rows and the 菜单栏角标 column hidden
//  4. keyboard     ⌘, (host command) focuses the settings dialog, Tab stays inside, Esc returns to the opener; sheets are named
//  5. live native  badge frames → statusBadge warn / none, 预览通知 → system notify (force) and the delivered:false reason
//  6. live sources discovery ids spelled differently from the about mappers are not listed as 未检测到; index count labelled
import { pathToFileURL } from 'node:url';
import { test, expect } from '@playwright/test';
import { ADV_FILE, stubGateway, openLive, collectErrors, sseText } from './live-helpers.mjs';

const URL0 = pathToFileURL(ADV_FILE).href;
const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at the default size');
const FULL = ['window', 'notify', 'prefs', 'commands', 'loginItem', 'statusBadge', 'notificationStatus', 'openNotificationSettings', 'notifyResult', 'appearance'];

async function host(page, features, o) {
  await page.addInitScript(([features, o]) => {
    window.__ORBIT_NATIVE__ = { v: 1, app: '0.0.4', platform: 'macos', features };
    window.__nativeMsgs = []; window.__login = !!o.login; window.__loginFail = false; window.__notifAuth = o.auth || 'denied';
    const reply = (ev, m, d) => setTimeout(() => window.dispatchEvent(new CustomEvent(ev, { detail: Object.assign({ id: m.id }, d) })), 10);
    window.webkit = { messageHandlers: { tandem: { postMessage(m0) {
      const m = JSON.parse(JSON.stringify(m0)); if (m.type === 'dragRegions') return;
      window.__nativeMsgs.push(m);
      if (m.type === 'loginItem') {
        if (m.enabled === undefined) reply('tandem:loginItem', m, { enabled: window.__login, status: window.__login ? 'enabled' : 'notRegistered' });
        else if (window.__loginFail) reply('tandem:loginItem', m, { enabled: window.__login, status: 'notRegistered', error: '系统拒绝了请求' });
        else { window.__login = !!m.enabled; reply('tandem:loginItem', m, { enabled: window.__login, status: window.__login ? 'enabled' : 'notRegistered' }); }
      }
      if (m.type === 'notificationStatus') reply('tandem:notificationStatus', m, { status: window.__notifAuth });
      if (m.type === 'notify' && m.force) reply('tandem:notified', m, window.__notifAuth === 'denied' ? { delivered: false, reason: 'denied' } : { delivered: true });
    } } } };
  }, [features, o || {}]);
}
const msgs = (page, type) => page.evaluate((t) => window.__nativeMsgs.filter((m) => m.type === t), type);
async function openFile(page) {
  await page.goto(URL0);
  await page.waitForFunction(() => typeof S !== 'undefined' && !!document.querySelector('#content'));
}
const tab = (page, t) => page.evaluate((t) => { S.setTab = t; renderSet(); if (t === 'notify') NATV.notifGet(); }, t);

test('1. browser: native-only rows hidden, badge column kept, no errors', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await openFile(page);
  await page.evaluate(() => openSettings('general'));
  await expect(page.locator('#set')).toContainText('外观');
  await expect(page.locator('#set')).not.toContainText('登录时启动');
  await expect(page.locator('#set .lights')).toHaveCount(1);   // the browser demo keeps its drawn window
  await tab(page, 'notify');
  await expect(page.locator('#set .nmx thead th')).toHaveCount(4);
  await expect(page.locator('#set .nmx thead')).toContainText('菜单栏角标');
  await expect(page.locator('#set [data-tl="notif-auth"]')).toHaveCount(0);
  await expect(page.locator('#set')).not.toContainText('「演示」菜单');
  await expect(page.locator('#set [data-act="setTestNotif"]')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('2. native: login item, notification permission, appearance, no fake lights', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await host(page, FULL, { login: true, auth: 'denied' });
  await openFile(page);
  await page.evaluate(() => openSettings('general'));
  const sw = page.locator('#set [data-act="setLogin"]');
  await expect(sw).toHaveAttribute('aria-checked', 'true');   // read from the system, not the page default
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  expect((await msgs(page, 'loginItem')).map((m) => [m.op, m.enabled])).toEqual([['get', undefined], ['set', false]]);
  await page.evaluate(() => { window.__loginFail = true; });
  await sw.click();
  await expect(page.locator('#toast')).toContainText('系统拒绝了请求');
  await expect(sw).toHaveAttribute('aria-checked', 'false');   // rolled back
  await expect(page.locator('#set .lights')).toHaveCount(0);
  await expect(page.locator('#set .set-x')).toHaveCount(1);
  await page.locator('#set [data-act="setTheme"][data-v="dark"]').click();
  await expect.poll(() => msgs(page, 'appearance').then((a) => a.map((m) => m.mode))).toContain('dark');
  await expect(page.locator('#set')).toContainText('只影响 Orbit');
  await page.locator('#set [data-act="setTheme"][data-v="system"]').click();
  await expect.poll(() => msgs(page, 'appearance').then((a) => a.pop().mode)).toBe('system');
  await page.locator('#set [data-act="setTab"][data-v="notify"]').click();
  await expect(page.locator('#set [data-tl="notif-auth"]')).toHaveAttribute('data-v', 'denied');
  await expect(page.locator('#set .nmx thead th')).toHaveCount(4);
  await page.locator('#set [data-act="setNotifSys"]').click();
  expect((await msgs(page, 'openNotificationSettings')).length).toBe(1);
  expect(errors).toEqual([]);
});

test('3. older shell: missing features hide the rows and the badge column', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  await host(page, ['window', 'notify', 'prefs', 'commands']);
  await openFile(page);
  await page.evaluate(() => openSettings('general'));
  await expect(page.locator('#set')).not.toContainText('登录时启动');
  await page.evaluate(() => setTheme('dark'));
  expect((await msgs(page, 'appearance')).length).toBe(0);
  await tab(page, 'notify');
  await expect(page.locator('#set .nmx thead th')).toHaveCount(3);
  await expect(page.locator('#set .nmx')).not.toContainText('菜单栏角标');
  await expect(page.locator('#set')).not.toContainText('菜单栏角标仍然更新');
  await expect(page.locator('#set [data-tl="notif-auth"]')).toHaveCount(0);
  await tab(page, 'sources');
  await expect(page.locator('#set')).not.toContainText('状态角标');
  expect((await msgs(page, 'loginItem')).length).toBe(0);
  expect(errors).toEqual([]);
});

test('4. keyboard: settings dialog takes and returns focus; sheets have names', async ({ page }) => {
  ONLY();
  await openFile(page);
  const set = page.locator('#set');
  await page.locator('.tsearch').first().focus();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('tandem:command', { detail: { cmd: 'settings' } })));
  await expect(set).toHaveAttribute('role', 'dialog');
  await expect(set).toHaveAttribute('aria-labelledby', 'setName setTitle');
  await expect(page.locator('#setName')).toHaveText('设置');
  const inside = () => page.evaluate(() => document.getElementById('set').contains(document.activeElement));
  expect(await inside()).toBe(true);
  let out = 0;
  for (let i = 0; i < 40; i++) { await page.keyboard.press('Tab'); if (!(await inside())) out++; }
  expect(out).toBe(0);
  await page.keyboard.press('Escape');
  await expect(set).toBeHidden();
  expect(await page.evaluate(() => document.activeElement.classList.contains('tsearch'))).toBe(true);
  // opened with <body> focused: closing lands on the page title, not <body>
  await page.evaluate(() => { document.activeElement.blur(); openSettings(); });
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
  // command palette and about sheet
  await page.evaluate(() => openPalette());
  await expect(page.locator('#modal')).toHaveAttribute('aria-label', '命令面板');
  await page.keyboard.press('Escape');
  await page.evaluate(() => openAbout());
  await expect(page.locator('#modal')).toHaveAttribute('aria-labelledby', 'modalTitle');
  await expect(page.locator('#modalTitle')).toContainText('关于');
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
});

test('5. live native: statusBadge from badge frames, preview notification goes to the system', async ({ page }) => {
  ONLY();
  const errors = collectErrors(page);
  const gw = await stubGateway(page, 'core');
  await host(page, FULL, { auth: 'denied' });
  gw.push([{ event: 'notification', data: { id: 7, type: 'awaiting_approval', title: '等你确认', body: 'demo', channels: ['badge'] } }]);
  await openLive(page);
  await expect.poll(() => msgs(page, 'statusBadge').then((a) => a.map((m) => m.state)), { timeout: 8000 }).toContain('warn');
  await page.evaluate(() => { S.waitOpen = false; render(); });
  await expect.poll(() => msgs(page, 'statusBadge').then((a) => a.pop().state)).toBe('none');
  await page.evaluate(() => openSettings('notify'));
  await page.locator('#set [data-act="setTestNotif"]').click();
  await expect.poll(() => msgs(page, 'notify').then((a) => a.filter((m) => m.force).length), { timeout: 8000 }).toBe(1);
  await expect(page.locator('#toast')).toContainText('系统通知没有送达');
  expect(errors).toEqual([]);
});

test('6. live sources: no detected agent under 未检测到; index count labelled', async ({ page }) => {
  ONLY();
  const gw = await stubGateway(page, 'core', {
    'GET /v1/app/discovery': [
      { id: 's-cc', agent: 'claude', root: '/Users/demo/.claude', files: 3, status: 'available', enabled: true },
      { id: 's-cx', agent: 'codex', root: '/Users/demo/.codex', files: 3, status: 'available', enabled: true },
      { id: 's-ds', agent: 'deepseek', root: '/Users/demo/.dsh', files: 3, status: 'available', enabled: true }
    ],
    'GET /v1/app/about': { app: { name: 'tandem', version: '0.0.4' }, components: { mappers: ['claude_code', 'codex', 'dsh', 'gemini'] } },
    'GET /v1/app/state': { settings: {}, sources: [], jobs: [], storage: { projection: 'present', counts: { sessions: 99999 } } }
  });
  await openLive(page);
  await page.evaluate(() => openSettings('sources'));
  await expect.poll(() => page.locator('#set [data-act="setAddSrc"][data-v]').evaluateAll((els) => els.map((e) => e.dataset.v)), { timeout: 8000 }).toEqual(['gemini']);
  await expect(page.locator('#set')).toContainText('含子会话共 99,999 个');
  void gw;
});

test('7. persona method: pole words, 你 follows the persona period, no %', async ({ page }) => {
  ONLY();
  await openFile(page);
  await page.evaluate(() => { S.persona.period = '90'; openMethod(); });
  const m = page.locator('#modal');
  await expect(m).toContainText('即兴');
  await expect(m).not.toContainText('自主度');
  const you = m.locator('[data-method="you"]');
  if (await you.count()) {
    await expect(you.first()).toContainText('你 · 近 90 天');
    expect(await you.first().textContent()).not.toMatch(/%/);
  }
});
