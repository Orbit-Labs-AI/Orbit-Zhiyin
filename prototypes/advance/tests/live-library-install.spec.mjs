// Live binding for A8 资源库 and the install sheet (src/js/97-live-library-install.js + C.li in prototypes/shared/tandem-live.js).
// The gateway is simulated with page.route on http://tandem.test; /v1/catalog/* and /v1/install/* answer with the synthetic
// fixtures in prototypes/shared/fixtures/library-install (fixture mode, no real backend, no real sessions).
//  1. library   cards, rows, facet counts, 加载更多 (cursor), search, 本地生成, item detail (README, versions, risk)
//  2. install   plan → preview (default selection narrows Codex off) → toggle target → confirm → 409 preview_stale
//               re-previews → confirm → written → 撤销 (revert); installed sheet lists state + ledger
//  3. Lite      the single-file Lite page: catalog cards, detail, install with preview_stale re-confirm, undo
//  4. degraded  catalog / install routes missing → demo library and demo install sheet with 示例数据
import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..', '..');
const ADV_FILE = path.join(ROOT, 'advance', 'tandem-demo.html');
const LITE_FILE = path.join(ROOT, 'lite', 'tandem-benchmark-demo.html');
const FX = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, 'shared', 'fixtures', name + '.json'), 'utf8'));
const LI = (name) => FX('library-install/' + name);
const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');

function collectErrors(page, allow) {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const url = m.location().url || '';
    if (/fonts\.(googleapis|gstatic)\.com/.test(url)) return;
    if (allow && allow(m.text(), url)) return;
    errors.push(m.text());
  });
  return errors;
}

async function gateway(page, opt = {}) {
  const state = { seen: [], applies: 0 };
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.route(/^http:\/\/tandem\.test\//, async (route) => {
    const req = route.request(); const u = new URL(req.url()); const p = decodeURIComponent(u.pathname); const m = req.method();
    const body = req.postData() ? JSON.parse(req.postData()) : null;
    state.seen.push({ method: m, path: p, search: u.search, body });
    const json = (b, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(b) });
    if (p === '/app') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(ADV_FILE, 'utf8') });
    if (p === '/lite') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: fs.readFileSync(LITE_FILE, 'utf8') });
    if (p === '/v1/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    if (p === '/v1/status') return json(FX('status'));
    if (p === '/v1/analytics/overview') return json(FX('overview'));
    if (!opt.degraded) {
      if (p === '/v1/catalog/items') return json(u.searchParams.get('cursor') ? LI('catalog-items-page2') : u.searchParams.get('origin') === 'local' ? LI('catalog-items-local') : LI('catalog-items'));
      if (p === '/v1/catalog/facets') return json(LI('catalog-facets'));
      if (p === '/v1/catalog/search') return json(LI('catalog-search'));
      if (p.startsWith('/v1/catalog/items/')) return json(LI('catalog-item'));
      if (p === '/v1/install/environment') return json(LI('install-environment'));
      if (p === '/v1/install/plans' && m === 'POST') return json(LI('install-plan'), 201);
      if (p === '/v1/install/plans/plan-fx-1/preview') return json(m === 'GET' ? LI('install-preview') : (body.disabled_targets || []).length ? LI(state.applies ? 'install-preview-refreshed' : 'install-preview-narrowed') : LI('install-preview'));
      if (p === '/v1/install/apply') { state.applies++; return state.applies === 1 ? json(LI('install-apply-stale'), 409) : json(LI('install-apply')); }
      if (p === '/v1/install/inst-fx-1/revert') return json(LI('install-revert'));
      if (p === '/v1/install/state') return json(LI('install-state'));
      if (p === '/v1/install/ledger') return json(LI('install-ledger'));
    }
    return json({ error: { code: 'not_found', message: p, retryable: false } }, 404);
  });
  return state;
}
const allow404 = (text) => /status of 404/.test(text) || /status of 409/.test(text);

