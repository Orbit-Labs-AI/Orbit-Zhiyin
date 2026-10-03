// Orbit 人格素材：16 型协作人格之花、16 型总览图、画像页表盘（协作人格之花与轨道），浅色 / 深色，写出 kit/manifest.json。
// 只导出、不绘制：在构建好的 prototypes/advance/orbit-demo.html 里调用原型自己的 typeP()、bloom()、bloomParts() 与画像页
// （fp2SVG 画的表盘），把 CSS 变量解析成具体颜色。原型改了花或表盘，重新运行即可。
// 用法（仓库根目录，先 node prototypes/advance/build.mjs）：
//   node docs/design/persona/export.mjs                 写入 docs/design/persona/kit/
//   node docs/design/persona/export.mjs --out <dir>     写到别处（相对仓库根）
//   node docs/design/persona/export.mjs --check         导出到临时目录，与 kit/ 的 SVG 逐字比对；过期时列出并以 1 退出
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const kitDir = path.join(here, 'kit');
const args = process.argv.slice(2);
const opt = (key, fallback) => (args.includes(key) ? args[args.indexOf(key) + 1] : fallback);
const check = args.includes('--check');
const out = check ? await fs.mkdtemp(path.join(os.tmpdir(), 'orbit-persona-kit-')) : path.resolve(root, opt('--out', kitDir));

const THEMES = ['light', 'dark'];
// 花按画像页表盘里的尺寸取：半径 FPG.RR（页面里读），花心线宽 1.4；放在 180 × 180 的方形视框中央
const FLOWER_BOX = 180, FLOWER_HW = 1.4, FLOWER_PNG = [512, 128];
const DIAL_PX = 720, DIAL_SCALE = 2, SHEET_SCALE = 2;
// Chromium 不认 ui-rounded；macOS 上把系统自带的 SF Pro Rounded 以 --font-type 里的同名字体注册，类型码与 App（WebKit）一致
const ROUNDED = '/System/Library/Fonts/SFNSRounded.ttf';

try {
  execFileSync(process.execPath, [path.join(root, 'prototypes/advance/build.mjs'), '--check'], { cwd: root, stdio: 'pipe' });
} catch {
  console.error('prototypes/advance/orbit-demo.html 与 src/ 不一致：先运行 node prototypes/advance/build.mjs');
  process.exit(1);
}

const req = createRequire(import.meta.url);
let runtime;
if (process.env.PLAYWRIGHT_MODULE) runtime = req(process.env.PLAYWRIGHT_MODULE);
else {
  const project = createRequire(path.join(root, 'prototypes/advance/package.json'));
  runtime = createRequire(project.resolve('@playwright/test'))('playwright');
}
const { chromium } = runtime;
const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();

