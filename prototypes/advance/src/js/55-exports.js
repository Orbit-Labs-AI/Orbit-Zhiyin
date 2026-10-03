/* ============ exports: report, csv, share card ============ */
const REP_SECS = [['ov', '概览'], ['persona', '协作人格'], ['proj', '项目'], ['fric', '主要摩擦'], ['recs', '建议']];
// Active filters, as one line for the report header. The persona uses the shared persona scope (personaNow, BUG-06):
// session-level filters such as topic or outcome do not change it, and the report says so.
function filterNote() {
  const f = [];
  const agN = AG.filter((a) => S.agents.has(a.id)).length; if (agN !== AG.length) f.push('Agent · ' + AG.filter((a) => S.agents.has(a.id)).map((a) => a.name).join('、'));
  if (S.project) f.push('项目 · ' + PJI[S.project].name); if (S.topic) f.push('主题 · ' + TOPICS[S.topic]); if (S.outcome) f.push('结果 · ' + ({ ok: '完成', part: '部分完成', fail: '放弃' })[S.outcome]); if (S.fric) f.push('摩擦 · ' + S.fric); if (S.hour != null) f.push('时段 · ' + S.hour + ':00–' + (S.hour + 1) + ':00');
  return f.join(' · ');
}
function reportMD() {
  const L = sel(); const st = stats(L); const p = personaNow(); const fn = filterNote();
  const out = ['# Orbit 协作报告 · ' + rangeLabel(), '', '> ' + winLabel() + ' · 示例数据 · 生成于 ' + nowText(), ''];
  if (fn) out.push('> 筛选：' + fn, '');
  if (S.rep.has('ov')) out.push('## 概览', '', '| 指标 | 数值 |', '| --- | ---: |', '| 会话 | ' + fmt(st.n) + ' |', '| 协作时长 | ' + f1(st.hours) + ' 小时 |', '| 你的消息 | ' + fmt(st.msgs) + ' |', '| 自主比 | ' + f1(st.auto) + '× |', '| 摩擦率 | ' + f1(st.fric) + '% |', '| 完成率 | ' + Math.round(st.ok) + '% |', '');
  if (S.rep.has('persona')) {
    out.push('## 协作人格', '', p.ok ? '**' + p.code + ' · ' + p.zh + '**（' + p.en + '）：' + p.line + (fn ? '　—　' + (personaScopeNote() || '按上面的筛选计算') + '，' + p.n + ' 个会话' : '') : '所选范围还没有会话，暂不判断。', '');
    if (p.ok) { AXES.forEach((ax, i) => { const v = axisView(p, i); out.push('- ' + ax.dim + '：' + v.letter + ' ' + v.name + ' ' + v.strong); }); out.push(''); }
  }
  if (S.rep.has('proj')) { out.push('## 项目', '', '| 项目 | 会话 | 时长 | 自主比 | 摩擦率 |', '| --- | ---: | ---: | ---: | ---: |'); projRows(L).filter((r) => r.st.n).sort((a, b) => b.st.hours - a.st.hours).slice(0, 6).forEach((r) => out.push('| ' + r.p.name + ' | ' + r.st.n + ' | ' + f1(r.st.hours) + 'h | ' + f1(r.st.auto) + '× | ' + f1(r.st.fric) + '% |')); out.push(''); }
  if (S.rep.has('fric')) { out.push('## 主要摩擦', ''); Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]).slice(0, 4).forEach((f, i) => out.push((i + 1) + '. ' + f[0] + '：' + f[1] + ' 个会话')); out.push(''); }
  if (S.rep.has('recs')) { out.push('## 建议', ''); visibleRecs().slice(0, 6).forEach((r) => out.push('- [' + (S.installed.has(r.id) ? 'x' : ' ') + '] ' + r.title + '（' + r.type + ' · ' + LEVELS[r.lvl] + ' · ' + recGain(r) + '）')); out.push(''); }
  return out.join('\n');
}
function openReport() {
  CUR.report = reportMD();
  openModal(modalHead('导出报告', rangeLabel() + ' · ' + winLabel() + ' · 跟随主窗口的筛选') + '<div class="mb" style="display:flex;flex-wrap:wrap;gap:16px"><div class="col" style="gap:8px;width:150px;flex:none"><span class="eb">包含</span>' + REP_SECS.map((x) => '<label class="row" style="font-size:13px"><input type="checkbox" data-chg="repSec" data-k="' + x[0] + '"' + (S.rep.has(x[0]) ? ' checked' : '') + ' style="accent-color:var(--ink-1)">' + x[1] + '</label>').join('') + '<span class="eb" style="margin-top:8px">格式</span><span style="font-size:13px">Markdown</span></div><textarea readonly id="repText" aria-label="报告内容" style="flex:1;min-width:min(260px,100%);min-height:340px;font:12px/1.55 var(--font-mono);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--surface);color:var(--ink-1);resize:vertical">' + esc(CUR.report) + '</textarea></div><div class="mf"><span class="cap" style="margin-right:auto;font-size:11px">Demo 不能直接下载 · 复制后粘贴到任意 Markdown 编辑器</span><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="repCopy">复制 Markdown</button></div>', 'wide');
  MODAL_KEY = 'report';
}
function openCSV() {
  const rows = toolRows(sel());
  CUR.csv = ['tool,calls,error_rate,failures,avg_duration,approval_rate'].concat(rows.map((r) => [r.name, r.n, (r.err * 100).toFixed(1) + '%', r.fails, r.avg, Math.round(r.ap * 100) + '%'].join(','))).join('\n');
  openModal(modalHead('导出工具明细 CSV', rangeLabel() + ' · ' + rows.length + ' 种工具 · 复制后可以粘贴到表格软件') + '<div class="mb"><textarea readonly aria-label="CSV 内容" style="width:100%;min-height:260px;font:12px/1.6 var(--font-mono);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--surface);color:var(--ink-1);resize:vertical">' + esc(CUR.csv) + '</textarea></div><div class="mf"><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="copyCSV">复制 CSV</button></div>', 'wide');
}
// 分享卡金句：16 型各一句（与 packages/backend/src/orbit_backend/exporting/type_copy.py 的 SHARE_QUOTES 逐字一致）
const SHAREQ = { DPMV: ['先把规格写清楚，', '再让每个 Agent 各司其职。'], DPMT: ['把需求讲清楚，', '让产出并行流动。'], DPFV: ['一次只推一件事，', '每一件都严格验收。'], DPFT: ['把想法写成好任务，', '把精力留给关键判断。'],
  DIMV: ['把目标交出去，', '把验收留给自己。'], DIMT: ['同时开很多条线，', '顺着结果往前走。'], DIFV: ['让 Agent 带路，', '方向由我来核实。'], DIFT: ['放手让它发挥，', '享受意外的收获。'],
  SPMV: ['多条线同时起飞，', '每一条都稳稳落地。'], SPMT: ['计划周全，亲自操盘，', '几件事一起向前跑。'], SPFV: ['先想清楚，再动手，', '每一步都有依据。'], SPFT: ['把每一步讲清楚，', 'Agent 照着就能抵达。'],
  SIMV: ['几种做法一起试，', '让结果说出更优解。'], SIMT: ['和 Agent 你来我往，', '灵感在对话里生长。'], SIFV: ['一次只做一件事，', '每一步都亲自确认。'], SIFT: ['边聊边推进，', '彼此信任，配合默契。'] };
