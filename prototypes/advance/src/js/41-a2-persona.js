/* ============ A2 persona ============
 * 结构：hero（四字母 + 名称 + 「实验性」+ 演变：月份码 + 四轴折线）与协作指纹（Orbit 表盘：外框是 16 型（格雷码顺序）/
 * 轨道是每个会话按自己的四个维度归到的类型分布（每个 Agent 一层平滑曲线）+ 16 个类型热区，点击展开该型的会话点 / Agent 标志徽章 /
 * 内盘是协作人格的花（16 型各一朵，旋转对称，整朵转到一片主瓣指向你的类型））→ 四个维度（VZ 双向条：以 50 为界取一极、对照刻度、
 * 数值跟随胜出极、每轴证据微型图）+ 优势与盲点 + 契合度（中性条、透明度随 n、95% 区间、Agent 色只在圆点）。
 * 人格口径统一走 personaScope（BUG-06）；1 个会话即出完整 4 字母，少于 30 个只在徽标旁温和提示；没有会话时列出放宽哪个筛选能补到多少（A2-V08），全部来源停用时引导到设置（BUG-50）。 */
const PERIODS = { sep: [90, 119, '9 月'], '90': [30, 119, '近 90 天'], all: [0, 119, '全部'], jun: [0, 27, '6 月'], jul: [28, 58, '7 月'], aug: [59, 89, '8 月'] };
const POP = { D: 52, I: 54, M: 47, V: 58 };
if (S.persona.fpType === undefined) S.persona.fpType = null;
// strength = max(val, 100 − val): rounded once from the unrounded bar value, so it matches axisView().strong (hero, method)
const peNum = (v) => String(Math.round(+(Math.abs(v) * 50 + 50).toFixed(6)));
function peAxisRows(p, prev) {
  return [0, 1, 2, 3].map((i) => {
    const a = axisView(p, i); const k = a.ax.k; const sgn = k === 'I' ? 1 : -1;
    const gv = S.persona.vs === 'pop' ? POP[k] : (prev && prev.ok ? prev.v[k] : null);
    return { name: '', left: a.ax.L + ' ' + a.ax.Ln, right: a.ax.Rn + ' ' + a.ax.R, value: (50 - a.val) * sgn * -1 / 50, ref: gv == null ? null : (50 - gv) * sgn * -1 / 50, hint: a.ax.q + ' · 强度 ' + a.strong, id: k };
  });
}
// 维度证据的计数单位（live 的 axes[].unit）：写成人能读懂的「112 轮对话」，不写 n=112（F15）
const peUnits = (n, unit) => fmt(n) + ' ' + (({ turn: '轮对话', session: '个会话', session_opening: '个会话开场', active_day: '个活跃日' })[unit] || '个样本');
// 每轴证据微型图：D 每会话消息数分布、P/I 项目按结构度排序的时长、M 每日会话数分布、V 项目按求证度排序的时长
function peEvidence(L, st, p, i) {
  if (LV.live) {   // live: the server's per-axis evidence (unit counts the client cannot see until G1)
    const ax = (p.axes || [])[i]; const e = ax && ax.evidence;
    return e ? { txt: e.txt, vals: e.vals && e.vals.length ? e.vals : [0], lbl: e.lbl + (e.projects && e.projects.length ? ' · ' + e.projects.join(' / ') : '') } : { txt: ax && ax.n_units != null ? peUnits(ax.n_units, ax.unit) : '—', vals: [0], lbl: '暂无证据' };
  }
  const hist = (vals, n, max) => { const out = new Array(n).fill(0); vals.forEach((v) => { out[Math.min(n - 1, Math.floor(v / max * n))]++; }); return out; };
  const byProj = (key) => PJ.slice().sort((a, b) => a[key] - b[key]).map((pj) => sum(L.filter((s) => s.p === pj.id), (s) => s.dur) / 60);
  if (i === 0) return { txt: '每会话 ' + f1(st.per) + ' 条消息 · 每轮 ' + f1(st.auto) + ' 步', vals: hist(L.map((s) => s.msgs), 10, 20), lbl: '消息数 0 → 20+ 的会话数' };
  if (i === 1) return { txt: '规划型项目占 ' + Math.round(sum(L.filter((s) => PJI[s.p].I < 50), (s) => s.dur) / (st.hours * 60 || 1) * 100) + '% 时长', vals: byProj('I'), lbl: '项目时长 · 规划型 → 即兴型' };
  if (i === 2) { const by = {}; L.forEach((s) => { by[s.d] = (by[s.d] || 0) + 1; }); return { txt: '日均 ' + f1(p.avgS) + ' 会话 · 同日 ' + f1(p.avgA) + ' Agent', vals: hist(Object.values(by), 8, 8), lbl: '每日会话数 1 → 8+ 的天数' }; }
  return { txt: pctKnown(st.verify, st.verKnown) + ' 要求验证 · 完成 ' + pctKnown(st.ok, st.okKnown), vals: byProj('V'), lbl: '项目时长 · 信任型 → 求证型' };
}
// 样本不足时：放宽哪个筛选能补到多少（只看人格口径里的三个条件：Agent、项目、周期）
function peRelax(w) {
  const out = []; const n = (o) => ALL.filter((s) => s.d >= o.w[0] && s.d <= o.w[1] && !s.live && sourceEnabled(s) && (o.allAg || S.agents.has(s.a)) && (o.noProj || !S.project || s.p === S.project)).length;
  if (S.project) out.push({ k: 'project', t: '项目 · ' + PJI[S.project].name, n: n({ w, noProj: true }) });
  if (S.agents.size < AG.length) out.push({ k: 'agents', t: 'Agent · ' + AG.filter((a) => S.agents.has(a.id)).map((a) => a.short).join(' / '), n: n({ w, allAg: true }) });
  if (S.persona.period !== 'all') out.push({ k: 'period', t: '周期 · ' + PERIODS[S.persona.period][2], n: n({ w: [0, LASTDAY] }) });
  return out;
}
// the persona page keeps its own period (近 90 天 / a month / 全部), not the global time range: say so on the page (E)
function peScopeTag(per) {
  const same = (S.persona.period === '90' && S.range === 90) || (S.persona.period === 'all' && S.range === 0);
  return '<span class="cap pe-scope" data-pe-scope title="协作人格按本页的统计周期计算；概览人格卡跟随全局范围">统计周期 · ' + per[2] + (same ? '' : '（本页单独设置，全局为' + rangeLabel() + '）') + '</span>';
}
// 表盘几何（400 视框，圆心 200）：外框 196（刻度贴着它向内）、轨道基线 R0、曲线最高起伏 RH、花的最大半径 RR、
// 花苞比例 BUD（Genesis 01–02 花合拢旋转，03 开花）、首次启动 Orbit 内弧收拢成的主瓣中线长度 NL、Agent 徽章的轨道半径 PR 与徽章
// 半径 PB（PR − PB − 描边 > 曲线最高处 R0 + 1 + RH，PR + PB + 描边 < 型分界刻度的内端 189.5）。16 个类型码贴着刻度内侧
// （fpCodeLbls），左右两侧的码横向更宽、向内伸得更深，RH 留出它们的位置。Genesis（56-onboarding.js）的粒子落点、环带扫描
// 与开花共用这一组常量。
const FPG = { R0: 104, RH: 54, HM: 4, RR: 80, BUD: 0.34, NL: 56, PR: 172, PB: 9 };
let FP_UID = 0;
// 表盘按 16 型排布：格雷码顺序（相邻两型只差一个字母，与宣传片一致），每型 22.5°，DIMV 在 12 点右侧。这样排下来，右半圈全是
// 委托 D、左半圈全是掌舵 S，上半圈全是即兴 I、下半圈全是规划 P；多线 / 专注、求证 / 信任在象限里交替。外框不写方位字，
// 16 个扇区各标自己的类型码
const FP_TYPES = Array.from({ length: 16 }, (_, i) => { const g = i ^ (i >> 1); return ['DS', 'IP', 'MF', 'VT'].map((q, k) => q[(g >> (3 - k)) & 1]).join(''); });
// 16 个类型码（SF Pro Rounded，正立）：每个码在本型扇区的中线上，文字框外缘贴着刻度内端（离 192.5 留 2），所以上下的码
// 离圆心远、左右的码（横向更宽）离圆心近，像表盘内切的数字。大表盘 9.5、小表盘（Lite / Genesis，300 px 显示）10.8——
// 按 fp2SVG 的 size 显示时都是 8 px 以上，16 个都标；表盘被 CSS 缩得更小、码不到 8 px 时（窄窗口里的 Lite），
// 42-a2-persona.css 只留你的类型码。文字框的半宽 / 半高按 SF Pro Rounded 粗体大写的平均字宽估算，徽章避让也用这个框
const FP_CW = { D: 0.7, S: 0.62, I: 0.3, P: 0.64, M: 0.84, F: 0.57, V: 0.66, T: 0.6 };
function fpCodeLbls(sm) {
  const fs = sm ? 10.8 : 9.5;
  return FP_TYPES.map((c, t) => {
    const deg = (t + 0.5) * 22.5, a = deg * Math.PI / 180, w = fs * (c.split('').reduce((x, ch) => x + FP_CW[ch], 0) + 0.12) / 2 + 0.5, h = fs * 0.37 + 0.5;
    const r = 190.5 - (w * Math.abs(Math.sin(a)) + h * Math.abs(Math.cos(a)));
    return { t, code: c, deg, fs, w, h, p: fpPt(r, deg) };
  });
}
const fpTypeIdx = (code) => FP_TYPES.indexOf(code);
const fpTypeDeg = (code) => (Math.max(0, fpTypeIdx(code)) + 0.5) * 22.5;
// 单个会话的四个维度（与 persona() 同一多信号口径，只看这一个会话和它所在的那一天）：
//   示例数据：用会话自带的 lean（四维倾向，只供表盘归类）；其它会话：D / I / V 由该会话自己的信号算，M 由当天的会话数、
//   Agent 数与是否多线算（psAxis，与 persona() 同一份锚点与权重）；某维度没有任何信号时取 50
function fpSessV(s, dd) {
  let D, I, M, V;
  if (s.lean) ({ D, I, M, V } = s.lean);   // 示例数据：会话自带的四维倾向（05-data.js），只供这里归类；live 会话没有这个字段
  else {
    const o = psSuff([s]); o.days = s.d != null ? { [s.d]: [dd.n, dd.a, dd.multi ? 1 : 0] } : {};
    const val = (k) => { const a = psAxis(o, AXES.find((x) => x.k === k)); return a.value == null ? 50 : a.value; };
    D = val('D'); I = val('I'); M = val('M'); V = val('V');
  }
  const v = { D: clamp(D, 4, 96), I: clamp(I, 4, 96), M: clamp(M, 4, 96), V: clamp(V, 4, 96) };
  // 软归属：每个轴偏向高值一极的概率（50 → 0.5，96 → 0.91），四轴相乘得到该会话在 16 型上的分布；轨道用它画（相邻类型
  // 也分到一些，曲线连续），点击、计数与徽章用最接近的那一型（argmax）
  const q = (x) => clamp(0.5 + (x - 50) / 50 * 0.45, 0.05, 0.95), qv = [q(v.D), q(v.I), q(v.M), q(v.V)];
  const w = FP_TYPES.map((c) => ['D', 'I', 'M', 'V'].reduce((m, k, i) => m * (c[i] === k ? qv[i] : 1 - qv[i]), 1));
  return { v, w, code: (v.D >= 50 ? 'D' : 'S') + (v.I >= 50 ? 'I' : 'P') + (v.M >= 50 ? 'M' : 'F') + (v.V >= 50 ? 'V' : 'T'), strong: (Math.abs(v.D - 50) + Math.abs(v.I - 50) + Math.abs(v.M - 50) + Math.abs(v.V - 50)) / 4 };
}
// 把每个会话归到它最接近的类型（byT[16]），并给它一个连续的方位 a：在本型扇区里，朝软归属更多的那一侧相邻类型偏过去
function fpClassify(L) {
  const days = {}; L.forEach((s) => { (days[s.d] = days[s.d] || []).push(s); });
  const ctx = {}; Object.keys(days).forEach((d) => {
    const xs = days[d], ag = new Set(xs.map((s) => s.a)).size;
    const sp = xs.filter((s) => s.t0 != null && s.t1 != null).map((s) => [s.t0, s.t1]).sort((x, y) => x[0] - y[0]);
    let ov = false, end = null; for (const [a, b] of sp) { if (end != null && a < end) ov = true; end = end == null ? b : Math.max(end, b); }
    ctx[d] = { n: xs.length, a: ag, multi: ag >= 2 || ov };
  });
  const by = {}, byT = Array.from({ length: 16 }, () => []);
  L.forEach((s) => {
    const c = fpSessV(s, ctx[s.d]); c.t = fpTypeIdx(c.code);
    const wl = c.w[(c.t + 15) % 16], wr = c.w[(c.t + 1) % 16];
    c.a = (c.t + 0.5 + 0.5 * (wr - wl) / (wl + c.w[c.t] + wr)) * 22.5;
    by[s.id] = c; byT[c.t].push(s);
  });
  return { by, byT };
}
// 轨道：每个 Agent 一条自己的曲线，不再叠加。该 Agent 的每个会话在它的方位上放一个高斯核（σ = 8°），得到这个 Agent 的密度；
// 所有 Agent 共用一个高度尺度（全部 Agent、全部方位里的最高密度对应 RH，经 0.9 次方略压缩），所以各条曲线的高低可以直接比。
// 每条曲线都从同一条基线（inner，恒为 0）向外长出，曲线之间可以重叠：半透明的低饱和填充 + 一条清楚的细边，会话多的 Agent
// 先画、少的后画，小的不会被盖住。H 是各方位上最高的那条曲线（外包络），给 Genesis 等只关心整体高度的地方用。
// 每 2.5° 采样，画成闭合的 Catmull-Rom 曲线。
// 徽章：每个有会话的 Agent 一枚 Agent 标志，表示这个 Agent 的总体平均方向——它在当前筛选里全部会话方位（与色带密度同一组
// 连续方位）的圆周平均，不吸附到扇区中线，也不找峰：曲线是逐个会话的分布，平均方向一般不在峰上。所有徽章停在同一条轨道
// FPG.PR 上（曲线最高处之外、外框刻度之内，像同一轨道上的行星），不会压在曲线峰顶；与别的徽章或 16 个类型码相碰时，沿轨道
// 以最小的角度错开（真实平均方向留在 mean / data-mean，提示里报它所在的类型）。
const FP_N = 144;
const fpPt = (r, deg) => { const a = deg * Math.PI / 180; return [200 + r * Math.sin(a), 200 - r * Math.cos(a)]; };
function fpOrbit(L, cls, sm) {
  const N = FP_N, idx = AG.map(() => []);
  L.forEach((s) => { const i = AG.findIndex((a) => a.id === s.a); if (i >= 0) idx[i].push(cls.by[s.id].a); });
  const kde = (sig) => idx.map((as) => { const d = new Float64Array(N + 1); for (let k = 0; k <= N; k++) { const th = k / N * 360; let v = 0; as.forEach((a) => { const x = ((th - a) % 360 + 540) % 360 - 180; v += Math.exp(-x * x / (2 * sig * sig)); }); d[k] = v; } return d; });
  const dens = kde(8), mx = Math.max(1e-9, ...dens.map((d) => Math.max(...d)));
  const layers = AG.map((ag, i) => ({ a: ag, inner: new Array(N + 1).fill(0), outer: Array.from(dens[i], (v) => FPG.RH * Math.pow(v / mx, 0.9)), n: idx[i].length }));
  const H = Array.from({ length: N + 1 }, (_, k) => Math.max(0, ...layers.map((ly) => ly.outer[k])));
  // 徽章的真实方向：该 Agent 全部会话方位的圆周平均（单位向量求和再取角）；提示里的类型是这个方向落在的扇区
  const planets = AG.map((ag, i) => {
    const as = idx[i], n = as.length; if (!n) return null;
    let sx = 0, sy = 0; as.forEach((a) => { sx += Math.sin(a * Math.PI / 180); sy += Math.cos(a * Math.PI / 180); });
    const mean = +(((Math.atan2(sx, sy) * 180 / Math.PI) % 360 + 360) % 360).toFixed(1), t = Math.floor(mean / 22.5) % 16;
    return { a: ag, n, mean, t, code: FP_TYPES[t], deg: mean, r: FPG.PR };
  }).filter(Boolean);
  // 由多到少放置：先放在真实平均方向上；与已放的徽章或 16 个类型码（按文字框算）相碰时，沿轨道两侧各试 0.5°、1°、1.5°…
  // 取最小的错开
  const BO = FPG.PB + 0.6, xy = (deg) => fpPt(FPG.PR, deg), placed = [];
  const lbls = fpCodeLbls(sm);
  const free = (deg) => { const p0 = xy(deg); return placed.every((y) => { const q = xy(y.deg); return Math.hypot(p0[0] - q[0], p0[1] - q[1]) >= BO * 2 + 2; }) &&
    lbls.every((b) => Math.hypot(Math.max(0, Math.abs(p0[0] - b.p[0]) - b.w), Math.max(0, Math.abs(p0[1] - b.p[1]) - b.h)) >= BO + 3); };
  planets.slice().sort((a, b) => b.n - a.n).forEach((x) => {
    let d = 0; for (let k = 0; k <= 360; k++) { const o = k * 0.5; if (free(x.mean + o)) { d = o; break; } if (k && free(x.mean - o)) { d = -o; break; } }
    x.deg = +((((x.mean + d) % 360) + 360) % 360).toFixed(1); placed.push(x);
  });
  return { layers, planets, H };
}
// 闭合的 Catmull-Rom 曲线（样本首尾相同），rev 时反向；head 为 'M' 或 'L'
function fpCR(edge, rev, head) {
  const N = edge.length - 1, P = []; for (let s = 0; s < N; s++) P.push(fpPt(FPG.R0 + 1 + edge[s], s / N * 360));
  if (rev) P.reverse();
  const n = P.length, g = (i) => P[(i + n) % n], f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
  let d = (head || 'M') + f(P[0]);
  for (let i = 0; i < n; i++) {
    const p0 = g(i - 1), p1 = g(i), p2 = g(i + 1), p3 = g(i + 2);
    d += 'C' + f([p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6]) + ' ' + f([p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6]) + ' ' + f(p2);
  }
  return d;
}
// 一层的外缘曲线（等高线）
const fpEdgeD = (edge) => fpCR(edge, false, 'M') + 'Z';
// 一层的填充：外缘顺时针，内缘（基线）逆时针收口
const fpLayerD = (ly) => fpCR(ly.outer, false, 'M') + fpCR(ly.inner, true, 'L') + 'Z';
// 暖纸底上的轨道用低饱和的 Agent 色：识别色只占三到五成，其余是主题里的暖灰（填充混 --fp-base、细线混 --h4），亮暗两套主题都
// 沉稳。曲线各自独立、可以重叠，所以填充半透明（--fp-bo），细边比填充更饱和一些，重叠处仍分得清是哪条。底色与不透明度
// --fp-base / --fp-bo 在 42-a2-persona.css
const fpMute = (c, k) => 'color-mix(in oklab, ' + c + ' ' + (k || 46) + '%, var(--h3))';
const fpFill = (c) => 'color-mix(in oklab, ' + c + ' 42%, var(--fp-base))';
const fpLine = (c) => 'color-mix(in oklab, ' + c + ' 52%, var(--h4))';
// 协作指纹 · Orbit 表盘：表盘没有底色，直接落在页面纸面上。外框是一圈细线与 128 道细刻度（16 型的分界稍长），刻度内侧
// 16 个扇区各标类型码（你的类型加粗、墨色，其余浅灰），你的类型另有 --orbit 基准三角；轨道是每个会话按自己四个维度落到的
// 方位的密度（每个 Agent 一条独立的曲线：半透明填充 + 一条细边，彼此可重叠），上有 16 个透明的类型热区（选中展开该型会话的
// Agent 标志）与 Agent 标志徽章；内盘是协作人格的花，整朵花旋转（--hd），一片瓣指向你的类型。环带的 .fp-sweep 遮罩与
// 徽章的 --pa 留给入场动画。
function fp2SVG(L, p, size, opt) {
  opt = opt || {}; const C = 200; const R0 = FPG.R0, RH = FPG.RH, RR = FPG.RR; const sm = size < 340; const uid = 'fpm' + (++FP_UID);
  const cls = fpClassify(L), byT = cls.byT, orb = fpOrbit(L, cls, sm);
  const code = bloomCode(p), mine = fpTypeIdx(code), hd = mine >= 0 ? (mine + 0.5) * 22.5 : 0;
  CUR.fp = { byT, cls, n: L.length, pl: orb.planets, H: orb.H };
  const f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
  const sector = (r0, r1, d0, d1) => { const p0 = fpPt(r0, d0), p1 = fpPt(r1, d0), p2 = fpPt(r1, d1), p3 = fpPt(r0, d1); return 'M' + f(p0) + 'L' + f(p1) + 'A' + r1 + ' ' + r1 + ' 0 0 1 ' + f(p2) + 'L' + f(p3) + 'A' + r0 + ' ' + r0 + ' 0 0 0 ' + f(p0) + 'Z'; };
  const sel = opt.interactive ? S.persona.fpType : null, RO = R0 + RH + 6;   // 只有可交互的表盘（画像页）展开选中的类型；Lite / Genesis 的表盘不带选中态
  // 轨道：每个 Agent 一条从基线长出的独立曲线（低饱和半透明填充）+ 一条细边；会话多的先画，少的后画，彼此可以重叠。
  // 基线以内与曲线之外什么都不画：没有底盘、灰色衬带、渐变与光晕，花直接落在纸面上
  const lys = orb.layers.filter((ly) => ly.n).sort((x, y) => y.n - x.n);
  const orbG = '<g class="fp-orbw"><g class="fp-orb" id="' + uid + 'o" mask="url(#' + uid + ')"><g class="fp-body">' +
    lys.map((ly) => '<path class="fpo" data-a="' + ly.a.id + '" d="' + fpLayerD(ly) + '" fill="' + fpFill(ly.a.c) + '"/>').join('') + '</g>' +
    lys.map((ly) => '<path class="fpc" data-a="' + ly.a.id + '" d="' + fpEdgeD(ly.outer) + '" fill="none" stroke="' + fpLine(ly.a.c) + '" stroke-width=".9" stroke-linejoin="round"/>').join('') + '</g></g>';
  // 选中一型：整条轨道变淡，只把该型扇区里的那一段按原样再画一遍
  const focus = sel != null ? '<g class="fp-focus" clip-path="url(#' + uid + 'c)"><use href="#' + uid + 'o"/></g>' : '';
  // 16 个透明的类型热区：悬停提示该型按 Agent 的会话数，点击展开会话
  let ring = '';
  byT.forEach((xs, t) => {
    const on = sel == null || sel === t;
    ring += '<g class="fps' + (sel === t ? ' sel' : '') + (!on ? ' dim' : '') + '" data-t="' + t + '"' + (opt.interactive ? ' data-tf="fpt|' + t + '" data-act="fpType" tabindex="0" role="button" aria-label="' + FP_TYPES[t] + ' ' + TYPES[FP_TYPES[t]][0] + ' · ' + xs.length + ' 个会话"' : '') + '><path d="' + sector(R0, RO, t * 22.5, (t + 1) * 22.5) + '" fill="transparent"/></g>';
  });
  // 选中的类型：该型的每个会话画成它那个 Agent 的小标志，按 Agent、再按方位排好，从内向外一排排铺满扇区；可悬停、点开
  let dots = '';
  if (sel != null && byT[sel]) {
    const ord = (s) => AG.findIndex((a) => a.id === s.a);
    const xs = byT[sel].slice().sort((x, y) => ord(x) - ord(y) || cls.by[x.id].a - cls.by[y.id].a), GAP = 8.4;
    let i = 0, r = R0 + 8;
    while (i < xs.length) {
      const span = 22.5 - 3, cap = Math.max(1, Math.floor(r * span * Math.PI / 180 / GAP)), row = xs.slice(i, i + cap);
      row.forEach((s, j) => {
        const q = fpPt(r, sel * 22.5 + 1.5 + span * (j + 0.5) / row.length), c = fpLine(agent(s.a).c);
        dots += '<g class="fpd" data-a="' + s.a + '"' + (opt.interactive ? ' data-tf="sess|' + s.id + '" data-act="openSession" data-id="' + s.id + '" style="cursor:pointer"' : '') + '><circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="3.9" fill="var(--bg)"/>' + agGlyph(s.a, q[0], q[1], 6.6, c) + '</g>';
      });
      i += row.length; r += GAP;
    }
  }
  // 徽章：画在 (200, 200 − PR)，外层按 --pa（错开后的画出方位；真实平均方向在 data-mean）旋转到位，标志本身反向转回保持
  // 正立；纸色圆底 + 低饱和细环 + 标志
  const planets = '<g class="fp-pls">' + orb.planets.map((x) => '<g class="fp-pl" data-a="' + x.a.id + '" data-pa="' + x.deg + '" data-mean="' + x.mean + '" style="--pa:' + x.deg + 'deg"' + (opt.interactive ? ' data-tf="fpp|' + x.a.id + '"' : '') + '><g class="fp-pd">' + agLogo(x.a.id, 200, +(C - x.r).toFixed(1), FPG.PB, fpLine(x.a.c), 'var(--bg)') + '</g></g>').join('') + '</g>';
  // 外框：一圈细线 + 贴着它向内的 128 道细刻度（每型 8 道，型与型的分界稍长，四个方位最长），刻度内侧 16 个类型码（正立，
  // 你的类型 .me 加粗墨色）；外侧基准三角（--orbit）指向你的类型
  const tk = ['', '', '']; for (let i = 0; i < 128; i++) { const w = i % 32 === 0 ? 2 : i % 8 === 0 ? 1 : 0; tk[w] += 'M' + f(fpPt(196, i * 2.8125)) + 'L' + f(fpPt([192.5, 189.5, 185][w], i * 2.8125)); }
  const lbl = fpCodeLbls(sm).map((x) => '<text class="tcode fp-code' + (x.t === mine ? ' me' : '') + '" data-t="' + x.t + '" x="' + x.p[0].toFixed(1) + '" y="' + x.p[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="' + x.fs + '" fill="' + (x.t === mine ? 'var(--ink-1)' : 'var(--ink-3)') + '">' + x.code + '</text>').join('');
  // 内盘：协作人格的花。.fp-flower（Genesis 淡入）› .fp-bloom（--hd 旋转，Genesis 逐帧写）› .fp-bd（入场晃动、悬停轻颤）›
  // .fp-back 浅灰小瓣 / .fp-front 墨色主瓣（Genesis 从花苞开到全开）；花心不随旋转。有未定的轴（live 的「?」）时花是灰色
  const g = bloom(p, C, RR), un = !p.ok || (p.code || '').includes('?'), ink = un ? 'var(--ink-3)' : 'var(--ink-1)';
  const lay = bloomParts(g, C, C, { ink, gray: 'var(--petal2)', lead: un ? 'var(--ink-4)' : 'var(--orbit)', bg: 'var(--bg)', hw: 1.4 });
  const flower = '<g class="fp-flower" data-code="' + (p.code || code) + '"><g class="fp-bloom" data-hd="' + hd + '" style="--hd:' + hd + 'deg"><title>你的类型 ' + code + ' ' + (TYPES[code] ? TYPES[code][0] : '') + '</title><g class="fp-bd">' +
    (lay.back ? '<g class="fp-pw fp-back">' + lay.back + '</g>' : '') + '<g class="fp-pw fp-front">' + lay.front + '</g></g></g><g class="fp-heart">' + lay.heart + '</g></g>';
  const tn = TYPES[code];
  return '<svg class="fp2' + (sm ? ' fp-sm' : '') + (sel != null ? ' fp-sel' : '') + '" width="' + size + '" height="' + size + '" viewBox="0 0 400 400" role="img" aria-label="协作指纹：外框是 16 种类型，16 个扇区各标类型码，右半是委托、左半是掌舵、上半是即兴、下半是规划；外圈是每个会话按它自己的四个维度落到的方位，每个 Agent 一条独立曲线，越高会话越多；Agent 标志停在外圈同一条轨道上，方位是该 Agent 全部会话的平均方向；内盘是' + (tn ? ' ' + code + ' ' + tn[0] + ' ' : '协作人格') + '的花，一片瓣与外框上的三角指向你的类型" style="overflow:visible;max-width:100%;height:auto">' +
    '<defs><mask id="' + uid + '" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="400"><circle class="fp-sweep" cx="200" cy="200" r="' + (R0 + RH / 2) + '" fill="none" stroke="#fff" stroke-width="' + (RH + 30) + '" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="0" transform="rotate(-90 200 200)"/></mask>' +
    (sel != null ? '<clipPath id="' + uid + 'c"><path d="' + sector(R0 - 2, RO + 2, sel * 22.5, (sel + 1) * 22.5) + '"/></clipPath>' : '') + '</defs>' +
    '<g class="fp-base"><circle cx="200" cy="200" r="196" fill="none" stroke="var(--ink-4)" stroke-width=".8"/>' +
    '<path class="fp-tk" d="' + tk[0] + '" stroke="var(--ink-4)" stroke-width=".5"/><path class="fp-tk" d="' + tk[1] + '" stroke="var(--ink-4)" stroke-width=".9"/><path class="fp-tk" d="' + tk[2] + '" stroke="var(--ink-2)" stroke-width="1.2"/>' +
    '<path class="fp-n0" d="M200 2L195 -8L205 -8Z" fill="var(--orbit)" transform="rotate(' + hd + ' 200 200)"/></g>' +
    '<g class="fp-hours">' + lbl + '</g>' +
    '<g class="fp-band"></g>' +
    orbG + focus + '<g class="ring">' + ring + '</g><g class="dots">' + dots + '</g>' + planets +
    '<g class="fp-core"></g>' +
    flower + '</svg>';
}
const fpPct = (n, all) => Math.round(n / Math.max(1, all) * 100) + '%';
TIPS.fpp = (id) => { const F = CUR.fp; const x = F && F.pl.find((q) => q.a.id === id); if (!x) return ''; return '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + fpMute(x.a.c, 74) + ';vertical-align:-1px"></span> <b>' + x.a.name + ' · ' + x.n + ' 个会话 · 平均偏向 ' + x.code + ' ' + TYPES[x.code][0] + '</b>\n占全部 ' + fpPct(x.n, F.n) + ' · 标志停在这些会话方位的平均方向上'; };
TIPS.fpt = (t) => { const F = CUR.fp; if (!F) return ''; const xs = F.byT[+t], c = FP_TYPES[+t]; const by = AG.map((a) => [a, xs.filter((s) => s.a === a.id).length]).filter((x) => x[1]); return '<b>' + c + ' ' + TYPES[c][0] + ' · ' + xs.length + ' 个会话（' + fpPct(xs.length, F.n) + '）</b>\n' + (by.length ? by.map((x) => '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + fpMute(x[0].c, 74) + ';vertical-align:-1px"></span> ' + x[0].short + ' ' + x[1]).join(' · ') : '没有会话偏向这一型') + '\n<span style="opacity:.75">' + (S.persona.fpType === +t ? '再点一次收起' : '点击展开') + '</span>'; };
// previous calendar month of a month period (null for 近 90 天 / 全部)
function pePrevKey(k) { const ks = peMonthKeys(); const i = ks.indexOf(k); return i > 0 ? ks[i - 1] : null; }
function peMonthLbl(k) { return LV.live ? k : '2026-0' + ({ jun: 6, jul: 7, aug: 8, sep: 9 })[k]; }
PAGES.persona = () => {
  if (!PERIODS[S.persona.period]) S.persona.period = '90';
  if (LV.live && S.persona.vs === 'pop') S.persona.vs = 'past';   // no population baseline in live (POP is a demo constant)
  const per = PERIODS[S.persona.period];
  const L = personaScope([per[0], per[1]]);
  // live: the full /v1/uiview/persona payload for this period (axes, evidence, traits, strengths, blind spots, months)
  const p = LV.live && L.length >= 1 && !lvHasUnits(L) ? LV.personaFor(S.persona.period, L) : persona(L);
  const note = personaScopeNote();
  const months = peMonthKeys().map((k) => ({ k, lbl: peMonthLbl(k), p: persona(personaScope([PERIODS[k][0], PERIODS[k][1]])) }));
  const prevKey = pePrevKey(S.persona.period);
  const prev = prevKey ? persona(personaScope([PERIODS[prevKey][0], PERIODS[prevKey][1]])) : null;
  const filt = (S.project ? PJI[S.project].name + ' · ' : '') + (S.agents.size < AG.length ? AG.filter((a) => S.agents.has(a.id)).map((a) => a.short).join(' / ') + ' · ' : '');
  const cm = peCurMonth();
  const right = '<div class="seg" role="group" aria-label="统计周期">' + [[cm, PERIODS[cm][2]], ['90', '近 90 天'], ['all', '全部']].map((x) => '<button type="button" data-act="period" data-v="' + x[0] + '" class="' + (S.persona.period === x[0] ? 'on' : '') + '">' + x[1] + '</button>').join('') + '</div><button type="button" class="btn gh" data-act="method">' + ic('info', 14) + '算法说明</button><button type="button" class="btn" data-act="share">' + ic('share', 14) + '导出分享卡</button><button type="button" class="btn ai" data-act="ask" data-ctx="persona">' + ic('spark', 14) + '让 Agent 写一份自述</button>';
  const allOff = AG.every((a) => S.srcOff.has(a.id));
  if (p.pending) return tbar('协作人格', filt + L.length + ' 个会话 · ' + per[2], right) + '<div class="content" id="content"><div class="stack">' + LV.pend(420) + LV.pend(260) + '</div></div>';
  if (!p.ok) {
    const frac = 0; const x = 56, y = 10;   // 1 个会话即可出结论：这里只剩没有会话 / 取不到 / 暂不计算三种空态，环不再表示进度
    const relax = peRelax([per[0], per[1]]).filter((r) => r.n > L.length);   // only filters whose removal adds sessions (D)
    const more = relax.some((r) => r.k !== 'period'), wider = relax.some((r) => r.k === 'period');
    return tbar('协作人格', filt + '基于 ' + L.length + ' 个会话 · ' + per[2], right) + '<div class="content" id="content"><div class="card pad pe-low"><svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true"><circle cx="56" cy="56" r="46" fill="none" stroke="var(--line)" stroke-width="10"/>' + (frac > 0 ? '<path d="M56 10 A46 46 0 ' + (frac > 0.5 ? 1 : 0) + ' 1 ' + x.toFixed(1) + ' ' + y.toFixed(1) + '" fill="none" stroke="var(--ink-1)" stroke-width="10" stroke-linecap="round"/>' : '') + '<text x="56" y="62" text-anchor="middle" font-size="18" font-weight="700" font-family="var(--font-num)" fill="var(--ink-1)">' + L.length + '</text></svg><div class="col" style="flex:1;min-width:240px">' +
      (allOff ? '<h2 class="serif" style="margin:0;font-size:24px">所有数据源已停用</h2><p style="margin:0;color:var(--ink-2)">人格需要会话数据。到「设置 › 数据源」重新启用至少一个 Agent，分析会立即恢复。</p><div class="row"><button type="button" class="btn p" data-act="openSettings" data-tab="sources">打开设置 · 数据源</button></div>'
        : L.length ? '<h2 class="serif" style="margin:0;font-size:24px">' + (persPending(p.error) ? '正在整理数据…' : p.error ? '画像暂时取不到' : '当前筛选下暂不计算画像') + '</h2><p style="margin:0;color:var(--ink-2)">' + (persPending(p.error) ? '导入的会话发布后会自动显示画像。' : p.error ? '稍后会自动重试，也可以换一个统计周期。' : '换一个统计周期，或清除 Agent / 项目筛选。') + '</p><div class="row" style="flex-wrap:wrap"><button type="button" class="btn" data-act="period" data-v="all">看全部历史</button></div>'
        : '<h2 class="serif" style="margin:0;font-size:24px">当前筛选下还没有会话</h2><p style="margin:0;color:var(--ink-2)">有 1 个会话就能给出协作人格。' + (relax.length ? '放宽下面任一筛选可以补到：' : '会话还不够，继续使用 Orbit 就会积累。') + '</p>' + peScopeTag(per) +
        (relax.length ? '<div class="pe-relax">' + relax.map((r) => '<button type="button" class="chip on" data-act="peRelax" data-k="' + r.k + '">' + esc(r.t) + ic('x', 12) + '<b class="mono" style="color:' + (r.n >= 1 ? 'var(--good)' : 'var(--ink-3)') + '">移除后约 ' + r.n + ' 个会话</b></button>').join('') + '</div>' : '') +
        (more || wider ? '<div class="row" style="flex-wrap:wrap">' + (more ? '<button type="button" class="btn p" data-act="clearAllFilters">清除筛选</button>' : '') + (wider ? '<button type="button" class="btn' + (more ? '' : ' p') + '" data-act="period" data-v="all">看全部历史</button>' : '') + '</div>' : '')) +
      '</div></div></div>';
  }
  CUR.persona = p;
  const traits = [];
  if (LV.live) (p.traits || []).forEach((t) => traits.push(t));
  else {
    traits.push(p.v.D >= 50 ? '高吞吐' : '亲自掌舵', p.v.I >= 50 ? '边做边想' : '先规划', p.v.M >= 50 ? '多线程' : '单线专注', p.v.V >= 50 ? '验收严格' : '信任结果');
    traits.push('中英混用');
  }
  const st = p.st || stats(L); if (p.avgS == null) Object.assign(p, { avgS: 0, avgA: 0 });
  const conts = LV.live && p.blind_spots ? p.blind_spots.map((b) => [b.type, b.n]) : Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const recFor = { '方向错误': 'deploy-target', '工具 / 环境失败': 'retry-breaker', '改动过度': 'paper-audit', '误解需求': 'acceptance', '并行会话冲突': 'worktree', '流程过重（子代理）': 'pr-wrapup', '额度 / 用量中断': 'summary-compact' };
  const fitRows = AG.map((a) => { const xs = L.filter((s) => s.a === a.id); const st2 = stats(xs); const f = fitOf(xs); const okp = st2.ok / 100; const ci = f == null ? null : Math.round(1.96 * Math.sqrt(okp * (1 - okp) / xs.length) * 100); return { a, n: xs.length, f, st: st2, ci, off: S.srcOff.has(a.id) }; });
  CUR.peMonths = months;
  const evos = [0, 1, 2, 3].map((i) => peEvidence(L, st, p, i));
  const metaFull = filt + '基于 ' + L.length + ' 个会话 · ' + new Set(L.map((s) => s.a)).size + ' 个 Agent · ' + per[2] + (note ? ' · ' + note : '');
  return tbar('协作人格', '<span title="' + esc(metaFull) + '">' + filt + L.length + ' 个会话 · ' + per[2] + '</span>', right) +
    '<div class="content" id="content"><div class="stack">' +
    '<div class="card persona-hero"><div class="col" style="gap:0;min-width:0"><div class="row" style="flex-wrap:wrap"><span class="eb" title="Your agent collaboration type">你的协作人格</span><span class="tag" data-tip="维度信号与权重是初版设想，待真实数据校准">实验性</span><span class="bdg">置信度 ' + p.conf + ' · ' + fmt(p.n) + ' 个会话</span>' + peScopeTag(per) + (p.hint ? '<span class="cap" style="font-size:11px">' + esc(p.hint) + '</span>' : '') + '</div>' +
    '<div class="letters" data-hero="code">' + p.code.split('').map((ch, i) => { const a = axisView(p, i); return '<button type="button" data-act="axisJump" data-tf="axis|' + i + '"><span class="L">' + ch + '</span><span style="font-size:12px;color:var(--ink-2);white-space:nowrap">' + (ch === '?' ? '未定型' : a.name) + ' <span class="mono" style="color:var(--ink-1);font-weight:600">' + a.strong + '</span></span></button>'; }).join('') + '</div>' +
    '<div class="row" style="align-items:baseline;gap:12px;margin-top:16px;flex-wrap:wrap"><span class="serif" style="font-size:36px;line-height:1.1;font-weight:600">' + p.zh + '</span><span class="serif" style="font-size:24px;color:var(--ink-3)">' + p.en + '</span></div>' +
    '<p class="pe-line">' + esc(p.line) + '<button type="button" class="btn sm gh" data-act="notMe">不像我？</button></p><div class="pe-facts mono"><span><b>' + f1(st.per) + '</b> 条消息 / 会话</span><span><b>' + f1(st.auto) + '</b> 步自主 / 轮</span><span><b>' + Math.round(st.verify) + '%</b> 要求验证</span></div>' +
    '<div class="row" style="flex-wrap:wrap;gap:6px;margin-top:12px">' + traits.map((t) => '<span class="tag">' + t + '</span>').join('') + '</div>' +
    (note ? '<div class="cap" style="margin-top:8px;font-size:11px" title="人格只按时间、Agent 与项目计算，和侧栏、报告一致">' + esc(note) + '</div>' : '') +
    // 演变：月份码 + 四轴折线（评审 A2-V06）
    '<div class="pe-evw"><div class="eb" style="margin-bottom:8px" title="按月重算，点击月份切换统计周期">演变 · 按月</div><div class="evo pe-evrow">' + months.map((m, i) => '<button type="button" data-act="period" data-v="' + m.k + '" class="' + (S.persona.period === m.k ? 'on' : '') + '"><span class="mono" style="display:block;font-size:10px;color:var(--ink-3)">' + m.lbl + '</span><span class="tcode" style="display:block;font-size:14px;letter-spacing:.06em">' + (m.p.ok ? m.p.code : '—') + '</span><span style="display:block;font-size:11px;color:var(--ink-2)">' + (m.p.ok ? m.p.zh : '样本不足') + '</span></button>' + (i < 3 ? ic('arrow', 12, 'color:var(--ink-4)') : '')).join('') + '</div>' +
    '<div class="vz pe-evo" data-vz="pe-evo"></div><div class="cap pe-foot" title="四个维度逐月的值；跨过中线 50 的月份，该位字母会变">中线 50 · ≥ 50 取高值一极</div></div></div>' +
    '<div class="fp-wrap" data-hero="fp"><button type="button" class="btn sm gh" data-act="reveal" style="position:absolute;right:8px;top:8px;z-index:2">重播揭晓</button>' + '<div class="pe-fpc">' + fp2SVG(L, p, 400, { interactive: true, labels: true }) +
    '</div></div></div>' +
    '<div class="three pe-three" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr) minmax(0,1fr)">' +
    '<div class="card pad" id="axesCard"><div class="hd"><div class="grow"><span class="ct">四个维度</span></div><div class="seg" role="group" aria-label="对照组"><button type="button" data-act="vs" data-v="past" class="' + (S.persona.vs === 'past' ? 'on' : '') + '">与过去的我</button>' + (LV.live ? '' : '<button type="button" data-act="vs" data-v="pop" class="' + (S.persona.vs === 'pop' ? 'on' : '') + '">与全体用户</button>') + '</div></div>' +
    '<div class="vz" data-vz="pe-axes"></div>' +
    '<div class="pe-ev">' + evos.map((e, i) => { const a = axisView(p, i); return '<div class="pe-evi" title="' + esc(e.lbl) + '"><span class="row" style="justify-content:space-between;gap:6px"><span class="mono pe-evl">' + a.ax.dim + ' · ' + a.letter + '</span>' + VZ.spark(e.vals, { bars: true, w: 72, h: 20, color: 'var(--h3)', last: 'var(--h3)', label: e.lbl }) + '</span><span class="pe-evt">' + esc(e.txt) + '</span></div>'; }).join('') + '</div>' +
    '<div class="cap pe-foot" title="中线为 50；条偏向哪一侧就取哪一极，恰好 50 归高值一极">细刻度 = ' + (S.persona.vs === 'pop' ? '全体用户均值（示例）' : prev && prev.ok ? '上个月' : '无可比时段') + ' · 中线 50 为分界</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">优势与盲点</span></div></div><div class="col pe-sw">' +
    (LV.live ? (p.strengths || []).map((x) => [x.text, '强度 ' + x.strong + ' · ' + peUnits(x.n_units, ((p.axes || []).find((a) => a.k === x.k) || {}).unit), true]) : [['整段委托', '每轮自主 ' + f1(st.auto) + ' 步', p.v.D >= 50], ['验收严格', Math.round(st.verify) + '% 要求验证', p.v.V >= 50], ['节奏稳定', '日均 ' + f1(p.avgS) + ' 个会话', true]]).filter((x) => x[2]).map((x) => '<div class="pe-swr">' + ic('okc', 14, 'color:var(--good)') + '<b>' + x[0] + '</b><span class="m">' + x[1] + '</span></div>').join('') +
    '<div class="pe-swsep"></div>' +
    (conts.length ? conts.map((c) => '<div class="pe-swr">' + ic('alert', 14, 'color:var(--crit)') + '<b title="' + esc(c[0]) + '">' + c[0] + '</b><span class="m">出现在 ' + c[1] + ' 个会话</span>' + (LV.live ? '<button type="button" class="lnk" data-act="go" data-r="recs">建议 →</button>' : '<button type="button" class="lnk" data-act="openRec" data-id="' + recFor[c[0]] + '">建议 →</button>') + '</div>').join('') : '<span class="cap">这段时间没有明显盲点。</span>') + '</div></div>' +
    // 契合度：中性条 + 透明度随 n + 95% 区间（评审 A2-V07）；来源停用的 Agent 不可点（BUG-49）
    '<div class="card pad"><div class="pe-fit-h"><span class="ct">与 Agent 的契合度</span><span class="cap">0–100 · 细线为 95% 区间</span></div><div class="col" style="gap:12px">' +
    fitRows.map((r) => '<' + (r.off || !r.n ? 'div' : 'button type="button" data-act="soloAgent" data-a="' + r.a.id + '"') + ' class="pe-fit' + (r.off ? ' off' : '') + '"><span class="row pe-fit-t"><span class="dot" style="background:' + r.a.c + '"></span><span style="flex:1">' + r.a.name + '</span>' + (r.off ? '<span class="cap" style="font-size:11px">来源已停用</span>' : '<b class="mono">' + (r.f == null ? '—' : r.f) + '</b>') + '</span><span class="pe-fit-bar" style="opacity:' + (r.n < 20 ? 0.5 : 1) + '"><span class="fill" style="width:' + (r.f || 0) + '%"></span>' + (r.ci != null ? '<span class="ci" style="left:' + Math.max(0, r.f - r.ci) + '%;width:' + Math.min(100 - Math.max(0, r.f - r.ci), r.ci * 2) + '%"></span>' : '') + '</span><span class="pe-fit-m">' + (r.off ? '到设置里重新启用后参与计算' : r.n < 5 ? '样本少（' + r.n + ' 个会话），不计分' : '<span class="nw" title="' + r.n + ' 个会话' + (r.n < 20 ? '（样本少）' : '') + ' · 95% 区间 ±' + r.ci + ' · 完成率 ' + Math.round(r.st.ok) + '% · 摩擦率 ' + f1(r.st.fric) + '%">' + r.n + ' 个会话 · ±' + r.ci + ' · 完成 ' + Math.round(r.st.ok) + '% · 摩擦 ' + f1(r.st.fric) + '%</span>') + '</span></' + (r.off || !r.n ? 'div' : 'button') + '>').join('') +
    '</div><div class="cap pe-foot" title="契合度综合完成率与摩擦率；条越淡，样本越少（n < 20）">条越淡样本越少 · 点击只看该 Agent</div></div>' +
    '</div></div></div>';
};
PAGES.persona.after = () => {
  const p = CUR.persona; if (!p || !$('[data-vz="pe-axes"]')) return;
  const prevKey = pePrevKey(S.persona.period);
  const prev = prevKey ? persona(personaScope([PERIODS[prevKey][0], PERIODS[prevKey][1]])) : null;
  VZ.mount('pe-axes', { type: 'diverging', title: '协作人格 · 四个维度', rows: peAxisRows(p, prev), domain: [-1, 1], colors: ['var(--ink-2)', 'var(--ink-2)'], format: peNum, refLabel: S.persona.vs === 'pop' ? '全体用户（示例）' : '上月', axis: false, rowH: 34, barH: 10, legend: false, animate: false, onSelect: () => ACT.axisJump() });
  const months = CUR.peMonths || [];
  VZ.mount('pe-evo', { type: 'line', title: '四个维度 · 逐月', height: 150, legend: 'top', animate: false, points: true, endLabels: false, x: { values: months.map((m) => m.lbl.slice(5) + ' 月') }, y: { min: 0, max: 100, format: 'int', ticks: 4 }, refs: [{ y: 50 }],
    series: [['D', '委托 D', 'var(--ink-1)', false], ['I', '即兴 I', 'var(--ink-2)', true], ['M', '多线 M', 'var(--ink-3)', false], ['V', '求证 V', 'var(--h3)', true]].map((k) => ({ name: k[1], color: k[2], dash: k[3], values: months.map((m) => m.p.ok ? Math.round(m.p.v[k[0]]) : null) })) });
};
TIPS.axis = (i) => { const p = CUR.persona; if (!p) return ''; const a = axisView(p, +i); return '<b>' + a.ax.dim + '：' + a.ax.L + ' ' + a.ax.Ln + ' ↔ ' + a.ax.R + ' ' + a.ax.Rn + '</b>\n' + a.ax.q + '\n<span style="opacity:.8">信号：' + a.ax.sig + '</span>'; };
Object.assign(ACT, {
  period: (el) => { S.persona.period = el.dataset.v; S.persona.fpType = null; render(); },
  vs: (el) => { S.persona.vs = el.dataset.v; render(); },
  fpType: (el) => { const t = +el.dataset.t; S.persona.fpType = S.persona.fpType === t ? null : t; tipOff(); render(); },
  peRelax: (el) => { const k = el.dataset.k; if (k === 'project') S.project = null; else if (k === 'agents') AG.forEach((a) => S.agents.add(a.id)); else S.persona.period = 'all'; render(); },
  axisJump: () => { const c = $('#axesCard'); if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'center' }); c.animate([{ boxShadow: '0 0 0 3px var(--focus)' }, { boxShadow: '0 0 0 0 transparent' }], { duration: 900 }); } },
  notMe: (el) => openDD(el, [{ h: '哪里不像你？' }, { t: '描述太夸张了', v: 1 }, { t: '某个维度判断不对', v: 2 }, { t: '这段时间不代表我', v: 3 }, { t: '其他', v: 4 }], () => toast('已记录反馈，下次计算会降低相关信号的权重')),
  soloAgent: (el) => {
    const id = el.dataset.a;
    if (S.srcOff.has(id)) { toast(agent(id).name + ' 已在设置中停用，先到「设置 › 数据源」启用', { act: '打开设置', onAct: () => openSettings('sources') }); return; }
    S.agents.clear(); S.agents.add(id); render(); toast('已只看 ' + agent(id).name + '；点侧边栏同一个 Agent 可恢复全部');
  },
  clearAllFilters: () => {
    S.project = null; S.topic = null; S.outcome = null; S.fric = null; S.hour = null; AG.forEach((a) => S.agents.add(a.id)); render();
    if (AG.every((a) => S.srcOff.has(a.id))) toast('筛选已清除，但所有数据源都已停用', { act: '打开设置', onAct: () => openSettings('sources') });
  },
  method: () => openMethod(),
  share: () => openShare(),
  reveal: () => (LV.live ? peLiveReveal() : openReveal()),
  openSession: (el) => {
    const s = BYID[el.dataset.id];
    if (!s || !sourceEnabled(s) || S.excluded.has(s.id)) { toast('此会话的来源已停用或已从分析中排除'); return; }
    stopPlay();
    S.agents.add(s.a);
    for (const [key, value] of [['project', s.p], ['topic', s.topic], ['outcome', s.out], ['fric', s.fric], ['hour', s.h]]) {
      if (S[key] != null && S[key] !== value) S[key] = null;
    }
    const w = win(S.range);
    if (s.d !== (LV.live ? -1 : 120) && (s.d < w[0] || s.d > w[1])) S.range = 0;
    S.sess.sel = s.id; S.sess.mode = 'single'; S.sess.cmp = null; S.sess.q = ''; S.sess.ph = traj(s).T;
    go('sessions');
  }
});
// 进入画像页（Advance persona / Lite l-persona）：花做一次阻尼晃动后定位到你的类型，轨道随扫描遮罩从 12 点顺时针展开（0.9 s），
// 徽章从 12 点出发沿轨道运行到各自多数会话所在的类型（1.2 s，彼此错开 60 ms）。Genesis 落地时（overlay 仍开着）都不播，
// 免得飞入的表盘与页面对不上。减少动态效果时静止。
function fpWobble(svg) {
  const nd = svg && svg.querySelector('.fp-bd'); if (!nd || !nd.animate || reduceMotion()) return null;
  return nd.animate([-40, 24, -12, 6, -2, 0].map((d) => ({ transform: 'rotate(' + d + 'deg)' })), { duration: 1400, easing: 'cubic-bezier(.37,0,.63,1)' });
}
function fpOrbitIn(svg) {
  if (!svg || reduceMotion()) return [];
  const out = [], sw = svg.querySelector('.fp-sweep');
  if (sw && sw.animate) out.push(sw.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 900, easing: 'cubic-bezier(.45,.05,.35,1)' }));
  svg.querySelectorAll('.fp-pl').forEach((el, i) => { if (el.animate) out.push(el.animate([{ transform: 'rotate(0deg)', opacity: 0 }, { opacity: 1, offset: 0.12 }, { transform: 'rotate(' + el.dataset.pa + 'deg)', opacity: 1 }], { duration: 1200, delay: i * 60, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' })); });
  return out;
}
// 何时播放（进入页面、版本切换、数据到位、人格切换时的收起与绽开）由 38-bloom-motion.js 的渲染钩子决定

// live reveal: GET /v1/uiview/persona/reveal for the shown scope first; a settled code plays the same dial / Genesis reveal
// on the real rows (openReveal → persona(L) → personaLive); only an empty scope (0 sessions) has nothing to reveal
function peLiveReveal() {
  const period = S.route === 'persona' ? S.persona.period : ({ 7: '7', 30: '30', 90: '90', 0: 'all' })[S.range];
  const e = LV.reveal(period); const go2 = () => {
    const d = e.data;
    if (!d) { toast(e.state === 'error' ? '揭晓数据暂不可用' : '正在准备揭晓…'); return; }
    if (!d.ok) { toast('当前范围还没有会话，暂时不能揭晓'); return; }
    if (!d.classified) { toast('协作画像正在更新，稍后再揭晓'); return; }   // 旧版快照（带「?」）才会走到这里
    openReveal(S.route === 'persona' ? { L: personaScope([PERIODS[period][0], PERIODS[period][1]]) } : undefined);
  };
  if (e.data || e.state === 'error') go2(); else { const t0 = Date.now(); const iv = setInterval(() => { if (e.data || e.state === 'error' || Date.now() - t0 > 8000) { clearInterval(iv); go2(); } }, 100); }
}
