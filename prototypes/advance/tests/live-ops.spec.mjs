// Live ops bindings (src/js/98-live-ops.js + the ops section of prototypes/shared/tandem-live.js). Fixture mode: page.route
// plays the gateway on http://tandem.test with the synthetic files in prototypes/shared/fixtures (+ ops/). Sibling of
// live-adapter.spec.mjs, kept separate so the binding branches do not edit the same spec.
//  1. realtime   snapshot → HUD pill / card, menu-bar panel (failing command, context %, live card), 忽略 → dismiss; a stream
//                frame moves everything to the calm snapshot
//  2. A3         不计入分析 with a reason, excluded list + badge, 恢复, 复制继续命令, 定位原始日志
//  3. A4         tool row → call drilldown, 加载更多 (cursor), 失败 filter, a call opens its session
//  4. export     report markdown, tool-call CSV, share card (live payload, save → snapshot); blocked card → reason toast
//  5. degrade    realtime / sessionops / export missing (404): demo HUD and panel with 示例数据, demo report, honest toasts
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ADV_FILE = path.join(ROOT, 'advance', 'tandem-demo.html');
const FX = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'fixtures', name + '.json'), 'utf8'));
const OPS = (name) => FX('ops/' + name);
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');

function collectErrors(page) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (/fonts\.(googleapis|gstatic)\.com/.test(m.location().url || '')) return;
    if (/status of 404/.test(m.text())) return;
    errors.push(m.text());
  });
  return errors;
}
// realtime fixtures carry absolute timestamps: move them so generated_at is now (lanes / since stay relative)
function rtNow(name) {
  const o = OPS(name); const dt = Date.now() - o.generated_at;
  const mv = (x) => (typeof x === 'number' ? x + dt : x);
  o.generated_at += dt;
  o.sessions.forEach((s) => { s.since = mv(s.since); if (s.lanes) Object.keys(s.lanes).forEach((k) => { s.lanes[k] = s.lanes[k].map(mv); }); });
  return o;
}

// state: ops = false answers 404 for realtime / sessionops / export; stream = fixture name the next stream connection sends
// (null → an empty stream that ends at once); share = 'blocked' for an ineligible card; excluded flips after POST exclude.
async function gateway(page, opts = {}) {
  const state = Object.assign({ ops: true, stream: null, share: 'ok', excluded: false, seen: [] }, opts);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/^http:\/\/tandem\.test\//, async (route) => {
    const req = route.request(); const u = new URL(req.url()); const m = req.method(); const p = u.pathname;
    let body = null; try { body = req.postData() ? JSON.parse(req.postData()) : null; } catch (e) { body = null; }
    state.seen.push({ m, path: p, q: Object.fromEntries(u.searchParams), body });
    const json = (b, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) });
    const nf = () => json({ error: { code: 'not_found', message: p, retryable: false } }, 404);
    if (p === '/app') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(ADV_FILE, 'utf8') });
    if (p === '/v1/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    const core = { '/v1/status': 'status', '/v1/analytics/overview': 'overview', '/v1/analytics/sessions': 'sessions', '/v1/sessions/fx-s1/events': 'session-events', '/v1/analytics/tools': 'tools', '/v1/app/sources': 'app-sources', '/v1/app/settings': 'app-settings' };
    if (m === 'GET' && core[p]) return json(FX(core[p]));
    const ops = p.startsWith('/v1/analytics/realtime') || p.startsWith('/v1/export/') || p === '/v1/analytics/tool_calls' || /^\/v1\/sessions\/[^/]+\/(exclude|resume|source_location)$/.test(p) || p === '/v1/sessions/excluded';
    if (!ops) return nf();
    if (!state.ops) return nf();
    if (p === '/v1/analytics/realtime/stream') { const n = state.stream; state.stream = null; return route.fulfill({ status: 200, contentType: 'text/event-stream', body: n ? 'retry: 2000\n\nevent: realtime\ndata: ' + JSON.stringify(rtNow(n)) + '\n\n' : '' }); }
    if (p === '/v1/analytics/realtime') return json(rtNow('realtime-active'));
    if (p === '/v1/analytics/tool_calls') return json(OPS(u.searchParams.get('cursor') ? 'tool-calls-p2' : u.searchParams.get('status') === 'failed' ? 'tool-calls-failed' : 'tool-calls-p1'));
    if (p === '/v1/export/csv') return route.fulfill({ status: 200, contentType: 'text/csv; charset=utf-8', body: fs.readFileSync(path.join(ROOT, 'shared', 'fixtures', 'ops', 'export-csv.csv'), 'utf8') });
    if (p === '/v1/sessions/excluded') return json(OPS(state.excluded ? 'excluded-after' : 'excluded'));
    if (m === 'POST' && p === '/v1/sessions/fx-s1/exclude') { state.excluded = true; return json(OPS('exclude')); }
    if (m === 'POST' && p === '/v1/export/share_card') return json(state.share === 'blocked' ? OPS('export-share-blocked') : body && body.save ? OPS('export-snapshot-saved') : OPS('export-share-card'));
    const routes = {
      'POST /v1/analytics/realtime/fx-rt-fail/dismiss': 'dismiss', 'DELETE /v1/sessions/fx-s2/exclude': 'include',
      'GET /v1/sessions/fx-s1/resume': 'resume', 'GET /v1/sessions/fx-s1/source_location': 'source-location', 'POST /v1/export/report': 'export-report'
    };
    if (routes[m + ' ' + p]) return json(OPS(routes[m + ' ' + p]));
    return nf();
  });
  return state;
}
const sent = (gw, m, p) => gw.seen.filter((s) => s.m === m && s.path === p);
async function open(page) {
  await page.goto('http://tandem.test/app#token=fx-token');
  await expect.poll(() => page.evaluate(() => TL.mode)).toBe('live');
}

