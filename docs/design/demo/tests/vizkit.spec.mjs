// VZ 组件库测试。流程：
//   1. 打开 demo，go('vizkit') 进入隐藏的组件画廊，取 VZ_DEMO.specs() 得到每种组件的示例 spec；
//   2. 在 #content 顶部挂一个实验区，把每个 spec 分别 mount 到 360 / 720 / 1200px 宽的容器里；
//   3. 逐个断言：innerHTML 无 NaN / Infinity / undefined、容器不横向溢出、SVG 不宽于容器、文字不越出 SVG；
//   4. 坐标文字的 computed font-size 在三种宽度下相同（恒定像素，不随宽度缩放）；
//   5. 交互：十字准线 tooltip（hover）、图例点击隐藏系列、brush 拖选回调、键盘 ← → / Enter；
//   6. 状态：空数据与样本不足；深色模式下系列色与文字色取自主题变量；表格视图行数与数据一致。
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const WIDTHS = [360, 720, 1200];

async function openGallery(page) {
  const errors = await openDemo(page);
  await go(page, 'vizkit');
  await expect(page.locator('#content .vz[data-vz="line"] svg.vz-svg')).toBeVisible();
  return errors;
}
// 把所有示例 spec 挂到固定宽度的容器里，返回 id 列表
async function mountAll(page, w) {
  return page.evaluate((w) => {
    let lab = document.getElementById('vzLab');
    if (!lab) { lab = document.createElement('div'); lab.id = 'vzLab'; document.querySelector('#content').prepend(lab); }
    lab.innerHTML = '';
    const specs = VZ_DEMO.specs();
    Object.keys(specs).forEach((id) => { const el = document.createElement('div'); el.className = 'vz'; el.dataset.lab = id; el.style.width = w + 'px'; lab.appendChild(el); VZ.mount(el, specs[id]); });
    return Object.keys(specs);
  }, w);
}
// 挂一个示例到实验区，返回交互模型的关键坐标
async function mountOne(page, id, w, extra) {
  return page.evaluate(({ id, w, extra }) => {
    let lab = document.getElementById('vzLab');
    if (!lab) { lab = document.createElement('div'); lab.id = 'vzLab'; document.querySelector('#content').prepend(lab); }
    lab.innerHTML = '';
    const el = document.createElement('div'); el.className = 'vz'; el.dataset.lab = id; el.style.width = w + 'px'; lab.appendChild(el);
    const spec = Object.assign(VZ_DEMO.specs()[id], extra || {});
    const inst = VZ.mount(el, spec); window.__vzInst = inst;
    const m = inst.model || {};
    return { xs: m.xs || [], yT: m.F ? m.F.yT : 0, yB: m.F ? m.F.yB : 0, n: m.n, series: (spec.series || []).map((s) => ({ name: s.name, values: s.values })), x: spec.x && spec.x.values };
  }, { id, w, extra });
}

test('every component renders at 360 / 720 / 1200 without NaN or overflow', async ({ page }) => {
  const errors = await openGallery(page);
  for (const w of WIDTHS) {
    const ids = await mountAll(page, w);
    expect(ids.length).toBeGreaterThan(20);
    const report = await page.evaluate(() => Array.from(document.querySelectorAll('#vzLab .vz[data-lab]')).map((el) => {
      const svg = el.querySelector('svg.vz-svg'); const r = { id: el.dataset.lab, nan: /NaN|Infinity|undefined/.test(el.innerHTML), over: el.scrollWidth - el.clientWidth, svgW: svg ? +svg.getAttribute('width') : null, outside: 0, rendered: !!(svg || el.querySelector('.vz-empty') || el.querySelector('.vz-child svg.vz-svg')) };
      if (svg) { const W = +svg.getAttribute('width'), H = +svg.getAttribute('height'); svg.querySelectorAll('text').forEach((t) => { const b = t.getBBox(); if (b.x < -1 || b.x + b.width > W + 1 || b.y < -1 || b.y + b.height > H + 1) r.outside++; }); }
      return r;
    }));
    for (const r of report) {
      expect.soft(r.nan, `${r.id}@${w} contains NaN/Infinity/undefined`).toBe(false);
      expect.soft(r.rendered, `${r.id}@${w} rendered nothing`).toBe(true);
      expect.soft(r.over, `${r.id}@${w} overflows its container`).toBeLessThanOrEqual(0);
      if (r.svgW != null) expect.soft(r.svgW, `${r.id}@${w} svg wider than container`).toBeLessThanOrEqual(w);
      expect.soft(r.outside, `${r.id}@${w} has text outside the svg`).toBe(0);
    }
  }
  expect(errors).toEqual([]);
});

