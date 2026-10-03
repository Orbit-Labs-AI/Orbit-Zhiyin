// A4 工具调用 / A5 项目习惯 / A6 情绪与语义 页面测试（分支 ui/p-tools-projects-sentiment）。流程：
//   A4：1. 打开 demo 进入 tools；KPI 四卡各带迷你线与环比；2. 点「工具」列头两次，行顺序按名称升 / 降变化（BUG-20）；
//       3. 「仅看失败」后列头与 KPI 口径同步为「失败次数」；4. 展开 Bash 行，出现最近调用与「在轨迹中查看」，点击跳到会话页；
//       5. 调用链矩阵为 HTML grid（36 个格子 + 6 个行 n），悬停一格高亮整行整列（.hl）；6. 展开一类失败原因，「相关会话」把 S.fric 设为工具失败并进入 sessions；
//       7. 切到 7 天后迷你线列头随范围（BUG-85）；8. 标记 figma 已移除后页头变为 1 个 MCP，S.tools.figma 同步（BUG-21）。
//   A5：1. 项目表任何单元格不被裁切（scrollWidth ≤ clientWidth），含摩擦率列；2. 散点挂载为 pscatter：有拟合线、置信带、残差竖线与尺寸图例；
//       3. 对比模式下点第二个项目：表中出现 A / B 徽标、散点出现 B 环；4. 全局项目筛选 → 详情定位到该项目（BUG-07）；
//       5. 退出对比后 A 选成原 B → B 被清掉（BUG-71）；6. 覆盖矩阵格子数 = 配置类型数 × 项目用到的 Agent 数。
//   A6：1. 情绪图为 moodcorr：分布带 + 中位线 + 纠偏柱共用一张 svg，一条游标跨两图；指针移动后游标可见、tooltip 含「情绪中位数」与「纠偏」；
//       2. 「看表格」切到表格视图并可切回；3. 语义主题、情绪前因两卡已删除；4. 不同反馈语的出处不同（BUG-73）；
//       5. 90 天时说明文字为「每周」（BUG-69）；6. AI 抽取内容带紫色 .aib 标识；7. 三页浅 / 深色均无页面错误；
//       8. 高频词：词云不重叠、不出框，Top 10 与 WORDS 一致，悬停显示次数与天数，点击打开命令面板搜索该词；最小窗口与大窗口都正常；空态。
import { test, expect } from '@playwright/test';
import { openDemo, go, closeAll } from './helpers.mjs';

const only14 = () => test.skip(test.info().project.name !== 'mac-14', 'page coverage runs once, at the default size');
const names = (page) => page.locator('.tbl.tt tbody tr[data-act="toggleTool"] .tt-name').allInnerTexts();

