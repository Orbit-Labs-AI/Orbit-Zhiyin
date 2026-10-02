// A4 工具调用 / A5 项目习惯 / A6 情绪与语义 页面测试（分支 ui/p-tools-projects-sentiment）。流程：
//   A4：1. 打开 demo 进入 tools；KPI 四卡各带迷你线与环比；2. 点「工具」列头两次，行顺序按名称升 / 降变化（BUG-20）；
//       3. 「仅看失败」后列头与 KPI 口径同步为「失败次数」；4. 展开 Bash 行，出现最近调用与「在轨迹中查看」，点击跳到会话页；
//       5. 调用链矩阵为 HTML grid（36 个格子 + 6 个行 n），悬停一格高亮整行整列（.hl）；6. 展开一类失败原因，「相关会话」把 S.fric 设为工具失败并进入 sessions；
//       7. 切到 7 天后迷你线列头随范围（BUG-85）；8. 标记 figma 已移除后页头变为 1 个 MCP，S.tools.figma 同步（BUG-21）。
//   A5：1. 项目表任何单元格不被裁切（scrollWidth ≤ clientWidth），含摩擦率列；2. 散点挂载为 pscatter：有拟合线、置信带、残差竖线与尺寸图例；
//       3. 对比模式下点第二个项目：表中出现 A / B 徽标、散点出现 B 环；4. 全局项目筛选 → 详情定位到该项目（BUG-07）；
//       5. 退出对比后 A 选成原 B → B 被清掉（BUG-71）；6. 覆盖矩阵格子数 = 配置类型数 × 项目用到的 Agent 数。
//   A6：1. 情绪图为 moodcorr：分布带 + 中位线 + 纠偏柱共用一张 svg，一条游标跨两图；指针移动后游标可见、tooltip 含「情绪中位数」与「纠偏」；
//       2. 「看表格」切到表格视图并可切回；3. 点一个主题后其它主题仍在（BUG-72）；4. 不同反馈语的出处不同（BUG-73）；
//       5. 90 天时说明文字为「每周」（BUG-69）；6. AI 抽取内容带紫色 .aib 标识；7. 三页浅 / 深色均无页面错误。
import { test, expect } from '@playwright/test';
import { openDemo, go, closeAll } from './helpers.mjs';

const only14 = () => test.skip(test.info().project.name !== 'mac-14', 'page coverage runs once, at the default size');
const names = (page) => page.locator('.tbl.tt tbody tr[data-act="toggleTool"] .tt-name').allInnerTexts();

test('A4 tools: sorting, fail-only scope, expanded calls, matrix grid and failure drill-down', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  await go(page, 'tools');
  await expect(page.locator('.vz-kpi')).toHaveCount(4);
  await expect(page.locator('.vz-kpi .vz-spark')).toHaveCount(4);
  await expect(page.locator('.vz-kpi .vz-kpi-d').first()).toContainText('上期');
  // 名称排序（BUG-20）
  await page.locator('th button[data-k="name"]').click();
  const asc = (await names(page)).map((s) => s.trim());
  expect(asc).toEqual(asc.slice().sort((a, b) => a.localeCompare(b)));
  await page.locator('th button[data-k="name"]').click();
  const desc = (await names(page)).map((s) => s.trim());
  expect(desc).toEqual(asc.slice().reverse());
  // 仅看失败：列头与 KPI 口径同步
  await page.locator('[data-act="failOnly"]').click();
  await expect(page.locator('th button[data-k="n"]')).toContainText('失败次数');
  await expect(page.locator('.vz-kpi .vz-kpi-l').first()).toHaveText('失败次数');
  await page.locator('[data-act="failOnly"]').click();
  // 展开行：最近调用 + 跳到会话
  await page.locator('tr[data-act="toggleTool"][data-t="Bash"]').click();
  await expect(page.locator('tr.tt-open .tt-call')).toHaveCount(5);
  const jump = page.locator('tr.tt-open [data-act="openSession"]').first();
  const sid = await jump.getAttribute('data-id');
  await jump.click();
  expect(await page.evaluate(() => S.route)).toBe('sessions');
  expect(await page.evaluate(() => S.sess.sel)).toBe(sid);
  await go(page, 'tools');
  // 矩阵：HTML grid + 行 n + 悬停高亮
  await expect(page.locator('#tm .tm-c')).toHaveCount(36);
  await expect(page.locator('#tm .tm-n')).toHaveCount(6);
  await expect(page.locator('#tm .tm-c.peak')).toHaveCount(1);
  await page.locator('#tm .tm-c[data-r="1"][data-c="0"]').hover();
  await expect(page.locator('#tm')).toHaveClass(/has-hl/);
  expect(await page.locator('#tm .tm-c.hl').count()).toBe(11);
  await expect(page.locator('#tm .tm-rh[data-r="1"]')).toHaveClass(/hl/);
  await expect(page.locator('.tt-retry')).toHaveCount(5);
  // 失败原因：绝对次数 + 相关会话
  await expect(page.locator('.tt-fail .tt-fail-v').first()).toContainText('次');
  await page.locator('.tt-fail').first().click();
  await expect(page.locator('.tt-fail-x')).toContainText('典型');
  await page.locator('[data-act="failSessions"]').click();
  expect(await page.evaluate(() => [S.route, S.fric])).toEqual(['sessions', '工具 / 环境失败']);
  await page.evaluate(() => { S.fric = null; });
  await go(page, 'tools');
  // 迷你线列头随范围（BUG-85）
  await page.evaluate(() => { S.range = 7; render(); });
  await expect(page.locator('.tbl.tt thead th').last()).toHaveText('近 7 天');
  await page.evaluate(() => { S.range = 30; render(); });
  // figma 移除联动（BUG-21）
  await expect(page.locator('#main')).toContainText('2 个 MCP 服务');
  await page.evaluate(() => { S.installed.set('remove-figma', { days: 1, at: Date.now() }); render(); });
  await expect(page.locator('#main')).toContainText('1 个 MCP 服务');
  expect(await page.evaluate(() => S.tools.figma)).toBe(false);
  await page.evaluate(() => { S.installed.delete('remove-figma'); render(); });
  expect(errors).toEqual([]);
});

