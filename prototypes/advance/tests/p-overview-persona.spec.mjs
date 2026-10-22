// A1 概览 + A2 协作人格（分支 ui/p-overview-persona）。每个用例从新页面开始，只在 mac-14 跑一次。
//
// 测试流程：
//  1 kpi        三张指标卡用环比三件套（▲/▼ + 变化量 + 「上期」），摩擦率按极性着色；关掉「对比上一周期」后环比消失
//  2 trend      度量 / 堆叠·分组·100% / 图表↔表格 切换都重绘；表格视图带 sticky 表头容器；
//               点图例只隐藏本图系列，S.agents 不变（A1-V09）；拖选一段后指标卡按范围重算并出现「清除刷选」，清除后恢复
//  3 heat       消息数 / 纠偏率切换；点格子只按小时筛选并在提示里说明不分星期（BUG-10）
//  4 evidence   「卡在哪」的证据数等于该摩擦类型的会话数，点击后 A3 带摩擦筛选；「立刻可做」打开优化建议
//  5 regen      连点「重新生成」只保留一个定时器（最终文本是完整的一句话）；重绘后导语与「刚刚已同步」保留（BUG-66）
//  6 scope      设置主题筛选后，侧栏、A2、导出报告的人格代码一致，并注明「主题筛选不计入人格」（BUG-06）
//  7 persona    周期切换、与过去 / 与全体对照、四维度双向条以 50 为界（无未定型带）与参照刻度、演变折线挂载、指纹外环点一段展开会话点再点收起
//  8 fit        契合度条有 95% 区间；停用来源的 Agent 不可点、点击 soloAgent 不改筛选（BUG-49）
//  9 low-sample 少量会话也出完整 4 字母；0 个会话时列出「移除后 n≈」的放宽芯片并可一键放宽（A2-V08）；全部来源停用时给「打开设置 · 数据源」（BUG-50）
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'page coverage runs once, at the default size');

test('KPI tiles use the ▲▼ + change + previous-value triplet with polarity colouring', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  const deltas = () => page.evaluate(() => [...document.querySelectorAll('#ovTiles .vz-kpi-d')].map((x) => [x.textContent, x.className]));
  let d = await deltas();
  expect(d).toHaveLength(3);                          // merged overview: 会话 · 协作时长 · 摩擦率
  for (const [t] of d) { expect(t).toMatch(/^[▲▼]/); expect(t).toContain('上期'); }
  expect(d[2][1]).toMatch(/vz-(good|bad)/);           // 摩擦率有极性
  expect(d[0][1]).not.toMatch(/vz-(good|bad)/);       // 会话数中性
  await expect(page.locator('#ovTiles .vz-kpi-p').first()).toHaveText('近 12 周');
  await page.evaluate(() => ACT.compare());
  const off = await deltas();
  expect(off).toHaveLength(3);
  for (const [t] of off) expect(t).not.toContain('上期');   // 关掉对比后不再显示环比
  await page.evaluate(() => { S.range = 7; render(); });
  await expect(page.locator('#ovTiles .vz-kpi-p').first()).toHaveText('近 7 天');
  expect(errors).toEqual([]);
});

test('trend chart: metric / stack mode / table view switch, legend stays local, brush recomputes the tiles', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  const trend = page.locator('[data-vz="ov-trend"]');
  await expect(trend.locator('svg.vz-svg')).toBeVisible();
  await page.evaluate(() => ACT.metric({ dataset: { v: 'tok' } }));
  await expect(page.locator('#main')).toContainText('tokens · 估算');
  await page.evaluate(() => ACT.stackMode({ dataset: { v: 'pct' } }));
  await expect(page.locator('#main')).toContainText('各 Agent 占比');
  await page.evaluate(() => ACT.stackMode({ dataset: { v: 'grouped' } }));
  await expect(page.locator('#main')).toContainText('按 Agent 分组');
  await page.evaluate(() => { ACT.stackMode({ dataset: { v: 'stacked' } }); ACT.metric({ dataset: { v: 'n' } }); ACT.view({ dataset: { v: 'table' } }); });
  await expect(trend.locator('.vz-tbl table')).toBeVisible();
  await page.evaluate(() => ACT.view({ dataset: { v: 'chart' } }));
  // 图例只影响本图
  const before = await page.evaluate(() => S.agents.size);
  await trend.locator('.vz-lg').first().click();
  expect(await page.evaluate(() => S.agents.size)).toBe(before);
  expect(await page.evaluate(() => S.ov.hidden)).toEqual(['Claude Code']);
  await expect(trend.locator('.vz-lg.off')).toHaveCount(1);
  await trend.locator('.vz-lg').first().click();
  expect(await page.evaluate(() => S.ov.hidden)).toEqual([]);
  // 刷选 → 指标卡重算
  const n0 = await page.locator('#ovTiles .vz-kpi .v').first().textContent();
  const box = await trend.locator('.vz-plot svg').boundingBox();
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5, { steps: 6 });
  await page.mouse.up();
  await expect(page.locator('#ovBrush')).toBeVisible();
  await expect(page.locator('#ovBrushTxt')).toContainText('指标卡已按该范围重算');
  const n1 = await page.locator('#ovTiles .vz-kpi .v').first().textContent();
  expect(n1).not.toBe(n0);
  expect(await page.evaluate(() => S.ov.brush)).not.toBeNull();
  await page.locator('[data-act="ovBrushClear"]').click();
  await expect(page.locator('#ovBrush')).toBeHidden();
  expect(await page.locator('#ovTiles .vz-kpi .v').first().textContent()).toBe(n0);
  expect(errors).toEqual([]);
});

