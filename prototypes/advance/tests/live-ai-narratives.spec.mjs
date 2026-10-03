// AI narratives in live mode (src/js/96-live-ai.js), against the stub gateway with synthetic fixtures — no real model:
//  1. persona   「AI 解读」 posts narrate.persona with the profile the page shows; only model text carries the AI badge;
//               a fallback (output failed the checks) is explained in place and the template is not shown;
//               after data.published (a new import) the shown result is marked as based on the earlier data
//  2. sessions  「让 Agent 复盘」 posts narrate.session_review for the selected session: stage + log line while running,
//               停止 cancels, consent_required shows in place, the model review is labelled AI with its engine
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const NOW = new Date('2026-10-03T12:00:00+08:00');
test.use({ timezoneId: 'Asia/Shanghai' });
test.beforeEach(async ({ page }) => { ONLY('mac-14'); test.skip(!!PASS, 'fixture tests'); await page.clock.setFixedTime(NOW); await page.emulateMedia({ reducedMotion: 'reduce' }); });

const json = (status, body) => ({ status, body });
const jobs = (posts, next) => (req) => { const b = req.postDataJSON(); posts.push(b); return next(b); };

test('persona: 「AI 解读」 posts narrate.persona with the shown profile; only model text carries the AI badge', async ({ page }) => {
  const errors = collectErrors(page);
  const posts = []; let n = 0;
  await stubGateway(page, ['core', 's1'], {
    'GET /v1/uiview/persona': (req, u) => { const p = u.searchParams.get('period') || '90'; return p === '30' ? fx('s1/persona-30.json') : p === '90' ? fx('s1/persona-90.json') : { status: 404 }; },
    'GET /v1/uiview/persona/reveal': () => fx('s1/reveal.json'),
    'POST /v1/ai/jobs': jobs(posts, () => json(202, { job_id: 'fx-per-' + (++n), status: 'queued', cached: false })),
    'GET /v1/ai/jobs/fx-per-1': { job_id: 'fx-per-1', task_id: 'narrate.persona', engine: 'claude_code', status: 'ok', finished_at: Date.UTC(2026, 9, 3, 2, 0), stages: [], log: [],
      result: { headline: 'FX 模型写的画像解读', traits: [{ text: '先定计划', metric: 'rates.sessions', value_ref: 1 }], tradeoffs: [{ axis: 'D', text: 'FX 取舍说明' }], blind_spots: [], caveats: ['FX 样本少'], source: 'ai' } },
    'GET /v1/ai/jobs/fx-per-2': { job_id: 'fx-per-2', task_id: 'narrate.persona', status: 'fallback', stages: [{ id: 'check', status: 'failed', message: '数字不在输入中' }], log: [],
      result: { headline: '模板标题', source: 'template' } }
  });
  await openLive(page, 'persona');
  const box = page.locator('.pe-ai');
  await expect(box.locator('[data-act="perAi"]')).toContainText('AI 解读');
  await expect(box.locator('.aib')).toHaveCount(0);
  await box.locator('[data-act="perAi"]').click();
  await expect(box).toContainText('FX 模型写的画像解读');
  await expect(box.locator('.aib')).toHaveCount(1);
  await expect(box).toContainText('Claude Code 撰写');
  await expect(box).toContainText('FX 取舍说明');
  await expect(box.locator('[data-act="perAi"]')).toContainText('重新生成');
  const shown = await page.evaluate(() => ({ code: CUR.persona.code, n: CUR.persona.n }));
  expect(posts[0].task_id).toBe('narrate.persona');
  expect(posts[0].params.profile.code).toBe(shown.code);
  expect(posts[0].params.profile.rates.sessions).toBe(shown.n);
  expect(Object.keys(posts[0].params.profile.axes)).toEqual(['D', 'I', 'M', 'V']);
  expect(posts[0].fresh).toBe(false);
  // a later import keeps the result but says it is based on the earlier data
  await expect(box).not.toContainText('之后导入了新数据');
  await page.evaluate(() => TL.dispatch('data.published', { data_rev: 99 }));
  await expect(box).toContainText('之后导入了新数据，这份结果基于之前的数据，可重新生成');
  await box.locator('[data-act="perAi"]').click();
  await expect(box).toContainText('模型这次没有写出可用的AI 解读（数字不在输入中），未显示模板内容');
  await expect(box).not.toContainText('模板标题');
  expect(posts[1].fresh).toBe(true);
  expect(errors).toEqual([]);
});

test('sessions: 「让 Agent 复盘」 shows stages, 停止 cancels, consent errors stay in place, the model review is labelled AI', async ({ page }) => {
  const errors = collectErrors(page);
  const posts = []; const cancels = []; let n = 0; let deny = false;
  const LIST = fx('s2/list.json');
  await stubGateway(page, ['core', 's2'], {
    'GET /v1/uiview/sessions': () => LIST,
    'POST /v1/ai/jobs': jobs(posts, () => deny
      ? json(403, { error: { code: 'consent_required', message: '需要授权', retryable: false, missing: ['snippets'], engine: 'claude_code' } })
      : json(202, { job_id: 'fx-rev-' + (++n), status: 'queued', cached: false })),
    'GET /v1/ai/jobs/fx-rev-1': () => ({ job_id: 'fx-rev-1', task_id: 'narrate.session_review', status: cancels.length ? 'cancelled' : 'running', stages: [{ id: 'pack', status: 'ok' }, { id: 'draft', status: 'running' }], log: ['FX 调用本地 Agent'] }),
    'POST /v1/ai/jobs/fx-rev-1/cancel': () => { cancels.push(1); return { job_id: 'fx-rev-1', status: 'cancelled' }; },
    'GET /v1/ai/jobs/fx-rev-2': { job_id: 'fx-rev-2', task_id: 'narrate.session_review', engine: 'codex', status: 'ok', stages: [], log: [],
      result: { summary: 'FX 复盘结论', findings: [{ title: '卡在哪', text: 'FX 同一命令连续失败', scene: 'stuck', evidence_ids: [] }], lessons: [{ text: 'FX 失败两次先停下', mechanism: 'hook', evidence_ids: [] }], caveats: [], source: 'ai' } }
  });
  await openLive(page, 'sessions');
  await expect.poll(() => page.evaluate(() => S.sess.sel)).not.toBeNull();
  const sel = await page.evaluate(() => S.sess.sel);
  await page.locator('[data-act="sessReview"]').first().click();
  const card = page.locator('[data-aikey="review|' + sel + '"]');
  await expect(card).toContainText('本地 Agent 撰写…');
  await expect(card.locator('[data-ailine]')).toHaveText('FX 调用本地 Agent');
  await card.locator('[data-act="aiStop"]').click();
  await expect(card).toContainText('已停止，未生成复盘');
  expect(cancels.length).toBe(1);
  deny = true;
  await card.locator('[data-act="sessReview"]').click();
  await expect(card).toContainText('需要先授权这些数据类：snippets');
  await expect(card.locator('.aib')).toHaveCount(0);
  deny = false;
  await card.locator('[data-act="sessReview"]').click();
  await expect(card).toContainText('FX 复盘结论');
  await expect(card.locator('.aib')).toHaveCount(1);
  await expect(card).toContainText('加 Hook');
  await expect(card).toContainText('Codex 撰写');
  expect(posts.every((b) => b.task_id === 'narrate.session_review' && b.params.session_uid === sel)).toBe(true);
  expect(errors).toEqual([]);
});
