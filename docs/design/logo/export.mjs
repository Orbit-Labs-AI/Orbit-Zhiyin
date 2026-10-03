// 由 generate.py 写出的 SVG 渲染全部位图素材（PNG、ICO、ICNS），并写出 kit/manifest.json。
// 只渲染、不绘制：每张位图都是某个母版 SVG 的整体缩放，所以标志与 App 图标完全等比。
// 用法（仓库根目录，先运行 generate.py）：node docs/design/logo/export.mjs
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..', '..');
const kit = path.join(here, 'kit');
const project = createRequire(path.join(root, 'prototypes/advance/package.json'));
const { chromium } = createRequire(project.resolve('@playwright/test'))('playwright');

const ICON_SIZES = [16, 32, 48, 64, 128, 256, 512, 1024];
const DOCK_SIZES = [128, 256, 512, 1024];
const MARK_HEIGHTS = [64, 128, 256, 512, 1024];
// 菜单栏与导航栏：标志高度（pt），每个尺寸出 @1x/@2x/@3x
const NAV_HEIGHTS = [16, 18, 20, 22, 24, 32];
// ICNS 条目：类型 → 像素边长（macOS 10.8+ 的 PNG 条目）
const ICNS = [['icp4', 16], ['icp5', 32], ['ic11', 32], ['ic12', 64], ['ic07', 128], ['ic13', 256], ['ic08', 256], ['ic14', 512], ['ic09', 512], ['ic10', 1024]];

const rel = p => path.relative(kit, p).split(path.sep).join('/');
const box = svg => svg.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });
const manifest = [];

