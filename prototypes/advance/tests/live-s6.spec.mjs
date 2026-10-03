// Slice 6 (src/js/97-live-studio-settings.js + 48-a9 / 53-ask / 57-settings): A9 生成工坊, 问本地 Agent, every settings tab and
// the notify banners on the core spine + the r4 bodies captured on the synthetic home (fixtures/s6). Personal data never
// shows demo rows; writes go to the gateway; native-only actions (chooseFolder / reveal / save / notify) post to the host.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx } from './live-helpers.mjs';

const NATIVE = { v: 1, app: '0.0.1', platform: 'macos', features: ['chooseFolder', 'save', 'openExternal', 'reveal', 'window'] };
const sent = (gw, m, p) => gw.seen.filter((s) => s.method === m && s.path === p);
const bodies = [];
async function track(page) { page.on('request', (r) => { if (/^http:\/\/orbit\.test\/v1\//.test(r.url()) && r.method() !== 'GET') bodies.push({ m: r.method(), path: new URL(r.url()).pathname, query: new URL(r.url()).search, body: r.postData() ? JSON.parse(r.postData()) : null }); }); }
const posted = (m, p) => bodies.filter((b) => b.m === m && b.path === p);
const tab = (page, t) => page.evaluate((x) => { S.setTab = x; renderSet(); }, t);
const MOCK_WORDS = /Confluo|latentskill|Gemini CLI|Copilot|812 MB|1\.0（演示版）/;

test.beforeEach(async ({ page }) => { bodies.length = 0; await page.clock.setFixedTime(new Date('2026-10-03T12:00:00+08:00')); await track(page); });

test('empty spine, no AI/platform routes: studio and every settings tab render honestly, no demo rows', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, [], { 'GET /v1/uiview/facts': Object.assign(fx('core/facts.json'), { rows: [], agents: [], projects: [] }) });
  await openLive(page, 'studio');
  await expect(page.locator('#content')).toContainText('已检测：本地服务暂不提供生成接口');
  await expect(page.locator('#content')).not.toContainText('46 个');
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#toast')).toContainText('本地服务暂不提供生成接口');
  await expect(page.locator('#studioLog')).not.toContainText('stream-json');
  for (const t of ['general', 'sources', 'privacy', 'analysis', 'notify', 'about']) {
    await page.evaluate((x) => openSettings(x), t);
    await page.waitForTimeout(150);
    await expect(page.locator('#set')).not.toContainText(MOCK_WORDS);
  }
  await page.evaluate(() => openSettings('privacy'));
  await expect(page.locator('#set [data-lv="na"]')).toContainText('本地服务暂不提供脱敏规则');
  await expect(page.locator('#set')).toContainText('—');
  await expect(page.locator('.tl-table, .tl-kpi')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('settings: 通用 / 数据源 / 隐私 / 分析 / 通知 read the gateway and write back', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's6'], {
    'PATCH /v1/app/settings': (req) => ({ body: Object.assign({ onboarded: true, recent_days: 90, default_range_days: 30, sync_mode: 'off', weekly_report: false, onboarding_step: 4 }, JSON.parse(req.postData())) }),
    'POST /v1/app/sources': (req) => ({ body: Object.assign({ id: 'source_fx_new' }, JSON.parse(req.postData())) }),
    'POST /v1/app/jobs': { status: 202, body: { id: 'job-fx', kind: 'import', status: 'queued' } },
    'PUT /v1/privacy/rules': (req) => ({ body: null, status: 200 }),
    'POST /v1/privacy/preview': (req) => ({ body: { text: JSON.parse(req.postData()).text.replace(/\S+@\S+/g, '[email]'), n: 1, hits: [{ rule: 'email' }] } }),
    'POST /v1/app/data/clear': { status: 202, body: { pending: true } },
    'PUT /v1/ai/consent': (req) => ({ body: Object.assign({ mode: 'stats', grants: {} }, JSON.parse(req.postData())) })
  }, { native: NATIVE });
  await openLive(page, 'overview');
  // 通用: default range → PATCH
  await page.evaluate(() => openSettings('general'));
  await page.locator('#set [data-act="setRange"][data-v="7"]').click();
  await expect.poll(() => posted('PATCH', '/v1/app/settings').map((b) => b.body)).toEqual([{ default_range_days: 7 }]);
  // 数据源: real sources from discovery, enable toggle, sync mode, add a folder through the host
  await tab(page, 'sources');
  await expect(page.locator('#set .srcrow')).toHaveCount(7);
  await expect(page.locator('#set')).toContainText('Kimi CLI');
  await expect(page.locator('#set')).toContainText('/fx/fx-src/opencode');
  await expect(page.locator('#set')).not.toContainText(MOCK_WORDS);
  await expect(page.locator('#set [data-act="setIdx"][data-v="manual"]')).toHaveAttribute('aria-checked', 'true');   // sync_mode off
  const foot = page.locator('#side .sb-foot .pv');   // the sidebar indicator follows the server's sync_mode, not a fixed 实时
  await expect(foot).toHaveAttribute('data-st', 'off');
  await expect(foot).toContainText('手动');
  await page.locator('#set [data-act="setSrc"][data-ag="hermes"]').click();
  await expect.poll(() => posted('POST', '/v1/app/sources').map((b) => b.body)).toEqual([{ agent: 'hermes', root: '/fx/fx-src/hermes', enabled: false }]);
  await page.locator('#set [data-act="setIdx"][data-v="hour"]').click();
  await expect.poll(() => posted('PATCH', '/v1/app/settings').map((b) => b.body).slice(-1)).toEqual([{ sync_mode: 'hour' }]);
  await expect(foot).toContainText('每小时');
  await page.locator('#set [data-act="setAddSrc"]').last().click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'chooseFolder').length)).toBe(1);
  await page.evaluate(() => { const m = window.__nativeMsgs.find((x) => x.type === 'chooseFolder'); window.dispatchEvent(new CustomEvent('orbit:folder', { detail: { id: m.id, path: '/fx/extra/.codex/sessions', cancelled: false } })); });
  await expect.poll(() => posted('POST', '/v1/app/sources').map((b) => b.body).slice(-1)).toEqual([{ agent: 'codex', root: '/fx/extra/.codex/sessions', enabled: true }]);
  await expect.poll(() => posted('POST', '/v1/app/jobs').map((b) => b.body)).toEqual([{ kind: 'import', source_ids: ['source_fx_new'] }]);
  await page.locator('#set [data-act="setMap"]').click();
  await expect(page.locator('#modal [data-tl="tool-map"]')).toContainText('exec_command');
  await page.evaluate(() => closeModal());
  // 隐私: rules, toggle, preview, storage, reveal, clear
  await tab(page, 'privacy');
  await expect(page.locator('#set')).toContainText('邮箱地址');
  await expect(page.locator('#set [data-act="setRule"][data-k="credentials"]')).toBeDisabled();
  await page.locator('#set [data-act="setRule"][data-k="email"]').click();
  await expect.poll(() => posted('PUT', '/v1/privacy/rules').map((b) => b.body)).toEqual([{ enabled: { email: false } }]);
  await page.locator('#set [data-act="setTest"]').click();
  await page.locator('#rdIn').fill('mail me at a@b.co');
  await expect(page.locator('#rdOut mark.rd')).toHaveText('[email]');
  await expect(page.locator('#set [data-tl="storage"]')).toContainText('规范数据库');
  await expect(page.locator('#set')).toContainText('/fx/fx-homes/full');
  await page.locator('#set [data-act="setFinder"]').click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'reveal').map((m) => m.path))).toEqual(['/fx/fx-homes/full']);
  await page.locator('#set [data-act="setClear"]').click();
  await expect(page.locator('#modal [data-tl="clear"]')).toContainText('规范数据库');
  await page.locator('#clrIn').fill('清除');
  await page.locator('#clrIn').dispatchEvent('input');
  await page.locator('#clrBtn').click();
  await expect.poll(() => posted('POST', '/v1/app/data/clear').map((b) => b.body)).toEqual([{ confirm: '清除' }]);
  // 分析: 仅统计 sends 'stats' (never 'off'); Ollama is not wired, nothing is sent
  await tab(page, 'analysis');
  await expect(page.locator('#set [data-tl="ai-cap"]')).toContainText('今日 $0.00');
  await page.locator('#set [data-act="setEngine"][data-v="agent"]').click();
  await page.locator('#set [data-act="setEngine"][data-v="stats"]').click();
  await page.locator('#set [data-act="setEngine"][data-v="ollama"]').click();
  await expect.poll(() => posted('PUT', '/v1/ai/consent').map((b) => b.body)).toEqual([{ mode: 'agent' }, { mode: 'stats' }]);
  await page.locator('#set [data-act="setWeekly"]').click();
  await expect.poll(() => posted('PATCH', '/v1/app/settings').map((b) => b.body).slice(-1)).toEqual([{ weekly_report: true }]);
  // 通知: just_finished → the 会话完成 row
  await tab(page, 'notify');
  const cell = (e, c) => page.locator('#set [data-chg="setNotif"][data-e="' + e + '"][data-c="' + c + '"]');
  await expect(cell('done', 0)).not.toBeChecked();
  await expect(cell('done', 1)).toBeChecked();
  await expect(cell('ctx', 1)).toBeChecked();
  await expect(cell('ctx', 0)).not.toBeChecked();
  await expect(page.locator('#set [data-tl="sample"]')).toHaveCount(0);
  await expect(page.locator('.tl-table, .tl-kpi')).toHaveCount(0);
  expect(gw.count('/v1/app/state')).toBeGreaterThan(0);
  expect(errors).toEqual([]);
});

