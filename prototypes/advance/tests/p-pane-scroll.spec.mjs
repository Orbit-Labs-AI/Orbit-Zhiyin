// 窗格独立滚动（styles/88-panes.css + js/88-panes.js）：主从分栏并排时各窗格自己滚，页面不滚；堆叠时退回整页滚动。
// 流程：
//   1. mac-14：会话轨迹、优化建议、生成工坊、导出分享卡里，对每个窗格滚动滚轮 → 只有它动，其他窗格与 #content 不动；
//      从别页进入会话页时，列表里靠后的选中行在列表窗格内可见，#content 不滚。
//   2. 全部尺寸：内容列够宽（≥ 800px）时会话页进入窗格模式且 #content 不溢出，否则整页滚动。
import { test, expect } from '@playwright/test';
import { openDemo, go, settle } from './helpers.mjs';

const tops = (page, sels) => page.evaluate((sels) => sels.map((s) => Math.round(document.querySelector(s).scrollTop)), sels);

async function onlyThisScrolls(page, panes) {
  const all = ['#content', ...panes];
  for (const p of panes) {
    await page.evaluate((all) => all.forEach((s) => { document.querySelector(s).scrollTop = 0; }), all);
    // locator.hover() waits for the pane to be stable (window/pane animations under parallel load), then the wheel goes to it
    const box = await page.locator(p).boundingBox();
    await page.locator(p).hover({ position: { x: Math.round(box.width / 2), y: Math.min(60, Math.round(box.height / 2)) } });
    await page.mouse.wheel(0, 240);
    await expect.poll(async () => (await tops(page, [p]))[0], p + ' scrolls').toBeGreaterThan(0);
    expect(await tops(page, all.filter((s) => s !== p)), 'only ' + p + ' moved').toEqual(all.filter((s) => s !== p).map(() => 0));
  }
}

test('each pane scrolls on its own', async ({ page }, info) => {
  test.skip(info.project.name !== 'mac-14', 'interaction runs once, at the default size');
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await onlyThisScrolls(page, ['#slist', '#content .sess>.stack']);
  await go(page, 'recs');
  await onlyThisScrolls(page, ['#content .recs>.stack', '#content .recs>:last-child']);
  await go(page, 'studio');
  await onlyThisScrolls(page, ['#content .studio>.card:nth-child(1)', '#content .studio>.card:nth-child(3)']);
  // Lite 会话轨迹（F12）：列表与详情各自滚动；窗口变矮后仍然是两个窗格各滚各的
  await page.evaluate(() => edSet('lite', 'l-sessions'));
  await expect.poll(() => page.evaluate(() => S.ed + '|' + S.route)).toBe('lite|l-sessions');
  await settle(page);
  // 默认高度下两栏都放得下：整页不溢出（不会出现整页一起滚）；窗口变矮后两栏各自滚
  expect(await page.evaluate(() => $('#content').scrollHeight - $('#content').clientHeight)).toBeLessThanOrEqual(1);
  await page.evaluate(() => { S.win.h = 640; applyWin(); });
  await settle(page);
  await onlyThisScrolls(page, ['#content .l-sess>.card>.slist', '#content .l-sess>.stack']);
  await page.evaluate(() => { S.win.h = null; applyWin(); edSet('advance', 'sessions'); });
  await expect.poll(() => page.evaluate(() => S.ed + '|' + S.route)).toBe('advance|sessions');
  await settle(page);
  // the selected session stays visible inside the list pane
  await page.evaluate(() => { S.sess.sel = sessList()[40].id; go('sessions'); });
  await settle(page);
  expect(await page.evaluate(() => { const l = $('#slist'), r = l.querySelector('.srow.sel').getBoundingClientRect(), p = l.getBoundingClientRect(); return [r.top >= p.top - 1 && r.bottom <= p.bottom + 1, $('#content').scrollTop]; })).toEqual([true, 0]);
  // share sheet on a short window: preview and options scroll apart
  await page.evaluate(() => { S.win.h = 600; applyWin(); go('persona'); openShare(); });
  await settle(page);
  await onlyThisScrolls(page, ['#shareBody>:nth-child(1)']);
  expect(await tops(page, ['#modal', '#shareBody>:nth-child(2)'])).toEqual([0, 0]);
  expect(errors).toEqual([]);
});

test('pane mode only while the split is side by side', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  const s = await page.evaluate(() => ({ w: $('#main').clientWidth, flex: getComputedStyle($('#content')).display === 'flex', over: $('#content').scrollHeight - $('#content').clientHeight }));
  expect(s.flex, 'pane mode at ' + s.w + 'px').toBe(s.w >= 800);
  if (s.flex) expect(s.over).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