const SHAREQ0 = ['和 AI 一起，', '找到自己的节奏。'];
/* 分享卡按时间长度各出一张：每个长度用自己的窗口算人格（同一个人在近 7 天和全部里可以是不同类型），卡上的标签（周卡 / 月卡 /
   季卡 / 全时卡 / N 月卡）、日期、外圈的日历环（每格一天，超过 92 天每格一周，深浅 = 当天会话数）都跟着这张卡的窗口走。
   人格的口径与「协作人格」页相同（personaScope：时间窗 + Agent + 项目）；live 由 98-live-ops 换成网关按同一窗口算的卡片数据。 */
const SHARE_TAG = { '7': ['周卡', 'WEEKLY'], '30': ['月卡', 'MONTHLY'], '90': ['季卡', 'QUARTERLY'], all: ['全时卡', 'ALL TIME'] };
// 7 / 30 / 90 / 全部，外加「协作人格」页正在看的月份（与近 30 天窗口相同时不重复列出）
function shareSpans() { const ks = ['7', '30', '90', 'all']; const pk = String(S.persona.period); if (PERIODS[pk] && ks.indexOf(pk) < 0 && String(spanWin(pk)) !== String(win(30))) ks.splice(2, 0, pk); return ks; }
function shareKey() { const ks = shareSpans(); return ks.indexOf(S.shareSpan) >= 0 ? S.shareSpan : ks.indexOf(String(S.persona.period)) >= 0 ? String(S.persona.period) : '30'; }
function spanWin(k) { return k === '7' || k === '30' ? win(+k) : PERIODS[k] ? [PERIODS[k][0], PERIODS[k][1]] : k === '90' ? win(90) : [0, LASTDAY]; }
function spanMonth(k) { return !SHARE_TAG[k] && PERIODS[k] ? dayDate(PERIODS[k][0]) : null; }
function spanLabel(k) { const m = spanMonth(k); return m ? m.getUTCFullYear() + ' 年 ' + (m.getUTCMonth() + 1) + ' 月' : k === 'all' ? '全部' : '近 ' + k + ' 天'; }
function spanTag(k) { const m = spanMonth(k); return SHARE_TAG[k] || (m ? [(m.getUTCMonth() + 1) + ' 月卡', 'MONTHLY'] : [k + ' 天卡', k + ' DAYS']); }
const spanDate = (x, y) => (y ? x.getUTCFullYear() + '.' : '') + String(x.getUTCMonth() + 1).padStart(2, '0') + '.' + String(x.getUTCDate()).padStart(2, '0');
function spanRange(a, b) { return spanDate(a, true) + ' — ' + spanDate(b, a.getUTCFullYear() !== b.getUTCFullYear()); }
// 日历环：窗口内每天（> 92 天时每周）一格，值 = 会话数 ÷ 最多的一格（0 = 没有会话）
function spanRing(L, w) {
  const days = w[1] - w[0] + 1, step = days > 92 ? 7 : 1, n = Math.max(1, Math.ceil(days / step)); const c = new Array(n).fill(0);
  L.forEach((s) => { const i = Math.floor((s.d - w[0]) / step); if (i >= 0 && i < n) c[i]++; });
  const mx = Math.max(1, ...c); return { unit: step === 7 ? 'week' : 'day', cells: c.map((x) => +(x / mx).toFixed(3)) };
}
// sp = 一张卡的事实：{key, w, L, p, label, tag, range, ring}；live 另带 q / stats（网关的卡片数据）
function sharePersona(k) {
  k = k || shareKey(); const w = spanWin(k); const L = sel({ win: w, noExtra: true });
  return { key: k, w, L, p: persona(L), label: spanLabel(k), tag: spanTag(k), range: spanRange(dayDate(w[0]), dayDate(w[1])), ring: spanRing(L, w) };
}
// 一张卡在弹窗里的状态：ok（可导出）/ pending（计算中）/ blocked（附原因）。live 覆盖它
function shareSpanState(k) { const sp = sharePersona(k); return sp.p.ok ? { state: 'ok', sp } : { state: 'blocked', sp, reason: sp.label + '还没有会话' }; }
/* 卡片模型 → 绘制指令（100 × 125 的单位格，1 单位 = 卡宽的 1%）。网页预览（SVG）与 1080 × 1350 PNG（canvas 2D；WebKit 会污染
   画了 SVG foreignObject 的 canvas，所以不能直接栅格化 HTML）都只执行这一份指令，排版、字体与换行逐像素一致。 */
