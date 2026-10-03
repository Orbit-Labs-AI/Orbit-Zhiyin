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
// 协作人格的花：16 型各一朵，延续分享卡 4/8 花的做法：平涂、两色、几何、安静。
// 每朵都旋转对称：N 片相同的墨色主瓣（3–6 片）均匀围着花心，可再加一圈 N 片浅灰小瓣（错开半格），中间是花心；
// 形状与颜色都按 360°/N 重复，不求镜像，也没有领瓣、花籽、花蕊。一片主瓣朝 0°（12 点），调用方整体旋转让它指向类型。
// 字母约定：多线 M 5–6 瓣 / 专注 F 3–4 瓣；即兴 I 瓣同向旋卷（风车）/ 规划 P 瓣直；
// 委托 D 瓣长、小花心 / 掌舵 S 瓣短而宽、大花心；求证 V 花心是一圈环 + 中心点 / 信任 T 是实心圆点。
// 其余靠元素区分：瓣形（杏仁、水滴、圆、圆菱形、心形凹口、长矛、尖头莲瓣、方头扇瓣，小瓣另有菱形）与浅灰小瓣的有无和形状。
//   总设计师  六片尖头莲瓣 + 六片小菱形，层次规整如蓝图   调度官    五片细长杏仁瓣放射开，放手并行
//   监制      三片水滴瓣 + 三片浅灰小瓣，一次只开一朵     策划人    四片杏仁瓣 + 四片浅灰小瓣，即分享卡的 4/8 花
//   指挥家    五片杏仁瓣带浅灰小瓣齐齐旋向一侧           冲浪者    六片弯月瓣卷成浪
//   探路者    四片长矛瓣旋开探向前方，浅灰小瓣随后       远航者    四片水滴瓣像帆顺风微旋，浅灰瓣一样饱满
//   飞控官    六片方头扇瓣围着大环心，像仪表盘           杂技师    五片圆瓣，梅花一样饱满
//   分析学家  四片心形凹口瓣十字端正，浅灰小菱形补角     领航员    四片圆菱形瓣 + 四片小菱形，罗盘星
//   实验家    五片心形瓣一起旋开                         即兴乐手  六片水滴瓣转成风车
//   雕刻师    四片尖头莲瓣斜着排开，像一刀刀刻出         同行者    三片心形宽瓣与三片浅灰圆瓣交错相拥
// 比例随强度微调（委托越强瓣越长、掌舵越强瓣越短，即兴越强旋得越多）。字母取 p.axes 的结论（live 里未定的轴按分值取一极），没有时按分值以 50 为界取一极。
const BLOOM_K = ['D', 'I', 'M', 'V'];
// 瓣形：右半边轮廓，从瓣基 (0, 0) 到瓣尖 (0, 1)，x 以半宽为单位、y 是沿瓣长的比例；三个点是一段三次曲线（两控制点 + 终点），一个点是直线
const BSHAPE = {
  almond: [[[1.333, 0.377], [1.333, 0.71], [0, 1]]],
  drop: [[[1.18, 0.35], [1.47, 1], [0, 1]]],
  round: [[[0.3, 0.04], [1, 0.22], [1, 0.55]], [[1, 0.8], [0.552, 1], [0, 1]]],
  kite: [[[1, 0.42]], [[0, 1]]],
  gem: [[[0.4, 0.1], [0.85, 0.3], [1, 0.42]], [[0.85, 0.6], [0.4, 0.88], [0, 1]]],
  heart: [[[1.1, 0.22], [1.15, 1], [0.5, 1]], [[0.2, 1], [0, 0.92], [0, 0.86]]],
  lance: [[[0.9, 0.18], [1.45, 0.45], [0, 1]]],
  lotus: [[[0.55, 0.05], [1, 0.2], [1, 0.42]], [[1, 0.66], [0.3, 0.78], [0, 1]]],
  fan: [[[0.35, 0.1], [0.85, 0.45], [1, 0.72]], [[1.06, 0.9], [0.9, 1], [0.6, 1]], [[0.4, 1], [0.2, 1], [0, 1]]]
};
// 一种花：n 主瓣数，s 瓣形，l 瓣长、w 半宽（以 R 为单位），tw 旋卷°，sk 偏宽（顺旋向的一侧更饱满），m 浅灰小瓣 { s, l, w }，hr 花心半径
const BLOOMS = {
  DPMV: { n: 6, s: 'lotus', l: 1, w: 0.12, m: { s: 'kite', l: 0.56, w: 0.08 } },
  DPMT: { n: 5, s: 'almond', l: 1, w: 0.115 },
  DPFV: { n: 3, s: 'drop', l: 0.98, w: 0.22, m: { s: 'almond', l: 0.6, w: 0.12 } },
  DPFT: { n: 4, s: 'almond', l: 1, w: 0.14, m: { s: 'almond', l: 0.6, w: 0.085 } },
  DIMV: { n: 5, s: 'almond', l: 0.98, w: 0.15, tw: 30, sk: 0.12, m: { s: 'almond', l: 0.58, w: 0.08 } },
  DIMT: { n: 6, s: 'almond', l: 0.98, w: 0.12, tw: 55, sk: 0.2 },
  DIFV: { n: 4, s: 'lance', l: 1, w: 0.16, tw: 30, sk: 0.15, m: { s: 'drop', l: 0.55, w: 0.1 } },
  DIFT: { n: 4, s: 'drop', l: 1, w: 0.15, tw: 20, sk: 0.3, m: { s: 'drop', l: 0.7, w: 0.12 } },
  SPMV: { n: 6, s: 'fan', l: 0.84, w: 0.16, hr: 0.2 },
  SPMT: { n: 5, s: 'round', l: 0.84, w: 0.17 },
  SPFV: { n: 4, s: 'heart', l: 0.86, w: 0.24, m: { s: 'kite', l: 0.5, w: 0.1 }, hr: 0.2 },
  SPFT: { n: 4, s: 'gem', l: 0.86, w: 0.22, m: { s: 'kite', l: 0.56, w: 0.11 }, hr: 0.22 },
  SIMV: { n: 5, s: 'heart', l: 0.84, w: 0.2, tw: 28, sk: 0.2 },
  SIMT: { n: 6, s: 'drop', l: 0.86, w: 0.14, tw: 30, sk: 0.3 },
  SIFV: { n: 4, s: 'lotus', l: 0.86, w: 0.23, tw: 26, sk: 0.3, m: { s: 'almond', l: 0.58, w: 0.09 } },
  SIFT: { n: 3, s: 'heart', l: 0.86, w: 0.26, tw: 12, sk: 0.1, m: { s: 'round', l: 0.6, w: 0.14 } }
};
function bloomCode(p) { return BLOOM_K.map((k, i) => { const l = p.axes && p.axes[i] && p.axes[i].letter; return l && l !== '?' ? l : axisView(p, i).letter; }).join(''); }
// 一片花瓣：按瓣形轮廓画右半、镜像回左半（右 / 左半宽 w(1 ± sk)）；P 把瓣轴坐标（x 横向、y 径向）转到角度并随旋卷弯曲
function bloomPetal(shape, P, r0, L, w, sk) {
  const pr = BSHAPE[shape] || BSHAPE.almond, h = L - r0, wr = w * (1 + (sk || 0)), wl = -w * (1 - (sk || 0));
  const Q = (q, s) => P(q[0] * s, r0 + q[1] * h), seg = (sg, pts, s) => (sg.length === 3 ? 'C' : 'L') + pts.map((q) => Q(q, s)).join(' ');
  let d = 'M' + Q([0, 0], 1) + pr.map((sg) => seg(sg, sg, wr)).join('');
  for (let i = pr.length - 1; i >= 0; i--) { const sg = pr[i], prev = i ? pr[i - 1][pr[i - 1].length - 1] : [0, 0]; d += seg(sg, sg.length === 3 ? [sg[1], sg[0], prev] : [prev], wl); }
  return d + 'Z';
}
// 返回：major 主瓣（墨色）、back / minor 小瓣（浅灰）、hr 花心半径、ring 是否环形花心、n 主瓣数、sw 线宽；lead、st、dotF、dotB 保留为空串
function bloom(p, C, R) {
  const av = BLOOM_K.map((k, i) => axisView(p, i)), u = (i) => clamp((av[i].strong - 50) / 35, 0, 1);
  const code = bloomCode(p), sp = BLOOMS[code] || BLOOMS.DIMV, D = code[0] === 'D', V = code[3] === 'V';
  const hr = sp.hr || (D ? 0.1 : 0.18), k = D ? 0.93 + 0.07 * u(0) : 1 - 0.05 * u(0), tw = (sp.tw || 0) * (0.7 + 0.6 * u(1)) * Math.PI / 180, f = (v) => v.toFixed(1);
  // 瓣基：环形花心从环上长出，实心花心从圆点里长出
  const r0 = V ? hr : hr * 0.3, n = sp.n, st = 360 / n;
  const ring = (q, off) => { let d = ''; const L = Math.max(r0 + 0.05, q.l * k);
    for (let i = 0; i < n; i++) {
      // 旋卷时瓣在 60% 处落在瓣轴上，整片瓣看起来朝向该角度
      const th = (off + i * st) * Math.PI / 180 - tw * Math.pow(0.6, 1.3);
      const P = (x, y) => { const a = th + tw * Math.pow(clamp((y - r0) / (L - r0), 0, 1.1), 1.3); return f(C + R * (y * Math.sin(a) + x * Math.cos(a))) + ' ' + f(C + R * (-y * Math.cos(a) + x * Math.sin(a))); };
      d += bloomPetal(q.s, P, r0, L, q.w, sp.sk);
    }
    return d; };
  const back = sp.m ? ring(sp.m, st / 2) : '';
  return { back, major: ring(sp, 0), lead: '', st: '', dotF: '', dotB: '', minor: back, hr: hr * R, ring: V, n, code, sw: Math.max(0.6, R * 0.012) };
}
// 花心：求证 V 是一圈环（底色填充）+ 中心点，信任 T 是实心圆点；sw = 线宽
function bloomHeart(g, cx, cy, ink, bg, sw) {
  return g.ring ? '<circle cx="' + cx + '" cy="' + cy + '" r="' + g.hr.toFixed(1) + '" fill="' + bg + '" stroke="' + ink + '" stroke-width="' + sw + '"/><circle cx="' + cx + '" cy="' + cy + '" r="' + (sw * 1.3).toFixed(1) + '" fill="' + ink + '"/>'
    : '<circle cx="' + cx + '" cy="' + cy + '" r="' + (g.hr * 0.62).toFixed(1) + '" fill="' + ink + '"/>';
}
// 一朵花的图层：back 小瓣（浅灰）、front 主瓣（墨色；有领瓣、花蕊、圆点时一并画上）、heart 花心；ink / gray / lead / bg 是颜色，hw 是花心线宽
function bloomParts(g, cx, cy, c) {
  return { back: g.back ? '<path class="fp-bk" d="' + g.back + '" fill="' + c.gray + '"/>' : '',
    front: (g.lead ? '<path class="fp-lead" d="' + g.lead + '" fill="' + c.lead + '"/>' : '') + '<path class="fp-pet" d="' + g.major + '" fill="' + c.ink + '"/>' +
      (g.st ? '<path class="fp-st" d="' + g.st + '" fill="none" stroke="' + c.ink + '" stroke-width="' + g.sw.toFixed(2) + '" stroke-linecap="round"/>' : '') + (g.dotF ? '<path class="fp-dt" d="' + g.dotF + '" fill="' + c.ink + '"/>' : '') + (g.dotB ? '<path class="fp-dt" d="' + g.dotB + '" fill="' + c.gray + '"/>' : ''),
    heart: bloomHeart(g, cx, cy, c.ink, c.bg, c.hw || 1.6) };
}
function bloomLayers(g, cx, cy, c) { const q = bloomParts(g, cx, cy, c); return q.back + q.front + q.heart; }
// 一个类型的代表花（算法说明的 16 型表）：四个维度都取该极、强度 72
const typeP = (code) => ({ v: { D: code[0] === 'D' ? 72 : 28, I: code[1] === 'I' ? 72 : 28, M: code[2] === 'M' ? 72 : 28, V: code[3] === 'V' ? 72 : 28 } });
// 小尺寸花（菜单栏、小组件、分享卡，80 视框）
function bloomGlyph(p) { const g = bloom(p, 40, 36); return Object.assign(g, { hr: +g.hr.toFixed(1), major: g.lead + g.major }); }
function glyphSVG(p, size) {
  const g = bloom(p, 40, 36);
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 80 80" aria-hidden="true" data-bloom="' + bloomCode(p) + '">' + bloomLayers(g, 40, 40, { ink: 'var(--ink-1)', gray: 'var(--h3)', lead: 'var(--ink-1)', bg: 'none', hw: 2 }) + '</svg>';
}
TIPS.sess = (id) => { const s = BYID[id]; if (!s) return ''; return '<b>' + esc(s.title) + '</b>\n<span class="mono" style="opacity:.8;font-size:11px">' + agent(s.a).name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + dur(s.dur) + '</span>'; };
TIPS.def = (k) => ({ n: '会话数：所选范围内开始的会话。', h: '协作时长：会话从第一条消息到最后一次 Agent 输出的时间之和。', m: '你发出的消息：只计你本人输入，不含 Agent 回复。', a: '自主比 = Agent 步数 ÷ 你的消息数。\nAgent 步数 = 工具调用 + 文字回复。', f: '摩擦率 = 纠偏与不满消息 ÷ 你的消息数。\n分类由本地 Agent 判定。' })[k];

