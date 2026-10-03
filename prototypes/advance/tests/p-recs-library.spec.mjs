// A7 优化建议 + A8 资源库 + 安装闭环（branch ui/p-recs-library）。
//
// Test flow (fresh page per test; interaction tests run once at mac-14, layout checks at every project):
//  1 recs list      cards are sorted by the saving share (省时 %, the token % where time is not measured), each shows the
//                   time / token percentages of the whole trajectory, the agent dots and the resident-token share; the detail head has the three KPI cells; cards are keyboard-selectable
//                   (Enter on a focused card, BUG-61) and a double click on「不适用」strikes one card only (BUG-65)
//  2 install loop   预览 (scope「仅项目」→ the target path moves into the project, BUG-22) → 下一步 (a double click does not
//                   skip the confirmation, BUG-64) → 确认写入 → the sheet stays on「已写入」with a counting-down undo →
//                   完成 hands the remaining seconds to the toast → the card shows 追踪中 with the scope → ⌘Z undoes once
//                   and a second ⌘Z reports nothing to undo (BUG-24)
//  3 primary kinds  openInstall on a tutorial rec opens the tutorial tab instead of installing it (BUG-25); an installed
//                   rec cannot be installed twice (BUG-37)
//  4 tracking       快进 7 天 renders the ▲ timeline, one dumbbell per metric with n and a 95% interval, and a verdict
//  5 evidence       「依据 · N 个会话」leaves other session filters behind and lands on A3 (BUG-27)
//  6 library search typing re-renders the results but not the input; pinyin composition (CDP IME) is not interrupted and
//                   ends with「钩子」in the box (BUG-32)
//  7 library install「获取」on cloudflare-deploy previews the plugin's own file, marks only that item installed (BUG-28),
//                   the toolbar count equals the sheet count (BUG-29), and 撤销 removes it again
//  8 library misc   「不感兴趣」hides the card without changing「和你相似的人」(BUG-31); the sort toggle reorders the picks;
//                   the match bar has three segments and the peer bars carry the all-users tick
//  9 layout         recs and library have no horizontal overflow at any project size, light and dark
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'interaction runs once, at ' + name);
const settle = (page, ms = 450) => page.waitForTimeout(ms);   // the install sheet ignores a second click within 400 ms

test('recs cards carry the unified metric, select by keyboard, and strike one card per dismiss', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'recs');
  const saves = await page.$$eval('#content .rcard .rc-save b', (els) => els.map((e) => e.textContent));
  expect(saves.length).toBeGreaterThan(5);
  expect(saves.slice(0, 2)).toEqual(['4.3%', '3.8%']);   // 省时 · token of the top card
  expect(saves.join(' ')).not.toMatch(/h|min/);
  // sorted by the main share (the first number) inside each group（高收益 · 低成本 / 值得投入 · 需要配置）
  const groups = await page.evaluate(() => { const out = []; for (const el of document.querySelectorAll('#content .stack > *')) { if (el.classList.contains('eb')) out.push([]); else if (el.classList.contains('rcard')) { out[out.length - 1].push(parseFloat(el.querySelector('.rc-save b').textContent.replace(/[^\d.]/g, ''))); } } return out; });
  expect(groups.length).toBe(2);
  for (const g of groups) for (let i = 1; i < g.length; i++) expect(g[i]).toBeLessThanOrEqual(g[i - 1] + 1e-9);
  await expect(page.locator('#content .rcard').first().locator('.rc-ag .dot')).toHaveCount(2);
  await expect(page.locator('#content .rcard').first().locator('.rc-tok')).toContainText('常驻 +0.3%');
  await expect(page.locator('#content .rc-kpi')).toHaveCount(3);
  await expect(page.locator('#content .rc-kpis')).toContainText('预计节省');
  await expect(page.locator('#content .rc-kpi-save .v')).toHaveText('4.3%时间 3.8%token');
  await expect(page.locator('#content .rc-kpis')).toContainText('常驻 TOKEN', { ignoreCase: true });
  // keyboard: Enter on the second card selects it (BUG-61)
  const second = page.locator('#content .rcard').nth(1);
  const id = await second.getAttribute('data-id');
  await second.focus(); await page.keyboard.press('Enter');
  expect(await page.evaluate(() => S.recs.sel)).toBe(id);
  await expect(page.locator('#content .rcard.sel')).toHaveAttribute('data-id', id);
  // double click on 不适用 strikes exactly one card (BUG-65), undo restores the selection (BUG-26)
  const n0 = await page.locator('#content .rcard').count();
  await page.locator('#content .rcard.sel [data-act="dismissRec"]').dblclick();
  await expect(page.locator('#content .rcard')).toHaveCount(n0 - 1);
  expect(await page.evaluate(() => S.recs.gone.size)).toBe(1);
  await page.click('[data-act="toastAct"]');
  await expect(page.locator('#content .rcard')).toHaveCount(n0);
  expect(await page.evaluate(() => S.recs.sel)).toBe(id);
  expect(errors).toEqual([]);
});