test('A5 projects: table fits, scatter has residuals and A/B marks, filters and comparison stay consistent', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  await go(page, 'projects');
  // 表格不裁切（A5-V01），摩擦率列存在
  const clipped = await page.evaluate(() => Array.from(document.querySelectorAll('.pj-tbl td, .pj-tbl th')).filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.textContent.trim()));
  expect(clipped).toEqual([]);
  await expect(page.locator('.pj-tbl thead')).toContainText('摩擦率');
  await expect(page.locator('.pj-pers').first()).toHaveText(/^[A-Z?]{4}$|^—$/);
  // 散点：拟合、置信带、残差、尺寸图例
  const sc = page.locator('[data-vz="pj-scatter"]');
  await expect(sc.locator('.vz-fit')).toHaveCount(1);
  await expect(sc.locator('.vz-cband')).toHaveCount(1);
  expect(await sc.locator('.pj-res').count()).toBeGreaterThan(3);
  await expect(sc.locator('.vz-scale')).toContainText('95%');
  await expect(sc.locator('.vz-rleg')).toHaveCount(2);
  // 对比模式：A / B
  await page.locator('[data-act="projCompare"]').click();
  await page.locator('tr[data-act="pickProject"][data-p="confluo"]').click();
  expect(await page.evaluate(() => [S.proj.sel, S.proj.cmp])).toEqual(['latentskill', 'confluo']);
  await expect(page.locator('.pj-tbl .bdg', { hasText: 'A' })).toHaveCount(1);
  await expect(page.locator('.pj-tbl .bdg', { hasText: 'B' })).toHaveCount(1);
  await expect(sc.locator('.pj-ring')).toHaveCount(1);
  await expect(sc.locator('.pj-ab')).toHaveCount(2);
  await expect(page.locator('#main')).toContainText('此项目 vs Confluo');
  // 退出对比后把 A 选成原 B → B 清掉（BUG-71）
  await page.locator('[data-act="projCompare"]').click();
  await page.evaluate(() => { S.proj.cmp = 'confluo'; });
  await page.locator('tr[data-act="pickProject"][data-p="confluo"]').click();
  expect(await page.evaluate(() => [S.proj.sel, S.proj.cmp])).toEqual(['confluo', null]);
  // 全局项目筛选 → 详情跟随（BUG-07）
  await page.evaluate(() => { S.project = 'teamhub'; render(); });
  expect(await page.evaluate(() => S.proj.sel)).toBe('teamhub');
  await expect(page.locator('#main h2.serif')).toHaveText('team-hub');
  await page.evaluate(() => { S.project = null; render(); });
  // 覆盖矩阵：配置类型 × 此项目用到的 Agent
  const cells = await page.evaluate(() => { const r = projRows(sel({ project: null })).find((x) => x.p.id === S.proj.sel); return r.p.cover.length * r.split.filter((v) => v > 0).length; });
  await expect(page.locator('.pj-cov .pj-cov-c')).toHaveCount(cells);
  await expect(page.locator('.pj-ag')).toHaveCount(await page.evaluate(() => projRows(sel({ project: null })).find((x) => x.p.id === S.proj.sel).split.filter((v) => v > 0).length));
  expect(errors).toEqual([]);
});

