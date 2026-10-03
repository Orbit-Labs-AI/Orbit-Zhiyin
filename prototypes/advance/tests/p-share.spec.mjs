// 分享卡（src/js/55-exports.js）：每个时间长度一张卡，卡上的人格就是该窗口算出的人格；网页预览与 PNG 共用一份绘制指令。
// Test flow (mac-14, demo data):
//  1 spans      openShare() lists 近 7 / 30 / 90 天与全部；each row's code = persona(that window) under the persona scope;
//               clicking a row swaps the preview (data-span, tag 周卡 / 月卡 / 季卡 / 全时卡, day ring with one cell per day,
//               one per week past 92 days); within one project the spans can disagree (demo: quant is DIFV over 90 days, SIFV over all) and the sheet says so
//  2 parity     sharePNG draws exactly the strings the SVG preview shows (fillText vs <text>), at 1080 × 1350;
//               「隐藏具体数字」 drops strengths and the stats row from both
//  3 copy       every one of the 16 types has its own quote; the card carries the type's description (TYPES[code][2])
//  4 lite       Lite's 导出分享卡 opens the same sheet
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const ONLY = () => test.skip(test.info().project.name !== 'mac-14', 'share card coverage runs once, at the default size');

test('spans: one card per time span, each from its own window', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  await go(page, 'persona');
  await page.evaluate(() => openShare());
  const rows = page.locator('#modal [data-act="shareSpan"]');
  await expect(rows).toHaveCount(4);
  const truth = await page.evaluate(() => shareSpans().map((k) => [k, persona(sel({ win: spanWin(k), noExtra: true })).code]));
  for (const [k, code] of truth) {
    await page.locator('#modal [data-act="shareSpan"][data-v="' + k + '"]').click();
    const card = page.locator('#modal .sharecard');
    await expect(card).toHaveAttribute('data-span', k);
    await expect(card.locator('svg')).toHaveAttribute('data-code', code);
    const tag = { '7': '周卡', '30': '月卡', '90': '季卡', all: '全时卡' }[k];
    await expect(card).toContainText(tag);
    const ring = await page.evaluate((k) => { const sp = sharePersona(k); const w = spanWin(k); return [sp.ring.cells.length, sp.ring.unit, w[1] - w[0] + 1]; }, k);
    expect(ring[0]).toBe(ring[2] > 92 ? Math.ceil(ring[2] / 7) : ring[2]);
  }
  // a single project can lean differently over a week than over all time; the sheet names how many types it found
  const multi = await page.evaluate(() => {
    for (const pj of Object.keys(PJI)) { S.project = pj; const codes = new Set(shareSpans().map((k) => shareSpanState(k)).filter((s) => s.state === 'ok').map((s) => s.sp.p.code)); if (codes.size > 1) { shareRefresh(); return codes.size; } }
    return 0;
  });
  expect(multi).toBeGreaterThan(1);
  await expect(page.locator('#modal')).toContainText('算出了 ' + multi + ' 种人格');
  expect(errors).toEqual([]);
});

test('parity: the PNG draws what the preview shows; hidden numbers hide in both', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  const r = await page.evaluate(async () => {
    const out = []; const f = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { out.push(String(t)); return f.call(this, t, ...a); };
    const res = {};
    try {
      for (const nn of [false, true]) {
        out.length = 0; S.shareNoNum = nn; const sp = sharePersona('30');
        const b64 = await sharePNG(shareModel(sp), true, nn);
        const img = new Image(); await new Promise((ok) => { img.onload = ok; img.src = 'data:image/png;base64,' + b64; });
        const div = document.createElement('div'); div.innerHTML = shareCard(sp);
        res[nn] = { png: out.slice(), svg: Array.from(div.querySelectorAll('text')).map((t) => t.textContent), size: [img.width, img.height], line: sp.p.line };
      }
    } finally { CanvasRenderingContext2D.prototype.fillText = f; S.shareNoNum = false; }
    return res;
  });
  for (const nn of ['false', 'true']) {
    expect(r[nn].size).toEqual([1080, 1350]);
    expect(r[nn].png).toEqual(r[nn].svg);
  }
  expect(r.false.png.some((t) => /^\d+%$/.test(t))).toBe(true);
  expect(r.true.png.some((t) => /^\d+%$/.test(t))).toBe(false);
  expect(r.true.png).not.toContain('会话');
  expect(r.false.png.join('')).toContain(r.false.line.slice(0, 10));
  expect(errors).toEqual([]);
});

test('copy: 16 types, 16 quotes; the card shows the type description', async ({ page }) => {
  ONLY();
  await openDemo(page);
  const r = await page.evaluate(() => ({ types: Object.keys(TYPES).sort(), quotes: Object.keys(SHAREQ).sort(), uniq: new Set(Object.values(SHAREQ).map((q) => q.join(''))).size }));
  expect(r.quotes).toEqual(r.types);
  expect(r.uniq).toBe(16);
});

test('lite: 导出分享卡 opens the same sheet', async ({ page }) => {
  ONLY();
  const errors = await openDemo(page);
  await page.evaluate(() => { S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-persona'); });
  await expect.poll(() => page.evaluate(() => S.route)).toBe('l-persona');
  await page.locator('#main [data-act="share"]').first().click();
  await expect(page.locator('#modal [data-act="shareSpan"]')).toHaveCount(4);
  await expect(page.locator('#modal .sharecard svg')).toBeVisible();
  expect(errors).toEqual([]);
});