test('live library: catalog cards, facets, paging, search, local items and item detail', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.addStyleTag({ content: '#notes{display:none!important}' });   // demo notifications would cover the toolbar
  await page.evaluate(() => go('library'));
  const lib = page.locator('[data-tl="library"]');
  await expect(lib.locator('.lb-card')).toHaveCount(3);
  await expect(lib.locator('.lb-row')).toHaveCount(1);
  await expect(lib.locator('.lb-card').first()).toContainText('worktree-helper');
  await expect(lib.locator('[data-act="libKind"][data-v="Skill"]')).toContainText('2');
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await expect(lib.locator('[data-tl="lib-facets"]')).toContainText('MIT 3');
  // installed state from the catalog card and from /v1/install/state
  await expect(lib.locator('[data-tl-item="fx:agent/release-check"]')).toContainText('已安装');
  // missing installs show —, not 0
  await expect(lib.locator('[data-tl-item="fx:mcp/doc-reader"] .lb-fc.mono')).toHaveText('—');
  await page.locator('[data-tl="lib-more"]').click();
  await expect(lib.locator('.lb-row')).toHaveCount(2);
  await expect(lib).toContainText('deploy-kit');
  expect(gw.seen.some((s) => s.path === '/v1/catalog/items' && /cursor=fx-cursor-2/.test(s.search))).toBe(true);
  await page.locator('[data-act="libKind"][data-v="插件"]').click();
  await expect.poll(() => gw.seen.some((s) => s.path === '/v1/catalog/items' && /kind=plugin&kind=marketplace/.test(s.search))).toBe(true);
  await page.locator('[data-act="libKind"][data-v="全部"]').click();
  // search (debounced) goes to /v1/catalog/search
  await page.locator('#libQ').fill('retry');
  await expect(page.locator('[data-tl="library"]')).toContainText('搜索「retry」');
  await expect(page.locator('[data-tl="library"] .lb-card')).toHaveCount(1);
  await expect(page.locator('[data-tl="library"] .lb-card')).toContainText('失败两次后暂停');
  expect(gw.seen.some((s) => s.path === '/v1/catalog/search' && /q=retry/.test(s.search))).toBe(true);
  await page.locator('#libQ').fill('');
  // 本地生成 tab
  await page.locator('[data-act="libTab"][data-v="local"]').click();
  await expect(page.locator('[data-tl="library"] .lb-card')).toContainText('paper-audit-loop');
  // detail
  await page.locator('[data-act="libTab"][data-v="for"]').click();
  await page.locator('[data-tl-item="fx:hook/retry-guard"] [data-act="liDetail"]').first().click();
  const d = page.locator('#modal [data-tl="lib-detail"]');
  await expect(d.locator('[data-tl="lib-readme"]')).toContainText('同一命令连续失败两次后暂停');
  await expect(d.locator('[data-tl="lib-versions"] tbody tr')).toHaveCount(2);
  await expect(d).toContainText('shell');
  expect(errors).toEqual([]);
});