test('about: version from the host and the gateway, health, diagnostics saved through the host', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's6'], {}, { native: NATIVE });
  await openLive(page, 'overview');
  await page.evaluate(() => openSettings('about'));
  await expect(page.locator('#set .body .mono.cap').first()).toContainText('0.0.1 · 服务 0.13.6');
  await expect(page.locator('#set [data-tl="health"]')).toContainText('sync_loop');
  await expect(page.locator('#set [data-tl="about"]')).toContainText('opencode');
  await page.locator('#set [data-act="tlsDiag"]').click();
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'save').length)).toBe(1);
  const msg = await page.evaluate(() => window.__nativeMsgs.find((m) => m.type === 'save'));
  expect(msg.filename).toMatch(/^orbit-diagnostics-\d{8}-\d{4}\.json$/);
  expect(msg.mime).toBe('application/json');
  expect(JSON.parse(msg.text)).toBeTruthy();
  await page.evaluate((id) => window.dispatchEvent(new CustomEvent('orbit:saved', { detail: { id, ok: true, path: '/fx/Downloads/x.json' } })), msg.id);
  await expect(page.locator('#toast')).toContainText('/fx/Downloads/x.json');
  await expect(page.locator('#set')).not.toContainText('1.0（演示版）');
  expect(errors).toEqual([]);
});

