// Round 3 (change 1): click through A1..A6, Lite and the palette against a REAL synthetic gateway and assert that no
// /v1 request is rejected as invalid (422 = an undeclared query parameter such as agent / weekday / hour / q on
// /v1/analytics/*). Skipped without LIVE_GATEWAY + ORBIT_TOKEN (fixture runs cover the rendering).
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, PASS } from './live-helpers.mjs';

test('real gateway: A1..A6, Lite and palette send only declared params (no 422)', async ({ page }) => {
  test.skip(!PASS, 'needs LIVE_GATEWAY');
  test.setTimeout(120_000);
  const bad = [];
  page.on('response', (r) => { const u = new URL(r.url()); if (u.pathname.startsWith('/v1/') && (r.status() === 422 || r.status() === 400)) bad.push(r.status() + ' ' + u.pathname + u.search); });
  const gw = await stubGateway(page, []);
  await openLive(page, 'overview');
  const go = async (route) => { await page.evaluate((r) => go(r), route); await page.waitForTimeout(1200); };
  for (const r of ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment']) await go(r);
  // A4: open the first tool row (tool_calls drill-down) and toggle 仅看失败
  await go('tools');
  const row = page.locator('#main tr.click').first();
  if (await row.count()) { await row.click(); await page.waitForTimeout(800); await page.locator('#main [data-act="failOnly"]').click(); await page.waitForTimeout(800); }
  // agent scope on analytics-backed pages
  await page.evaluate(() => { const a = AG.find((x) => x.all > 0) || AG[0]; if (a) { S.agents = new Set([a.id]); render(); } });
  for (const r of ['overview', 'persona', 'tools', 'projects', 'sentiment', 'sessions']) await go(r);
  // A3: open a session
  await page.evaluate(() => { const s = ALL.find((x) => !x.live); if (s) { S.sess.sel = s.id; go('sessions'); } });
  await page.waitForTimeout(1200);
  // Lite
  await page.evaluate(() => { S.agents = new Set(AG.map((a) => a.id)); go('overview'); });
  await page.evaluate(() => typeof edSet === 'function' && edSet('lite'));
  await page.waitForTimeout(1500);
  await page.evaluate(() => typeof edSet === 'function' && edSet('advance'));
  // palette
  await page.evaluate(() => openPalette());
  await page.fill('#palQ', 'test');
  await page.waitForTimeout(1500);
  console.log('[r3] /v1 paths: ' + [...new Set(gw.seen.filter((x) => x.path.startsWith('/v1/')).map((x) => x.path.replace(/session_[^/]+/, ':uid')))].sort().join(' '));
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  expect(bad).toEqual([]);
});
