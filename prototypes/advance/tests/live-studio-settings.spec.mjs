// Live bindings for A9 生成工坊, 问本地 Agent, settings (分析 / 隐私 / 数据源 / 通知 / 关于) and notify frames
// (src/js/97-live-studio-settings.js). Fixture mode: page.route plays the gateway on http://orbit.test with the synthetic
// files in prototypes/shared/fixtures (+ studio-settings/). Sibling of live-adapter.spec.mjs, kept separate so the three
// binding branches do not edit the same spec.
//  1. studio      engines, context preview (budget from the gateway), job stages → artifact lines + checks, history
//  2. studio      stop cancels the job; 403 consent_required stops the run with the reason
//  3. degrade     /v1/ai/* and /v1/platform/* missing (404): studio runs the demo flow with 示例数据, cards keep demo values
//  4. settings    storage, collection pause, notify matrix / preset / snooze / test, AI 通道 consent, health + diagnostics
//  5. notify      notification frame → banner + menu-bar badge, attention → HUD list, collection frame → paused, no banner
//  6. ask         presets from the gateway, preset answer, free question through an ask.question job
//  7. regressions  no demo goal in live, readable pack preview, one row per agent with ~ paths, sheets closed on tab change
//  8. R4-05/R4-16  the typed goal re-packs the context (manual goal, exact small token counts); 授权对象 shows the engine name
//  9. overview    「AI 生成」 posts narrate.overview (card scope, fresh) and shows model text only once the backend reads it back
//                 (AI errors carry missing / reason next to code, as routes_ai.AIApiError sends them)
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ADV_FILE = path.join(ROOT, 'advance', 'orbit-demo.html');
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
  await page.route(/^http:\/\/orbit\.test\//, async (route) => {
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
    if (state.extra && state.extra[K] !== undefined) return json(typeof state.extra[K] === 'function' ? state.extra[K](body) : state.extra[K]);
    if (K === 'POST /v1/ai/jobs') return state.job === 'consent' ? json({ error: { code: 'consent_required', message: '需要授权', retryable: false, missing: ['snippets'], engine: 'claude_code' } }, 403) : json(SS('ai-job-created'), 202);
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
      'GET /v1/platform/storage': 'storage', 'GET /v1/app/data': 'storage', 'GET /v1/platform/diagnostics': 'health', 'GET /v1/platform/telemetry': 'telemetry', 'PUT /v1/platform/telemetry': 'telemetry-off', 'GET /v1/platform/health': 'health', 'POST /v1/platform/diagnostics/export': 'diagnostics-export'
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
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#content')).toContainText('已检测：Claude Code · Codex · Gemini CLI（不可用）');
  await expect(page.locator('#content .st-ctx')).toContainText(['相关会话摘要 · 12 个', '摩擦统计', '需要授权 · 关键时刻前后']);
  await expect(page.locator('#stTok')).toContainText('上限 16.0k');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await page.locator('#studioGoal').fill('合并前收尾：最多两轮 review');   // live has no prefilled goal
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
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#stTok')).toContainText('上限 16.0k');
  await page.locator('#studioGoal').fill('合并前收尾：最多两轮 review');   // live has no prefilled goal
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('任务 fx-job-1');
  await page.locator('[data-act="studioStop"]').click();
  await expect(page.locator('#studioLog')).toContainText('任务 fx-job-1 · cancelled');
  expect(sent(gw, 'POST', '/v1/ai/jobs/fx-job-1/cancel')).toHaveLength(1);
  gw.job = 'consent';
  await page.locator('#studioGoal').fill('合并前收尾：最多两轮 review');   // live has no prefilled goal
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#studioLog')).toContainText('! 需要授权：snippets');
  await expect(page.locator('#modal [data-tl="consent"]')).toContainText('脱敏片段');   // the real consent dialog
  expect(errors).toEqual([]);
});

