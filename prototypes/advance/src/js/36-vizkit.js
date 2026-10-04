/* ============ VZ · shared visualization kit ============
 *
 * 用法（页面）：
 *   PAGES.foo = () => '… <div class="vz" data-vz="trend"></div> …';
 *   PAGES.foo.after = () => VZ.mount($('[data-vz="trend"]'), spec);
 * 组件按容器实际像素宽度与 spec.height 渲染 SVG：文字、线宽、点大小恒定像素，不随宽度缩放。
 * 容器尺寸变化（ResizeObserver）或 window 'orbit:layout' 事件触发时自动重绘。
 *
 * 入口：
 *   VZ.mount(el | selector, spec) -> inst       挂载/更新；el 需有可测量宽度；返回实例 { el, spec, hidden, focus, redraw() }
 *   VZ.svg(spec, w, h) -> string                同一 spec 直接得到 <svg> 字符串（测试、导出、分享卡）
 *   VZ.html(spec, w, h) -> string               图例 + svg + tooltip 容器（无交互绑定）
 *   VZ.table(spec) -> string                    表格视图（与图表同数据；每种类型都有）
 *   VZ.setView(el, 'chart' | 'table')           图表 ↔ 表格切换（也可直接 spec.view）
 *   VZ.spark(values, opt) / VZ.kpi(opt)         迷你趋势线 / KPI tile（返回 HTML，不必 mount）
 *   VZ.color(i)                                 第 i 个系列的颜色：var(--a1..--a5)；第 6 个起折叠为灰色「其他」
 *   VZ.sem                                      语义色 { err 失败, corr 纠偏/异常, good 改善, neg/pos 情绪发散, accent 选中, bar/barStrong 中性条 }
 *   VZ.fmt(v, f), VZ.ticks(a, b, n), VZ.timeTicks(t0, t1, px), VZ.scale.linear/band, VZ.time.*, VZ.delta2(d)  工具函数
 *
 * 所有类型共用的 spec 字段：
 *   type       见下表                          title     图表名（写进 <title> 与 aria-label）
 *   desc       aria 补充说明                    height    绘图区高度 px（含坐标轴；默认按类型）
 *   legend     false 隐藏；'top'|'bottom'（默认 top；单系列自动不显示）。点击 = 显示/隐藏，⌥ 点击 = 只看该系列，悬停 = 其他淡出
 *   hidden     初始隐藏的系列名数组              view      'chart' | 'table'
 *   empty      空数据文案（默认「暂无数据」）     minN / n  样本门槛：n < minN 时显示「样本不足 n / minN」
 *   head       { eyebrow, title, sub, evidence: { label, act, attrs }, right }  图表头（VZ.head；等宽眉标 + 结论句标题 + 口径说明）
 *   animate    false 关闭首次绘制的入场动画（线描入、柱升起、点弹出；prefers-reduced-motion 下自动关闭）
 *   onHover(i, d) onSelect(i, d) onBrush([a, b], meta) onLegend(name, visible, { hidden }) onFocus(i, d)  回调
 *   brush      true 允许在绘图区拖选（line/area/bar/histogram/timeline/scatter）
 *   selected   当前选中项（索引或 id），用描边高亮
 *   refs       [{ y, label, color }]           横向参考线（目标线）
 *   bands      [{ from, to, label }]           x 区间带（如「安装后」）
 *   marks      [{ x, label }]                  x 竖线标注
 *   notes      [{ i | x, y, text, series }]    callout 标注
 *   x          { values: [...], type: 'band' | 'time' | 'linear', label, format }   time 用毫秒时间戳；band 用文字
 *   y          { min, max, zero, label, format, ticks }   format: 'int' | '1f' | 'pct' | 'k' | 函数 | '{v} h'
 *
 * 类型与专有字段：
 *   line / area   series: [{ name, values: [n|null], color, band: [[lo, hi]], dash, width, area }]，curve: 'monotone'，endLabels，points
 *   bar           series 同上；stacked，horizontal，err: 每系列 { err: [n] } 误差；x.values 为类别；labels: true | 'max'；hatch: [i] 斜纹标未完成的桶
 *   histogram     values: [n]，bins（数量）或 edges: [n]，format；marks 可标均值
 *   diverging     rows: [{ name, value, left, right, ref }]，domain: [-1, 1]，colors: [负, 正]（默认情绪发散色），deadband: [a, b] 中间「未定型」带，format
 *   ranked        rows: [{ name, value, share, meta, flag, id }]，top（前 k 深色、其余浅灰），format，barH（默认 8）
 *   share         items: [{ name, value, color }]，单条 100% 比例条 + 图例
 *   bullet        rows: [{ name, value, target, ranges: [q1, q2, q3], format }]，max
 *   dumbbell      rows: [{ name, a, b, id }]，labels: ['安装前', '安装后']，format，goodDown
 *   slope         同 dumbbell 字段，纵向两列对比
 *   heatmap       rows: [str]，cols: [str]，values: [[n]]，ramp: 'gray' | 'accent' | 'err' | 'corr' | 'good' | 'mood'（发散，值域自动对称）| 任意 var()，showValues，peak，cellMax，format，min / max
 *                 layout: 'calendar' 时 days: [{ t, v }]（t 毫秒）
 *   scatter       points: [{ x, y, r, label, id, color, series }]，fit（回归 + 95% CI），nUnit（拟合说明里样本数的单位，默认「个点」），labels，rMax，x/y 同上
 *   dist          rows: [{ name, values: [n] }]，mode: 'box' | 'dots'，format，nUnit（右侧样本数的单位，默认「个」）
 *   flow          nodes: [{ id, name, col }]，links: [{ from, to, value }]，format
 *   timeline      lanes: [{ id, label, h, color, mode: 'density' }]，events: [{ lane, t, t2, kind: 'tick' | 'dot' | 'ring' | 'span', color, label, sub, detail, err, id, dim, cat（密度桶悬停按类别计数）}]
 *                 range: [t0, t1]，unit: 'ms' | 'min'（min 时 start 为起始时刻的分钟数，刻度显示 HH:MM），playhead（之后的事件变淡），now（运行中：竖线 + 脉冲点）
 *                 spans: [{ t, t2, label, short, tip, color, inferred }] 阶段带（label 放不下退到 short；tip 为原生悬停说明）；markers: [{ t, label, n, alert }] 关键时刻徽章（相距 < 20px 自动合并成簇）
 *                 mode: 'density' 的泳道把事件按 bucket px（默认 4）聚合成密度块（高度对数、失败叠红），hover 列出桶内事件
 *                 onSelect(i, d)：d 为事件本身，或 { bucket: true, lane, t0, t1, n, err, events }，或 { marker: true, t, markers }
 *                 axisMode: 'time' | 'steps'（事件等距、跨度固定 1 步、刻度每 k 步）；zoom: false 关闭 ⌘/Ctrl + 滚轮以光标为锚的缩放（1 – maxZoom，默认 12 倍）；
 *                 缩放改写 spec.range 并把全程记在 spec.extent，触发 onView(range | null, { zoom, full })；⇧ + 滚轮平移
 *                 回放：playhead 可拖动（snap: false 关闭吸附），onPlayhead(t, { done })；VZ.playhead(el, t, { playing }) 逐帧定位不重绘；
 *                 VZ.replay(el, { ms: 8000, rate, realtime, onTick, onDone }) 内置 rAF 回放（Space 播放 / 暂停，[ ] 逐事件；spec.onPlay(play) 可接管）
 *   minimap       range，events: [{ t, err, user }]（或 density: [n]），window: [a, b]（当前视窗，null = 全程），bins，axis，onView(range | null, { px, done, full })
 *                 总览条：密度面积 + 失败刻 + 你的消息点 + 可拖视窗（拖动平移、拖手柄缩放、点空白跳转、双击 / Home 复位、← → 平移、↑ ↓ 缩放）
 *   multiples     items: [{ title, spec }]，minW，shareY，height
 *   spark         values: [n]（也可 VZ.spark(values, { w: 80, h: 24, area, bars, color, last, ref, label }) 直接得到 HTML；默认 --ink-3 线 + 强调色末点）
 *   kpi           VZ.kpi({ label, value, unit, delta: { cur, prev, unit: 'pct' | 'pt' | 'x', goodDown }, trend, trendLabel, sub, act, tip })：环比 = ▲▼ + 变化量 + 上期值
 *
 * 颜色只用 CSS 变量：系列色 --a1..--a5 只表示 Agent 身份；语义色走 VZ.sem（--vz-err / --vz-corr / --vz-good / --vz-mood-neg / --vz-mood-pos，缺省回落主题色）；
 * 强调色 var(--accent) 在外壳里就是墨色（单色控件体系，蓝色只留给焦点环），只用于选中 / 当前 / 刷选 / 迷你线末点；AI 紫 --ai；灰阶 --h0..--h5；墨色 --ink-1..4；单系列条默认中性灰。
 * 文字永远用墨色（--ink-*），颜色只落在图元上；浅深色自动适配；reduced-motion 下无过渡。
 */
