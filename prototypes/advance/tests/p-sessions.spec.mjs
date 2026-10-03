// A3 会话轨迹（src/js/42-a3-sessions.js + styles/43-a3-sessions.css）。只在 mac-14 跑一次。
// 流程：
//   1. 列表口径：结果 = 放弃 时今天 / 运行中的会话也要满足筛选（BUG-02），页头不再写死「1 个运行中」（BUG-03）；
//      「全部历史」只渲染 120 行时给出截断提示，「加载更多」追加（BUG-05）；运行中时长按真实分钟（BUG-68）；
//      标记为不计入分析的会话仍留在列表并带标签（BUG-19）。
//   2. 搜索：组字中的 input 事件不改状态；真正输入后只重绘列表，输入框是同一个节点且保持焦点（BUG-12）。
//   3. 轨迹：总览条与时间线都由 VZ 挂载（含上下文装饰层与顶部相对时间轴）；+ 以播放头为锚缩放并更新「适应」与视窗；
//      ⌘/Ctrl + 滚轮缩放后「适应」不再高亮（BUG-17）；「适应」复位；步数模式有整数刻度（BUG-18）；
//      点关键时刻列表跳转播放头并高亮徽章，检视面板跟随；‹ › 逐事件；点击空白处移动播放头；拖播放头手柄；刷选显示选段统计。
//   4. 从其他入口切到另一个会话：播放头回到末尾、视窗复位（BUG-15）；回放中离开页面即停止（BUG-16）。
//   5. 对比：两条时间线是独立的 VZ 实例、标题各自对应（BUG-13）；依次点选先换 A 再换 B（BUG-14）；差异列有 Δ 与阶段占比。
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

test.beforeEach(({}, info) => { test.skip(info.project.name !== 'mac-14', 'page coverage runs once, at the default size'); });

test('session list applies filters to today, flags truncation, keeps excluded sessions and shows live minutes', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  // BUG-02 / 03: today's rows obey the outcome filter; the header counts live sessions for real
  await page.evaluate(() => { S.outcome = 'fail'; render(); });
  expect(await page.evaluate(() => sessList().every((s) => s.out === 'fail'))).toBe(true);
  await expect(page.locator('#main .tbar')).not.toContainText('运行中');
  await page.evaluate(() => { S.outcome = null; render(); });
  await expect(page.locator('#main .tbar')).toContainText('1 个运行中');
  // BUG-68: a live session that has run 125 minutes says so
  await page.evaluate(() => { S.live.t0 = Date.now() - 125 * 60000; render(); });
  await expect(page.locator('.srow[data-id="sess-1001-1512"] .m')).toContainText('运行中 125m');
  // BUG-05: "全部历史" declares more than 120 sessions, renders 120 and offers to load more
  await page.evaluate(() => { S.range = 0; render(); });
  const total = await page.evaluate(() => sessList().length);
  expect(total).toBeGreaterThan(120);
  await expect(page.locator('#slist .srow')).toHaveCount(120);
  const more = page.locator('.tl-more');
  await expect(more).toContainText('已显示前 120 个 · 还有 ' + (total - 120) + ' 个');
  await more.click();
  await expect(page.locator('#slist .srow')).toHaveCount(Math.min(total, 240));
  // BUG-19: excluding the selected session keeps it browsable with a tag
  const sel = await page.evaluate(() => S.sess.sel);
  await page.evaluate(() => { S.excluded.add(S.sess.sel); render(); });
  await expect(page.locator('.srow[data-id="' + sel + '"] .tag')).toHaveText('不计入');
  expect(await page.evaluate(() => sel({ range: 0 }).some((s) => s.id === S.sess.sel))).toBe(false);
  expect(errors).toEqual([]);
});

test('search does not interrupt IME composition and only repaints the list', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  const q = page.locator('#sessQ');
  await q.focus();
  // composing: the value changes but state and list stay put
  await page.evaluate(() => { const el = $('#sessQ'); el.dataset.ime = '1'; el.value = 'bushu'; el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true })); });
  expect(await page.evaluate(() => S.sess.q)).toBe('');
  // committed text: the list repaints but the input is the same node and keeps focus
  await page.evaluate(() => { const el = $('#sessQ'); el.__same = true; delete el.dataset.ime; el.value = '部署'; el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: false })); });
  expect(await page.evaluate(() => S.sess.q)).toBe('部署');
  expect(await page.evaluate(() => !!$('#sessQ').__same && document.activeElement === $('#sessQ'))).toBe(true);
  expect(await page.evaluate(() => $$('#slist .srow').length)).toBe(await page.evaluate(() => sessList().length));
  await expect(page.locator('#sessCount')).toContainText(String(await page.evaluate(() => sessList().filter((s) => s.d !== 120).length)) + ' 个会话');
  expect(errors).toEqual([]);
});

