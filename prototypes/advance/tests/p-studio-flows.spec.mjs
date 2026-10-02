// Branch ui/p-studio-flows: A9 studio workflow, command palette, ask-the-local-agent, exports and first launch / reveal.
// Runs once, at mac-14 (behaviour does not depend on the window size; the layout is covered by smoke + screenshots).
//
// Test flow:
//  1 context pack   the token stack has one segment per ticked item and a budget mark; ticking「原始对话片段」pushes the total
//                   over the 24k budget (bar turns critical, log warns); redaction hits follow the ticked items; the per-item
//                   preview sheet lists samples with placeholders when redaction is on and raw values when it is off;
//                   an empty pack cannot start a run (BUG-38)
//  2 workflow       a v1 run walks 6 steps in order, streams the draft, shows four check rows (spec / safety / replay with
//                   three session rows / judge), then marks the artifact「待审阅」; the quick template skips the checks
//                   (rows read「已跳过」) and the strict template adds a cross-check step (BUG-81)
//  3 run guards     while running the type is locked (BUG-33) and studioStart / ⌘↩ is ignored (BUG-34); typing in the goal box
//                   keeps focus and caret across the per-step redraw (BUG-35); a redraw while typing on another page does not
//                   steal focus (BUG-67); stopping keeps the partial draft
//  4 artifact       install → confirm marks the run installed (button reads「已安装」, undo row appears) and refuses a second
//                   install (BUG-37); saving to the library twice yields one item plus a toast (BUG-36); history lists only
//                   studio output (BUG-86); the ask sheet's「交给生成工坊」does not wipe a running run (BUG-39)
//  5 palette        ⌘K while the first-launch overlay is open does nothing (BUG-53); Return during IME composition does not run
//                   a result (BUG-56); after picking a page focus lands on the page title, not <body> (BUG-59)
//  6 ask / export   the figma answer follows the installed state (BUG-21); the report's persona uses the filtered set and
//                   names the filter (BUG-06)
//  7 first launch   Space on a source checkbox keeps focus there; the progress page redraw keeps focus (BUG-54); facts ignore
//                   the main window's project filter (BUG-84); Tab cycles inside the overlay (BUG-55); reveal takes focus
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

test.describe.configure({ mode: 'parallel' });
const only = () => test.skip(test.info().project.name !== 'mac-14', 'runs once, at mac-14');
const run = (page) => page.evaluate(() => S.studio.run);
const finish = (page) => expect.poll(() => page.evaluate(() => !!(S.studio.run && S.studio.run.done)), { timeout: 20_000 }).toBe(true);

test('context pack: token stack, budget, redaction and per-item preview', async ({ page }) => {
  only();
  const errors = await openDemo(page);
  await go(page, 'studio');
  await expect(page.locator('#stTok .st-seg')).toHaveCount(3);
  await expect(page.locator('#stTok')).not.toHaveClass(/over/);
  await expect(page.locator('#stTok [data-tok]')).toHaveText(/10\.7k/);
  await expect(page.locator('[data-red]').first()).toHaveText('23');
  // Ticking raw snippets exceeds the budget; the bar turns critical and the redaction count grows.
  await page.locator('#main [data-chg="studioCtx"][data-k="raw"]').check();
  await expect(page.locator('#stTok')).toHaveClass(/over/);
  await expect(page.locator('#stTok .st-seg')).toHaveCount(4);
  await expect(page.locator('[data-red]').first()).toHaveText('31');
  // Per-item preview: placeholders while redaction is on, raw values when off; unticked items are not sent.
  await page.evaluate(() => ACT.ctxPreview());
  await expect(page.locator('#ctxPrev .st-prev')).toHaveCount(4);
  await expect(page.locator('#ctxPrev mark.rd').first()).toHaveText('[user]');
  expect(await page.locator('#ctxPrev mark.st-leak').count()).toBe(0);
  await page.locator('#ctxPrev [data-chg="studioCtx"][data-k="redact"]').uncheck();
  await expect(page.locator('#ctxPrev mark.st-leak').first()).toHaveText('alex');
  await expect(page.locator('#ctxPrev [data-red]')).toHaveText('0');
  await page.locator('#ctxPrev [data-chg="studioCtx"][data-k="raw"]').uncheck();
  await expect(page.locator('#ctxPrev .st-prev.off')).toHaveCount(1);
  await page.evaluate(() => closeModal());
  // A run over budget logs the truncation warning.
  await page.evaluate(() => { S.studio.ctx.raw = true; ACT.studioStart(); });
  await expect.poll(() => page.evaluate(() => S.studio.run.log.some((l) => l.startsWith('!')))).toBe(true);
  await page.evaluate(() => ACT.studioStop());
  // An empty pack cannot start (BUG-38).
  await page.evaluate(() => { S.studio.run = null; Object.assign(S.studio.ctx, { sum: false, fric: false, rules: false, raw: false }); ACT.studioStart(); });
  expect(await run(page)).toBeNull();
  await expect(page.locator('#toast')).toContainText('至少勾选一项');
  expect(errors).toEqual([]);
});