test('live install: preview, target selection, preview_stale re-confirm, apply, undo and the installed sheet', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.addStyleTag({ content: '#notes{display:none!important}' });   // demo notifications would cover the toolbar
  await page.evaluate(() => go('library'));
  await page.locator('[data-tl-item="fx:hook/retry-guard"] [data-act="getLib"]').first().click();
  const pv = page.locator('#modal [data-tl="inst-preview"]');
  await expect(pv.locator('[data-tl="inst-target"]')).toHaveCount(2);
  // default: only the first agent writes; Codex target off (POST preview with disabled_targets [1])
  const plan = gw.seen.find((s) => s.path === '/v1/install/plans');
  expect(plan.body).toEqual({ source: { type: 'catalog', id: 'fx:hook/retry-guard' }, scope: 'user', agents: ['claude_code'] });
  expect(gw.seen.find((s) => s.path === '/v1/install/plans/plan-fx-1/preview').body).toEqual({ disabled_targets: [1] });
  await expect(pv.locator('[data-idx="1"]')).toContainText('已取消');
  await expect(pv.locator('[data-idx="0"] .code .add')).toHaveCount(1);
  await expect(pv.locator('[data-idx="0"] .code .ai')).toHaveCount(1);
  // turn Codex on → unchanged selection → GET preview (digest a)
  await pv.locator('[data-chg="liTarget"][data-i="1"]').check();
  await expect(pv.locator('[data-idx="1"] .code')).toBeVisible();
  await pv.locator('[data-chg="liTarget"][data-i="1"]').uncheck();
  await expect(pv.locator('[data-idx="1"]')).toContainText('已取消');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await expect(page.locator('#modal [data-tl="inst-confirm"]')).toContainText('~/.claude/settings.json');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  // 409 preview_stale: back to the diff with a notice, nothing written
  await expect(page.locator('#modal [data-tl="inst-stale"]')).toContainText('重新生成预览');
  expect(gw.seen.filter((s) => s.path === '/v1/install/apply')[0].body).toEqual({ plan_id: 'plan-fx-1', preview_digest: 'sha256:fx-digest-b', disabled_targets: [1] });
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  await expect(page.locator('#modal [data-tl="inst-done"]')).toContainText('settings.json.1');
  expect(gw.seen.filter((s) => s.path === '/v1/install/apply')[1].body.preview_digest).toBe('sha256:fx-digest-c');
  await expect(page.locator('[data-tl-item="fx:hook/retry-guard"]').first()).toContainText('已安装');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instUndo"]').click();
  await expect(page.locator('#toast')).toContainText('已撤销');
  expect(gw.seen.some((s) => s.method === 'POST' && s.path === '/v1/install/inst-fx-1/revert')).toBe(true);
  // installed sheet: state + ledger
  await page.locator('[data-act="libInstalled"]').click();
  await expect(page.locator('#modal [data-tl="installed"]')).toContainText('release-check');
  await expect(page.locator('#modal [data-tl="ledger"] .tl-ev')).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('live library degraded: missing catalog / install routes fall back to the demo with 示例数据', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  await gateway(page, { degraded: true });
  await page.goto('http://tandem.test/app#token=fx-token');
  await page.addStyleTag({ content: '#notes{display:none!important}' });   // demo notifications would cover the toolbar
  await page.evaluate(() => go('library'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await expect(page.locator('#content .lb-card').first()).toContainText('retry-breaker');
  await page.locator('#content .lb-card [data-act="getLib"]').first().click();
  await expect(page.locator('#modal')).toContainText('预览变更');
  await page.locator('#modal [data-act="closeModal"]').first().click();
  await page.locator('[data-act="libInstalled"]').click();
  await expect(page.locator('#modal [data-tl="sample"]')).toHaveText('示例数据');
  expect(errors).toEqual([]);
});

test('live Lite library: catalog cards, detail and install (preview_stale re-confirm, undo)', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  const gw = await gateway(page);
  await page.goto('http://tandem.test/lite#token=fx-token');
  await page.evaluate(() => go('library'));
  const lib = page.locator('[data-tl="library"]');
  await expect(lib.locator('.lib-feature')).toHaveCount(3);
  await expect(lib.locator('.lib-row')).toHaveCount(1);
  await expect(page.locator('#content [data-tl="sample"]')).toHaveCount(0);
  await page.locator('[data-tl-item="fx:hook/retry-guard"] [data-act="li-detail"]').evaluate((el) => el.click());
  await expect(page.locator('#modal [data-tl="lib-readme"]')).toContainText('同一命令连续失败两次后暂停');
  await expect(page.locator('#modal [data-tl="lib-versions"]')).toContainText('0.9.0');
  await page.locator('#modal [data-act="li-install"]').evaluate((el) => el.click());
  await expect(page.locator('#modal [data-tl="inst-preview"]')).toContainText('~/.claude/settings.json');
  await page.locator('#modal [data-act="li-apply"]').evaluate((el) => el.click());
  await expect(page.locator('#modal [data-tl="inst-stale"]')).toContainText('重新生成预览');
  await page.locator('#modal [data-act="li-apply"]:not([disabled])').evaluate((el) => el.click());
  await expect(page.locator('#modal [data-tl="inst-done"]')).toContainText('settings.json');
  expect(gw.seen.filter((s) => s.path === '/v1/install/apply').map((s) => s.body.preview_digest)).toEqual(['sha256:fx-digest-b', 'sha256:fx-digest-c']);
  await page.locator('#modal [data-act="li-undo"]').evaluate((el) => el.click());
  await expect.poll(() => gw.seen.some((s) => s.path === '/v1/install/inst-fx-1/revert')).toBe(true);
  expect(errors).toEqual([]);
});

test('live Lite library degraded: the demo library with 示例数据', async ({ page }) => {
  ONLY('mac-14');
  const errors = collectErrors(page, allow404);
  await gateway(page, { degraded: true });
  await page.goto('http://tandem.test/lite#token=fx-token');
  await page.evaluate(() => go('library'));
  await expect(page.locator('#content [data-tl="sample"]')).toHaveText('示例数据');
  await expect(page.locator('#content .lib-feature')).toHaveCount(3);
  expect(errors).toEqual([]);
});
