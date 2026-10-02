// Live bindings for A9 生成工坊, 问本地 Agent, settings (分析 / 隐私 / 数据源 / 通知 / 关于) and notify frames
// (src/js/97-live-studio-settings.js). Fixture mode: page.route plays the gateway on http://tandem.test with the synthetic
// files in prototypes/shared/fixtures (+ studio-settings/). Sibling of live-adapter.spec.mjs, kept separate so the three
// binding branches do not edit the same spec.
//  1. studio      engines, context preview (budget from the gateway), job stages → artifact lines + checks, history
//  2. studio      stop cancels the job; 403 consent_required stops the run with the reason
//  3. degrade     /v1/ai/* and /v1/platform/* missing (404): studio runs the demo flow with 示例数据, cards keep demo values
//  4. settings    storage, collection pause, notify matrix / preset / snooze / test, AI 通道 consent, health + diagnostics
//  5. notify      notification frame → banner + menu-bar badge, attention → HUD list, collection frame → paused, no banner
//  6. ask         presets from the gateway, preset answer, free question through an ask.question job
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ADV_FILE = path.join(ROOT, 'advance', 'tandem-demo.html');
const FX = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'fixtures', name + '.json'), 'utf8'));
const SS = (name) => FX('studio-settings/' + name);
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const sseText = (frames) => frames.map((f) => 'id: ' + f.id + '\nevent: ' + f.event + '\ndata: ' + JSON.stringify(f.data) + '\n\n').join('');

function collectErrors(page, allow) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (/fonts\.(googleapis|gstatic)\.com/.test(m.location().url || '')) return;
    if (allow && allow(m.text())) return;
    errors.push(m.text());
  });
  return errors;
}

// state: ai / platform = false answers 404 for that prefix; job: 'progress' (running → done) | 'stuck' (always running) |
// 'consent' (POST /v1/ai/jobs → 403); queue = SSE frame lists for the next /v1/events connections.
async function gateway(page, opts = {}) {
  const state = Object.assign({ ai: true, platform: true, job: 'progress', queue: [], seen: [], jobPolls: 0 }, opts);
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/^http:\/\/tandem\.test\//, async (route) => {
    const req = route.request(); const u = new URL(req.url()); const m = req.method(); const p = u.pathname;
    let body = null; try { body = req.postData() ? JSON.parse(req.postData()) : null; } catch (e) { body = null; }
    state.seen.push({ m, path: p, search: u.search, body });
    const json = (b, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) });
    const nf = () => json({ error: { code: 'not_found', message: p, retryable: false } }, 404);
    if (p === '/app') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(ADV_FILE, 'utf8') });
    if (p === '/v1/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: sseText(state.queue.shift() || []) });
    if (!state.ai && p.startsWith('/v1/ai/')) return nf();
    if (!state.platform && (p.startsWith('/v1/platform/') || p.startsWith('/v1/notifications'))) return nf();
    const core = { '/v1/status': 'status', '/v1/analytics/overview': 'overview', '/v1/app/sources': 'app-sources', '/v1/app/settings': 'app-settings' };
    if (m === 'GET' && core[p]) return json(FX(core[p]));
    const K = m + ' ' + p;
    if (K === 'POST /v1/ai/jobs') return state.job === 'consent' ? json({ error: { code: 'consent_required', message: '需要授权', detail: { missing: ['snippets'] } } }, 403) : json(SS('ai-job-created'), 202);
    if (K === 'GET /v1/ai/jobs/fx-job-1') { state.jobPolls++; return json(state.job === 'stuck' || state.jobPolls < 2 ? SS('ai-job-running') : SS('ai-job-done')); }
    if (K === 'GET /v1/ai/jobs/fx-ask-1') return json(SS('ask-job-done'));
    if (K === 'POST /v1/ai/ask') return json(body && body.question ? { job_id: 'fx-ask-1', status: 'queued', cached: false } : SS('ask-answer'));
    if (K === 'PUT /v1/notifications/policy') return json(u.searchParams.get('preset') === 'all' ? SS('notify-policy-all') : SS('notify-policy'));
    if (K === 'PUT /v1/ai/consent') { const c = SS('ai-consent'); if (body && body.grants) Object.keys(body.grants).forEach((e) => Object.assign(c.grants[e], body.grants[e])); return json(Object.assign(c, { cancelled_jobs: [] })); }
    const routes = {
      'GET /v1/ai/engines': 'ai-engines', 'GET /v1/ai/consent': 'ai-consent', 'POST /v1/ai/preview': 'ai-preview', 'POST /v1/ai/jobs/fx-job-1/cancel': 'ai-job-cancelled',
      'GET /v1/ai/artifacts/fx-art-1': 'ai-artifact', 'GET /v1/ai/artifacts': 'ai-artifacts', 'GET /v1/ai/ask/presets': 'ask-presets',
      'GET /v1/notifications/policy': 'notify-policy', 'GET /v1/notifications/snooze': 'notify-snooze', 'POST /v1/notifications/snooze': 'notify-snooze-set', 'DELETE /v1/notifications/snooze': 'notify-snooze-set',
      'POST /v1/notifications/test': 'notify-test', 'GET /v1/notifications/attention': 'notify-attention', 'POST /v1/notifications/fx-n2/ack': 'notify-ack',
      'GET /v1/platform/collection': 'collection', 'POST /v1/platform/collection/pause': 'collection-pause', 'POST /v1/platform/collection/resume': 'collection-resume',
      'GET /v1/platform/storage': 'storage', 'GET /v1/platform/telemetry': 'telemetry', 'PUT /v1/platform/telemetry': 'telemetry-off', 'GET /v1/platform/health': 'health', 'POST /v1/platform/diagnostics/export': 'diagnostics-export'
    };
    if (routes[K]) return json(SS(routes[K]));
    return nf();
  });
  return state;
}
const allow404 = (t) => /status of 404/.test(t);
const sent = (gw, m, p) => gw.seen.filter((s) => s.m === m && s.path === p);