test('workflow: v1 walks six steps with four check rows; quick skips checks; strict adds a cross-check', async ({ page }) => {
  only();
  test.setTimeout(60_000);
  const errors = await openDemo(page);
  await go(page, 'studio');
  await expect(page.locator('.st-steps .step')).toHaveCount(6);
  await expect(page.locator('.st-chk')).toHaveCount(4);
  await expect(page.locator('.st-chk.pend')).toHaveCount(4);
  await page.evaluate(() => ACT.studioStart());
  await expect.poll(() => page.evaluate(() => S.studio.run.step)).toBe(2);
  await expect(page.locator('.st-steps .step.run .st-lines')).toBeVisible();
  await expect(page.locator('.code')).toBeVisible();
  await finish(page);
  const seen = await page.evaluate(() => S.studio.run.log.filter((l) => l.startsWith('›')).length);
  expect(seen).toBeGreaterThanOrEqual(9);
  await expect(page.locator('.st-steps .step.done')).toHaveCount(6);
  await expect(page.locator('.st-steps .st-dur i')).toHaveCount(5);
  await expect(page.locator('.st-chk.ok')).toHaveCount(4);
  await expect(page.locator('.st-chk[data-chk="replay"] .st-rp .t')).toHaveCount(3);
  await expect(page.locator('.st-chk[data-chk="judge"]')).toContainText('8.6 / 10');
  await expect(page.locator('.st-sum')).toContainText('+11 行');
  await expect(page.locator('#main .bdg', { hasText: '待审阅' })).toBeVisible();
  // Replay rows jump to the session.
  await page.locator('.st-chk[data-chk="replay"] .st-rp .t').first().click();
  await expect.poll(() => page.evaluate(() => S.route)).toBe('sessions');
  // Quick template: three steps, checks skipped (BUG-81).
  await go(page, 'studio');
  await page.evaluate(() => ACT.studioTpl());
  await page.locator('#modal input[name="tpl"][value="quick"]').check();
  await page.evaluate(() => ACT.studioTplUse());
  expect(await page.evaluate(() => [S.studio.tpl, S.studio.run])).toEqual(['quick', null]);
  await expect(page.locator('.st-steps .step')).toHaveCount(3);
  await page.evaluate(() => ACT.studioStart());
  await finish(page);
  await expect(page.locator('.st-chk.skip')).toHaveCount(4);
  await expect(page.locator('.st-chk.skip').first()).toContainText('已跳过');
  // Strict template adds the cross-check step.
  await page.evaluate(() => { S.studio.tpl = 'strict'; S.studio.run = null; render(); });
  await expect(page.locator('.st-steps .step')).toHaveCount(7);
  await expect(page.locator('.st-steps')).toContainText('交叉自检');
  expect(errors).toEqual([]);
});

test('run guards: type lock, ⌘↩ ignored, focus kept while typing, stop keeps the draft', async ({ page }) => {
  only();
  test.setTimeout(45_000);
  const errors = await openDemo(page);
  await go(page, 'studio');
  await page.evaluate(() => ACT.studioStart());
  await expect.poll(() => page.evaluate(() => S.studio.run.step)).toBeGreaterThanOrEqual(1);
  // BUG-33: the type is locked while running.
  await page.evaluate(() => ACT.studioType({ dataset: { v: '规则' } }));
  expect(await page.evaluate(() => [S.studio.type, S.studio.run.step >= 1])).toEqual(['Skill', true]);
  // BUG-34: studioStart (⌘↩) does not reset the run.
  const before = await page.evaluate(() => S.studio.run.log.length);
  await page.keyboard.press('Control+Enter');
  await page.evaluate(() => ACT.studioStart());
  expect(await page.evaluate(() => S.studio.run.log.length)).toBeGreaterThanOrEqual(before);
  expect(await page.evaluate(() => S.studio.run.stopped)).toBe(false);
  // BUG-35: typing in the goal box across step redraws keeps focus and every character.
  const goal = page.locator('#studioGoal');
  await goal.click();
  await page.keyboard.press('End');
  const typed = 'abcdefghij';
  for (const ch of typed) { await page.keyboard.type(ch); await page.waitForTimeout(140); }
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('studioGoal');
  expect(await page.evaluate(() => S.studio.goal.endsWith('abcdefghij'))).toBe(true);
  // BUG-67: a redraw of the studio while typing on another page does not steal focus.
  await go(page, 'sessions');
  await page.locator('#sessQ').click();
  await page.keyboard.type('部署');
  await finish(page);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('sessQ');
  await expect(page.locator('#sessQ')).toHaveValue('部署');
  // Stop keeps the partial draft and the type can change again.
  await go(page, 'studio');
  await page.evaluate(() => { S.studio.run = null; ACT.studioStart(); });
  await expect.poll(() => page.evaluate(() => S.studio.run.lines)).toBeGreaterThan(1);
  await page.evaluate(() => ACT.studioStop());
  const after = await page.evaluate(() => [S.studio.run.stopped, S.studio.run.lines, document.querySelectorAll('.code > div').length]);
  expect(after[0]).toBe(true);
  expect(after[2]).toBe(after[1]);
  await expect(page.locator('.st-steps .step.stop')).toHaveCount(1);
  await page.evaluate(() => ACT.studioType({ dataset: { v: '规则' } }));
  expect(await page.evaluate(() => [S.studio.type, S.studio.run])).toEqual(['规则', null]);
  expect(errors).toEqual([]);
});