test('axis text keeps the same computed font-size at every width', async ({ page }) => {
  await openGallery(page);
  const sizes = {};
  for (const w of WIDTHS) {
    await mountAll(page, w);
    // 分别记录坐标刻度（.vz-ax）与类别名（.vz-cat）的字号，两类各自跨宽度比较
    const got = await page.evaluate(() => Array.from(document.querySelectorAll('#vzLab .vz[data-lab]')).flatMap((el) => ['vz-ax', 'vz-cat'].map((cls) => { const t = el.querySelector('svg.vz-svg text.' + cls); return [el.dataset.lab + '/' + cls, t ? getComputedStyle(t).fontSize : null]; })));
    got.forEach(([key, fs]) => { if (fs) (sizes[key] = sizes[key] || new Set()).add(fs); });
  }
  expect(Object.keys(sizes).length).toBeGreaterThan(15);
  for (const [key, set] of Object.entries(sizes)) { expect.soft(Array.from(set), key + ' font-size differs by width').toHaveLength(1); expect.soft(Array.from(set)[0], key + ' font size').toBe(key.endsWith('vz-cat') ? '12px' : '11px'); }
});

test('crosshair tooltip shows every visible series at the hovered x', async ({ page }) => {
  await openGallery(page);
  const m = await mountOne(page, 'line', 720);
  const plot = page.locator('#vzLab .vz[data-lab="line"] .vz-plot');
  await plot.scrollIntoViewIfNeeded();
  const box = await plot.boundingBox();
  const i = 5;
  await page.mouse.move(box.x + m.xs[i], box.y + (m.yT + m.yB) / 2);
  await page.mouse.move(box.x + m.xs[i] + 1, box.y + (m.yT + m.yB) / 2);
  const tip = page.locator('#vzLab .vz[data-lab="line"] .vz-tip');
  await expect(tip).toBeVisible();
  const text = await tip.textContent();
  for (const s of m.series) { expect(text, 'series name in tooltip').toContain(s.name); expect(text, 'series value in tooltip').toContain(String(s.values[i])); }
  const xline = page.locator('#vzLab .vz[data-lab="line"] .vz-xline');
  await expect(xline).toHaveAttribute('x1', String(Math.round(m.xs[i] * 10) / 10));
  await page.mouse.move(box.x + box.width + 40, box.y + box.height + 40);
  await expect(tip).toBeHidden();
});

test('legend click hides a series and reports it', async ({ page }) => {
  await openGallery(page);
  await mountOne(page, 'line', 720);
  const el = page.locator('#vzLab .vz[data-lab="line"]');
  await expect(el.locator('path.vz-line[data-s="1"]')).toHaveCount(1);
  await el.locator('.vz-lg[data-lg="Codex"]').click();
  await expect(el.locator('path.vz-line[data-s="1"]')).toHaveCount(0);
  await expect(el.locator('.vz-lg[data-lg="Codex"]')).toHaveAttribute('aria-pressed', 'false');
  expect(await page.evaluate(() => VZ_LAST.legend)).toEqual(['Codex', false]);
  await el.locator('.vz-lg[data-lg="Codex"]').click();
  await expect(el.locator('path.vz-line[data-s="1"]')).toHaveCount(1);
});

test('brush drag reports the selected range', async ({ page }) => {
  await openGallery(page);
  const m = await mountOne(page, 'bar', 720);
  const plot = page.locator('#vzLab .vz[data-lab="bar"] .vz-plot');
  await plot.scrollIntoViewIfNeeded();
  const box = await plot.boundingBox();
  const y = box.y + (m.yT + m.yB) / 2;
  await page.mouse.move(box.x + m.xs[3], y);
  await page.mouse.down();
  await page.mouse.move(box.x + m.xs[5], y, { steps: 4 });
  await page.mouse.move(box.x + m.xs[8], y, { steps: 4 });
  await expect(page.locator('#vzLab .vz[data-lab="bar"] .vz-brush')).toBeVisible();
  await page.mouse.up();
  expect(await page.evaluate(() => VZ_LAST.brush)).toEqual([3, 8]);
  // 点一下（不拖）清除
  await page.mouse.click(box.x + m.xs[10], y);
  expect(await page.evaluate(() => VZ_LAST.brush)).toBeNull();
});

