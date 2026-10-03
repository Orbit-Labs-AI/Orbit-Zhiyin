// Pane scrolling（styles/88-panes.css + js/88-panes.js）：主从分栏的页面在分栏并排时各窗格独立滚动，页面本身不滚。
// 交互用例只在 mac-14 跑一次；布局用例在全部尺寸跑。
// 流程：
//   1. 分栏页（会话与轨迹、优化建议、生成工坊）：每个可滚动的窗格确实可滚（scrollHeight > clientHeight，演示数据 mac-14）；
//      在窗格上滚动鼠标滚轮后，只有这个窗格动了：其他窗格与 #content 的 scrollTop 不变，页头（引导 / 筛选行）位置不变。
//   2. Lite 会话轨迹（窗口高 600）与项目习惯（窗口拉宽到内容列 ≥ 1100px）：列表 / 详情窗格同样各自滚动。
//   3. 选中项：从别的页面进入时，列表窗格里的选中行在窗格内可见，而 #content 不滚；在列表里换一个会话 / 建议后，详情窗格
//      回到顶部，列表窗格保持原位；render() 后各窗格的位置保留；换页再回来时窗格从顶部开始。
//   4. 导出分享卡（窗口高 600）：标题与按钮留在 sheet 内，正文滚动；预览与选项两栏各自滚动，滚预览不带动选项栏与正文。
//   5. 布局（全部尺寸）：分栏并排时 #content 是 flex 列且不溢出，每个窗格的底边不超出窗口；分栏堆叠时（内容列 < 800px，
//      项目习惯 < 1100px）退回整页滚动。
import { test, expect } from '@playwright/test';
import { openDemo, go, settle } from './helpers.mjs';

const mac14 = (info) => test.skip(info.project.name !== 'mac-14', 'interaction runs once, at the default size');

// scrollTop / scrollHeight / clientHeight of each selector (null when missing)
const state = (page, sels) => page.evaluate((sels) => sels.map((s) => { const el = document.querySelector(s); return el ? { t: Math.round(el.scrollTop), sh: el.scrollHeight, ch: el.clientHeight } : null; }), sels);

// wheel over one pane, then check that it alone moved
async function wheelPane(page, panes, i) {
  const all = ['#content', ...panes];
  await page.evaluate((all) => all.forEach((s) => { document.querySelector(s).scrollTop = 0; }), all);   // start from the top
  const before = await state(page, all);
  const box = await page.locator(panes[i]).boundingBox();
  const head = () => page.evaluate(() => $('#content').firstElementChild.getBoundingClientRect().top);
  const top0 = await head();
  await page.mouse.move(box.x + box.width / 2, box.y + Math.min(80, box.height / 2));
  await page.mouse.wheel(0, 240);
  await expect.poll(async () => (await state(page, [panes[i]]))[0].t, panes[i] + ' scrolls under the wheel').toBeGreaterThan(before[i + 1].t);
  const after = await state(page, all);
  all.forEach((s, k) => { if (k !== i + 1) expect(after[k].t, s + ' must not move when ' + panes[i] + ' scrolls').toBe(before[k].t); });
  expect(await head(), 'the page head (guide / filter row) stays put').toBeCloseTo(top0, 0);
  await page.evaluate((s) => { document.querySelector(s).scrollTop = 0; }, panes[i]);
}

async function checkSplit(page, panes, scrollable) {
  const st = await state(page, ['#content', ...panes]);
  expect(st[0].sh, '#content does not scroll in pane mode').toBeLessThanOrEqual(st[0].ch + 1);
  for (let i = 0; i < panes.length; i++) {
    expect(st[i + 1], panes[i] + ' exists').not.toBeNull();
    if (!scrollable.includes(i)) continue;
    expect(st[i + 1].sh, panes[i] + ' overflows with demo data').toBeGreaterThan(st[i + 1].ch + 20);
    await wheelPane(page, panes, i);
  }
}

