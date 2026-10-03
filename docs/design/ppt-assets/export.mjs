// Extract the checked-in Orbit UI without changing its source or connecting to a backend.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../../..');
const args = process.argv.slice(2);
const opt = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const out = path.resolve(root, opt('--out', 'output/playwright/orbit-ppt-assets'));
const themes = opt('--themes', 'light,dark').split(',');
const scale = Number(opt('--scale', '3'));
if (!themes.every(t => ['light', 'dark'].includes(t)) || !Number.isFinite(scale) || scale < 1 || scale > 4) throw new Error('Use light/dark themes and scale 1–4.');
const req = createRequire(import.meta.url);
let runtime;
if (process.env.PLAYWRIGHT_MODULE) runtime = req(process.env.PLAYWRIGHT_MODULE);
else {
  const project = createRequire(path.join(root, 'prototypes/advance/package.json'));
  runtime = createRequire(project.resolve('@playwright/test'))('playwright');
}
const { chromium } = runtime;
const allRoutes = [
  ['overview', '概览', '40-a1-overview.js'], ['persona', '协作人格', '41-a2-persona.js'],
  ['sessions', '会话与轨迹', '42-a3-sessions.js'], ['tools', '工具调用', '43-a4-tools.js'],
  ['projects', '项目习惯', '44-a5-projects.js'], ['sentiment', '情绪与语义', '45-a6-sentiment.js'],
  ['recs', '优化建议', '46-a7-recs.js'], ['library', '资源库', '47-a8-library.js'],
  ['studio', '生成工坊', '48-a9-studio.js'], ['l-home', 'Lite 概览', '39-lite-pages.js'],
  ['l-persona', 'Lite 协作画像', '39-lite-pages.js'], ['l-sessions', 'Lite 会话轨迹', '39-lite-pages.js'],
  ['l-recs', 'Lite 优化建议', '39-lite-pages.js'],
];
const routes = args.includes('--shared-only') ? [] : allRoutes.filter(r => !opt('--routes', '') || opt('--routes', '').split(',').includes(r[0]));
const titleOverrides = {
  overview: ['AI 解读', '会话数量', '协作时长', '用户消息', '自主比', '摩擦率', '会话结果', 'Agent 使用趋势', '协作人格摘要', '活跃节律', '工具调用 Top 6', '本周建议'],
  persona: ['协作人格与罗盘', '四个维度', '优势与盲点', '与 Agent 的契合度'],
  sessions: ['会话列表', '会话概要', '会话轨迹', '关键时刻', '会话启示'],
  tools: ['工具调用数量', '工具错误率', '审批数量', '子代理派发', '工具明细', '调用链矩阵', '失败原因', '审批负担', 'MCP 服务'],
  projects: ['项目列表', '跨项目对比', '项目概要', '项目与整体对比', 'Agent 分工', '识别到的工作流', '规则与配置覆盖'],
  sentiment: ['情绪分布与纠偏', '摩擦分类', '语义主题', '高频反馈语', '情绪的前因'],
  studio: ['新建生成任务', '生成进度与预览', '自检'],
  'l-home': ['协作画像摘要', '会话数量', '协作时长', '摩擦率', '完成率', '本周最值得做的事'],
  'l-persona': ['协作画像与罗盘', '四个维度', '人格演变'],
  'l-sessions': ['最近会话列表', '会话概要', '用户消息', '工具调用', '工具错误', '会话时长', '关键步骤'],
};
const assets = [], errors = [], coverage = [];
const sourceCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const sourceRef = execFileSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
const write = async (name, data) => { const f = path.join(out, name); await fs.mkdir(path.dirname(f), { recursive: true }); await fs.writeFile(f, data); };
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
await fs.mkdir(out, { recursive: true });
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
const server = http.createServer(async (request, response) => {
  try {
    const file = path.resolve(root, '.' + decodeURIComponent(new URL(request.url, 'http://local').pathname));
    const rel = path.relative(root, file);
    if (rel.startsWith('..') || path.isAbsolute(rel)) { response.writeHead(403).end(); return; }
    response.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
    response.end(await fs.readFile(file));
  } catch { response.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
const context = await browser.newContext({ viewport: { width: 1720, height: 1200 }, deviceScaleFactor: scale, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' });
const page = await context.newPage();
page.on('pageerror', e => errors.push(e.message));
await page.addInitScript(() => {
  Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
  document.startViewTransition = undefined;
});
const cleanCSS = `html,body{background:transparent!important} #notes,#tip,#toast{display:none!important}
  html.asset-isolation body *{visibility:hidden!important}
  html.asset-isolation body .asset-selected,html.asset-isolation body .asset-selected *{visibility:visible!important}
  html.asset-isolation body .asset-selected [hidden]{visibility:hidden!important}
  .asset-overflow{overflow:visible!important;clip-path:none!important}
  *{caret-color:transparent!important} .asset-selected{outline:none!important;transition:none!important;animation:none!important}`;

async function settle() {
  await page.evaluate(async () => {
    await document.fonts.ready;
    for (const a of document.getAnimations()) {
      const timing = a.effect?.getComputedTiming();
      if (timing && Number.isFinite(timing.endTime)) { try { a.finish(); } catch {} }
      else a.pause();
    }
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
}
async function resetCapture() {
  await page.evaluate(() => {
    document.documentElement.classList.remove('asset-isolation');
    document.querySelectorAll('.asset-overflow').forEach(e => e.classList.remove('asset-overflow'));
    document.querySelectorAll('.asset-selected').forEach(e => {
      if (e.dataset.assetStyle === 'null') e.removeAttribute('style');
      else if (e.dataset.assetStyle !== undefined) e.setAttribute('style', e.dataset.assetStyle);
      delete e.dataset.assetStyle;
      e.classList.remove('asset-selected');
    });
  });
}
async function prepare(route, theme) {
  await resetCapture();
  await page.setViewportSize({ width: 1720, height: 1200 });
  await page.evaluate(({ route, theme }) => {
    document.documentElement.classList.remove('asset-isolation');
    document.querySelectorAll('.asset-selected').forEach(e => e.classList.remove('asset-selected'));
    closeOverlay(); closeModal(); closeDD(); closeSettings();
    S.ed = route.startsWith('l-') ? 'lite' : 'advance';
    document.querySelector('#win').dataset.ed = S.ed;
    S.win = { x: 80, y: 60, w: 1440, h: 1040, zoom: false, full: false };
    S.hud.show = false; S.widgets = false; S.pop = false;
    store.set('guideOff', true); setTheme(theme); go(route);
  }, { route, theme });
  await settle();
}
async function svgOf(locator) {
  return locator.evaluate(el => {
    const clone = el.cloneNode(true);
    const before = [el, ...el.querySelectorAll('*')], after = [clone, ...clone.querySelectorAll('*')];
    const properties = ['color', 'fill', 'fill-opacity', 'fill-rule', 'stroke', 'stroke-width', 'stroke-opacity', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray', 'stroke-dashoffset', 'opacity', 'font-family', 'font-size', 'font-weight', 'font-style', 'letter-spacing', 'text-anchor', 'dominant-baseline', 'paint-order', 'vector-effect', 'stop-color', 'stop-opacity', 'clip-path', 'mask', 'filter', 'display'];
    before.forEach((node, i) => {
      const css = getComputedStyle(node); after[i].removeAttribute('class'); after[i].removeAttribute('style');
      for (const p of properties) after[i].style.setProperty(p, css.getPropertyValue(p).replace(/url\(["']?[^)"']*#([^\s)"']+)["']?\)/g, 'url(#$1)'));
      if (css.transform !== 'none') { after[i].style.transform = css.transform; after[i].style.transformOrigin = css.transformOrigin; }
    });
    const rect = el.getBoundingClientRect(); clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('width', String(rect.width)); clone.setAttribute('height', String(rect.height));
    return { svg: new XMLSerializer().serializeToString(clone), width: rect.width, height: rect.height };
  });
}
async function capture(locator, info, extractSVG = true) {
  await resetCapture();
  if (await locator.count() !== 1) throw new Error(`${info.id}: expected exactly one element`);
  await locator.evaluate(el => el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
  await settle();
  const viewport = page.viewportSize(), pad = info.kind === 'pages' ? 24 : 12;
  // A DOM element screenshot still clips at scroll ancestors. Keep the component's own
  // scroll panes intact, but release ancestor clips and translate the rendered component
  // into the capture viewport. Its layout, width, typography and source DOM stay intact.
  await locator.evaluate((el, pad) => {
    el.dataset.assetStyle = el.getAttribute('style') ?? 'null';
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) p.classList.add('asset-overflow');
    const r = el.getBoundingClientRect(), transform = getComputedStyle(el).transform;
    el.style.setProperty('transform', `translate(${pad + 2 - r.x}px,${pad + 2 - r.y}px) ${transform === 'none' ? '' : transform}`, 'important');
    el.classList.add('asset-selected');
    document.documentElement.classList.add('asset-isolation');
  }, pad);
  const rect = await locator.boundingBox();
  if (!rect || rect.width < 2 || rect.height < 2) throw new Error(`${info.id}: empty element`);
  if (rect.y < -1 || rect.y + rect.height > viewport.height + 1) throw new Error(`${info.id}: element exceeds viewport ${JSON.stringify(rect)}`);
  const x = Math.max(0, Math.floor(rect.x - pad)), y = Math.max(0, Math.floor(rect.y - pad));
  const clip = { x, y, width: Math.min(viewport.width - x, Math.ceil(rect.x + rect.width + pad) - x), height: Math.min(viewport.height - y, Math.ceil(rect.y + rect.height + pad) - y) };
  const png = `${info.kind}/${info.id}--${info.theme}.png`;
  await write(png, await page.screenshot({ clip, omitBackground: true, animations: 'disabled' }));
  assets.push({ ...info, file: png, format: 'PNG', width: Math.round(clip.width * scale), height: Math.round(clip.height * scale), contentWidth: Math.round(rect.width), contentHeight: Math.round(rect.height), scale, transparent: true, data: 'demo' });
  if (extractSVG) {
    const svgs = locator.locator('svg');
    for (let i = 0; i < await svgs.count(); i++) {
      const svg = svgs.nth(i), box = await svg.boundingBox();
      if (!box || box.width < 80 || box.height < 45) continue;
      const result = await svgOf(svg);
      const id = `${info.id}-chart-${String(i + 1).padStart(2, '0')}`;
      const file = `vectors/${id}--${info.theme}.svg`;
      await write(file, result.svg);
      assets.push({ ...info, id, kind: 'vectors', title: info.title + ' · 图形', file, format: 'SVG', width: Math.round(result.width), height: Math.round(result.height), transparent: true, data: 'demo' });
    }
  }
  await resetCapture();
}

try {
  await page.goto(base + '/prototypes/advance/tandem-demo.html', { waitUntil: 'networkidle' });
  if (await page.evaluate(() => LV.live)) throw new Error('Expected the standalone sample-data UI.');
  await page.addStyleTag({ content: cleanCSS });
  await settle();
  const designTokens = {};
  for (const theme of themes) {
    for (const [route, title, sourceFile] of routes) {
      const edition = route.startsWith('l-') ? 'Lite' : 'Advance';
      const source = 'prototypes/advance/src/js/' + sourceFile;
      await prepare(route, theme);
      await capture(page.locator('#win'), { id: route + '-window', title: title + ' · 完整窗口', kind: 'pages', theme, route, edition, source, selector: '#win', usage: '产品演示与页面全貌；窗口内下方内容仍按原 UI 滚动' }, false);
      await prepare(route, theme);
      const cards = await page.evaluate(() => Array.from(document.querySelectorAll('#content .card')).filter(e => !e.parentElement.closest('.card')).map((e, i) => {
        e.dataset.exportId = String(i);
        const heading = e.querySelector('.rc-title,.rc-t,.lb-title,h3,.ct,.eb,.lbl,.vz-kpi-l');
        return { index: i, title: (heading?.textContent || e.getAttribute('aria-label') || e.textContent).trim().replace(/\s+/g, ' ').slice(0, 64), originalId: e.id };
      }));
      coverage.push({ route, theme, cards: cards.length });
      for (const card of cards) {
        const id = `${route}-${String(card.index + 1).padStart(2, '0')}`;
        const name = titleOverrides[route]?.[card.index] || card.title;
        await capture(page.locator(`[data-export-id="${card.index}"]`), { id, title: name, kind: 'components', theme, route, edition, source, selector: card.originalId ? '#' + card.originalId : `#content .card (top-level index ${card.index})`, usage: title + '中的独立组件' });
      }
      if (route === 'persona') await capture(page.locator('.pe-fpc > svg').first(), { id: 'persona-compass', title: '人格罗盘 · 独立透明图形', kind: 'components', theme, route, edition, source, selector: '.pe-fpc > svg', usage: '适合放大展示或与路演文字并排排版' }, false);
      console.log(`${theme} ${route}: ${cards.length} components + window`);
    }
    if (opt('--routes', '')) continue;
    await prepare('overview', theme);
    designTokens[theme] = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement), names = ['--bg', '--surface', '--sb', '--ink-1', '--ink-2', '--ink-3', '--orbit', '--ai', '--ai-bg', '--good', '--warn', '--crit', '--line', '--sans', '--serif', '--mono', '--a1', '--a2', '--a3', '--a4', '--a5'];
      return Object.fromEntries(names.map(n => [n, css.getPropertyValue(n).trim()]));
    });
    const controls = [
      ['sidebar', '侧边栏', '#side'], ['edition-switch', 'Lite / Advance 切换', '.edsw'], ['window-controls', '窗口控制', '#wtop'],
      ['toolbar', '页面工具栏', '#main .tbar'], ['filters', '筛选栏', '#content .frow'], ['button', '普通按钮', '#main .btn:not(.ai):not(.gh)'],
      ['ai-button', 'AI 操作按钮', '#main .btn.ai'], ['range-segment', '时间范围分段控件', '#content .frow .seg'],
      ['filter-chip', '筛选胶囊', '#content .frow .chip'], ['toggle', '开关', '#content .sw'], ['ai-badge', 'AI 标签', '#aiCard .aib'],
      ['tag', '标签', '#content .tag'], ['badge', '信息徽标', '#content .bdg'],
    ];
    for (const [id, title, selector] of controls) await capture(page.locator(selector).first(), { id, title, kind: 'controls', theme, route: 'overview', edition: 'Shared', source: 'prototypes/advance/src/', selector, usage: '说明界面操作与组件复用' }, false);
    await page.evaluate(() => { S.widgets = true; S.wgSize = 'l'; renderWidgets(); });
    const widgets = page.locator('#widgets .wg');
    const widgetTitles = ['协作人格', '今日会话', '本周协作', '运行中的会话', '近七天趋势', '本周建议'];
    for (let i = 0; i < await widgets.count(); i++) await capture(widgets.nth(i), { id: `widget-${i + 1}`, title: widgetTitles[i] + '小组件', kind: 'desktop', theme, edition: 'Shared', source: 'prototypes/advance/src/js/62-widgets.js', selector: `#widgets .wg >> nth=${i}`, usage: '桌面侧的轻量信息展示' });
    for (const state of ['running', 'done', 'waiting', 'stuck', 'ctx']) {
      await page.evaluate(state => { S.widgets = false; S.sim = 'running'; S.hudSim = state; S.hud.show = true; S.hud.open = false; renderHud(); }, state);
      await capture(page.locator('#hud'), { id: 'hud-' + state, title: '悬浮胶囊 · ' + state, kind: 'desktop', theme, edition: 'Shared', source: 'prototypes/advance/src/js/61-hud.js', selector: '#hud', usage: 'Agent 运行状态提示' }, false);
    }
    await page.evaluate(() => { S.sim = 'running'; S.hudSim = 'running'; S.hud.open = true; renderHud(); });
    await capture(page.locator('#hud'), { id: 'hud-expanded', title: '展开的悬浮组件', kind: 'desktop', theme, edition: 'Shared', source: 'prototypes/advance/src/js/61-hud.js', selector: '#hud' }, false);
    await page.evaluate(() => { S.hud.show = false; renderHud(); S.pop = true; renderPop(); });
    await capture(page.locator('#pop'), { id: 'menubar-panel', title: '菜单栏面板', kind: 'desktop', theme, edition: 'Shared', source: 'prototypes/advance/src/js/60-menubar-panel.js', selector: '#pop' });
    await page.evaluate(() => { S.pop = false; render(); });
    const tabs = await page.evaluate(() => SET_TABS);
    for (const [tab, name] of tabs) {
      await page.evaluate(t => openSettings(t), tab);
      await capture(page.locator('#set'), { id: 'settings-' + tab, title: '设置 · ' + name, kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/57-settings.js', selector: '#set' }, false);
    }
    await page.evaluate(() => { closeSettings(); openPalette(); });
    await capture(page.locator('#modal'), { id: 'command-palette', title: '命令面板', kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/52-palette.js', selector: '#modal' }, false);
    await page.evaluate(t => { closeModal(); S.shareDark = t === 'dark'; openShare(); }, theme);
    await capture(page.locator('#modal'), { id: 'share-dialog', title: '分享卡预览', kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/55-exports.js', selector: '#modal' });
    await capture(page.locator('.sharecard'), { id: 'persona-share-card', title: '人格分享卡', kind: 'components', theme, edition: 'Shared', source: 'prototypes/advance/src/js/55-exports.js', selector: '.sharecard', usage: '单独展示人格代码、罗盘与维度' });
    await page.evaluate(() => closeModal());
    for (const [step, name] of [[0, '首次启动欢迎'], [1, '选择会话来源'], [3, '人格揭晓']]) {
      await page.evaluate(step => openOnboarding(step), step);
      await capture(page.locator('#overlay .obox'), { id: 'onboarding-' + step, title: name, kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/56-onboarding.js', selector: '#overlay .obox' });
    }
    await page.evaluate(() => { closeOverlay(); openInstall('ro-allow'); });
    await capture(page.locator('#modal'), { id: 'install-preview', title: '安装前预览变更', kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/51-install.js', selector: '#modal' }, false);
    await capture(page.locator('#modal .btn.p'), { id: 'primary-button', title: '主操作按钮', kind: 'controls', theme, edition: 'Shared', source: 'prototypes/advance/src/styles/30-primitives.css', selector: '#modal .btn.p' }, false);
    await page.evaluate(() => { INST.step = 2; drawInstall(); });
    await capture(page.locator('#modal'), { id: 'install-confirm', title: '安装确认', kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/51-install.js', selector: '#modal', usage: '展示确认界面，导出过程没有执行安装' }, false);
    await page.evaluate(() => { closeModal(); openAsk(); });
    await capture(page.locator('#modal'), { id: 'ask-agent', title: '问本地 Agent', kind: 'flows', theme, edition: 'Shared', source: 'prototypes/advance/src/js/53-ask.js', selector: '#modal' }, false);
    await page.evaluate(() => closeModal());
    console.log(`${theme}: shared controls, desktop and dialogs exported`);
  }
  const icons = await page.evaluate(() => I);
  for (const [name, d] of Object.entries(icons)) {
    const file = `icons/${name}.svg`;
    await write(file, `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="#17181b" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="${esc(d)}"/></svg>`);
    assets.push({ id: 'icon-' + name, title: name, kind: 'icons', file, format: 'SVG', width: 96, height: 96, theme: 'light', source: 'prototypes/advance/src/js/00-utils.js', transparent: true });
  }
  for (const name of ['orbit-mark.svg', 'orbit-mark-light.svg', 'orbit-mark-small.svg', 'orbit-icon.svg', 'orbit-icon.png']) {
    const source = 'docs/design/logo/' + name, file = 'brand/' + name;
    await write(file, await fs.readFile(path.join(root, source)));
    assets.push({ id: name.replace(/\./g, '-'), title: name, kind: 'brand', source, file, format: path.extname(name).slice(1).toUpperCase(), theme: name.includes('light') ? 'dark' : 'light', transparent: !name.includes('icon') });
  }
  await write('design-tokens.json', JSON.stringify(designTokens, null, 2) + '\n');
  await write('sources/orbit-demo.html', await fs.readFile(path.join(root, 'prototypes/advance/tandem-demo.html')));
  await fs.cp(path.join(root, 'docs/design/visual-cases-v1'), path.join(out, 'sources/visual-cases-v1'), { recursive: true });
  const manifest = { product: 'Orbit', sourceCommit, sourceRef, data: 'Repository demo sample data; no real logs or performance claims', scale, generatedAt: new Date().toISOString(), coverage, browserErrors: errors, assets };
  await write('manifest.json', JSON.stringify(manifest, null, 2) + '\n');
  await write('manifest.csv', '\ufeff' + ['id,title,kind,theme,format,file,width,height,source', ...assets.map(a => ['id','title','kind','theme','format','file','width','height','source'].map(k => '"' + String(a[k] ?? '').replace(/"/g, '""') + '"').join(','))].join('\r\n'));
  const cards = assets.map(a => `<article data-kind="${a.kind}" data-theme="${a.theme}" data-search="${esc(a.id + ' ' + a.title + ' ' + (a.route || ''))}"><a class="preview" href="${a.file}" target="_blank"><img loading="lazy" src="${a.file}" alt="${esc(a.title)}"></a><div class="body"><h3>${esc(a.title)}</h3><p>${a.id} · ${a.theme} · ${a.format}${a.width ? ' · ' + a.width + '×' + a.height : ''}</p><a href="${a.file}" download>下载素材</a><details><summary>来源</summary><code>${esc(a.source || '')}</code><p>${esc(a.selector || '')}</p></details></div></article>`).join('\n');
  await write('index.html', `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Orbit · PPT 组件素材</title><style>
  *{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#17181b;font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}header{padding:42px 5vw 26px;border-bottom:1px solid #e3e1dc}h1{font:48px Georgia,serif;margin:0}header p{max-width:1000px;color:#62666f}a{color:inherit}nav{position:sticky;top:0;background:#f5f4f0ed;backdrop-filter:blur(16px);padding:14px 5vw;display:flex;gap:12px;flex-wrap:wrap;z-index:2;border-bottom:1px solid #e3e1dc}input,select,button{font:inherit;border:1px solid #c9c6bf;border-radius:7px;background:white;padding:8px 12px}input{width:260px}main{padding:28px 5vw;display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:22px}article{background:white;border:1px solid #e3e1dc;border-radius:12px;overflow:hidden}.preview{height:250px;display:flex;align-items:center;justify-content:center;padding:18px;background:repeating-conic-gradient(#ebe8e1 0% 25%,#f7f5f0 0% 50%) 50% / 20px 20px}article[data-theme=dark] .preview{background:#242429}.preview img{display:block;max-width:100%;max-height:100%;object-fit:contain}.body{padding:16px}h3{font-size:16px;margin:0}article p,details{font-size:12px;color:#62666f;overflow-wrap:anywhere}article[hidden]{display:none}body.dark-stage .preview{background:#17181b!important}#count{align-self:center;color:#62666f}footer{padding:24px 5vw;color:#62666f}</style>
  <header><h1>Orbit / PPT 素材</h1><p>${assets.length} 个文件 · PNG ${scale}× · 浅色 / 深色 · 原始 SVG。基于 main ${sourceCommit.slice(0,8)}。所有界面数字均为 Demo 示例；PNG 保留原组件表面，组件外部透明。</p><a href="manifest.csv">素材清单 CSV</a> · <a href="manifest.json">来源与尺寸 JSON</a> · <a href="design-tokens.json">配色与字体</a> · <a href="sources/orbit-demo.html">原始可交互 HTML</a></header>
  <nav><input id="q" placeholder="搜索人格、轨迹、建议…"><select id="kind"><option value="">全部类型</option><option value="pages">完整页面</option><option value="components" selected>页面组件</option><option value="desktop">桌面与悬浮组件</option><option value="controls">通用控件</option><option value="flows">设置与对话框</option><option value="vectors">图表 SVG</option><option value="brand">品牌</option><option value="icons">图标</option></select><select id="theme"><option value="">全部主题</option><option value="light" selected>浅色</option><option value="dark">深色</option></select><button id="stage">切换预览底色</button><span id="count"></span></nav><main>${cards}</main><footer>sources/visual-cases-v1 保留了 26 份早期画板源文件，依赖原 Design 运行时，仅作存档；本页图片来自现行 Orbit UI。</footer><script>
  const items=[...document.querySelectorAll('article')],q=document.querySelector('#q'),kind=document.querySelector('#kind'),theme=document.querySelector('#theme');function filter(){let n=0;for(const e of items){e.hidden=!!((kind.value&&e.dataset.kind!==kind.value)||(theme.value&&e.dataset.theme!==theme.value)||!e.dataset.search.toLowerCase().includes(q.value.toLowerCase()));if(!e.hidden)n++}document.querySelector('#count').textContent=n+' 个素材'}for(const el of [q,kind,theme])el.addEventListener('input',filter);document.querySelector('#stage').onclick=()=>document.body.classList.toggle('dark-stage');filter();</script></html>`);
  await write('README.txt', `Orbit PPT 素材包\n来源 main: ${sourceCommit}\n\n双击 index.html 浏览和搜索。PNG 为 ${scale} 倍分辨率，组件外部透明，可直接插入 PowerPoint / Keynote。品牌 SVG 为原文件的逐字节副本。图表 SVG 保留矢量，但文字依赖 Source Serif 4、JetBrains Mono 和系统中文字体；需要完全一致时使用 PNG。\n\n所有数字、收益与社区用户数量来自 Demo 示例，不能作为实测成果。Windows 浏览器使用系统中文字体，和 macOS 的 PingFang 字形可能不同。页面图保留原窗口可见范围，滚动区域的各卡片另有完整导出。\n\nmanifest.csv / manifest.json 提供文件、尺寸、主题、来源和组件定位。design-tokens.json 是当前界面的配色和字体。sources/orbit-demo.html 是当前可运行单文件原型；sources/visual-cases-v1 是 26 份历史画板与 canvas.json，依赖原 Design 运行时，不是可直接打开的网页。\n`);
  console.log(JSON.stringify({ out, files: assets.length, png: assets.filter(a => a.format === 'PNG').length, svg: assets.filter(a => a.format === 'SVG').length, errors }));
  if (errors.length) throw new Error('Browser errors occurred; inspect manifest.json.');
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
