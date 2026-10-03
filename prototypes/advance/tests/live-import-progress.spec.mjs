// Import progress that explains itself (bug 8, docs/development/import-pipeline.md): the note under 导入历史会话 names the
// step and where the job is (the gateway's label / detail), the count says what it counts, the bar follows the job's
// overall progress (never moving back when the next source starts), a partial import is done rather than failed, and a
// projection stuck behind its captures offers 重新导入. Stub gateway; job frames go through TL.dispatch.
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const JOB = '10951bad4daa4a2fb0994de1f0d61e09';
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
test.skip(!!PASS, 'stub-only: feeds synthetic job frames');

const frame = (page, name, data) => page.evaluate(([n, d]) => TL.dispatch(n, d), [name, data]);
const running = (progress, status) => ({ id: JOB, kind: 'import', status: status || 'running', progress });
const MAP = {
  stage: 'map', completed: 419, total: 975, records: 203000, unit: 'files', label: '解析会话记录',
  detail: 'Codex · 第 1/2 个来源 · 重建整个来源 · 已解析 203,000 条记录', step: 1, steps: 2, overall: 0.43
};

function firstRun(progress) {
  const job = Object.assign(fx('s7/job-running.json'), { progress });
  return {
    'GET /v1/uiview/facts': fx('core/facts-empty.json'),
    'POST /v1/app/sources': (req) => { const b = JSON.parse(req.postData() || '{}'); return { id: 'source_new_' + b.agent, agent: b.agent, root: b.root, enabled: b.enabled }; },
    'PATCH /v1/app/settings': (req) => Object.assign({ onboarded: false, recent_days: 90 }, JSON.parse(req.postData() || '{}')),
    'POST /v1/app/jobs': { status: 202, body: fx('s7/job-queued.json') },
    ['GET /v1/app/jobs/' + JOB]: job,
    'POST /v1/catalog/sync': { status: 202, body: { accepted: true } }
  };
}

async function startImport(page, gw) {
  await openLive(page, 'overview');
  await page.locator('#overlay [data-act="obNext"]').click();
  await expect(page.locator('#overlay label.srcrow').first()).toBeVisible();
  await page.locator('#overlay [data-act="obStart"]').click();
  await expect(page.locator('#overlay [data-ob="stages"] .step')).toHaveCount(4);
  return gw;
}

test('the import note names the step, the source and what the numbers count', async ({ page }) => {
  ONLY('mac-14');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's7'], firstRun(MAP));
  await startImport(page, gw);
  const row = page.locator('#overlay [data-stage="backfill"]');
  await frame(page, 'job', running(MAP));
  await expect(row.locator('.s')).toHaveText('解析会话记录 · Codex · 第 1/2 个来源 · 重建整个来源 · 已解析 203,000 条记录');
  await expect(row.locator('.mono')).toHaveText('419 / 975 个文件');
  // the bar is the whole job (43 %), not this stage's 419 / 975
  await expect(page.locator('#overlay [data-ob="bar"]')).toHaveAttribute('style', /width:\s*43%/);
  // the next source starts at capture 0 / 12: the bar holds instead of jumping back to 0
  const next = { stage: 'capture', completed: 0, total: 12, unit: 'files', label: '读取会话文件', detail: 'Claude Code · 第 2/2 个来源', step: 2, steps: 2, overall: 0.5 };
  gw.set('GET /v1/app/jobs/' + JOB, Object.assign(fx('s7/job-running.json'), { progress: next }));
  await frame(page, 'job', running(next));
  await expect(row.locator('.s')).toHaveText('读取会话文件 · Claude Code · 第 2/2 个来源');
  await expect(row.locator('.mono')).toHaveText('0 / 12 个文件');
  await expect(page.locator('#overlay [data-ob="bar"]')).toHaveAttribute('style', /width:\s*50%/);
  // an older gateway sends the raw stage only: it is named, never shown as "reset_projection"
  const old = { stage: 'reset_projection' };
  gw.set('GET /v1/app/jobs/' + JOB, Object.assign(fx('s7/job-running.json'), { progress: old }));
  await frame(page, 'job', running(old));
  await expect(row.locator('.s')).toHaveText('开始重建');
  // the page strip says the same (after 在后台继续)
  gw.set('GET /v1/app/jobs/' + JOB, Object.assign(fx('s7/job-running.json'), { progress: MAP }));
  await frame(page, 'job', running(MAP));
  await page.locator('#overlay [data-act="obBgImport"]').click();
  await expect(page.locator('#content .tl-progress')).toContainText('解析会话记录 · Codex · 第 1/2 个来源');
  await expect(page.locator('#content .tl-progress')).toContainText('419 / 975 个文件');
  await expect(page.locator('#side [data-side="import"]')).toContainText('43%');
  expect(errors).toEqual([]);
});

test('a partial import counts as imported, not as a failure', async ({ page }) => {
  ONLY('mac-14');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const errors = collectErrors(page);
  const gw = await stubGateway(page, ['core', 's7'], firstRun(MAP));
  await startImport(page, gw);
  const partial = Object.assign(fx('s7/job-completed.json'), { status: 'partial' });
  gw.set('GET /v1/app/jobs/' + JOB, partial);
  await frame(page, 'job', partial);
  const row = page.locator('#overlay [data-stage="backfill"]');
  await expect(row).toHaveAttribute('data-st', 'done');
  await expect(row.locator('.s')).toContainText('已导入');
  await expect(page.locator('#overlay [data-ob="err"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a projection stuck behind its captures offers 重新导入', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  const status = fx('core/status.json');
  status.projection = 'pending';
  status.projection_info = { state: 'pending', pending_files: 3, retained_files: 0, pending_since: 1, stuck: true,
    retry: { method: 'POST', path: '/v1/app/jobs', body: { kind: 'import' } } };
  const posted = [];
  const gw = await stubGateway(page, ['core'], {
    'GET /v1/status': status,
    'POST /v1/app/jobs': (req) => { posted.push(JSON.parse(req.postData() || '{}')); return { status: 202, body: fx('s7/job-queued.json') }; }
  });
  await openLive(page, 'overview');
  const banner = page.locator('#content [data-tl="projection-stuck"]');
  await expect(banner).toContainText('最近的会话变化还没有发布（3 个文件）');
  await expect(banner).toContainText('显示上次发布的数据');
  await banner.locator('[data-act="lvReimport"]').click();
  await expect.poll(() => posted.length).toBe(1);
  expect(posted[0]).toEqual({ kind: 'import' });
  expect(gw.seen.some((x) => x.method === 'POST' && x.path === '/v1/app/jobs')).toBe(true);
  expect(errors).toEqual([]);
});

test('a background sync reads as 后台同步 and leaves the sidebar import entry alone', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page);
  await stubGateway(page, ['core']);
  await openLive(page, 'sessions');
  const sync = { id: 'sync-1', kind: 'import', status: 'running', origin: 'sync',
    progress: { stage: 'map', completed: 3, total: 3, unit: 'files', label: '解析会话记录', detail: 'Claude Code · 只重建受影响的会话', overall: 0.6, origin: 'sync' } };
  await frame(page, 'job', sync);
  await expect(page.locator('#content .tl-progress')).toContainText('后台同步 · 解析会话记录 · Claude Code · 只重建受影响的会话');
  await expect(page.locator('#content .tl-progress')).toContainText('3 / 3 个文件');
  await expect(page.locator('#side [data-side="import"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});
