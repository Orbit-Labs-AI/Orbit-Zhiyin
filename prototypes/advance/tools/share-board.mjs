// Writes docs/design/visual-cases-v1/ShareCard.dc.html (P2 分享卡画板) from the demo's own shareSVG(): the board shows the
// same drawing the App previews and saves as PNG. Rerun after the share card changes:
//   node build.mjs && node tools/share-board.mjs
import { webkit } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
const b = await webkit.launch(); const page = await b.newPage({ viewport: { width: 1512, height: 982 } });
await page.goto('file://' + path.join(here, '..', 'tandem-demo.html')); await page.waitForTimeout(1200);
const r = await page.evaluate(() => {
  const sp = sharePersona('30'); const m = shareModel(sp);
  return { dark: shareSVG(m, true, false), light: shareSVG(m, false, false), code: m.code, zh: m.zh };
});
const out = path.join(here, '..', '..', '..', 'docs', 'design', 'visual-cases-v1', 'ShareCard.dc.html');
const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>P2 人格分享卡</title>
<script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
<style>
body{margin:0}
/* 2026-10-03 版：由 prototypes/advance 的 shareSVG()（src/js/55-exports.js）生成，与 App 预览和 1080×1350 PNG 同一份绘制指令。
   字体全用系统字体（类型码 SF Pro Rounded、其余 SF Pro + PingFang SC），页眉是 Orbit·知音 正式字标。示例：近 30 天 · 月卡。 */
.sc{width:1080px;height:1350px;overflow:hidden;-webkit-font-smoothing:antialiased}
.sc svg{display:block;width:1080px;height:1350px}
.sc .lt-only{display:none}
.sc.lt .lt-only{display:block}
.sc.lt .dk-only{display:none}
</style>
</helmet>
<div class="sc {{ theme }}">
<div class="dk-only">${r.dark}</div>
<div class="lt-only">${r.light}</div>
</div>
</x-dc>
<script type="text/x-dc" data-dc-script data-props='{"light":{"editor":"boolean","default":false,"section":"外观"},"$preview":{"width":1080,"height":1350}}'>
class Component extends DCLogic {
  renderVals() {
    const light = this.props.light ?? false;
    return { theme: light ? 'lt' : '' };
  }
}
</script>
</body>
</html>
`;
fs.writeFileSync(out, html);
console.log('board ->', path.relative(process.cwd(), out), r.code, r.zh);
await b.close();