test('realtime: HUD and menu-bar panel follow the snapshot; 忽略 dismisses; a stream frame calms everything down', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await open(page);
  await expect.poll(() => page.evaluate(() => [S.simBase, S.attn.has('stuck'), S.attn.has('ctx'), S.waitOpen, S.hudSim])).toEqual(['running', true, true, true, 'stuck']);
  expect(sent(gw, 'GET', '/v1/analytics/realtime')[0].q).toEqual({ lanes: '1' });
  await expect(page.locator('#hudPill')).toContainText('同一命令失败 5 次');
  await expect(page.locator('#hudPill')).toContainText('fx-rules');
  // the running session's numbers come from the snapshot (since, context ratio, lane counts)
  expect(await page.evaluate(() => [S.live.ctx, S.live.tools, HUD_TOOLS[0], Math.round((Date.now() - S.live.t0) / 60000)])).toEqual([91, 9, 'Edit src/js/98-live-ops.js', 23]);
  // desktop widget 今日: sessions started today and the running project from the snapshot
  await expect(page.locator('#widgets [data-r="sessions"] .mono').first()).toHaveText('7');
  await expect(page.locator('#widgets [data-r="sessions"]')).toContainText('fx-tandem');
  await page.evaluate(() => { S.pop = true; render(); });
  const pop = page.locator('#pop');
  await expect(pop.locator('[data-tl="rt-failing"]')).toContainText('make publish');
  await expect(pop.locator('[data-tl="rt-failing"]')).toContainText('令牌过期');
  await expect(pop.locator('[data-tl="rt-ctx"]')).toContainText('91%');
  await expect(pop.locator('[data-tl="rt-ctx"]')).toContainText('fx-tandem');
  await expect(pop.locator('[data-tl="rt-live"]')).toContainText('合成会话：整理 HUD 绑定');
  await pop.locator('[data-tl="rt-failing"] [data-act="popIgnore"]').click();
  await expect.poll(() => sent(gw, 'POST', '/v1/analytics/realtime/fx-rt-fail/dismiss').map((s) => s.body)).toEqual([{ seconds: 3600 }]);
  // HUD card: live agent / project / title, the other sessions
  await page.evaluate(() => { S.pop = false; S.hud.open = true; S.hudSim = 'running'; render(); });
  const card = page.locator('#hud .hcard[data-tl="rt-hud"]');
  await expect(card).toContainText('合成会话：整理 HUD 绑定');
  await expect(card).toContainText('Claude Code');
  await expect(card).toContainText('等你确认 3 分钟');
  // next stream connection sends the calm snapshot: no alerts, running on fx-tandem
  gw.stream = 'realtime-calm';
  await expect.poll(() => page.evaluate(() => [S.attn.has('stuck'), S.attn.has('ctx'), S.waitOpen, S.hudSim, S.live.ctx]), { timeout: 20000 }).toEqual([false, false, false, 'running', 41]);
  await page.evaluate(() => { S.hud.open = false; render(); });
  await expect(page.locator('#hudPill')).toContainText('fx-tandem');
  expect(errors).toEqual([]);
});