test('A6 sentiment: distribution band with shared cursor, table view, topics, phrase sources and AI badges', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  await go(page, 'sentiment');
  const mood = page.locator('[data-vz="mood"]');
  await expect(mood.locator('svg.vz-svg')).toHaveCount(1);
  await expect(mood.locator('.sn-band').first()).toBeVisible();
  await expect(mood.locator('.vz-line')).toHaveCount(1);
  expect(await mood.locator('.vz-bar').count()).toBeGreaterThan(10);
  await expect(mood.locator('.vz-xline')).toHaveCount(1);
  // 游标跨两图：x 线从上图顶部到下图底部
  const span = await mood.locator('.vz-xline').evaluate((l) => +l.getAttribute('y2') - +l.getAttribute('y1'));
  expect(span).toBeGreaterThan(150);
  const box = await mood.locator('.vz-plot').boundingBox();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.3);
  await page.mouse.move(box.x + box.width * 0.5 + 1, box.y + box.height * 0.3);
  await expect.poll(() => mood.locator('.vz-xline').getAttribute('hidden')).toBeNull();
  await expect(mood.locator('.vz-tip')).toBeVisible();
  await expect(mood.locator('.vz-tip')).toContainText('情绪中位数');
  await expect(mood.locator('.vz-tip')).toContainText('纠偏');
  // 表格视图
  await page.locator('[data-act="moodView"]').click();
  await expect(page.locator('[data-vz="mood"] table')).toHaveCount(1);
  await expect(page.locator('[data-vz="mood"] thead')).toContainText('P25');
  await page.locator('[data-act="moodView"]').click();
  await expect(page.locator('[data-vz="mood"] svg.vz-svg')).toHaveCount(1);
  // 主题筛选不吞掉其它主题（BUG-72）
  const before = await page.locator('.sn-topic').count();
  await page.locator('.sn-topic[data-k="git"]').click();
  expect(await page.evaluate(() => S.topic)).toBe('git');
  await expect(page.locator('.sn-topic')).toHaveCount(before);
  await expect(page.locator('.sn-topic.on')).toHaveCount(1);
  await page.locator('.sn-topic[data-k="git"]').click();
  expect(await page.evaluate(() => S.topic)).toBe(null);
  // 反馈语按次数降序，出处因短语而异（BUG-73）
  const counts = await page.locator('.sn-ph-n').allInnerTexts();
  const nums = counts.map((t) => +t.replace('×', ''));
  expect(nums).toEqual(nums.slice().sort((a, b) => b - a));
  const src = await page.evaluate(() => [phraseSources('直接合并', '纠偏').map((s) => s.id), phraseSources('别用子代理', '纠偏').map((s) => s.id), phraseSources('用中文', '偏好').map((s) => s.id)]);
  expect(src[0].length).toBe(3);
  expect(src[0]).not.toEqual(src[1]);
  expect(src[0]).not.toEqual(src[2]);
  await page.locator('.sn-ph').first().click();
  await expect(page.locator('#dd')).toBeVisible();
  await expect(page.locator('#dd')).toContainText('出处');
  await closeAll(page);
  // 摩擦分类 hover 列典型会话
  await page.locator('.sn-fric[data-act="fricGo"]').first().hover();
  await expect(page.locator('#tip')).toContainText('典型会话');
  // 周聚合说明（BUG-69）
  await page.evaluate(() => { S.range = 90; render(); });
  await expect(page.locator('#main')).toContainText('每周桶');
  await page.evaluate(() => { S.range = 30; render(); });
  // AI 抽取标识
  expect(await page.locator('#main .aib').count()).toBeGreaterThanOrEqual(4);
  expect(errors).toEqual([]);
});

test('tools, projects and sentiment render in light and dark without errors or overflow', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  for (const theme of ['light', 'dark']) {
    await page.evaluate((t) => setTheme(t), theme);
    for (const r of ['tools', 'projects', 'sentiment']) {
      await go(page, r);
      const over = await page.evaluate(() => { const c = document.querySelector('#main .content'); return c ? c.scrollWidth - c.clientWidth : 0; });
      expect(over, theme + ' ' + r).toBeLessThanOrEqual(1);
    }
  }
  await page.evaluate(() => setTheme('light'));
  expect(errors).toEqual([]);
});
