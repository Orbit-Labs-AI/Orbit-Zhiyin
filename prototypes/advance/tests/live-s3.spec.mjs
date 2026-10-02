// Slice 3 (A4 tools / A5 projects): the polished pages read /v1/uiview/tools, /v1/uiview/projects(+/{id}),
// /v1/features/linked and /v1/analytics/tool_calls; same cards, no plain tables, no demo rows; honest empty states.
// Fixtures: prototypes/shared/fixtures/core + s3 (synthetic, real agent ids; LIVE_GATEWAY switches to a real gateway).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
const TOOLS = fx('s3/tools.json');
const PROJ = fx('s3/projects.json');
const ALPHA = fx('s3/project-alpha.json');
const MOCK = /Confluo|latentskill|wrangler deploy --env production|mcp·figma|mcp·browser|Gemini CLI|Copilot CLI|design-review/;
const NODE = { read: 'Read', search: 'Search', edit: 'Edit', shell: 'Shell', subagent: 'Task', web: 'Web', other: 'Other' };

test.beforeEach(async ({ page }) => { ONLY('mac-14'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

async function noPlain(page) {
  expect(await page.locator('.tl-table, .tl-kpi').count()).toBe(0);
  expect(await page.locator('#main').innerText()).not.toMatch(MOCK);
}

test('A4: table, matrix, failures, retries and header equal /v1/uiview/tools', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await expect(page.locator('#main table.tt tbody tr').first()).toBeVisible();
  if (PASS) { await noPlain(page); expect(errors).toEqual([]); return; }
  // table rows: server order by calls, names and counts
  const rows = await page.locator('#main table.tt tbody tr[data-t]').evaluateAll((trs) => trs.map((tr) => [tr.dataset.t, tr.querySelector('.tt-num').textContent]));
  const want = TOOLS.tools.slice().sort((a, b) => b.n - a.n).map((t) => [t.name, t.n.toLocaleString('en-US')]);
  expect(rows.map((r) => r[0])).toEqual(want.map((w) => w[0]));
  expect(rows.map((r) => r[1].replace(/,/g, ''))).toEqual(want.map((w) => w[1].replace(/,/g, '')));
  // matrix: labels and P(next | prev) %
  const tm = await page.evaluate(() => ({ names: Array.from(document.querySelectorAll('#tm .tm-h.mono[data-c]')).map((x) => x.textContent), cells: Array.from(document.querySelectorAll('#tm .tm-c')).map((x) => +x.textContent), n: Array.from(document.querySelectorAll('#tm .tm-n')).length }));
  expect(tm.names).toEqual(TOOLS.matrix.nodes.map((n) => NODE[n]));
  expect(tm.cells).toEqual(TOOLS.matrix.prob.flat().map((p) => Math.round(p * 100)));
  // failures: label · share · count
  const fails = await page.locator('#main .tt-fail').evaluateAll((bs) => bs.map((b) => [b.querySelector('.tt-fail-n').textContent, b.querySelector('.tt-fail-v').textContent]));
  expect(fails).toEqual(TOOLS.failures.rows.map((f) => [f.label, Math.round(f.share * 100) + '% · ' + f.n + ' 次']));
  const retries = await page.locator('#main .tt-retry .tt-cmd').allTextContents();
  expect(retries).toEqual(TOOLS.retries.slice(0, 5).map((r) => r.command));
  const meta = await page.locator('#main').innerText();
  expect(meta).toContain(TOOLS.header.tool_kinds + ' 种工具');
  expect(meta).toContain('mcp·github');
  // waits + parallel charts mounted from the server buckets
  await expect(page.locator('[data-vz="waits"] svg')).toBeVisible();
  await expect(page.locator('[data-vz="par"] svg')).toBeVisible();
  await noPlain(page);
  // one request per scope; agent filter → agent=<backend id>
  expect(gw.seen.filter((x) => x.path === '/v1/uiview/tools').length).toBe(1);
  await page.evaluate(() => { S.agents = new Set(['cc']); render(); });
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/tools' && /agent=claude_code/.test(x.query))).toBe(true);
  expect(errors).toEqual([]);
});

test('A4: a row opens its recent calls from /v1/analytics/tool_calls; topic filter shows the scope note', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await page.locator('#main tr[data-t="Bash"]').click();
  await expect(page.locator('[data-lv="tool-calls"] .tt-call')).toHaveCount(2);
  await expect(page.locator('[data-lv="tool-calls"]')).toContainText('pytest -q tests/');
  await expect(page.locator('[data-lv="tool-calls"]')).toContainText('exit 1');
  const q = gw.seen.filter((x) => x.path === '/v1/analytics/tool_calls');
  expect(q.length).toBe(1); expect(q[0].query).toMatch(/name=Bash/);
  // collapse + reopen = LRU hit (no second request)
  await page.locator('#main tr[data-t="Bash"]').click();
  await page.locator('#main tr[data-t="Bash"]').click();
  await expect(page.locator('[data-lv="tool-calls"] .tt-call')).toHaveCount(2);
  expect(gw.count('/v1/analytics/tool_calls')).toBe(1);
  await expect(page.locator('[data-lv="scope-note"]')).toHaveCount(0);
  await page.evaluate(() => { S.topic = 'bug'; render(); });
  await expect(page.locator('[data-lv="scope-note"]')).toContainText('主题');
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('A4: missing route, empty body and empty spine render honest empty states', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/tools': { status: 404 } });
  await openLive(page, 'tools');
  await expect(page.locator('#main')).toContainText('本地服务暂不提供工具统计');
  expect(await page.locator('#main .tt-fail, #main .tm-c, #main table.tt').count()).toBe(0);
  await noPlain(page);
  gw.set('GET /v1/uiview/tools', fx('s3/tools-empty.json'));
  gw.set('GET /v1/uiview/facts', fx('core/facts-empty.json'));
  await page.reload();
  await expect.poll(() => page.evaluate(() => LV.state), { timeout: 10_000 }).toBe('empty');
  await expect(page.locator('#main')).toContainText('还没有导入会话');
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('A5: rows, persona, compare, workflow, coverage, rule files and top rec come from the projects endpoints', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's3'], {
    'GET /v1/uiview/projects': (req, u) => u.searchParams.get('group') === 'folder' ? fx('s3/projects-folder.json') : PROJ
  }, { native: { v: 1, app: '0.0.1', platform: 'macos', features: ['reveal'] } });
  await openLive(page, 'projects');
  await expect(page.locator('#main .pj-tbl tbody tr[data-p]').first()).toBeVisible();
  if (PASS) { await noPlain(page); expect(errors).toEqual([]); return; }
  const rows = await page.locator('#main .pj-tbl tbody tr[data-p]').evaluateAll((trs) => trs.map((tr) => [tr.dataset.p, tr.querySelector('.pj-title').textContent.trim(), tr.cells[1].textContent, tr.querySelector('.pj-pers').textContent]));
  const want = PROJ.projects.slice().sort((a, b) => b.hours.value - a.hours.value).map((p) => [p.project_id, p.name, String(p.sessions), p.persona.code || '—']);
  expect(rows).toEqual(want);
  // detail for the selected project (alpha = most hours)
  await expect(page.locator('#main .pj-step')).toHaveCount(ALPHA.workflows[0].steps.length);
  const steps = await page.locator('#main .pj-step b').allTextContents();
  expect(steps).toEqual(ALPHA.workflows[0].steps.map((s) => s.head || s.name));
  await expect(page.locator('#main .pj-cov-r')).toHaveCount(ALPHA.coverage.length);
  await expect(page.locator('#main .pj-vs')).toHaveCount(ALPHA.vs.metrics.length);
  await expect(page.locator('[data-lv="rule-files"]')).toContainText('AGENTS.md');
  await expect(page.locator('#main')).toContainText(ALPHA.top_recommendation.title);
  await expect(page.locator('#main .pj-pline')).toContainText('DPMV');
  await expect(page.locator('[data-vz="pj-scatter"]')).toBeAttached();
  // agent split uses real agent colors only
  const split = await page.locator('#main .pj-share span').evaluateAll((s) => s.map((x) => x.style.background));
  expect(split.length).toBe(ALPHA.agents.length);
  // Finder → native reveal of the project folder
  await page.locator('#main [data-act="finder"]').click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'reveal').map((m) => m.path))).toEqual([ALPHA.header.path]);
  // compare: B = beta → compare=proj_beta on the detail request
  await page.locator('#main [data-act="projCompare"]').click();
  await page.locator('#main tr[data-p="proj_beta"]').click();
  await expect.poll(() => gw.seen.some((x) => x.path === '/v1/uiview/projects/proj_alpha' && /compare=proj_beta/.test(x.query))).toBe(true);
  await expect(page.locator('#main')).toContainText('此项目 vs beta-lib');
  await page.locator('#main [data-act="projCompare"]').click();
  // folder grouping from the server folders
  await page.locator('#main [data-act="projGroup"][data-v="folder"]').click();
  await expect.poll(() => page.locator('#main .pj-tbl tbody tr[data-p] .pj-title').allTextContents()).toEqual(fx('s3/projects-folder.json').folders.map((f) => f.cwd));
  // beta: no workflow, no rule files, no rec → honest text
  await page.locator('#main [data-act="projGroup"][data-v="project"]').click();
  await page.locator('#main tr[data-p="proj_beta"]').click();
  await expect(page.locator('#main')).toContainText('还没有识别到重复出现的工作流');
  await expect(page.locator('#main')).toContainText('暂时没有针对这个项目的建议');
  await page.evaluate(() => { S.outcome = 'ok'; render(); });
  await expect(page.locator('[data-lv="scope-note"]')).toContainText('结果');
  await noPlain(page);
  expect(errors).toEqual([]);
});

test('A5: projects 503 on an empty spine renders the empty state', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's3'], { 'GET /v1/uiview/facts': fx('core/facts-empty.json'), 'GET /v1/uiview/projects': { status: 503, body: { error: { code: 'no_projection', message: 'No canonical database yet', retryable: true } } } });
  await openLive(page, 'projects');
  await expect(page.locator('#main')).toContainText(/还没有导入会话|本地服务暂不提供项目统计/);
  await noPlain(page);
  expect(errors).toEqual([]);
});