test('degrade: without AI and platform routes the studio says so (no demo flow) and settings never show demo personal data', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  await gateway(page, { ai: false, platform: false });
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#content')).toContainText('已检测：本地服务暂不提供生成接口');
  await page.locator('#studioGoal').fill('合并前收尾：最多两轮 review');   // live has no prefilled goal
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#toast')).toContainText('本地服务暂不提供生成接口');
  await expect(page.locator('#studioLog')).not.toContainText('--output-format stream-json');
  await page.evaluate(() => openSettings('privacy'));
  await expect(page.locator('#set')).not.toContainText('812 MB');
  await page.evaluate(() => { S.setTab = 'about'; renderSet(); });
  await expect(page.locator('#set [data-tl="health"]')).toHaveCount(0);
  await page.evaluate(() => { S.setTab = 'notify'; renderSet(); });
  await expect(page.locator('#set [data-tl="sample"]')).toHaveCount(2);
  expect(errors).toEqual([]);
});

test('settings live: storage, collection pause, notify policy / preset / snooze / test, AI consent, health and diagnostics', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => openSettings('privacy'));
  await expect(page.locator('#set [data-tl="storage"]')).toContainText('快照缓存');
  await expect(page.locator('#set')).toContainText('150 MB');
  await expect(page.locator('#set')).toContainText('~/.orbit-fixture');
  // 数据源 › 暂停采集
  await page.evaluate(() => { S.setTab = 'sources'; renderSet(); });
  const pause = page.locator('#set [data-act="setPause"]');
  await expect(pause).toHaveAttribute('aria-checked', 'false');
  await pause.click();
  await expect(pause).toHaveAttribute('aria-checked', 'true');
  await expect.poll(() => sent(gw, 'POST', '/v1/platform/collection/pause').length).toBe(1);
  await expect(page.locator('#side .sb-foot .pv')).toHaveAttribute('data-st', 'off');   // sidebar indicator: gray, 采集已暂停
  await expect(page.locator('#side .sb-foot .pv')).toContainText('采集已暂停');
  await pause.click();
  await expect.poll(() => sent(gw, 'POST', '/v1/platform/collection/resume').length).toBe(1);
  await expect(page.locator('#side .sb-foot .pv')).not.toContainText('采集已暂停');
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
  await expect(page.locator('#toast')).toContainText('诊断包已下载');   // browser fallback of the host's save panel
  await page.locator('#set [data-act="tlsTel"]').click();
  await expect(page.locator('#set [data-act="tlsTel"]')).toHaveAttribute('aria-checked', 'false');
  expect(errors).toEqual([]);
});

test('notify frames: banner + menu-bar badge, attention list, collection paused without a service banner', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  gw.queue.push(SS('notify-frames').frames);
  await page.goto('http://orbit.test/app#token=fx-token');
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
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => openAsk('overview'));
  const chips = page.locator('#modal [data-tl="ask-presets"] [data-act="askPick"]');
  await expect(chips).toHaveText(['FX 预置问题一？', 'FX 预置问题二？', 'FX 预置问题三？']);
  await expect(page.locator('#modal .mh')).not.toContainText('Demo 中为预置回答');
  await chips.nth(1).click();
  await expect(page.locator('#askA')).toContainText('FX 合成回答');
  await expect(page.locator('#askA')).toContainText('规则模板 · 在本机查询你的数据生成，没有调用模型');   // source: template
  expect(sent(gw, 'POST', '/v1/ai/ask')[0].body).toEqual({ context: 'overview', preset_index: 1 });
  await page.locator('#askIn').fill('FX 自由问题');
  await page.locator('#modal [data-act="askSend"]').click();
  await expect(page.locator('#askA')).toContainText('FX 自由提问回答');
  await expect(page.locator('#askA')).toContainText('本地 Agent 回答');                                       // source: ai
  await expect(page.locator('#modal .mf')).not.toContainText('本机进程间');
  expect(sent(gw, 'POST', '/v1/ai/ask')[1].body).toEqual({ context: 'overview', question: 'FX 自由问题' });
  expect(errors).toEqual([]);
});