test('A3 live: exclude with a reason, excluded list and badge, include, resume command, raw-log location', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await open(page);
  await page.evaluate(() => go('sessions'));
  await expect(page.locator('[data-tl="excluded-list"]')).toContainText('合成会话 2');
  await expect(page.locator('tr[data-id="fx-s2"] [data-tl="excluded"]')).toBeVisible();
  await page.locator('tr[data-id="fx-s1"]').click();
  const opsRow = page.locator('[data-tl="sess-ops"]');
  await opsRow.getByRole('button', { name: '不计入分析' }).click();
  await page.locator('#dd').getByRole('menuitem', { name: '测试会话' }).click();
  await expect.poll(() => sent(gw, 'POST', '/v1/sessions/fx-s1/exclude').map((s) => s.body)).toEqual([{ reason: 'test' }]);
  await expect(page.locator('tr[data-id="fx-s1"] [data-tl="excluded"]')).toBeVisible();
  await expect(opsRow.getByRole('button', { name: '恢复计入分析' })).toBeVisible();
  await page.locator('[data-tl="excluded-list"] [data-act="tloInclude"][data-id="fx-s2"]').click();
  await expect.poll(() => sent(gw, 'DELETE', '/v1/sessions/fx-s2/exclude').length).toBe(1);
  await page.locator('[data-tl="sess-ops"] [data-act="tloResume"]').click();
  // http://tandem.test is not a secure context, so copyText falls back to its manual-copy sheet with the same text
  await expect(page.locator('#copyArea')).toHaveValue("cd '/tmp/fx project' && claude --resume fx-native-1");
  await page.evaluate(() => closeModal());
  await page.locator('[data-tl="sess-ops"] [data-act="tloLocate"]').click();
  const loc = page.locator('#modal [data-tl="locate"]');
  await expect(loc).toContainText('/tmp/fx-home/.claude/projects/fx/fx-native-1.jsonl');
  await expect(loc).toContainText('文件已不存在');
  expect(errors).toEqual([]);
});

test('A4 live: tool row opens the call drilldown, 加载更多 pages by cursor, 失败 filters, a call opens its session', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await open(page);
  await page.evaluate(() => go('tools'));
  await page.locator('[data-tl="tools"] tr[data-name="Bash"]').click();
  const calls = page.locator('[data-tl="tool-calls"]');
  await expect(calls.locator('tbody tr')).toHaveCount(3);
  await expect(calls).toContainText('pnpm test --filter fx-2');
  expect(sent(gw, 'GET', '/v1/analytics/tool_calls')[0].q).toEqual({ limit: '50', name: 'Bash', status: 'all' });
  await calls.getByRole('button', { name: '加载更多' }).click();
  await expect(calls.locator('tbody tr')).toHaveCount(5);
  expect(sent(gw, 'GET', '/v1/analytics/tool_calls')[1].q.cursor).toBe('fx-cursor-2');
  await expect(calls.getByRole('button', { name: '加载更多' })).toHaveCount(0);
  await calls.getByRole('button', { name: '失败' }).click();
  await expect(calls.locator('tbody tr')).toHaveCount(2);
  expect(sent(gw, 'GET', '/v1/analytics/tool_calls').at(-1).q.status).toBe('failed');
  await calls.locator('tbody tr').first().click();
  await expect.poll(() => page.evaluate(() => [S.route, S.lvSess])).toEqual(['sessions', 'fx-s2']);
  expect(errors).toEqual([]);
});