test('A4 tools: sorting, fail-only scope, expanded calls, matrix grid and failure drill-down', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  await go(page, 'tools');
  // F24：「仅看失败」首次进入默认开启，切换后记住；调用链矩阵在明细表之前，明细表在页面最下方
  await expect(page.locator('[data-act="failOnly"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('th button[data-k="n"]')).toContainText('失败次数');
  const order = await page.locator('#main .stack > *').evaluateAll((ns) => ns.map((n) => n.className.split(' ')[0] + (n.querySelector('table.tt') ? ':table' : '')));
  expect(order).toEqual(['tiles', 'tt-grid', 'card:table']);
  await page.locator('[data-act="failOnly"]').click();
  expect(await page.evaluate(() => store.get('toolsFailOnly', true))).toBe(false);
  // MCP 服务：完整服务名，展开后列出其下工具；各工具次数之和 = 服务次数
  await page.locator('[data-act="toggleMcp"][data-k="browser"]').click();
  const mcpTools = page.locator('[data-lv="mcp-tools"] .tt-mcp-t');
  await expect(mcpTools).toHaveCount(3);
  const mcpSum = (await page.locator('[data-lv="mcp-tools"] .tt-mcp-tv').allTextContents()).reduce((a, t) => a + parseInt(t.replace(/,/g, ''), 10), 0);
  expect(String(mcpSum)).toBe((await page.locator('[data-mcp="browser"] .tt-mcp-v').textContent()).match(/^([\d,]+) 次/)[1].replace(/,/g, ''));
  await expect(page.locator('[data-mcp="browser"] .tt-mcp-n')).toHaveText('mcp·browser');
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

test('A6 sentiment: distribution band with shared cursor, table view, phrase sources and AI badges', async ({ page }) => {
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
  // 语义主题与情绪前因两卡已删除
  await expect(page.locator('#main .sn-topic, #main .sn-drv')).toHaveCount(0);
  await expect(page.locator('#main')).not.toContainText('语义主题');
  await expect(page.locator('#main')).not.toContainText('情绪的前因');
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
  expect(await page.locator('#main .aib').count()).toBeGreaterThanOrEqual(3);
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

// 高频词词云：可见词两两不重叠、都在框内；字号随次数单调；Top 10 次数降序；悬停 / 点击；窗口最小 960×640 与大窗口
const cloudGeo = (page) => page.evaluate(() => {
  const box = document.querySelector('#main .sn-cloud').getBoundingClientRect();
  const ws = [...document.querySelectorAll('#main .sn-w')];
  const vis = ws.filter((w) => !w.classList.contains('off')).map((w) => ({ r: w.getBoundingClientRect(), n: +w.dataset.n, f: parseFloat(w.style.fontSize) }));
  let ov = 0; for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) { const a = vis[i].r, b = vis[j].r; if (a.left < b.right - 1 && a.right > b.left + 1 && a.top < b.bottom - 1 && a.bottom > b.top + 1) ov++; }
  const out = vis.filter(({ r }) => r.left < box.left - 1 || r.right > box.right + 1 || r.top < box.top - 1 || r.bottom > box.bottom + 1).length;
  const mono = vis.every((a) => vis.every((b) => !(a.n > b.n) || a.f >= b.f - 0.01));
  return { n: ws.length, shown: vis.length, ov, out, mono, w: box.width, h: box.height };
});
test('A6 高频词: word cloud layout, Top 10, tooltip, click to search, window sizes and empty state', async ({ page }) => {
  only14();
  const errors = await openDemo(page);
  await go(page, 'sentiment');
  await expect(page.locator('#main .sn-wcard .ct')).toHaveText('高频词');
  const g = await cloudGeo(page);
  expect(g.n).toBeGreaterThan(30);
  expect(g.shown).toBeGreaterThanOrEqual(Math.floor(g.n * 0.9));
  expect(g).toMatchObject({ ov: 0, out: 0, mono: true });
  // Top 10：次数降序、与词云同一组数据，带「次」「天」
  const top = await page.locator('#main .sn-tw:not(.sn-tw-h)').evaluateAll((els) => els.map((e) => [e.querySelector('.sn-tw-t').textContent, +e.querySelector('.sn-tw-n').textContent.replace(/[^\d]/g, ''), e.querySelector('.sn-tw-d').textContent]));
  expect(top.length).toBe(10);
  expect(top.map((x) => x[1])).toEqual(top.map((x) => x[1]).slice().sort((a, b) => b - a));
  expect(top.every((x) => / 天$/.test(x[2]))).toBe(true);
  expect(await page.locator('#main .sn-w').first().getAttribute('data-k')).toBe(top[0][0]);
  // 悬停：出现 N 次 · N 天
  await page.locator('#main .sn-w:not(.off)').first().hover();
  await expect(page.locator('#tip')).toContainText(/出现 \d+ 次 · \d+ 天/);
  // 点击：命令面板以该词为查询
  const word = await page.locator('#main .sn-w:not(.off)').nth(1).getAttribute('data-k');
  await page.locator('#main .sn-w:not(.off)').nth(1).click();
  await expect(page.locator('#palQ')).toHaveValue(word);
  await expect(page.locator('#palList')).not.toBeEmpty();
  await closeAll(page);
  await page.locator('#main .sn-tw:not(.sn-tw-h)').first().click();
  await expect(page.locator('#palQ')).toHaveValue(top[0][0]);
  await closeAll(page);
  // 最小窗口 960×640：词云与 Top 10 仍各自完整，内容不横向溢出
  await page.evaluate(() => { Object.assign(S.win, { x: 40, y: 40, w: 960, h: 640 }); render(); });
  await expect.poll(async () => (await cloudGeo(page)).w).toBeLessThan(g.w);
  const gs = await cloudGeo(page);
  expect(gs).toMatchObject({ ov: 0, out: 0 });
  expect(gs.shown).toBeGreaterThanOrEqual(Math.floor(gs.n * 0.9));
  expect(await page.evaluate(() => { const c = document.querySelector('#main .content'); return c.scrollWidth - c.clientWidth; })).toBeLessThanOrEqual(1);
  // 没有可用词：空态，没有词也没有 Top 10
  await page.evaluate(() => { Object.assign(S.win, { x: null, y: null, w: null, h: null }); window.__words = WORDS.splice(0); render(); });
  await expect(page.locator('#main [data-wc-empty]')).toBeVisible();
  await expect(page.locator('#main .sn-w, #main .sn-tw')).toHaveCount(0);
  await page.evaluate(() => { WORDS.push(...window.__words); render(); });
  await expect(page.locator('#main .sn-w').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('A6 高频词 fits the studio window too', async ({ page }) => {
  test.skip(test.info().project.name !== 'studio', 'large display only');
  const errors = await openDemo(page);
  await go(page, 'sentiment');
  const g = await cloudGeo(page);
  expect(g).toMatchObject({ ov: 0, out: 0, mono: true });
  expect(g.shown).toBe(g.n);
  expect(errors).toEqual([]);
});
