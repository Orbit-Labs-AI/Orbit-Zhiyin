// v0.0.4 bug hunt (UI) regressions — synthetic fixtures, stubbed gateway (mac-14 only):
//  K1  a KPI tile without a drawable trend has no period label: A4 仅看失败 reads「36」, not「36 近 12 周」(a 12-week count)
//  R1  a live rec with a body but no path hint: preview says 剪贴板 / 不写入文件 (copy) or 由安装预览生成 (install), never an
//      empty path, an empty file name marked 新建 or「已限定项目 · 」with nothing after it
//  U1  a library imported by an older version (facts 409 rebuild_required / 422 schema obsolete, nothing ever shown): pages of
//      both editions, the sidebar, widgets and menubar say the data needs a rebuild — never 还没有会话 / 导入会话 / 计算中 —
//      and the stuck banner does not claim to show 上次发布的数据 when there is none on screen
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, collectErrors, fx, PASS } from './live-helpers.mjs';

test.beforeEach(async ({ page }) => { test.skip(test.info().project.name !== 'mac-14', 'interaction checks run once'); test.skip(!!PASS, 'stubbed bodies'); await page.emulateMedia({ reducedMotion: 'reduce' }); });

test('K1 A4: 仅看失败 has no 近 12 周 next to the failure count', async ({ page }) => {
  const errors = collectErrors(page);
  await stubGateway(page, ['core', 's3']);
  await openLive(page, 'tools');
  await page.evaluate(() => { S.tools.failOnly = true; edSet('advance', 'tools'); });
  const fail = page.locator('#main .vz-kpi').filter({ hasText: '失败次数' });
  await expect(fail).toBeVisible();
  await expect(fail.locator('.vz-spark')).toHaveCount(0);
  await expect(fail.locator('.vz-kpi-p')).toHaveCount(0);
  // the tiles that do draw a 12-week line keep their label
  await page.evaluate(() => { S.tools.failOnly = false; render(); });
  const calls = page.locator('#main .vz-kpi').filter({ hasText: '工具调用' });
  await expect(calls.locator('.vz-kpi-p')).toHaveText('近 12 周');
  expect(errors).toEqual([]);
});

test('R1 A7: preview of a live rec without a path hint never shows an empty target', async ({ page }) => {
  const errors = collectErrors(page);
  const b = fx('recs/recommendations.json');
  const copy = b.items.find((c) => c.ui.primary === '复制片段'); copy.ui.target = '';
  const inst = b.items.find((c) => c.ui.primary === '预览并安装' && c.ui.file.length); inst.ui.target = '';
  await stubGateway(page, 's1', { 'GET /v1/recommendations': b, 'GET /v1/install/state': { items: [] } });
  await openLive(page, 'recs');
  await expect.poll(() => page.evaluate(() => RECS.filter((r) => r.live).length)).toBe(3);
  const pv = page.locator('#content .rc-pv');
  await page.evaluate((i) => { edSet('advance', 'recs'); S.recs.lv = new Set([1, 2, 3, 4]); S.recs.sel = i; S.recs.tab = 'preview'; render(); }, copy.candidate_id);
  await expect(pv.locator('[data-tl="rec-pv-clip"]')).toHaveText('剪贴板');
  await expect(pv).toContainText('不写入文件');
  await expect(pv).not.toContainText('已限定项目');
  await expect(pv).not.toContainText('新建');
  await expect(pv.locator('.code')).toHaveCount(1);
  await page.evaluate((i) => { S.recs.sel = i; S.recs.tab = 'preview'; render(); }, inst.candidate_id);
  await expect(pv.locator('[data-tl="rec-pv-planned"]')).toContainText('安装预览');
  await expect(pv).not.toContainText('已限定项目');
  await expect(pv).not.toContainText('不写入文件');
  expect(errors).toEqual([]);
});

const FALSE_CLAIMS = /没有会话|还没有接入|都已处理|查看 0 条建议|显示上次发布的数据/;
const PROGRESS = /计算中|分析中|分析完成后|正在分析|正在导入/;
const FAKE_ZERO = /\b0(\.0)? ?(个会话|次|条|会话|h\b)|全部 0\b|▲ 0%|样本不足/;
const UPGRADE = {
  obsolete: { 'GET /v1/uiview/facts': { status: 422, body: { error: { code: 'invalid_request', message: 'Storage schema is obsolete; migrate and rebuild before analysis', retryable: false } } } },
  rebuild: {
    'GET /v1/uiview/facts': { status: 409, body: { error: { code: 'rebuild_required', message: 'Projection version is obsolete or incomplete; rebuild before analysis', retryable: true } } },
    'GET /v1/status': Object.assign(fx('core/status.json'), { projection: 'invalid', projection_info: { state: 'invalid', pending_files: 0, retained_files: 0, pending_since: null, stuck: true } })
  }
};
for (const kind of Object.keys(UPGRADE)) {
  test('U1 upgrade (' + kind + '): no page claims there are no sessions while the library needs a rebuild', async ({ page }) => {
    const errors = collectErrors(page);
    await stubGateway(page, ['core'], UPGRADE[kind]);
    await openLive(page, 'overview');
    expect(await page.evaluate(() => [LV.state, ALL.length])).toEqual(['error', 0]);
    if (kind === 'rebuild') await expect(page.locator('#content [data-tl="projection-stuck"]')).toContainText('数据需要按新版本重建');
    for (const ed of ['advance', 'lite']) {
      await page.evaluate((e) => { if (S.ed !== e) edSet(e); }, ed);
      await expect.poll(() => page.evaluate(() => S.ed)).toBe(ed);
      for (const r of ed === 'lite' ? ['l-home', 'l-persona', 'l-sessions', 'l-recs'] : ['overview', 'persona', 'sentiment', 'projects', 'sessions', 'tools', 'recs']) {
        await page.evaluate((x) => go(x), r);
        await expect.poll(() => page.evaluate(() => S.route)).toBe(r);
        const txt = await page.locator('#main').innerText();
        expect(txt, ed + ' ' + r).not.toMatch(FALSE_CLAIMS);
        expect(txt, ed + ' ' + r).not.toMatch(PROGRESS);
        expect(txt, ed + ' ' + r).not.toMatch(FAKE_ZERO);
        expect(txt, ed + ' ' + r).toContain('重建');
        await expect(page.locator('#main [data-act="liteImport"]'), ed + ' ' + r).toHaveCount(0);
      }
    }
    expect(await page.locator('#side').innerText()).not.toMatch(FALSE_CLAIMS);
    await page.evaluate(() => { S.widgets = true; S.pop = true; render(); });
    for (const sz of ['s', 'm', 'l']) {
      await page.evaluate((x) => { S.wgSize = x; render(); }, sz);
      const wt = await page.locator('#widgets').innerText();
      expect(wt, 'widgets ' + sz).not.toMatch(FALSE_CLAIMS);
      expect(wt, 'widgets ' + sz).not.toMatch(PROGRESS);
    }
    const pt = await page.locator('#pop').innerText();
    expect(pt).not.toMatch(FALSE_CLAIMS);
    expect(pt).not.toMatch(PROGRESS);
    expect(errors).toEqual([]);
  });
}
