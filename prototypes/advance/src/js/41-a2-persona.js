/* ============ A2 persona ============
 * 结构：hero（四字母 + 名称 + 「实验性」+ 演变：月份码 + 四轴折线）与协作指纹（Orbit 罗盘：外框 120 道刻度与 24 小时方位 /
 * 轨道环带（五层平滑，每个 Agent 一层）+ 24 个小时热区，点击展开该小时的会话点 / Agent 行星停在各自的协作重心 / 节律带 /
 * 内盘罗盘玫瑰 + 指向协作重心的指针）→ 四个维度（VZ 双向条：45–55 未定型带、对照刻度、
 * 数值跟随胜出极、每轴证据微型图）+ 优势与盲点 + 契合度（中性条、透明度随 n、95% 区间、Agent 色只在圆点）。
 * 人格口径统一走 personaScope（BUG-06）；样本不足时列出放宽哪个筛选能补到多少（A2-V08），全部来源停用时引导到设置（BUG-50）。 */
const PERIODS = { sep: [90, 119, '9 月'], '90': [30, 119, '近 90 天'], all: [0, 119, '全部'], jun: [0, 27, '6 月'], jul: [28, 58, '7 月'], aug: [59, 89, '8 月'] };
const POP = { D: 52, I: 54, M: 47, V: 58 };
if (S.persona.fpHour === undefined) S.persona.fpHour = null;
const peNum = (v) => String(Math.round(Math.abs(v) * 50 + 50));
function peAxisRows(p, prev) {
  return [0, 1, 2, 3].map((i) => {
    const a = axisView(p, i); const k = a.ax.k; const sgn = k === 'I' ? 1 : -1;
    const gv = S.persona.vs === 'pop' ? POP[k] : (prev && prev.ok ? prev.v[k] : null);
    return { name: '', left: a.ax.L + ' ' + a.ax.Ln, right: a.ax.Rn + ' ' + a.ax.R, value: +((50 - a.val) * sgn * -1 / 50).toFixed(2), ref: gv == null ? null : +((50 - gv) * sgn * -1 / 50).toFixed(2), hint: a.ax.q + ' · 强度 ' + a.strong, id: k };
  });
}
// 每轴证据微型图：D 每会话消息数分布、P/I 项目按结构度排序的时长、M 每日会话数分布、V 项目按求证度排序的时长
function peEvidence(L, st, p, i) {
  if (LV.live) {   // live: the server's per-axis evidence (unit counts the client cannot see until G1)
    const ax = (p.axes || [])[i]; const e = ax && ax.evidence;
    return e ? { txt: e.txt, vals: e.vals && e.vals.length ? e.vals : [0], lbl: e.lbl + (e.projects && e.projects.length ? ' · ' + e.projects.join(' / ') : '') } : { txt: ax ? ax.n_units + ' 个' + ({ turn: '轮次', session_opening: '开场', active_day: '活跃日' })[ax.unit] : '—', vals: [0], lbl: '暂无证据' };
  }
  const hist = (vals, n, max) => { const out = new Array(n).fill(0); vals.forEach((v) => { out[Math.min(n - 1, Math.floor(v / max * n))]++; }); return out; };
  const byProj = (key) => PJ.slice().sort((a, b) => a[key] - b[key]).map((pj) => sum(L.filter((s) => s.p === pj.id), (s) => s.dur) / 60);
  if (i === 0) return { txt: '每会话 ' + f1(st.per) + ' 条消息 · 每轮 ' + f1(st.auto) + ' 步', vals: hist(L.map((s) => s.msgs), 10, 20), lbl: '消息数 0 → 20+ 的会话数' };
  if (i === 1) return { txt: '规划型项目占 ' + Math.round(sum(L.filter((s) => PJI[s.p].I < 50), (s) => s.dur) / (st.hours * 60 || 1) * 100) + '% 时长', vals: byProj('I'), lbl: '项目时长 · 规划型 → 即兴型' };
  if (i === 2) { const by = {}; L.forEach((s) => { by[s.d] = (by[s.d] || 0) + 1; }); return { txt: '日均 ' + f1(p.avgS) + ' 会话 · 同日 ' + f1(p.avgA) + ' Agent', vals: hist(Object.values(by), 8, 8), lbl: '每日会话数 1 → 8+ 的天数' }; }
  return { txt: Math.round(st.verify) + '% 要求验证 · 完成 ' + Math.round(st.ok) + '%', vals: byProj('V'), lbl: '项目时长 · 信任型 → 求证型' };
}
// 样本不足时：放宽哪个筛选能补到多少（只看人格口径里的三个条件：Agent、项目、周期）
function peRelax(w) {
  const out = []; const n = (o) => ALL.filter((s) => s.d >= o.w[0] && s.d <= o.w[1] && !s.live && sourceEnabled(s) && (o.allAg || S.agents.has(s.a)) && (o.noProj || !S.project || s.p === S.project)).length;
  if (S.project) out.push({ k: 'project', t: '项目 · ' + PJI[S.project].name, n: n({ w, noProj: true }) });
  if (S.agents.size < AG.length) out.push({ k: 'agents', t: 'Agent · ' + AG.filter((a) => S.agents.has(a.id)).map((a) => a.short).join(' / '), n: n({ w, allAg: true }) });
  if (S.persona.period !== 'all') out.push({ k: 'period', t: '周期 · ' + PERIODS[S.persona.period][2], n: n({ w: [0, LASTDAY] }) });
  return out;
}
const AXR = { D: 0, I: 90, M: 180, V: 270 };
// 罗盘几何（400 视框，圆心 200）：外框 198/195 + 120 道刻度、轨道环带 R0 → R0+RH、行星轨道 PR、节律带 98 → 118、内盘 92、
// 玫瑰半径 RR、指针半长 NL（= 0.8 × RR，短于字母位，不压住分数）。Genesis（56-onboarding.js）的粒子落点、环带扫描与玫瑰生长共用这一组常量。
const FPG = { R0: 124, RH: 38, RR: 70, NL: 56, PR: 160 };
let FP_UID = 0;
// 协作重心：会话开始时刻在 24 小时表盘上的圆形平均（0° = 00:00，顺时针）；没有会话时指向 00
function fpHeading(L) {
  let sx = 0, cx = 0; L.forEach((s) => { const a = (s.h + s.mi / 60) / 24 * Math.PI * 2; sx += Math.sin(a); cx += Math.cos(a); });
  const deg = Math.abs(sx) + Math.abs(cx) < 1e-9 ? 0 : (Math.atan2(sx, cx) * 180 / Math.PI + 360) % 360;
  const mins = Math.round(deg / 360 * 1440) % 1440;
  return { deg: +deg.toFixed(1), hm: Math.floor(mins / 60) + ':' + String(mins % 60).padStart(2, '0') };
}
// 轨道环带（与宣传片共用的规格）：每个 Agent 一层，层高 = 该小时该 Agent 的会话数 ÷ 全天最大的小时总数 × RH；
// 小时值放在该小时扇区的中线上，小时之间用周期 Catmull-Rom 平滑，每 2° 采样，按 AG 顺序逐层叠加。
// 行星：每个有会话的 Agent 一颗，停在它自己的协作重心上（轨道半径 PR）。
function fpOrbit(L) {
  const hrs = Array.from({ length: 24 }, () => AG.map(() => 0)); L.forEach((s) => { const i = AG.findIndex((a) => a.id === s.a); if (i >= 0) hrs[s.h][i]++; });
  const mx = Math.max(1, ...hrs.map((r) => r.reduce((x, y) => x + y, 0)));
  const N = 180, cum = new Array(N + 1).fill(0), layers = [];
  const cr = (i, x) => { const h0 = Math.floor(x), f = x - h0, v = (k) => hrs[((h0 + k) % 24 + 24) % 24][i], a = v(-1), b = v(0), c = v(1), d = v(2); return 0.5 * (2 * b + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f * f + (-a + 3 * b - 3 * c + d) * f * f * f); };
  AG.forEach((ag, i) => {
    const inner = cum.slice();
    for (let s = 0; s <= N; s++) cum[s] += Math.max(0, cr(i, s / N * 24 - 0.5)) / mx * FPG.RH;
    layers.push({ a: ag, inner, outer: cum.slice(), n: hrs.reduce((x, r) => x + r[i], 0) });
  });
  const planets = AG.map((ag) => { const xs = L.filter((s) => s.a === ag.id); if (!xs.length) return null; const hd = fpHeading(xs); return { a: ag, n: xs.length, deg: hd.deg, hm: hd.hm }; }).filter(Boolean);
  return { hrs, mx, layers, planets };
}
// 一层环带的路径：外缘顺时针，内缘逆时针收口
function fpLayerD(ly) {
  const N = ly.outer.length - 1, f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1); let d = '';
  for (let s = 0; s <= N; s++) d += (s ? 'L' : 'M') + f(pt(200, FPG.R0 + 1 + ly.outer[s], s / N * Math.PI * 2));
  for (let s = N; s >= 0; s--) d += 'L' + f(pt(200, FPG.R0 + 1 + ly.inner[s], s / N * Math.PI * 2));
  return d + 'Z';
}
// 玫瑰主角长度：随该轴强度（50 → 85+）从 0.36 长到 1.0 × RR（实际强度多在 55–80，按 85 封顶让形状可读）；u 用于 Genesis 生长（0 = 强度 50 的长度）
const fpRoseLen = (strong, u) => FPG.RR * (0.36 + 0.64 * clamp((strong - 50) / 35, 0, 1) * (u == null ? 1 : u));
// 一个罗盘角：顺时针半面实心、逆时针半面空心描边（经典明暗面）；w = 侧点半径
function fpRosePt(deg, len, w) {
  const a = deg * Math.PI / 180, f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
  const tip = f(pt(200, len, a)), r = f(pt(200, w, a + Math.PI / 4)), l = f(pt(200, w, a - Math.PI / 4));
  return ['M200 200L' + tip + 'L' + r + 'Z', 'M200 200L' + tip + 'L' + l + 'Z'];
}
// 协作指纹 · Orbit 罗盘（评审 A2-V01/02/03）：外框 120 道刻度与 24 小时方位；轨道环带（五层平滑，每个 Agent 一层）上有 24 个透明的
// 小时热区（选中小时展开会话点）与 Agent 行星（各自的协作重心）；节律带；内盘是罗盘玫瑰（四个主角朝 D I M V，长度 = 该轴强度，
// 端点标胜出极与分数），指针指向全体协作重心（--hd，CSS rotate），画在字母与分数下层。环带的 .fp-sweep 遮罩与行星的 --pa 留给入场动画。
function fp2SVG(L, p, size, opt) {
  opt = opt || {}; const C = 200; const R0 = FPG.R0, RH = FPG.RH, RR = FPG.RR; const sm = size < 340; const k = sm ? 1.25 : 1; const uid = 'fpm' + (++FP_UID);
  const byH = Array.from({ length: 24 }, () => []); L.forEach((s) => byH[s.h].push(s));
  const mxH = Math.max(1, ...byH.map((x) => x.length));
  const orb = fpOrbit(L);
  CUR.fp = { byH, mxH, pl: orb.planets };
  const f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1);
  const sector = (r0, r1, a0, a1) => { const p0 = pt(C, r0, a0), p1 = pt(C, r1, a0), p2 = pt(C, r1, a1), p3 = pt(C, r0, a1); const lg = a1 - a0 > Math.PI ? 1 : 0; return 'M' + f(p0) + 'L' + f(p1) + 'A' + r1 + ' ' + r1 + ' 0 ' + lg + ' 1 ' + f(p2) + 'L' + f(p3) + 'A' + r0 + ' ' + r0 + ' 0 ' + lg + ' 0 ' + f(p0) + 'Z'; };
  const sel = S.persona.fpHour;
  // 轨道环带：五层连续平滑的 Agent 色带，叠成一条有厚度起伏的轨道（遮罩 .fp-sweep 从 00 顺时针展开）
  const band5 = '<g class="fp-orb" mask="url(#' + uid + ')">' + orb.layers.map((ly, i) => ly.n ? '<path class="fpo" data-a="' + ly.a.id + '" d="' + fpLayerD(ly) + '" fill="' + ly.a.c + '" fill-opacity="' + (0.95 - i * 0.05).toFixed(2) + '"/>' : '').join('') + '</g>';
  // 24 个透明的小时热区：悬停提示该小时按 Agent 的会话数，点击展开会话点；选中时其余小时罩一层纸色
  let ring = '';
  byH.forEach((xs, h) => {
    const a0 = h / 24 * Math.PI * 2, a1 = (h + 1) / 24 * Math.PI * 2; const on = sel == null || sel === h;
    ring += '<g class="fps' + (sel === h ? ' sel' : '') + (!on ? ' dim' : '') + '" data-h="' + h + '"' + (opt.interactive ? ' data-tf="fph|' + h + '" data-act="fpHour" tabindex="0" role="button" aria-label="' + h + ':00–' + (h + 1) + ':00 · ' + xs.length + ' 个会话"' : '') + '><path d="' + sector(R0, R0 + RH + 2, a0, a1) + '" fill="transparent"/></g>';
  });
  // 选中小时：展开该小时的会话点（角度 = 开始分钟，半径 = 时长），这时才能悬停到单个会话
  let dots = '';
  if (sel != null) dots = byH[sel].map((s) => { const a = (s.h + s.mi / 60) / 24 * Math.PI * 2; const q = pt(C, R0 + 4 + Math.min(s.dur, 126) / 126 * (RH - 6), a); return '<circle class="fpd" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="4" fill="' + agent(s.a).c + '" stroke="var(--surface)" stroke-width="1.5"' + (opt.interactive ? ' data-tf="sess|' + s.id + '" data-act="openSession" data-id="' + s.id + '" style="cursor:pointer"' : '') + '/>'; }).join('');
  // 行星：画在 (200, 200 − PR)，外层按 --pa（该 Agent 的协作重心）旋转到位；实心 Agent 色 + 浅色光晕
  const planets = '<g class="fp-pls">' + orb.planets.map((x) => '<g class="fp-pl" data-a="' + x.a.id + '" data-pa="' + x.deg + '" style="--pa:' + x.deg + 'deg"' + (opt.interactive ? ' data-tf="fpp|' + x.a.id + '"' : '') + '><circle cx="200" cy="' + (C - FPG.PR) + '" r="9" fill="' + x.a.c + '" fill-opacity=".2"/><circle class="fp-pd" cx="200" cy="' + (C - FPG.PR) + '" r="4.6" fill="' + x.a.c + '" stroke="var(--surface)" stroke-width="1.3"/></g>').join('') + '</g>';
  // 外框：120 道刻度（每 3°），整点较长、每 6 小时最长；每 3 小时一个方位数字，00 / 06 / 12 / 18 用衬线当作四方位；00 外侧基准三角（--orbit）
  const tk = ['', '', '']; for (let i = 0; i < 120; i++) { const w = i % 30 === 0 ? 2 : i % 5 === 0 ? 1 : 0; const a = i * 3 * Math.PI / 180; tk[w] += 'M' + f(pt(C, 194.5, a)) + 'L' + f(pt(C, [190.5, 187.5, 184][w], a)); }
  const hrs = [0, 3, 6, 9, 12, 15, 18, 21].filter((h) => !sm || h % 6 === 0).map((h) => { const card = h % 6 === 0; const q = pt(C, card ? (sm ? 170 : 171.5) : 176, h * 15 * Math.PI / 180); return '<text x="' + q[0].toFixed(1) + '" y="' + q[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central"' + (card ? ' font-size="' + (sm ? 17 : 15) + '" font-family="var(--serif)" font-weight="700" fill="var(--ink-1)" paint-order="stroke" stroke="var(--bg)" stroke-width="4"' : ' font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)"') + '>' + String(h).padStart(2, '0') + '</text>'; }).join('');
  // 中环：节律带（每半小时一个采样点，半径 98 → 118）+ 24 个小刻度
  const hc = new Array(24).fill(0); L.forEach((s) => { hc[s.h]++; });
  const hm2 = Math.max(1, ...hc);
  let ticks = ''; for (let h = 0; h < 24; h++) { const a = h / 24 * Math.PI * 2; ticks += 'M' + f(pt(C, 92, a)) + 'L' + f(pt(C, h % 6 ? 95 : 98, a)); }
  let band = ''; for (let i = 0; i < 48; i++) { const h = Math.floor(i / 2); const v = (i % 2 === 0 ? hc[h] : (hc[h] + hc[(h + 1) % 24]) / 2) / hm2; band += (i ? 'L' : 'M') + f(pt(C, 98 + v * 20, i / 48 * Math.PI * 2)); }
  band += 'Z'; let inner = ''; for (let i = 0; i < 48; i++) inner += (i ? 'L' : 'M') + f(pt(C, 98, i / 48 * Math.PI * 2));
  // 内盘：罗盘玫瑰。四个次角（45°）固定短；四个主角朝 D I M V，长度随强度；深色面与字母都按分值判定（强度 < 55 = 未定型：浅灰、「?」）
  const axes = ['D', 'I', 'M', 'V'];
  const av = axes.map((x, i) => axisView(p, i));
  const minor = [45, 135, 225, 315].map((d) => fpRosePt(d, RR * 0.4, RR * 0.1)).map((x) => '<g class="fp-minor"><path d="' + x[0] + '" fill="var(--ink-4)"/><path d="' + x[1] + '" fill="var(--line)" stroke="var(--ink-4)" stroke-width=".8" stroke-linejoin="round"/></g>').join('');
  const major = axes.map((x, i) => { const q = fpRosePt(AXR[x], fpRoseLen(av[i].strong), RR * 0.18), un = p.axes && p.axes[i] ? p.axes[i].letter === '?' : av[i].strong < 55, ink = un ? 'var(--ink-3)' : 'var(--ink-1)'; return '<g class="fp-pt" data-k="' + x + '"><path d="' + q[1] + '" fill="var(--surface)" stroke="' + ink + '" stroke-width="1.1" stroke-linejoin="round"/><path d="' + q[0] + '" fill="' + ink + '" stroke="' + ink + '" stroke-width="1.1" stroke-linejoin="round"/></g>'; }).join('');
  const lbl = axes.map((x, i) => {
    const a = av[i]; const sl = p.axes && p.axes[i] && p.axes[i].letter; const ch = sl ? sl : a.strong < 55 ? '?' : a.letter; const d = AXR[x], rad = d * Math.PI / 180, len = fpRoseLen(a.strong);
    const q = pt(C, len + 11 * k, rad);
    const sq = [q[0], q[1] + (d === 0 ? -13 : 13) * k];
    return '<g class="fp-ax" data-k="' + x + '"><text x="' + q[0].toFixed(1) + '" y="' + q[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="' + 15 * k + '" font-family="var(--serif)" font-weight="600" fill="' + (ch === '?' ? 'var(--ink-3)' : 'var(--ink-1)') + '" paint-order="stroke" stroke="var(--bg)" stroke-width="3">' + ch + '</text>' +
      (opt.labels && !sm ? '<text x="' + sq[0].toFixed(1) + '" y="' + sq[1].toFixed(1) + '" text-anchor="middle" dominant-baseline="central" font-size="' + 9 * k + '" font-family="var(--mono)" fill="var(--ink-3)" paint-order="stroke" stroke="var(--bg)" stroke-width="3">' + a.strong + '</text>' : '') + '</g>';
  }).join('');
  // 指针：细长双头菱形，北半 --orbit 实心、南半空心描边；--hd = 协作重心。画在玫瑰之上、字母与分数之下
  const hd = fpHeading(L); const NL = FPG.NL;
  const needle = '<g class="fp-compass"><g class="fp-needle" data-hd="' + hd.deg + '" style="--hd:' + hd.deg + 'deg"><title>协作重心 ' + hd.hm + '</title><g class="fp-nd"><path class="fp-nn" d="M200 ' + (C - NL) + 'L203.6 200L196.4 200Z" fill="var(--orbit)" stroke="var(--surface)" stroke-width="1" stroke-linejoin="round"/><path class="fp-ns" d="M200 ' + (C + NL) + 'L203.6 200L196.4 200Z" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="1.1" stroke-linejoin="round"/></g></g>' +
    '<circle cx="200" cy="200" r="7" fill="var(--surface)" stroke="var(--ink-1)" stroke-width="1.4"/><circle cx="200" cy="200" r="2" fill="var(--ink-1)"/></g>';
  const hub = (fpRoseLen(55) - 1).toFixed(1);
  return '<svg class="fp2" width="' + size + '" height="' + size + '" viewBox="0 0 400 400" role="img" aria-label="协作指纹：外框是 24 小时罗盘刻度；轨道环带按小时叠出各 Agent 的会话数，环带外缘的行星停在各 Agent 的协作重心；中环是节律带，内盘罗盘玫瑰的四个主角长度是四个维度的强度；指针指向协作重心 ' + hd.hm + '" style="overflow:visible;max-width:100%;height:auto">' +
    '<defs><mask id="' + uid + '" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="400"><circle class="fp-sweep" cx="200" cy="200" r="' + (R0 + RH / 2) + '" fill="none" stroke="#fff" stroke-width="' + (RH + 30) + '" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="0" transform="rotate(-90 200 200)"/></mask></defs>' +
    '<g class="fp-base"><circle cx="200" cy="200" r="198" fill="var(--surface)" stroke="var(--ink-2)" stroke-width="1.1"/><circle cx="200" cy="200" r="179.5" fill="none" stroke="var(--bg)" stroke-width="31"/><circle cx="200" cy="200" r="195" fill="none" stroke="var(--ink-3)" stroke-width=".6"/><circle cx="200" cy="200" r="164" fill="none" stroke="var(--line)"/>' +
    '<path class="fp-tk" d="' + tk[0] + '" stroke="var(--ink-4)" stroke-width=".8"/><path class="fp-tk" d="' + tk[1] + '" stroke="var(--ink-3)" stroke-width="1.1"/><path class="fp-tk" d="' + tk[2] + '" stroke="var(--ink-1)" stroke-width="1.6"/>' +
    '<path class="fp-n0" d="M200 3L194.5 -7L205.5 -7Z" fill="var(--orbit)"/>' +
    '<circle cx="200" cy="200" r="' + R0 + '" fill="none" stroke="var(--line)"/><circle cx="200" cy="200" r="' + FPG.PR + '" fill="none" stroke="var(--hair)" stroke-dasharray="2 3"/></g>' +
    '<g class="fp-hours">' + hrs + '</g>' +
    '<g class="fp-band"><path d="' + band + inner + '" fill="var(--h2)" fill-opacity=".7" fill-rule="evenodd"/><path d="' + ticks + '" stroke="var(--ink-3)" stroke-width="1"/></g>' +
    band5 + '<g class="ring">' + ring + '</g><g class="dots">' + dots + '</g>' + planets +
    '<g class="fp-core"><circle cx="200" cy="200" r="92" fill="var(--bg)" stroke="var(--line)"/><circle cx="200" cy="200" r="' + hub + '" fill="var(--sunken)" stroke="var(--hair)"/><circle cx="200" cy="200" r="' + RR + '" fill="none" stroke="var(--line)" stroke-dasharray="1.5 3"/>' +
    '<path d="M200 110V290M110 200H290" stroke="var(--line)" stroke-width=".8"/>' + minor + '</g>' +
    '<g class="fp-rose pet">' + major + '</g>' + needle + '<g class="fp-axl">' + lbl + '</g></svg>';
}
TIPS.fpp = (id) => { const F = CUR.fp; const x = F && F.pl.find((q) => q.a.id === id); if (!x) return ''; return '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + x.a.c + ';vertical-align:-1px"></span> <b>' + x.a.name + ' · 协作重心 ' + x.hm + ' · ' + x.n + ' 个会话</b>\n<span style="opacity:.75">该 Agent 会话开始时刻的圆形平均</span>'; };
TIPS.fph = (h) => { const F = CUR.fp; if (!F) return ''; const xs = F.byH[+h]; const by = AG.map((a) => [a, xs.filter((s) => s.a === a.id).length]).filter((x) => x[1]); return '<b>' + h + ':00–' + (+h + 1) + ':00 · ' + xs.length + ' 个会话</b>\n' + (by.length ? by.map((x) => '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + x[0].c + ';vertical-align:-1px"></span> ' + x[0].short + ' ' + x[1]).join(' · ') : '这个小时没有会话') + '\n<span style="opacity:.75">' + (S.persona.fpHour === +h ? '再点一次收起' : '点击展开这个小时的会话点') + '</span>'; };
// previous calendar month of a month period (null for 近 90 天 / 全部)
function pePrevKey(k) { const ks = peMonthKeys(); const i = ks.indexOf(k); return i > 0 ? ks[i - 1] : null; }
function peMonthLbl(k) { return LV.live ? k : '2026-0' + ({ jun: 6, jul: 7, aug: 8, sep: 9 })[k]; }
PAGES.persona = () => {
  if (!PERIODS[S.persona.period]) S.persona.period = '90';
  if (LV.live && S.persona.vs === 'pop') S.persona.vs = 'past';   // no population baseline in live (POP is a demo constant)
  const per = PERIODS[S.persona.period];
  const L = personaScope([per[0], per[1]]);
  // live: the full /v1/uiview/persona payload for this period (axes, evidence, traits, strengths, blind spots, months)
  const p = LV.live && L.length >= 30 && !lvHasUnits(L) ? LV.personaFor(S.persona.period, L) : persona(L);
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
    const frac = Math.min(1, L.length / 30); const a = frac * Math.PI * 2; const x = 56 + 46 * Math.sin(a), y = 56 - 46 * Math.cos(a);
    const relax = peRelax([per[0], per[1]]);
    return tbar('协作人格', filt + '基于 ' + L.length + ' 个会话 · ' + per[2], right) + '<div class="content" id="content"><div class="card pad pe-low"><svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true"><circle cx="56" cy="56" r="46" fill="none" stroke="var(--line)" stroke-width="10"/>' + (frac > 0 ? '<path d="M56 10 A46 46 0 ' + (frac > 0.5 ? 1 : 0) + ' 1 ' + x.toFixed(1) + ' ' + y.toFixed(1) + '" fill="none" stroke="var(--ink-1)" stroke-width="10" stroke-linecap="round"/>' : '') + '<text x="56" y="62" text-anchor="middle" font-size="18" font-weight="700" font-family="var(--mono)" fill="var(--ink-1)">' + L.length + '/30</text></svg><div class="col" style="flex:1;min-width:240px">' +
      (allOff ? '<h2 class="serif" style="margin:0;font-size:24px">所有数据源已停用</h2><p style="margin:0;color:var(--ink-2)">人格需要会话数据。到「设置 › 数据源」重新启用至少一个 Agent，分析会立即恢复。</p><div class="row"><button type="button" class="btn p" data-act="openSettings" data-tab="sources">打开设置 · 数据源</button></div>'
        : '<h2 class="serif" style="margin:0;font-size:24px">再积累 ' + (30 - L.length) + ' 个会话后揭晓</h2><p style="margin:0;color:var(--ink-2)">当前筛选下样本太少，人格需要足够的会话才可靠。' + (relax.length ? '放宽下面任一筛选可以补到：' : '可以放宽筛选，或换一个统计周期。') + '</p>' +
        (relax.length ? '<div class="pe-relax">' + relax.map((r) => '<button type="button" class="chip on" data-act="peRelax" data-k="' + r.k + '">' + esc(r.t) + ic('x', 12) + '<b class="mono" style="color:' + (r.n >= 30 ? 'var(--good)' : 'var(--ink-3)') + '">移除后 n≈' + r.n + '</b></button>').join('') + '</div>' : '') +
        '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn p" data-act="clearAllFilters">清除筛选</button><button type="button" class="btn" data-act="period" data-v="all">看全部历史</button></div>') +
      '</div></div></div>';
  }
  CUR.persona = p;
  const traits = [];
  if (LV.live) (p.traits || []).forEach((t) => traits.push(t));
  else if (p.v.D >= 55) traits.push('高吞吐'); else if (p.v.D <= 45) traits.push('亲自掌舵');
  if (p.v.I >= 55) traits.push('边做边想'); else if (p.v.I <= 45) traits.push('先规划');
  if (p.v.M >= 55) traits.push('多线程'); else if (p.v.M <= 45) traits.push('单线专注');
  if (p.v.V >= 55) traits.push('验收严格'); else if (p.v.V <= 45) traits.push('信任结果');
  if (!LV.live) traits.push('中英混用');
  const st = p.st || stats(L); if (p.avgS == null) Object.assign(p, { avgS: 0, avgA: 0 });
  const conts = LV.live && p.blind_spots ? p.blind_spots.map((b) => [b.type, b.n]) : Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const recFor = { '方向错误': 'deploy-target', '工具 / 环境失败': 'retry-breaker', '改动过度': 'paper-audit', '误解需求': 'acceptance', '并行会话冲突': 'worktree', '流程过重（子代理）': 'pr-wrapup', '额度 / 用量中断': 'summary-compact' };
  const fitRows = AG.map((a) => { const xs = L.filter((s) => s.a === a.id); const st2 = stats(xs); const f = fitOf(xs); const okp = st2.ok / 100; const ci = f == null ? null : Math.round(1.96 * Math.sqrt(okp * (1 - okp) / xs.length) * 100); return { a, n: xs.length, f, st: st2, ci, off: S.srcOff.has(a.id) }; });
  CUR.peMonths = months;
  const evos = [0, 1, 2, 3].map((i) => peEvidence(L, st, p, i));
  const metaFull = filt + '基于 ' + L.length + ' 个会话 · ' + new Set(L.map((s) => s.a)).size + ' 个 Agent · ' + per[2] + (note ? ' · ' + note : '');
  return tbar('协作人格', '<span title="' + esc(metaFull) + '">' + filt + L.length + ' 个会话 · ' + per[2] + '</span>', right) +
    '<div class="content" id="content"><div class="stack">' +
    '<div class="card persona-hero"><div class="col" style="gap:0;min-width:0"><div class="row" style="flex-wrap:wrap"><span class="eb" title="Your agent collaboration type">你的协作人格</span><span class="tag" data-tip="维度信号与权重是初版设想，待真实数据校准">实验性</span><span class="bdg">置信度 ' + p.conf + ' · n=' + p.n + '</span></div>' +
    '<div class="letters" data-hero="code">' + p.code.split('').map((ch, i) => { const a = axisView(p, i); return '<button type="button" data-act="axisJump" data-tf="axis|' + i + '"><span class="L">' + ch + '</span><span style="font-size:12px;color:var(--ink-2);white-space:nowrap">' + (ch === '?' ? '未定型' : a.name) + ' <span class="mono" style="color:var(--ink-1);font-weight:600">' + a.strong + '</span></span></button>'; }).join('') + '</div>' +
    '<div class="row" style="align-items:baseline;gap:12px;margin-top:16px;flex-wrap:wrap"><span class="serif" style="font-size:36px;line-height:1.1;font-weight:600">' + p.zh + '</span><span class="serif" style="font-size:24px;font-style:italic;color:var(--ink-3)">' + p.en + '</span></div>' +
    '<p class="pe-line"><span class="aib">' + ic('spark', 11) + 'AI 撰写</span>' + esc(p.line) + '<button type="button" class="btn sm gh" data-act="notMe">不像我？</button></p><div class="pe-facts mono"><span><b>' + f1(st.per) + '</b> 条消息 / 会话</span><span><b>' + f1(st.auto) + '</b> 步自主 / 轮</span><span><b>' + Math.round(st.verify) + '%</b> 要求验证</span></div>' +
    '<div class="row" style="flex-wrap:wrap;gap:6px;margin-top:12px">' + traits.map((t) => '<span class="tag">' + t + '</span>').join('') + '</div>' +
    (note ? '<div class="cap" style="margin-top:8px;font-size:11px" title="人格只按时间、Agent 与项目计算，和侧栏、报告一致">' + esc(note) + '</div>' : '') +
    // 演变：月份码 + 四轴折线（评审 A2-V06）
    '<div class="pe-evw"><div class="eb" style="margin-bottom:8px" title="按月重算，点击月份切换统计周期">演变 · 按月</div><div class="evo pe-evrow">' + months.map((m, i) => '<button type="button" data-act="period" data-v="' + m.k + '" class="' + (S.persona.period === m.k ? 'on' : '') + '"><span class="mono" style="display:block;font-size:10px;color:var(--ink-3)">' + m.lbl + '</span><span class="mono" style="display:block;font-size:14px;font-weight:700;letter-spacing:.06em">' + (m.p.ok ? m.p.code : '—') + '</span><span style="display:block;font-size:11px;color:var(--ink-2)">' + (m.p.ok ? m.p.zh : '样本不足') + '</span></button>' + (i < 3 ? ic('arrow', 12, 'color:var(--ink-4)') : '')).join('') + '</div>' +
    '<div class="vz pe-evo" data-vz="pe-evo"></div><div class="cap pe-foot" title="四个维度逐月的值；跨过中线 50 的月份，该位字母会变">中线 50 · 灰带 45–55 为未定型</div></div></div>' +
    '<div class="fp-wrap" data-hero="fp"><button type="button" class="btn sm gh" data-act="reveal" style="position:absolute;right:8px;top:8px;z-index:2">重播揭晓</button>' + '<div class="pe-fpc">' + fp2SVG(L, p, 400, { interactive: true, labels: true }) +
    '<div class="pe-fp-legend"><span class="row" style="gap:5px"><span style="width:10px;height:10px;background:var(--ink-1);clip-path:polygon(50% 0,100% 100%,50% 70%,0 100%)"></span>玫瑰 · 主角越长，该维度越强</span><span class="row" style="gap:5px"><span style="width:2px;height:12px;border-radius:1px;background:var(--orbit)"></span>指针 · 协作重心 <b class="mono">' + fpHeading(L).hm + '</b></span><span class="row" style="gap:5px"><span style="width:10px;height:5px;border-radius:2px;background:var(--h2)"></span>中环 · 24 小时节律</span><span class="row" style="gap:5px"><span style="width:14px;height:6px;border-radius:3px;background:linear-gradient(90deg,var(--a1),var(--a2),var(--a3))"></span>轨道 · 每小时会话数，按 Agent 分层（峰值 ' + CUR.fp.mxH + '）· ' + (S.persona.fpHour != null ? '<button type="button" class="lnk" data-act="fpHour" data-h="' + S.persona.fpHour + '">收起 ' + S.persona.fpHour + ' 时</button>' : '点击展开') + '</span><span class="row" style="gap:5px"><span class="dot" style="background:var(--a1)"></span>行星 · 各 Agent 的协作重心</span></div></div></div></div>' +
    '<div class="three pe-three" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr) minmax(0,1fr)">' +
    '<div class="card pad" id="axesCard"><div class="hd"><div class="grow"><span class="ct">四个维度</span></div><div class="seg" role="group" aria-label="对照组"><button type="button" data-act="vs" data-v="past" class="' + (S.persona.vs === 'past' ? 'on' : '') + '">与过去的我</button>' + (LV.live ? '' : '<button type="button" data-act="vs" data-v="pop" class="' + (S.persona.vs === 'pop' ? 'on' : '') + '">与全体用户</button>') + '</div></div>' +
    '<div class="vz" data-vz="pe-axes"></div>' +
    '<div class="pe-ev">' + evos.map((e, i) => { const a = axisView(p, i); return '<div class="pe-evi" title="' + esc(e.lbl) + '"><span class="row" style="justify-content:space-between;gap:6px"><span class="mono pe-evl">' + a.ax.dim + ' · ' + a.letter + '</span>' + VZ.spark(e.vals, { bars: true, w: 72, h: 20, color: 'var(--h3)', last: 'var(--h3)', label: e.lbl }) + '</span><span class="pe-evt">' + esc(e.txt) + '</span></div>'; }).join('') + '</div>' +
    '<div class="cap pe-foot" title="中线为 50；落在 45–55（灰带）记为未定型">细刻度 = ' + (S.persona.vs === 'pop' ? '全体用户均值（示例）' : prev && prev.ok ? '上个月' : '无可比时段') + ' · 灰带为未定型</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">优势与盲点</span></div></div><div class="col pe-sw">' +
    (LV.live ? (p.strengths || []).map((x) => [x.text, '强度 ' + x.strong + ' · n=' + x.n_units, true]) : [['整段委托', '每轮自主 ' + f1(st.auto) + ' 步', p.v.D >= 55], ['验收严格', Math.round(st.verify) + '% 要求验证', p.v.V >= 55], ['节奏稳定', '日均 ' + f1(p.avgS) + ' 个会话', true]]).filter((x) => x[2]).map((x) => '<div class="pe-swr">' + ic('okc', 14, 'color:var(--good)') + '<b>' + x[0] + '</b><span class="m">' + x[1] + '</span></div>').join('') +
    '<div class="pe-swsep"></div>' +
    (conts.length ? conts.map((c) => '<div class="pe-swr">' + ic('alert', 14, 'color:var(--crit)') + '<b title="' + esc(c[0]) + '">' + c[0] + '</b><span class="m">出现在 ' + c[1] + ' 个会话</span>' + (LV.live ? '<button type="button" class="lnk" data-act="go" data-r="recs">建议 →</button>' : '<button type="button" class="lnk" data-act="openRec" data-id="' + recFor[c[0]] + '">建议 →</button>') + '</div>').join('') : '<span class="cap">这段时间没有明显盲点。</span>') + '</div></div>' +
    // 契合度：中性条 + 透明度随 n + 95% 区间（评审 A2-V07）；来源停用的 Agent 不可点（BUG-49）
    '<div class="card pad"><div class="pe-fit-h"><span class="ct">与 Agent 的契合度</span><span class="cap">0–100 · 细线为 95% 区间</span></div><div class="col" style="gap:12px">' +
    fitRows.map((r) => '<' + (r.off || !r.n ? 'div' : 'button type="button" data-act="soloAgent" data-a="' + r.a.id + '"') + ' class="pe-fit' + (r.off ? ' off' : '') + '"><span class="row pe-fit-t"><span class="dot" style="background:' + r.a.c + '"></span><span style="flex:1">' + r.a.name + '</span>' + (r.off ? '<span class="cap" style="font-size:11px">来源已停用</span>' : '<b class="mono">' + (r.f == null ? '—' : r.f) + '</b>') + '</span><span class="pe-fit-bar" style="opacity:' + (r.n < 20 ? 0.5 : 1) + '"><span class="fill" style="width:' + (r.f || 0) + '%"></span>' + (r.ci != null ? '<span class="ci" style="left:' + Math.max(0, r.f - r.ci) + '%;width:' + Math.min(100 - Math.max(0, r.f - r.ci), r.ci * 2) + '%"></span>' : '') + '</span><span class="pe-fit-m">' + (r.off ? '到设置里重新启用后参与计算' : r.n < 5 ? '样本少（' + r.n + ' 个会话），不计分' : '<span class="nw" title="n=' + r.n + (r.n < 20 ? '（样本少）' : '') + ' · 95% 区间 ±' + r.ci + ' · 完成率 ' + Math.round(r.st.ok) + '% · 摩擦率 ' + f1(r.st.fric) + '%">n=' + r.n + ' ±' + r.ci + ' · 完成 ' + Math.round(r.st.ok) + '% · 摩擦 ' + f1(r.st.fric) + '%</span>') + '</span></' + (r.off || !r.n ? 'div' : 'button') + '>').join('') +
    '</div><div class="cap pe-foot" title="契合度综合完成率与摩擦率；条越淡，样本越少（n < 20）">条越淡样本越少 · 点击只看该 Agent</div></div>' +
    '</div></div></div>';
};
PAGES.persona.after = () => {
  const p = CUR.persona; if (!p || !$('[data-vz="pe-axes"]')) return;
  const prevKey = pePrevKey(S.persona.period);
  const prev = prevKey ? persona(personaScope([PERIODS[prevKey][0], PERIODS[prevKey][1]])) : null;
  VZ.mount('pe-axes', { type: 'diverging', title: '协作人格 · 四个维度', rows: peAxisRows(p, prev), domain: [-1, 1], colors: ['var(--ink-2)', 'var(--ink-2)'], deadband: [-0.1, 0.1], format: peNum, refLabel: S.persona.vs === 'pop' ? '全体用户（示例）' : '上月', axis: false, rowH: 34, barH: 10, legend: false, animate: false, onSelect: () => ACT.axisJump() });
  const months = CUR.peMonths || [];
  VZ.mount('pe-evo', { type: 'line', title: '四个维度 · 逐月', height: 150, legend: 'top', animate: false, points: true, endLabels: false, x: { values: months.map((m) => m.lbl.slice(5) + ' 月') }, y: { min: 0, max: 100, format: 'int', ticks: 4 }, refs: [{ y: 55, color: 'var(--line)' }, { y: 50 }, { y: 45, color: 'var(--line)' }],
    series: [['D', '自主 D', 'var(--ink-1)', false], ['I', '结构 I', 'var(--ink-2)', true], ['M', '并发 M', 'var(--ink-3)', false], ['V', '求证 V', 'var(--h3)', true]].map((k) => ({ name: k[1], color: k[2], dash: k[3], values: months.map((m) => m.p.ok ? Math.round(m.p.v[k[0]]) : null) })) });
};
TIPS.axis = (i) => { const p = CUR.persona; if (!p) return ''; const a = axisView(p, +i); return '<b>' + a.ax.dim + '：' + a.ax.L + ' ' + a.ax.Ln + ' ↔ ' + a.ax.R + ' ' + a.ax.Rn + '</b>\n' + a.ax.q + '\n<span style="opacity:.8">信号：' + a.ax.sig + '</span>'; };
Object.assign(ACT, {
  period: (el) => { S.persona.period = el.dataset.v; S.persona.fpHour = null; render(); },
  vs: (el) => { S.persona.vs = el.dataset.v; render(); },
  fpHour: (el) => { const h = +el.dataset.h; S.persona.fpHour = S.persona.fpHour === h ? null : h; tipOff(); render(); },
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
// 进入画像页（Advance persona / Lite l-persona）：指针做一次阻尼晃动后定位到协作重心，轨道环带随扫描遮罩从 00 顺时针展开（0.9 s），
// 行星从 00 出发沿轨道运行到各自的协作重心（1.2 s，彼此错开 60 ms）。Genesis 落地时（overlay 仍开着）都不播，
// 免得飞入的表盘与页面对不上。减少动态效果时静止。
function fpWobble(svg) {
  const nd = svg && svg.querySelector('.fp-nd'); if (!nd || !nd.animate || reduceMotion()) return null;
  return nd.animate([-40, 24, -12, 6, -2, 0].map((d) => ({ transform: 'rotate(' + d + 'deg)' })), { duration: 1400, easing: 'cubic-bezier(.37,0,.63,1)' });
}
function fpOrbitIn(svg) {
  if (!svg || reduceMotion()) return [];
  const out = [], sw = svg.querySelector('.fp-sweep');
  if (sw && sw.animate) out.push(sw.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 900, easing: 'cubic-bezier(.45,.05,.35,1)' }));
  svg.querySelectorAll('.fp-pl').forEach((el, i) => { if (el.animate) out.push(el.animate([{ transform: 'rotate(0deg)', opacity: 0 }, { opacity: 1, offset: 0.12 }, { transform: 'rotate(' + el.dataset.pa + 'deg)', opacity: 1 }], { duration: 1200, delay: i * 60, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'backwards' })); });
  return out;
}
RENDER_HOOKS.push((m, entered) => { if (entered && !OVL) { const svg = m.querySelector('svg.fp2'); fpWobble(svg); fpOrbitIn(svg); } });

// live reveal: GET /v1/uiview/persona/reveal for the shown scope first; a settled code plays the same compass / genesis reveal
// on the real rows (openReveal → persona(L) → personaLive), an unsettled one says which candidates are closest instead of a fake reveal
function peLiveReveal() {
  const period = S.route === 'persona' ? S.persona.period : ({ 7: '7', 30: '30', 90: '90', 0: 'all' })[S.range];
  const e = LV.reveal(period); const go2 = () => {
    const d = e.data;
    if (!d) { toast(e.state === 'error' ? '揭晓数据暂不可用' : '正在准备揭晓…'); return; }
    if (!d.ok) { toast('样本不足（' + d.n + ' 个会话，少于 ' + ((d.low && d.low.need) || 30) + ' 个），暂时不能揭晓'); return; }
    if (!d.classified) { const c = (d.candidates || [])[0]; toast('部分维度尚未定型，暂时不能揭晓' + (c ? ' · 最接近 ' + c.code + ' ' + c.zh + ' ' + Math.round(c.match) + '%' : '')); return; }
    openReveal(S.route === 'persona' ? { L: personaScope([PERIODS[period][0], PERIODS[period][1]]) } : undefined);
  };
  if (e.data || e.state === 'error') go2(); else { const t0 = Date.now(); const iv = setInterval(() => { if (e.data || e.state === 'error' || Date.now() - t0 > 8000) { clearInterval(iv); go2(); } }, 100); }
}
