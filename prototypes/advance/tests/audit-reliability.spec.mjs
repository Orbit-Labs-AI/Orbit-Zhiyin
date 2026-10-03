import { test, expect } from '@playwright/test';
import { stubGateway, openLive, fx } from './live-helpers.mjs';
import { openDemo } from './helpers.mjs';

test.beforeEach(async ({ page }) => {
  test.skip(test.info().project.name !== 'mac-14', 'shared behavior, one viewport');
  await page.emulateMedia({ reducedMotion: 'reduce' });
});

test('settings serialize rapid choices and retain a later success after an earlier failure', async ({ page }) => {
  const initial = fx('s7/app-state-full.json');
  let settings = { ...initial.settings, weekly_report: true, sync_mode: 'live' };
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const writes = [];
  await stubGateway(page, 'core', {
    'GET /v1/app/state': () => ({ ...initial, settings }),
    'PATCH /v1/app/settings': async (req) => {
      const patch = req.postDataJSON(); writes.push(patch);
      if (writes.length === 1) {
        await gate;
        return { status: 503, body: { error: { code: 'temporarily_unavailable', message: 'try again' } } };
      }
      settings = { ...settings, ...patch };
      return settings;
    }
  });
  await openLive(page, 'overview');
  await page.evaluate(() => openSettings('analysis'));
  await expect(page.locator('[data-act="setWeekly"]')).toHaveAttribute('aria-checked', 'true');
  await page.locator('[data-act="setWeekly"]').click();
  await expect.poll(() => writes.length).toBe(1);
  await page.locator('[data-act="setWeekly"]').click();
  await expect(page.locator('[data-act="setWeekly"]')).toHaveAttribute('aria-checked', 'true');
  expect(writes).toEqual([{ weekly_report: false }]);
  release();
  await expect.poll(() => writes).toEqual([{ weekly_report: false }, { weekly_report: true }]);
  await expect.poll(() => page.evaluate(() => TLS_WRITES.size)).toBe(0);
  expect(settings.weekly_report).toBe(true);
  await expect(page.locator('[data-act="setWeekly"]')).toHaveAttribute('aria-checked', 'true');
});

test('sheets always provide a named close icon and HUD collapse preserves the pill', async ({ page }) => {
  await openDemo(page);
  await page.evaluate(() => openModal(modalHead('检查对话框', '构造内容') + '<div class="mf"><button class="btn" data-act="closeModal">取消</button></div>'));
  await page.getByRole('button', { name: '关闭对话框', exact: true }).click();
  await expect(page.locator('#modal')).toBeHidden();
  await page.evaluate(() => { S.hud.show = true; S.hud.open = true; renderHud(); });
  await expect(page.getByRole('dialog', { name: '会话详情' })).toBeVisible();
  await page.getByRole('button', { name: '收起会话详情', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '会话详情' })).toHaveCount(0);
  await expect(page.locator('#hudPill')).toBeVisible();
  await expect(page.locator('#hudPill')).toBeFocused();
});

test('ask carries the selected scope and an old answer cannot overwrite a newer one', async ({ page }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const bodies = [];
  await stubGateway(page, 'core', {
    'GET /v1/ai/ask/presets': [],
    'POST /v1/ai/ask': async (req) => {
      const body = req.postDataJSON(); bodies.push(body);
      if (body.question === '第一个问题') { await gate; return { answer: '旧的回答不应该出现', source: 'ai' }; }
      return { answer: '当前问题的答案', source: 'ai' };
    }
  });
  await openLive(page, 'overview');
  await page.evaluate(() => { S.range = 7; S.project = 'fixture-project'; S.excluded = new Set(['excluded-session']); openAsk('overview'); });
  await page.locator('#askIn').fill('第一个问题');
  await page.locator('[data-act="askSend"]').click();
  await expect.poll(() => bodies.length).toBe(1);
  await page.locator('#askIn').fill('第二个问题');
  await page.locator('[data-act="askSend"]').click();
  await expect(page.locator('#askA')).toContainText('当前问题的答案');
  release();
  await expect.poll(() => page.evaluate(() => ASK.text)).toBe('当前问题的答案\n\n— 本地 Agent 回答 · 只发送了脱敏后的查询结果');
  expect(bodies[0].scope).toMatchObject({ project_id: 'fixture-project', excluded_session_uids: ['excluded-session'] });
  expect(bodies[0].scope.end_ms - bodies[0].scope.start_ms).toBeLessThanOrEqual(7 * 86400000);
  expect(bodies[0].scope.end_ms - bodies[0].scope.start_ms).toBeGreaterThan(6 * 86400000);
});

test('professional analysis selector submits an existing job and shows validated structured findings', async ({ page }) => {
  const bodies = [];
  await stubGateway(page, 'core', {
    'GET /v1/ai/ask/presets': [],
    'POST /v1/ai/jobs': (req) => { bodies.push(req.postDataJSON()); return { job_id: 'analysis-fixture', status: 'queued' }; },
    'GET /v1/ai/jobs/analysis-fixture': { status: 'completed', result: {
      summary: '验证流程可以更明确', findings: [{ kind: 'observation', text: '缺少验收步骤', evidence_ids: ['event-fixture'], metrics: [] }],
      next_steps: ['先定义完成条件'], limitations: ['仅依据所选样本']
    } }
  });
  await openLive(page, 'overview');
  await page.evaluate(() => openAsk('overview'));
  await page.locator('#askTemplate').selectOption('analyze.quality');
  await page.locator('#askIn').fill('检查交付质量');
  await page.locator('[data-act="askSend"]').click();
  await expect(page.locator('#askA')).toContainText('仅依据所选样本');
  expect(bodies[0]).toMatchObject({ task_id: 'analyze.quality', goal_source: 'ask', params: { question: '检查交付质量' } });
  await expect(page.locator('#askA')).toContainText('证据：event-fixture');
});

test('AI advice remains a visible draft and hands a workflow to the studio without installing', async ({ page }) => {
  const data = fx('recs/recommendations.json');
  const candidate = data.items[0];
  candidate.expert_advice = [{ kind: 'workflow', title: '缩短重复验证', summary: '按变更范围选择验证', steps: ['列出验收条件', '只运行相关检查'], evidence_ids: ['problem-fixture'], limitations: ['收益需要后续验证'], draft: true, effect_status: 'unmeasured' }];
  const gw = await stubGateway(page, 's1', { 'GET /v1/recommendations': data });
  await openLive(page, 'recs');
  await expect.poll(() => page.evaluate(() => RECS.filter((r) => r.live).length)).toBeGreaterThan(0);
  await page.evaluate((id) => { S.recs.sel = id; S.recs.tab = 'why'; render(); }, candidate.candidate_id || candidate.rec_key);
  await expect(page.locator('[data-tl="expert-advice"]')).toContainText('收益需要后续验证');
  await page.locator('[data-act="recExpertStudio"]').click();
  await expect(page.locator('#studioGoal')).toHaveValue(/缩短重复验证/);
  expect(await page.evaluate(() => S.studio.type)).toBe('工作流');
  expect(gw.seen.filter((x) => x.path === '/v1/install/apply')).toHaveLength(0);
});