test('studio live: engines, context preview, job stages, artifact lines and checks, history', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#content')).toContainText('已检测：Claude Code · Codex · Gemini CLI（不可用）');
  await expect(page.locator('#content .st-ctx')).toContainText(['相关会话摘要 · 12 个', '摩擦统计', '需要授权 · 关键时刻前后']);
  await expect(page.locator('#stTok')).toContainText('上限 16.0k');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('$ POST /v1/ai/jobs · generate.skill · claude_code');
  await expect(page.locator('#content .bdg').filter({ hasText: '待审阅' })).toBeVisible();
  await expect(page.locator('#content .code')).toContainText('FX 合成行：第二轮后停止');
  await expect(page.locator('#content [data-chk="replay"]')).toContainText('合成会话 A');
  await expect(page.locator('#content [data-chk="judge"]')).toContainText('judge 未启用');
  await expect(page.locator('#studioLog')).toContainText('产物 fx-art-1');
  const job = sent(gw, 'POST', '/v1/ai/jobs')[0].body;
  expect([job.task_id, job.engine, job.preview_digest]).toEqual(['generate.skill', 'claude_code', 'sha256:fx-preview']);
  expect(job.selection.items).toMatchObject({ sessions: true, friction: true, snippets: false });
  await expect(page.locator('#notes')).toContainText('生成完成：SKILL.md');
  await page.locator('[data-act="studioHistory"]').click();
  await expect(page.locator('#modal [data-tl="artifacts"]')).toContainText('Skill · fx-wrapup');
  await expect(page.locator('#modal [data-tl="artifacts"]')).toContainText('已归档');
  expect(errors).toEqual([]);
});