test('heat map toggles messages / correction rate and drills down by hour only', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  const heat = page.locator('[data-vz="ov-heat"]');
  await expect(heat.locator('.vz-cell')).toHaveCount(7 * 24);
  await expect(page.locator('#main')).toContainText('高峰 周');
  await page.evaluate(() => ACT.heatMode({ dataset: { v: 'corr' } }));
  await expect(page.locator('#main')).toContainText('纠偏率');
  await expect(heat.locator('.vz-scale')).toContainText('%');
  await page.evaluate(() => ACT.heatMode({ dataset: { v: 'msgs' } }));
  await page.evaluate(() => ACT.heatCell({ dataset: { h: '14', d: '2' } }));
  await expect.poll(() => page.evaluate(() => S.route)).toBe('sessions');
  expect(await page.evaluate(() => S.hour)).toBe(14);
  await expect(page.locator('#toast')).toContainText('不分星期');
  expect(errors).toEqual([]);
});

test('AI-card evidence counts match the filter they apply; the suggestion card opens the recs page', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  // 卡在哪 → 证据数是摩擦会话数，点击把摩擦类型带进会话轨迹
  const topF = await page.evaluate(() => Object.entries(countBy(sel(), 'fric')).sort((a, b) => b[1] - a[1])[0]);
  await expect(page.locator('[data-act="evBad"]')).toHaveText('证据 · ' + topF[1] + ' 个会话');
  await page.locator('[data-act="evBad"]').click();
  await expect.poll(() => page.evaluate(() => S.route)).toBe('sessions');
  expect(await page.evaluate(() => S.fric)).toBe(topF[0]);
  // 立刻可做 → 建议卡打开优化建议
  await go(page, 'overview');
  await page.evaluate(() => { S.fric = null; render(); });
  const topR = await page.evaluate(() => recTop('A1').slice(0, 3).length);
  await expect(page.locator('[data-act="evRec"]')).toHaveText('查看 ' + topR + ' 条建议');
  await page.locator('[data-act="evRec"]').click();
  await expect.poll(() => page.evaluate(() => S.route)).toBe('recs');
  expect(errors).toEqual([]);
});

test('regenerate keeps a single typing timer and survives a re-render; the sync marker persists too', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  await page.evaluate(() => { ACT.regen(); ACT.regen(); ACT.regen(); });
  const variants = await page.evaluate(() => { const p = personaNow(); return ['你像一位' + p.zh + '：' + p.line, '一句话：你把大块目标交给 Agent，并且很在意结果是否真的可用。', '你的协作重心在「交出去」和「收回来」两端：委托得多，验收也严。']; });
  // three clicks keep one timer: the lede finishes as exactly one complete variant, never a doubled/partial sentence
  await expect.poll(() => page.evaluate((vs) => vs.includes(document.querySelector('#aiLead').textContent), variants), { timeout: 8000 }).toBe(true);
  const txt = await page.locator('#aiLead').textContent();
  await page.evaluate(() => render());
  await expect(page.locator('#aiLead')).toHaveText(txt);
  await page.evaluate(() => ACT.reindex());
  await expect(page.locator('[data-sync]')).toContainText('正在索引');
  await expect(page.locator('[data-sync]')).toHaveText('刚刚已同步', { timeout: 5000 });
  await page.evaluate(() => render());
  await expect(page.locator('[data-sync]')).toHaveText('刚刚已同步');
  expect(errors).toEqual([]);
});

test('persona code is the same in the sidebar, A2 and the report while a topic filter is on', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  await page.evaluate(() => { S.topic = 'design'; render(); });
  const side = await page.locator('.side .me .pc').textContent();
  // the merged A1 no longer carries a persona card; it only notes which filters are left out of the persona scope
  await expect(page.locator('#main')).toContainText('主题筛选不计入人格');
  await go(page, 'persona');
  const a2 = await page.evaluate(() => [...document.querySelectorAll('#main .letters .L')].map((x) => x.textContent).join(''));
  expect(side).toContain(a2);
  await expect(page.locator('#main')).toContainText('主题筛选不计入人格');
  const rep = await page.evaluate(() => reportMD());
  expect(rep).toContain(a2); // report wording comes from 55-exports.js; only the code must match
  expect(errors).toEqual([]);
});