// ---- 页面内工具（注入到 window.__kit）----------------------------------------------------------------------------------
function installKit() {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const mk = (r, g, b, a) => ({ hex: '#' + [r, g, b].map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, '0')).join(''), a: +(+a).toFixed(3) });
  // 计算后的颜色 → { hex, a }：rgb() / color(srgb …) 直接读；oklab() 等（color-mix 的结果）去掉 alpha 后在 canvas 上量一个像素
  function color(v) {
    v = String(v).trim();
    if (!v || v === 'none') return null;
    if (v === 'transparent') return { hex: null, a: 0 };
    let m = v.match(/^rgba?\(([^)]+)\)$/);
    if (m) { const n = m[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat); return mk(n[0], n[1], n[2], n.length > 3 ? n[3] : 1); }
    m = v.match(/^color\(srgb\s+([^)]+)\)$/);
    if (m) { const n = m[1].split(/[\s/]+/).filter(Boolean).map(parseFloat); return mk(n[0] * 255, n[1] * 255, n[2] * 255, n.length > 3 ? n[3] : 1); }
    let a = 1; const al = v.match(/\s\/\s*([\d.]+)(%?)\s*\)$/);
    if (al) { a = al[2] ? parseFloat(al[1]) / 100 : parseFloat(al[1]); v = v.slice(0, al.index) + ')'; }
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#010203'; cx.fillStyle = v;
    if (cx.fillStyle === '#010203') throw new Error('无法解析的颜色 ' + v);
    cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data;
    return mk(d[0], d[1], d[2], a * d[3] / 255);
  }
  const token = (name) => { const c = color(getComputedStyle(document.documentElement).getPropertyValue(name)); if (!c || !c.hex) throw new Error('缺少颜色变量 ' + name); return c.hex; };
  const num = (v) => String(+parseFloat(v).toFixed(3));
  const NS = 'http://www.w3.org/2000/svg';

  // 一朵类型花：原型的 typeP() → bloom() → bloomParts()，颜色是具体值；返回 SVG 文本与内容外框
  function flower(code, c, box, hw) {
    const C = box / 2, g = bloom(typeP(code), C, FPG.RR), q = bloomParts(g, C, C, { ink: c.ink, gray: c.gray, lead: c.lead, bg: 'none', hw });
    const name = TYPES[code][0];
    const holder = document.createElement('div'); holder.style.cssText = 'position:fixed;left:-10000px;top:0';
    holder.innerHTML = '<svg xmlns="' + NS + '" width="' + box + '" height="' + box + '" viewBox="0 0 ' + box + ' ' + box + '" role="img" aria-label="' + code + ' ' + name + '之花"><title>' + code + ' ' + name + '</title><g>' + q.back + q.front + q.heart + '</g></svg>';
    document.body.appendChild(holder);
    const svg = holder.firstChild, wrap = svg.querySelector('g'), b = wrap.getBBox();
    wrap.replaceWith(...wrap.childNodes);
    svg.querySelectorAll('[class]').forEach((el) => el.removeAttribute('class'));
    const text = new XMLSerializer().serializeToString(svg); holder.remove();
    return { code, name, svg: text, bbox: [b.x, b.y, b.x + b.width, b.y + b.height] };
  }

  // 页面上的 SVG → 独立文件：计算样式写成属性（颜色转 hex，透明度并入 *-opacity），CSS 变换压成 matrix，pathLength 换成实际长度，
  // 去掉交互属性与看不见的热区，id 统一加前缀，视框扩成以圆心为中心、包住全部可见内容的正方形
  function exportSVG(svg, prefix) {
    const inDefs = (el) => el.closest('defs,mask,clipPath,pattern,linearGradient,radialGradient,marker,symbol');
    const INH = ['fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-opacity', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit', 'stroke-dasharray', 'stroke-dashoffset', 'paint-order', 'visibility'];
    const FONT = ['font-family', 'font-size', 'font-weight', 'font-style', 'letter-spacing', 'text-anchor', 'dominant-baseline'];
    const hasText = !!svg.querySelector('text'), props = hasText ? INH.concat(FONT) : INH;
    const INIT = { fill: '#000000', 'fill-opacity': '1', 'fill-rule': 'nonzero', stroke: 'none', 'stroke-opacity': '1', 'stroke-width': '1', 'stroke-linecap': 'butt', 'stroke-linejoin': 'miter', 'stroke-miterlimit': '4', 'stroke-dasharray': 'none', 'stroke-dashoffset': '0', 'paint-order': 'normal', visibility: 'visible', 'font-style': 'normal', 'letter-spacing': 'normal', 'text-anchor': 'start', 'dominant-baseline': 'auto' };
    const LEAF = new Set(['path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'text']);
    function eff(el) {
      const cs = getComputedStyle(el), o = {};
      for (const p of props) o[p] = cs.getPropertyValue(p).trim();
      for (const [p, po] of [['fill', 'fill-opacity'], ['stroke', 'stroke-opacity']]) {
        let op = parseFloat(o[po]); const u = o[p].match(/^url\(["']?[^"')]*#([^"')]+)["']?\)/);
        if (u) o[p] = 'url(#' + u[1] + ')';
        else { const c = color(o[p]); if (!c || !c.hex || c.a === 0) o[p] = 'none'; else { o[p] = c.hex; op *= c.a; } }
        o[po] = num(op);
      }
      for (const p of ['stroke-width', 'stroke-miterlimit', 'stroke-dashoffset', 'font-size']) if (o[p] != null) o[p] = num(o[p]);
      if (o['letter-spacing'] && o['letter-spacing'] !== 'normal') o['letter-spacing'] = num(o['letter-spacing']);
      // Chromium 把 BlinkMacSystemFont 算成带引号的 "system-ui"（一个并不存在的字体名），写回原名
      if (o['font-family']) o['font-family'] = o['font-family'].replace(/"system-ui"/g, 'BlinkMacSystemFont');
      if (o['stroke-dasharray'] !== 'none') o['stroke-dasharray'] = o['stroke-dasharray'].split(/[\s,]+/).filter(Boolean).map(num).join(' ');
      return o;
    }
    function local(el) {
      const cs = getComputedStyle(el); if (cs.transform === 'none') return null;
      let [ox, oy] = cs.transformOrigin.split(' ').map(parseFloat);
      if (cs.transformBox === 'fill-box' || cs.transformBox === 'content-box') { const b = el.getBBox(); ox += b.x; oy += b.y; }
      const L = new DOMMatrix().translate(ox, oy).multiply(new DOMMatrix(cs.transform)).translate(-ox, -oy);
      const P = el.parentElement.getScreenCTM(), Q = el.getScreenCTM();   // 与浏览器实际用的变换核对
      if (P && Q) { const k = P.inverse().multiply(Q); if (['a', 'b', 'c', 'd', 'e', 'f'].some((x) => Math.abs(k[x] - L[x]) > 0.02)) throw new Error('变换不一致：' + el.outerHTML.slice(0, 80)); }
      if (Math.abs(L.a - 1) + Math.abs(L.b) + Math.abs(L.c) + Math.abs(L.d - 1) + Math.abs(L.e) + Math.abs(L.f) < 1e-6) return null;
      return 'matrix(' + [L.a, L.b, L.c, L.d, L.e, L.f].map((v) => String(+v.toFixed(4))).join(' ') + ')';
    }
    const live = svg.getAnimations({ subtree: true }).filter((a) => a.playState !== 'finished');
    if (live.length) throw new Error('表盘仍有 ' + live.length + ' 个未结束的动画');
    const clone = svg.cloneNode(true), src = [svg, ...svg.querySelectorAll('*')], dst = [clone, ...clone.querySelectorAll('*')];
    const E = new Map(), drop = new Set(), visible = [];
    src.forEach((el, i) => {
      const d = dst[i], tag = el.localName;
      for (const a of [...d.attributes]) if (['class', 'style', 'tabindex'].includes(a.name) || a.name.startsWith('data-') || (i && (a.name === 'role' || a.name.startsWith('aria-')))) d.removeAttribute(a.name);
      if (tag === 'title' || tag === 'desc') return;
      const pe = i ? E.get(el.parentElement) : INIT; if (!pe) { drop.add(d); return; }
      const cs = getComputedStyle(el);
      if (i && !inDefs(el) && cs.display === 'none') { drop.add(d); return; }
      const e = eff(el); E.set(el, e);
      for (const p of props) { if (!i && ['font-family', 'font-size', 'font-weight'].includes(p)) { d.setAttribute(p, e[p]); continue; } if (e[p] !== pe[p]) d.setAttribute(p, e[p]); else d.removeAttribute(p); }
      if (tag === 'stop') { const c = color(cs.stopColor); d.setAttribute('stop-color', c.hex); const so = num(parseFloat(cs.stopOpacity) * c.a); if (so !== '1') d.setAttribute('stop-opacity', so); else d.removeAttribute('stop-opacity'); }
      const op = num(cs.opacity); if (op !== '1') d.setAttribute('opacity', op); else d.removeAttribute('opacity');
      if (cs.vectorEffect && cs.vectorEffect !== 'none') d.setAttribute('vector-effect', cs.vectorEffect);
      // pathLength 只有浏览器认得准：一段虚线就覆盖全长时写成实线，否则按实际长度换算
      if (el.hasAttribute('pathLength') && e['stroke-dasharray'] !== 'none') {
        const pl = parseFloat(el.getAttribute('pathLength')), dash = e['stroke-dasharray'].split(' ').map(Number), off = +e['stroke-dashoffset'];
        if (off === 0 && dash[0] >= pl) Object.assign(e, { 'stroke-dasharray': 'none', 'stroke-dashoffset': '0' });
        else { const k = el.getTotalLength() / pl; Object.assign(e, { 'stroke-dasharray': dash.map((v) => num(v * k)).join(' '), 'stroke-dashoffset': num(off * k) }); }
        for (const p of ['stroke-dasharray', 'stroke-dashoffset']) { if (e[p] !== pe[p]) d.setAttribute(p, e[p]); else d.removeAttribute(p); }
        d.removeAttribute('pathLength');
      }
      if (i && !inDefs(el)) {
        const m = local(el); if (m) d.setAttribute('transform', m); else d.removeAttribute('transform');
        if (LEAF.has(tag)) { if (e.fill === 'none' && e.stroke === 'none' && tag !== 'text') drop.add(d); else visible.push(el); }
      }
    });
    drop.forEach((d) => d.remove());
    for (let more = true; more;) { more = false; clone.querySelectorAll('g').forEach((g) => { if (!g.firstElementChild) { g.remove(); more = true; } }); }
    // id 加前缀（同一页面内联多张也不冲突），引用跟着改
    const ids = new Map(); clone.querySelectorAll('[id]').forEach((el, i) => { ids.set(el.id, prefix + '-' + (i + 1)); el.id = prefix + '-' + (i + 1); });
    const ref = (v) => v.replace(/url\(#([^)]+)\)/g, (s, id) => 'url(#' + (ids.get(id) || id) + ')');
    clone.querySelectorAll('*').forEach((el) => {
      for (const a of ['mask', 'clip-path', 'fill', 'stroke', 'filter']) if (el.hasAttribute(a)) el.setAttribute(a, ref(el.getAttribute(a)));
      for (const a of ['href', 'xlink:href']) { const v = el.getAttribute(a); if (v && v[0] === '#') el.setAttribute(a, '#' + (ids.get(v.slice(1)) || v.slice(1))); }
    });
    // 视框：以原视框中心为中心，包住全部可见图形（另留 3 个单位给描边）
    const vb = svg.viewBox.baseVal, cx0 = vb.x + vb.width / 2, cy0 = vb.y + vb.height / 2, inv = svg.getScreenCTM().inverse();
    let half = Math.max(vb.width, vb.height) / 2;
    for (const el of visible) {
      const r = el.getBoundingClientRect(); if (!r.width && !r.height) continue;
      for (const [x, y] of [[r.left, r.top], [r.right, r.top], [r.left, r.bottom], [r.right, r.bottom]]) { const q = new DOMPoint(x, y).matrixTransform(inv); half = Math.max(half, Math.abs(q.x - cx0) + 3, Math.abs(q.y - cy0) + 3); }
    }
    half = Math.ceil(half);
    clone.setAttribute('viewBox', (cx0 - half) + ' ' + (cy0 - half) + ' ' + 2 * half + ' ' + 2 * half);
    clone.setAttribute('width', String(2 * half)); clone.setAttribute('height', String(2 * half));
    let text = new XMLSerializer().serializeToString(clone);
    if (!text.startsWith('<svg xmlns="' + NS + '"')) text = text.replace('<svg', '<svg xmlns="' + NS + '"');
    if (/var\(|color-mix|oklab|oklch/.test(text)) throw new Error('导出的 SVG 仍含未解析的 CSS 颜色');
    return { svg: text, size: 2 * half };
  }

  // 16 型总览：4 × 4，花 + 类型码（.tcode，与 App 同一字体）+ 中文名，铺在 App 纸面（--bg）上
  function sheet(items) {
    document.getElementById('kit-sheet')?.remove();
    const el = document.createElement('div'); el.id = 'kit-sheet';
    el.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;display:grid;grid-template-columns:repeat(4,200px);gap:30px 24px;padding:52px 56px 48px;background:var(--bg);color:var(--ink-1);font-family:var(--font-sans)';
    el.innerHTML = items.map((x) => '<div style="display:flex;flex-direction:column;align-items:center">' + x.svg.replace(/ width="\d+" height="\d+"/, ' width="148" height="148"') +
      '<b class="tcode" style="margin-top:12px;font-size:22px;line-height:28px;letter-spacing:.04em">' + x.code + '</b><span style="margin-top:2px;font-size:14px;line-height:20px;color:var(--ink-2)">' + x.name + '</span></div>').join('');
    document.body.appendChild(el);
  }
  window.__kit = { color, token, flower, exportSVG, sheet };
}

// ---- 浏览器 ---------------------------------------------------------------------------------------------------------
const files = [], errors = [], colors = {};
const write = async (name, data, info) => {
  const f = path.join(out, name); await fs.mkdir(path.dirname(f), { recursive: true }); await fs.writeFile(f, data);
  files.push({ file: name, ...info, bytes: Buffer.byteLength(data) });
};
const pngSize = (buf) => [buf.readUInt32BE(16), buf.readUInt32BE(20)];
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
const ctx = async (o) => {
  const c = await browser.newContext({ locale: 'zh-CN', timezoneId: 'Asia/Shanghai', ...o });
  await c.route(/^https?:\/\/fonts\.(googleapis|gstatic)\.com\//, (r) => r.abort());
  return c;
};
async function settle(page, timeout = 8000) {
  await page.evaluate(async (timeout) => {
    await document.fonts.ready;
    const t0 = performance.now(), finite = (a) => Number.isFinite(a.effect?.getComputedTiming().endTime);
    while (performance.now() - t0 < timeout && document.getAnimations().some((a) => a.playState === 'running' && finite(a))) await new Promise((r) => setTimeout(r, 100));
    for (const a of document.getAnimations()) { if (finite(a)) { try { a.finish(); } catch {} } else a.pause(); }
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }, timeout);
}
async function raster(page, svg, px, clip) {
  await page.setViewportSize({ width: Math.max(px, 64), height: Math.max(px, 64) });
  await page.setContent('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;background:transparent}svg{display:block;width:' + px + 'px;height:' + px + 'px}</style>' + svg);
  await page.evaluate(() => document.fonts.ready);
  return page.screenshot({ omitBackground: true, clip: clip || { x: 0, y: 0, width: px, height: px } });
}

try {
  const app = await ctx({ viewport: { width: 1720, height: 1200 }, deviceScaleFactor: SHEET_SCALE, reducedMotion: 'no-preference' });
  const page = await app.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
    document.startViewTransition = undefined;
  });
  await page.goto(pathToFileURL(path.join(root, 'prototypes/advance/orbit-demo.html')).href);
  await page.waitForFunction(() => typeof bloom === 'function' && typeof bloomParts === 'function' && typeof typeP === 'function' && typeof fp2SVG === 'function');
  if (await page.evaluate(() => LV.live)) throw new Error('需要示例数据模式（LV.live 应为 false）');
  await page.addStyleTag({ content: '#notes,#tip,#toast{display:none!important}' });
  await page.evaluate(installKit);
  const rounded = await fs.readFile(ROUNDED).catch(() => null);
  if (rounded) {
    await page.evaluate(async (b64) => {
      const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const face = new FontFace('SF Pro Rounded', bin.buffer, { weight: '1 1000' }); await face.load(); document.fonts.add(face);
    }, rounded.toString('base64'));
  } else console.warn('未找到 SF Pro Rounded（' + ROUNDED + '）：总览图的类型码会退回系统无衬线字体');
  const codes = await page.evaluate(() => Object.keys(TYPES));
  if (codes.length !== 16) throw new Error('TYPES 应有 16 型，实际 ' + codes.length);

  const r1 = await (await ctx({ deviceScaleFactor: 1 })).newPage();
  const r2 = await (await ctx({ deviceScaleFactor: DIAL_SCALE })).newPage();
  const flowers = {};

  for (const theme of THEMES) {
    await page.evaluate((theme) => {
      closeOverlay(); closeModal(); closeDD(); closeSettings();
      S.ed = 'advance'; document.querySelector('#win').dataset.ed = 'advance';
      S.win = { x: 80, y: 60, w: 1440, h: 1040, zoom: false, full: false };
      S.hud.show = false; S.widgets = false; S.pop = false; S.persona.fpType = null;
      store.set('guideOff', true); setTheme(theme); go('overview');
    }, theme);
    await settle(page);
    const c = await page.evaluate(() => ({ ink: __kit.token('--ink-1'), ink2: __kit.token('--ink-2'), gray: __kit.token('--h2'), lead: __kit.token('--orbit'), bg: __kit.token('--bg') }));
    colors[theme] = c;

    // 16 型花：两色（墨色 + 浅灰）+ 领瓣（--orbit），透明底；PNG 是同一 SVG 的整体缩放
    const list = await page.evaluate(({ codes, c, box, hw }) => codes.map((k) => __kit.flower(k, c, box, hw)), { codes, c, box: FLOWER_BOX, hw: FLOWER_HW });
    for (const f of list) {
      if (f.bbox[0] < 1 || f.bbox[1] < 1 || f.bbox[2] > FLOWER_BOX - 1 || f.bbox[3] > FLOWER_BOX - 1) throw new Error(f.code + ' 超出画布：' + f.bbox.map((v) => v.toFixed(1)).join(' '));
      const svg = f.svg + '\n';
      await write(`flowers/svg/${f.code}-${theme}.svg`, svg, { kind: 'flower', code: f.code, name: f.name, theme, format: 'svg', width: FLOWER_BOX, height: FLOWER_BOX });
      for (const px of FLOWER_PNG) {
        const png = await raster(r1, svg, px);
        await write(`flowers/png/${f.code}-${theme}-${px}.png`, png, { kind: 'flower', code: f.code, name: f.name, theme, format: 'png', width: px, height: px });
      }
    }
    flowers[theme] = list;

    // 16 型总览图（App 纸面 / 深色底）
    await page.evaluate((items) => __kit.sheet(items), list.map((f) => ({ code: f.code, name: f.name, svg: f.svg })));
    await settle(page);
    if (rounded && !(await page.evaluate(() => document.fonts.check('700 22px "SF Pro Rounded"')))) throw new Error('SF Pro Rounded 未生效');
    const sheetPng = await page.locator('#kit-sheet').screenshot({ animations: 'disabled' });
    await page.evaluate(() => document.getElementById('kit-sheet').remove());
    const [sw, sh] = pngSize(sheetPng);
    await write(`sheet/types-${theme}.png`, sheetPng, { kind: 'sheet', theme, format: 'png', width: sw, height: sh });

    // 画像页表盘：进入画像页，等入场动画（花的晃动、轨道扫开、徽章归位）结束后导出 .pe-fpc > svg
    await page.evaluate(() => go('persona'));
    await settle(page);
    const dial = page.locator('.pe-fpc > svg');
    if (await dial.count() !== 1) throw new Error('画像页应有且只有一个 .pe-fpc > svg');
    const d = await dial.evaluate((el, prefix) => __kit.exportSVG(el, prefix), 'orbit-dial-' + theme);
    const dsvg = d.svg + '\n';
    await write(`dial/dial-${theme}.svg`, dsvg, { kind: 'dial', theme, format: 'svg', width: d.size, height: d.size, data: 'demo' });
    const dpng = await raster(r2, dsvg, DIAL_PX);
    await write(`dial/dial-${theme}.png`, dpng, { kind: 'dial', theme, format: 'png', width: DIAL_PX * DIAL_SCALE, height: DIAL_PX * DIAL_SCALE, data: 'demo' });
    console.log(`${theme}: 16 flowers, sheet, dial`);
  }

  // 单色墨稿：所有花瓣与花心同一种颜色（浅色主题的 --ink-1），透明底，供印刷、描摹或改色
  const ink = colors.light.ink;
  const inkList = await page.evaluate(({ codes, ink, box, hw }) => codes.map((k) => __kit.flower(k, { ink, gray: ink, lead: ink }, box, hw)), { codes, ink, box: FLOWER_BOX, hw: FLOWER_HW });
  for (const f of inkList) await write(`flowers/svg/${f.code}-ink.svg`, f.svg + '\n', { kind: 'flower', code: f.code, name: f.name, theme: 'ink', format: 'svg', width: FLOWER_BOX, height: FLOWER_BOX });

  if (errors.length) throw new Error('页面脚本出错：\n' + errors.join('\n'));
  files.sort((a, b) => a.file.localeCompare(b.file, 'en', { numeric: true }));
  await fs.writeFile(path.join(out, 'manifest.json'), JSON.stringify({
    product: 'Orbit', generator: 'docs/design/persona/export.mjs', sourceCommit,
    source: 'prototypes/advance/orbit-demo.html（花：src/js/35-visuals.js；表盘：src/js/41-a2-persona.js；类型名：src/js/05-data.js）',
    base: 'docs/design/persona/kit/（file 相对此目录）',
    data: '表盘为 Demo 示例数据（画像页默认「近 90 天」），不代表真实统计',
    colors,
    files,
  }, null, 2) + '\n');
  console.log(`persona kit: ${files.length} files → ${out.startsWith(root + path.sep) ? path.relative(root, out) : out}`);
} finally {
  await browser.close();
}

// ---- --check：与 kit/ 的 SVG 逐字比对 ------------------------------------------------------------------------------------
if (check) {
  const walk = async (dir) => (await fs.readdir(dir, { recursive: true }).catch(() => [])).filter((f) => f.endsWith('.svg')).map((f) => f.split(path.sep).join('/')).sort();
  const [had, now] = [await walk(kitDir), await walk(out)];
  const stale = [];
  for (const f of new Set([...had, ...now])) {
    if (!had.includes(f)) stale.push('缺少 ' + f);
    else if (!now.includes(f)) stale.push('多余 ' + f);
    else if (await fs.readFile(path.join(kitDir, f), 'utf8') !== await fs.readFile(path.join(out, f), 'utf8')) stale.push('过期 ' + f);
  }
  const manifest = JSON.parse(await fs.readFile(path.join(kitDir, 'manifest.json'), 'utf8').catch(() => '{"files":[]}'));
  for (const item of manifest.files) if (!(await fs.stat(path.join(kitDir, item.file)).catch(() => null))) stale.push('缺少 ' + item.file);
  await fs.rm(out, { recursive: true, force: true });
  if (stale.length) {
    console.error('人格素材与原型不一致（运行 node docs/design/persona/export.mjs 重新导出）：\n  ' + stale.sort().join('\n  '));
    process.exit(1);
  }
  console.log('persona kit is up to date');
}