test('trajectory: overview + timeline mount, zoom controls, step axis, moments, inspector, playhead and brush', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  const box = page.locator('#tlBox');
  await expect(box.locator('svg.vz-svg.vz-t-timeline')).toHaveCount(1);
  await expect(page.locator('#tlOv svg.vz-svg.vz-t-minimap')).toHaveCount(1);
  await expect(box.locator('.tl-deco .tl-ctx-area')).toHaveCount(1);          // context area is decorated after each draw
  await expect(box.locator('.tl-deco .tl-rel').first()).toHaveText('+0m');     // top relative axis
  await expect(box.locator('.vz-marker')).not.toHaveCount(0);
  await expect(box.locator('.vz-dens').first()).toBeAttached();              // tool lanes fold into a density band at this width
  // + zooms around the playhead; 适应 drops its highlight; the minimap window follows
  const fit = page.locator('[data-act="zoom"][data-v="0"]');
  await expect(fit).toHaveClass(/on/);
  const win0 = await page.evaluate(() => +$('#tlOv .vz-mm-view').getAttribute('width'));
  await page.locator('[data-act="zoom"][data-v="1"]').click();
  const v1 = await page.evaluate(() => ({ view: S.sess.view, zoom: S.sess.zoom, ph: S.sess.ph }));
  expect(v1.view).not.toBeNull(); expect(v1.zoom).toBeCloseTo(1.5, 5);
  expect(v1.ph).toBeGreaterThanOrEqual(v1.view[0]); expect(v1.ph).toBeLessThanOrEqual(v1.view[1]);
  await expect(fit).not.toHaveClass(/on/);
  expect(await page.evaluate(() => +$('#tlOv .vz-mm-view').getAttribute('width'))).toBeLessThan(win0);
  await expect(page.locator('#tlZoom')).toHaveText('1.5×');
  await fit.click();
  expect(await page.evaluate(() => [S.sess.view, S.sess.zoom])).toEqual([null, 1]);
  // BUG-17: wheel zoom also updates the 适应 button
  await box.hover();
  await page.keyboard.down('Control'); await page.mouse.wheel(0, -200); await page.keyboard.up('Control');
  await expect.poll(() => page.evaluate(() => S.sess.zoom)).toBeGreaterThan(1);
  await expect(fit).not.toHaveClass(/on/);
  await fit.click();
  // BUG-18: step layout shows integer step ticks
  await page.locator('[data-act="axis"][data-v="steps"]').click();
  const ticks = await page.evaluate(() => $$('#tlBox .vz-ax').map((t) => t.textContent).filter((t) => /^\d+$/.test(t)));
  expect(ticks.length).toBeGreaterThan(2);
  await page.locator('[data-act="axis"][data-v="time"]').click();
  // a moment in the list seeks the playhead, marks itself and highlights the badge on hover
  const mom = page.locator('.tl-mom').nth(3);
  const t = +(await mom.getAttribute('data-t'));
  await mom.hover();
  await expect(box.locator('.vz-marker.vz-hot')).not.toHaveCount(0);
  await mom.click();
  expect(await page.evaluate(() => S.sess.ph)).toBeCloseTo(t, 5);
  await expect(mom).toHaveClass(/on/);
  const insp = page.locator('#tlInsp');
  await expect(insp).toContainText('播放头处');
  // ‹ › step through events and pin them in the inspector
  const ph0 = await page.evaluate(() => S.sess.ph);
  await insp.locator('[data-act="tlStep"][data-v="1"]').click();
  const picked = await page.evaluate(() => ({ ev: S.sess.ev, ph: S.sess.ph }));
  expect(picked.ev).toMatch(/^e\d+$/); expect(picked.ph).toBeGreaterThanOrEqual(ph0);
  await expect(insp).toContainText('选中');
  await expect(box.locator('.vz-sel')).toHaveCount(1);
  await insp.locator('[data-act="tlClear"]').click();
  expect(await page.evaluate(() => S.sess.ev)).toBeNull();
  // clicking empty plot space moves the playhead to that time
  const F = await page.evaluate(() => { const inst = VZ._inst.get($('#tlBox')); const r = $('#tlBox .vz-plot').getBoundingClientRect(); const F = inst.model.F; return { left: r.left, top: r.top, x0: F.x0, x1: F.x1, yT: F.yT, yB: F.yB, T: inst.spec.extent[1] }; });
  await page.mouse.click(F.left + (F.x0 + F.x1) / 2, F.top + F.yT + 2);
  await expect.poll(() => page.evaluate(() => S.sess.ph)).toBeGreaterThan(F.T * 0.4);
  expect(await page.evaluate(() => S.sess.ph)).toBeLessThan(F.T * 0.6);
  // the playhead handle drags (VZ playhead → onPlayhead → S.sess.ph)
  const hx = F.left + (F.x0 + F.x1) / 2, hy = F.top + F.yB + 15;
  await page.mouse.move(hx, hy); await page.mouse.down(); await page.mouse.move(hx + 60, hy, { steps: 4 }); await page.mouse.up();
  const dragged = await page.evaluate(() => S.sess.ph);
  expect(dragged).toBeGreaterThan(F.T * 0.5);
  // a drag across lanes brushes a segment and the readout sums it up
  await page.mouse.move(F.left + F.x0 + 40, F.top + F.yT + 30); await page.mouse.down(); await page.mouse.move(F.left + F.x0 + 160, F.top + F.yT + 30, { steps: 5 }); await page.mouse.up();
  await expect(page.locator('#tlRead .tl-brush')).toContainText('选段');
  await page.locator('[data-act="tlBrushClear"]').click();
  await expect(page.locator('#tlRead .tl-brush')).toHaveCount(0);
  // the tool-lane toggle expands four lanes and back
  await page.locator('[data-act="tlTools"]').click();
  await expect(box.locator('.vz-lane-lbl')).toContainText(['读取 / 搜索', '编辑', '命令', '网络']);
  await page.locator('[data-act="tlTools"]').click();
  await expect(box.locator('.vz-dens').first()).toBeAttached();
  expect(errors).toEqual([]);
});