test('install loop: scoped preview, guarded steps, written sheet with undo countdown, tracking card, single ⌘Z', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'recs');
  await page.evaluate(() => { S.recs.sel = 'pr-wrapup'; S.recs.tab = 'preview'; render(); });
  await page.check('#content input[data-chg="recScope"][value="proj"]');
  const target = await page.locator('#content .rc-pv .mono').first().textContent();
  expect(target).toMatch(/^latentskill\/\.claude\/skills\/pr-wrapup\/SKILL\.md$/);   // BUG-22: the path follows the scope
  await page.click('#content [data-act="install"][data-id="pr-wrapup"]');
  const modal = page.locator('#modal');
  await expect(modal).toContainText('预览变更');
  await expect(modal).toContainText('latentskill/.claude/skills/pr-wrapup/SKILL.md');
  await expect(modal.locator('.inst-steps > span')).toHaveCount(4);
  await settle(page);
  await modal.locator('[data-act="instNext"]').dblclick();   // BUG-64: the second click must not act
  await expect(modal).toContainText('写入 SKILL.md？');
  await expect(modal.locator('[data-act="instDo"]')).toBeVisible();
  await settle(page);
  await modal.locator('[data-act="instDo"]').dblclick();   // BUG-88: the second click stays inside the sheet
  await expect(modal).toContainText('已写入 SKILL.md');
  await expect(modal).toContainText('撤销倒计时');
  await expect(modal).toContainText('7 天效果追踪已开始');
  await expect(modal).toContainText(await page.evaluate(() => '安装前 7 天作为基准（' + recX('pr-wrapup').n[0] + ' 个会话）'));   // F15
  expect(await modal.innerText()).not.toMatch(/\bn\s*[=≈]/);
  const left0 = await modal.locator('#instLeft').textContent();
  await expect(modal.locator('#instLeft')).not.toHaveText(left0, { timeout: 2500 });
  expect(await page.evaluate(() => S.installed.get('pr-wrapup').scope)).toBe('proj');
  expect(await page.evaluate(() => S.installed.get('pr-wrapup').target)).toMatch(/^latentskill\//);
  await settle(page);
  await modal.locator('[data-act="instClose"]').click();
  await expect(modal).toBeHidden();
  await expect(page.locator('[data-act="toastAct"]')).toContainText('撤销');
  await expect(page.locator('#content .rcard[data-id="pr-wrapup"]')).toContainText('追踪中 1 / 7 天');
  await expect(page.locator('#content .rcard[data-id="pr-wrapup"]')).toContainText('仅 latentskill');
  expect(await page.evaluate(() => S.history.length)).toBe(0);   // BUG-86: install records are not studio artefacts
  expect(await page.evaluate(() => S.instLog.length)).toBe(1);
  // ⌘Z once undoes; the second ⌘Z has nothing left (BUG-24)
  await page.evaluate(() => undoInstall());
  expect(await page.evaluate(() => S.installed.has('pr-wrapup'))).toBe(false);
  await page.evaluate(() => undoInstall());
  await expect(page.locator('#toast')).toContainText('没有可以撤销的安装');
  expect(await page.evaluate(() => S.instLog.filter((x) => /^撤销/.test(x.t)).length)).toBe(1);
  expect(errors).toEqual([]);
});