test('regressions: no demo goal, readable pack preview, deduped sources with ~ paths, settings sheets never stack (B15–B17, J17)', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const rules = { rules: [{ id: 'secrets', label: '密钥、令牌与带认证的地址', placeholder: '[密钥已隐藏]', enabled: true, locked: true }, { id: 'email', label: '邮箱地址', placeholder: '[email]', enabled: true, locked: false }] };
  await gateway(page, { extra: { 'POST /v1/ai/preview': SS('ai-preview-pack'), 'GET /v1/app/discovery': SS('discovery-dup'), 'GET /v1/privacy/rules': rules, 'GET /v1/app/tool_map': FX('s6/v1-app-tool_map') } });
  await page.goto('http://orbit.test/app#token=fx-token');
  // B15: the demo's prefilled goal and its「来自 A7 建议」caption never show in live
  await page.evaluate(() => go('studio'));
  await expect(page.locator('#studioGoal')).toHaveValue('');
  await expect(page.locator('#content')).not.toContainText('来自 A7');
  await expect(page.locator('#content .st-ctx')).toContainText(['工具证据']);
  await page.locator('#content [data-act="ctxPreview"]').first().click();
  const modal = page.locator('#modal');
  await expect(modal).toContainText('命令 · ["pnpm test", "git push"]');
  for (const raw of ['source:', 'text:', 'file_exts', 'verify_commands: []']) await expect(modal).not.toContainText(raw);
  await expect(modal).toContainText('暂无可发送的内容');
  await expect(modal).toContainText('将发送给 Claude Code 的上下文包');
  await expect(modal).toContainText('由 Claude Code 读取');
  await page.evaluate(() => closeModal());
  // B17: one row per agent (the empty default root of an agent that has a real one is dropped), home shown as ~
  await page.evaluate(() => openSettings('sources'));
  const set = page.locator('#set');
  await expect(set.locator('.srcrow').filter({ hasText: 'Claude Code' })).toHaveCount(1);
  await expect(set).toContainText('~/.claude/projects · ');
  await expect(set).not.toContainText('/Users/fx');
  await expect(set).not.toContainText('orbit-journey');
  await expect(set.locator('.srcrow').filter({ hasText: 'Pi' })).toContainText('没有会话文件');   // an empty agent with no other root keeps its row
  // B16 / J17: a sheet opened from one tab never covers the next one; real pointer clicks reach the controls
  await set.locator('[data-act="setMap"]').click();
  await expect(modal).toBeVisible();
  await page.evaluate(() => openSettings('privacy'));
  await expect(modal).toBeHidden();
  await expect(set.locator('[data-act="setRule"][data-k="secrets"]')).toHaveAttribute('aria-label', '密钥、令牌与带认证的地址 始终开启');
  await set.locator('[data-act="setRule"][data-k="email"]').click({ timeout: 3000 });
  await page.evaluate(() => openSettings('analysis'));
  await set.locator('[data-act="method"]').click({ timeout: 3000 });
  await expect(modal).toContainText('协作人格如何计算');
  await page.evaluate(() => ACT.setTab({ dataset: { v: 'notify' } }));
  await expect(modal).toBeHidden();
  await expect(page.locator('#tip')).toBeHidden();
  await set.locator('[data-act="setNotifPreset"]').first().click({ timeout: 3000 });
  await page.evaluate(() => openSettings('about'));
  await set.locator('[data-act="setUpdate"]').click({ timeout: 3000 });
  expect(errors).toEqual([]);
});