test('artifact: install once with undo, save to library once, history lists studio output only, ask hand-off respects a run', async ({ page }) => {
  only();
  test.setTimeout(45_000);
  const errors = await openDemo(page);
  await go(page, 'studio');
  await expect(page.locator('[data-act="studioInstall"]')).toBeDisabled();
  await page.evaluate(() => ACT.studioStart());
  await finish(page);
  await page.locator('[data-act="studioInstall"]').click();
  await expect(page.locator('#modal')).toContainText('预览变更');
  await page.evaluate(() => { ACT.instNext(); ACT.instDo(); });
  // The install flow (51-install.js) ends on a "written" sheet with an undo countdown; close it.
  await page.evaluate(() => { if (!document.querySelector('#modal').hidden) closeModal(); });
  await expect(page.locator('#modal')).toBeHidden();
  await expect(page.locator('[data-act="studioInstall"]')).toHaveText('已安装');
  await expect(page.locator('[data-act="studioInstall"]')).toBeDisabled();
  await expect(page.locator('.st-inst')).toBeVisible();
  // BUG-37: a second install is refused.
  await page.evaluate(() => ACT.studioInstall());
  await expect(page.locator('#modal')).toBeHidden();
  await expect(page.locator('#toast')).toContainText('已经安装过');
  await page.evaluate(() => ACT.studioUndo());
  await expect(page.locator('[data-act="studioInstall"]')).toHaveText('安装');
  await expect(page.locator('.st-inst')).toHaveCount(0);
  // BUG-36: saving twice yields one library item and a toast.
  await page.evaluate(() => { ACT.studioSave(); ACT.studioSave(); });
  expect(await page.evaluate(() => LIB.filter((x) => x.id === 'my-pr-wrapup').length)).toBe(1);
  await expect(page.locator('#toast')).toContainText('已经有这一项');
  // BUG-86: history shows studio output, not install / undo records.
  await page.evaluate(() => { S.history.unshift({ t: '安装 只读命令自动放行', when: '刚刚' }); ACT.studioHistory(); });
  await expect(page.locator('#modal')).not.toContainText('只读命令自动放行');
  await expect(page.locator('#modal')).toContainText('SKILL.md（资源库）');
  await page.evaluate(() => closeModal());
  // BUG-39: hand-off from the ask sheet keeps a running run.
  await page.evaluate(() => { S.studio.run = null; ACT.studioStart(); });
  await expect.poll(() => page.evaluate(() => S.studio.run.step)).toBeGreaterThanOrEqual(1);
  await page.evaluate(() => { openAsk('overview'); ACT.askStudio(); });
  expect(await page.evaluate(() => !!S.studio.run && !S.studio.run.stopped)).toBe(true);
  await expect(page.locator('#toast')).toContainText('正在运行');
  expect(errors).toEqual([]);
});

