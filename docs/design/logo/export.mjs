// 由 generate.py 写出的 SVG 渲染全部位图素材（PNG、ICO、ICNS）与动效录屏（MP4、GIF、关键帧图），并写出 kit/manifest.json。
// 只渲染、不绘制：每张位图都是某个母版 SVG 的整体缩放，所以标志与 App 图标完全等比。
// 用法（仓库根目录，先运行 generate.py）：node docs/design/logo/export.mjs
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import os from 'node:os';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..', '..');
const kit = path.join(here, 'kit');
const project = createRequire(path.join(root, 'prototypes/advance/package.json'));
const { chromium } = createRequire(project.resolve('@playwright/test'))('playwright');

const ICON_SIZES = [16, 32, 48, 64, 128, 256, 512, 1024];
const DOCK_SIZES = [128, 256, 512, 1024];
const MARK_HEIGHTS = [64, 128, 256, 512, 1024];
const WORDMARK_HEIGHTS = [32, 48, 64, 128, 256, 512];
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
  // 字标：标志作 O + rbit，透明底，按高度
  for (const color of ['ink', 'black', 'paper', 'night']) {
    const src = `kit/wordmark/orbit-wordmark-${color}.svg`;
    const [, , w, h] = box(await fs.readFile(path.join(here, src), 'utf8'));
    for (const H of WORDMARK_HEIGHTS) await render(src, `wordmark/png/orbit-wordmark-${color}-${H}.png`, Math.round(H * w / h), H);
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

  // 动效：录制 kit/motion/orbit-reveal.html 点击展开（浅色 / 深色），转为 MP4 与 GIF（需 ffmpeg）；另出关键帧图
  const reveal = 'file://' + path.join(kit, 'motion/orbit-reveal.html');
  const hasFfmpeg = spawnSync('ffmpeg', ['-version']).status === 0;
  for (const scheme of ['light', 'dark']) {
    const tag = scheme === 'light' ? '' : '-night';
    // 关键帧：转动进度 0、¼、½、¾、1，最后一格为字标完全展开
    const kp = await browser.newPage({ viewport: { width: 960, height: 300 }, colorScheme: scheme, deviceScaleFactor: 1 });
    await kp.goto(reveal);
    await kp.addStyleTag({ content: '.l{transition:none!important} p{display:none}' });
    const cells = [];
    for (const u of [0, 0.25, 0.5, 0.75, 1]) {
      await kp.evaluate(v => draw(v), u);
      cells.push((await kp.screenshot()).toString('base64'));
    }
    await kp.evaluate(() => document.querySelector('button').classList.add('on'));
    cells.push((await kp.screenshot()).toString('base64'));
    await kp.setViewportSize({ width: 1440, height: 340 });
    await kp.setContent(`<body style="margin:0;display:grid;grid-template-columns:repeat(3,1fr)">${cells.map(c => `<img style="width:100%;display:block" src="data:image/png;base64,${c}">`).join('')}</body>`);
    const strip = path.join(kit, `motion/orbit-reveal-frames${tag}.png`);
    await fs.writeFile(strip, await kp.screenshot({ fullPage: true }));
    const [sw, sh] = await kp.evaluate(() => [document.body.scrollWidth, document.body.scrollHeight]);
    manifest.push({ file: rel(strip), source: 'kit/motion/orbit-reveal.html', width: sw, height: sh, use: '动效关键帧：转动进度 0、¼、½、¾、1 与字标展开' });
    await kp.close();
    if (!hasFfmpeg) { console.warn('ffmpeg not found: skip motion video'); continue; }
    const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'orbit-reveal-'));
    const ctx = await browser.newContext({ viewport: { width: 960, height: 400 }, colorScheme: scheme, recordVideo: { dir: tmp, size: { width: 960, height: 400 } } });
    const vp = await ctx.newPage();
    await vp.goto(reveal);
    await vp.addStyleTag({ content: 'p{visibility:hidden}' });
    await vp.waitForTimeout(800);
    await vp.click('button');
    await vp.waitForTimeout(3600);
    const video = await vp.video().path();
    await ctx.close();
    const mp4 = path.join(kit, `motion/orbit-reveal${tag}.mp4`), gif = path.join(kit, `motion/orbit-reveal${tag}.gif`);
    const cut = ['-y', '-loglevel', 'error', '-ss', '0.5', '-i', video];
    spawnSync('ffmpeg', [...cut, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', '-an', mp4], { stdio: 'inherit' });
    spawnSync('ffmpeg', [...cut, '-vf', 'fps=20,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse=dither=bayer:bayer_scale=4', gif], { stdio: 'inherit' });
    await fs.rm(tmp, { recursive: true, force: true });
    for (const [f, w, h, use] of [[mp4, 960, 400, '动效录屏（点击展开）'], [gif, 720, 300, '动效录屏 GIF（文档内嵌用）']])
      manifest.push({ file: rel(f), source: 'kit/motion/orbit-reveal.html', width: w, height: h, use });
  }

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