test('R4-05 / R4-16: the typed goal is packed and sized honestly; 授权对象 uses the display name', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  // the synthetic gateway's answer for a manual goal: the goal text, FTS evidence for it, small exact token counts
  const pack = (b) => {
    const goal = (b && b.goal) || '';
    const items = [{ key: 'goal', label: '目标', desc: '本次要解决的问题', data_class: 'summary', enabled: true, tokens: goal ? 16 : 1, redaction_hits: 0, preview: goal ? ['text: ' + JSON.stringify(goal), 'source: "' + b.goal_source + '"'] : [], consent: 'granted' },
      { key: 'evidence', label: '证据片段', desc: '≤5 条已脱敏的原话或错误片段', data_class: 'snippets', enabled: true, tokens: goal && b.goal_source === 'manual' ? 306 : 1, redaction_hits: 0, preview: goal && b.goal_source === 'manual' ? ['[you] fx: the flaky test failed again'] : [], consent: 'granted' }];
    return { task_id: 'generate.skill', engine: 'claude_code', items, total_tokens: items.reduce((a, x) => a + x.tokens, 0), input_budget: 12000, over_budget: false, redaction_hits: 0, preview_digest: 'sha256:fx-' + goal.length, payload: {}, stages: ['pack'] };
  };
  const gw = await gateway(page, { extra: { 'POST /v1/ai/preview': pack } });
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => openSettings('analysis'));
  await expect(page.locator('#set [data-tl="ai-cap"]')).toContainText('授权对象：Claude Code');
  await expect(page.locator('#set [data-tl="ai-cap"]')).not.toContainText('claude_code');
  await page.evaluate(() => { closeSettings(); go('studio'); });
  await expect(page.locator('#content .st-ctx')).toContainText(['证据片段']);
  await page.locator('#studioGoal').fill('fix the flaky test');
  await expect.poll(() => sent(gw, 'POST', '/v1/ai/preview').some((s) => s.body.goal === 'fix the flaky test' && s.body.goal_source === 'manual')).toBe(true);
  await expect(page.locator('#content [data-tok]')).toHaveText('≈ 322 tokens');
  await expect(page.locator('#content .st-ctx').filter({ hasText: '证据片段' })).toContainText('306 tok');
  await expect(page.locator('#content')).not.toContainText('0.0k');
  await expect(page.locator('#studioGoal')).toBeFocused();   // patched in place: typing is never interrupted
  await page.locator('#content [data-act="ctxPreview"]').first().click();
  const modal = page.locator('#modal');
  await expect(modal).toContainText('fix the flaky test');
  await expect(modal).toContainText('the flaky test failed again');
  await expect(modal).not.toContainText('0.0k');
  // an empty goal stays an 'ask' preview (a manual one would be 422 goal_required)
  expect(sent(gw, 'POST', '/v1/ai/preview')[0].body.goal_source).toBe('ask');
  expect(errors).toEqual([]);
});

test('overview live: 「AI 生成」 posts narrate.overview with the card scope and fresh, AI badge only on the model text', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, (t) => /status of (404|403)/.test(t));
  const OV = FX('s1/overview-30'); let written = false; let consent = false; const posts = [];
  const ovBody = () => {
    const o = JSON.parse(JSON.stringify(OV)); o.insight.ai_scope = { days: 30, project_id: null };
    if (written) Object.assign(o.insight, { lede: 'FX 模型写的结论', when: 'AI 撰写 · 基于当前数据', basis: 'ai_narrative', caveats: ['FX 样本少'],
      source: { task_id: 'narrate.overview', job_id: 'fx-ov-1', engine: 'claude_code', finished_at: Date.UTC(2026, 9, 3, 1, 5) } });
    return o;
  };
  const gw = await gateway(page, { extra: {
    'GET /v1/uiview/overview': () => ovBody(),
    'GET /v1/ai/jobs/fx-ov-1': () => { written = true; return { job_id: 'fx-ov-1', task_id: 'narrate.overview', status: 'ok', stages: [], log: [], result: { summary: 'FX 模型写的结论', source: 'ai' } }; }
  } });
  await page.route(/^http:\/\/orbit\.test\/v1\/ai\/jobs$/, (route) => (posts.push(route.request().postDataJSON()), route.fulfill(consent
    ? { status: 403, contentType: 'application/json', body: JSON.stringify({ error: { code: 'consent_required', message: '需要授权', retryable: false, missing: ['summary'], engine: 'claude_code' } }) }
    : { status: 202, contentType: 'application/json', body: JSON.stringify({ job_id: 'fx-ov-1', status: 'queued', cached: false }) })));
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => { S.range = 30; go('overview'); });
  const card = page.locator('#aiCard');
  await expect(card.locator('#aiLead')).toContainText('四个维度里有的还落在');
  await expect(card.locator('[data-lv="ins-basis"]')).toHaveText('规则解读');      // rule template: no purple AI badge
  await expect(card.locator('.aib')).toHaveCount(0);
  await expect(card.locator('[data-aigen]')).toHaveText('规则模板 · 本地生成');
  consent = true;
  await card.locator('[data-act="regen"]').click();
  await expect(page.locator('#toast')).toContainText('需要先授权这些数据类：summary');   // details sit next to code
  await expect(card.locator('.aib')).toHaveCount(0);
  consent = false;
  await card.locator('[data-act="regen"]').click();
  await expect(card.locator('#aiLead')).toContainText('FX 模型写的结论');
  await expect(card.locator('.aib')).toContainText('AI 解读');
  await expect(card.locator('[data-aigen]')).toContainText('AI 撰写 · 基于当前数据 · Claude Code');
  await expect(card.locator('[data-aigen]')).toHaveAttribute('data-tip', 'FX 样本少');
  expect(posts.length).toBe(2);
  expect(gw.seen.some((x) => x.path === '/v1/uiview/overview')).toBe(true);
  expect(posts[1]).toEqual({ task_id: 'narrate.overview', scope: { days: 30 }, fresh: true });
  expect(errors).toEqual([]);
});