test('tutorial recs open their tutorial instead of installing; an installed rec is not installed twice', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'recs');
  await page.evaluate(() => { S.recs.aud = 2; openInstall('worktree'); });   // BUG-25
  await expect(page.locator('#modal')).toBeHidden();
  expect(await page.evaluate(() => [S.recs.tab, S.recs.sel, S.installed.has('worktree')])).toEqual(['tut', 'worktree', false]);
  await page.evaluate(() => { S.installed.set('ro-allow', { days: 2, scope: 'global', target: RECI['ro-allow'].target }); openInstall('ro-allow'); });   // BUG-37
  await expect(page.locator('#modal')).toBeHidden();
  expect(await page.evaluate(() => [S.recs.sel, S.recs.tab, S.installed.size])).toEqual(['ro-allow', 'track', 1]);
  expect(errors).toEqual([]);
});

test('7-day tracking shows the ▲ timeline, a dumbbell per metric with n and interval, and a verdict', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'recs');
  await page.evaluate(() => { S.installed.set('pr-wrapup', { days: 3, scope: 'global', target: RECI['pr-wrapup'].target }); S.recs.sel = 'pr-wrapup'; S.recs.tab = 'track'; render(); });
  await expect(page.locator('#content .rc-days')).toBeVisible();
  await expect(page.locator('#content .rc-days i.on')).toHaveCount(3);
  await expect(page.locator('#content')).toContainText('第 3 / 7 天');
  await expect(page.locator('#content .rc-dlbl')).toContainText(/安装前 7 天 · \d+ 个会话/);
  await page.click('#content [data-act="ff7"]');
  await expect(page.locator('#content .rc-verdict')).toContainText('有效');
  await expect(page.locator('#content .rc-metric')).toHaveCount(3);
  await expect(page.locator('#content .rc-metric svg.vz-svg')).toHaveCount(3);
  await expect(page.locator('#content .rc-metric').first()).toContainText('95% CI');
  await expect(page.locator('#content .rc-metric').first()).toContainText('前后 12 / 11 个会话');
  await expect(page.locator('#content .rc-dlbl')).toContainText('安装前 7 天 · 12 个会话');
  await expect(page.locator('#content .rc-dlbl')).toContainText('7 天 · 11 个会话');
  expect(await page.locator('#content').innerText()).not.toMatch(/\bn\s*[=≈]/);   // F15: no n= anywhere on the recs page
  await expect(page.locator('#content .rcard[data-id="pr-wrapup"]')).toContainText('已安装 · 有效');
  // 样本不足 when either window is thin
  await page.evaluate(() => { S.installed.set('latex-hook', { days: 7, scope: 'global', target: RECI['latex-hook'].target }); S.recs.sel = 'latex-hook'; S.recs.peek = 'latex-hook'; render(); });
  await expect(page.locator('#content .rc-verdict')).toContainText('样本不足');
  expect(errors).toEqual([]);
});

test('evidence link leaves other session filters behind and lands on A3', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'recs');
  await page.evaluate(() => { S.outcome = 'fail'; S.hour = 9; S.project = 'confluo'; });
  await page.click('#content .rcard[data-id="pr-wrapup"] [data-act="recEvidence"]');
  await expect.poll(() => page.evaluate(() => S.route)).toBe('sessions');
  expect(await page.evaluate(() => [S.outcome, S.hour, S.sess.mode])).toEqual([null, null, 'single']);
  await expect(page.locator('#toast')).toContainText('依据：46 个会话');
  expect(errors).toEqual([]);
});

test('library search keeps the input and survives IME composition', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'library');
  const q = page.locator('#libQ');
  await q.focus();
  await q.pressSequentially('retry');
  await expect(q).toHaveValue('retry');
  await expect(q).toBeFocused();   // the toolbar is not re-rendered while typing
  await expect(page.locator('#content .lb-card')).toHaveCount(1);
  await expect(page.locator('#content .lb-id')).toHaveText('retry-breaker');
  await q.fill('');
  await expect(page.locator('#content .lb-card')).toHaveCount(3);
  // pinyin composition (BUG-32): composing text must not be committed by a re-render
  const cdp = await page.context().newCDPSession(page);
  await q.focus();
  for (const t of ['g', 'go', 'gou', 'gouz', 'gouzi']) await cdp.send('Input.imeSetComposition', { text: t, selectionStart: t.length, selectionEnd: t.length });
  await cdp.send('Input.insertText', { text: '钩子' });
  await expect(q).toHaveValue('钩子');
  await expect(q).toBeFocused();
  expect(await page.evaluate(() => S.lib.q)).toBe('钩子');
  await q.fill('');
  expect(errors).toEqual([]);
});