test('split pages scroll each pane on its own', async ({ page }, info) => {
  mac14(info);
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await checkSplit(page, ['#slist', '#content .sess>.stack'], [0, 1]);
  await go(page, 'recs');
  await checkSplit(page, ['#content .recs>.stack', '#content .recs>:last-child'], [0, 1]);
  await go(page, 'studio');
  await checkSplit(page, ['#content .studio>.card:nth-child(1)', '#content .studio>.card:nth-child(2)', '#content .studio>.card:nth-child(3)'], [0, 2]);
  // the task card keeps 开始生成 in view while its options scroll
  await page.evaluate(() => { document.querySelector('#content .studio>.card').scrollTop = 0; });
  const card = await page.locator('#content .studio>.card').first().boundingBox();
  const start = await page.locator('[data-act="studioStart"]').boundingBox();
  expect(start.y + start.height).toBeLessThanOrEqual(card.y + card.height + 1);
  expect(errors).toEqual([]);
});

test('Lite sessions and wide projects scroll per pane', async ({ page }, info) => {
  mac14(info);
  const errors = await openDemo(page);
  await page.evaluate(() => { S.win.h = 600; applyWin(); S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-sessions'); });
  await settle(page);
  await checkSplit(page, ['#content .lite .sess>.card>.slist', '#content .lite .sess>.stack'], [0, 1]);
  await page.evaluate(() => { S.ed = 'advance'; $('#win').dataset.ed = 'advance'; S.win.h = innerHeight - 60; S.win.x = 24; S.win.w = innerWidth - 48; applyWin(); go('projects'); });
  await settle(page);
  expect(await page.evaluate(() => $('#main').clientWidth), 'content column wide enough for two project panes').toBeGreaterThanOrEqual(1100);
  await checkSplit(page, ['#content .pj>.stack:nth-child(1)', '#content .pj>.stack:nth-child(2)'], [0]);
  expect(errors).toEqual([]);
});

test('selection stays visible in its pane and the detail starts at the top', async ({ page }, info) => {
  mac14(info);
  const errors = await openDemo(page);
  // a session far down the list, opened from another page
  await page.evaluate(() => { S.sess.sel = sessList()[40].id; go('overview'); go('sessions'); });
  await settle(page);
  const vis = () => page.evaluate(() => { const l = $('#slist'), r = l.querySelector('.srow.sel').getBoundingClientRect(), p = l.getBoundingClientRect(); return { inside: r.top >= p.top - 1 && r.bottom <= p.bottom + 1, list: l.scrollTop, content: $('#content').scrollTop }; });
  let v = await vis();
  expect(v.inside, 'selected row visible inside the list pane').toBe(true);
  expect(v.list).toBeGreaterThan(0);
  expect(v.content).toBe(0);
  // picking another row: the detail pane starts at the top, the list stays where it is
  await page.evaluate(() => { $('#content .sess>.stack').scrollTop = 120; });
  const list0 = v.list;
  const next = page.locator('#slist .srow:not(.sel)').nth(41);
  await next.scrollIntoViewIfNeeded();
  const list1 = await page.evaluate(() => $('#slist').scrollTop);
  await next.click();
  await expect.poll(() => page.evaluate(() => $('#content .sess>.stack').scrollTop)).toBe(0);
  expect(await page.evaluate(() => $('#slist').scrollTop)).toBe(list1);
  expect(list1).toBeGreaterThanOrEqual(0); expect(list0).toBeGreaterThan(0);
  // a full render keeps both panes
  await page.evaluate(() => { $('#content .sess>.stack').scrollTop = 90; render(); });
  expect(await state(page, ['#slist', '#content .sess>.stack'])).toEqual(expect.arrayContaining([expect.objectContaining({ t: list1 }), expect.objectContaining({ t: 90 })]));
  // recs: a different card resets the detail pane, the list keeps its place
  await go(page, 'recs');
  await page.evaluate(() => { $('#content .recs>:last-child').scrollTop = 25; $('#content .recs>.stack').scrollTop = 200; });
  const id = await page.locator('#content .recs>.stack .rcard:not(.sel)').nth(2).getAttribute('data-id');
  const card = page.locator('#content .recs>.stack .rcard[data-id="' + id + '"]');
  await card.scrollIntoViewIfNeeded();
  const rl = await page.evaluate(() => $('#content .recs>.stack').scrollTop);
  await card.click({ position: { x: 20, y: 12 } });
  await expect.poll(() => page.evaluate(() => S.recs.sel)).toBe(id);
  expect(await page.evaluate(() => $('#content .recs>:last-child').scrollTop)).toBe(0);
  expect(await page.evaluate(() => $('#content .recs>.stack').scrollTop)).toBe(rl);
  // leaving and coming back starts the panes at the top (the selected card is near the top of the list)
  await page.evaluate(() => { S.recs.sel = RECS[0].id; $('#content .recs>.stack').scrollTop = 600; go('overview'); go('recs'); });
  expect(await page.evaluate(() => $('#content .recs>.stack').scrollTop)).toBeLessThan(200);
  expect(errors).toEqual([]);
});

test('share sheet keeps its title and buttons and scrolls preview and options apart', async ({ page }, info) => {
  mac14(info);
  const errors = await openDemo(page);
  await page.evaluate(() => { S.win.h = 600; applyWin(); go('persona'); openShare(); });
  await expect(page.locator('#modal')).toBeVisible();
  await settle(page);
  const m = await page.locator('#modal').boundingBox();
  for (const s of ['#modal .mh', '#modal .mf']) {
    const b = await page.locator(s).boundingBox();
    expect(b.y, s + ' inside the sheet').toBeGreaterThanOrEqual(m.y - 1);
    expect(b.y + b.height, s + ' inside the sheet').toBeLessThanOrEqual(m.y + m.height + 1);
  }
  const panes = ['#shareBody>:nth-child(1)', '#shareBody>:nth-child(2)'];
  const st = await state(page, ['#modal', '#shareBody', ...panes]);
  expect(st[0].sh, 'the sheet itself does not scroll').toBeLessThanOrEqual(st[0].ch + 1);
  expect(st[2].sh, 'the preview overflows a 600px window').toBeGreaterThan(st[2].ch);
  await page.mouse.move(...await page.locator(panes[0]).boundingBox().then((b) => [b.x + b.width / 2, b.y + 60]));
  await page.mouse.wheel(0, 200);
  await expect.poll(async () => (await state(page, [panes[0]]))[0].t).toBeGreaterThan(0);
  const after = await state(page, ['#modal', '#shareBody', panes[1]]);
  expect(after.map((x) => x.t)).toEqual([0, 0, 0]);
  expect(errors).toEqual([]);
});

test('pane mode only while the split is side by side', async ({ page }) => {
  const errors = await openDemo(page);
  for (const [r, min, panes] of [['sessions', 800, ['#content .sess>.stack']], ['recs', 800, ['#content .recs>.stack', '#content .recs>:last-child']], ['studio', 800, ['#content .studio>.card']], ['projects', 1100, ['#content .pj>.stack']]]) {
    await go(page, r);
    const s = await page.evaluate((panes) => {
      const c = $('#content'), w = $('#main').clientWidth, wb = $('#win').getBoundingClientRect().bottom;
      return { w, flex: getComputedStyle(c).display === 'flex', over: c.scrollHeight - c.clientHeight, bottoms: panes.map((p) => document.querySelector(p).getBoundingClientRect().bottom - wb) };
    }, panes);
    if (s.w >= min) {
      expect(s.flex, r + ' is in pane mode at ' + s.w + 'px').toBe(true);
      expect(s.over, r + ': #content does not overflow').toBeLessThanOrEqual(1);
      s.bottoms.forEach((d) => expect(d, r + ': pane ends inside the window').toBeLessThanOrEqual(1));
    } else {
      expect(s.flex, r + ' stacks and scrolls as a page at ' + s.w + 'px').toBe(false);
    }
  }
  expect(errors).toEqual([]);
});