function shareModel(sp) {
  const p = sp.p, L = sp.L || []; const st = stats(L);
  const stats4 = sp.stats || [[fmt(p.n != null ? p.n : st.n), '会话'], [String(new Set(L.map((s) => s.d)).size), '活跃天数'], [String(new Set(L.map((s) => s.a)).size), 'Agent'], [fmt(st.msgs), '对话轮次']];
  return { key: sp.key, code: p.code, label: sp.label, tag: sp.tag, range: sp.range, zh: p.zh, en: p.en, line: p.line || '', q: sp.q || SHAREQ[p.code] || SHAREQ0,
    glyph: bloomGlyph(p), axes: AXES.map((ax, i) => { const v = axisView(p, i); return { L: v.letter, name: v.name, strong: v.strong + '%' }; }),
    stats: stats4, ring: sp.ring || { unit: 'day', cells: [] }, foot: (sp.disclaimer ? sp.disclaimer + ' · ' : '') + '全部分析在本机完成' };
}
const SHARE_C = { dark: { bg: '#131417', ink: '#f1f1f3', ink2: '#c3c6cc', ink3: '#8f949c', line: 'rgba(255,255,255,.14)', mj: '#f1f1f3', mn: '#4a4d54' }, light: { bg: '#f5f4f0', ink: '#17181b', ink2: '#45484f', ink3: '#62666f', line: '#dcd9d2', mj: '#17181b', mn: '#c0bdb5' } };
function shareFonts() {
  const cs = getComputedStyle(document.documentElement); const v = (n) => cs.getPropertyValue(n).trim() || 'sans-serif';
  return { type: v('--font-type'), display: v('--font-display'), num: v('--font-num'), sans: v('--font-sans') };
}
let SHARE_MCTX = null;
// 文字宽度（单位格）：在 10 倍字号下量再缩回，避免小字号的取整误差
function shareMeasure(F) {
  if (!SHARE_MCTX) SHARE_MCTX = document.createElement('canvas').getContext('2d');
  return (t, o) => { SHARE_MCTX.font = (o.italic ? 'italic ' : '') + (o.weight || 400) + ' ' + o.size * 10 + 'px ' + F[o.family || 'sans']; const w = SHARE_MCTX.measureText(t).width / 10; return w + (o.ls ? o.ls * o.size * t.length : 0); };
}
// 中文按字断行；行首不留标点（，。、；：！？」）
function shareWrap(t, maxW, mw, o) {
  const lines = []; let cur = '';
  for (const ch of Array.from(t)) {
    if (cur && mw(cur + ch, o) > maxW && !/[，。、；：！？」）]/.test(ch)) { lines.push(cur); cur = ch; } else cur += ch;
  }
  if (cur) lines.push(cur);
  return lines;
}
/* 版式（留白优先）：页眉（Orbit·知音 字标，取自 docs/design/logo/kit/wordmark；深色卡用香槟黄）→ 花 + 日历环 → 类型码 → 类型名与描述 → 四个数字 → 一行页脚。金句不上卡（放进「复制分享文案」），
   二维码占位去掉；隐藏数字时类型名以下整体下移，留白均匀。 */