test('switching sessions from elsewhere resets the playhead and view; leaving the page stops replay', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await page.locator('[data-act="zoom"][data-v="1"]').click();
  await page.evaluate(() => { S.sess.ph = 3; updTimeline(); });
  // BUG-15: an entry point that only sets S.sess.sel (A2 fingerprint, palette, menu-bar panel) lands at the end of the new session
  const other = await page.evaluate(() => { const o = sessList().find((s) => s.id !== S.sess.sel && !s.live); S.sess.sel = o.id; go('sessions'); return [o.id, traj(o).T]; });
  const st = await page.evaluate(() => ({ sel: S.sess.sel, ph: S.sess.ph, view: S.sess.view, zoom: S.sess.zoom }));
  expect(st.sel).toBe(other[0]); expect(st.ph).toBeCloseTo(other[1], 5); expect(st.view).toBeNull(); expect(st.zoom).toBe(1);
  // BUG-16: replay stops when the user navigates away mid-run
  await page.evaluate(() => { S.sess.ph = 0; startPlay(); });
  await expect.poll(() => page.evaluate(() => S.sess.playing)).toBe(true);
  await page.evaluate(() => go('overview'));
  await expect.poll(() => page.evaluate(() => S.sess.playing)).toBe(false);
  expect(errors).toEqual([]);
});

test('compare mode mounts two independent timelines, picks A then B and fills the delta column', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await page.locator('[data-act="sessMode"][data-v="cmp"]').click();
  await expect(page.locator('.tl-cmp svg.vz-svg')).toHaveCount(2);
  // BUG-13: each timeline carries its own session (titles differ, tooltips come from separate instances)
  const titles = await page.evaluate(() => $$('.tl-cmp').map((el) => VZ._inst.get(el).spec.title));
  expect(titles[0]).not.toBe(titles[1]);
  const ids0 = await page.evaluate(() => [S.sess.sel, S.sess.cmp]);
  expect(titles).toEqual(await page.evaluate((ids) => ids.map((id) => BYID[id].title), ids0));
  await expect(page.locator('#sessCount ~ span')).toContainText('下一次点选作为 A');
  // BUG-14: the first pick replaces A, the second replaces B
  const fresh = await page.evaluate((ids) => sessList().filter((s) => !ids.includes(s.id)).slice(0, 2).map((s) => s.id), ids0);
  await page.locator('.srow[data-id="' + fresh[0] + '"]').click();
  expect(await page.evaluate(() => [S.sess.sel, S.sess.cmp])).toEqual([fresh[0], ids0[1]]);
  await expect(page.locator('#sessCount ~ span')).toContainText('下一次点选作为 B');
  await page.locator('.srow[data-id="' + fresh[1] + '"]').click();
  expect(await page.evaluate(() => [S.sess.sel, S.sess.cmp])).toEqual([fresh[0], fresh[1]]);
  await expect(page.locator('.srow[data-id="' + fresh[0] + '"] .bdg')).toHaveText('A');
  await expect(page.locator('.srow[data-id="' + fresh[1] + '"] .bdg')).toHaveText('B');
  // every delta cell is filled; the phase-share row exists
  const tbl = page.locator('.tbl');
  await expect(tbl).toContainText('Δ（B − A）');
  await expect(tbl).toContainText('阶段耗时占比');
  const empties = await page.evaluate(() => $$('.tbl tbody tr td:last-child').filter((td) => !td.textContent.trim()).length);
  expect(empties).toBe(0);
  expect(errors).toEqual([]);
});