test('export live: report markdown, tool-call CSV, share card from the payload and save; blocked card shows the reason', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const gw = await gateway(page);
  await open(page);
  await page.evaluate(() => openReport());
  await expect(page.locator('#repText')).toHaveValue(/合成样本/);
  expect(sent(gw, 'POST', '/v1/export/report')[0].body.sections).toEqual(['overview', 'metrics', 'persona', 'projects', 'friction', 'recommendations']);
  await page.locator('#modal input[data-k="persona"]').uncheck();
  await expect.poll(() => sent(gw, 'POST', '/v1/export/report').length).toBe(2);
  expect(sent(gw, 'POST', '/v1/export/report')[1].body.sections).not.toContain('persona');
  await expect.poll(() => page.evaluate(() => CUR.report)).toMatch(/合成样本/);
  await page.evaluate(() => { closeModal(); openCSV(); });
  await expect(page.locator('#modal textarea[data-tl="csv"]')).toHaveValue(/fx-call-2,fx-s2,Bash,failed/);
  await expect(page.locator('#modal .mh .cap')).toContainText('tool_calls · 2 行');
  expect(sent(gw, 'GET', '/v1/export/csv')[0].q).toMatchObject({ table: 'tool_calls', limit: '500' });
  await page.evaluate(() => { closeModal(); openShare(); });
  const card = page.locator('#modal [data-tl="share-card"]');
  await expect(card).toContainText('指挥家');
  await expect(card).toContainText('The Conductor');
  await expect(card).toContainText('实验性画像，仅供参考');
  await page.locator('#modal [data-act="shareSave"]').click();
  await expect.poll(() => sent(gw, 'POST', '/v1/export/share_card').map((s) => s.body.save)).toEqual([false, true]);
  await expect(page.locator('.toast, #toast').last()).toContainText('已存为分享卡快照');
  await page.evaluate(() => closeModal());
  gw.share = 'blocked';
  await page.evaluate(() => openShare());
  await expect(page.locator('.toast, #toast').last()).toContainText('样本不足');
  expect(await page.evaluate(() => MODAL_KEY)).toBe(null);
  expect(errors).toEqual([]);
});

test('degrade: without realtime, sessionops and export routes the demo HUD / panel / report stay, with 示例数据', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await gateway(page, { ops: false });
  await open(page);
  await expect.poll(() => page.evaluate(() => TLO.demo)).toBe(true);
  expect(await page.evaluate(() => [S.simBase, HUD_TOOLS.length > 1])).toEqual(['running', true]);
  await expect(page.locator('#hudPill')).toBeVisible();
  await page.evaluate(() => { S.pop = true; render(); });
  await expect(page.locator('#pop [data-tl="sample"]')).toBeVisible();
  await page.evaluate(() => { S.pop = false; render(); openReport(); });
  await expect(page.locator('#repText')).toHaveValue(/示例数据/);
  await expect(page.locator('#modal .mh [data-tl="sample"]')).toBeVisible();
  await page.evaluate(() => { closeModal(); go('sessions'); });
  await page.locator('tr[data-id="fx-s1"]').click();
  await page.locator('[data-tl="sess-ops"] [data-act="tloResume"]').click();
  await expect(page.locator('.toast, #toast').last()).toContainText('本地服务暂不支持');
  expect(errors).toEqual([]);
});