const VZ = { types: {}, _inst: new WeakMap(), ACC: 'var(--accent, #17181b)', _uid: 0 };
// 语义色（评审 §4：一个颜色只对应一个含义）。值是 36-viz.css 的 --vz-* 变量，缺省回落到主题的 crit / good 与琥珀 / 冷紫 / 青绿。
VZ.sem = { err: 'var(--vz-err)', corr: 'var(--vz-corr)', good: 'var(--vz-good)', neg: 'var(--vz-mood-neg)', pos: 'var(--vz-mood-pos)', accent: 'var(--accent, #17181b)', bar: 'var(--ink-4)', barStrong: 'var(--ink-3)' };
// 第 i 个系列的颜色；传入系列总数 n === 1 时（单一度量的柱 / 条）用中性 --ink-3，Agent 五色只表示身份（评审 G-03）
VZ.color = (i, s, n) => (s && s.color) || (n === 1 ? 'var(--ink-3)' : i < 5 ? 'var(--a' + (i + 1) + ')' : 'var(--h3)');
// 斜纹（未完成的末桶、推断值）：每张 svg 自带一份 <pattern>，id 唯一
VZ.hatchId = () => 'vzh' + (VZ._uid++);
VZ.hatchDefs = (id) => '<defs><pattern id="' + id + '" patternUnits="userSpaceOnUse" width="5" height="5" patternTransform="rotate(45)"><line class="vz-hatch-ln" x1="0" y1="0" x2="0" y2="5"/></pattern></defs>';
VZ.num = (v) => (typeof v === 'number' && Number.isFinite(v)) ? v : null;
VZ.r1 = (v) => Math.round(v * 10) / 10;
// 文字宽度估算（px）。mono = true 按等宽字体（刻度、数值用 var(--font-num)：ASCII 0.6em，中日韩 1em）；否则按 SF / 苹方的比例字体
VZ.tw = (s, size, mono) => { s = String(s == null ? '' : s); let w = 0; for (const ch of s) { const c = ch.charCodeAt(0); if (mono) { w += c > 0x2e7f ? 1 : c >= 0x2000 && c <= 0x2bff ? 0.8 : 0.6; continue; } w += c > 0x2e7f ? 1 : c >= 0x2000 && c <= 0x2bff ? (c === 0x2022 || c === 0x2013 ? 0.5 : 0.8) : /[0-9]/.test(ch) ? 0.64 : /[A-Z%@#]/.test(ch) ? 0.74 : /[ .,:·/|'()\[\]]/.test(ch) ? 0.32 : /[mwMW]/.test(ch) ? 0.9 : 0.56; } return w * (size || 11); };
VZ.twm = (s, size) => VZ.tw(s, size, true);
VZ.tickFmt = (f) => (v) => ((f === '1f' || f === '2f') && Number.isInteger(v)) ? VZ.fmt(v) : VZ.fmt(v, f);
VZ.fmt = function (v, f) {
  if (v == null || !Number.isFinite(v)) return '—';
  if (typeof f === 'function') return f(v);
  if (f === 'int') return Math.round(v).toLocaleString('en-US');
  if (f === '1f') return (Math.round(v * 10) / 10).toFixed(1);
  if (f === '2f') return v.toFixed(2);
  if (f === 'pct') return (Math.abs(v) < 10 && v % 1 ? (Math.round(v * 10) / 10) : Math.round(v)) + '%';
  if (f === 'signed') return v === 0 ? '0' : (v > 0 ? '+' : '−') + VZ.fmt(Math.abs(v), '1f');
  if (f === 'k') return Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : Math.abs(v) >= 1e4 ? (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k' : VZ.fmt(v);
  if (typeof f === 'string' && f.includes('{v}')) return f.replace('{v}', VZ.fmt(v));
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (Number.isInteger(v)) return v.toLocaleString('en-US');
  return Math.abs(v) >= 100 ? Math.round(v).toLocaleString('en-US') : (Math.round(v * 10) / 10).toString();
};
VZ.tickStep = function (a, b, n) {
  const span = Math.abs(b - a) || 1; const raw = span / Math.max(1, n);
  const p = Math.pow(10, Math.floor(Math.log10(raw))); const e = raw / p;
  return p * (e >= 5 ? 10 : e >= 2 ? 5 : e >= 1 ? 2 : 1);
};
VZ.ticks = function (a, b, n) {
  if (!(b > a)) return [a];
  const st = VZ.tickStep(a, b, n || 5); const out = [];
  for (let v = Math.ceil(a / st) * st; v <= b + st * 1e-6; v += st) out.push(+v.toFixed(10));
  return out;
};
VZ.nice = function (a, b, n) {
  if (a === b) { a = a > 0 ? 0 : a - 1; b = b > 0 ? b + 1 : b === 0 ? 1 : 0; }
  const st = VZ.tickStep(a, b, n || 5);
  return [Math.floor(a / st) * st, Math.ceil(b / st) * st];
};
VZ.scale = {
  linear: (d0, d1, r0, r1) => { const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0); const f = (v) => r0 + (v - d0) * k; f.inv = (p) => k ? d0 + (p - r0) / k : d0; return f; },
  band: (n, r0, r1) => { const step = n ? (r1 - r0) / n : 0; const f = (i) => r0 + step * (i + 0.5); f.step = step; f.inv = (p) => Math.max(0, Math.min(n - 1, Math.floor((p - r0) / (step || 1)))); return f; }
};
VZ.time = {
  M: 60000, H: 3600000, D: 86400000,
  pad: (n) => String(n).padStart(2, '0'),
  local: (t) => new Date(t + 8 * 3600000),
  md: (t) => { const d = VZ.time.local(t); return (d.getUTCMonth() + 1) + '/' + d.getUTCDate(); },
  hm: (t) => { const d = VZ.time.local(t); return VZ.time.pad(d.getUTCHours()) + ':' + VZ.time.pad(d.getUTCMinutes()); },
  ymd: (t) => { const d = VZ.time.local(t); return d.getUTCFullYear() + '-' + VZ.time.pad(d.getUTCMonth() + 1) + '-' + VZ.time.pad(d.getUTCDate()); },
  wd: (t) => '日一二三四五六'[VZ.time.local(t).getUTCDay()],
  scale: (t0, t1, x0, x1) => VZ.scale.linear(t0, t1, x0, x1)
};
// 时间轴刻度：按像素宽度挑选小时 / 日 / 周 / 月间隔，保证相邻刻度 >= 64px。
VZ.timeTicks = function (t0, t1, px, opt) {
  opt = opt || {}; const T = VZ.time; const span = Math.max(1, t1 - t0); const out = [];
  if (opt.unit === 'min') {
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 240]; const minPx = 56;
    const st = steps.find((s) => s / span * px >= minPx) || steps[steps.length - 1];
    const start = opt.start || 0;
    for (let m = Math.ceil(t0 / st) * st; m <= t1; m += st) { const abs = start + m; out.push({ t: m, label: T.pad(Math.floor(abs / 60) % 24) + ':' + T.pad(Math.round(abs % 60)), major: m % (st * 2) === 0 }); }
    return out;
  }
  const units = [[T.H, 'h'], [T.H * 3, 'h'], [T.H * 6, 'h'], [T.H * 12, 'h'], [T.D, 'd'], [T.D * 2, 'd'], [T.D * 7, 'w'], [T.D * 14, 'w'], [T.D * 30.4, 'm'], [T.D * 91, 'm']];
  const minPx = { h: 52, d: 56, w: 56, m: 40 };
  const pick = units.find((u) => u[0] / span * px >= minPx[u[1]]) || units[units.length - 1];
  const step = pick[0], kind = pick[1];
  let t = kind === 'h' ? Math.ceil(t0 / step) * step : (() => { const d = T.local(t0); d.setUTCHours(0, 0, 0, 0); let s = d.getTime() - 8 * 3600000; if (kind === 'w') { const w = (T.local(s).getUTCDay() + 6) % 7; s += (7 - w) % 7 * T.D; } if (kind === 'm') { const m = T.local(s); s = Date.UTC(m.getUTCFullYear(), m.getUTCMonth() + 1, 1) - 8 * 3600000; } return s < t0 ? s + (kind === 'w' ? T.D * 7 : kind === 'm' ? T.D * 30 : step) : s; })();
  let guard = 0;
  while (t <= t1 && guard++ < 400) {
    const d = T.local(t);
    const label = kind === 'h' ? (d.getUTCHours() === 0 ? T.md(t) : T.hm(t)) : kind === 'm' ? (d.getUTCMonth() + 1) + ' 月' : T.md(t);
    out.push({ t, label, major: kind === 'h' ? d.getUTCHours() === 0 : kind === 'm' ? d.getUTCMonth() === 0 : d.getUTCDate() <= 7 });
    if (kind === 'm') { t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + (step > T.D * 60 ? 3 : 1), 1) - 8 * 3600000; } else t += step;
  }
  return out;
};
VZ.esc = (s) => esc(s);
VZ.attr = (o) => Object.keys(o).map((k) => o[k] == null || o[k] === false ? '' : ' ' + k + '="' + esc(o[k]) + '"').join('');
VZ.el = (tag, attrs, inner) => '<' + tag + VZ.attr(attrs || {}) + (inner == null ? '/>' : '>' + inner + '</' + tag + '>');
VZ.txt = (x, y, s, o) => VZ.el('text', Object.assign({ x: VZ.r1(x), y: VZ.r1(y) }, o || {}), esc(s));
// 上端圆角的柱（基线平、数据端 4px 圆角）；dir: 'up' | 'down' | 'right' | 'left'
VZ.barPath = function (x, y, w, h, dir, r) {
  r = Math.min(r == null ? 4 : r, w / 2, h / 2); if (w <= 0 || h <= 0) return '';
  const R = VZ.r1; const x2 = x + w, y2 = y + h;
  if (dir === 'down') return 'M' + R(x) + ' ' + R(y) + 'H' + R(x2) + 'V' + R(y2 - r) + 'Q' + R(x2) + ' ' + R(y2) + ' ' + R(x2 - r) + ' ' + R(y2) + 'H' + R(x + r) + 'Q' + R(x) + ' ' + R(y2) + ' ' + R(x) + ' ' + R(y2 - r) + 'Z';
  if (dir === 'right') return 'M' + R(x) + ' ' + R(y) + 'H' + R(x2 - r) + 'Q' + R(x2) + ' ' + R(y) + ' ' + R(x2) + ' ' + R(y + r) + 'V' + R(y2 - r) + 'Q' + R(x2) + ' ' + R(y2) + ' ' + R(x2 - r) + ' ' + R(y2) + 'H' + R(x) + 'Z';
  if (dir === 'left') return 'M' + R(x2) + ' ' + R(y) + 'H' + R(x + r) + 'Q' + R(x) + ' ' + R(y) + ' ' + R(x) + ' ' + R(y + r) + 'V' + R(y2 - r) + 'Q' + R(x) + ' ' + R(y2) + ' ' + R(x + r) + ' ' + R(y2) + 'H' + R(x2) + 'Z';
  return 'M' + R(x) + ' ' + R(y2) + 'V' + R(y + r) + 'Q' + R(x) + ' ' + R(y) + ' ' + R(x + r) + ' ' + R(y) + 'H' + R(x2 - r) + 'Q' + R(x2) + ' ' + R(y) + ' ' + R(x2) + ' ' + R(y + r) + 'V' + R(y2) + 'Z';
};
VZ.linePath = function (pts, curve) {
  // pts: [[x, y] | null]；null 断开。curve === 'monotone' 用 Fritsch–Carlson 单调三次样条，不越过数据点。
  const segs = []; let cur = [];
  pts.forEach((p) => { if (p) cur.push(p); else if (cur.length) { segs.push(cur); cur = []; } });
  if (cur.length) segs.push(cur);
  const R = VZ.r1;
  return segs.map((s) => {
    if (s.length === 1) return 'M' + R(s[0][0]) + ' ' + R(s[0][1]) + 'h0.01';
    if (curve !== 'monotone' || s.length < 3) return 'M' + s.map((p) => R(p[0]) + ' ' + R(p[1])).join('L');
    const n = s.length, dx = [], dy = [], m = [];
    for (let i = 0; i < n - 1; i++) { dx.push(s[i + 1][0] - s[i][0]); dy.push(s[i + 1][1] - s[i][1]); m.push(dx[i] ? dy[i] / dx[i] : 0); }
    const t = [m[0]]; for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2); t.push(m[n - 2]);
    for (let i = 0; i < n - 1; i++) { if (!m[i]) { t[i] = 0; t[i + 1] = 0; continue; } const a = t[i] / m[i], b = t[i + 1] / m[i]; const h = Math.hypot(a, b); if (h > 3) { t[i] = 3 * m[i] * a / h; t[i + 1] = 3 * m[i] * b / h; } }
    let d = 'M' + R(s[0][0]) + ' ' + R(s[0][1]);
    for (let i = 0; i < n - 1; i++) { const h = dx[i] / 3; d += 'C' + R(s[i][0] + h) + ' ' + R(s[i][1] + t[i] * h) + ' ' + R(s[i + 1][0] - h) + ' ' + R(s[i + 1][1] - t[i + 1] * h) + ' ' + R(s[i + 1][0]) + ' ' + R(s[i + 1][1]);
    }
    return d;
  }).join('');
};
VZ.defaultH = { line: 200, area: 200, bar: 200, histogram: 160, diverging: 0, ranked: 0, share: 44, bullet: 0, dumbbell: 0, slope: 220, heatmap: 0, scatter: 260, dist: 0, flow: 220, timeline: 0, multiples: 0, spark: 24 };
VZ.vis = (spec, inst) => (spec.series || []).map((s, i) => !(inst && inst.hidden.has(s.name == null ? String(i) : s.name)));
VZ.isEmpty = function (spec) {
  const t = VZ.types[spec.type];
  if (t && t.isEmpty) return t.isEmpty(spec);
  const ser = spec.series || []; const vals = spec.values || spec.points || spec.rows || spec.items || spec.events || spec.links || spec.days;
  if (ser.length) return !ser.some((s) => (s.values || []).some((v) => VZ.num(v && v.y !== undefined ? v.y : v) != null));
  return !vals || !vals.length;
};
// empty text: spec.empty or 「暂无数据」; the app may replace it (live: 正在分析… while nothing is published yet, F08)
VZ.emptyText = (spec) => spec.empty || '暂无数据';
VZ.lowSample = (spec) => spec.minN != null && spec.n != null && spec.n < spec.minN;
/* ---------- 共享坐标框架：左轴刻度、网格、x 轴标签、x 定位 ---------- */
VZ.frame = function (spec, w, h, o) {
  // o: { domain: [y0, y1], fmtY, left, right, top, bottom, noX, noY, xLabels: [{ label, i | t | v }], xType }
  o = o || {};
  const fmtY = o.fmtY || VZ.tickFmt(spec.y && spec.y.format);
  let [y0, y1] = o.domain || [0, 1];
  if (!(y1 > y0)) { y1 = y0 + 1; }
  const yTicksN = (spec.y && spec.y.ticks) || Math.max(2, Math.min(6, Math.floor((h - 30) / 36)));
  const ticks = o.noY ? [] : VZ.ticks(y0, y1, yTicksN);
  const tickW = o.noY ? 0 : Math.max(0, ...ticks.map((v) => VZ.twm(fmtY(v), 11)));
  const left = o.left != null ? o.left : Math.ceil(tickW) + 10;
  const top = o.top != null ? o.top : 10;
  const bottom = o.bottom != null ? o.bottom : (o.noX ? 6 : 22);
  const right = o.right != null ? o.right : 10;
  const F = { x0: left, x1: Math.max(left + 10, w - right), yT: top, yB: Math.max(top + 10, h - bottom), w, h };
  F.pw = F.x1 - F.x0; F.ph = F.yB - F.yT;
  F.y = VZ.scale.linear(y0, y1, F.yB, F.yT); F.y0 = y0; F.y1 = y1; F.ticks = ticks; F.fmtY = fmtY;
  return F;
};
VZ.grid = function (F, o) {
  o = o || {}; let g = ''; let prev = null;
  F.ticks.forEach((v) => { const y = VZ.r1(F.y(v)); const base = Math.abs(v) < 1e-9; const lbl = F.fmtY(v); g += '<line class="vz-grid' + (base ? ' vz-base' : '') + '" x1="' + F.x0 + '" x2="' + F.x1 + '" y1="' + y + '" y2="' + y + '"/>' + (lbl === prev ? '' : VZ.txt(F.x0 - 6, y + 3.5, lbl, { class: 'vz-ax', 'text-anchor': 'end' })); prev = lbl; });
  if (!F.ticks.some((v) => Math.abs(v) < 1e-9) && !o.noBase) g += '<line class="vz-base" x1="' + F.x0 + '" x2="' + F.x1 + '" y1="' + VZ.r1(F.yB) + '" y2="' + VZ.r1(F.yB) + '"/>';
  return g;
};
// x 轴：items [{ x, label, major }]；按实际标签宽度抽稀：主刻度（major）先保留，其余从左到右加入且不与已保留的重叠。
VZ.axisX = function (F, items, o) {
  o = o || {}; if (!items.length) return '';
  const y = F.yB + (o.dy || 15); const tw = (it) => VZ.twm(it.label, 11);
  let keep;
  if (o.every) keep = items.filter((it, i) => i % o.every === 0 || (o.keepMajor && it.major));
  else { const sel = items.filter((it) => it.major); const fits = (it) => sel.every((k) => k === it || Math.abs(k.x - it.x) >= (tw(k) + tw(it)) / 2 + 10); items.forEach((it) => { if (!it.major && fits(it)) sel.push(it); }); keep = items.filter((it) => sel.includes(it)); }
  let g = '';
  keep.forEach((it) => {
    const anchor = o.anchor || 'middle'; let x = it.x;
    if (anchor === 'middle') { const tw = VZ.twm(it.label, 11) + 4; x = Math.max(F.x0 + tw / 2 - 4, Math.min(F.x1 - tw / 2 + 2, x)); }
    g += (o.tick ? '<line class="vz-tick" x1="' + VZ.r1(it.x) + '" x2="' + VZ.r1(it.x) + '" y1="' + VZ.r1(F.yB) + '" y2="' + VZ.r1(F.yB + 4) + '"/>' : '') + VZ.txt(x, y, it.label, { class: 'vz-ax' + (it.major ? ' vz-major' : ''), 'text-anchor': anchor });
  });
  if (o.label) g += VZ.txt(F.x1, F.yB - 6, o.label, { class: 'vz-axl', 'text-anchor': 'end' });
  return g;
};
// 解析 x：返回 { type, xs: [像素], items: 轴标签, at(i) }
VZ.xaxis = function (spec, F, n, o) {
  o = o || {}; const X = spec.x || {}; const vals = X.values || [];
  const type = X.type || (vals.length && typeof vals[0] === 'number' && vals[0] > 1e11 ? 'time' : vals.length && typeof vals[0] === 'number' ? 'linear' : 'band');
  const fmtX = X.format;
  if (type === 'band' || o.band) {
    const sc = VZ.scale.band(n, F.x0, F.x1);
    const xs = Array.from({ length: n }, (_, i) => sc(i));
    const items = xs.map((x, i) => ({ x, label: typeof fmtX === 'function' ? fmtX(vals[i], i) : String(vals[i] == null ? i + 1 : vals[i]) }));
    return { type: 'band', xs, items, step: sc.step, inv: sc.inv, sc };
  }
  const nums = vals.map((v) => +v); let a = Math.min(...nums), b = Math.max(...nums); if (!(b > a)) { b = a + 1; }
  if (type === 'linear' && X.nice !== false) { [a, b] = VZ.nice(a, b, 6); }
  if (X.min != null) a = X.min; if (X.max != null) b = X.max;
  const sc = VZ.scale.linear(a, b, F.x0, F.x1); const xs = nums.map((v) => sc(v));
  const items = type === 'time' ? VZ.timeTicks(a, b, F.pw, { unit: X.unit, start: X.start }).map((t) => ({ x: sc(t.t), label: t.label, major: t.major })) : VZ.ticks(a, b, Math.max(2, Math.floor(F.pw / 70))).map((v) => ({ x: sc(v), label: typeof fmtX === 'function' ? fmtX(v) : VZ.fmt(v, fmtX) }));
  return { type, xs, items, step: n > 1 ? F.pw / (n - 1) : F.pw, inv: (p) => { const v = sc.inv(p); let best = 0, bd = Infinity; nums.forEach((x, i) => { const d = Math.abs(x - v); if (d < bd) { bd = d; best = i; } }); return best; }, sc, domain: [a, b] };
};
VZ.bandsAndMarks = function (spec, F, XA) {
  // x 区间带与竖线标注（bands / marks）；x 用索引（band）或值（time/linear）
  let g = ''; const px = (x) => XA.type === 'band' ? XA.xs[Math.max(0, Math.min(XA.xs.length - 1, Math.round(x)))] : XA.sc(x);
  const lbl = (x, text) => { const tw = VZ.tw(text, 11); return x + 4 + tw <= F.x1 ? VZ.txt(x + 4, F.yT + 11, text, { class: 'vz-note' }) : VZ.txt(Math.min(F.x1, Math.max(x - 4, F.x0 + tw)), F.yT + 11, text, { class: 'vz-note', 'text-anchor': 'end' }); };
  (spec.bands || []).forEach((b) => { const a = px(b.from), c = px(b.to); const x = Math.min(a, c) - (XA.type === 'band' ? XA.step / 2 : 0), ww = Math.abs(c - a) + (XA.type === 'band' ? XA.step : 0); g += '<rect class="vz-band" x="' + VZ.r1(x) + '" y="' + F.yT + '" width="' + VZ.r1(ww) + '" height="' + F.ph + '"/>' + (b.label ? (x + 4 + VZ.tw(b.label, 11) <= F.x1 ? lbl(x, b.label) : VZ.txt(Math.min(F.x1, x + ww) - 4, F.yT + 11, b.label, { class: 'vz-note', 'text-anchor': 'end' })) : ''); });
  (spec.marks || []).forEach((m) => { const x = VZ.r1(px(m.x)); g += '<line class="vz-mark" x1="' + x + '" x2="' + x + '" y1="' + F.yT + '" y2="' + F.yB + '"/>' + (m.label ? lbl(x, m.label) : ''); });
  return g;
};
VZ.refs = function (spec, F) {
  return (spec.refs || []).map((r) => { const y = VZ.r1(F.y(r.y)); if (y < F.yT - 1 || y > F.yB + 1) return ''; return '<line class="vz-ref" x1="' + F.x0 + '" x2="' + F.x1 + '" y1="' + y + '" y2="' + y + '"' + (r.color ? ' style="stroke:' + r.color + '"' : '') + '/>' + (r.label ? VZ.txt(F.x1, y - 4, r.label, { class: 'vz-note', 'text-anchor': 'end' }) : ''); }).join('');
};
// callout：点 + 引线 + 文字（带表面色描边，压在图元上也可读）；优先放右上，放不下依次试左上、正上方
VZ.callouts = function (notes, F, pos) {
  let g = ''; const used = [];
  (notes || []).forEach((n) => {
    const p = pos(n); if (!p) return; const [x, y] = p; const tw = VZ.tw(n.text, 11) + 8;
    const cands = [[x + 10, y - 12], [x - 10 - tw, y - 12], [x - tw / 2, y - 18], [x + 10, y + 20], [x - 10 - tw, y + 20]];
    let [lx, ly] = cands.find(([a, b]) => a >= F.x0 - 2 && a + tw <= F.x1 + 2 && b - 11 >= F.yT - 2 && b <= F.yB) || cands[0];
    lx = Math.max(F.x0, Math.min(F.x1 - tw, lx));
    while (used.some((u) => Math.abs(u[1] - ly) < 14 && Math.abs(u[0] - lx) < tw)) ly += 14;
    used.push([lx, ly]);
    const ex = lx + tw / 2 > x ? lx - 2 : lx + tw - 6;
    g += '<circle class="vz-dot vz-callout-dot" cx="' + VZ.r1(x) + '" cy="' + VZ.r1(y) + '" r="4"/><line class="vz-leader" x1="' + VZ.r1(x) + '" y1="' + VZ.r1(y) + '" x2="' + VZ.r1(ex) + '" y2="' + VZ.r1(ly - 4) + '"/>' + VZ.txt(lx, ly, n.text, { class: 'vz-note vz-callout' });
  });
  return g;
};
/* ---------- 图例 / tooltip / 空状态 ---------- */
VZ.legendItems = function (spec) {
  const ser = spec.series || []; const t = VZ.types[spec.type];
  return t && t.legend ? t.legend(spec) : ser.map((s, i) => ({ name: s.name == null ? '系列 ' + (i + 1) : s.name, color: VZ.color(i, s, spec.type === 'bar' ? ser.length : 0), kind: spec.type === 'bar' || s.area || spec.type === 'area' ? 'rect' : 'line', total: s.total }));
};
// 图例只影响本图：点击 = 显示 / 隐藏该系列；⌥ 点击 = 只看该系列（再 ⌥ 点击恢复全部）；悬停 = 其他系列淡出。
VZ.legendHTML = function (spec, inst) {
  const items = VZ.legendItems(spec);
  if (spec.legend === false || (items.length < 2 && spec.legend !== true)) return '';
  const vis = inst ? items.map((it) => !inst.hidden.has(it.name)) : items.map(() => true);
  return '<div class="vz-legend" role="group" aria-label="图例（点击切换系列，⌥ 点击只看该系列）">' + items.map((it, i) => '<button type="button" class="vz-lg' + (vis[i] ? '' : ' off') + '" data-lg="' + esc(it.name) + '" data-si="' + i + '" aria-pressed="' + vis[i] + '"><span class="vz-sw ' + (it.kind || 'rect') + '" style="--c:' + it.color + '"></span><span class="vz-lgn">' + esc(it.name) + '</span>' + (it.total != null ? '<b class="vz-lgv">' + esc(it.total) + '</b>' : '') + '</button>').join('') + '</div>';
};
VZ._lgDim = function (inst, si) {
  const svg = inst.el.querySelector('svg.vz-svg'); if (!svg) return;
  const byS = svg.querySelectorAll('[data-s]'); const list = byS.length ? byS : svg.querySelectorAll('.vz-seg[data-i]'); const key = byS.length ? 'data-s' : 'data-i';
  list.forEach((n) => n.classList.toggle('vz-lo', si >= 0 && +n.getAttribute(key) !== si));
};
VZ.tipRow = (color, name, value, o) => '<div class="vz-tr"><span class="vz-tk' + (o && o.kind === 'rect' ? ' rect' : '') + '" style="--c:' + (color || 'transparent') + '"></span><b class="vz-tv">' + esc(value) + '</b><span class="vz-tn">' + esc(name) + '</span></div>';
VZ.tipHead = (t, sub) => '<div class="vz-th">' + esc(t) + (sub ? '<span>' + esc(sub) + '</span>' : '') + '</div>';
VZ.emptyHTML = function (spec, h) {
  if (VZ.lowSample(spec)) { const frac = Math.min(1, spec.n / spec.minN); const r = 14, c = 2 * Math.PI * r; return '<div class="vz-empty vz-low" style="min-height:' + Math.max(80, h) + 'px" role="status"><svg width="36" height="36" viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="' + r + '" class="vz-ring-bg"/><circle cx="18" cy="18" r="' + r + '" class="vz-ring" stroke-dasharray="' + (c * frac).toFixed(1) + ' ' + c.toFixed(1) + '" transform="rotate(-90 18 18)"/></svg><div><b>样本不足</b><span class="cap">' + spec.n + ' / ' + spec.minN + ' 个会话' + (spec.lowText ? ' · ' + esc(spec.lowText) : '') + '</span></div></div>'; }
  return '<div class="vz-empty" style="min-height:' + Math.max(64, Math.min(h, 160)) + 'px" role="status">' + VZ.el('svg', { width: 28, height: 20, viewBox: '0 0 28 20', 'aria-hidden': true }, '<path class="vz-empty-ic" d="M2 17h24M5 14l5-6 5 4 5-7 5 4" fill="none"/>') + '<span>' + esc(VZ.emptyText(spec)) + '</span></div>';
};
/* ---------- 渲染入口 ---------- */
VZ.height = (spec, w) => { const t = VZ.types[spec.type]; return spec.height || (t && t.height ? t.height(spec, w) : VZ.defaultH[spec.type]) || 200; };
// bare：交互图（VZ.html）不写 <title>，免得原生提示盖住自定义浮层（F23）；名字仍在 aria-label 里
VZ.render = function (spec, w, h, inst, bare) {
  const t = VZ.types[spec.type]; if (!t) return { svg: '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '"><text x="8" y="20" class="vz-ax">未知图表类型 ' + esc(spec.type) + '</text></svg>', model: null };
  h = h || VZ.height(spec, w); w = Math.max(80, Math.round(w)); h = Math.max(24, Math.round(h));
  const ctx = { w, h, inst: inst || { hidden: new Set(), focus: -1 }, vis: VZ.vis(spec, inst) };
  const r = t.render(spec, w, h, ctx);
  const title = spec.title || t.name || spec.type;
  const svg = '<svg class="vz-svg vz-t-' + spec.type + '" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(title + (spec.desc ? '。' + spec.desc : '')) + '"' + (r.model && r.model.kind ? ' data-kind="' + r.model.kind + '"' : '') + '>' + (bare ? '' : '<title>' + esc(title) + '</title>') + r.body + (spec.brush ? '<rect class="vz-brush" x="0" y="0" width="0" height="0" hidden/>' : '') + '</svg>';
  return { svg, model: r.model || null, h };
};
VZ.svg = function (spec, w, h) {
  w = w || spec.width || 600; const ts = VZ.types[spec.type]; h = h || (ts && ts.svgHeight ? ts.svgHeight(spec, w) : VZ.height(spec, w));
  if (VZ.isEmpty(spec) || VZ.lowSample(spec)) return '<svg class="vz-svg vz-empty-svg" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + esc(spec.title || '') + '：' + (VZ.lowSample(spec) ? '样本不足' : esc(VZ.emptyText(spec))) + '"><title>' + esc(spec.title || '') + '</title>' + VZ.txt(w / 2, h / 2 + 4, VZ.lowSample(spec) ? '样本不足 · ' + spec.n + ' / ' + spec.minN : VZ.emptyText(spec), { class: 'vz-ax', 'text-anchor': 'middle' }) + '</svg>';
  return VZ.render(spec, w, h).svg;
};
// 图表头：沿用卡片层级 —— .eb 等宽眉标（模块名）、.ct 13px 标题（按 Apple 的做法写成结论句）、.cap 12px 说明（口径 / 范围）、evidence「证据 →」链接
// o: { eyebrow, title, sub, evidence: { label, act, attrs }, right（额外 HTML，如图表 ↔ 表格切换） }
VZ.head = function (o) {
  if (!o) return '';
  return '<div class="vz-head">' + (o.eyebrow ? '<span class="eb">' + esc(o.eyebrow) + '</span>' : '') + '<div class="hd"><div class="grow"><span class="ct">' + esc(o.title || '') + '</span>' + (o.sub ? '<span class="cap">' + esc(o.sub) + '</span>' : '') + '</div>' + (o.evidence ? '<button type="button" class="lnk" data-act="' + esc(o.evidence.act || '') + '"' + (o.evidence.attrs || '') + '>' + esc(o.evidence.label || '证据 →') + '</button>' : '') + (o.right || '') + '</div></div>';
};
VZ.html = function (spec, w, h, inst) {
  h = h || VZ.height(spec, w); const head = VZ.head(spec.head);
  if (spec.view === 'table') return head + VZ.table(spec);
  if (VZ.isEmpty(spec) || VZ.lowSample(spec)) return head + VZ.emptyHTML(spec, h);
  const t = VZ.types[spec.type]; if (t && t.html) { if (inst) inst.model = null; return head + t.html(spec, w, h, inst); }
  const r = VZ.render(spec, w, h, inst, true); if (inst) inst.model = r.model;
  const lg = VZ.legendHTML(spec, inst);
  const extra = t && t.extra ? t.extra(spec, w, r.model) : '';
  return head + (spec.legend === 'bottom' ? '' : lg) + '<div class="vz-plot" tabindex="0" role="group" aria-roledescription="图表" aria-label="' + esc(spec.title || spec.type) + '（← → 移动焦点，Enter 选择）">' + r.svg + '<div class="vz-tip" role="tooltip" hidden></div><div class="vh" aria-live="polite" data-vz-live></div></div>' + extra + (spec.legend === 'bottom' ? lg : '');
};
VZ.mount = function (el, spec) {
  if (typeof el === 'string') el = document.querySelector(el.startsWith('#') || el.startsWith('.') || el.startsWith('[') ? el : '[data-vz="' + el + '"]');
  if (!el) return null;
  let inst = VZ._inst.get(el);
  if (!inst) {
    inst = { el, hidden: new Set(spec.hidden || []), focus: -1, model: null, w: 0 };
    inst.redraw = () => VZ.draw(el);
    VZ._inst.set(el, inst); el.classList.add('vz'); VZ._bind(el, inst); VZ._observe(el);
  }
  inst.spec = spec;
  VZ.draw(el);
  return inst;
};
VZ.draw = function (el) {
  const inst = VZ._inst.get(el); if (!inst) return;
  const spec = inst.spec; const w = el.clientWidth || spec.width || 600; inst.w = w;
  const h = VZ.height(spec, w);
  el.innerHTML = VZ.html(spec, w, h, inst);
  // 入场动画只在首次绘制时播放（vz-in）；尺寸变化、图例切换等重绘不再播放；prefers-reduced-motion 下 CSS 关闭全部动画
  if (!inst.drawn) { inst.drawn = true; const svg = el.querySelector('svg.vz-svg'); if (svg && spec.animate !== false) svg.classList.add('vz-in'); }
  el.classList.toggle('vz-table-view', spec.view === 'table');
  if (spec.type === 'multiples') VZ.types.multiples.mountChildren(el, spec, inst);
  if (inst.focus >= 0) VZ._focus(inst, inst.focus, true);
};
VZ.setView = function (el, view) { const inst = VZ._inst.get(el); if (!inst) return; inst.spec.view = view; VZ.draw(el); };
VZ.table = function (spec) {
  const t = VZ.types[spec.type]; const d = t && t.table ? t.table(spec) : VZ.xyTable(spec);
  if (!d || !d.rows.length) return '<div class="vz-empty" role="status"><span>' + esc(VZ.emptyText(spec)) + '</span></div>';
  return '<div class="scroll-x vz-tbl"><table class="tbl"><thead><tr>' + d.cols.map((c, i) => '<th' + (i ? ' style="text-align:right"' : '') + '>' + esc(c) + '</th>').join('') + '</tr></thead><tbody>' + d.rows.map((r) => '<tr>' + r.map((c, i) => '<td class="' + (i ? 'mono' : '') + '"' + (i ? ' style="text-align:right"' : '') + '>' + esc(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
};
VZ.xyTable = function (spec) {
  const ser = spec.series || []; const X = spec.x || {}; const vals = X.values || []; const n = Math.max(vals.length, ...ser.map((s) => (s.values || []).length));
  const fx = (v, i) => typeof X.format === 'function' ? X.format(v, i) : (X.type === 'time' || (typeof v === 'number' && v > 1e11)) ? VZ.time.md(v) : String(v == null ? i + 1 : v);
  const fy = (v) => VZ.fmt(v, spec.y && spec.y.format);
  return { cols: [X.label || '时间'].concat(ser.map((s, i) => s.name == null ? '系列 ' + (i + 1) : s.name)), rows: Array.from({ length: n }, (_, i) => [fx(vals[i], i)].concat(ser.map((s) => { const v = (s.values || [])[i]; return fy(VZ.num(v && v.y !== undefined ? v.y : v)); }))) };
};
/* ---------- 尺寸变化 ---------- */
VZ._ro = (typeof ResizeObserver !== 'undefined') ? new ResizeObserver((entries) => { entries.forEach((e) => { const el = e.target; const inst = VZ._inst.get(el); if (!inst) return; if (!el.isConnected) { VZ._ro.unobserve(el); return; } const w = el.clientWidth; if (Math.abs(w - inst.w) >= 1) VZ.draw(el); }); }) : null;
VZ._observe = (el) => { if (VZ._ro) VZ._ro.observe(el); };
VZ.relayout = () => { $$('.vz').forEach((el) => { const inst = VZ._inst.get(el); if (inst && el.isConnected && Math.abs(el.clientWidth - inst.w) >= 1) VZ.draw(el); }); };
window.addEventListener('orbit:layout', VZ.relayout);
/* ---------- 交互：hover / 十字准线 / 键盘 / 点击 / 图例 / brush ---------- */
// F23：浮层 position:fixed，不被卡片 / .scroll-x 的 overflow 裁切；按所在窗口（.main / .win）与视口的可见区避让边缘，
// 右侧放不下翻到左侧、上方放不下翻到下方。fixed 的包含块可能是带 container 的祖先（.main），所以摆好后量一次实际位置再校正。
VZ._tipShow = function (inst, html, x, y) {
  const tip = inst.el.querySelector('.vz-tip'); const plot = inst.el.querySelector('.vz-plot'); if (!tip || !plot) return;
  tip.innerHTML = html; tip.hidden = false;
  const pr = plot.getBoundingClientRect(); const host = plot.closest('.main, .panel, .modal, .win');
  const hr = host ? host.getBoundingClientRect() : { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
  const L = Math.max(0, hr.left) + 4, T = Math.max(0, hr.top) + 4, R = Math.min(window.innerWidth, hr.right) - 4, B = Math.min(window.innerHeight, hr.bottom) - 4;
  const tw = tip.offsetWidth, th = tip.offsetHeight; const px = pr.left + x, py = pr.top + y;
  let left = px + 12, top = py - th - 10;
  if (left + tw > R) left = px - tw - 12; if (left < L) left = Math.max(L, Math.min(R - tw, px - tw / 2));
  if (top < T) top = py + 16; if (top + th > B) top = Math.max(T, B - th);
  tip.style.left = left + 'px'; tip.style.top = top + 'px';
  const a = tip.getBoundingClientRect();
  if (Math.abs(a.left - left) > 0.5 || Math.abs(a.top - top) > 0.5) { tip.style.left = (2 * left - a.left) + 'px'; tip.style.top = (2 * top - a.top) + 'px'; }
};
// 浮层是 fixed：内容区滚动时收起，免得停在原处
document.addEventListener('scroll', () => { document.querySelectorAll('.vz-tip:not([hidden])').forEach((t) => { t.hidden = true; }); }, true);
VZ._tipHide = (inst) => { const tip = inst.el.querySelector('.vz-tip'); if (tip) tip.hidden = true; VZ._hl(inst, -1); };
VZ._hl = function (inst, i) {
  const svg = inst.el.querySelector('svg.vz-svg'); if (!svg) return; const m = inst.model;
  svg.querySelectorAll('.vz-hot').forEach((n) => n.classList.remove('vz-hot'));
  const xl = svg.querySelector('.vz-xline'); const dots = svg.querySelector('.vz-xdots');
  if (i < 0 || !m) { if (xl) xl.setAttribute('hidden', ''); if (dots) dots.innerHTML = ''; return; }
  if (m.kind === 'x' && xl) { const x = VZ.r1(m.xs[i]); xl.removeAttribute('hidden'); xl.setAttribute('x1', x); xl.setAttribute('x2', x); if (dots && m.dots) dots.innerHTML = m.dots(i); }
  svg.querySelectorAll('[data-i="' + i + '"]').forEach((n) => n.classList.add('vz-hot'));
};
VZ._focus = function (inst, i, silent) {
  const m = inst.model; if (!m || !m.n) return;
  i = Math.max(0, Math.min(m.n - 1, i)); inst.focus = i; VZ._hl(inst, i);
  const at = m.at ? m.at(i) : null; const html = m.tip ? m.tip(i) : '';
  if (html && at) VZ._tipShow(inst, html, at[0], at[1]);
  const live = inst.el.querySelector('[data-vz-live]'); if (live) live.textContent = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  if (!silent && inst.spec.onFocus) inst.spec.onFocus(i, m.datum ? m.datum(i) : null);
  if (!silent && inst.spec.onHover) inst.spec.onHover(i, m.datum ? m.datum(i) : null);
};
VZ._bind = function (el, inst) {
  const plotOf = () => el.querySelector('.vz-plot');
  const pos = (e) => { const p = plotOf(); const r = p.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
  const indexAt = (e) => {
    const m = inst.model; if (!m) return -1;
    const mark = e.target.closest && e.target.closest('[data-i]'); if (mark && mark.closest('.vz-plot') === plotOf()) return +mark.dataset.i;
    if (m.kind !== 'x' || !m.xs || !m.xs.length) return -1;
    const [x, y] = pos(e); if (m.F && (y < m.F.yT - 4 || y > m.F.yB + 20 || x < m.F.x0 - 8 || x > m.F.x1 + 8)) return -1;
    let best = -1, bd = Infinity; m.xs.forEach((px, i) => { if (m.has && !m.has(i)) return; const d = Math.abs(px - x); if (d < bd) { bd = d; best = i; } });
    return best;
  };
  let brush = null;
  el.addEventListener('pointermove', (e) => {
    if (inst.mm) { VZ._mmMove(inst, pos(e)[0]); return; }
    if (inst.phDrag) { VZ._phDrag(inst, pos(e)[0], false); return; }
    if (brush) { VZ._brushMove(inst, brush, pos(e)[0]); return; }
    const i = indexAt(e); if (i < 0) { VZ._tipHide(inst); inst.hover = -1; return; }
    const m = inst.model; if (!m) return;
    VZ._hl(inst, i); const html = m.tip ? m.tip(i) : '';
    if (html) { const at = m.kind === 'x' && m.at ? [pos(e)[0], m.at(i)[1]] : (m.at ? m.at(i) : pos(e)); VZ._tipShow(inst, html, m.kind === 'x' ? at[0] : at[0], m.kind === 'x' ? Math.min(at[1], pos(e)[1]) : at[1]); }
    if (inst.hover !== i) { inst.hover = i; if (inst.spec.onHover) inst.spec.onHover(i, m.datum ? m.datum(i) : null); }
  });
  el.addEventListener('pointerleave', () => { if (!brush && !inst.mm && !inst.phDrag) { VZ._tipHide(inst); inst.hover = -1; } });
  el.addEventListener('pointerdown', (e) => {
    if (inst.model && inst.model.kind === 'view') { if (e.button !== 0 || e.target.closest('.vz-legend')) return; VZ._mmDown(inst, pos(e)[0], e); return; }
    if (e.button === 0 && e.target.closest && e.target.closest('.vz-playhead') && inst.model && inst.model.F) { if (inst.play) inst.play.stop(); inst.phDrag = true; el.setPointerCapture(e.pointerId); VZ._tipHide(inst); e.preventDefault(); return; }
    if (!inst.spec.brush || e.button !== 0 || !inst.model || !inst.model.F) return;
    if (e.target.closest('.vz-legend')) return;
    const [x, y] = pos(e); const F = inst.model.F; if (y < F.yT || y > F.yB || x < F.x0 || x > F.x1) return;
    brush = { x0: x, x1: x, id: e.pointerId }; el.setPointerCapture(e.pointerId); VZ._tipHide(inst); e.preventDefault();
  });
  const endBrush = (e) => { if (inst.mm) { VZ._mmUp(inst, pos(e)[0]); return; } if (inst.phDrag) { inst.phDrag = false; VZ._phDrag(inst, pos(e)[0], true); return; } if (!brush) return; const b = brush; brush = null; VZ._brushEnd(inst, b, pos(e)[0]); };
  el.addEventListener('pointerup', endBrush); el.addEventListener('pointercancel', endBrush);
  // ⌘ / Ctrl + 滚轮：以光标为锚缩放时间线（1 – maxZoom 倍，默认 12）；缩放后 ⇧ + 滚轮或横向滚轮平移。页面滚动不受影响。
  el.addEventListener('wheel', (e) => {
    const m = inst.model; const spec = inst.spec; if (!m || !m.F || !m.F.range || spec.type !== 'timeline' || spec.zoom === false) return;
    const F = m.F; const [x] = pos(e); if (x < F.x0 || x > F.x1) return;
    const ext = spec.extent || (spec.extent = F.range.slice()); const [a, b] = F.range; const span = b - a; const full = ext[1] - ext[0];
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault(); const f = Math.exp(-e.deltaY * 0.0025); const ns = clamp(span / f, full / (spec.maxZoom || 12), full); if (Math.abs(ns - span) < 1e-9) return;
      const t = F.inv(x); const k = (t - a) / span; let na = t - k * ns, nb = na + ns; if (na < ext[0]) { na = ext[0]; nb = na + ns; } if (nb > ext[1]) { nb = ext[1]; na = nb - ns; }
      if (ns >= full - 1e-9) { na = ext[0]; nb = ext[1]; }   // 缩回全程时落在精确的端点上，不留浮点误差
      VZ._setRange(inst, [na, nb]);
    } else if ((e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) && span < full - 1e-9) {
      e.preventDefault(); const d = (e.deltaX || e.deltaY) / F.pw * span; const na = clamp(a + d, ext[0], ext[1] - span); VZ._setRange(inst, [na, na + span]);
    }
  }, { passive: false });
  el.addEventListener('dblclick', (e) => { const m = inst.model; if (m && m.kind === 'view' && !e.target.closest('.vz-legend')) VZ._mmApply(inst, m.F.x0, m.F.x1, true); });
  el.addEventListener('pointerover', (e) => { const lg = e.target.closest('.vz-lg'); if (lg) VZ._lgDim(inst, +lg.dataset.si); });
  el.addEventListener('pointerout', (e) => { const lg = e.target.closest('.vz-lg'); if (lg && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.vz-lg') === lg)) VZ._lgDim(inst, -1); });
  el.addEventListener('click', (e) => {
    const lg = e.target.closest('.vz-lg');
    if (lg) {
      const name = lg.dataset.lg; const names = VZ.legendItems(inst.spec).map((it) => it.name);
      if (e.altKey) { const solo = names.every((n) => n === name ? !inst.hidden.has(n) : inst.hidden.has(n)); inst.hidden = new Set(solo ? [] : names.filter((n) => n !== name)); }
      else if (inst.hidden.has(name)) inst.hidden.delete(name); else inst.hidden.add(name);
      VZ.draw(el); if (inst.spec.onLegend) inst.spec.onLegend(name, !inst.hidden.has(name), { hidden: Array.from(inst.hidden) }); return;
    }
    if (e.target.closest('.vz-tv-toggle')) { VZ.setView(el, inst.spec.view === 'table' ? 'chart' : 'table'); return; }
    if (brush || (inst.model && inst.model.kind === 'view')) return;
    const i = indexAt(e); if (i < 0 || !inst.model) return;
    inst.focus = i; if (inst.spec.onSelect) inst.spec.onSelect(i, inst.model.datum ? inst.model.datum(i) : null);
  });
  el.addEventListener('keydown', (e) => {
    if (!e.target.classList.contains('vz-plot')) return; const m = inst.model; if (!m) return;
    if (m.kind === 'view') { VZ._mmKey(inst, e); return; }
    // 时间线回放键：Space 播放 / 暂停（spec.onPlay 或内置 VZ.replay），[ ] 把播放头移到上一个 / 下一个事件
    if (inst.spec.type === 'timeline' && (e.key === ' ' || e.key === '[' || e.key === ']') && !(e.key === ' ' && inst.focus >= 0 && !inst.spec.onPlay && inst.spec.playhead == null)) {
      e.preventDefault();
      if (e.key === ' ') { if (inst.spec.onPlay) inst.spec.onPlay(!inst.play); else if (inst.play) inst.play.stop(); else VZ.replay(el); return; }
      const ts = m.evTs || []; const ph = inst.spec.playhead != null ? inst.spec.playhead : m.F.range[1]; const nt = e.key === ']' ? ts.find((t) => t > ph + 1e-9) : ts.slice().reverse().find((t) => t < ph - 1e-9);
      if (nt != null) { if (inst.play) inst.play.stop(); VZ.playhead(el, nt); if (inst.spec.onPlayhead) inst.spec.onPlayhead(nt, { done: true, key: true }); } return;
    }
    if (!m.n) return;
    const k = e.key; const cur = inst.focus < 0 ? (k === 'ArrowLeft' || k === 'End' ? m.n : -1) : inst.focus;
    if (k === 'ArrowRight' || k === 'ArrowDown') { e.preventDefault(); VZ._focus(inst, cur + 1); }
    else if (k === 'ArrowLeft' || k === 'ArrowUp') { e.preventDefault(); VZ._focus(inst, cur - 1); }
    else if (k === 'Home') { e.preventDefault(); VZ._focus(inst, 0); }
    else if (k === 'End') { e.preventDefault(); VZ._focus(inst, m.n - 1); }
    else if ((k === 'Enter' || k === ' ') && inst.focus >= 0) { e.preventDefault(); if (inst.spec.onSelect) inst.spec.onSelect(inst.focus, m.datum ? m.datum(inst.focus) : null); }
    else if (k === 'Escape') { inst.focus = -1; VZ._tipHide(inst); }
  });
  el.addEventListener('focusout', (e) => { if (!el.contains(e.relatedTarget)) { VZ._tipHide(inst); } });
};
VZ._brushMove = function (inst, b, x) {
  const F = inst.model.F; b.x1 = Math.max(F.x0, Math.min(F.x1, x));
  const r = inst.el.querySelector('.vz-brush'); if (!r) return;
  const a = Math.min(b.x0, b.x1), w = Math.abs(b.x1 - b.x0);
  r.removeAttribute('hidden'); r.setAttribute('x', VZ.r1(a)); r.setAttribute('y', F.yT); r.setAttribute('width', VZ.r1(w)); r.setAttribute('height', F.ph);
};
VZ._brushEnd = function (inst, b, x) {
  const m = inst.model; const F = m.F; b.x1 = Math.max(F.x0, Math.min(F.x1, x));
  const r = inst.el.querySelector('.vz-brush');
  if (Math.abs(b.x1 - b.x0) < 4) { if (r) r.setAttribute('hidden', ''); inst.brushRange = null; if (inst.spec.onBrush) inst.spec.onBrush(null); return; }
  const a = Math.min(b.x0, b.x1), c = Math.max(b.x0, b.x1);
  const range = m.brushRange ? m.brushRange(a, c) : [a, c];
  inst.brushRange = range; if (inst.spec.onBrush) inst.spec.onBrush(range, { px: [a, c] });
};
/* ---------- 时间线回放：播放头拖动 / 定位（不重绘）、范围缩放、VZ.replay 控制器 ---------- */
VZ._setRange = function (inst, r) { inst.spec.range = r; VZ.draw(inst.el); const ext = inst.spec.extent; const full = !ext || (Math.abs(r[0] - ext[0]) < 1e-9 && Math.abs(r[1] - ext[1]) < 1e-9); if (inst.spec.onView) inst.spec.onView(full ? null : r, { zoom: true, full, range: r }); };
VZ._phDrag = function (inst, x, done) {
  const m = inst.model; const F = m.F; x = clamp(x, F.x0, F.x1); let t = F.inv(x);
  if (inst.spec.snap !== false && m.evTs && m.evTs.length) { let best = null, bd = 6; m.evTs.forEach((et) => { const d = Math.abs(F.px(et) - x); if (d < bd) { bd = d; best = et; } }); if (best != null) t = best; }
  t = clamp(t, F.range[0], F.range[1]); VZ.playhead(inst.el, t); if (inst.spec.onPlayhead) inst.spec.onPlayhead(t, { done });
};
// VZ.playhead(el, t, { playing })：把播放头移到 t 并按 t 切换事件的「未发生」态。逐帧调用也只改 transform 与 class，不重绘。
// playing = true 时 svg 带 vz-playing，未发生的事件完全隐藏（回放中逐个出现）；拖动 / 定位时只淡化，便于看全貌（评审 A3-V07）
VZ.playhead = function (el, t, o) {
  const inst = VZ._inst.get(el); if (!inst || !inst.model || !inst.model.F) return; const F = inst.model.F; o = o || {};
  if (inst.spec.playhead == null) { inst.spec.playhead = t; VZ.draw(el); } else inst.spec.playhead = t;
  const svg = el.querySelector('svg.vz-svg'); if (!svg) return; const g = svg.querySelector('.vz-playhead'); if (g) g.setAttribute('transform', 'translate(' + VZ.r1(F.px(t)) + ' 0)');
  svg.classList.toggle('vz-playing', !!o.playing);
  svg.querySelectorAll('[data-t]').forEach((n) => n.classList.toggle('vz-future', +n.getAttribute('data-t') > t));
  const live = el.querySelector('[data-vz-live]'); if (live && inst.model.ft && !o.playing) { const done = (inst.model.evTs || []).filter((et) => et <= t).length; live.textContent = '播放头 ' + inst.model.ft(t) + ' · 已发生 ' + done + ' / ' + (inst.model.evTs || []).length + ' 个事件'; }
};
// VZ.replay(el, { from, to, ms = 8000（全程时长，范围变窄按比例缩短）, rate = 1, realtime（按真实时长，unit 'min' 时 1 分钟 = 60 s）, onTick(t, k), onDone }) -> { playing, stop() }
// 与现有 A3 的 8 秒 requestAnimationFrame 回放等价：从当前播放头继续，到末尾自动停止并恢复「全部显示」；再次调用从头开始
VZ.replay = function (el, o) {
  o = o || {}; const inst = VZ._inst.get(el); if (!inst || !inst.model || !inst.model.F) return null; const F = inst.model.F; const [r0, r1] = F.range;
  if (inst.play) inst.play.stop();
  const cur = inst.spec.playhead; const from = o.from != null ? o.from : (cur != null && cur < r1 - 1e-9 && cur >= r0 ? cur : r0); const to = o.to != null ? o.to : r1;
  const rate = o.rate || 1; const unitMs = (inst.spec.unit || 'ms') === 'min' ? 60000 : 1;
  const total = (o.realtime ? (to - from) * unitMs : (o.ms || 8000) * ((to - from) / Math.max(1e-9, r1 - r0))) / rate;
  let raf = null, t0 = null; const ctl = { playing: true, from, to };
  const tick = (now) => { if (t0 == null) t0 = now; const k = total > 0 ? Math.min(1, (now - t0) / total) : 1; const t = from + (to - from) * k; VZ.playhead(el, t, { playing: k < 1 }); if (o.onTick) o.onTick(t, k); if (k < 1 && ctl.playing) raf = requestAnimationFrame(tick); else { ctl.playing = false; raf = null; if (inst.play === ctl) inst.play = null; if (o.onDone) o.onDone(t); } };
  ctl.stop = () => { if (raf) cancelAnimationFrame(raf); raf = null; ctl.playing = false; if (inst.play === ctl) inst.play = null; VZ.playhead(el, inst.spec.playhead != null ? inst.spec.playhead : to, { playing: false }); if (o.onStop) o.onStop(inst.spec.playhead); };
  inst.play = ctl; VZ.playhead(el, from, { playing: true }); raf = requestAnimationFrame(tick); return ctl;
};
VZ.playing = (el) => { const inst = VZ._inst.get(el); return !!(inst && inst.play && inst.play.playing); };
/* ---------- minimap 视窗（model.kind === 'view'）：拖动平移、拖手柄缩放、点空白跳转、双击 / Home 复位、键盘平移与缩放 ---------- */
VZ._mmDown = function (inst, x, e) {
  const m = inst.model; const F = m.F; let [a, b] = m.view; let mode = 'in';
  const nearA = Math.abs(x - a) <= 6, nearB = Math.abs(x - b) <= 6;
  if (nearA && (!nearB || x - a <= b - x)) mode = 'l'; else if (nearB) mode = 'r';
  else if (x < a || x > b) { const wd = b - a; a = clamp(x - wd / 2, F.x0, F.x1 - wd); b = a + wd; VZ._mmApply(inst, a, b, false); }
  inst.mm = { mode, x0: x, a, b }; inst.el.setPointerCapture(e.pointerId); VZ._tipHide(inst); e.preventDefault();
};
VZ._mmMove = function (inst, x) {
  const d = inst.mm; const m = inst.model; const F = m.F; let a = d.a, b = d.b; const dx = x - d.x0;
  if (d.mode === 'in') { const wd = b - a; a = clamp(a + dx, F.x0, F.x1 - wd); b = a + wd; }
  else if (d.mode === 'l') a = clamp(d.a + dx, F.x0, b - m.minW); else b = clamp(d.b + dx, a + m.minW, F.x1);
  VZ._mmApply(inst, a, b, false);
};
VZ._mmUp = function (inst, x) { if (inst.mm) VZ._mmMove(inst, x); inst.mm = null; const v = inst.model.view; VZ._mmApply(inst, v[0], v[1], true); };
VZ._mmApply = function (inst, a, b, done) {
  const m = inst.model; const F = m.F; a = VZ.r1(a); b = VZ.r1(b); m.view = [a, b];
  const el = inst.el; const r = el.querySelector('.vz-mm-view'); if (r) { r.setAttribute('x', a); r.setAttribute('width', VZ.r1(Math.max(2, b - a))); }
  el.querySelectorAll('.vz-mm-hdl').forEach((hd) => hd.setAttribute('x', VZ.r1((hd.dataset.h === 'l' ? a : b) - 2)));
  const full = a <= F.x0 + 0.5 && b >= F.x1 - 0.5; const range = full ? null : [F.sx.inv(a), F.sx.inv(b)];
  if (done) { inst.spec.window = range; const live = el.querySelector('[data-vz-live]'); if (live && m.ft) live.textContent = full ? '全程' : m.ft(range[0]) + ' – ' + m.ft(range[1]); }
  if (inst.spec.onView) inst.spec.onView(range, { px: [a, b], done: !!done, full });
};
VZ._mmKey = function (inst, e) {
  const m = inst.model; const F = m.F; let [a, b] = m.view; const wd = b - a; const k = e.key; const step = Math.max(2, wd * 0.1);
  const zoom = (f) => { const nw = clamp(wd * f, m.minW, F.pw); const c = (a + b) / 2; a = Math.max(F.x0, c - nw / 2); b = Math.min(F.x1, a + nw); a = Math.max(F.x0, b - nw); };
  if (k === 'ArrowLeft') { a = Math.max(F.x0, a - step); b = a + wd; } else if (k === 'ArrowRight') { b = Math.min(F.x1, b + step); a = b - wd; }
  else if (k === 'ArrowUp' || k === '+' || k === '=') zoom(0.8); else if (k === 'ArrowDown' || k === '-') zoom(1.25);
  else if (k === 'Home' || k === 'Escape') { a = F.x0; b = F.x1; } else return;
  e.preventDefault(); VZ._mmApply(inst, a, b, true);
};
/* ---------- xy 公共准备：y 域、框架、x 轴 ---------- */
VZ.val = (v) => VZ.num(v && typeof v === 'object' && v.y !== undefined ? v.y : v);
VZ.xyPrep = function (spec, w, h, ctx, o) {
  o = o || {}; const ser = spec.series || []; const vis = ctx.vis;
  const n = Math.max((spec.x && spec.x.values || []).length, ...ser.map((s) => (s.values || []).length), 0);
  let lo = Infinity, hi = -Infinity; const Y = spec.y || {};
  if (o.stacked) { for (let i = 0; i < n; i++) { let p = 0, q = 0; ser.forEach((s, j) => { if (!vis[j]) return; const v = VZ.val((s.values || [])[i]); if (v == null) return; if (v >= 0) p += v; else q += v; }); lo = Math.min(lo, q); hi = Math.max(hi, p); } }
  else ser.forEach((s, j) => { if (!vis[j]) return; (s.values || []).forEach((v) => { const y = VZ.val(v); if (y != null) { lo = Math.min(lo, y); hi = Math.max(hi, y); } }); (s.band || []).forEach((b) => { if (b && b[0] != null) { lo = Math.min(lo, b[0]); hi = Math.max(hi, b[1]); } }); });
  (spec.refs || []).forEach((r) => { lo = Math.min(lo, r.y); hi = Math.max(hi, r.y); });
  if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
  if (Y.zero !== false && (o.zero || Y.zero)) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (lo === hi) { hi = lo + (lo ? Math.abs(lo) * 0.2 : 1); }
  let [y0, y1] = VZ.nice(lo, hi, (Y.ticks || 5)); if (Y.min != null) y0 = Y.min; if (Y.max != null) y1 = Y.max;
  const F = VZ.frame(spec, w, h, { domain: [y0, y1], right: o.right, top: o.top, left: o.left, bottom: o.bottom });
  const XA = VZ.xaxis(spec, F, n, { band: o.band });
  return { ser, vis, n, F, XA };
};
VZ.xLabel = function (spec, i) {
  const X = spec.x || {}; const v = (X.values || [])[i];
  if (typeof X.format === 'function') return X.format(v, i);
  if (X.type === 'time' || (typeof v === 'number' && v > 1e11)) return VZ.time.md(v) + (X.unit === 'h' ? ' ' + VZ.time.hm(v) : '');
  return String(v == null ? i + 1 : v);
};
VZ.xyModel = function (spec, P, o) {
  // 共享十字准线模型：xs 像素、tip、datum、brushRange
  const { ser, vis, n, F, XA } = P; o = o || {};
  const fy = (v) => VZ.fmt(v, spec.y && spec.y.format);
  const stackTop = (i, j) => ser.slice(0, j + 1).reduce((a, q, k) => a + (vis[k] ? Math.max(0, VZ.val((q.values || [])[i]) || 0) : 0), 0);
  return {
    kind: 'x', n, F, xs: XA.xs,
    has: (i) => ser.some((s, j) => vis[j] && VZ.val((s.values || [])[i]) != null),
    tip: (i) => {
      const rows = ser.map((s, j) => { if (!vis[j]) return ''; const v = VZ.val((s.values || [])[i]); if (v == null) return ''; return VZ.tipRow(VZ.color(j, s, o.rect ? ser.length : 0), s.name == null ? '' : s.name, fy(v) + (s.unit || ''), { kind: o.rect ? 'rect' : 'line' }); }).join('');
      const tot = o.total ? ser.reduce((a, s, j) => a + (vis[j] ? (VZ.val((s.values || [])[i]) || 0) : 0), 0) : null;
      return VZ.tipHead(VZ.xLabel(spec, i), tot != null && ser.filter((s, j) => vis[j]).length > 1 ? '合计 ' + fy(tot) : '') + rows;
    },
    at: (i) => { let top = F.yB; ser.forEach((s, j) => { if (!vis[j]) return; const v = VZ.val((s.values || [])[i]); if (v != null) top = Math.min(top, F.y(o.stacked ? stackTop(i, j) : v)); }); return [XA.xs[i], top]; },
    datum: (i) => ({ i, x: (spec.x && spec.x.values || [])[i], label: VZ.xLabel(spec, i), values: ser.map((s) => VZ.val((s.values || [])[i])) }),
    dots: (i) => o.rect ? '' : ser.map((s, j) => { if (!vis[j]) return ''; const v = VZ.val((s.values || [])[i]); return v == null ? '' : '<circle class="vz-pt" cx="' + VZ.r1(XA.xs[i]) + '" cy="' + VZ.r1(F.y(v)) + '" r="4" style="--c:' + VZ.color(j, s) + '"/>'; }).join(''),
    brushRange: (a, c) => XA.type === 'band' ? [XA.inv(a), XA.inv(c)] : [XA.sc.inv(a), XA.sc.inv(c)]
  };
};
/* ---------- line / area ---------- */
VZ.types.line = {
  name: '折线图',
  render(spec, w, h, ctx) {
    const area = spec.type === 'area';
    const ser = spec.series || []; const vis = ctx.vis;
    const shown = ser.filter((s, j) => vis[j]);
    const endLabels = spec.endLabels !== false && shown.length >= 2 && shown.length <= 4 && w >= 480;
    const right = endLabels ? Math.min(140, Math.ceil(Math.max(...shown.map((s) => VZ.tw(s.name || '', 11))) + 18)) : 10;
    const P = VZ.xyPrep(spec, w, h, ctx, { zero: area, right });
    const { F, XA, n } = P; const base = F.y(Math.max(F.y0, Math.min(F.y1, 0)));
    let g = VZ.grid(F) + VZ.bandsAndMarks(spec, F, XA);
    const ends = [];
    ser.forEach((s, j) => {
      if (!vis[j]) return; const c = VZ.color(j, s); const pts = []; let lastI = -1;
      for (let i = 0; i < n; i++) { const v = VZ.val((s.values || [])[i]); if (v == null) pts.push(null); else { pts.push([XA.xs[i], F.y(v)]); lastI = i; } }
      if (s.band) { let up = '', dn = ''; s.band.forEach((b, i) => { if (!b || b[0] == null || XA.xs[i] == null) return; up += (up ? 'L' : 'M') + VZ.r1(XA.xs[i]) + ' ' + VZ.r1(F.y(b[1])); dn = 'L' + VZ.r1(XA.xs[i]) + ' ' + VZ.r1(F.y(b[0])) + dn; }); if (up) g += '<path class="vz-cband" data-s="' + j + '" d="' + up + dn + 'Z" style="--c:' + c + '"/>'; }
      if (area || s.area) { const segs = []; let cur = []; pts.forEach((p) => { if (p) cur.push(p); else if (cur.length) { segs.push(cur); cur = []; } }); if (cur.length) segs.push(cur); segs.forEach((sg) => { g += '<path class="vz-area" data-s="' + j + '" d="' + VZ.linePath(sg, spec.curve) + 'L' + VZ.r1(sg[sg.length - 1][0]) + ' ' + VZ.r1(base) + 'L' + VZ.r1(sg[0][0]) + ' ' + VZ.r1(base) + 'Z" style="--c:' + c + '"/>'; }); }
      // pathLength="1" 让入场的描线动画（CSS vz-draw）与路径长度无关；虚线依赖真实长度，不加
      g += '<path class="vz-line' + (s.dash ? ' dash' : '') + '" data-s="' + j + '"' + (s.dash ? '' : ' pathLength="1"') + ' d="' + VZ.linePath(pts, spec.curve) + '" style="--c:' + c + (s.width ? ';stroke-width:' + s.width + 'px' : '') + '"/>';
      const showPts = spec.points === true || (spec.points !== false && n <= 12);
      if (showPts) pts.forEach((p) => { if (p) g += '<circle class="vz-pt" data-s="' + j + '" cx="' + VZ.r1(p[0]) + '" cy="' + VZ.r1(p[1]) + '" r="3.5" style="--c:' + c + '"/>'; });
      if (lastI >= 0) ends.push({ name: s.name || '', c, x: pts[lastI][0], y: pts[lastI][1] });
    });
    if (endLabels && ends.length) { ends.sort((a, b) => a.y - b.y); for (let k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 13) ends[k].y = ends[k - 1].y + 13; ends.forEach((e) => { g += '<line class="vz-leader" x1="' + VZ.r1(e.x + 3) + '" y1="' + VZ.r1(e.y) + '" x2="' + VZ.r1(F.x1 + 6) + '" y2="' + VZ.r1(e.y) + '"/>' + VZ.txt(F.x1 + 8, e.y + 3.5, e.name, { class: 'vz-end' }); }); }
    g += VZ.refs(spec, F) + VZ.axisX(F, XA.items, { label: spec.x && spec.x.label, keepMajor: XA.type === 'time' });
    g += VZ.callouts(spec.notes, F, (nt) => { const i = nt.i != null ? nt.i : (spec.x && spec.x.values || []).indexOf(nt.x); if (i < 0 || XA.xs[i] == null) return null; const sIdx = nt.series != null ? (typeof nt.series === 'number' ? nt.series : ser.findIndex((s) => s.name === nt.series)) : 0; const v = nt.y != null ? nt.y : VZ.val(((ser[Math.max(0, sIdx)] || {}).values || [])[i]); return v == null ? null : [XA.xs[i], F.y(v)]; });
    g += '<line class="vz-xline" x1="0" x2="0" y1="' + F.yT + '" y2="' + F.yB + '" hidden/><g class="vz-xdots"></g>';
    return { body: g, model: VZ.xyModel(spec, P, { total: spec.total }) };
  },
  table: (spec) => VZ.xyTable(spec)
};
VZ.types.area = Object.assign({}, VZ.types.line, { name: '面积图' });
/* ---------- bar：分组 / 堆叠 / 横向 / 误差 ---------- */
VZ.types.bar = {
  name: '柱状图',
  height: (spec) => spec.horizontal ? Math.max(60, Math.max((spec.x && spec.x.values || []).length, ((spec.series || [])[0] || {}).values ? spec.series[0].values.length : 0, 1) * (spec.rowH || 28) + 30) : 200,
  render(spec, w, h, ctx) {
    if (spec.horizontal) return VZ.types.bar.renderH(spec, w, h, ctx);
    const ser = spec.series || []; const vis = ctx.vis; const stacked = !!spec.stacked; const k = Math.max(1, vis.filter(Boolean).length);
    const fy = (v) => VZ.fmt(v, spec.y && spec.y.format);
    const P = VZ.xyPrep(spec, w, h, ctx, { zero: true, band: true, stacked });
    const { F, XA, n } = P; const base = F.y(Math.max(F.y0, Math.min(F.y1, 0)));
    const hatch = Array.isArray(spec.hatch) && spec.hatch.length ? spec.hatch : null; const pid = hatch ? VZ.hatchId() : null;
    let g = (pid ? VZ.hatchDefs(pid) : '') + VZ.grid(F) + VZ.bandsAndMarks(spec, F, XA);
    const slot = XA.step; const gw = stacked ? Math.min(24, slot * 0.72) : Math.min(slot * 0.82, k * 24 + (k - 1) * 2); const bw = stacked ? gw : Math.max(2, (gw - (k - 1) * 2) / k);
    const selI = spec.selected; let maxI = -1, maxV = -Infinity;
    if (spec.labels === 'max') for (let i = 0; i < n; i++) { const t = ser.reduce((a, s, j) => a + (vis[j] ? (VZ.val((s.values || [])[i]) || 0) : 0), 0); if (t > maxV) { maxV = t; maxI = i; } }
    for (let i = 0; i < n; i++) {
      const cx = XA.xs[i]; let up = 0, dn = 0, kk = 0;
      const segs = []; ser.forEach((s, j) => { if (!vis[j]) return; segs.push({ v: VZ.val((s.values || [])[i]), c: VZ.color(j, s, ser.length), j, e: s.err ? VZ.num(s.err[i]) : null }); });
      const pos = segs.filter((s) => s.v > 0), neg = segs.filter((s) => s.v < 0);
      segs.forEach((sg) => {
        if (sg.v == null) { kk++; return; }
        const x = stacked ? cx - bw / 2 : cx - gw / 2 + kk * (bw + 2); kk++;
        let a, b; if (stacked) { if (sg.v >= 0) { a = up; up += sg.v; b = up; } else { b = dn; dn += sg.v; a = dn; } } else { a = Math.min(0, sg.v); b = Math.max(0, sg.v); }
        const yT = F.y(b), yB = F.y(a);
        const isEnd = !stacked || (sg.v >= 0 ? pos[pos.length - 1] === sg : neg[neg.length - 1] === sg); const isFirst = !stacked || (sg.v >= 0 ? pos[0] === sg : neg[0] === sg);
        const gap = stacked && !isFirst ? 2 : 0; const hgt = Math.max(0.5, yB - yT - gap); const ys = sg.v >= 0 ? yT : yT + gap;
        const d = isEnd ? VZ.barPath(x, ys, bw, hgt, sg.v >= 0 ? 'up' : 'down') : 'M' + VZ.r1(x) + ' ' + VZ.r1(ys) + 'h' + VZ.r1(bw) + 'v' + VZ.r1(hgt) + 'h' + VZ.r1(-bw) + 'Z';
        g += '<path class="vz-bar' + (selI != null && selI === i ? ' vz-sel' : '') + '" data-i="' + i + '" data-s="' + sg.j + '" d="' + d + '" style="--c:' + sg.c + '"/>';
        if (hatch && hatch.indexOf(i) >= 0) g += '<path class="vz-hatch" d="' + d + '" fill="url(#' + pid + ')"/>';
        if (sg.e != null && !stacked) { const xm = x + bw / 2, ya = F.y(sg.v + sg.e), yb = F.y(sg.v - sg.e); g += '<path class="vz-err" d="M' + VZ.r1(xm) + ' ' + VZ.r1(ya) + 'V' + VZ.r1(yb) + 'M' + VZ.r1(xm - 4) + ' ' + VZ.r1(ya) + 'h8M' + VZ.r1(xm - 4) + ' ' + VZ.r1(yb) + 'h8"/>'; }
        if (!stacked && (spec.labels === true || (spec.labels === 'max' && i === maxI))) g += VZ.txt(x + bw / 2, sg.v >= 0 ? yT - 4 : yB + 11, fy(sg.v), { class: 'vz-val', 'text-anchor': 'middle' });
      });
      if (stacked && (spec.labels === true || (spec.labels === 'max' && i === maxI)) && up > 0) g += VZ.txt(cx, F.y(up) - 4, fy(up), { class: 'vz-val', 'text-anchor': 'middle' });
      g += '<rect class="vz-hit" data-i="' + i + '" x="' + VZ.r1(cx - slot / 2) + '" y="' + F.yT + '" width="' + VZ.r1(slot) + '" height="' + F.ph + '"/>';
    }
    g += '<line class="vz-base" x1="' + F.x0 + '" x2="' + F.x1 + '" y1="' + VZ.r1(base) + '" y2="' + VZ.r1(base) + '"/>';
    g += VZ.refs(spec, F) + VZ.axisX(F, XA.items, { label: spec.x && spec.x.label });
    g += VZ.callouts(spec.notes, F, (nt) => { const i = nt.i != null ? nt.i : (spec.x && spec.x.values || []).indexOf(nt.x); if (i < 0) return null; const v = nt.y != null ? nt.y : (stacked ? ser.reduce((a, s, j) => a + (vis[j] ? Math.max(0, VZ.val((s.values || [])[i]) || 0) : 0), 0) : VZ.val(((ser[0] || {}).values || [])[i])); return v == null ? null : [XA.xs[i], F.y(v)]; });
    const model = VZ.xyModel(spec, P, { rect: true, stacked, total: spec.total !== false }); model.has = () => true;
    return { body: g, model };
  },
  renderH(spec, w, h, ctx) {
    const ser = spec.series || []; const vis = ctx.vis; const stacked = !!spec.stacked; const k = Math.max(1, vis.filter(Boolean).length);
    const X = spec.x || {}; const cats = X.values || []; const n = Math.max(cats.length, ...ser.map((s) => (s.values || []).length));
    const fy = (v) => VZ.fmt(v, spec.y && spec.y.format);
    let lo = 0, hi = 0;
    for (let i = 0; i < n; i++) { let p = 0, q = 0; ser.forEach((s, j) => { if (!vis[j]) return; const v = VZ.val((s.values || [])[i]); if (v == null) return; if (stacked) { if (v >= 0) p += v; else q += v; } else { p = Math.max(p, v); q = Math.min(q, v); } }); hi = Math.max(hi, p); lo = Math.min(lo, q); }
    if (hi === lo) hi = lo + 1;
    let [v0, v1] = VZ.nice(lo, hi, 5); if (spec.y && spec.y.min != null) v0 = spec.y.min; if (spec.y && spec.y.max != null) v1 = spec.y.max;
    const labW = Math.min(Math.max(40, Math.ceil(Math.max(...cats.map((c) => VZ.tw(String(c), 12)), 0) + 10)), Math.round(w * 0.38));
    const valW = spec.labels === false ? 0 : Math.ceil(VZ.twm(fy(v1), 11)) + 10;
    const F = { x0: labW, x1: Math.max(labW + 20, w - 10 - valW), yT: 6, yB: h - 20, w, h }; F.pw = F.x1 - F.x0; F.ph = F.yB - F.yT;
    const sx = VZ.scale.linear(v0, v1, F.x0, F.x1); const by = VZ.scale.band(n, F.yT, F.yB); const step = by.step;
    const gw = stacked ? Math.min(20, step * 0.68) : Math.min(step * 0.8, k * 18 + (k - 1) * 2); const bw = stacked ? gw : Math.max(2, (gw - (k - 1) * 2) / k);
    const ticks = VZ.ticks(v0, v1, Math.max(2, Math.floor(F.pw / 70)));
    const hatch = Array.isArray(spec.hatch) && spec.hatch.length ? spec.hatch : null; const pid = hatch ? VZ.hatchId() : null;
    let g = (pid ? VZ.hatchDefs(pid) : '') + ticks.map((t) => { const x = VZ.r1(sx(t)); return '<line class="vz-grid' + (t === 0 ? ' vz-base' : '') + '" x1="' + x + '" x2="' + x + '" y1="' + F.yT + '" y2="' + F.yB + '"/>' + VZ.txt(x, F.yB + 14, fy(t), { class: 'vz-ax', 'text-anchor': 'middle' }); }).join('');
    const x0px = sx(Math.max(v0, Math.min(v1, 0)));
    for (let i = 0; i < n; i++) {
      const cy = by(i); let up = 0, dn = 0, kk = 0; let endX = x0px;
      const lbl = String(cats[i] == null ? i + 1 : cats[i]); let txt = lbl; if (VZ.tw(txt, 12) > labW - 10) { while (txt.length > 1 && VZ.tw(txt + '…', 12) > labW - 10) txt = txt.slice(0, -1); txt += '…'; }
      g += VZ.txt(F.x0 - 8, cy + 4, txt, { class: 'vz-cat', 'text-anchor': 'end' });
      const segs = []; ser.forEach((s, j) => { if (!vis[j]) return; segs.push({ v: VZ.val((s.values || [])[i]), c: VZ.color(j, s, ser.length), j }); });
      const pos = segs.filter((s) => s.v > 0), neg = segs.filter((s) => s.v < 0);
      segs.forEach((sg) => {
        if (sg.v == null) { kk++; return; }
        const y = stacked ? cy - bw / 2 : cy - gw / 2 + kk * (bw + 2); kk++;
        let a, b; if (stacked) { if (sg.v >= 0) { a = up; up += sg.v; b = up; } else { b = dn; dn += sg.v; a = dn; } } else { a = Math.min(0, sg.v); b = Math.max(0, sg.v); }
        const xa = sx(a), xb = sx(b); const isEnd = !stacked || (sg.v >= 0 ? pos[pos.length - 1] === sg : neg[neg.length - 1] === sg); const isFirst = !stacked || (sg.v >= 0 ? pos[0] === sg : neg[0] === sg);
        const gap = stacked && !isFirst ? 2 : 0; const wd = Math.max(0.5, xb - xa - gap); const xs = sg.v >= 0 ? xa + gap : xa;
        const d = isEnd ? VZ.barPath(xs, y, wd, bw, sg.v >= 0 ? 'right' : 'left') : 'M' + VZ.r1(xs) + ' ' + VZ.r1(y) + 'h' + VZ.r1(wd) + 'v' + VZ.r1(bw) + 'h' + VZ.r1(-wd) + 'Z';
        const gx = sg.v >= 0 ? ' vz-gx' : ' vz-gxr';
        g += '<path class="vz-bar' + gx + (spec.selected != null && spec.selected === i ? ' vz-sel' : '') + '" data-i="' + i + '" data-s="' + sg.j + '" d="' + d + '" style="--c:' + sg.c + '"/>';
        if (hatch && hatch.indexOf(i) >= 0) g += '<path class="vz-hatch' + gx + '" d="' + d + '" fill="url(#' + pid + ')"/>';
        endX = Math.max(endX, xb);
      });
      const tot = stacked ? up : Math.max(...segs.map((s) => s.v || 0), 0);
      if (spec.labels !== false && segs.some((s) => s.v != null)) g += VZ.txt(endX + 6, cy + 4, fy(stacked || k > 1 ? tot : segs[0].v), { class: 'vz-val' });
      g += '<rect class="vz-hit" data-i="' + i + '" x="0" y="' + VZ.r1(cy - step / 2) + '" width="' + w + '" height="' + VZ.r1(step) + '"/>';
    }
    g += '<line class="vz-base" x1="' + VZ.r1(x0px) + '" x2="' + VZ.r1(x0px) + '" y1="' + F.yT + '" y2="' + F.yB + '"/>';
    const stackTop = (i, j) => ser.slice(0, j + 1).reduce((a2, q, kq) => a2 + (vis[kq] ? Math.max(0, VZ.val((q.values || [])[i]) || 0) : 0), 0);
    const model = { kind: 'mark', n, F, xs: [], has: () => true,
      tip: (i) => VZ.tipHead(String(cats[i] == null ? i + 1 : cats[i])) + ser.map((s, j) => { if (!vis[j]) return ''; const v = VZ.val((s.values || [])[i]); return v == null ? '' : VZ.tipRow(VZ.color(j, s, ser.length), s.name || '', fy(v), { kind: 'rect' }); }).join(''),
      at: (i) => { let e = x0px; ser.forEach((s, j) => { if (!vis[j]) return; const v = VZ.val((s.values || [])[i]); if (v != null) e = Math.max(e, sx(stacked ? stackTop(i, j) : v)); }); return [e, by(i)]; },
      datum: (i) => ({ i, x: cats[i], label: String(cats[i]), values: ser.map((s) => VZ.val((s.values || [])[i])) }) };
    return { body: g, model };
  },
  table: (spec) => VZ.xyTable(spec)
};
/* ---------- histogram ---------- */
VZ.types.histogram = {
  name: '直方图',
  isEmpty: (spec) => !(spec.values || []).some((v) => VZ.num(v) != null),
  bins(spec) {
    const vals = (spec.values || []).map(VZ.num).filter((v) => v != null); let edges = spec.edges;
    if (!edges) { const k = spec.bins || clamp(Math.ceil(Math.log2(Math.max(2, vals.length)) + 1), 5, 24); let mn = Math.min(...vals), mx = Math.max(...vals); if (mn === mx) { mn -= 0.5; mx += 0.5; } const st = VZ.tickStep(mn, mx, k); const a = Math.floor(mn / st) * st, b = Math.ceil(mx / st) * st; edges = []; for (let v = a; v <= b + st * 1e-6; v += st) edges.push(+v.toFixed(10)); if (edges.length < 2) edges = [a, a + st]; }
    const counts = new Array(edges.length - 1).fill(0);
    vals.forEach((v) => { for (let j = 0; j < edges.length - 1; j++) { const last = j === edges.length - 2; if (v >= edges[j] && (v < edges[j + 1] || (last && v <= edges[j + 1]))) { counts[j]++; break; } } });
    return { edges, counts, n: vals.length };
  },
  render(spec, w, h) {
    const B = VZ.types.histogram.bins(spec); const E = B.edges; const hi = Math.max(1, ...B.counts);
    const F = VZ.frame(spec, w, h, { domain: VZ.nice(0, hi, 4) });
    const sx = VZ.scale.linear(E[0], E[E.length - 1], F.x0, F.x1); const fx = (v) => VZ.fmt(v, spec.format);
    let g = VZ.grid(F) + VZ.bandsAndMarks(spec, F, { type: 'linear', sc: sx, xs: [], step: 0 });
    const xs = [];
    B.counts.forEach((c, i) => { const xa = sx(E[i]) + 1, xb = sx(E[i + 1]) - 1; const yT = F.y(c); xs.push((xa + xb) / 2); g += '<path class="vz-bar" data-i="' + i + '" d="' + VZ.barPath(xa, yT, Math.max(1, xb - xa), Math.max(0.5, F.yB - yT), 'up', 3) + '" style="--c:' + (spec.color || 'var(--h3)') + '"/>'; });
    g += VZ.axisX(F, E.map((e) => ({ x: sx(e), label: fx(e) })), { label: spec.x && spec.x.label }) + VZ.refs(spec, F);
    g += '<line class="vz-xline" x1="0" x2="0" y1="' + F.yT + '" y2="' + F.yB + '" hidden/><g class="vz-xdots"></g>';
    const pct = (i) => B.n ? Math.round(B.counts[i] / B.n * 100) + '%' : '';
    return { body: g, model: { kind: 'x', n: B.counts.length, F, xs, has: () => true, tip: (i) => VZ.tipHead(fx(E[i]) + ' – ' + fx(E[i + 1]), pct(i)) + VZ.tipRow(spec.color || 'var(--h3)', spec.unit || '个', String(B.counts[i]), { kind: 'rect' }), at: (i) => [xs[i], F.y(B.counts[i])], datum: (i) => ({ i, from: E[i], to: E[i + 1], count: B.counts[i] }), brushRange: (a, c) => [sx.inv(a), sx.inv(c)] } };
  },
  table(spec) { const B = VZ.types.histogram.bins(spec); const fx = (v) => VZ.fmt(v, spec.format); return { cols: ['区间', '数量', '占比'], rows: B.counts.map((c, i) => [fx(B.edges[i]) + ' – ' + fx(B.edges[i + 1]), String(c), B.n ? Math.round(c / B.n * 100) + '%' : '—']) }; }
};
/* ---------- 行式布局公共：左侧名称列 ---------- */
VZ.rowsFrame = function (spec, w, h, rows, o) {
  o = o || {}; const names = rows.map((r) => String(r.name == null ? '' : r.name));
  const labW = names.some((s) => s) ? Math.min(Math.max(36, Math.ceil(Math.max(...names.map((s) => VZ.tw(s, 12))) + 12)), Math.round(w * (o.labFrac || 0.34))) : 0;
  const F = { x0: labW + (o.leftExtra || 0), x1: Math.max(labW + 30, w - (o.rightW || 0)), yT: o.top != null ? o.top : 6, yB: h - (o.bottom != null ? o.bottom : (o.axis ? 20 : 6)), w, h, labW };
  F.pw = F.x1 - F.x0; F.ph = F.yB - F.yT; F.by = VZ.scale.band(rows.length, F.yT, F.yB); F.step = F.by.step;
  F.name = (i) => { const s = names[i]; let t = s; if (VZ.tw(t, 12) > labW - 10) { while (t.length > 1 && VZ.tw(t + '…', 12) > labW - 10) t = t.slice(0, -1); t += '…'; } return s ? VZ.txt(labW - 8, F.by(i) + 4, t, { class: 'vz-cat', 'text-anchor': 'end' }) : ''; };
  F.hit = (i) => '<rect class="vz-hit" data-i="' + i + '" x="0" y="' + VZ.r1(F.by(i) - F.step / 2) + '" width="' + w + '" height="' + VZ.r1(F.step) + '"/>';
  return F;
};
// 「名称 值」标签放不下时截断名称（保留数值）；side 'end' = 名称在前，'start' = 数值在前
VZ.fitLbl = function (name, val, maxW, side) {
  const join = (n) => side === 'start' ? val + ' ' + n : n + ' ' + val; let t = name;
  if (VZ.tw(join(t), 12) <= maxW) return join(t);
  while (t.length > 1 && VZ.tw(join(t + '…'), 12) > maxW) t = t.slice(0, -1);
  return join(t + '…');
};
VZ.axisBottom = (F, sx, ticks, fmt) => { let prev = null; return ticks.map((t) => { const x = VZ.r1(sx(t)); const lbl = fmt(t); const out = '<line class="vz-grid" x1="' + x + '" x2="' + x + '" y1="' + F.yT + '" y2="' + F.yB + '"/>' + (lbl === prev ? '' : VZ.txt(x, F.yB + 14, lbl, { class: 'vz-ax', 'text-anchor': 'middle' })); prev = lbl; return out; }).join(''); };
/* ---------- diverging：双向条（人格维度、情绪前因） ---------- */
VZ.types.diverging = {
  name: '双向条形图',
  height: (spec) => (spec.rows || []).length * (spec.rowH || 30) + (spec.axis === false ? 10 : 24),
  render(spec, w, h) {
    const rows = spec.rows || []; const n = rows.length; const fmt = (v) => VZ.fmt(v, spec.format || 'signed');
    const hasPoles = rows.some((r) => r.left || r.right);
    const lW = hasPoles ? Math.ceil(Math.max(...rows.map((r) => VZ.tw(r.left || '', 12)), 0) + 10) : 0, rW = hasPoles ? Math.ceil(Math.max(...rows.map((r) => VZ.tw(r.right || '', 12)), 0) + 10) : 0;
    const mx = Math.max(1e-9, ...rows.map((r) => Math.abs(VZ.num(r.value) || 0)), ...rows.map((r) => Math.abs(VZ.num(r.ref) || 0)));
    const dom = spec.domain || [-VZ.nice(0, mx, 4)[1], VZ.nice(0, mx, 4)[1]];
    const valW = Math.ceil(Math.max(VZ.twm(fmt(dom[0]), 11), VZ.twm(fmt(dom[1]), 11))) + 8;
    const F = VZ.rowsFrame(spec, w, h, rows, { leftExtra: lW + valW, rightW: rW + valW, axis: spec.axis !== false });
    const sx = VZ.scale.linear(dom[0], dom[1], F.x0, F.x1); const cx = VZ.r1(sx(0)); const bh = Math.min(spec.barH || 12, F.step * 0.6);
    const colors = spec.colors || [VZ.sem.neg, VZ.sem.pos];
    let g = '';
    // deadband: [a, b]（如人格的 45–55「未定型」带），画在中线之后、条之前
    if (spec.deadband) { const a = sx(spec.deadband[0]), b = sx(spec.deadband[1]); g += '<rect class="vz-band" x="' + VZ.r1(Math.min(a, b)) + '" y="' + F.yT + '" width="' + VZ.r1(Math.abs(b - a)) + '" height="' + VZ.r1(F.ph) + '" rx="2"/>'; }
    g += '<line class="vz-base" x1="' + cx + '" x2="' + cx + '" y1="' + F.yT + '" y2="' + F.yB + '"/>';
    if (spec.axis !== false) g += VZ.axisBottom(F, sx, VZ.ticks(dom[0], dom[1], Math.max(2, Math.floor(F.pw / 60))).filter((t) => t !== 0), fmt);
    rows.forEach((r, i) => {
      const cy = F.by(i); const v = VZ.num(r.value); g += F.name(i);
      if (hasPoles) { g += VZ.txt(F.labW + 4, cy + 4, r.left || '', { class: 'vz-cat' + (v != null && v < 0 ? ' vz-strong' : '') }) + VZ.txt(w - 2, cy + 4, r.right || '', { class: 'vz-cat' + (v != null && v > 0 ? ' vz-strong' : ''), 'text-anchor': 'end' }); }
      if (VZ.num(r.ref) != null) { const rx = VZ.r1(sx(r.ref)); g += '<line class="vz-ghost" x1="' + rx + '" x2="' + rx + '" y1="' + VZ.r1(cy - bh) + '" y2="' + VZ.r1(cy + bh) + '"/>'; }
      if (v == null) return;
      const xe = sx(v); const c = r.color || (v < 0 ? colors[0] : colors[1]);
      g += '<path class="vz-bar' + (v < 0 ? ' vz-gxr' : ' vz-gx') + (spec.selected != null && (spec.selected === i || spec.selected === r.id) ? ' vz-sel' : '') + '" data-i="' + i + '" d="' + VZ.barPath(Math.min(cx, xe), cy - bh / 2, Math.max(1, Math.abs(xe - cx)), bh, v < 0 ? 'left' : 'right') + '" style="--c:' + c + '"/>';
      if (spec.values !== false) g += VZ.txt(v < 0 ? xe - 5 : xe + 5, cy + 4, fmt(v), { class: 'vz-val', 'text-anchor': v < 0 ? 'end' : 'start' });
      g += F.hit(i);
    });
    return { body: g, model: { kind: 'mark', n, F, xs: [], has: () => true, tip: (i) => { const r = rows[i]; return VZ.tipHead(r.name || '', r.left && r.right ? (VZ.num(r.value) < 0 ? r.left : r.right) : '') + VZ.tipRow(r.color || (VZ.num(r.value) < 0 ? colors[0] : colors[1]), r.hint || '', fmt(VZ.num(r.value)), { kind: 'rect' }) + (VZ.num(r.ref) != null ? VZ.tipRow('var(--ink-4)', spec.refLabel || '参照', fmt(r.ref), { kind: 'rect' }) : ''); }, at: (i) => [sx(VZ.num(rows[i].value) || 0), F.by(i)], datum: (i) => rows[i] } };
  },
  table: (spec) => ({ cols: ['名称', '值', '偏向'], rows: (spec.rows || []).map((r) => [r.name || '', VZ.fmt(VZ.num(r.value), spec.format || 'signed'), VZ.num(r.value) == null ? '—' : VZ.num(r.value) < 0 ? (r.left || '负') : (r.right || '正')]) })
};
/* ---------- ranked：排名条 + 占比 ---------- */
VZ.types.ranked = {
  name: '排名条',
  height: (spec) => (spec.rows || []).length * (spec.rowH || 26) + 10,
  rows: (spec) => { const rows = (spec.rows || []).slice(); if (spec.sorted !== false) rows.sort((a, b) => (VZ.num(b.value) || 0) - (VZ.num(a.value) || 0)); return rows; },
  render(spec, w, h) {
    const rows = VZ.types.ranked.rows(spec); const n = rows.length; const fmt = (v) => VZ.fmt(v, spec.format);
    const sum = rows.reduce((a, r) => a + (VZ.num(r.value) || 0), 0); const shareOf = (r) => r.share != null ? (r.share <= 1 ? r.share * 100 : r.share) : (sum ? (VZ.num(r.value) || 0) / sum * 100 : 0);
    const mx = Math.max(1e-9, ...rows.map((r) => VZ.num(r.value) || 0));
    const valW = Math.ceil(VZ.twm(fmt(mx), 11)) + 10; const shW = spec.share === false ? 0 : 40;
    const F = VZ.rowsFrame(spec, w, h, rows, { rightW: valW + shW, labFrac: 0.4 });
    const sx = VZ.scale.linear(0, mx, F.x0, F.x1); const bh = Math.min(spec.barH || 8, F.step * 0.6);
    let g = '';
    rows.forEach((r, i) => {
      const cy = F.by(i); const v = VZ.num(r.value) || 0; const top = spec.top != null ? i < spec.top : true;
      // 列表条浅灰、只有被强调的（top）用深色（评审 G-03）
      const c = r.color || (spec.top != null ? (top ? (spec.color || 'var(--ink-2)') : 'var(--h2)') : (spec.color || 'var(--h3)'));
      g += F.name(i) + '<path class="vz-bar vz-gx' + (spec.selected != null && (spec.selected === i || spec.selected === r.id) ? ' vz-sel' : '') + '" data-i="' + i + '" d="' + VZ.barPath(F.x0, cy - bh / 2, Math.max(2, sx(v) - F.x0), bh, 'right', 3) + '" style="--c:' + c + '"/>';
      g += VZ.txt(F.x1 + valW - 2, cy + 4, fmt(v), { class: 'vz-val', 'text-anchor': 'end' });
      if (shW) g += VZ.txt(w - 2, cy + 4, Math.round(shareOf(r)) + '%', { class: 'vz-ax', 'text-anchor': 'end' });
      if (r.flag) g += '<circle class="vz-flag" cx="' + VZ.r1(F.x1 + valW - 2 - VZ.twm(fmt(v), 11) - 8) + '" cy="' + VZ.r1(cy) + '" r="2.5"/>';
      g += F.hit(i);
    });
    return { body: g, model: { kind: 'mark', n, F, xs: [], has: () => true, tip: (i) => { const r = rows[i]; return VZ.tipHead(r.name || '', r.meta || '') + VZ.tipRow(r.color || 'var(--ink-2)', '占比 ' + Math.round(shareOf(r)) + '%', fmt(VZ.num(r.value)), { kind: 'rect' }) + (r.flag ? '<div class="vz-tr"><span class="vz-tk" style="--c:var(--crit-m)"></span><span class="vz-tn">' + esc(r.flag) + '</span></div>' : ''); }, at: (i) => [sx(VZ.num(rows[i].value) || 0), F.by(i)], datum: (i) => rows[i] } };
  },
  table: (spec) => { const rows = VZ.types.ranked.rows(spec); const sum = rows.reduce((a, r) => a + (VZ.num(r.value) || 0), 0); return { cols: ['名称', '值', '占比'], rows: rows.map((r) => [r.name || '', VZ.fmt(VZ.num(r.value), spec.format), (r.share != null ? Math.round(r.share <= 1 ? r.share * 100 : r.share) : sum ? Math.round((VZ.num(r.value) || 0) / sum * 100) : 0) + '%']) }; }
};
/* ---------- share：单条 100% 比例条（代替饼图） ---------- */
VZ.types.share = {
  name: '比例条',
  isEmpty: (spec) => !(spec.items || []).some((it) => VZ.num(it.value) > 0),
  legend: (spec) => { const items = spec.items || []; const sum = items.reduce((a, it) => a + (VZ.num(it.value) || 0), 0); return items.map((it, i) => ({ name: it.name, color: it.color || VZ.color(i), kind: 'rect', total: sum ? Math.round((VZ.num(it.value) || 0) / sum * 100) + '%' : '' })); },
  render(spec, w, h) {
    const items = spec.items || []; const sum = items.reduce((a, it) => a + (VZ.num(it.value) || 0), 0) || 1;
    const bh = Math.min(spec.barH || 14, h - 4); const y = (h - bh) / 2; const x0 = 0, x1 = w; const gap = 2; const vis = items.filter((it) => VZ.num(it.value) > 0);
    const avail = x1 - x0 - gap * Math.max(0, vis.length - 1); let x = x0; let g = ''; const segs = [];
    vis.forEach((it, k) => {
      const i = items.indexOf(it); const ww = Math.max(1, (VZ.num(it.value) || 0) / sum * avail); const c = it.color || VZ.color(i);
      const d = vis.length === 1 ? VZ.el('rect', { x: VZ.r1(x), y: VZ.r1(y), width: VZ.r1(ww), height: bh, rx: 4 }) : null;
      const path = d || '<path d="' + (k === 0 ? VZ.barPath(x, y, ww, bh, 'left') : k === vis.length - 1 ? VZ.barPath(x, y, ww, bh, 'right') : 'M' + VZ.r1(x) + ' ' + VZ.r1(y) + 'h' + VZ.r1(ww) + 'v' + bh + 'h' + VZ.r1(-ww) + 'Z') + '"/>';
      g += '<g class="vz-seg' + (spec.selected != null && (spec.selected === i || spec.selected === it.id) ? ' vz-sel' : '') + '" data-i="' + i + '" style="--c:' + c + '">' + path + '</g>';
      const pct = Math.round((VZ.num(it.value) || 0) / sum * 100) + '%';
      if (spec.labels !== false && ww >= VZ.twm(pct, 10.5) + 10 && bh >= 12) g += VZ.txt(x + ww / 2, y + bh / 2 + 3.5, pct, { class: 'vz-inbar', 'text-anchor': 'middle' });
      segs[i] = [x + ww / 2, y]; x += ww + gap;
    });
    return { body: g, model: { kind: 'mark', n: items.length, xs: [], has: (i) => !!segs[i], tip: (i) => { const it = items[i]; return VZ.tipHead(it.name || '') + VZ.tipRow(it.color || VZ.color(i), '占比 ' + Math.round((VZ.num(it.value) || 0) / sum * 100) + '%', VZ.fmt(VZ.num(it.value), spec.format) + (spec.unit || ''), { kind: 'rect' }); }, at: (i) => segs[i] || [0, y], datum: (i) => items[i] } };
  },
  table: (spec) => { const items = spec.items || []; const sum = items.reduce((a, it) => a + (VZ.num(it.value) || 0), 0) || 1; return { cols: ['项目', '值', '占比'], rows: items.map((it) => [it.name || '', VZ.fmt(VZ.num(it.value), spec.format), Math.round((VZ.num(it.value) || 0) / sum * 100) + '%']) }; }
};
/* ---------- bullet：目标 vs 实际 ---------- */
VZ.types.bullet = {
  name: '子弹图',
  height: (spec) => (spec.rows || []).length * (spec.rowH || 34) + (spec.axis === false ? 10 : 24),
  render(spec, w, h) {
    const rows = spec.rows || []; const fmt = (v, r) => VZ.fmt(v, (r && r.format) || spec.format);
    const mx = spec.max || VZ.nice(0, Math.max(1e-9, ...rows.map((r) => Math.max(VZ.num(r.value) || 0, VZ.num(r.target) || 0, ...(r.ranges || [])))), 4)[1];
    const valW = Math.ceil(Math.max(...rows.map((r) => VZ.twm(fmt(VZ.num(r.value), r) + ' / ' + fmt(VZ.num(r.target), r), 11)), 20)) + 10;
    const F = VZ.rowsFrame(spec, w, h, rows, { rightW: valW, axis: spec.axis !== false });
    const sx = VZ.scale.linear(0, mx, F.x0, F.x1); const bh = Math.min(16, F.step * 0.56);
    let g = spec.axis === false ? '' : VZ.axisBottom(F, sx, VZ.ticks(0, mx, Math.max(2, Math.floor(F.pw / 70))), VZ.tickFmt(spec.format));
    rows.forEach((r, i) => {
      const cy = F.by(i); const v = VZ.num(r.value) || 0, t = VZ.num(r.target); g += F.name(i);
      const rg = (r.ranges || []).slice().sort((a, b) => a - b); let prev = 0;
      rg.forEach((q, k) => { g += '<rect class="vz-range" x="' + VZ.r1(sx(prev)) + '" y="' + VZ.r1(cy - bh / 2) + '" width="' + VZ.r1(Math.max(0, sx(Math.min(q, mx)) - sx(prev))) + '" height="' + bh + '" style="fill:var(--h' + Math.max(0, 2 - k) + ')"/>'; prev = Math.min(q, mx); });
      if (!rg.length) g += '<rect class="vz-range" x="' + VZ.r1(F.x0) + '" y="' + VZ.r1(cy - bh / 2) + '" width="' + VZ.r1(F.pw) + '" height="' + bh + '" style="fill:var(--h0)"/>';
      g += '<path class="vz-bar vz-gx" data-i="' + i + '" d="' + VZ.barPath(F.x0, cy - 3, Math.max(2, sx(Math.min(v, mx)) - F.x0), 6, 'right', 2) + '" style="--c:' + (r.color || spec.color || VZ.ACC) + '"/>';
      if (t != null) { const tx = VZ.r1(sx(Math.min(t, mx))); g += '<line class="vz-target" x1="' + tx + '" x2="' + tx + '" y1="' + VZ.r1(cy - bh / 2 - 3) + '" y2="' + VZ.r1(cy + bh / 2 + 3) + '"/>'; }
      g += VZ.txt(w - 2, cy + 4, fmt(v, r) + (t != null ? ' / ' + fmt(t, r) : ''), { class: 'vz-val', 'text-anchor': 'end' }) + F.hit(i);
    });
    return { body: g, model: { kind: 'mark', n: rows.length, F, xs: [], has: () => true, tip: (i) => { const r = rows[i]; const v = VZ.num(r.value), t = VZ.num(r.target); return VZ.tipHead(r.name || '', t ? '达成 ' + Math.round((v || 0) / t * 100) + '%' : '') + VZ.tipRow(r.color || spec.color || VZ.ACC, '实际', fmt(v, r), { kind: 'rect' }) + (t != null ? VZ.tipRow('var(--ink-1)', '目标', fmt(t, r), { kind: 'rect' }) : ''); }, at: (i) => [sx(Math.min(VZ.num(rows[i].value) || 0, mx)), F.by(i)], datum: (i) => rows[i] } };
  },
  table: (spec) => ({ cols: ['名称', '实际', '目标', '达成'], rows: (spec.rows || []).map((r) => { const v = VZ.num(r.value), t = VZ.num(r.target); return [r.name || '', VZ.fmt(v, r.format || spec.format), VZ.fmt(t, r.format || spec.format), t ? Math.round((v || 0) / t * 100) + '%' : '—']; }) })
};
/* ---------- dumbbell / slope：前后对比 ---------- */
VZ.delta = function (a, b, goodDown) {
  if (a == null || b == null) return { text: '—', cls: '' }; const d = b - a; const pct = a ? Math.round(Math.abs(d) / Math.abs(a) * 100) : null;
  const good = goodDown == null ? null : (d < 0) === goodDown;
  return { text: (d > 0 ? '+' : d < 0 ? '−' : '±') + VZ.fmt(Math.abs(d)) + (pct != null && pct <= 999 ? ' (' + (d > 0 ? '+' : d < 0 ? '−' : '') + pct + '%)' : ''), cls: d === 0 || good == null ? '' : good ? 'vz-good' : 'vz-bad', d };
};
VZ.types.dumbbell = {
  name: '前后对比',
  height: (spec) => (spec.rows || []).length * (spec.rowH || 30) + 24,
  legend: (spec) => { const L = spec.labels || ['前', '后'], C = spec.colors || ['var(--h2)', 'var(--ink-1)']; return [{ name: L[0], color: C[0], kind: 'dot' }, { name: L[1], color: C[1], kind: 'dot' }]; },
  render(spec, w, h) {
    const rows = spec.rows || []; const C = spec.colors || ['var(--h2)', 'var(--ink-1)']; const fmt = (v) => VZ.fmt(v, spec.format);
    const vals = rows.flatMap((r) => [VZ.num(r.a), VZ.num(r.b)]).filter((v) => v != null); let lo = Math.min(0, ...vals), hi = Math.max(1e-9, ...vals); [lo, hi] = VZ.nice(lo, hi, 4);
    const dW = spec.delta === false ? 0 : Math.ceil(Math.max(...rows.map((r) => VZ.twm(VZ.delta(VZ.num(r.a), VZ.num(r.b), spec.goodDown).text, 11)), 30)) + 12;
    const F = VZ.rowsFrame(spec, w, h, rows, { rightW: dW + 14, axis: true, leftExtra: 10 });
    const sx = VZ.scale.linear(lo, hi, F.x0, F.x1);
    let g = VZ.axisBottom(F, sx, VZ.ticks(lo, hi, Math.max(2, Math.floor(F.pw / 70))), VZ.tickFmt(spec.format));
    rows.forEach((r, i) => {
      const cy = F.by(i); const a = VZ.num(r.a), b = VZ.num(r.b); g += F.name(i);
      if (a != null && b != null) g += '<line class="vz-dline" x1="' + VZ.r1(sx(a)) + '" x2="' + VZ.r1(sx(b)) + '" y1="' + VZ.r1(cy) + '" y2="' + VZ.r1(cy) + '"/>';
      if (a != null) g += '<circle class="vz-pt" data-i="' + i + '" data-s="0" cx="' + VZ.r1(sx(a)) + '" cy="' + VZ.r1(cy) + '" r="5" style="--c:' + C[0] + '"/>';
      if (b != null) g += '<circle class="vz-pt" data-i="' + i + '" data-s="1" cx="' + VZ.r1(sx(b)) + '" cy="' + VZ.r1(cy) + '" r="5" style="--c:' + C[1] + '"/>';
      if (dW) { const d = VZ.delta(a, b, spec.goodDown); g += VZ.txt(w - 2, cy + 4, d.text, { class: 'vz-val ' + d.cls, 'text-anchor': 'end' }); }
      g += F.hit(i);
    });
    const L = spec.labels || ['前', '后'];
    return { body: g, model: { kind: 'mark', n: rows.length, F, xs: [], has: () => true, tip: (i) => { const r = rows[i]; const a = VZ.num(r.a), b = VZ.num(r.b); const d = VZ.delta(a, b, spec.goodDown); return VZ.tipHead(r.name || '', d.text) + VZ.tipRow(C[0], L[0], fmt(a), { kind: 'rect' }) + VZ.tipRow(C[1], L[1], fmt(b), { kind: 'rect' }); }, at: (i) => [sx(VZ.num(rows[i].b) != null ? VZ.num(rows[i].b) : (VZ.num(rows[i].a) || 0)), F.by(i)], datum: (i) => rows[i] } };
  },
  table: (spec) => { const L = spec.labels || ['前', '后']; return { cols: ['名称', L[0], L[1], '变化'], rows: (spec.rows || []).map((r) => [r.name || '', VZ.fmt(VZ.num(r.a), spec.format), VZ.fmt(VZ.num(r.b), spec.format), VZ.delta(VZ.num(r.a), VZ.num(r.b), spec.goodDown).text]) }; }
};
VZ.types.slope = {
  name: '斜率图',
  legend: VZ.types.dumbbell.legend,
  render(spec, w, h) {
    const rows = spec.rows || []; const L = spec.labels || ['前', '后']; const C = spec.colors || ['var(--h2)', 'var(--ink-1)']; const fmt = (v) => VZ.fmt(v, spec.format);
    const vals = rows.flatMap((r) => [VZ.num(r.a), VZ.num(r.b)]).filter((v) => v != null); let [lo, hi] = VZ.nice(Math.min(0, ...vals), Math.max(1e-9, ...vals), 4);
    const lblW = Math.min(Math.round(w * 0.32), Math.ceil(Math.max(...rows.map((r) => Math.max(VZ.tw((r.name || '') + ' ' + fmt(VZ.num(r.a)), 12), VZ.tw(fmt(VZ.num(r.b)) + ' ' + (r.name || ''), 12))), 40)) + 14);
    const F = { x0: lblW, x1: w - lblW, yT: 24, yB: h - 10 }; const sy = VZ.scale.linear(lo, hi, F.yB, F.yT);
    let g = '<line class="vz-grid" x1="' + F.x0 + '" x2="' + F.x0 + '" y1="' + F.yT + '" y2="' + F.yB + '"/><line class="vz-grid" x1="' + F.x1 + '" x2="' + F.x1 + '" y1="' + F.yT + '" y2="' + F.yB + '"/>' + VZ.txt(F.x0, 14, L[0], { class: 'vz-axl', 'text-anchor': 'middle' }) + VZ.txt(F.x1, 14, L[1], { class: 'vz-axl', 'text-anchor': 'middle' });
    const left = rows.map((r, i) => ({ i, y: sy(VZ.num(r.a) || 0) })).sort((p, q) => p.y - q.y), right = rows.map((r, i) => ({ i, y: sy(VZ.num(r.b) || 0) })).sort((p, q) => p.y - q.y);
    const spread = (arr) => { for (let k = 1; k < arr.length; k++) if (arr[k].y - arr[k - 1].y < 14) arr[k].y = arr[k - 1].y + 14; const over = arr.length ? arr[arr.length - 1].y - (F.yB - 2) : 0; if (over > 0) arr.forEach((p) => { p.y -= over; }); return arr; };
    const ly = {}, ry = {}; spread(left).forEach((p) => { ly[p.i] = p.y; }); spread(right).forEach((p) => { ry[p.i] = p.y; });
    rows.forEach((r, i) => {
      const a = VZ.num(r.a), b = VZ.num(r.b); if (a == null || b == null) return; const d = VZ.delta(a, b, spec.goodDown);
      const sel = spec.selected != null && (spec.selected === i || spec.selected === r.id);
      g += '<line class="vz-slope ' + d.cls + (sel ? ' vz-sel' : '') + '" data-i="' + i + '" x1="' + F.x0 + '" y1="' + VZ.r1(sy(a)) + '" x2="' + F.x1 + '" y2="' + VZ.r1(sy(b)) + '"/>';
      g += '<circle class="vz-pt" data-s="0" cx="' + F.x0 + '" cy="' + VZ.r1(sy(a)) + '" r="4" style="--c:' + C[0] + '"/><circle class="vz-pt" data-s="1" cx="' + F.x1 + '" cy="' + VZ.r1(sy(b)) + '" r="4" style="--c:' + C[1] + '"/>';
      g += VZ.txt(F.x0 - 8, ly[i] + 4, VZ.fitLbl(r.name || '', fmt(a), lblW - 10, 'end'), { class: 'vz-cat', 'text-anchor': 'end' }) + VZ.txt(F.x1 + 8, ry[i] + 4, VZ.fitLbl(r.name || '', fmt(b), lblW - 10, 'start'), { class: 'vz-cat' });
    });
    return { body: g, model: { kind: 'mark', n: rows.length, xs: [], has: () => true, tip: (i) => { const r = rows[i]; const a = VZ.num(r.a), b = VZ.num(r.b); return VZ.tipHead(r.name || '', VZ.delta(a, b, spec.goodDown).text) + VZ.tipRow(C[0], L[0], fmt(a), { kind: 'rect' }) + VZ.tipRow(C[1], L[1], fmt(b), { kind: 'rect' }); }, at: (i) => [(F.x0 + F.x1) / 2, (sy(VZ.num(rows[i].a) || 0) + sy(VZ.num(rows[i].b) || 0)) / 2], datum: (i) => rows[i] } };
  },
  table: VZ.types.dumbbell.table
};
/* ---------- heatmap：矩阵（7×24 节律、转移矩阵）与日历 ---------- */
VZ.rampFill = function (lvl, ramp) {
  // lvl 0..5；gray 用 --h0..--h5；accent / err / corr / good / ai / 任意 var() 用 color-mix 从表面色到主色（最低档落在 --sunken 上，深色模式下格子仍可见）；
  // mood 是发散色：0–2 冷紫（负）、3–5 青绿（正），搭配对称的值域
  if (!ramp || ramp === 'gray') return 'var(--h' + lvl + ')';
  if (ramp === 'mood') { const k = [[VZ.sem.neg, 100], [VZ.sem.neg, 62], [VZ.sem.neg, 26], [VZ.sem.pos, 26], [VZ.sem.pos, 62], [VZ.sem.pos, 100]][lvl]; return 'color-mix(in oklab, ' + k[0] + ' ' + k[1] + '%, var(--surface))'; }
  const base = ramp === 'crit' || ramp === 'err' ? VZ.sem.err : ramp === 'corr' ? VZ.sem.corr : ramp === 'good' ? VZ.sem.good : ramp === 'ai' ? 'var(--ai)' : ramp.startsWith('var(') ? ramp : VZ.ACC;
  return lvl === 0 ? 'color-mix(in oklab, ' + base + ' 7%, var(--sunken))' : 'color-mix(in oklab, ' + base + ' ' + [6, 22, 40, 58, 78, 100][lvl] + '%, var(--surface))';
};
VZ.types.heatmap = {
  name: '热力图',
  isEmpty: (spec) => spec.layout === 'calendar' ? !(spec.days || []).some((d) => VZ.num(d.v) != null) : !(spec.values || []).some((r) => (r || []).some((v) => VZ.num(v) != null)),
  geo(spec, w) {
    const rows = spec.rows || [], cols = spec.cols || []; const gap = spec.gap != null ? spec.gap : 2;
    const labW = rows.some((r) => r != null && r !== '') ? Math.min(Math.round(w * 0.3), Math.ceil(Math.max(...rows.map((r) => VZ.twm(String(r), 11))) + 10)) : 0;
    const cell = clamp(Math.floor((w - labW - 2 - gap * (cols.length - 1)) / Math.max(1, cols.length)), 4, spec.cellMax || 18);
    const cellH = spec.cellH || (spec.square === false ? Math.max(cell, 14) : cell);
    const top = cols.some((c) => c != null && c !== '') && spec.colLabels !== 'bottom' ? 16 : 2;
    const bottom = spec.colLabels === 'bottom' ? 16 : 2;
    return { rows, cols, gap, labW, cell, cellH, top, h: top + rows.length * (cellH + gap) - gap + bottom + 2, x: (c) => labW + c * (cell + gap), y: (r) => top + r * (cellH + gap) };
  },
  height: (spec, w) => spec.layout === 'calendar' ? VZ.types.heatmap.calGeo(spec, w).h : VZ.types.heatmap.geo(spec, w).h,
  // 色阶值域：默认 [min(0, 最小值), 最大值]；mood 发散色默认对称 ±max|v|；spec.min / max 可覆盖
  domain(spec, vals) {
    vals = (vals || []).filter((v) => v != null);
    let mn = spec.min != null ? spec.min : Math.min(0, ...vals), mx = spec.max != null ? spec.max : Math.max(1e-9, ...vals);
    if (spec.ramp === 'mood' && spec.min == null && spec.max == null) { const amp = Math.max(1e-9, ...vals.map(Math.abs)); mn = -amp; mx = amp; }
    return [mn, mx];
  },
  calGeo(spec, w) {
    const days = (spec.days || []).filter((d) => d && d.t != null); const T = VZ.time; const gap = 2;
    const from = spec.from != null ? spec.from : Math.min(...days.map((d) => d.t)), to = spec.to != null ? spec.to : Math.max(...days.map((d) => d.t));
    const d0 = T.local(from); const start = from - ((d0.getUTCDay() + 6) % 7) * T.D; const weeks = Math.max(1, Math.ceil((to - start + 1) / (T.D * 7)));
    const labW = 20; const cell = clamp(Math.floor((w - labW - 2 - gap * (weeks - 1)) / weeks), 5, spec.cellMax || 14);
    return { days, from, to, start, weeks, gap, labW, cell, top: 16, h: 16 + 7 * (cell + gap) + 2, x: (wk) => labW + wk * (cell + gap), y: (wd) => 16 + wd * (cell + gap) };
  },
  render(spec, w, h) {
    if (spec.layout === 'calendar') return VZ.types.heatmap.renderCal(spec, w, h);
    const G = VZ.types.heatmap.geo(spec, w); const V = spec.values || []; const fmt = (v) => VZ.fmt(v, spec.format);
    const flat = V.flat().map(VZ.num).filter((v) => v != null); const [mn, mx] = VZ.types.heatmap.domain(spec, flat);
    const lvl = (v) => v == null ? -1 : clamp(Math.floor((v - mn) / (mx - mn || 1) * 5.999), 0, 5);
    let g = ''; const nC = G.cols.length, nR = G.rows.length;
    const every = Math.max(1, Math.ceil((Math.max(...G.cols.map((c) => VZ.twm(String(c), 11))) + 6) / (G.cell + G.gap)));
    G.cols.forEach((c, j) => { if (j % every) return; if (c == null || c === '') return; g += VZ.txt(G.x(j) + G.cell / 2, spec.colLabels === 'bottom' ? G.y(nR - 1) + G.cellH + 12 : 11, String(c), { class: 'vz-ax', 'text-anchor': 'middle' }); });
    G.rows.forEach((r, i) => { if (r == null || r === '') return; g += VZ.txt(G.labW - 6, G.y(i) + G.cellH / 2 + 3.5, String(r), { class: 'vz-ax', 'text-anchor': 'end' }); });
    let peak = null;
    for (let i = 0; i < nR; i++) for (let j = 0; j < nC; j++) {
      const v = VZ.num((V[i] || [])[j]); const L = lvl(v); const idx = i * nC + j;
      const sel = spec.selected && spec.selected.r === i && spec.selected.c === j;
      g += '<rect class="vz-cell' + (L < 0 ? ' vz-na' : '') + (sel ? ' vz-sel' : '') + '" data-i="' + idx + '" x="' + G.x(j) + '" y="' + G.y(i) + '" width="' + G.cell + '" height="' + G.cellH + '" rx="' + Math.min(3, G.cell / 4) + '"' + (L >= 0 ? ' style="fill:' + VZ.rampFill(L, spec.ramp) + '"' : '') + '/>';
      if (spec.showValues && v != null && G.cell >= 20) g += VZ.txt(G.x(j) + G.cell / 2, G.y(i) + G.cellH / 2 + 3.5, fmt(v), { class: 'vz-cv' + (L >= 4 ? ' on' : ''), 'text-anchor': 'middle' });
      if (v != null && (peak == null || v > peak.v)) peak = { v, i, j };
    }
    if (spec.peak && peak && peak.v > 0) g += '<rect class="vz-peak" x="' + (G.x(peak.j) - 2) + '" y="' + (G.y(peak.i) - 2) + '" width="' + (G.cell + 4) + '" height="' + (G.cellH + 4) + '" rx="4"/>';
    return { body: g, model: { kind: 'mark', n: nR * nC, xs: [], has: (i) => VZ.num((V[Math.floor(i / nC)] || [])[i % nC]) != null, tip: (i) => { const r = Math.floor(i / nC), c = i % nC; const v = VZ.num((V[r] || [])[c]); return VZ.tipHead((spec.tipHead ? spec.tipHead(r, c) : String(G.rows[r] == null ? '' : G.rows[r]) + (G.cols[c] != null ? ' · ' + G.cols[c] : ''))) + VZ.tipRow(VZ.rampFill(Math.max(0, lvl(v)), spec.ramp), spec.unit || '', fmt(v), { kind: 'rect' }) + (spec.tipExtra ? spec.tipExtra(r, c) : ''); }, at: (i) => [G.x(i % nC) + G.cell / 2, G.y(Math.floor(i / nC))], datum: (i) => ({ r: Math.floor(i / nC), c: i % nC, row: G.rows[Math.floor(i / nC)], col: G.cols[i % nC], value: VZ.num((V[Math.floor(i / nC)] || [])[i % nC]) }), peak } };
  },
  renderCal(spec, w, h) {
    const G = VZ.types.heatmap.calGeo(spec, w); const T = VZ.time; const fmt = (v) => VZ.fmt(v, spec.format);
    const byDay = {}; G.days.forEach((d) => { byDay[Math.floor((d.t - G.start) / T.D)] = d; });
    const vals = G.days.map((d) => VZ.num(d.v)).filter((v) => v != null); const [mn, mx] = VZ.types.heatmap.domain(spec, vals);
    const lvl = (v) => v == null ? -1 : clamp(Math.floor((v - mn) / (mx - mn || 1) * 5.999), 0, 5);
    let g = ''; ['一', '', '三', '', '五', '', '日'].forEach((l, i) => { if (l) g += VZ.txt(G.labW - 6, G.y(i) + G.cell / 2 + 3.5, l, { class: 'vz-ax', 'text-anchor': 'end' }); });
    const cells = []; let lastMonth = -1;
    for (let wk = 0; wk < G.weeks; wk++) {
      const m = T.local(G.start + wk * 7 * T.D).getUTCMonth(); if (m !== lastMonth) { lastMonth = m; g += VZ.txt(G.x(wk), 11, (m + 1) + ' 月', { class: 'vz-ax' }); }
      for (let wd = 0; wd < 7; wd++) { const k = wk * 7 + wd; const t = G.start + k * T.D; if (t < G.from - T.D / 2 || t > G.to + T.D / 2) continue; const d = byDay[k]; const v = d ? VZ.num(d.v) : null; const L = lvl(v); const idx = cells.length; cells.push({ t, v, d }); g += '<rect class="vz-cell' + (L < 0 ? ' vz-na' : '') + '" data-i="' + idx + '" x="' + G.x(wk) + '" y="' + G.y(wd) + '" width="' + G.cell + '" height="' + G.cell + '" rx="2"' + (L >= 0 ? ' style="fill:' + VZ.rampFill(L, spec.ramp) + '"' : '') + '/>'; }
    }
    return { body: g, model: { kind: 'mark', n: cells.length, xs: [], has: () => true, tip: (i) => { const c = cells[i]; return VZ.tipHead(T.ymd(c.t) + ' 周' + T.wd(c.t)) + VZ.tipRow(VZ.rampFill(Math.max(0, lvl(c.v)), spec.ramp), spec.unit || '', fmt(c.v), { kind: 'rect' }); }, at: (i) => { const k = Math.floor((cells[i].t - G.start) / T.D); return [G.x(Math.floor(k / 7)) + G.cell / 2, G.y(k % 7)]; }, datum: (i) => cells[i] } };
  },
  extra(spec) { if (spec.scale === false) return ''; const fmt = (v) => VZ.fmt(v, spec.format); const flat = spec.layout === 'calendar' ? (spec.days || []).map((d) => VZ.num(d.v)) : (spec.values || []).flat().map(VZ.num); const vals = flat.filter((v) => v != null); if (!vals.length) return ''; const [mn, mx] = VZ.types.heatmap.domain(spec, vals); return '<div class="vz-scale" aria-label="色阶：' + fmt(mn) + ' 到 ' + fmt(mx) + '"><span class="cap">' + esc(spec.scaleLabels ? spec.scaleLabels[0] : fmt(mn)) + '</span>' + [0, 1, 2, 3, 4, 5].map((l) => '<i style="background:' + VZ.rampFill(l, spec.ramp) + '"></i>').join('') + '<span class="cap">' + esc(spec.scaleLabels ? spec.scaleLabels[1] : fmt(mx)) + '</span>' + (spec.scaleNote ? '<span class="cap vz-scale-note">' + esc(spec.scaleNote) + '</span>' : '') + '</div>'; },
  table(spec) {
    if (spec.layout === 'calendar') return { cols: ['日期', spec.unit || '值'], rows: (spec.days || []).map((d) => [VZ.time.ymd(d.t), VZ.fmt(VZ.num(d.v), spec.format)]) };
    return { cols: [''].concat((spec.cols || []).map(String)), rows: (spec.rows || []).map((r, i) => [String(r)].concat(((spec.values || [])[i] || []).map((v) => VZ.fmt(VZ.num(v), spec.format)))) };
  }
};
/* ---------- scatter：气泡 + 回归 + 95% CI + 标签避让 ---------- */
VZ.fit = function (pts) {
  const n = pts.length; if (n < 3) return null;
  const mx = pts.reduce((a, p) => a + p.x, 0) / n, my = pts.reduce((a, p) => a + p.y, 0) / n;
  const sxx = pts.reduce((a, p) => a + (p.x - mx) ** 2, 0), syy = pts.reduce((a, p) => a + (p.y - my) ** 2, 0), sxy = pts.reduce((a, p) => a + (p.x - mx) * (p.y - my), 0);
  if (!sxx || !syy) return null; const b = sxy / sxx, a = my - b * mx;
  const sse = pts.reduce((acc, p) => acc + (p.y - (a + b * p.x)) ** 2, 0); const s2 = n > 2 ? sse / (n - 2) : 0;
  const tt = [12.71, 4.3, 3.18, 2.78, 2.57, 2.45, 2.36, 2.31, 2.26, 2.23, 2.2, 2.18, 2.16, 2.14, 2.13, 2.12, 2.11, 2.1, 2.09, 2.09, 2.08, 2.07, 2.07, 2.06, 2.06, 2.06, 2.05, 2.05, 2.05, 2.04]; const t = n - 2 <= 30 ? tt[n - 3] : 1.96;
  return { a, b, r: sxy / Math.sqrt(sxx * syy), n, se: (x) => Math.sqrt(s2 * (1 / n + (x - mx) ** 2 / sxx)) * t, pred: (x) => a + b * x };
};
VZ.types.scatter = {
  name: '散点图',
  isEmpty: (spec) => !(spec.points || []).some((p) => VZ.num(p.x) != null && VZ.num(p.y) != null),
  render(spec, w, h, ctx) {
    const all = (spec.points || []).map((p, i) => Object.assign({ _i: i }, p)).filter((p) => VZ.num(p.x) != null && VZ.num(p.y) != null && (p.series == null || ctx.vis[p.series] !== false));
    const X = spec.x || {}, Y = spec.y || {}; const fx = (v) => VZ.fmt(v, X.format), fy = (v) => VZ.fmt(v, Y.format);
    const fit = spec.fit && all.length >= 3 ? VZ.fit(all) : null;
    let xs0 = Math.min(...all.map((p) => p.x)), xs1 = Math.max(...all.map((p) => p.x)), ys0 = Math.min(...all.map((p) => p.y)), ys1 = Math.max(...all.map((p) => p.y));
    if (X.zero !== false) xs0 = Math.min(0, xs0); if (Y.zero !== false) ys0 = Math.min(0, ys0);
    if (fit) all.forEach((p) => { ys0 = Math.min(ys0, fit.pred(p.x) - fit.se(p.x)); ys1 = Math.max(ys1, fit.pred(p.x) + fit.se(p.x)); });
    let [x0, x1] = VZ.nice(xs0, xs1, 5), [y0, y1] = VZ.nice(ys0, ys1, 5); if (X.min != null) x0 = X.min; if (X.max != null) x1 = X.max; if (Y.min != null) y0 = Y.min; if (Y.max != null) y1 = Y.max;
    const F = VZ.frame(spec, w, h, { domain: [y0, y1], fmtY: fy, top: 12, right: 14 }); const sx = VZ.scale.linear(x0, x1, F.x0, F.x1);
    const xt = VZ.ticks(x0, x1, Math.max(2, Math.floor(F.pw / 70)));
    let g = VZ.grid(F, { noBase: true }) + xt.map((v) => { const x = VZ.r1(sx(v)); return '<line class="vz-grid" x1="' + x + '" x2="' + x + '" y1="' + F.yT + '" y2="' + F.yB + '"/>'; }).join('') + VZ.axisX(F, xt.map((v) => ({ x: sx(v), label: fx(v) })), { label: X.label });
    if (Y.label) g += VZ.txt(F.x0 + 4, F.yT + 11, Y.label, { class: 'vz-axl' });
    const hasR = all.some((p) => VZ.num(p.r) != null); const rMax = spec.rMax || 20; const rmx = hasR ? Math.max(1e-9, ...all.map((p) => VZ.num(p.r) || 0)) : 1;
    const rad = (p) => hasR ? 4 + Math.sqrt((VZ.num(p.r) || 0) / rmx) * (rMax - 4) : (spec.r || 5);
    if (fit) {
      // 回归线 + 95% 置信带；拟合读数（r、n）放在图下方的说明行（extra），不与点和标签争位置
      const xa = Math.min(...all.map((p) => p.x)), xb = Math.max(...all.map((p) => p.x)); const K = 24; let up = '', dn = '';
      for (let k = 0; k <= K; k++) { const x = xa + (xb - xa) * k / K; const yp = fit.pred(x), se = fit.se(x); up += (up ? 'L' : 'M') + VZ.r1(sx(x)) + ' ' + VZ.r1(F.y(clamp(yp + se, y0, y1))); dn = 'L' + VZ.r1(sx(x)) + ' ' + VZ.r1(F.y(clamp(yp - se, y0, y1))) + dn; }
      g += '<path class="vz-cband" d="' + up + dn + 'Z" style="--c:var(--ink-3)"/><line class="vz-fit' + (fit.n < 10 ? ' weak' : '') + '" x1="' + VZ.r1(sx(xa)) + '" y1="' + VZ.r1(F.y(clamp(fit.pred(xa), y0, y1))) + '" x2="' + VZ.r1(sx(xb)) + '" y2="' + VZ.r1(F.y(clamp(fit.pred(xb), y0, y1))) + '"/>';
    }
    const order = all.slice().sort((p, q) => rad(q) - rad(p)); const boxes = []; const placed = {};
    order.forEach((p) => { const cx = sx(p.x), cy = F.y(p.y), r = rad(p); const sel = spec.selected != null && (spec.selected === p._i || (p.id != null && spec.selected === p.id)); const c = p.color || (p.series != null ? VZ.color(p.series) : spec.color || VZ.ACC); g += '<circle class="vz-dot' + (hasR ? ' vz-bubble' : '') + (sel ? ' vz-sel' : '') + '" data-i="' + p._i + '" cx="' + VZ.r1(cx) + '" cy="' + VZ.r1(cy) + '" r="' + VZ.r1(r) + '" style="--c:' + c + '"/>'; boxes.push([cx - r, cy - r, cx + r, cy + r]); });
    if (spec.labels !== false) order.forEach((p) => {
      if (p.label == null || p.label === '') return; const cx = sx(p.x), cy = F.y(p.y), r = rad(p); const tw = VZ.tw(p.label, 11), th = 12;
      const cands = [[cx + r + 4, cy + 4, 'start'], [cx - r - 4, cy + 4, 'end'], [cx, cy - r - 5, 'middle'], [cx, cy + r + 12, 'middle']];
      for (const [lx, ly, an] of cands) { const bx0 = an === 'start' ? lx : an === 'end' ? lx - tw : lx - tw / 2, bx1 = bx0 + tw, by0 = ly - th + 2, by1 = ly + 2; if (bx0 < F.x0 - 2 || bx1 > w - 2 || by0 < F.yT - 2 || by1 > F.yB + 2) continue; if (boxes.some((b) => bx0 < b[2] && bx1 > b[0] && by0 < b[3] && by1 > b[1] && !(Math.abs(b[0] - (cx - r)) < 0.01 && Math.abs(b[1] - (cy - r)) < 0.01))) continue; boxes.push([bx0, by0, bx1, by1]); placed[p._i] = 1; g += VZ.txt(lx, ly, p.label, { class: 'vz-lbl' + (spec.selected != null && (spec.selected === p._i || spec.selected === p.id) ? ' vz-strong' : ''), 'text-anchor': an }); break; }
    });
    order.forEach((p) => { g += '<circle class="vz-hit vz-hit-pt" data-i="' + p._i + '" cx="' + VZ.r1(sx(p.x)) + '" cy="' + VZ.r1(F.y(p.y)) + '" r="' + VZ.r1(Math.max(12, rad(p) + 6)) + '"/>'; });
    const P = spec.points || [];
    return { body: g, model: { kind: 'mark', n: P.length, F, xs: [], has: (i) => all.some((p) => p._i === i), tip: (i) => { const p = P[i]; const res = fit ? p.y - fit.pred(p.x) : null; return VZ.tipHead(p.label || p.name || '', p.meta || '') + VZ.tipRow(p.color || (p.series != null ? VZ.color(p.series) : spec.color || VZ.ACC), X.label || 'x', fx(p.x), { kind: 'rect' }) + VZ.tipRow('transparent', Y.label || 'y', fy(p.y)) + (hasR && p.r != null ? VZ.tipRow('transparent', spec.rLabel || '大小', VZ.fmt(p.r, spec.rFormat)) : '') + (res != null ? '<div class="vz-tr"><span class="vz-tk" style="--c:var(--ink-3)"></span><span class="vz-tn">' + (res >= 0 ? '高于拟合预期 ' : '低于拟合预期 ') + fy(Math.abs(res)) + '</span></div>' : ''); }, at: (i) => [sx(P[i].x), F.y(P[i].y)], datum: (i) => P[i], brushRange: (a, c) => [sx.inv(a), sx.inv(c)], fit } };
  },
  // 图下说明行：拟合读数 + 气泡尺寸图例（评审 A5-V04）
  extra(spec, w, model) {
    const fit = model && model.fit; const hasR = (spec.points || []).some((p) => VZ.num(p.r) != null); if (!fit && !hasR) return '';
    const rmx = hasR ? Math.max(1e-9, ...(spec.points || []).map((p) => VZ.num(p.r) || 0)) : 0;
    return '<div class="vz-scale">' + (fit ? '<span class="cap">拟合 r = ' + fit.r.toFixed(2) + ' · ' + VZ.fmt(fit.n, 'int') + ' ' + (spec.nUnit || '个点') + ' · 带为 95% 置信区间' + (fit.n < 10 ? '（样本少，仅供参考）' : '') + '</span>' : '') + (hasR ? '<span class="cap vz-scale-note"><i class="vz-rleg" style="width:12px;height:12px"></i>' + esc(VZ.fmt(rmx / 4, spec.rFormat)) + ' <i class="vz-rleg" style="width:20px;height:20px"></i>' + esc(VZ.fmt(rmx, spec.rFormat)) + (spec.rLabel ? ' · ' + esc(spec.rLabel) : '') + '</span>' : '') + '</div>';
  },
  table: (spec) => { const X = spec.x || {}, Y = spec.y || {}; const hasR = (spec.points || []).some((p) => p.r != null); return { cols: ['名称', X.label || 'x', Y.label || 'y'].concat(hasR ? [spec.rLabel || '大小'] : []), rows: (spec.points || []).map((p) => [p.label || p.name || '', VZ.fmt(VZ.num(p.x), X.format), VZ.fmt(VZ.num(p.y), Y.format)].concat(hasR ? [VZ.fmt(VZ.num(p.r), spec.rFormat)] : [])) }; }
};
/* ---------- dist：箱线 / 蜂群分布 ---------- */
VZ.stats = function (values) {
  const v = (values || []).map(VZ.num).filter((x) => x != null).sort((a, b) => a - b); const n = v.length; if (!n) return null;
  const q = (p) => { const k = (n - 1) * p, lo = Math.floor(k), hi = Math.ceil(k); return v[lo] + (v[hi] - v[lo]) * (k - lo); };
  return { n, min: v[0], max: v[n - 1], p10: q(0.1), p25: q(0.25), p50: q(0.5), p75: q(0.75), p90: q(0.9), mean: v.reduce((a, b) => a + b, 0) / n, sorted: v };
};
VZ.types.dist = {
  name: '分布',
  isEmpty: (spec) => !(spec.rows || []).some((r) => (r.values || []).some((v) => VZ.num(v) != null)),
  height: (spec) => (spec.rows || []).length * (spec.rowH || (spec.mode === 'dots' ? 34 : 28)) + 24,
  render(spec, w, h) {
    const rows = spec.rows || []; const S = rows.map((r) => VZ.stats(r.values)); const fmt = (v) => VZ.fmt(v, spec.format); const dots = spec.mode === 'dots';
    const lo0 = Math.min(0, ...S.filter(Boolean).map((s) => dots || spec.whisker === 'minmax' ? s.min : s.p10)), hi0 = Math.max(1e-9, ...S.filter(Boolean).map((s) => dots || spec.whisker === 'minmax' ? s.max : s.p90));
    let [lo, hi] = VZ.nice(lo0, hi0, 5); if (spec.min != null) lo = spec.min; if (spec.max != null) hi = spec.max;
    const nW = 44; const F = VZ.rowsFrame(spec, w, h, rows, { rightW: nW, axis: true, leftExtra: 8 });
    const sx = VZ.scale.linear(lo, hi, F.x0, F.x1); const bh = Math.min(14, F.step * 0.55);
    let g = VZ.axisBottom(F, sx, VZ.ticks(lo, hi, Math.max(2, Math.floor(F.pw / 70))), fmt);
    rows.forEach((r, i) => {
      const s = S[i]; const cy = F.by(i); g += F.name(i); if (!s) return; const c = r.color || spec.color || 'var(--ink-2)';
      if (dots) {
        const rr = 3; const placed = []; const maxOff = Math.floor((F.step / 2 - rr) / (rr * 2 + 0.5));
        s.sorted.forEach((v) => { const x = sx(clamp(v, lo, hi)); let off = 0; for (let k = 0; k <= maxOff * 2; k++) { const cand = k === 0 ? 0 : (k % 2 ? (k + 1) / 2 : -(k / 2)); const y = cy + cand * (rr * 2 + 0.5); if (!placed.some((p) => Math.abs(p[0] - x) < rr * 2 + 0.5 && Math.abs(p[1] - y) < rr * 2 + 0.5)) { off = cand; break; } } const y = cy + off * (rr * 2 + 0.5); placed.push([x, y]); g += '<circle class="vz-swarm" cx="' + VZ.r1(x) + '" cy="' + VZ.r1(y) + '" r="' + rr + '" style="--c:' + c + '"/>'; });
        g += '<line class="vz-median" x1="' + VZ.r1(sx(s.p50)) + '" x2="' + VZ.r1(sx(s.p50)) + '" y1="' + VZ.r1(cy - F.step / 2 + 3) + '" y2="' + VZ.r1(cy + F.step / 2 - 3) + '"/>';
      } else {
        const wa = spec.whisker === 'minmax' ? s.min : s.p10, wb = spec.whisker === 'minmax' ? s.max : s.p90;
        g += '<line class="vz-whisker" x1="' + VZ.r1(sx(wa)) + '" x2="' + VZ.r1(sx(wb)) + '" y1="' + VZ.r1(cy) + '" y2="' + VZ.r1(cy) + '"/>';
        g += '<rect class="vz-box" data-i="' + i + '" x="' + VZ.r1(sx(s.p25)) + '" y="' + VZ.r1(cy - bh / 2) + '" width="' + VZ.r1(Math.max(2, sx(s.p75) - sx(s.p25))) + '" height="' + bh + '" rx="2" style="--c:' + c + '"/>';
        g += '<line class="vz-median" x1="' + VZ.r1(sx(s.p50)) + '" x2="' + VZ.r1(sx(s.p50)) + '" y1="' + VZ.r1(cy - bh / 2 - 2) + '" y2="' + VZ.r1(cy + bh / 2 + 2) + '"/>';
        if (spec.mean) g += '<circle class="vz-pt" cx="' + VZ.r1(sx(s.mean)) + '" cy="' + VZ.r1(cy) + '" r="3" style="--c:var(--ink-1)"/>';
      }
      g += VZ.txt(w - 2, cy + 4, VZ.fmt(s.n, 'int') + ' ' + (spec.nUnit || '个'), { class: 'vz-ax', 'text-anchor': 'end' }) + F.hit(i);
    });
    return { body: g, model: { kind: 'mark', n: rows.length, F, xs: [], has: (i) => !!S[i], tip: (i) => { const s = S[i]; const r = rows[i]; if (!s) return ''; return VZ.tipHead(r.name || '', VZ.fmt(s.n, 'int') + ' ' + (spec.nUnit || '个')) + VZ.tipRow('var(--ink-1)', '中位数', fmt(s.p50), { kind: 'rect' }) + VZ.tipRow(r.color || spec.color || 'var(--ink-2)', 'P25 – P75', fmt(s.p25) + ' – ' + fmt(s.p75), { kind: 'rect' }) + VZ.tipRow('transparent', '均值', fmt(s.mean)) + VZ.tipRow('transparent', spec.whisker === 'minmax' ? '最小 – 最大' : 'P10 – P90', fmt(spec.whisker === 'minmax' ? s.min : s.p10) + ' – ' + fmt(spec.whisker === 'minmax' ? s.max : s.p90)); }, at: (i) => [S[i] ? sx(S[i].p50) : F.x0, F.by(i)], datum: (i) => Object.assign({ row: rows[i] }, S[i] || {}) } };
  },
  table: (spec) => ({ cols: ['名称', '样本数', '中位数', 'P25', 'P75', '均值'], rows: (spec.rows || []).map((r) => { const s = VZ.stats(r.values); return s ? [r.name || '', String(s.n), VZ.fmt(s.p50, spec.format), VZ.fmt(s.p25, spec.format), VZ.fmt(s.p75, spec.format), VZ.fmt(s.mean, spec.format)] : [r.name || '', '0', '—', '—', '—', '—']; }) })
};
/* ---------- spark / kpi ---------- */
VZ.sparkBody = function (values, w, h, opt) {
  opt = opt || {}; const vals = (values || []).map(VZ.num); const valid = vals.filter((v) => v != null); if (!valid.length) return '';
  const mn = opt.min != null ? opt.min : (opt.zero ? Math.min(0, ...valid) : Math.min(...valid)), mx = opt.max != null ? opt.max : Math.max(...valid); const n = vals.length;
  const X = (i) => 2 + i * ((w - 4) / Math.max(1, n - 1)), Y = (v) => 2 + (1 - (v - mn) / ((mx - mn) || 1)) * (h - 4);
  // 评审 G-04 / D-02：线 --ink-3 1.5px，末点强调色（深色模式下 --ink-4 太淡）
  const c = opt.color || 'var(--ink-3)'; const last = opt.last || VZ.ACC;
  if (opt.bars) { const bw = Math.max(1, (w - 2) / n - 1); return vals.map((v, i) => v == null ? '' : '<rect x="' + VZ.r1(1 + i * (bw + 1)) + '" y="' + VZ.r1(Y(v)) + '" width="' + VZ.r1(bw) + '" height="' + VZ.r1(h - 2 - Y(v)) + '" rx="1" fill="' + (i === n - 1 ? last : c) + '"/>').join(''); }
  const pts = vals.map((v, i) => v == null ? null : [X(i), Y(v)]); let g = '';
  if (opt.area) { const sg = pts.filter(Boolean); if (sg.length) g += '<path d="' + VZ.linePath(sg) + 'L' + VZ.r1(sg[sg.length - 1][0]) + ' ' + (h - 2) + 'L' + VZ.r1(sg[0][0]) + ' ' + (h - 2) + 'Z" fill="' + c + '" fill-opacity=".12"/>'; }
  g += '<path d="' + VZ.linePath(pts) + '" fill="none" stroke="' + c + '" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>';
  if (opt.ref != null) g += '<line x1="2" x2="' + (w - 2) + '" y1="' + VZ.r1(Y(opt.ref)) + '" y2="' + VZ.r1(Y(opt.ref)) + '" stroke="var(--line)" stroke-dasharray="2 2"/>';
  let li = -1; vals.forEach((v, i) => { if (v != null) li = i; });
  if (li >= 0 && opt.dot !== false) g += '<circle cx="' + VZ.r1(X(li)) + '" cy="' + VZ.r1(Y(vals[li])) + '" r="2.5" fill="' + last + '" stroke="var(--surface)" stroke-width="1.5"/>';
  return g;
};
VZ.spark = function (values, opt) { opt = opt || {}; const w = opt.w || 80, h = opt.h || 24; return '<svg class="vz-spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '"' + (opt.label ? ' role="img" aria-label="' + esc(opt.label) + '"' : ' aria-hidden="true"') + '>' + VZ.sparkBody(values, w, h, opt) + '</svg>'; };
VZ.types.spark = { name: '迷你趋势', isEmpty: (spec) => !(spec.values || []).some((v) => VZ.num(v) != null), render: (spec, w, h) => ({ body: VZ.sparkBody(spec.values, w, h, spec), model: null }), table: (spec) => ({ cols: ['序号', '值'], rows: (spec.values || []).map((v, i) => [String(i + 1), VZ.fmt(VZ.num(v))]) }) };
// 环比三件套（评审 A1-V01 / V03）：▲▼ 符号 + 变化量 + 上期值；按极性（goodDown）着色，中性指标灰色。
// d: { cur, prev, unit: 'pct' | 'pt' | 'x', goodDown, fmt（上期值格式）, prevText: false 省略上期, none（无上期文案） } 或直接 { text, cls }
VZ.delta2 = function (d) {
  if (!d) return null; if (d.text != null) return d;
  if (d.prev == null || d.cur == null) return { text: d.none || '无可比上期', cls: '' };
  const diff = d.unit === 'pt' || d.unit === 'x' ? d.cur - d.prev : (d.prev ? (d.cur - d.prev) / Math.abs(d.prev) * 100 : null);
  if (diff == null) return { text: '—', cls: '' };
  const flat = Math.abs(diff) < 1e-9; const good = d.goodDown == null || flat ? null : (diff < 0) === d.goodDown;
  const mag = d.unit === 'pt' ? VZ.fmt(Math.abs(diff), '1f') + ' pt' : d.unit === 'x' ? VZ.fmt(Math.abs(diff), '1f') + '×' : Math.round(Math.abs(diff)) + '%';
  const prev = typeof d.fmt === 'function' ? d.fmt(d.prev) : VZ.fmt(d.prev, d.fmt);
  return { text: (flat ? '± 0' : (diff > 0 ? '▲ ' : '▼ ') + mag) + (d.prevText === false ? '' : ' · 上期 ' + prev), cls: good == null ? '' : good ? 'vz-good' : 'vz-bad', diff };
};
// KPI tile：{ label, value, unit, delta（见 VZ.delta2）, trend: [n], trendLabel（迷你线周期，如「近 12 周」）, sub, act, attrs, tip, tf, cls }
// trendLabel 只说明迷你线：没有可画的趋势（trend 为空 / 全为 null）时不显示，免得「36 近 12 周」读成 12 周的总数
VZ.kpi = function (o) {
  const d = VZ.delta2(o.delta); const tl = o.trendLabel && (o.trend || []).some((v) => VZ.num(v) != null) ? o.trendLabel : null;
  return '<' + (o.act ? 'button type="button"' : 'div') + ' class="card tile vz-kpi' + (o.cls ? ' ' + o.cls : '') + '"' + (o.act ? ' data-act="' + esc(o.act) + '"' + (o.attrs || '') : '') + (o.tip ? ' data-tip="' + esc(o.tip) + '"' : '') + (o.tf ? ' data-tf="' + esc(o.tf) + '"' : '') + '><span class="row vz-kpi-h"><span class="vz-kpi-l">' + esc(o.label) + '</span>' + (o.trend ? VZ.spark(o.trend, Object.assign({ w: 80, h: 24, label: o.trendLabel ? o.label + '：' + o.trendLabel : null }, o.sparkOpt || {})) : '') + '</span><span class="row vz-kpi-v"><span class="v">' + esc(o.value) + '</span>' + (o.unit ? '<span class="vz-kpi-u">' + esc(o.unit) + '</span>' : '') + (tl ? '<span class="vz-kpi-p">' + esc(tl) + '</span>' : '') + '</span><span class="vz-kpi-d ' + (d ? d.cls : '') + '">' + (d && d.text ? esc(d.text) : (o.sub ? esc(o.sub) : '&nbsp;')) + '</span></' + (o.act ? 'button' : 'div') + '>';
};
/* ---------- multiples：小倍数 ---------- */
VZ.types.multiples = {
  name: '小倍数',
  isEmpty: (spec) => !(spec.items || []).length,
  height: (spec) => spec.cellH || 140,
  shared(spec) { if (!spec.shareY) return null; let lo = Infinity, hi = -Infinity; (spec.items || []).forEach((it) => { (it.spec.series || []).forEach((s) => (s.values || []).forEach((v) => { const y = VZ.val(v); if (y != null) { lo = Math.min(lo, y); hi = Math.max(hi, y); } })); }); if (!Number.isFinite(lo)) return null; const [a, b] = VZ.nice(Math.min(0, lo), hi, 4); return { min: a, max: b }; },
  child(spec, it) { const y = VZ.types.multiples.shared(spec); return Object.assign({}, it.spec, { legend: false, height: spec.cellH || 140, title: it.title || it.spec.title }, y ? { y: Object.assign({}, it.spec.y || {}, y) } : {}); },
  html(spec) { return '<div class="vz-grid" style="--minw:' + (spec.minW || 220) + 'px">' + (spec.items || []).map((it, i) => '<div class="vz-cell-wrap"><div class="vz-ct">' + esc(it.title || '') + (it.sub ? '<span class="cap">' + esc(it.sub) + '</span>' : '') + '</div><div class="vz vz-child" data-vzi="' + i + '"></div></div>').join('') + '</div>'; },
  mountChildren(el, spec) { el.querySelectorAll('.vz-child').forEach((c) => { const it = (spec.items || [])[+c.dataset.vzi]; if (it) VZ.mount(c, VZ.types.multiples.child(spec, it)); }); },
  render(spec, w, h) { const items = spec.items || []; const cols = Math.max(1, Math.floor((w + 12) / ((spec.minW || 220) + 12))); const cw = (w - 12 * (cols - 1)) / cols; const ch = spec.cellH || 140; let g = ''; items.forEach((it, i) => { const x = (i % cols) * (cw + 12), y = Math.floor(i / cols) * (ch + 28); g += VZ.txt(x, y + 12, it.title || '', { class: 'vz-ct-svg' }) + '<svg x="' + VZ.r1(x) + '" y="' + (y + 18) + '" width="' + VZ.r1(cw) + '" height="' + ch + '">' + VZ.svg(VZ.types.multiples.child(spec, it), Math.floor(cw), ch) + '</svg>'; }); return { body: g, model: null }; },
  svgHeight: (spec, w) => { const items = spec.items || []; const cols = Math.max(1, Math.floor((w + 12) / ((spec.minW || 220) + 12))); return Math.ceil(items.length / cols) * ((spec.cellH || 140) + 28); },
  table(spec) { const items = spec.items || []; if (!items.length) return { cols: [], rows: [] }; const first = VZ.types[items[0].spec.type]; const d0 = first && first.table ? first.table(items[0].spec) : VZ.xyTable(items[0].spec); return { cols: ['面板'].concat(d0.cols), rows: items.flatMap((it) => { const t = VZ.types[it.spec.type]; const d = t && t.table ? t.table(it.spec) : VZ.xyTable(it.spec); return d.rows.map((r) => [it.title || ''].concat(r)); }) }; }
};
/* ---------- flow：简化 Sankey（工具调用链、阶段流转） ---------- */
VZ.types.flow = {
  name: '流向图',
  isEmpty: (spec) => !(spec.links || []).some((l) => VZ.num(l.value) > 0),
  layout(spec, w, h) {
    const links = (spec.links || []).filter((l) => VZ.num(l.value) > 0); const N = {}; const order = [];
    const add = (id, extra) => { if (!N[id]) { N[id] = Object.assign({ id, name: id, in: 0, out: 0, col: null }, extra || {}); order.push(id); } else if (extra) Object.assign(N[id], extra); return N[id]; };
    (spec.nodes || []).forEach((n) => add(n.id, n)); links.forEach((l) => { add(l.from); add(l.to); N[l.from].out += l.value; N[l.to].in += l.value; });
    // 列：显式 col，否则按最长路径
    const ids = order; let changed = true, guard = 0; ids.forEach((id) => { if (N[id].col == null) N[id].col = 0; });
    while (changed && guard++ < 50) { changed = false; links.forEach((l) => { if (l.from === l.to) return; const a = N[l.from], b = N[l.to]; if ((spec.nodes || []).some((n) => n.id === b.id && n.col != null)) return; if (b.col <= a.col) { b.col = a.col + 1; changed = true; } }); }
    const C = Math.max(...ids.map((id) => N[id].col)) + 1; const cols = Array.from({ length: C }, () => []);
    ids.forEach((id) => { if (N[id].in + N[id].out > 0) cols[N[id].col].push(N[id]); });
    if (spec.sort !== false) cols.forEach((c) => c.sort((a, b) => Math.max(b.in, b.out) - Math.max(a.in, a.out)));
    const gap = 8; const yT = 6, yB = h - 6; const ph = yB - yT;
    const k = Math.min(...cols.map((c) => (ph - gap * (c.length - 1)) / Math.max(1e-9, c.reduce((a, n) => a + Math.max(n.in, n.out), 0))));
    const nodeW = 8; const x0 = 4, x1 = w - 4 - nodeW;
    cols.forEach((c, ci) => { const tot = c.reduce((a, n) => a + Math.max(n.in, n.out) * k, 0) + gap * (c.length - 1); let y = yT + (ph - tot) / 2; c.forEach((n, ni) => { n.h = Math.max(2, Math.max(n.in, n.out) * k); n.x = C === 1 ? x0 : x0 + ci * (x1 - x0) / (C - 1); n.y = y; y += n.h + gap; n.ci = ci; n.ni = ni; n.oy = 0; n.iy = 0; }); });
    const firstCol = cols[0]; firstCol.forEach((n, i) => { if (!n.color) n.color = VZ.color(i); });
    const L = links.map((l, i) => { const a = N[l.from], b = N[l.to]; const t = l.value * k; const p = { i, l, a, b, t, y1: a.y + a.oy, y2: b.y + b.iy, color: l.color || a.color || 'var(--h3)' }; a.oy += t; b.iy += t; return p; });
    return { N, cols, links: L, nodeW, k, C };
  },
  render(spec, w, h) {
    const G = VZ.types.flow.layout(spec, w, h); const fmt = (v) => VZ.fmt(v, spec.format); let g = '';
    G.links.forEach((p) => { const x1 = p.a.x + G.nodeW, x2 = p.b.x; const xm = (x1 + x2) / 2; const R = VZ.r1; g += '<path class="vz-ribbon" data-i="' + p.i + '" d="M' + R(x1) + ' ' + R(p.y1) + 'C' + R(xm) + ' ' + R(p.y1) + ' ' + R(xm) + ' ' + R(p.y2) + ' ' + R(x2) + ' ' + R(p.y2) + 'L' + R(x2) + ' ' + R(p.y2 + p.t) + 'C' + R(xm) + ' ' + R(p.y2 + p.t) + ' ' + R(xm) + ' ' + R(p.y1 + p.t) + ' ' + R(x1) + ' ' + R(p.y1 + p.t) + 'Z" style="--c:' + p.color + '"/>'; });
    G.cols.forEach((c, ci) => {
      const ys = c.map((n) => ({ n, y: n.y + n.h / 2 + 4 })).sort((a, b) => a.y - b.y);
      for (let k = 1; k < ys.length; k++) if (ys[k].y - ys[k - 1].y < 13) ys[k].y = ys[k - 1].y + 13;
      const over = ys.length ? ys[ys.length - 1].y - (h - 4) : 0; if (over > 0) ys.forEach((p) => { p.y -= over; });
      const ly = new Map(ys.map((p) => [p.n, p.y]));
      c.forEach((n) => { g += '<rect class="vz-node" x="' + VZ.r1(n.x) + '" y="' + VZ.r1(n.y) + '" width="' + G.nodeW + '" height="' + VZ.r1(n.h) + '" rx="2" style="--c:' + (n.color || 'var(--ink-2)') + '"/>'; const last = ci === G.C - 1; const lbl = n.name + (spec.nodeValues !== false ? ' ' + fmt(Math.max(n.in, n.out)) : ''); g += VZ.txt(last ? n.x - 5 : n.x + G.nodeW + 5, ly.get(n), lbl, { class: 'vz-nlbl', 'text-anchor': last ? 'end' : 'start' }); });
    });
    return { body: g, model: { kind: 'mark', n: G.links.length, xs: [], has: () => true, tip: (i) => { const p = G.links[i]; const share = p.a.out ? Math.round(p.l.value / p.a.out * 100) : 0; return VZ.tipHead(p.a.name + ' → ' + p.b.name, '占 ' + p.a.name + ' 流出 ' + share + '%') + VZ.tipRow(p.color, spec.unit || '', fmt(p.l.value), { kind: 'rect' }) + (p.l.note ? '<div class="vz-tr"><span class="vz-tk" style="--c:transparent"></span><span class="vz-tn">' + esc(p.l.note) + '</span></div>' : ''); }, at: (i) => { const p = G.links[i]; return [(p.a.x + G.nodeW + p.b.x) / 2, (p.y1 + p.y2 + p.t) / 2]; }, datum: (i) => G.links[i].l } };
  },
  table: (spec) => { const out = {}; (spec.links || []).forEach((l) => { out[l.from] = (out[l.from] || 0) + (VZ.num(l.value) || 0); }); return { cols: ['从', '到', spec.unit || '值', '占来源'], rows: (spec.links || []).map((l) => [String(l.from), String(l.to), VZ.fmt(VZ.num(l.value), spec.format), out[l.from] ? Math.round((VZ.num(l.value) || 0) / out[l.from] * 100) + '%' : '—']) }; }
};
/* ---------- timeline primitives：时间刻度、泳道布局、事件、区间、标记、播放头、brush ---------- */
VZ.lanes = function (lanes, top, gap) { let y = top || 0; return (lanes || []).map((l) => { const h = l.h || 16; const o = Object.assign({}, l, { h, y0: y, y1: y + h, cy: y + h / 2 }); y += h + (gap == null ? 2 : gap); return o; }); };
VZ.laneOf = (L, id) => L.find((l) => l.id === id);
VZ.types.timeline = {
  name: '时间线',
  isEmpty: (spec) => !(spec.events || []).length && !(spec.spans || []).length,
  top(spec) { let top = spec.top || (spec.now != null ? 8 : 4); const mkY = spec.markers && spec.markers.length ? top + 9 : null; if (mkY != null) top += 20; const phY = spec.spans && spec.spans.length ? top + 11 : null; if (phY != null) top += 16; return { top, mkY, phY }; },
  height(spec) { const top = VZ.types.timeline.top(spec).top; const L = VZ.lanes(spec.lanes || [], top, spec.laneGap); const yB = L.length ? L[L.length - 1].y1 : top + 40; return yB + (spec.axis === false ? 6 : 24); },
  frame(spec, w, h) {
    const { top, mkY, phY } = VZ.types.timeline.top(spec); const L = VZ.lanes(spec.lanes || [], top, spec.laneGap);
    const labW = spec.laneLabels === false || !L.some((l) => l.label) ? 0 : Math.min(120, Math.ceil(Math.max(...L.map((l) => VZ.tw(l.label || '', 11))) + 12));
    const ev = spec.events || []; const ts = ev.flatMap((e) => [e.t, e.t2 != null ? e.t2 : e.t]).concat((spec.spans || []).flatMap((s) => [s.t, s.t2]), (spec.markers || []).map((m) => m.t)).filter((t) => VZ.num(t) != null);
    const range = spec.range ? spec.range.slice() : ts.length ? [Math.min(...ts), Math.max(...ts)] : [0, 1]; if (!(range[1] > range[0])) range[1] = range[0] + 1;
    const F = { x0: labW + 2, x1: w - 6, yT: top, yB: L.length ? L[L.length - 1].y1 : top + 40, w, h, L, labW, range, mkY, phY, steps: spec.axisMode === 'steps' }; F.pw = F.x1 - F.x0; F.ph = F.yB - F.yT;
    // 横轴两种排布：'time'（像素 ∝ 时间）或 'steps'（每个事件等距，像素 ∝ 事件序号；跨度事件固定 1 步宽）。
    // F.pos(t) 把时刻映射到「轴坐标」（时间模式即 t，步数模式为小数序号），F.sx / F.px 再映射到像素；F.inv(px) 反推时刻（供 brush / 缩放 / 播放头）
    if (F.steps) {
      let a = Array.from(new Set(ev.map((e) => VZ.num(e.t)).filter((t) => t != null))).sort((p, q) => p - q); if (!a.length) a = [range[0]]; if (a.length === 1) a.push(a[0] + 1);
      F.stepTs = a; const n = a.length - 1;
      F.pos = (t) => { if (t <= a[0]) return -Math.min(0.5, (a[0] - t) / Math.max(1e-9, a[1] - a[0])); if (t >= a[n]) return n + Math.min(0.5, (t - a[n]) / Math.max(1e-9, a[n] - a[n - 1])); let lo = 0, hi = n; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (a[m] <= t) lo = m; else hi = m; } return lo + (t - a[lo]) / Math.max(1e-9, a[hi] - a[lo]); };
      F.unpos = (s) => { const i = clamp(Math.floor(s), 0, n - 1); return a[i] + (a[i + 1] - a[i]) * (s - i); };
    } else { F.pos = (t) => t; F.unpos = (s) => s; }
    F.dom = [F.pos(range[0]), F.pos(range[1])]; if (!(F.dom[1] > F.dom[0])) F.dom[1] = F.dom[0] + 1;
    F.sx = VZ.scale.linear(F.dom[0], F.dom[1], F.x0, F.x1); F.px = (t) => clamp(F.sx(F.pos(t)), F.x0, F.x1); F.inv = (px) => F.unpos(F.sx.inv(px)); F.stepPx = F.steps ? F.pw / Math.max(1, F.dom[1] - F.dom[0]) : 0;
    return F;
  },
  // 步数轴刻度：每 k 步一个（k ∈ 1/2/5/10/20/50/100，保证 ≥ 48px），每 5k 为主刻度
  stepTicks(F) { const [d0, d1] = F.dom; const ks = [1, 2, 5, 10, 20, 50, 100, 200, 500]; const k = ks.find((s) => s * F.stepPx >= 48) || ks[ks.length - 1]; const out = []; for (let s = Math.max(0, Math.ceil(d0 / k) * k); s <= d1; s += k) out.push({ x: F.sx(s), label: String(s), major: s % (k * 5) === 0 }); return out; },
  render(spec, w, h) {
    const F = VZ.types.timeline.frame(spec, w, h); const L = F.L; const ft = VZ.tfmt(spec, F);
    // 统一索引空间：items[i] = 逐个画出的事件 → 密度桶 → 关键时刻簇；data-i 指向它，tooltip / 键盘 / onSelect 都按它分发
    const items = []; let g = '';
    L.forEach((l, i) => { g += '<rect class="vz-lane' + (i % 2 ? ' alt' : '') + '" x="' + F.x0 + '" y="' + l.y0 + '" width="' + VZ.r1(F.pw) + '" height="' + l.h + '"/>'; if (l.label && F.labW) g += VZ.txt(4, l.cy + 4, l.label, { class: 'vz-cat vz-lane-lbl' }); });
    // 阶段带：label 放得下就画 label，否则退到 short（如只写阶段名）；tip 作为原生悬停说明（<title>）
    (spec.spans || []).forEach((s) => { const a = F.px(s.t), b = F.px(s.t2); const lb = [s.label, s.short].find((x) => x && b - a > VZ.tw(x, 11) + 8); g += '<rect class="vz-phase' + (s.inferred ? ' inferred' : '') + '" x="' + VZ.r1(a + 1) + '" y="' + F.yT + '" width="' + VZ.r1(Math.max(1, b - a - 2)) + '" height="' + VZ.r1(F.ph) + '"' + (s.color ? ' style="fill:' + s.color + '"' : '') + '>' + (s.tip ? '<title>' + esc(s.tip) + '</title>' : '') + '</rect>' + (lb ? VZ.txt((a + b) / 2, F.phY, lb, { class: 'vz-note', 'text-anchor': 'middle' }) : ''); });
    const ph = spec.playhead; const dense = (l) => !!l && l.mode === 'density';
    // range 收窄（如 minimap 视窗）时，窗外的事件 / 标记不画（区间事件只要与窗口相交就画，端点由 F.px 裁到边界）
    const inR = (a, b) => (b == null ? a : b) >= F.range[0] - 1e-9 && a <= F.range[1] + 1e-9;
    const ev = (spec.events || []).filter((e) => VZ.num(e.t) != null && inR(e.t, e.t2 != null ? e.t2 : null));
    const evTip = (e, l) => VZ.tipHead(ft(e.t) + (e.t2 != null ? ' – ' + ft(e.t2) : ''), (l.label || '') + (e.err ? ' · 失败' : '')) + (e.label ? VZ.tipRow(e.err ? VZ.sem.err : (e.color || l.color || 'var(--ink-2)'), e.sub || '', e.label, { kind: 'rect' }) : '') + (e.detail ? '<div class="vz-tr"><span class="vz-tk" style="--c:transparent"></span><span class="vz-tn">' + esc(e.detail) + '</span></div>' : '');
    // 普通泳道：逐事件绘制（tick / dot / ring / span）
    ev.forEach((e, k) => {
      const l = VZ.laneOf(L, e.lane); if (!l || dense(l) || VZ.num(e.t) == null) return; const x = F.px(e.t); const kind = e.kind || (e.t2 != null ? 'span' : 'tick'); const c = e.err ? VZ.sem.err : (e.color || l.color || 'var(--ink-2)');
      const fut = ph != null && e.t > ph; const sel = spec.selected != null && (spec.selected === k || (e.id != null && spec.selected === e.id));
      const cls = 'vz-ev' + (e.err ? ' vz-err' : '') + (fut ? ' vz-future' : '') + (sel ? ' vz-sel' : '') + (e.dim ? ' vz-dim' : '');
      const i = items.length; items.push({ tip: () => evTip(e, l), at: () => [x, l.cy], datum: () => e, t: e.t }); const dt = ' data-i="' + i + '" data-t="' + e.t + '"';
      if (kind === 'span') { const x2 = F.steps ? Math.min(F.x1, x + Math.max(4, F.stepPx)) : Math.max(x + 4, F.px(e.t2)); const hh = Math.max(4, l.h - 6); g += '<rect class="' + cls + ' vz-span"' + dt + ' x="' + VZ.r1(x) + '" y="' + VZ.r1(l.cy - hh / 2) + '" width="' + VZ.r1(x2 - x) + '" height="' + hh + '" rx="3" style="--c:' + c + '"/>' + (e.label && l.h >= 16 && x2 - x > VZ.tw(e.label, 10.5) + 8 ? VZ.txt(x + 4, l.cy + 3.5, e.label, { class: 'vz-span-lbl' }) : ''); }   // 泳道矮于 16px 时标签放不下，只留给 tooltip
      else if (kind === 'dot') g += '<circle class="' + cls + ' vz-pt"' + dt + ' cx="' + VZ.r1(x) + '" cy="' + VZ.r1(l.cy) + '" r="' + (e.r || 5) + '" style="--c:' + c + '"/>';
      else if (kind === 'ring') g += '<circle class="' + cls + ' vz-ring-ev"' + dt + ' cx="' + VZ.r1(x) + '" cy="' + VZ.r1(l.cy) + '" r="' + (e.r || 5) + '" style="--c:' + c + '"/>';
      else { const hh = e.err ? l.h : l.h - 4; g += '<rect class="' + cls + ' vz-tickev"' + dt + ' x="' + VZ.r1(x - (e.err ? 1.5 : 1)) + '" y="' + VZ.r1(l.cy - hh / 2) + '" width="' + (e.err ? 3 : 2) + '" height="' + hh + '" rx="1" style="--c:' + c + '"/>'; }
      if (kind !== 'span') g += '<rect class="vz-hit" data-i="' + i + '" x="' + VZ.r1(x - 6) + '" y="' + l.y0 + '" width="12" height="' + l.h + '"/>';
    });
    // 密度泳道（lane.mode === 'density'，评审 A3-V02）：事件按 spec.bucket px（默认 4）聚合，高度按对数，失败份额叠在顶部
    const bpx = Math.max(2, spec.bucket || 4);
    L.filter(dense).forEach((l) => {
      const map = new Map();
      ev.forEach((e) => { if (e.lane !== l.id || VZ.num(e.t) == null) return; const k = Math.floor((F.px(e.t) - F.x0) / bpx); const b = map.get(k) || { k, n: 0, err: 0, t0: e.t, t1: e.t, evs: [] }; b.n++; if (e.err) b.err++; b.t0 = Math.min(b.t0, e.t); b.t1 = Math.max(b.t1, e.t); b.evs.push(e); map.set(k, b); });
      const bs = Array.from(map.values()).sort((a, b) => a.k - b.k); const maxN = Math.max(1, ...bs.map((b) => b.n)); const c = l.color || 'var(--ink-4)';
      bs.forEach((b) => {
        const x = F.x0 + b.k * bpx; const hh = VZ.r1(Math.max(2, 2 + Math.log2(b.n + 1) / Math.log2(maxN + 1) * (l.h - 4))); const y = VZ.r1(l.y1 - 1 - hh); const eh = b.err ? VZ.r1(Math.max(2, Math.min(hh, hh * b.err / b.n))) : 0;
        const fut = ph != null && b.t0 > ph; const i = items.length; const names = b.evs.map((e) => e.label || '').filter(Boolean);
        // 事件带 cat（类别）时按类别给出次数，如「命令 12 · 读取 / 搜索 5」
        const cats = {}; b.evs.forEach((e) => { if (e.cat) cats[e.cat] = (cats[e.cat] || 0) + 1; }); const catTxt = Object.keys(cats).sort((p, q) => cats[q] - cats[p]).map((k) => k + ' ' + cats[k]).join(' · ');
        items.push({ tip: () => VZ.tipHead(ft(b.t0) + (b.t1 > b.t0 ? ' – ' + ft(b.t1) : ''), l.label || '') + VZ.tipRow(c, l.unit || '次', String(b.n), { kind: 'rect' }) + (b.err ? VZ.tipRow(VZ.sem.err, '失败', String(b.err), { kind: 'rect' }) : '') + (catTxt ? '<div class="vz-tr"><span class="vz-tk" style="--c:transparent"></span><span class="vz-tn">' + esc(catTxt) + '</span></div>' : '') + (names.length ? '<div class="vz-tr"><span class="vz-tk" style="--c:transparent"></span><span class="vz-tn">' + esc(names.slice(0, 4).join(' · ') + (names.length > 4 ? ' · +' + (names.length - 4) : '')) + '</span></div>' : ''), at: () => [x + bpx / 2, y], datum: () => ({ bucket: true, lane: l.id, t0: b.t0, t1: b.t1, n: b.n, err: b.err, events: b.evs }), t: b.t0 });
        g += '<rect class="vz-dens vz-ev' + (fut ? ' vz-future' : '') + '" data-i="' + i + '" data-t="' + b.t0 + '" x="' + VZ.r1(x) + '" y="' + y + '" width="' + Math.max(1, bpx - 1) + '" height="' + hh + '" style="--c:' + c + '"/>' + (eh ? '<rect class="vz-dens-err vz-ev' + (fut ? ' vz-future' : '') + '" data-t="' + b.t0 + '" x="' + VZ.r1(x) + '" y="' + y + '" width="' + Math.max(1, bpx - 1) + '" height="' + eh + '"/>' : '') + '<rect class="vz-hit" data-i="' + i + '" x="' + VZ.r1(x) + '" y="' + l.y0 + '" width="' + bpx + '" height="' + l.h + '"/>';
      });
    });
    // 关键时刻：编号徽章 + 贯穿全高的虚线；相距 < 20px 的徽章合并成「2–3」簇（评审 A3-V08）；异常用纠偏色实心 + 白字
    const mks = (spec.markers || []).map((m, k) => ({ m, k })).filter((p) => VZ.num(p.m.t) != null && inR(p.m.t)).map((p) => Object.assign(p, { x: Math.max(F.x0 + 9, Math.min(F.x1 - 9, F.px(p.m.t))) })).sort((a, b) => a.x - b.x); const groups = [];
    mks.forEach((p) => { const gp = groups[groups.length - 1]; if (gp && p.x - gp.x1 < 20) { gp.list.push(p); gp.x1 = p.x; } else groups.push({ list: [p], x0: p.x, x1: p.x }); });
    groups.forEach((gp) => {
      const x = (gp.x0 + gp.x1) / 2; const alert = gp.list.some((p) => p.m.alert); const num = (p) => String(p.m.n != null ? p.m.n : p.k + 1); const one = gp.list.length === 1; const label = one ? num(gp.list[0]) : num(gp.list[0]) + '–' + num(gp.list[gp.list.length - 1]); const pw = one ? 16 : Math.ceil(VZ.twm(label, 10) + 10);
      const i = items.length; const first = gp.list[0].m, last = gp.list[gp.list.length - 1].m;
      items.push({ tip: () => VZ.tipHead(one ? ft(first.t) : ft(first.t) + ' – ' + ft(last.t), '关键时刻 ' + label) + gp.list.map((p) => VZ.tipRow(p.m.alert ? VZ.sem.corr : 'var(--ink-1)', one ? (p.m.alert ? '异常' : '') : '#' + num(p) + (p.m.alert ? ' · 异常' : ''), p.m.label || '', { kind: 'rect' })).join(''), at: () => [x, F.mkY], datum: () => ({ marker: true, t: first.t, markers: gp.list.map((p) => p.m) }) });
      g += '<g class="vz-marker' + (alert ? ' alert' : '') + '" data-i="' + i + '" data-mk="' + gp.list.map((p) => p.k).join(',') + '"><line x1="' + VZ.r1(x) + '" x2="' + VZ.r1(x) + '" y1="' + (F.mkY + 8) + '" y2="' + F.yB + '"/><rect x="' + VZ.r1(x - pw / 2) + '" y="' + (F.mkY - 8) + '" width="' + pw + '" height="16" rx="8"/>' + VZ.txt(x, F.mkY + 3.5, label, { 'text-anchor': 'middle' }) + '</g>';
    });
    // 播放头：整组用 transform 定位，VZ.playhead() 逐帧只改 transform，不重绘；手柄在底部轴上，可拖动（吸附到 5px 内最近的事件）
    if (ph != null) { const x = VZ.r1(F.px(ph)); g += '<g class="vz-playhead" transform="translate(' + x + ' 0)"><rect class="vz-ph-hit" x="-6" y="' + (F.yT - 2) + '" width="12" height="' + VZ.r1(F.yB - F.yT + 22) + '"/><line x1="0" x2="0" y1="' + (F.yT - 2) + '" y2="' + (F.yB + 6) + '"/><path d="M0 ' + (F.yB + 10) + 'l-5 5 5 5 5-5z"/></g>'; }
    // 运行中会话：now 竖线 + 脉冲点（评审 A3-V21）
    if (spec.now != null) { const x = VZ.r1(F.px(spec.now)); const y = F.yT - 3; g += '<g class="vz-now"><line x1="' + x + '" x2="' + x + '" y1="' + y + '" y2="' + (F.yB + 2) + '"/><circle class="ring" cx="' + x + '" cy="' + y + '" r="3"/><circle class="core" cx="' + x + '" cy="' + y + '" r="3"/></g>'; }
    if (spec.axis !== false) { const ticks = F.steps ? VZ.types.timeline.stepTicks(F) : VZ.timeTicks(F.range[0], F.range[1], F.pw, { unit: spec.unit || 'ms', start: spec.start }).map((t) => ({ x: F.sx(t.t), label: t.label, major: t.major })); g += VZ.axisX(F, ticks, { dy: 16, tick: true, label: F.steps ? '步' : null }); }
    g += '<line class="vz-xline" x1="0" x2="0" y1="' + F.yT + '" y2="' + F.yB + '" hidden/>';
    const evTs = ev.map((e) => e.t).filter((t) => VZ.num(t) != null).sort((a, b) => a - b);
    return { body: g, model: { kind: 'mark', n: items.length, F, xs: [], has: () => true, tip: (i) => items[i].tip(), at: (i) => items[i].at(), datum: (i) => items[i].datum(), brushRange: (a, c) => [F.inv(a), F.inv(c)], ft, items, evTs } };
  },
  table: (spec) => { const L = VZ.lanes(spec.lanes || []); const ft = VZ.tfmt(spec, VZ.types.timeline.frame(spec, 600, 100)); return { cols: ['时间', '泳道', '事件', '结果'], rows: (spec.events || []).map((e) => [ft(e.t) + (e.t2 != null ? ' – ' + ft(e.t2) : ''), (VZ.laneOf(L, e.lane) || {}).label || e.lane, e.label || '', e.err ? '失败' + (e.detail ? ' · ' + e.detail : '') : (e.detail || '')]) }; }
};
/* ---------- minimap：总览条（事件密度 + 失败刻 + 你的消息 + 视窗刷子），overview + detail 的上半部分 ----------
 * spec: { range: [t0, t1], events: [{ t, err, user }], density: [n]（已分桶时可直接给）, window: [a, b]（当前视窗；null = 全程）, bins, unit, start, axis,
 *        onView(range | null, { px, done, full }) }   拖视窗平移、拖两端手柄缩放、点空白处把视窗移过去、双击复位；键盘 ← → 平移 10%，↑ ↓ 缩放，Home 全程 */
// 时刻格式：unit 'min' 时 start + t 分钟 → HH:MM（非整分钟带秒 HH:MM:SS，密度桶能分辨）；'ms' 时两天内只显示 HH:MM，否则 M/D HH:MM
VZ.tfmt = function (spec, F) { const unit = spec.unit || 'ms'; const T = VZ.time; return (t) => unit === 'min' ? (() => { const abs = (spec.start || 0) + t; const sec = Math.round((abs % 1) * 60); const base = T.pad(Math.floor(abs / 60) % 24) + ':' + T.pad(Math.floor(abs % 60)); return sec ? base + ':' + T.pad(sec) : base; })() : (F.range[1] - F.range[0] < T.D * 2 ? T.hm(t) : T.md(t) + ' ' + T.hm(t)); };
VZ.types.minimap = {
  name: '总览条',
  isEmpty: (spec) => !(spec.events || []).length && !(spec.density || []).some((v) => VZ.num(v) > 0),
  height: (spec) => spec.axis ? 44 : 28,
  frame(spec, w, h) {
    const ts = (spec.events || []).map((e) => e.t).filter((t) => VZ.num(t) != null);
    const range = spec.range ? spec.range.slice() : ts.length ? [Math.min(...ts), Math.max(...ts)] : [0, 1]; if (!(range[1] > range[0])) range[1] = range[0] + 1;
    const F = { x0: 4, x1: w - 4, yT: 3, yB: h - (spec.axis ? 18 : 3), w, h, range }; F.pw = F.x1 - F.x0; F.ph = F.yB - F.yT; F.sx = VZ.scale.linear(range[0], range[1], F.x0, F.x1); F.px = (t) => clamp(F.sx(t), F.x0, F.x1); return F;
  },
  bins(spec, F) {
    const nb = spec.bins || Math.max(20, Math.min(120, Math.floor(F.pw / 3))); const [t0, t1] = F.range; const span = t1 - t0 || 1;
    const bins = Array.from({ length: nb }, (_, i) => ({ i, t0: t0 + span * i / nb, t1: t0 + span * (i + 1) / nb, n: 0, err: 0, user: 0 }));
    const D = spec.density || []; D.forEach((v, i) => { bins[Math.min(nb - 1, Math.floor(i / D.length * nb))].n += VZ.num(v) || 0; });
    (spec.events || []).forEach((e) => { if (VZ.num(e.t) == null) return; const b = bins[clamp(Math.floor((e.t - t0) / span * nb), 0, nb - 1)]; if (e.user) b.user++; else b.n++; if (e.err) b.err++; });
    return bins;
  },
  render(spec, w, h) {
    const F = VZ.types.minimap.frame(spec, w, h); const B = VZ.types.minimap.bins(spec, F); const maxN = Math.max(1, ...B.map((b) => b.n)); const bw = F.pw / B.length;
    const yOf = (n) => F.yB - 1 - (n / maxN) * (F.ph - 7);
    let area = '', line = ''; B.forEach((b, i) => { const x = VZ.r1(F.x0 + i * bw), x2 = VZ.r1(F.x0 + (i + 1) * bw), y = VZ.r1(yOf(b.n)); area += (i ? 'L' : 'M') + x + ' ' + y + 'L' + x2 + ' ' + y; line += (i ? 'L' : 'M') + x + ' ' + y + 'L' + x2 + ' ' + y; });
    let g = '<rect class="vz-mm-bg" x="' + F.x0 + '" y="' + F.yT + '" width="' + VZ.r1(F.pw) + '" height="' + VZ.r1(F.ph) + '" rx="3"/>';
    g += '<path class="vz-mm-area" d="' + area + 'L' + VZ.r1(F.x1) + ' ' + VZ.r1(F.yB - 1) + 'L' + F.x0 + ' ' + VZ.r1(F.yB - 1) + 'Z"/><path class="vz-mm-line" d="' + line + '"/>';
    B.forEach((b, i) => { const x = F.x0 + i * bw; if (b.err) g += '<rect class="vz-mm-err" x="' + VZ.r1(x) + '" y="' + VZ.r1(Math.min(yOf(b.n), F.yB - 5) - 2) + '" width="' + VZ.r1(Math.max(1.5, bw - 0.5)) + '" height="2"/>'; if (b.user) g += '<circle class="vz-mm-user" cx="' + VZ.r1(x + bw / 2) + '" cy="' + VZ.r1(F.yB - 2.5) + '" r="1.5"/>'; });
    const win = spec.window && spec.window[1] > spec.window[0] ? spec.window : F.range; const ax = VZ.r1(F.px(win[0])), bx = VZ.r1(F.px(win[1]));
    g += '<g class="vz-mm-win"><rect class="vz-mm-view" x="' + ax + '" y="' + F.yT + '" width="' + VZ.r1(Math.max(2, bx - ax)) + '" height="' + VZ.r1(F.ph) + '" rx="3"/><rect class="vz-mm-hdl" data-h="l" x="' + VZ.r1(ax - 2) + '" y="' + F.yT + '" width="4" height="' + VZ.r1(F.ph) + '" rx="2"/><rect class="vz-mm-hdl" data-h="r" x="' + VZ.r1(bx - 2) + '" y="' + F.yT + '" width="4" height="' + VZ.r1(F.ph) + '" rx="2"/></g>';
    if (spec.axis) { const ticks = VZ.timeTicks(F.range[0], F.range[1], F.pw, { unit: spec.unit || 'ms', start: spec.start }); g += VZ.axisX(F, ticks.map((t) => ({ x: F.sx(t.t), label: t.label, major: t.major })), { dy: 13, tick: true }); }
    return { body: g, model: { kind: 'view', n: 0, F, xs: [], view: [ax, bx], minW: 8, has: () => false, ft: VZ.tfmt(spec, F), bins: B } };
  },
  table(spec) { const F = VZ.types.minimap.frame(spec, 600, 28); const ft = VZ.tfmt(spec, F); return { cols: ['时间段', '事件', '失败', '你的消息'], rows: VZ.types.minimap.bins(spec, F).map((b) => [ft(b.t0) + ' – ' + ft(b.t1), String(b.n), String(b.err), String(b.user)]) }; }
};