test('persona page: periods, comparison group, diverging axes, evolution chart and fingerprint hour expansion', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page, 'persona');
  await expect(page.locator('#main')).toContainText('实验性');
  const axes = page.locator('[data-vz="pe-axes"]');
  await expect(axes.locator('.vz-bar')).toHaveCount(4);
  await expect(axes.locator('.vz-band')).toHaveCount(0);          // 不再有 45–55 未定型带（bug 4）
  await expect(axes.locator('.vz-ghost')).toHaveCount(4);         // 上月参照刻度
  await expect(page.locator('[data-vz="pe-evo"] .vz-line')).toHaveCount(4);
  await expect(page.locator('#axesCard .pe-evi')).toHaveCount(4);
  await page.evaluate(() => ACT.vs({ dataset: { v: 'pop' } }));
  await expect(page.locator('#axesCard')).toContainText('全体用户均值');
  await page.evaluate(() => ACT.period({ dataset: { v: 'jun' } }));
  await expect(page.locator('#main .evo button.on')).toContainText('2026-06');
  await page.evaluate(() => ACT.period({ dataset: { v: 'sep' } }));
  // 指纹外环：16 型；点一型展开偏向它的会话点，再点收起
  const fp = page.locator('#main svg.fp2');
  await expect(fp.locator('.fps')).toHaveCount(16);
  await expect(fp.locator('.fpd')).toHaveCount(0);
  const h = await page.evaluate(() => CUR.fp.byT.findIndex((x) => x.length > 0));
  await page.evaluate((hh) => ACT.fpType({ dataset: { t: String(hh) } }), h);
  const dots = await page.locator('#main svg.fp2 .fpd').count();
  expect(dots).toBe(await page.evaluate((hh) => CUR.fp.byT[hh].length, h));
  expect(dots).toBeGreaterThan(0);
  await expect(page.locator('#main svg.fp2 .fps.dim')).toHaveCount(15);
  await page.evaluate((hh) => ACT.fpType({ dataset: { t: String(hh) } }), h);
  await expect(page.locator('#main svg.fp2 .fpd')).toHaveCount(0);
  expect(await page.evaluate(() => S.persona.fpType)).toBeNull();
  expect(errors).toEqual([]);
});

test('fit rows carry confidence intervals; a disabled source cannot be soloed', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page, 'persona');
  await expect(page.locator('#main .pe-fit-bar .ci').first()).toBeVisible();
  await expect(page.locator('#main button.pe-fit')).toHaveCount(5);
  await page.evaluate(() => { S.srcOff.add('cc'); render(); });
  await expect(page.locator('#main button.pe-fit')).toHaveCount(4);
  await expect(page.locator('#main .pe-fit.off')).toContainText('来源已停用');
  const before = await page.evaluate(() => S.agents.size);
  await page.evaluate(() => ACT.soloAgent({ dataset: { a: 'cc' } }));
  expect(await page.evaluate(() => S.agents.size)).toBe(before);
  await expect(page.locator('#toast')).toContainText('已在设置中停用');
  expect(errors).toEqual([]);
});

test('low-sample state lists relax estimates; all sources off points to settings', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  // bug 4: a thin scope (a handful of sessions) still gets a full four-letter code, with a gentle hint instead of 「?」
  const thin = await page.evaluate(() => { S.agents = new Set(['oc']); S.project = 'orbit'; const per = PERIODS[S.persona.period]; return personaScope([per[0], per[1]]).length; });
  if (thin > 0) {
    await page.evaluate(() => go('persona'));
    const code = await page.locator('.persona-hero .letters .L').allTextContents();
    expect(code).toHaveLength(4); expect(code.join('')).not.toContain('?');
    if (thin < 30) await expect(page.locator('.persona-hero')).toContainText('数据越多越准');
  }
  // only an empty scope (0 sessions) shows the relax state
  const empty = await page.evaluate(() => { const per = PERIODS[S.persona.period]; for (const a of AG) for (const pj of Object.keys(PJI)) { S.agents = new Set([a.id]); S.project = pj; if (!personaScope([per[0], per[1]]).length) return [a.id, pj]; } return null; });
  expect(empty).not.toBeNull();
  await page.evaluate(() => go('persona'));
  await expect(page.locator('#main .pe-low')).toContainText('当前筛选下还没有会话');
  const chips = page.locator('#main .pe-relax .chip');
  expect(await chips.count()).toBeGreaterThanOrEqual(1);
  await expect(chips.first()).toContainText(/移除后约 \d+ 个会话/);
  const est = await page.evaluate(() => +document.querySelector('#main .pe-relax .chip[data-k="agents"] b').textContent.replace(/\D/g, ''));
  await page.locator('#main .pe-relax .chip[data-k="agents"]').click();
  expect(await page.evaluate(() => S.agents.size)).toBe(5);
  expect(await page.evaluate(() => personaScope([90, 119]).length)).toBe(est);
  await page.evaluate(() => { S.project = null; AG.forEach((a) => S.srcOff.add(a.id)); render(); });
  await expect(page.locator('#main')).toContainText('所有数据源已停用');
  await page.locator('#main [data-act="openSettings"][data-tab="sources"]').click();
  await expect(page.locator('#set')).toBeVisible();
  expect(await page.evaluate(() => S.setTab)).toBe('sources');
  expect(errors).toEqual([]);
});