test('keyboard moves the focus point and Enter selects it', async ({ page }) => {
  await openGallery(page);
  const m = await mountOne(page, 'line', 720);
  const plot = page.locator('#vzLab .vz[data-lab="line"] .vz-plot');
  await plot.focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  const tip = page.locator('#vzLab .vz[data-lab="line"] .vz-tip');
  await expect(tip).toBeVisible();
  expect(await tip.textContent()).toContain(String(m.series[0].values[1]));
  expect((await page.locator('#vzLab .vz[data-lab="line"] [data-vz-live]').textContent()).length).toBeGreaterThan(0);
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => VZ_LAST.select && VZ_LAST.select.i)).toBe(1);
  await page.keyboard.press('End');
  expect(await page.evaluate(() => window.__vzInst.focus)).toBe(m.n - 1);
});

test('empty data and low samples show their states', async ({ page }) => {
  await openGallery(page);
  await mountOne(page, 'empty', 720);
  await expect(page.locator('#vzLab .vz[data-lab="empty"] .vz-empty')).toContainText('所选范围内没有会话');
  await expect(page.locator('#vzLab .vz[data-lab="empty"] svg.vz-svg')).toHaveCount(0);
  await mountOne(page, 'low', 720);
  await expect(page.locator('#vzLab .vz[data-lab="low"] .vz-low')).toContainText('12 / 30');
  const svg = await page.evaluate(() => VZ.svg(VZ_DEMO.specs().empty, 400, 120));
  expect(svg).toContain('<svg'); expect(svg).toContain('所选范围内没有会话');
});

test('dark mode resolves series and text colors from the theme variables', async ({ page }) => {
  await openGallery(page);
  await mountOne(page, 'bar', 720);
  const read = () => page.evaluate(() => { const el = document.querySelector('#vzLab .vz[data-lab="bar"]'); return { bar: getComputedStyle(el.querySelector('path.vz-bar[data-s="0"]')).fill, ax: getComputedStyle(el.querySelector('text.vz-ax')).fill }; });
  await page.evaluate(() => { setTheme('light'); });
  const light = await read();
  expect(light.bar).toBe('rgb(226, 96, 43)');
  expect(light.ax).toBe('rgb(98, 102, 111)');
  await page.evaluate(() => { setTheme('dark'); });
  const dark = await read();
  expect(dark.bar).toBe('rgb(217, 89, 38)');
  expect(dark.ax).toBe('rgb(154, 158, 167)');
  await page.evaluate(() => { setTheme('system'); });
});

test('table view has one row per datum and switches in place', async ({ page }) => {
  await openGallery(page);
  const counts = await page.evaluate(() => {
    const specs = VZ_DEMO.specs(); const rows = (html) => (html.match(/<tr>/g) || []).length - 1;
    return { bar: [rows(VZ.table(specs.bar)), specs.bar.x.values.length], ranked: [rows(VZ.table(specs.ranked)), specs.ranked.rows.length], heat: [rows(VZ.table(specs.heat)), specs.heat.rows.length], scatter: [rows(VZ.table(specs.scatter)), specs.scatter.points.length], timeline: [rows(VZ.table(specs.timeline)), specs.timeline.events.length], flow: [rows(VZ.table(specs.flow)), specs.flow.links.length], dumbbell: [rows(VZ.table(specs.dumbbell)), specs.dumbbell.rows.length] };
  });
  for (const [id, [got, want]] of Object.entries(counts)) expect(got, id + ' table rows').toBe(want);
  await mountOne(page, 'bar', 720);
  await page.evaluate(() => VZ.setView(document.querySelector('#vzLab .vz[data-lab="bar"]'), 'table'));
  const el = page.locator('#vzLab .vz[data-lab="bar"]');
  await expect(el.locator('table tbody tr')).toHaveCount(counts.bar[1]);
  await expect(el.locator('svg.vz-svg')).toHaveCount(0);
  await page.evaluate(() => VZ.setView(document.querySelector('#vzLab .vz[data-lab="bar"]'), 'chart'));
  await expect(el.locator('svg.vz-svg')).toHaveCount(1);
});