function shareOps(m, dark, noNum) {
  const C = SHARE_C[dark ? 'dark' : 'light'], F = shareFonts(), mw = shareMeasure(F); const ops = []; const L = 8, R = 92;
  const T = (s, x, y, o) => ops.push(Object.assign({ t: 'text', s: String(s), x, y }, o));
  ops.push({ t: 'rect', x: 0, y: 0, w: 100, h: 125, fill: C.bg });
  // 页眉：字标 + 这张卡的标签胶囊；下一行是卡名与日期
  const wm = ORBIT_WORDMARK, wh = 3.4; ops.push({ t: 'wordmark', x: L, y: 6.6, k: wh / wm.vb[3], fill: dark ? wm.night : wm.ink });
  const tag = m.tag[0] + ' · ' + m.tag[1], tagO = { size: 2, weight: 600, family: 'sans', color: C.ink, ls: 0.06 }; const tw = mw(tag, tagO) + 4.4;
  ops.push({ t: 'rrect', x: R - tw, y: 6.8, w: tw, h: 4.5, r: 2.25, stroke: C.ink, sw: 0.2 });
  T(tag, R - tw / 2, 9.85, Object.assign({ align: 'center' }, tagO));
  T('我的 AI 协作人格 · ' + m.label, L, 16.2, { size: 2.4, family: 'sans', color: C.ink3 });
  T(m.range || '', R, 16.2, { size: 2.2, weight: 500, family: 'num', color: C.ink3, align: 'right' });
  // 花 + 日历环：12 点起顺时针，最早的一格在最前
  const cx = 75.5, cy = 36.5, rr = 15.6, cells = m.ring.cells || []; const n = cells.length;
  if (n) {
    const gap = n <= 12 ? 0.11 : Math.min(2 * Math.PI / n * 0.34, 0.05), seg = 2 * Math.PI / n;
    cells.forEach((v, i) => { const a0 = -Math.PI / 2 + i * seg + gap / 2, a1 = a0 + seg - gap; ops.push(v > 0 ? { t: 'arc', cx, cy, r: rr, a0, a1, sw: n <= 31 ? 1.1 : 0.85, color: C.ink, alpha: +(0.3 + 0.7 * v).toFixed(3) } : { t: 'arc', cx, cy, r: rr, a0, a1, sw: 0.4, color: C.mn, alpha: 1 }); });
  }
  if (m.glyph) { const k = 11.8 / 36; ops.push({ t: 'flower', g: m.glyph, tx: cx - 40 * k, ty: cy - 40 * k, k, mj: C.mj, mn: C.mn }); }
  // 四个字母（SF Pro Rounded）+ 极名 + 强度
  let x = L; const by = 59;
  m.axes.forEach((a) => {
    const lo = { size: 12, weight: 700, family: 'type', color: C.ink }, no = { size: 2.5, family: 'sans', color: C.ink2 };
    T(a.L, x, by, lo); T(a.name, x, by + 4.4, no);
    if (!noNum && a.strong) T(a.strong, x, by + 7.8, { size: 2.2, weight: 600, family: 'num', color: C.ink3 });
    x += Math.max(mw(a.L, lo), mw(a.name, no)) + 3.6;
  });
  // 类型名、英文名、描述（最多两行）
  let y = by + (noNum ? 22 : 20);
  T(m.zh || '', L, y, { size: 7.6, weight: 600, family: 'display', color: C.ink }); y += 5.4;
  T(m.en || '', L, y, { size: 3, weight: 500, family: 'display', color: C.ink3, ls: 0.01 }); y += 7.2;
  const lineO = { size: 2.9, family: 'sans', color: C.ink2 };
  shareWrap(m.line || '', 76, mw, lineO).slice(0, 2).forEach((s) => { T(s, L, y, lineO); y += 4.9; });
  if (!noNum && m.stats.length) {
    const sy = 101.5; ops.push({ t: 'rect', x: L, y: sy, w: R - L, h: 0.12, fill: C.line });
    const cw = (R - L - 6) / 4;
    m.stats.slice(0, 4).forEach((s, i) => { const sx = L + i * (cw + 2); T(s[0], sx, sy + 8, { size: 4.6, weight: 600, family: 'num', color: C.ink }); T(s[1], sx, sy + 11.6, { size: 2.2, family: 'sans', color: C.ink3 }); });
  }
  // 页脚：一行
  T('测测你和 AI 是哪种搭档', L, 119, { size: 2.3, weight: 600, family: 'sans', color: C.ink2 });
  T(m.foot || '', R, 119, { size: 2.1, family: 'sans', color: C.ink3, align: 'right' });
  return { ops, F };
}
const shareFam = { type: 'type', serif: 'serif', mono: 'mono', sans: 'sans' };
function shareSVG(m, dark, noNum) {
  const { ops, F } = shareOps(m, dark, noNum); const a = (v) => esc(String(v));
  const body = ops.map((o) => {
    if (o.t === 'rect') return '<rect x="' + o.x.toFixed(2) + '" y="' + o.y.toFixed(2) + '" width="' + o.w.toFixed(2) + '" height="' + o.h.toFixed(2) + '" fill="' + o.fill + '"/>';
    if (o.t === 'srect') return '<rect x="' + o.x.toFixed(2) + '" y="' + o.y.toFixed(2) + '" width="' + o.w.toFixed(2) + '" height="' + o.h.toFixed(2) + '" fill="none" stroke="' + o.stroke + '" stroke-width="' + o.sw.toFixed(3) + '"/>';
    if (o.t === 'rrect') return '<rect x="' + o.x.toFixed(2) + '" y="' + o.y.toFixed(2) + '" width="' + o.w.toFixed(2) + '" height="' + o.h + '" rx="' + o.r + '" fill="none" stroke="' + o.stroke + '" stroke-width="' + o.sw + '"/>';
    if (o.t === 'arc') { const p0 = [o.cx + o.r * Math.cos(o.a0), o.cy + o.r * Math.sin(o.a0)], p1 = [o.cx + o.r * Math.cos(o.a1), o.cy + o.r * Math.sin(o.a1)]; return '<path d="M' + p0[0].toFixed(2) + ' ' + p0[1].toFixed(2) + 'A' + o.r + ' ' + o.r + ' 0 ' + (o.a1 - o.a0 > Math.PI ? 1 : 0) + ' 1 ' + p1[0].toFixed(2) + ' ' + p1[1].toFixed(2) + '" fill="none" stroke="' + o.color + '" stroke-opacity="' + o.alpha + '" stroke-width="' + o.sw + '" stroke-linecap="round"/>'; }
    if (o.t === 'wordmark') return '<g transform="translate(' + o.x.toFixed(2) + ' ' + o.y.toFixed(2) + ') scale(' + o.k.toFixed(5) + ') translate(' + (-ORBIT_WORDMARK.vb[0]) + ' ' + (-ORBIT_WORDMARK.vb[1]) + ')" fill="' + o.fill + '" role="img" aria-label="Orbit·知音" data-wordmark="1">' + ORBIT_WORDMARK.paths.map((d) => '<path d="' + d + '"/>').join('') + '</g>';
    if (o.t === 'flower') return '<g transform="translate(' + o.tx.toFixed(2) + ' ' + o.ty.toFixed(2) + ') scale(' + o.k.toFixed(4) + ')"><path d="' + o.g.minor + '" fill="' + o.mn + '"/><path d="' + o.g.major + '" fill="' + o.mj + '"/><circle cx="40" cy="40" r="' + o.g.hr + '" fill="none" stroke="' + o.mj + '" stroke-width="1.6"/><circle cx="40" cy="40" r="1.6" fill="' + o.mj + '"/></g>';
    if (o.t === 'text') return '<text x="' + o.x.toFixed(2) + '" y="' + o.y.toFixed(2) + '" text-anchor="' + ({ center: 'middle', right: 'end' }[o.align] || 'start') + '" fill="' + o.color + '" font-size="' + o.size + '" font-weight="' + (o.weight || 400) + '"' + (o.italic ? ' font-style="italic"' : '') + (o.ls ? ' letter-spacing="' + (o.ls * o.size).toFixed(3) + '"' : '') + ' style="font-family:' + a(F[o.family || 'sans']) + '"' + (o.family === 'type' ? ' class="tcode"' : '') + '>' + a(o.s) + '</text>';
    return '';
  }).join('');
  return '<svg viewBox="0 0 100 125" width="100%" height="100%" role="img" aria-label="' + a(m.code + ' ' + (m.zh || '') + ' · ' + m.label) + '" data-code="' + a(m.code) + '" data-span="' + a(m.key || '') + '">' + body + '</svg>';
}
function shareCard(sp) {
  const m = shareModel(sp);
  return '<div class="sharecard" data-span="' + esc(String(sp.key || '')) + '"' + (sp.live ? ' data-tl="share-card"' : '') + ' style="background:' + SHARE_C[S.shareDark ? 'dark' : 'light'].bg + '">' + shareSVG(m, S.shareDark, S.shareNoNum) + '</div>';
}
// 弹窗：左边是选中的那张卡，右边列出每个时间长度的人格（小花 + 类型码 + 名称），点选切换
function shareSpanRow(k, st, on) {
  const sp = st.sp, p = sp && sp.p, tg = spanTag(k);
  const right = st.state === 'ok' ? '<span style="display:flex;flex:none">' + glyphSVG(p, 26) + '</span><span class="col" style="gap:1px;min-width:0;flex:1"><span class="row" style="gap:6px"><b class="tcode" style="font-size:13px;letter-spacing:.04em">' + esc(p.code) + '</b><span style="font-size:12.5px">' + esc(p.zh || '') + '</span></span><span class="cap" style="font-size:11px">' + esc(tg[0] + ' · ' + spanLabel(k)) + (p.n != null ? ' · ' + p.n + ' 个会话' : '') + '</span></span>'
    : '<span style="width:26px;height:26px;flex:none;border-radius:50%;border:1px dashed var(--line)"></span><span class="col" style="gap:1px;min-width:0;flex:1"><span style="font-size:12.5px">' + esc(tg[0] + ' · ' + spanLabel(k)) + '</span><span class="cap" style="font-size:11px">' + (st.state === 'pending' ? '计算中…' : esc(st.reason || '暂时不能生成')) + '</span></span>';
  return '<button type="button" role="radio" aria-checked="' + on + '" data-act="shareSpan" data-v="' + esc(k) + '" data-state="' + st.state + '" class="row" style="gap:10px;padding:7px 10px;border-radius:9px;text-align:left;width:100%;' + (on ? 'border:1.5px solid var(--ink-1);background:var(--surface)' : 'border:1px solid var(--line);background:var(--bg)') + (st.state === 'ok' ? '' : ';color:var(--ink-3)') + '">' + right + '</button>';
}
function shareBody() {
  const k = shareKey(), st = shareSpanState(k); const ks = shareSpans(); const states = ks.map((x) => (x === k ? st : shareSpanState(x)));
  const codes = new Set(states.filter((s) => s.state === 'ok').map((s) => s.sp.p.code));
  const prev = st.state === 'ok' ? shareCard(st.sp) : '<div class="sharecard" data-state="' + st.state + '" style="display:flex;align-items:center;justify-content:center;background:var(--sunken);color:var(--ink-3);font-size:13px;text-align:center;padding:24px">' + (st.state === 'pending' ? '<span class="spin" style="margin-right:8px"></span>正在生成' + esc(spanLabel(k)) + '的分享卡…' : esc(st.reason || '暂时不能生成分享卡') + '<br>换一个时间长度试试') + '</div>';
  return '<div style="flex:1 1 300px;max-width:360px;min-width:0">' + prev + '</div><div class="col" style="flex:1 1 230px;gap:14px;min-width:0">' +
    '<div class="col" style="gap:6px"><span class="eb">时间长度 · 每个长度一张卡</span><div class="col" role="radiogroup" aria-label="时间长度" style="gap:6px">' + ks.map((x, i) => shareSpanRow(x, states[i], x === k)).join('') + '</div>' +
    (codes.size > 1 ? '<span class="cap" style="font-size:11px">不同时间长度算出了 ' + codes.size + ' 种人格：短期看最近的习惯，长期看稳定的风格</span>' : '<span class="cap" style="font-size:11px">口径与「协作人格」页相同：时间窗 + Agent + 项目筛选</span>') + '</div>' +
    '<div class="col" style="gap:6px"><span class="eb">外观</span><div class="seg" role="radiogroup" aria-label="外观" style="align-self:flex-start"><button type="button" role="radio" aria-checked="' + S.shareDark + '" data-act="shareTheme" data-v="dark" class="' + (S.shareDark ? 'on' : '') + '">深色</button><button type="button" role="radio" aria-checked="' + !S.shareDark + '" data-act="shareTheme" data-v="light" class="' + (!S.shareDark ? 'on' : '') + '">浅色</button></div></div>' +
    '<div class="row" style="gap:10px">' + swBtn(S.shareNoNum, 'shareNum', '', '隐藏具体数字') + '<span style="font-size:13px">隐藏具体数字</span></div>' +
    '<div class="col" style="gap:4px;padding:10px 12px;border-radius:9px;background:var(--sunken);font-size:12px;line-height:1.55;color:var(--ink-2)"><b style="color:var(--ink-1)">包含</b>类型代号、四个维度、人格描述与这段时间的活跃日历（金句放在分享文案里）' + (S.shareNoNum ? '' : '、会话数与对话轮次') + '<b style="color:var(--ink-1);margin-top:4px">不包含</b>项目名、会话标题与任何对话原文</div></div>';
}
function shareFoot() {
  const n = shareSpans().filter((k) => shareSpanState(k).state === 'ok').length;
  return '<button type="button" class="btn" data-act="shareCopy">' + ic('copy', 13) + '复制分享文案</button><button type="button" class="btn" data-act="shareSaveAll"' + (n > 1 ? '' : ' disabled') + '>' + ic('down', 13) + '全部保存' + (n > 1 ? '（' + n + ' 张）' : '') + '</button><button type="button" class="btn p" data-act="shareSave">' + ic('down', 13) + '保存图片</button>';
}
// 重画弹窗内容并同步按钮：选中的卡还没好时「保存 / 复制」不可用，#shareBody 标 data-tl="share-pending"
function shareRefresh() {
  const b = $('#shareBody'); if (!b) return;
  const st = shareSpanState(shareKey()); b.innerHTML = shareBody();
  if (st.state === 'pending') { b.setAttribute('data-tl', 'share-pending'); b.setAttribute('aria-busy', 'true'); } else { b.removeAttribute('data-tl'); b.removeAttribute('aria-busy'); }
  const f = $('#shareFoot'); if (f) f.innerHTML = shareFoot();
  ['shareCopy', 'shareSave'].forEach((a) => { const el = $('#modal [data-act="' + a + '"]'); if (el) el.disabled = st.state !== 'ok'; });
}
function shareSheet() {
  openModal(modalHead('导出分享卡', '1080 × 1350 · 每个时间长度一张 · 适合朋友圈、小红书与 X') + '<div class="mb" id="shareBody" style="display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start"></div><div class="mf" id="shareFoot"></div>', 'wide');
  shareRefresh();
}
function openShare() {
  S.shareSpan = null; const ks = shareSpans(); const ok = ks.filter((k) => shareSpanState(k).state === 'ok');
  if (!ok.length) { toast('所选范围还没有会话，暂时不能生成分享卡'); return; }
  S.shareSpan = ok.indexOf(shareKey()) >= 0 ? shareKey() : ok[0];
  shareSheet(); MODAL_KEY = 'share';
}
function shareText(sp) { const p = sp.p; const q = sp.q || SHAREQ[p.code] || SHAREQ0; return '「' + q.join('') + '」' + '我的 AI 协作人格（' + sp.label + '）是 ' + p.code + '「' + p.zh + '」：' + (p.line || '') + (S.shareNoNum || p.n == null ? '' : '（' + p.n + ' 个会话）') + ' —— 来自 Orbit，全部分析在本机完成。'; }
const shareFile = (m) => 'orbit-persona-' + ({ '7': '7d', '30': '30d', '90': '90d', all: 'all' }[m.key] || m.key) + '-' + m.code + '-' + expStamp() + '.png';
function shareSaveOne(sp) { const m = shareModel(sp); return sharePNG(m, S.shareDark, S.shareNoNum).then((b64) => expSave(shareFile(m), 'image/png', { base64: b64 }), (e) => { toast('生成图片失败：' + (e && e.message || e)); return { ok: false }; }); }
Object.assign(ACT, {
  repSec: (el) => { const k = el.dataset.k; if (el.checked) S.rep.add(k); else S.rep.delete(k); CUR.report = reportMD(); const t = $('#repText'); if (t) t.value = CUR.report; },
  repCopy: () => copyText(CUR.report || reportMD(), '报告'),
  copyCSV: () => copyText(CUR.csv || '', 'CSV'),
  shareSpan: (el) => { S.shareSpan = el.dataset.v; shareRefresh(); },
  shareTheme: (el) => { S.shareDark = el.dataset.v === 'dark'; shareRefresh(); },
  shareNum: () => { S.shareNoNum = !S.shareNoNum; shareRefresh(); },
  shareCopy: () => { const st = shareSpanState(shareKey()); if (st.state === 'ok') copyText(shareText(st.sp), '分享文案'); },
  shareSave: () => { const st = shareSpanState(shareKey()); if (st.state === 'ok') shareSaveOne(st.sp); },
  // 每个时间长度各存一张（依次保存，文件名带长度：orbit-persona-7d-DIMV-日期.png）
  shareSaveAll: async () => { const sps = shareSpans().map(shareSpanState).filter((st) => st.state === 'ok').map((st) => st.sp); for (const sp of sps) { const r = await shareSaveOne(sp); if (r && (r.cancelled || r.ok === false)) break; } }
});
/* ---- saving exports (live / native): ORBIT.native.request('save') → orbit:saved; the browser fallback downloads a Blob.
   A saved file gets a toast with「在 Finder 中显示」(reveal). Used by 98-live-ops.js; the mock demo keeps its copy buttons. */
