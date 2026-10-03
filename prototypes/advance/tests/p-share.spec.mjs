// 分享卡（src/js/55-exports.js）：每个时间长度一张卡，卡上的人格就是该窗口算出的人格；预览（SVG）与 PNG 共用一份绘制指令。
// 流程（mac-14，示例数据）：
//   1. openShare() 列出 近 7 / 30 / 90 天与全部；点每一行，预览换成那个窗口的类型码与标签（周卡 / 月卡 / 季卡 / 全时卡）；
//      Lite 的「导出分享卡」打开同一个弹窗
//   2. sharePNG 是 1080 × 1350，画出的文字与 SVG 预览完全相同；页眉是 Orbit·知音 字标，类型码用 --font-type
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

test.beforeEach(({}, info) => test.skip(info.project.name !== 'mac-14', 'runs once, at the default size'));

test('one card per time span, each from its own window', async ({ page }) => {
  const errors = await openDemo(page);
  await go(page, 'persona');
  await page.evaluate(() => openShare());
  const truth = await page.evaluate(() => shareSpans().map((k) => [k, persona(sel({ win: spanWin(k), noExtra: true })).code]));
  expect(truth.map((t) => t[0])).toEqual(['7', '30', '90', 'all']);
  for (const [k, code] of truth) {
    await page.locator('#modal [data-act="shareSpan"][data-v="' + k + '"]').click();
    await expect(page.locator('#modal .sharecard svg')).toHaveAttribute('data-code', code);
    await expect(page.locator('#modal .sharecard')).toContainText({ '7': '周卡', '30': '月卡', '90': '季卡', all: '全时卡' }[k]);
  }
  await page.evaluate(() => { closeModal(); S.ed = 'lite'; $('#win').dataset.ed = 'lite'; go('l-persona'); });
  await page.locator('#main [data-act="share"]').first().click();
  await expect(page.locator('#modal [data-act="shareSpan"]')).toHaveCount(4);
  expect(errors).toEqual([]);
});

test('the PNG draws what the preview shows', async ({ page }) => {
  const errors = await openDemo(page);
  const r = await page.evaluate(async () => {
    const out = []; const f = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (t, ...a) { out.push(String(t)); return f.call(this, t, ...a); };
    const sp = sharePersona('30'); let b64;
    try { b64 = await sharePNG(shareModel(sp), S.shareDark, false); } finally { CanvasRenderingContext2D.prototype.fillText = f; }
    const img = new Image(); await new Promise((ok) => { img.onload = ok; img.src = 'data:image/png;base64,' + b64; });
    const d = document.createElement('div'); d.innerHTML = shareCard(sp);
    return { png: out, svg: Array.from(d.querySelectorAll('text')).map((t) => t.textContent), size: [img.width, img.height],
      wordmark: !!d.querySelector('[data-wordmark]'), type: d.querySelector('text.tcode').getAttribute('style') };
  });
  expect(r.size).toEqual([1080, 1350]);
  expect(r.png).toEqual(r.svg);
  expect(r.wordmark).toBe(true);
  expect(r.type).toMatch(/ui-rounded/);
  expect(errors).toEqual([]);
});