test('studio live: stop cancels the job; consent_required stops the run with the reason', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, (t) => /status of (404|403)/.test(t));
  const gw = await gateway(page, { job: 'stuck' });
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#stTok')).toContainText('上限 16.0k');
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('任务 fx-job-1');
  await page.locator('[data-act="studioStop"]').click();
  await expect(page.locator('#studioLog')).toContainText('任务 fx-job-1 · cancelled');
  expect(sent(gw, 'POST', '/v1/ai/jobs/fx-job-1/cancel')).toHaveLength(1);
  gw.job = 'consent';
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('! 需要授权：snippets');
  await expect(page.locator('#toast')).toContainText('去设置');
  expect(errors).toEqual([]);
});

test('degrade: without AI and platform routes the studio runs the demo flow with 示例数据 and settings keep demo values', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  await gateway(page, { ai: false, platform: false });
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await expect(page.locator('#content')).toContainText('已检测：Claude Code · Codex · Gemini CLI · DeepSeek · Copilot');
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('--output-format stream-json');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await page.evaluate(() => openSettings('privacy'));
  await expect(page.locator('#set')).toContainText('812 MB');
  await expect(page.locator('#set [data-tl="sample"]')).toHaveCount(1);
  await page.evaluate(() => { S.setTab = 'about'; renderSet(); });
  await expect(page.locator('#set [data-tl="health"]')).toHaveCount(0);
  await expect(page.locator('#set')).toContainText('1.0（演示版）');
  await page.evaluate(() => { S.setTab = 'notify'; renderSet(); });
  await expect(page.locator('#set [data-tl="sample"]')).toHaveCount(2);
  expect(errors).toEqual([]);
});

test('settings live: storage, collection pause, notify policy / preset / snooze / test, AI consent, health and diagnostics', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => openSettings('privacy'));
  await expect(page.locator('#set [data-tl="storage"]')).toContainText('快照缓存');
  await expect(page.locator('#set')).toContainText('150 MB');
  await expect(page.locator('#set')).toContainText('~/.tandem-fixture');
  // 数据源 › 暂停采集
  await page.evaluate(() => { S.setTab = 'sources'; renderSet(); });
  const pause = page.locator('#set [data-act="setPause"]');
  await expect(pause).toHaveAttribute('aria-checked', 'false');
  await pause.click();
  await expect(pause).toHaveAttribute('aria-checked', 'true');
  await expect.poll(() => sent(gw, 'POST', '/v1/platform/collection/pause').length).toBe(1);
  await pause.click();
  await expect.poll(() => sent(gw, 'POST', '/v1/platform/collection/resume').length).toBe(1);
  await expect(page.locator('#toast')).toContainText('正在补采');
  // 通知: matrix from the policy (done → hud only), one cell → PUT, preset → ?preset=all, mute → snooze, test → POST
  await page.evaluate(() => { S.setTab = 'notify'; renderSet(); });
  const cell = (e, c) => page.locator('#set [data-chg="setNotif"][data-e="' + e + '"][data-c="' + c + '"]');
  await expect(cell('done', 0)).not.toBeChecked();
  await expect(cell('done', 1)).toBeChecked();
  await expect(cell('stuck', 2)).toBeChecked();
  await cell('done', 0).click();
  await expect.poll(() => sent(gw, 'PUT', '/v1/notifications/policy').length).toBe(1);
  expect(sent(gw, 'PUT', '/v1/notifications/policy')[0].body).toEqual({ matrix: { done: ['banner', 'hud'] } });
  await page.locator('#set [data-act="setNotifPreset"][data-v="all"]').click();
  await expect.poll(() => sent(gw, 'PUT', '/v1/notifications/policy').map((s) => s.search)).toEqual(['', '?preset=all']);
  await expect(cell('weekly', 2)).toBeChecked();
  await page.locator('#set [data-act="setMute"]').click();
  await expect.poll(() => sent(gw, 'POST', '/v1/notifications/snooze').map((s) => s.body)).toEqual([{ seconds: 86400, scope: 'global' }]);
  await expect(page.locator('#set [data-act="setMute"]')).toHaveAttribute('aria-checked', 'true');
  await page.locator('#set [data-act="setTestNotif"]').click();
  await expect.poll(() => sent(gw, 'POST', '/v1/notifications/test').length).toBe(1);
  // 分析 › AI 通道 from the consent grants of the default engine
  await page.evaluate(() => { S.setTab = 'analysis'; renderSet(); });
  const ch = (k) => page.locator('#set [data-act="setAiCh"][data-k="' + k + '"]');
  await expect(ch('sum')).toHaveAttribute('aria-checked', 'true');
  await expect(ch('snip')).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('#set [data-tl="ai-cap"]')).toContainText('$2.00');
  await ch('snip').click();
  await expect(ch('snip')).toHaveAttribute('aria-checked', 'true');
  expect(sent(gw, 'PUT', '/v1/ai/consent').map((s) => s.body)).toEqual([{ grants: { claude_code: { snippets: true } } }]);
  // 关于: health + diagnostics
  await page.evaluate(() => { S.setTab = 'about'; renderSet(); });
  await expect(page.locator('#set [data-tl="health"]')).toContainText('部分降级');
  await expect(page.locator('#set [data-tl="health"]')).toContainText('FX 合成警告');
  await expect(page.locator('#set')).toContainText('0.9.0-fx');
  await page.locator('#set [data-act="tlsDiag"]').click();
  await expect(page.locator('#toast')).toContainText('diagnostics-fx.zip');
  await page.locator('#set [data-act="tlsTel"]').click();
  await expect(page.locator('#set [data-act="tlsTel"]')).toHaveAttribute('aria-checked', 'false');
  expect(errors).toEqual([]);
});

