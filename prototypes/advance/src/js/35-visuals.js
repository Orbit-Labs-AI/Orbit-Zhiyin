/* ============ shared visuals ============ */
const agent = (id) => AGI[id] || { id, name: id, short: id, c: 'var(--a0)', t: 'var(--a0t)' };   // live: an id the spine does not carry
const CUR = {};
const OUT = { ok: ['okc', 'var(--good)', '完成'], part: ['half', 'var(--warn)', '部分完成'], fail: ['xc', 'var(--crit)', '放弃'], live: ['clock', 'var(--a1)', '运行中'] };
function spark(arr, w, h) {
  w = w || 64; h = h || 22;
  const mn = Math.min(...arr), mx = Math.max(...arr);
  const pts = arr.map((v, i) => [2 + i * ((w - 4) / Math.max(1, arr.length - 1)), 2 + (1 - (v - mn) / ((mx - mn) || 1)) * (h - 4)]);
  const last = pts[pts.length - 1];
  return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true" style="overflow:visible;flex:none"><path d="M' + pts.map((p) => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' L') + '" fill="none" stroke="var(--ink-4)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/><circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '" r="2.5" fill="var(--ink-1)" stroke="var(--surface)" stroke-width="1.5"/></svg>';
}
function weekly(fn, endDay, n) { const out = []; for (let k = n - 1; k >= 0; k--) { const b = endDay - k * 7, a = b - 6; out.push(fn(ALL.filter((s) => s.d >= a && s.d <= b && pass(s, { noExtra: true })))); } return out; }
const pt = (C, r, a) => [C + r * Math.sin(a), C - r * Math.cos(a)];
// 协作人格的花：16 型各一朵，延续分享卡 4/8 花的做法：平涂、两色、几何、安静。每朵最多 6 片瓣，区别主要在瓣形与排布。
// 领瓣（--orbit）的瓣尖朝 0°（12 点），调用方整体旋转让它指向类型；其余瓣墨色 / 浅灰两色（浅灰在后排、略短）。
// 字母约定：多线 M 5–6 瓣 / 专注 F 3–4 瓣；即兴 I 瓣弯、旋开 / 规划 P 瓣直、对齐；委托 D 瓣长、小花心 / 掌舵 S 瓣短而宽、大花心；
// 求证 V 花心是一圈环 + 中心点 / 信任 T 是实心圆点。
//   总设计师  六片菱形瓣均匀展开，规整如蓝图           调度官    五片细长剑瓣放射，放手并行
//   监制      三片水滴瓣合成一只杯，一次只开一朵       策划人    笔尖领瓣（写好任务书）+ 两片直瓣
//   指挥家    五瓣都向领瓣弯拢，齐头并进               冲浪者    五片月牙瓣旋成浪卷
//   探路者    箭头领瓣在前，两片弯翼在后               远航者    三片帆瓣，一片花瓣随风飘远（意外之喜）
//   飞控官    六片圆角方瓣围着大环心，像仪表盘         杂技师    五片圆瓣，领瓣那颗被抛离花心
//   分析学家  四片凹口瓣十字对称，先想清楚再动手       领航员    四角罗盘星，领瓣是长针
//   实验家    五片瓣各一种形状（几种做法）             即兴乐手  三对一长一短的瓣，两两呼应
//   雕刻师    四片削切的多边形瓣 + 一粒碎屑            同行者    两片大瓣并肩（结对）+ 一片小瓣
// 比例随强度微调（委托强度 → 瓣长，即兴强度 → 弯度）。字母取 p.axes 的结论（live 里未定的轴按分值取一极），没有时按分值以 50 为界取一极。
const BLOOM_K = ['D', 'I', 'M', 'V'];
// 一片花瓣：a 角度（°），l 瓣尖半径，w 半宽（都以 R 为单位；负值左右镜像），s 形状，t 层（f 墨色 / b 浅灰 / L 领瓣），o：tw 弯度°、r0 起点半径
const BP = (a, l, w, s, t, o) => Object.assign({ a, l, w, s: s || 'almond', t: t || 'f' }, o);
const bRing = (n, off, fn) => Array.from({ length: n }, (_, i) => fn(off + i * 360 / n, i));
const BLOOMS = {
  DPMV: { p: bRing(6, 0, (a, i) => BP(a, i % 2 ? 0.7 : 1, i % 2 ? 0.14 : 0.18, 'kite', i ? (i % 2 ? 'b' : 'f') : 'L')) },
  DPMT: { p: [BP(144, 0.78, 0.085, 'blade', 'b'), BP(216, 0.78, 0.085, 'blade', 'b'), BP(72, 0.94, 0.095, 'blade'), BP(288, 0.94, 0.095, 'blade'), BP(0, 1, 0.095, 'blade', 'L')] },
  DPFV: { p: [BP(180, 0.56, 0.11, 'almond', 'b'), BP(-40, 0.8, 0.22, 'drop'), BP(40, 0.8, 0.22, 'drop'), BP(0, 0.96, 0.24, 'drop', 'L')] },
  DPFT: { p: [BP(180, 0.56, 0.11, 'almond', 'b'), BP(120, 0.8, 0.16), BP(240, 0.8, 0.16), BP(0, 1, 0.17, 'nib', 'L')] },
  DIMV: { p: [BP(-132, 0.74, 0.15, 'almond', 'b', { tw: 12 }), BP(132, 0.74, 0.15, 'almond', 'b', { tw: -12 }), BP(-64, 0.92, 0.18, 'almond', 'f', { tw: 12 }), BP(64, 0.92, 0.18, 'almond', 'f', { tw: -12 }), BP(0, 1, 0.18, 'almond', 'L')] },
  DIMT: { p: bRing(5, 0, (a, i) => BP(a, i % 2 ? 0.82 : 0.96, 0.14, 'moon', i ? (i % 2 ? 'b' : 'f') : 'L', { tw: 46 })) },
  DIFV: { p: [BP(150, 0.72, 0.17, 'sail', 'f', { tw: 18 }), BP(210, 0.72, -0.17, 'sail', 'f', { tw: -18 }), BP(0, 1, 0.21, 'arrow', 'L')] },
  DIFT: { p: [BP(240, 0.82, 0.2, 'sail', 'b', { tw: 22 }), BP(120, 0.9, 0.22, 'sail', 'f', { tw: 22 }), BP(0, 0.98, 0.22, 'sail', 'L', { tw: 22 }), BP(176, 0.94, 0.08, 'drop', 'b', { r0: 0.72 })] },
  SPMV: { p: bRing(6, 0, (a, i) => BP(a, i % 2 ? 0.7 : 0.86, i % 2 ? 0.13 : 0.15, 'square', i ? (i % 2 ? 'b' : 'f') : 'L')) },
  SPMT: { p: [...bRing(4, 72, (a, i) => BP(a, 0.7, 0.25, 'ball', i === 1 || i === 2 ? 'b' : 'f')), BP(0, 1.02, 0.15, 'ball', 'L', { r0: 0.72 })] },
  SPFV: { p: [BP(90, 0.68, 0.2, 'heart', 'b'), BP(270, 0.68, 0.2, 'heart', 'b'), BP(180, 0.8, 0.22, 'heart'), BP(0, 0.88, 0.23, 'heart', 'L')] },
  SPFT: { p: [BP(90, 0.6, 0.13, 'kite', 'b'), BP(270, 0.6, 0.13, 'kite', 'b'), BP(180, 0.66, 0.14, 'kite'), BP(0, 1, 0.15, 'kite', 'L')] },
  SIMV: { p: [BP(144, 0.64, 0.17, 'ball', 'b', { tw: 10 }), BP(288, 0.76, 0.17, 'heart', 'b', { tw: 10 }), BP(72, 0.82, 0.16, 'kite', 'f', { tw: 10 }), BP(216, 0.78, 0.14, 'square', 'f', { tw: 10 }), BP(0, 0.94, 0.17, 'drop', 'L', { tw: 10 })] },
  SIMT: { p: [0, 120, 240].flatMap((a) => [BP(a + 34, 0.64, 0.12, 'drop', 'b', { tw: 18 }), BP(a, 0.86, 0.15, 'drop', a ? 'f' : 'L', { tw: 18 })]) },
  SIFV: { p: [BP(180, 0.72, 0.19, 'facet', 'b', { tw: 8 }), BP(90, 0.8, 0.2, 'facet', 'f', { tw: 8 }), BP(270, 0.8, 0.2, 'facet', 'f', { tw: 8 }), BP(0, 0.95, 0.21, 'facet', 'L', { tw: 8 })],
    dt: [[46, 0.94, 0.035, 'f']] },
  SIFT: { p: [BP(208, 0.62, 0.15, 'drop', 'b'), BP(56, 0.9, -0.25, 'drop', 'f', { tw: -12 }), BP(0, 0.9, 0.25, 'drop', 'L', { tw: 12 })] }
};
function bloomCode(p) { return BLOOM_K.map((k, i) => { const l = p.axes && p.axes[i] && p.axes[i].letter; return l && l !== '?' ? l : axisView(p, i).letter; }).join(''); }
// 一片花瓣（瓣轴坐标：x 横向、y 径向，r0 → L，半宽 w）；点经 P 转到角度并随旋卷弯曲
function bloomPetal(shape, P, r0, L, w) {
  const h = L - r0, y = (t) => r0 + t * h, k = 0.5523;
  const M = (pts) => 'M' + pts.map((q) => P(q[0], q[1])).join('L') + 'Z';
  const C = (p0, segs) => 'M' + P(p0[0], p0[1]) + segs.map((sg) => 'C' + sg.map((q) => P(q[0], q[1])).join(' ')).join('') + 'Z';
  const mirror = (p0, segs) => C(p0, segs.concat(segs.slice().reverse().map((sg, i, arr) => { const prev = i + 1 < arr.length ? arr[i + 1][2] : p0; return [[-sg[1][0], sg[1][1]], [-sg[0][0], sg[0][1]], [-prev[0], prev[1]]]; })));
  const circ = (c) => C([0, c - w], [[[w * k, c - w], [w, c - w * k], [w, c]], [[w, c + w * k], [w * k, c + w], [0, c + w]], [[-w * k, c + w], [-w, c + w * k], [-w, c]], [[-w, c - w * k], [-w * k, c - w], [0, c - w]]]);
  switch (shape) {
    case 'kite': return M([[0, r0], [w, y(0.42)], [0, L], [-w, y(0.42)]]);
    case 'arrow': return M([[0, r0], [w * 0.22, y(0.46)], [w, y(0.5)], [0, L], [-w, y(0.5)], [-w * 0.22, y(0.46)]]);
    case 'nib': return M([[-w * 0.5, y(0.04)], [w * 0.5, y(0.04)], [w, y(0.5)], [0, L], [-w, y(0.5)]]);
    case 'facet': return M([[0, r0], [w, y(0.36)], [w * 0.64, y(0.94)], [-w * 0.24, L], [-w * 0.96, y(0.6)]]);
    case 'square': { const y0 = y(0.22), r = w * 0.45; return 'M' + P(-w + r, y0) + 'L' + P(w - r, y0) + 'Q' + P(w, y0) + ' ' + P(w, y0 + r) + 'L' + P(w, L - r) + 'Q' + P(w, L) + ' ' + P(w - r, L) + 'L' + P(-w + r, L) + 'Q' + P(-w, L) + ' ' + P(-w, L - r) + 'L' + P(-w, y0 + r) + 'Q' + P(-w, y0) + ' ' + P(-w + r, y0) + 'Z'; }
    case 'ball': return circ((r0 + L) / 2);
    case 'heart': return mirror([0, r0], [[[w * 1.1, y(0.24)], [w * 1.16, L], [w * 0.5, L]], [[w * 0.2, L], [0, y(0.9)], [0, y(0.86)]]]);
    case 'moon': return C([0, r0], [[[w * 1.6, y(0.3)], [w * 1.2, y(0.95)], [0, L]], [[-w * 0.2, y(0.7)], [-w * 0.5, y(0.3)], [0, r0]]]);
    case 'sail': return C([0, r0], [[[w * 1.5, y(0.22)], [w * 1.25, y(0.8)], [0, L]], [[-w * 0.1, y(0.7)], [-w * 0.2, y(0.3)], [0, r0]]]);
    case 'blade': return mirror([0, r0], [[[w, y(0.12)], [w * 0.9, y(0.55)], [0, L]]]);
    case 'drop': return mirror([0, r0], [[[w * 1.2, y(0.34)], [w * 0.86, L], [0, L]]]);
    default: return mirror([0, r0], [[[w * 1.15, y(0.3)], [w * 0.62, y(0.84)], [0, L]]]);   // almond
  }
}
// 返回：back 后排（浅灰）、major 前排（墨色）、lead 领瓣、st 花蕊线（描边）、dotF / dotB 圆点（墨色 / 浅灰）、hr 花心半径、ring 是否环形花心
function bloom(p, C, R) {
  const av = BLOOM_K.map((k, i) => axisView(p, i)), u = (i) => clamp((av[i].strong - 50) / 35, 0, 1);
  const code = bloomCode(p), sp = BLOOMS[code] || BLOOMS.DIMV, D = code[0] === 'D', V = code[3] === 'V';
  const hr = sp.hr || (D ? 0.09 : 0.16), k = 0.93 + 0.07 * u(0), tk = 0.7 + 0.6 * u(1), f = (v) => v.toFixed(1), rad = Math.PI / 180;
  const at = (c) => (c ? [Math.sin(c[0] * rad) * c[1], -Math.cos(c[0] * rad) * c[1]] : [0, 0]);
  const dot = (a, r, s) => { const x = C + R * r * Math.sin(a * rad), yy = C - R * r * Math.cos(a * rad), q = R * s; return 'M' + f(x - q) + ' ' + f(yy) + 'a' + f(q) + ' ' + f(q) + ' 0 1 0 ' + f(2 * q) + ' 0a' + f(q) + ' ' + f(q) + ' 0 1 0 ' + f(-2 * q) + ' 0Z'; };
  const out = { back: '', major: '', lead: '', st: '', dotF: '', dotB: '' };
  sp.p.forEach((q) => {
    const tw = (q.tw || 0) * tk * rad, o = at(q.c), r0 = q.r0 != null ? q.r0 : q.c ? 0.03 : hr * 0.92, L = q.c ? q.l : Math.max(r0 + 0.05, q.l * k), th = q.a * rad - tw;
    const P = (x, y) => { const a = th + tw * Math.pow(clamp((y - r0) / (L - r0), 0, 1.1), 1.3); return f(C + R * (o[0] + y * Math.sin(a) + x * Math.cos(a))) + ' ' + f(C + R * (o[1] - y * Math.cos(a) + x * Math.sin(a))); };
    out[q.t === 'L' ? 'lead' : q.t === 'b' ? 'back' : 'major'] += bloomPetal(q.s, P, r0, L, q.w);
  });
  (sp.st || []).forEach((q) => { const a = q[0] * rad, r1 = hr * 1.05, r2 = q[1] * (q[2] === 0 ? 1 : k); out.st += 'M' + f(C + R * r1 * Math.sin(a)) + ' ' + f(C - R * r1 * Math.cos(a)) + 'L' + f(C + R * r2 * Math.sin(a)) + ' ' + f(C - R * r2 * Math.cos(a)); if (q[2] !== 0) out.dotF += dot(q[0], r2, 0.028); });
  (sp.dt || []).forEach((q) => { out[q[3] === 'b' ? 'dotB' : 'dotF'] += dot(q[0], q[1] * (q[3] === 'b' ? 1 : k), q[2]); });
  return Object.assign(out, { minor: out.back, hr: hr * R, ring: V, n: sp.p.length, code, sw: Math.max(0.6, R * 0.012) });
}
// 花心：求证 V 是一圈环（底色填充）+ 中心点，信任 T 是实心圆点；sw = 线宽
function bloomHeart(g, cx, cy, ink, bg, sw) {
  return g.ring ? '<circle cx="' + cx + '" cy="' + cy + '" r="' + g.hr.toFixed(1) + '" fill="' + bg + '" stroke="' + ink + '" stroke-width="' + sw + '"/><circle cx="' + cx + '" cy="' + cy + '" r="' + (sw * 1.3).toFixed(1) + '" fill="' + ink + '"/>'
    : '<circle cx="' + cx + '" cy="' + cy + '" r="' + (g.hr * 0.62).toFixed(1) + '" fill="' + ink + '"/>';
}
// 一朵花的图层：back 后排（浅灰）、front 领瓣 → 前排 → 花蕊 → 圆点、heart 花心；ink / gray / lead / bg 是颜色，hw 是花心线宽
function bloomParts(g, cx, cy, c) {
  return { back: g.back ? '<path class="fp-bk" d="' + g.back + '" fill="' + c.gray + '"/>' : '',
    front: '<path class="fp-lead" d="' + g.lead + '" fill="' + c.lead + '"/><path class="fp-pet" d="' + g.major + '" fill="' + c.ink + '"/>' +
      (g.st ? '<path class="fp-st" d="' + g.st + '" fill="none" stroke="' + c.ink + '" stroke-width="' + g.sw.toFixed(2) + '" stroke-linecap="round"/>' : '') + (g.dotF ? '<path class="fp-dt" d="' + g.dotF + '" fill="' + c.ink + '"/>' : '') + (g.dotB ? '<path class="fp-dt" d="' + g.dotB + '" fill="' + c.gray + '"/>' : ''),
    heart: bloomHeart(g, cx, cy, c.ink, c.bg, c.hw || 1.6) };
}
function bloomLayers(g, cx, cy, c) { const q = bloomParts(g, cx, cy, c); return q.back + q.front + q.heart; }
// 一个类型的代表花（算法说明的 16 型表）：四个维度都取该极、强度 72
const typeP = (code) => ({ v: { D: code[0] === 'D' ? 72 : 28, I: code[1] === 'I' ? 72 : 28, M: code[2] === 'M' ? 72 : 28, V: code[3] === 'V' ? 72 : 28 } });
// 小尺寸花（菜单栏、小组件、分享卡，80 视框）：领瓣并入墨色
function bloomGlyph(p) { const g = bloom(p, 40, 36); return Object.assign(g, { hr: +g.hr.toFixed(1), major: g.lead + g.major }); }
function glyphSVG(p, size) {
  const g = bloom(p, 40, 36);
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 80 80" aria-hidden="true" data-bloom="' + bloomCode(p) + '">' + bloomLayers(g, 40, 40, { ink: 'var(--ink-1)', gray: 'var(--h3)', lead: 'var(--ink-1)', bg: 'none', hw: 2 }) + '</svg>';
}
TIPS.sess = (id) => { const s = BYID[id]; if (!s) return ''; return '<b>' + esc(s.title) + '</b>\n<span class="mono" style="opacity:.8;font-size:11px">' + agent(s.a).name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + dur(s.dur) + '</span>'; };
TIPS.def = (k) => ({ n: '会话数：所选范围内开始的会话。', h: '协作时长：会话从第一条消息到最后一次 Agent 输出的时间之和。', m: '你发出的消息：只计你本人输入，不含 Agent 回复。', a: '自主比 = Agent 步数 ÷ 你的消息数。\nAgent 步数 = 工具调用 + 文字回复。', f: '摩擦率 = 纠偏与不满消息 ÷ 你的消息数。\n分类由本地 Agent 判定。' })[k];