test('palette: blocked under the overlay, IME-safe Return, focus lands on the page title', async ({ page }) => {
  only();
  const errors = await openDemo(page);
  // BUG-53: ⌘K under the first-launch overlay does nothing.
  await page.evaluate(() => openOnboarding(0));
  await page.keyboard.press('Meta+KeyK');
  await page.evaluate(() => openPalette());
  await expect(page.locator('#modal')).toBeHidden();
  await page.evaluate(() => { closeOverlay(); render(); });
  // BUG-56: Return while composing only commits the IME text.
  await page.evaluate(() => openPalette());
  const q = page.locator('#palQ');
  await expect(q).toBeFocused();
  await q.evaluate((el) => { el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true, cancelable: true })); });
  await expect(page.locator('#modal')).toBeVisible();
  await q.evaluate((el) => { el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })); });
  await expect(page.locator('#modal')).toBeVisible();
  // A settled Return runs the selected page and leaves focus on its title (BUG-59).
  await q.fill('协作人格');
  await page.keyboard.press('Enter');
  await expect(page.locator('#modal')).toBeHidden();
  await expect.poll(() => page.evaluate(() => S.route)).toBe('persona');
  await expect.poll(() => page.evaluate(() => document.activeElement && document.activeElement.tagName)).toBe('H1');
  // Picking a result with the mouse behaves the same.
  await page.evaluate(() => openPalette());
  await page.locator('#palQ').fill('工具调用');
  await page.locator('#palList .palrow').first().click();
  await expect.poll(() => page.evaluate(() => S.route)).toBe('tools');
  await expect.poll(() => page.evaluate(() => document.activeElement && document.activeElement.tagName)).toBe('H1');
  expect(errors).toEqual([]);
});

test('ask follows the figma state; the report persona uses the shared persona scope', async ({ page }) => {
  only();
  const errors = await openDemo(page);
  // BUG-21
  const a = await page.evaluate(() => [askAnswer('tools', 2), (S.installed.set('remove-figma', { days: 1 }), askAnswer('tools', 2))]);
  expect(a[0]).toContain('可以先移除');
  expect(a[1]).toContain('已经移除');
  // BUG-06: topic filter → report persona follows personaNow() (session-level filters don't change it, the note says so);
  // the filter is named in the header and the session count follows the filtered set.
  const r = await page.evaluate(() => { S.topic = 'design'; const L = sel(); const p = personaNow(); return [reportMD(), p.ok ? p.code : 'n/a', L.length]; });
  expect(r[0]).toContain('> 筛选：主题 · ');
  if (r[1] !== 'n/a') { expect(r[0]).toContain('**' + r[1]); expect(r[0]).toContain('不计入人格'); } else expect(r[0]).toContain('样本不足');
  expect(r[0]).toContain('| 会话 | ' + r[2] + ' |');
  expect(errors).toEqual([]);
});

test('first launch keeps focus on redraw, ignores main-window filters, traps Tab; reveal takes focus', async ({ page }) => {
  only();
  test.setTimeout(45_000);
  const errors = await openDemo(page);
  // BUG-84: a project filter in the main window does not shrink the first-launch facts.
  await page.evaluate(() => { S.project = 'surge'; openOnboarding(0); ACT.obNext(); });
  const n = await page.evaluate(() => obSel().length);
  expect(n).toBeGreaterThan(100);
  // BUG-54: Space on a source checkbox keeps focus on that checkbox.
  const cb = page.locator('#overlay [data-chg="obSrc"][data-a="cx"]');
  await cb.focus();
  await page.keyboard.press('Space');
  expect(await page.evaluate(() => [document.activeElement && document.activeElement.dataset.a, OB.src.has('cx')])).toEqual(['cx', false]);
  await page.keyboard.press('Space');
  expect(await page.evaluate(() => OB.src.has('cx'))).toBe(true);
  // BUG-55: Tab wraps inside the overlay.
  const btns = await page.evaluate(() => $$('#overlay button:not([disabled]), #overlay input:not([disabled])').filter((el) => el.offsetParent !== null).length);
  for (let i = 0; i < btns + 2; i++) { await page.keyboard.press('Tab'); expect(await page.evaluate(() => $('#overlay').contains(document.activeElement))).toBe(true); }
  await page.keyboard.press('Shift+Tab');
  expect(await page.evaluate(() => $('#overlay').contains(document.activeElement))).toBe(true);
  // Progress page redraws every 950 ms without stealing focus from「在后台继续」.
  await page.evaluate(() => ACT.obStart());
  await page.locator('#overlay [data-act="obBg"]').focus();
  await expect.poll(() => page.evaluate(() => OB.prog), { timeout: 4000 }).toBeGreaterThanOrEqual(1);
  expect(await page.evaluate(() => document.activeElement && document.activeElement.dataset.act)).toBe('obBg');
  await expect.poll(() => page.evaluate(() => OB.step), { timeout: 8000 }).toBe(3);
  await expect(page.locator('#overlay .serif').first()).not.toHaveText('—');
  // The reveal from the first launch uses the first-launch selection (not the main window's filters) and takes focus.
  await page.evaluate(() => ACT.obReveal());
  await expect(page.locator('#revBox')).toBeVisible();
  expect(await page.evaluate(() => document.activeElement && document.activeElement.id)).toBe('revBox');
  await page.evaluate(() => { closeOverlay(); S.project = null; render(); });
  expect(errors).toEqual([]);
});
