// Lite 四页（src/js/39-lite-pages.js）。在 mac-14 与 compact 两个尺寸都跑，覆盖窄窗口的横向溢出。
//
// 测试流程：
//  1 pages      edSet('lite') 后落在 l-home；四页依次渲染，无 pageerror、内容区无横向溢出、没有 Advance 的筛选行；
//               l-home / l-persona 有 data-hero="code"，l-persona 有 data-hero="fp"，大数字带 data-count
//  2 range      Lite 只有时间范围 seg：点 7 天后 S.range = 7，概览的会话数随之变化
//  3 filters    带着 Advance 的项目筛选进入 Lite，标题栏出现「已应用 Advance 筛选 · 清除」，点击后筛选清空
//  4 session    Lite 中 openSession 打开一个较早的会话：留在 l-sessions 并选中它；点列表另一行切换选中
//  5 edOpen     「在 Advance 中回放」切回 Advance 并打开 sessions，选中的会话保持
//  6 recs       前三条建议卡；主按钮打开安装预览；安装后卡片显示「已应用」与「撤销」
//  7 persona    画像页吸收揭晓第 05 步：已读取 N 个会话 · N 次工具调用、匹配度、「已经知道的」四行与揭晓页同源（genFacts / genCands）；
//               会话数写成「N 个会话」，页面上没有「n=」；没有「AI 撰写」标记
//  8 empty      没有会话时概览与画像页不出现「????」：虚线花形 + 一句说明 + 导入会话 / 数据源设置
import { test, expect } from '@playwright/test';
import { openDemo } from './helpers.mjs';

const LITE = ['l-home', 'l-persona', 'l-sessions', 'l-recs'];

async function toLite(page) {
  await page.evaluate(() => edSet('lite'));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-home');
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'lite');
}
const goLite = async (page, r) => { await page.evaluate((x) => go(x), r); await expect.poll(() => page.evaluate(() => S.route)).toBe(r); };
const overflow = (page) => page.evaluate(() => { const c = $('#content'); return c.scrollWidth - c.clientWidth; });

test('Lite: four pages render without errors, overflow or the Advance filter row', async ({ page }) => {
  const errors = await openDemo(page);
  await toLite(page);
  for (const r of LITE) {
    await goLite(page, r);
    await expect(page.locator('#content .lite')).toBeVisible();
    expect(await overflow(page)).toBeLessThanOrEqual(0);
    await expect(page.locator('#content .frow')).toHaveCount(0);
    await expect(page.locator('#main .tbar .seg button[data-act="range"]')).toHaveCount(4);
    await expect(page.locator('#content .l-adv').first()).toBeAttached();
  }
  await goLite(page, 'l-home');
  await expect(page.locator('#content [data-hero="code"]')).toHaveText(await page.evaluate(() => personaNow().code));
  expect(await page.locator('#content [data-count]').count()).toBeGreaterThanOrEqual(4);
  await goLite(page, 'l-persona');
  await expect(page.locator('#content [data-hero="code"]')).toBeVisible();
  await expect(page.locator('#content [data-hero="fp"] svg.fp2')).toBeVisible();
  await expect(page.locator('#content .l-ax')).toHaveCount(4);
  // 一屏一个结论：每页至多三个主区块（加一行去 Advance 的链接）
  for (const r of LITE) { await goLite(page, r); expect(await page.locator('#content .lite > :not(.l-foot)').count()).toBeLessThanOrEqual(3); }
  expect(errors).toEqual([]);
});

test('Lite: the range seg is the only filter and recomputes the page', async ({ page }) => {
  const errors = await openDemo(page);
  await toLite(page);
  const n30 = await page.locator('#content .l-tiles .v').first().getAttribute('data-count');
  // 欢迎通知会盖住标题栏右上角，直接点按钮本身
  await page.evaluate(() => $('#main .tbar .seg button[data-v="7"]').click());
  await expect.poll(() => page.evaluate(() => S.range)).toBe(7);
  await expect(page.locator('#main .tbar .seg button[data-v="7"]')).toHaveClass(/on/);
  const n7 = await page.locator('#content .l-tiles .v').first().getAttribute('data-count');
  expect(+n7).toBe(await page.evaluate(() => sel().length));
  expect(+n7).toBeLessThan(+n30);
  await expect(page.locator('#main .tbar .meta')).toContainText(await page.evaluate(() => sel().length + ' 个会话'));
  expect(errors).toEqual([]);
});

