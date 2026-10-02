// J02 against a real synthetic gateway (skipped unless LIVE_GATEWAY / TANDEM_TOKEN / FX_USERHOME are set):
//   FX_BE=<worktree> .work/release/fx-start.sh <home>  → LIVE_GATEWAY=http://127.0.0.1:<port> TANDEM_TOKEN=<token>
//   FX_USERHOME=<home>.userhome (the gateway's redirected HOME). Synthetic data only (fx-seed.py on fx-src).
// A8 card → detail panel; a kb catalog item goes plan → preview → apply, every written file lands inside FX_USERHOME;
// 撤销 reverts it from the ledger and restores the redirected HOME. A7 kb candidate: plan answer shown honestly.
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '@playwright/test';
import { stubGateway, openLive, PASS } from './live-helpers.mjs';

const UH = process.env.FX_USERHOME ? path.resolve(process.env.FX_USERHOME) : null;
const KB_ITEM = process.env.FX_KB_ITEM || 'kb:stop-verify-hook';
// the shared pass-through proxy forwards the page's Origin (http://tandem.test), which the gateway refuses on writes;
// writes here go to the gateway as a same-origin client would send them (no Origin header)
async function passWrites(page) {
  await page.route(/^http:\/\/tandem\.test\/v1\//, async (route) => {
    const req = route.request(); if (req.method() === 'GET') return route.fallback();
    const u = new URL(req.url()); const h = Object.assign({}, req.headers(), { authorization: 'Bearer ' + process.env.TANDEM_TOKEN }); delete h.origin; delete h.referer;
    return route.fulfill({ response: await route.fetch({ url: PASS + u.pathname + u.search, headers: h }) });
  });
}
function snap(dir) {
  const out = {};
  const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else out[path.relative(dir, p)] = fs.readFileSync(p, 'utf8'); } };
  if (fs.existsSync(dir)) walk(dir);
  return out;
}

test.beforeEach(async ({ page }) => {
  test.skip(!PASS || !UH || test.info().project.name !== 'mac-14', 'needs LIVE_GATEWAY + FX_USERHOME (synthetic gateway)');
  await page.emulateMedia({ reducedMotion: 'reduce' });
});
test.afterEach(async ({ page }) => { await page.unrouteAll({ behavior: 'ignoreErrors' }); });

test('real gateway: A8 card opens the detail panel; kb item plan → preview → apply writes only inside the redirected HOME; 撤销 restores it', async ({ page }) => {
  await stubGateway(page, []); await passWrites(page);
  const applied = [];
  page.on('response', async (r) => { if (/\/v1\/install\/apply$/.test(new URL(r.url()).pathname) && r.status() === 200) applied.push(await r.json()); });
  const before = snap(path.join(UH, '.claude'));
  await openLive(page, 'library');
  const card = page.locator('#content [data-act="liDetail"]').first();
  await expect(card).toBeVisible({ timeout: 20000 });
  await card.click();
  await expect(page.locator('#modal [data-tl="lib-detail"]')).toBeVisible();
  await page.locator('#modal [data-act="closeModal"]').first().click();
  // the kb item's own detail → 获取
  await page.evaluate((id) => ACT.liDetail({ dataset: { id } }), KB_ITEM);
  const get = page.locator('#modal [data-act="getLib"]');
  await expect(get).toBeEnabled({ timeout: 20000 });
  await get.click();
  await expect(page.locator('#modal [data-tl="inst-preview"]')).toBeVisible({ timeout: 20000 });
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instNext"]').click();
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instDo"]').click();
  await expect(page.locator('#modal [data-tl="inst-done"]')).toBeVisible({ timeout: 20000 });
  expect(applied.length).toBe(1);
  const written = (applied[0].written || []).map((w) => path.resolve(w.path));
  expect(written.length).toBeGreaterThan(0);
  for (const w of written) expect(w.startsWith(UH + path.sep)).toBe(true);
  for (const w of written) expect(fs.existsSync(w)).toBe(true);
  expect(snap(path.join(UH, '.claude'))).not.toEqual(before);
  // 撤销 → POST /v1/install/{id}/revert; the redirected HOME is back to what it was
  await page.waitForTimeout(450);
  await page.locator('#modal [data-act="instUndo"]').click();
  await expect.poll(() => JSON.stringify(snap(path.join(UH, '.claude'))), { timeout: 15000 }).toBe(JSON.stringify(before));
});

test('real gateway: A7 kb candidate install answers with the plan (ready → preview, otherwise the reason), never /v1/install/fetch', async ({ page }) => {
  const gw = await stubGateway(page, []); await passWrites(page);
  await openLive(page, 'recs');
  const kb = page.locator('#content .rcard').first();
  await expect(kb).toBeVisible({ timeout: 20000 });
  await kb.locator(".rc-title").click();   // not the 依据 link, which opens the sessions page
  await page.locator('#content .rc-dfoot [data-act="install"]').click();
  await expect(page.locator('#modal [data-tl="inst-preview"], #modal [data-tl="inst-manual"], #modal [data-tl="inst-error"]')).toBeVisible({ timeout: 20000 });
  if (await page.locator('#modal [data-tl="inst-manual"]').count()) await expect(page.locator('#modal [data-tl="inst-reason"]')).not.toBeEmpty();
  expect(gw.count('/v1/install/fetch')).toBe(0);
});
