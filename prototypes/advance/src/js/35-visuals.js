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
// 协作人格的花：16 型各一朵，形状对应 05-data.js 里该型的名称与描述（不是四个维度的拼装）；不求中心对称，前后两层、
// 有的带花蕊或飘出的花瓣。领瓣（石板色）的瓣尖朝 0°（12 点），调用方整体旋转让它指向类型；其余前排是墨色、后排是浅灰。
//   总设计师  莲座：前后两层尖瓣左右对称地展开，井井有条的蓝图     调度官    放射的细长花丝，梢头带种子（放手并行，源源不断）
//   监制      郁金香杯：一次只开一朵，两片叶托着                 策划人    鸢尾：一片关键大瓣，两侧垂瓣把任务递出去
//   指挥家    同向扫开的七瓣，前长后短（齐头并进）               冲浪者    长短不一的浪卷
//   探路者    箭头领瓣 + 两根触须，身后短瓣                      远航者    几片帆，一片花瓣随风飘远（意外之喜）
//   飞控官    大花心的雷达：一圈短方瓣，扫向领瓣的那一段渐长     杂技师    托起的花杯 + 空中三颗球
//   分析学家  黄金角螺旋，一步步长大的花瓣                       领航员    罗盘星：长针领瓣与一串航点
//   实验家    每瓣一种形状（几种做法）                           即兴乐手  长短交替的旋瓣与音符
//   雕刻师    削切的多边形瓣与飞出的碎屑                         同行者    并蒂：一根茎上的两朵小花
// 花心沿用两条约定：委托 D 小花心 / 掌舵 S 大花心；求证 V 是一圈环 + 中心点 / 信任 T 是实心圆点。比例随强度微调（委托强度 → 瓣长，即兴强度 → 旋卷）。
// 字母取 p.axes 的结论（live 里未定的轴按分值取一极），没有时按分值以 50 为界取一极。
const BLOOM_K = ['D', 'I', 'M', 'V'];
// 一片花瓣：a 角度（°），l 瓣尖半径，w 半宽（都以 R 为单位），s 形状，t 层（f 前排 / b 后排 / L 领瓣），o：tw 旋卷°、r0 起点半径、c 子花心 [角度, 半径]
const BP = (a, l, w, s, t, o) => Object.assign({ a, l, w, s: s || 'almond', t: t || 'f' }, o);
const bRing = (n, off, fn) => Array.from({ length: n }, (_, i) => fn(off + i * 360 / n, i));
const bCos = (a) => (1 + Math.cos(a * Math.PI / 180)) / 2;
const BLOOMS = {
  DPMV: { p: [...[-52, -17, 17, 52].map((a, i) => BP(a, [0.76, 0.93, 0.93, 0.76][i], 0.12, 'almond', 'b')), ...[148, 180, 212].map((a, i) => BP(a, [0.46, 0.52, 0.46][i], 0.1, 'drop', 'b')),
    ...[-70, -35, 35, 70].map((a, i) => BP(a, [0.64, 0.84, 0.84, 0.64][i], 0.13)), BP(0, 1, 0.14, 'almond', 'L')] },
  DPMT: { p: [...bRing(11, 0, (a, i) => BP(a, 0.4 + 0.5 * Math.pow(bCos(a), 1.3), 0.042, 'almond', i ? 'f' : 'L')), ...bRing(11, 16.36, (a) => BP(a, 0.3 + 0.24 * bCos(a), 0.036, 'almond', 'b'))],
    dt: bRing(11, 0, (a) => [a, 0.47 + 0.5 * Math.pow(bCos(a), 1.3), 0.03, 'f']) },
  DPFV: { p: [BP(-18, 0.86, 0.17, 'drop', 'b'), BP(18, 0.86, 0.17, 'drop', 'b'), BP(156, 0.66, 0.09, 'almond', 'b'), BP(204, 0.52, 0.09, 'almond', 'b'),
    BP(-36, 0.74, 0.19, 'drop'), BP(36, 0.74, 0.19, 'drop'), BP(0, 0.9, 0.2, 'drop', 'L')] },
  DPFT: { p: [BP(54, 0.68, 0.07, 'almond', 'b'), BP(306, 0.62, 0.07, 'almond', 'b'), BP(180, 0.42, 0.09, 'drop', 'b'),
    BP(126, 0.8, 0.19, 'drop', 'f', { tw: 30 }), BP(234, 0.76, 0.19, 'drop', 'f', { tw: -24 }), BP(0, 1, 0.22, 'drop', 'L')], st: [[24, 0.7], [-24, 0.62]] },
  DIMV: { p: [...bRing(7, 25.7, (a) => BP(a, 0.6, 0.12, 'drop', 'b', { tw: 18 })), ...bRing(7, 0, (a, i) => BP(a, [1, 0.84, 0.72, 0.64, 0.64, 0.72, 0.84][i], 0.15, 'drop', i ? 'f' : 'L', { tw: 18 }))] },
  DIMT: { p: [...bRing(6, 30, (a, i) => BP(a, [0.5, 0.62, 0.48, 0.6, 0.46, 0.56][i], 0.08, 'moon', 'b', { tw: 58 })), ...bRing(6, 0, (a, i) => BP(a, [1, 0.68, 0.9, 0.62, 0.84, 0.58][i], 0.12, 'moon', i ? 'f' : 'L', { tw: 58 }))] },
  DIFV: { p: [...[148, 180, 212].map((a, i) => BP(a, [0.42, 0.52, 0.42][i], 0.1, 'drop', 'b')), BP(-46, 0.6, 0.11), BP(46, 0.6, 0.11), BP(0, 1, 0.16, 'arrow', 'L')], st: [[-20, 0.84], [20, 0.84]] },
  DIFT: { p: [...[40, 120, 270].map((a) => BP(a, 0.5, 0.12, 'sail', 'b', { tw: 10 })), ...[76, 160, 236, 300].map((a, i) => BP(a, [0.74, 0.88, 0.62, 0.8][i], 0.19, 'sail', 'f', { tw: 10 })),
    BP(118, 1, 0.07, 'drop', 'f', { r0: 0.8 }), BP(0, 1, 0.19, 'sail', 'L', { tw: 10 })], dt: [[36, 0.93, 0.022, 'f'], [202, 0.95, 0.018, 'f']] },
  SPMV: { p: [...bRing(12, 15, (a) => BP(a, 0.46, 0.06, 'drop', 'b')), ...bRing(12, 0, (a, i) => BP(a, 0.5 + 0.46 * (a === 0 ? 1 : a >= 240 ? Math.pow((a - 240) / 120, 1.4) : 0.06), 0.065, 'drop', i ? 'f' : 'L'))] },
  SPMT: { p: [BP(123, 0.54, 0.13, 'drop', 'b'), BP(237, 0.54, 0.13, 'drop', 'b'), ...[104, 142, 180, 218, 256].map((a, i) => BP(a, [0.62, 0.72, 0.76, 0.72, 0.62][i], 0.18, 'drop')),
    BP(-44, 0.82, 0.07, 'ball', 'f', { r0: 0.68 }), BP(44, 0.82, 0.07, 'ball', 'f', { r0: 0.68 }), BP(0, 1, 0.085, 'ball', 'L', { r0: 0.83 })] },
  SPFV: { p: Array.from({ length: 13 }, (_, k) => BP(((k - 12) * 137.508 % 360 + 360) % 360, 0.3 + 0.7 * Math.pow(k / 12, 0.9), 0.045 + 0.1 * k / 12, 'drop', k === 12 ? 'L' : k >= 7 ? 'b' : 'f')) },
  SPFT: { p: [...[45, 135, 225, 315].map((a, i) => BP(a, [0.46, 0.36, 0.36, 0.42][i], 0.07, 'kite', 'b')), BP(90, 0.66, 0.1, 'kite'), BP(270, 0.56, 0.1, 'kite'), BP(180, 0.5, 0.1, 'kite'), BP(0, 1, 0.12, 'kite', 'L')],
    dt: [[24, 0.5, 0.026, 'f'], [21, 0.68, 0.022, 'f'], [19, 0.85, 0.018, 'f']] },
  SIMV: { p: [...bRing(6, 31, (a) => BP(a, 0.45, 0.08, 'drop', 'b')), ...[0, 62, 118, 182, 238, 300].map((a, i) => BP(a, [1, 0.8, 0.84, 0.72, 0.74, 0.8][i], [0.15, 0.15, 0.15, 0.12, 0.085, 0.13][i], ['drop', 'kite', 'heart', 'almond', 'ball', 'nib'][i], i ? 'f' : 'L', i === 4 ? { r0: 0.57 } : {}))] },
  SIMT: { p: bRing(9, 0, (a, i) => BP(a, [1, 0.55, 0.8, 0.52, 0.92, 0.5, 0.76, 0.55, 0.86][i], 0.085, 'almond', i ? 'f' : 'L', { tw: 22 })),
    dt: bRing(9, 0, (a, i) => [a, [1, 0.55, 0.8, 0.52, 0.92, 0.5, 0.76, 0.55, 0.86][i] + 0.12, 0.03, 'f']).filter((d) => d[1] < 0.8) },
  SIFV: { p: [...[36, 108, 182, 256, 326].map((a) => BP(a, 0.5, 0.11, 'kite', 'b')), ...[70, 148, 220, 292].map((a, i) => BP(a, [0.78, 0.9, 0.7, 0.84][i], 0.2, 'facet')), BP(0, 1, 0.2, 'facet', 'L')],
    dt: [[106, 0.92, 0.02, 'f'], [258, 0.86, 0.018, 'f'], [334, 0.97, 0.015, 'f']] },
  SIFT: { hr: 0.06, p: [BP(160, 0.5, 0.08, 'almond', 'b'), BP(200, 0.44, 0.08, 'almond', 'b'), BP(0, 1, 0.06, 'almond', 'L'),
    ...bRing(5, 12, (a) => BP(a, 0.34, 0.1, 'drop', 'f', { c: [-42, 0.46], r0: 0.035 })), ...bRing(5, -10, (a) => BP(a, 0.3, 0.09, 'drop', 'f', { c: [46, 0.4], r0: 0.035 }))],
    st: [[-42, 0.46, 0], [46, 0.4, 0]], dt: [[-42, 0.46, 0.045, 'b'], [46, 0.4, 0.04, 'b']] }
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