test('notify frames: banner + menu-bar badge, attention list, collection paused without a service banner', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  gw.queue.push(SS('notify-frames').frames);
  await page.goto('http://tandem.test/app#token=fx-token');
  await expect(page.locator('#notes')).toContainText('FX 等你确认');
  // 「稍后」acks the notification with a one-hour snooze (dispatched directly: the banner auto-hides after 7 s)
  await page.locator('#notes .nt').filter({ hasText: 'FX 等你确认' }).locator('[data-act="noteAct"][data-k="2"]').dispatchEvent('click');
  await expect.poll(() => sent(gw, 'POST', '/v1/notifications/fx-n2/ack').map((s) => s.body)).toEqual([{ snooze_s: 3600 }]);
  // GET /v1/notifications/attention (refetched on the attention frame): a failing command outranks the confirmation
  await expect.poll(() => page.evaluate(() => [S.sim, S.hudSim, S.waitOpen, S.attn.has('stuck')])).toEqual(['stuck', 'stuck', true, true]);
  await expect.poll(() => page.evaluate(() => S.paused)).toBe(true);                      // service frame {collection: paused}
  await expect(page.locator('[data-tl="degraded"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('ask live: presets from the gateway, a preset answer and a free question via an ask.question job', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.evaluate(() => openAsk('overview'));
  const chips = page.locator('#modal [data-tl="ask-presets"] [data-act="askPick"]');
  await expect(chips).toHaveText(['FX 预置问题一？', 'FX 预置问题二？', 'FX 预置问题三？']);
  await expect(page.locator('#modal .mh')).not.toContainText('Demo 中为预置回答');
  await chips.nth(1).click();
  await expect(page.locator('#askA')).toContainText('FX 合成回答');
  expect(sent(gw, 'POST', '/v1/ai/ask')[0].body).toEqual({ context: 'overview', preset_index: 1 });
  await page.locator('#askIn').fill('FX 自由问题');
  await page.locator('#modal [data-act="askSend"]').click();
  await expect(page.locator('#askA')).toContainText('FX 自由提问回答');
  expect(sent(gw, 'POST', '/v1/ai/ask')[1].body).toEqual({ context: 'overview', question: 'FX 自由问题' });
  expect(errors).toEqual([]);
});
