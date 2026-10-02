// Round 4 regressions for A7 建议 / A8 资源库 / the install sheet (synthetic fixtures, stubbed gateway, no real data):
//  R4-01  目录分布 with a kind chip on: shares use the all-kind total (the kind facet stays unfiltered), never > 100%
//  R4-06  install confirm shows the backup dir with ~ and no literal <install_id>; one row per file; warning codes in words
//  R4-15  A7 header leads with the sidebar badge's total; a live rec without a file body shows an honest note, not an empty box
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'runs once, at the default size');
const LI = (n) => fx('library-install/' + n + '.json');
const HOME = '/private/var/folders/zz/fx/T/tmp.fx/home';

test.beforeEach(async ({ page }) => { ONLY('mac-14'); test.skip(!!PASS, 'stubbed bodies'); await page.emulateMedia({ reducedMotion: 'reduce' }); });

function recs() {
  const b = fx('recs/recommendations.json');
  b.items[0].ui.file = [];                       // target known, body not shipped
  b.items[2].ui.lvl = 4; b.items[2].level = 4;   // hidden by the default difficulty filter (L1–L3)
  return b;
}
function preview() {
  const p = LI('install-preview-refreshed');
  p.backup_dir = HOME + '/backups/<install_id>';
  p.targets = [Object.assign({}, p.targets[0], { idx: 0, path: HOME + '/.claude/settings.json', display: '~/.claude/settings.json' }),
    Object.assign({}, p.targets[0], { idx: 1, path: HOME + '/.claude/settings.json', display: '~/.claude/settings.json' })];
  p.totals = { files: 1, adds: 2, dels: 1 };
  p.warnings = ['already_present:claude_code:retry-guard'];
  return p;
}
function apply() {
  const a = LI('install-apply');
  a.written = [Object.assign({}, a.written[0], { backup_path: HOME + '/backups/inst-fx-1/0-settings.json' }), Object.assign({}, a.written[0], { idx: 1, backup_path: null })];
  a.warnings = ['inventory_refresh_failed', 'some_new_code'];
  return a;
}

test('R4-01 library: 目录分布 shares stay within 100% while a kind chip filters the list', async ({ page }) => {
  const errors = collectErrors(page);
  const kinds = [{ value: 'mcp_server', count: 300 }, { value: 'skill', count: 20 }, { value: 'plugin', count: 60 }, { value: 'hook', count: 10 }];
  await stubGateway(page, 's1', {
    'GET /v1/catalog/items': LI('catalog-items'),
    'GET /v1/catalog/status': { last_sync_at: 1, coverage: { by_source: {} } },
    'GET /v1/catalog/facets': (req, u) => Object.assign(LI('catalog-facets'), { kind: kinds, total: u.searchParams.getAll('kind').includes('skill') ? 20 : 390 })
  });
  await openLive(page, 'library');
  const card = page.locator('[data-tl="lib-facets"]');
  await expect(card).toContainText('390');
  await page.locator('[data-act="libKind"][data-v="Skill"]').click();
  await expect(card).toContainText('当前筛选下共 20 项');
  await expect(card).toContainText('全部类型共 390 项');
  const pcts = await card.locator('[data-tl="lib-facet"]').evaluateAll((els) => els.map((e) => +e.dataset.pct));
  expect(pcts.length).toBe(4);
  expect(Math.max(...pcts)).toBeLessThanOrEqual(100);
  expect(await card.innerText()).not.toMatch(/\d{3,}%/);
  // the bars never run past the card
  const over = await card.evaluate((c) => { const r = c.getBoundingClientRect(); return [...c.querySelectorAll('.lb-peer i')].some((i) => i.getBoundingClientRect().right > r.right + 0.5); });
  expect(over).toBe(false);
  expect(errors).toEqual([]);
});

test('R4-15 + R4-06 recs: header total matches the badge, no-body preview is honest, install sheet paths and warnings', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, 's1', {
    'GET /v1/recommendations': recs(),
    'GET /v1/install/environment': LI('install-environment'),
    'POST /v1/install/plans': { status: 201, body: LI('install-plan') },
    'GET /v1/install/plans/plan-fx-1/preview': preview(),
    'POST /v1/install/plans/plan-fx-1/preview': preview(),
    'POST /v1/install/apply': apply(),
    'GET /v1/install/state': { items: [] }
  });
  await openLive(page, 'recs');
  await expect.poll(() => page.evaluate(() => RECS.filter((r) => r.live).length)).toBe(3);
  const badge = await page.evaluate(() => visibleRecs().filter((r) => !S.installed.has(r.id)).length);
  await expect(page.locator('body')).toContainText('共 ' + badge + ' 条');
  await expect(page.locator('body')).toContainText('显示 2 条（1 条被筛选隐藏）');
  // preview tab of the rec without a file body: a note and the primary button, no empty code box
  const id = await page.evaluate(() => RECS.find((r) => r.live && !r.file.length).id);
  await page.evaluate((i) => { S.recs.sel = i; S.recs.tab = 'preview'; render(); }, id);
  const note = page.locator('#content [data-tl="rec-pv-nofile"]');
  await expect(note).toContainText('没有附带文件正文');
  await expect(page.locator('#content .rc-pv .code')).toHaveCount(0);
  await expect(page.locator('#content .rc-pv [data-act="copyRec"]')).toHaveCount(0);
  // install sheet: confirm step
  await note.locator('[data-act="install"]').first().click();
  const pv = page.locator('#modal [data-tl="inst-preview"]');
  await expect(pv).toBeVisible();
  await expect(pv).toContainText('已经存在于');
  await expect(pv).not.toContainText('already_present');
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  const cf = page.locator('#modal [data-tl="inst-confirm"]');
  await expect(cf).toContainText('~/backups/');
  await expect(cf).not.toContainText('<install_id>');
  await expect(cf).not.toContainText('/private/var');
  expect((await cf.innerText()).split('~/.claude/settings.json').length - 1).toBe(1);
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  const done = page.locator('#modal [data-tl="inst-done"]');
  await expect(done).toContainText('~/backups/inst-fx-1/0-settings.json');
  await expect(done).not.toContainText('inventory_refresh_failed');
  await expect(done).not.toContainText('some_new_code');
  await expect(done).toContainText('「已安装」列表暂未刷新');
  expect((await done.innerText()).split('~/.claude/settings.json').length - 1).toBe(1);
  expect(errors).toEqual([]);
});