function expStamp() { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function expSave(filename, mime, data) {
  const payload = Object.assign({ filename, mime }, data);
  return ORBIT.native.request('save', payload, { timeoutMs: 120000 }).then((r) => {
    r = r || {};
    if (r.cancelled) return r;
    if (r.ok === false) { toast('保存失败：' + (r.error || '未知错误')); return r; }
    if (r.path) toast('已保存 ' + filename, { act: '在 Finder 中显示', onAct: () => ORBIT.native.request('reveal', { path: r.path }) });
    else toast('已下载 ' + filename);
    return r;
  }, (e) => { toast('保存失败：' + ((e && (e.message || e.code)) || '未知错误')); return { ok: false }; });
}
async function sharePNG(m, dark, noNum) {
  try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch (e) { /* fonts optional */ }
  const W = 1080, H = 1350, u = W / 100; const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const x = cv.getContext('2d'); const { ops, F } = shareOps(m, dark, noNum); x.textBaseline = 'alphabetic';
  ops.forEach((o) => {
    x.save();
    if (o.t === 'rect') { x.fillStyle = o.fill; x.fillRect(o.x * u, o.y * u, o.w * u, Math.max(1, o.h * u)); }
    else if (o.t === 'srect') { x.strokeStyle = o.stroke; x.lineWidth = o.sw * u; x.strokeRect(o.x * u, o.y * u, o.w * u, o.h * u); }
    else if (o.t === 'rrect') { const r = o.r * u, X = o.x * u, Y = o.y * u, Wd = o.w * u, Hh = o.h * u; x.beginPath(); x.moveTo(X + r, Y); x.arcTo(X + Wd, Y, X + Wd, Y + Hh, r); x.arcTo(X + Wd, Y + Hh, X, Y + Hh, r); x.arcTo(X, Y + Hh, X, Y, r); x.arcTo(X, Y, X + Wd, Y, r); x.closePath(); x.strokeStyle = o.stroke; x.lineWidth = o.sw * u; x.stroke(); }
    else if (o.t === 'arc') { x.globalAlpha = o.alpha; x.strokeStyle = o.color; x.lineWidth = o.sw * u; x.lineCap = 'round'; x.beginPath(); x.arc(o.cx * u, o.cy * u, o.r * u, o.a0, o.a1); x.stroke(); }
    else if (o.t === 'wordmark' && typeof Path2D === 'function') { x.translate(o.x * u, o.y * u); x.scale(o.k * u, o.k * u); x.translate(-ORBIT_WORDMARK.vb[0], -ORBIT_WORDMARK.vb[1]); x.fillStyle = o.fill; ORBIT_WORDMARK.paths.forEach((d) => x.fill(new Path2D(d))); }
    else if (o.t === 'flower' && typeof Path2D === 'function') {
      x.translate(o.tx * u, o.ty * u); x.scale(o.k * u, o.k * u);
      x.fillStyle = o.mn; x.fill(new Path2D(o.g.minor)); x.fillStyle = o.mj; x.fill(new Path2D(o.g.major));
      x.strokeStyle = o.mj; x.lineWidth = 1.6; x.beginPath(); x.arc(40, 40, o.g.hr, 0, Math.PI * 2); x.stroke(); x.beginPath(); x.arc(40, 40, 1.6, 0, Math.PI * 2); x.fill();
    } else if (o.t === 'text') {
      x.font = (o.italic ? 'italic ' : '') + (o.weight || 400) + ' ' + o.size * u + 'px ' + F[o.family || 'sans']; x.fillStyle = o.color; x.textAlign = o.align || 'left';
      if ('letterSpacing' in x) x.letterSpacing = o.ls ? (o.ls * o.size * u).toFixed(1) + 'px' : '0px';
      x.fillText(o.s, o.x * u, o.y * u);
    }
    x.restore();
  });
  return cv.toDataURL('image/png').split(',')[1];
}