async function render(src, out, w, h, note) {
  const svg = (await fs.readFile(path.join(here, src), 'utf8')).replace(/ width="[^"]*" height="[^"]*"/, ' width="100%" height="100%" preserveAspectRatio="none"');
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<!doctype html><style>html,body{margin:0;background:transparent}svg{display:block;width:${w}px;height:${h}px}</style>${svg}`);
  const png = await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: w, height: h } });
  const file = path.join(kit, out);
  await fs.mkdir(path.dirname(file), { recursive: true });
  await fs.writeFile(file, png);
  manifest.push({ file: rel(file), source: src, width: w, height: h, ...(note ? { use: note } : {}) });
  return png;
}

function ico(images) { // [{size, png}] → ICO（PNG 条目）
  const head = Buffer.alloc(6 + 16 * images.length);
  head.writeUInt16LE(0, 0); head.writeUInt16LE(1, 2); head.writeUInt16LE(images.length, 4);
  let offset = head.length;
  images.forEach(({ size, png }, i) => {
    const o = 6 + 16 * i;
    head.writeUInt8(size % 256, o); head.writeUInt8(size % 256, o + 1);
    head.writeUInt16LE(1, o + 4); head.writeUInt16LE(32, o + 6);
    head.writeUInt32LE(png.length, o + 8); head.writeUInt32LE(offset, o + 12);
    offset += png.length;
  });
  return Buffer.concat([head, ...images.map(x => x.png)]);
}

function icns(bySize) { // {px: png} → ICNS
  const chunks = ICNS.map(([type, px]) => {
    const h = Buffer.alloc(8);
    h.write(type, 0, 'ascii'); h.writeUInt32BE(8 + bySize[px].length, 4);
    return Buffer.concat([h, bySize[px]]);
  });
  const h = Buffer.alloc(8);
  h.write('icns', 0, 'ascii'); h.writeUInt32BE(8 + chunks.reduce((n, c) => n + c.length, 0), 4);
  return Buffer.concat([h, ...chunks]);
}

async function write(out, data, sources, note) {
  await fs.writeFile(path.join(kit, out), data);
  manifest.push({ file: out, source: sources, use: note });
}

try {
  // App 图标（圆角方块，满版）与黑夜版
  for (const [name, src] of [['orbit-app-icon', 'kit/app-icon/orbit-app-icon.svg'], ['orbit-app-icon-night', 'kit/app-icon/orbit-app-icon-night.svg']]) {
    for (const s of ICON_SIZES) await render(src, `app-icon/png/${name}-${s}.png`, s, s);
  }
  // macOS Dock：Apple 图标网格（824 方块 + 投影），附 ICNS
  for (const [name, src] of [['orbit-dock', 'kit/dock/orbit-dock.svg'], ['orbit-dock-night', 'kit/dock/orbit-dock-night.svg']]) {
    const bySize = {};
    for (const s of [16, 32, 64, ...DOCK_SIZES]) {
      const png = await render(src, `dock/png/${name}-${s}.png`, s, s);
      bySize[s] = png;
    }
    await write(`dock/${name === 'orbit-dock' ? 'Orbit' : 'Orbit-night'}.icns`, icns(bySize), src, 'macOS App 图标（Dock / Finder）');
  }
  // 透明底标志：紧凑画布，按高度
  for (const color of ['ink', 'black', 'white', 'paper']) {
    const src = `kit/mark/orbit-mark-${color}.svg`;
    const [, , w, h] = box(await fs.readFile(path.join(here, src), 'utf8'));
    for (const H of MARK_HEIGHTS) await render(src, `mark/png/orbit-mark-${color}-${H}.png`, Math.round(H * w / h), H);
  }
  // 菜单栏 / 导航栏：黑色模板图（只用 alpha）与板岩灰，@1x @2x @3x
  for (const color of ['black', 'ink', 'white']) {
    const src = `kit/mark/orbit-mark-${color}.svg`;
    const [, , w, h] = box(await fs.readFile(path.join(here, src), 'utf8'));
    for (const H of NAV_HEIGHTS) for (const k of [1, 2, 3]) {
      const tag = color === 'black' ? 'template' : color;
      await render(src, `nav/orbit-nav-${tag}-${H}${k > 1 ? '@' + k + 'x' : ''}.png`, Math.round(H * k * w / h), H * k,
        color === 'black' ? 'macOS 菜单栏模板图（isTemplate）' : undefined);
    }
  }
  // 网页图标
  const fav = [];
  for (const s of [16, 32, 48]) fav.push({ size: s, png: await render('kit/app-icon/orbit-app-icon.svg', `favicon/favicon-${s}.png`, s, s) });
  await write('favicon/favicon.ico', ico(fav), 'kit/app-icon/orbit-app-icon.svg', '浏览器 favicon（16/32/48）');
  await render('kit/favicon/orbit-icon-square.svg', 'favicon/apple-touch-icon.png', 180, 180, 'iOS 主屏（系统自动加圆角）');
  for (const s of [192, 512]) await render('kit/favicon/orbit-icon-square.svg', `favicon/icon-${s}.png`, s, s, 'PWA manifest');
  // 分享图
  for (const name of ['orbit-social', 'orbit-social-night']) await render(`kit/social/${name}.svg`, `social/${name}.png`, 1280, 640);
  // 兼容：仓库 README、App 构建引用的 1024 图标
  await fs.copyFile(path.join(kit, 'app-icon/png/orbit-app-icon-1024.png'), path.join(here, 'orbit-icon.png'));

  manifest.sort((a, b) => a.file.localeCompare(b.file, 'en', { numeric: true }));
  await fs.writeFile(path.join(kit, 'manifest.json'), JSON.stringify({
    generator: 'docs/design/logo/export.mjs', spec: 'docs/design/logo/orbit-spec.json', base: 'docs/design/logo/kit/（file 相对此目录，source 相对 docs/design/logo/）',
    note: '每个位图都由 source 列出的母版 SVG 整体缩放渲染；SVG / PDF 由 generate.py 写出，同一条 path。',
    files: manifest,
  }, null, 2) + '\n');
  console.log(`logo kit: ${manifest.length} raster files`);
} finally {
  await browser.close();
}