test('library install previews the item itself, counts consistently, and can be undone', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'library');
  const before = +(await page.locator('#libInstN').textContent());
  await page.click('#content [data-act="getLib"][data-id="cloudflare-deploy"]');
  const modal = page.locator('#modal');
  await expect(modal).toContainText('预览变更 · cloudflare-deploy');
  await expect(modal).toContainText('~/.claude/plugins/cloudflare-deploy/plugin.json');   // BUG-28: not Confluo/AGENTS.md
  await expect(modal).not.toContainText('AGENTS.md');
  await settle(page); await modal.locator('[data-act="instNext"]').click();
  await settle(page); await modal.locator('[data-act="instDo"]').click();
  await expect(modal).toContainText('已写入 plugin.json');
  await settle(page); await modal.locator('[data-act="instClose"]').click();
  await expect(modal).toBeHidden();
  expect(await page.evaluate(() => [S.libInst.has('cloudflare-deploy'), S.installed.size])).toEqual([true, 0]);
  await expect(page.locator('#content .lb-row:has(b:text-is("cloudflare-deploy"))')).toContainText('已安装');
  await expect(page.locator('#content .lb-row:has(b:text-is("release-verifier"))')).not.toContainText('已安装');
  await expect(page.locator('#libInstN')).toHaveText(String(before + 1));
  await page.click('[data-act="libInstalled"]');
  await expect(modal.locator('.mh h2')).toHaveText('已安装 · ' + (before + 1));   // BUG-29
  await expect(modal).toContainText('cloudflare-deploy（插件，资源库）');
  await modal.locator('[data-act="libUninstall"][data-id="cloudflare-deploy"]').click();
  await expect(modal).toBeHidden();
  await expect(page.locator('#libInstN')).toHaveText(String(before));
  expect(await page.evaluate(() => S.libInst.has('cloudflare-deploy'))).toBe(false);
  expect(errors).toEqual([]);
});

test('library hide keeps the peer statistics, sort toggle reorders, match bars and peer ticks render', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page, 'library');
  await expect(page.locator('#content .lb-card .lb-bar').first().locator('i')).toHaveCount(3);
  await expect(page.locator('#content .lb-peer em')).toHaveCount(3);
  await expect(page.locator('#content .lb-peers')).toContainText('vs 全体');
  const peers0 = await page.locator('#content .lb-peers b.mono').allTextContents();
  await expect(page.locator('#content .lb-id').first()).toHaveText('retry-breaker');   // 痛点覆盖 95 leads
  await page.click('#content [data-act="libHide"][data-id="retry-breaker"]');
  await expect(page.locator('#content .lb-id').first()).not.toHaveText('retry-breaker');
  expect(await page.locator('#content .lb-peers b.mono').allTextContents()).toEqual(peers0);   // BUG-31
  expect(await page.evaluate(() => LIB.length)).toBe(12);
  await page.click('[data-act="toastAct"]');
  await expect(page.locator('#content .lb-id').first()).toHaveText('retry-breaker');
  await page.click('#content [data-act="libSort"][data-v="match"]');
  await expect(page.locator('#content .lb-id').first()).toHaveText('worktree-conductor');   // m 94 leads
  await page.click('#content [data-act="libSort"][data-v="users"]');
  await expect(page.locator('#content .lb-id').first()).toHaveText('readonly-allowlist');   // 12,000 installs
  expect(errors).toEqual([]);
});

for (const theme of ['light', 'dark']) {
  test(`recs and library fit the window without horizontal overflow (${theme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme });
    const errors = await openDemo(page);
    await page.evaluate(() => { S.installed.set('pr-wrapup', { days: 7, scope: 'global', target: RECI['pr-wrapup'].target }); S.recs.sel = 'pr-wrapup'; S.recs.tab = 'track'; });
    for (const r of ['recs', 'library']) {
      await go(page, r);
      const over = await page.evaluate(() => { const c = document.querySelector('#main .content'); return c ? c.scrollWidth - c.clientWidth : 0; });
      expect(over, r + ' overflows by ' + over + 'px').toBeLessThanOrEqual(1);
      const clipped = await page.evaluate(() => [...document.querySelectorAll('#content .rc-kpi .v, #content .lb-id, #content .rc-save b')].filter((e) => e.scrollWidth > e.clientWidth + 1).length);
      expect(clipped, r + ' has clipped figures').toBe(0);
    }
    expect(errors).toEqual([]);
  });
}