test('studio: real engines, honest context, consent 403 opens the consent dialog and retries after granting', async ({ page }) => {
  const errors = collectErrors(page);
  let jobs = 0;
  await stubGateway(page, ['core', 's6'], {
    'POST /v1/ai/preview': { body: { preview_digest: 'sha256:fx', input_budget: 16000, items: [{ key: 'sum', label: '相关会话摘要 · 26 个', desc: '结构化统计', tokens: 3000, enabled: true, preview: ['session · Pi · 合成'] }] } },
    'POST /v1/ai/jobs': () => (++jobs === 1 ? { status: 403, body: { error: { code: 'consent_required', message: '需要授权', detail: { missing: ['summary'], engine: 'claude_code' } } } } : { status: 403, body: { error: { code: 'ai_disabled', message: 'off' } } }),
    'PUT /v1/ai/consent': (req) => ({ body: { mode: 'agent', grants: JSON.parse(req.postData()).grants } })
  });
  await openLive(page, 'studio');
  await expect(page.locator('#content')).toContainText('已检测：Claude Code（未登录） · Codex（不可用）');
  await expect(page.locator('#content .st-ctx').first()).toContainText('相关会话摘要 · 26 个');
  await expect(page.locator('#content')).not.toContainText(MOCK_WORDS);
  await page.locator('#studioGoal').fill('合成目标');
  await page.locator('#studioGoal').dispatchEvent('input');
  await page.locator('[data-act="studioStart"]').click();
  await expect(page.locator('#modal [data-tl="consent"]')).toContainText('结构化统计');
  await page.locator('#modal [data-act="tlsConsentOk"]').click();
  await expect.poll(() => posted('PUT', '/v1/ai/consent').map((b) => b.body)).toEqual([{ grants: { claude_code: { summary: true } } }]);
  await expect.poll(() => jobs).toBe(2);
  await expect(page.locator('#studioLog')).toContainText('AI 已在设置中关闭');
  expect(errors).toEqual([]);
});

test('ask: presets and answers from the gateway; ask route missing answers honestly', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's6'], {
    'GET /v1/ai/consent': { body: { mode: 'agent', default_engine: 'claude_code', grants: { claude_code: { summary: true, snippets: false, rules: false, raw: false } } } },
    'POST /v1/ai/ask': { body: { answer: 'FX 合成回答：Pi 会话最多', refs: [] } }
  });
  await openLive(page, 'overview');
  await expect.poll(() => page.evaluate(() => S.engine)).toBe('agent');
  await page.evaluate(() => openAsk('overview'));
  await expect(page.locator('#modal [data-tl="ask-presets"] [data-act="askPick"]')).toHaveCount(4);
  await expect(page.locator('#modal .mh')).not.toContainText('Demo');
  await page.locator('#modal [data-act="askPick"]').nth(1).click();
  await expect(page.locator('#askA')).toContainText('FX 合成回答');
  expect(posted('POST', '/v1/ai/ask')[0].body).toEqual({ context: 'overview', preset_index: 1 });
  await page.evaluate(() => closeModal());
  await page.route(/\/v1\/ai\/ask$/, (r) => r.fulfill({ status: 404, contentType: 'application/json', body: '{"error":{"code":"not_found"}}' }));
  await page.evaluate(() => openAsk('tools'));
  await page.locator('#askIn').fill('哪个工具最慢？');
  await page.locator('#modal [data-act="askSend"]').click();
  await expect(page.locator('#askA')).toContainText('本地服务暂不提供问答接口');
  await expect(page.locator('#askA')).not.toContainText('figma');
  expect(errors).toEqual([]);
});

test('notify frame: banner in the window and a system notification through the host while hidden', async ({ page }) => {
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's6'], {}, { native: NATIVE });
  await page.addInitScript(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); });
  gw.push([{ event: 'notification', data: { id: 'fx-n1', type: 'awaiting_approval', title: 'FX 等你确认', body: 'Pi · 合成会话', channels: ['banner', 'badge'] } }]);
  await openLive(page, 'overview');
  await expect(page.locator('#notes')).toContainText('FX 等你确认');
  await expect.poll(() => page.evaluate(() => window.__nativeMsgs.filter((m) => m.type === 'notify').map((m) => [m.title, m.body]))).toEqual([['FX 等你确认', 'Pi · 合成会话']]);
  expect(errors).toEqual([]);
});