test('overview live: the running state survives re-renders, 「停止」 cancels the job, ok without model text says so', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, (t) => /status of (404|403)/.test(t));
  const OV = FX('s1/overview-30'); let job = 'running'; let jobN = 0; const cancels = [];
  let scoped = true;
  const ovBody = () => { const o = JSON.parse(JSON.stringify(OV)); o.insight.ai_scope = scoped ? { days: 30 } : null; return o; };
  await gateway(page, { extra: {
    'GET /v1/uiview/overview': () => ovBody(),
    'POST /v1/ai/jobs': () => ({ job_id: 'fx-ov-' + (++jobN), status: 'queued', cached: false }),
    'GET /v1/ai/jobs/fx-ov-1': () => ({ job_id: 'fx-ov-1', task_id: 'narrate.overview', status: job, stages: [], log: [] }),
    'POST /v1/ai/jobs/fx-ov-1/cancel': () => { cancels.push(1); job = 'cancelled'; return { job_id: 'fx-ov-1', status: 'cancelled' }; },
    // the job ends ok, but the overview re-read still returns the rule template (data changed / incomplete output)
    'GET /v1/ai/jobs/fx-ov-2': () => ({ job_id: 'fx-ov-2', task_id: 'narrate.overview', status: 'ok', stages: [], log: [] })
  } });
  await page.goto('http://orbit.test/app#token=fx-token');
  await page.evaluate(() => { S.range = 30; go('overview'); });
  const card = page.locator('#aiCard');
  await expect(card.locator('[data-aigen]')).toHaveText('规则模板 · 本地生成');
  await card.locator('[data-act="regen"]').click();
  await expect(card.locator('[data-aigen]')).toContainText('本地 Agent 生成中');
  await page.evaluate(() => render());                                             // a refresh keeps the running state
  await expect(card.locator('[data-aigen] .spin')).toHaveCount(1);
  await expect(card.locator('[data-act="regen"]')).toHaveCount(0);
  await card.locator('[data-act="regenStop"]').click();
  await expect(page.locator('#toast')).toContainText('AI 解读已停止');
  expect(cancels.length).toBe(1);
  await expect(card.locator('[data-act="regen"]')).toHaveCount(1);
  await expect(card.locator('[data-aigen]')).toHaveText('规则模板 · 本地生成');
  await card.locator('[data-act="regen"]').click();
  await expect(page.locator('#toast')).toContainText('卡片保持规则模板');
  await expect(page.locator('#toast')).not.toContainText('已更新');
  await expect(card.locator('.aib')).toHaveCount(0);
  // no ai_scope (「全部」/ filtered): the button stays focusable with its reason (aria-disabled), a click explains instead of submitting
  scoped = false;
  await page.evaluate(() => TL.invalidate((x) => String(x.path).indexOf('/v1/uiview/overview') === 0));
  const off = card.locator('[data-act="regen"]');
  await expect(off).toHaveAttribute('aria-disabled', 'true');
  expect(await off.evaluate((el) => el.disabled)).toBe(false);
  await off.click({ force: true });   // Playwright treats aria-disabled as not enabled; a real click still reaches ACT.regen
  await expect(page.locator('#toast')).toContainText('暂不生成 AI 解读');
  expect(errors).toEqual([]);
});