test('Lite: Advance filters show a clear chip in the title bar', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => { S.project = 'confluo'; render(); });
  await toLite(page);
  const chip = page.locator('#main .tbar [data-act="liteClear"]');
  await expect(chip).toContainText('已应用 Advance 筛选');
  await chip.click();
  await expect.poll(() => page.evaluate(() => S.project)).toBe(null);
  await expect(page.locator('#main .tbar [data-act="liteClear"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('Lite: openSession selects the session on l-sessions; edOpen returns to Advance', async ({ page }) => {
  const errors = await openDemo(page);
  await toLite(page);
  // 一个不在「最近 8 个」里的较早会话
  const id = await page.evaluate(() => ALL.filter((s) => s.d >= 95 && s.d <= 100 && !s.live && sourceEnabled(s)).at(-1).id);
  await page.evaluate((x) => ACT.openSession({ dataset: { id: x } }), id);
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-sessions');
  expect(await page.evaluate(() => S.ed)).toBe('lite');
  await expect(page.locator('#content .srow.sel')).toHaveAttribute('data-id', id);
  await expect(page.locator('#content .l-stitle')).toHaveText(await page.evaluate((x) => BYID[x].title, id));
  await expect(page.locator('#content .l-steps li').first()).toBeVisible();
  // 点列表里另一行
  const other = page.locator('#content .srow:not(.sel)').first();
  const oid = await other.getAttribute('data-id');
  await other.click();
  await expect(page.locator('#content .srow.sel')).toHaveAttribute('data-id', oid);
  expect(await page.evaluate(() => S.sess.sel)).toBe(oid);
  expect(await overflow(page)).toBeLessThanOrEqual(0);
  // 去 Advance 回放：切版本、打开 sessions、选中不变
  await page.locator('#content .l-adv[data-r="sessions"]').click();
  await expect.poll(() => page.evaluate(() => [S.ed, S.route])).toEqual(['advance', 'sessions']);
  await expect(page.locator('#win')).toHaveAttribute('data-ed', 'advance');
  expect(await page.evaluate(() => S.sess.sel)).toBe(oid);
  expect(errors).toEqual([]);
});

test('Lite: recs page shows the top three and reflects an install', async ({ page }) => {
  const errors = await openDemo(page);
  await toLite(page);
  await goLite(page, 'l-recs');
  const cards = page.locator('#content .l-rc');
  await expect(cards).toHaveCount(3);
  const ids = await cards.evaluateAll((els) => els.map((e) => e.dataset.id));
  expect(ids).toEqual(await page.evaluate(() => visibleRecs().slice().sort((a, b) => recRank(b.id) - recRank(a.id)).slice(0, 3).map((r) => r.id)));
  // 第一条的主按钮走现有安装流程（预览 sheet）
  const first = await page.evaluate((x) => RECI[x].primary, ids[0]);
  if (!/教程|交给|复制/.test(first)) {
    await cards.first().locator('.rc-foot .btn.p').click();
    await expect(page.locator('#modal')).toBeVisible();
    await page.evaluate(() => closeModal());
  }
  await page.evaluate((x) => { S.installed.set(x, { days: 1, at: Date.now(), scope: 'global', target: RECI[x].target, off: 0 }); render(); }, ids[0]);
  await expect(cards.first()).toHaveClass(/inst/);
  await expect(cards.first()).toContainText('已应用');
  await expect(cards.first().locator('[data-act="uninstall"]')).toBeVisible();
  // 概览的「本周最值得做的一件事」换成下一条未安装的
  await goLite(page, 'l-home');
  await expect(page.locator('#content .l-one .rc-title')).toHaveText(await page.evaluate((x) => RECI[x].title, ids[1]));
  expect(errors).toEqual([]);
});

test('Lite: persona page carries the reveal summary on the same numbers', async ({ page }) => {
  const errors = await openDemo(page);
  await toLite(page);
  await goLite(page, 'l-persona');
  const want = await page.evaluate(() => { const L = personaScope(); const p = persona(L); return { n: L.length, tools: stats(L).tools, facts: genFacts(L).map((f) => f[0] + f[2]), sim: genCands(p).find((c) => c.c === p.code).sim, pn: p.n }; });
  await expect(page.locator('#content .l-count')).toHaveText('已读取 ' + want.n.toLocaleString('en-US') + ' 个会话 · ' + want.tools.toLocaleString('en-US') + ' 次工具调用');
  await expect(page.locator('#content .l-match .bdg')).toHaveText('匹配度 ' + want.sim + '%');
  await expect(page.locator('#content .l-match')).toContainText(want.pn.toLocaleString('en-US') + ' 个会话');
  expect(await page.locator('#content .l-fact .l-ft').allTextContents()).toEqual(want.facts);
  await expect(page.locator('#content [data-hero="code"] .L')).toHaveCount(4);
  await expect(page.locator('#content [data-act="reveal"]')).toBeVisible();
  await expect(page.locator('#content [data-act="share"]')).toBeVisible();
  for (const r of ['l-home', 'l-persona']) {
    await goLite(page, r);
    expect(await page.locator('#main').innerText()).not.toMatch(/\bn\s*[=≈]\s*\d/);
    expect(await page.locator('#main').innerText()).not.toContain('AI 撰写');
  }
  expect(errors).toEqual([]);
});

test('Lite and overview: no sessions shows a flower outline and a way to import, never ????', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => { ALL.splice(0, ALL.length); });
  await toLite(page);
  for (const r of ['l-home', 'l-persona']) {
    await goLite(page, r);
    await expect(page.locator('#content [data-lv="pers-empty"] svg.e-bloom')).toBeVisible();
    await expect(page.locator('#content [data-lv="pers-empty"] [data-act="liteImport"]')).toBeVisible();
    expect(await page.locator('#main').innerText()).not.toContain('????');
  }
  await page.evaluate(() => edSet('advance', 'overview'));
  await expect.poll(() => page.evaluate(() => S.ed + '|' + S.route)).toBe('advance|overview');
  await expect(page.locator('#content .ov-pers [data-lv="pers-empty"] svg.e-bloom')).toBeVisible();
  expect(await page.locator('#main').innerText()).not.toContain('????');
  await page.evaluate(() => edSet('lite', 'l-persona'));
  await expect.poll(() => page.evaluate(() => S.ed + '|' + S.route)).toBe('lite|l-persona');
  await page.locator('#content [data-act="liteImport"]').click();
  await expect(page.locator('#overlay')).toBeVisible();
  expect(errors).toEqual([]);
});
