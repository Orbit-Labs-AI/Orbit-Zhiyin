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
// 协作人格的花：16 型各一朵，每型一种花瓣形状，单层、至多 8 瓣，保持简洁抽象。形状取自类型的性格：
//   DPMV 总设计师 6 枚菱形（蓝图般规整） · DPMT 调度官 8 道细长光芒（向外分派） · DPFV 监制 4 瓣尖叶十字（一次一件）
//   DPFT 委托人 3 枚长水滴（交出去就放手） · DIMV 指挥家 6 枚细柄圆头（指挥棒挥过的轨迹） · DIMT 冲浪者 7 道新月（浪）
//   DIFV 探路者 5 枚箭头（带路） · DIFT 漫游者 5 枚长短不一、间距不匀的水滴（随兴） · SPMV 塔台 8 块圆角方块绕大花心（雷达）
//   SPMT 杂技师 6 颗离开花心的圆球（抛接） · SPFV 工匠 5 瓣带缺口的樱瓣（打磨） · SPFT 执笔人 4 枚笔尖
//   SIMV 实验家 水滴与菱形交替（几种做法） · SIMT 即兴乐手 长短交替的 8 瓣（节奏） · SIFV 雕刻师 5 片削切的多边形 · SIFT 搭档 两两并肩的 4 瓣
// 四个字母另有两条共同约定：委托 D 长瓣小花心 / 掌舵 S 短瓣大花心；求证 V 花心是一圈环 + 中心点 / 信任 T 是实心圆点。
// 比例随强度微调（委托强度 → 瓣长，即兴强度 → 旋卷）。以 (C, C) 为圆心、R 为最大半径；领瓣（lead）的瓣尖朝 0°（12 点），
// 由调用方整体旋转。字母取 p.axes 的结论（live 里未定的轴是「?」，按分值取一极），没有时按分值以 50 为界取一极。
const BLOOM_K = ['D', 'I', 'M', 'V'];
const BLOOMS = {
  DPMV: { n: 6, s: 'kite', w: 0.25 }, DPMT: { n: 8, s: 'almond', w: 0.075 }, DPFV: { n: 4, s: 'almond', w: 0.26 }, DPFT: { n: 3, s: 'drop', w: 0.24 },
  DIMV: { n: 6, s: 'spoon', w: 0.17, tw: 14 }, DIMT: { n: 7, s: 'moon', w: 0.13, tw: 58 }, DIFV: { n: 5, s: 'arrow', w: 0.28 },
  DIFT: { n: 5, s: 'drop', w: 0.21, len: [1, 0.72, 0.9, 0.64, 0.82], ang: [0, 64, 152, 212, 292], tw: 8 },
  SPMV: { n: 8, s: 'square', w: 0.11 }, SPMT: { n: 6, s: 'disc', w: 0.13 }, SPFV: { n: 5, s: 'heart', w: 0.3 }, SPFT: { n: 4, s: 'nib', w: 0.21 },
  SIMV: { n: 6, s: ['drop', 'kite'], w: 0.19 }, SIMT: { n: 8, s: 'drop', w: 0.14, len: [1, 0.66], tw: 16 }, SIFV: { n: 5, s: 'facet', w: 0.28 },
  SIFT: { n: 4, s: 'drop', w: 0.22, ang: [0, 44, 180, 224] }
};
function bloomCode(p) { return BLOOM_K.map((k, i) => { const l = p.axes && p.axes[i] && p.axes[i].letter; return l && l !== '?' ? l : axisView(p, i).letter; }).join(''); }
// 一片花瓣（瓣轴坐标：x 横向、y 径向，r0 → L，半宽 w）；cmd 里的点经 P 转到角度 th，旋卷时越靠瓣尖转得越多
function bloomPetal(shape, P, r0, L, w) {
  const h = L - r0, y = (t) => r0 + t * h, k = 0.5523;
  const M = (pts) => 'M' + pts.map((q) => P(q[0], q[1])).join('L') + 'Z';
  const C = (p0, segs) => 'M' + P(p0[0], p0[1]) + segs.map((sg) => 'C' + sg.map((q) => P(q[0], q[1])).join(' ')).join('') + 'Z';
  const mirror = (p0, segs) => C(p0, segs.concat(segs.slice().reverse().map((sg, i, arr) => { const prev = i + 1 < arr.length ? arr[i + 1][2] : p0; return [[-sg[1][0], sg[1][1]], [-sg[0][0], sg[0][1]], [-prev[0], prev[1]]]; })));
  switch (shape) {
    case 'kite': return M([[0, r0], [w, y(0.42)], [0, L], [-w, y(0.42)]]);
    case 'arrow': return M([[0, r0], [w * 0.22, y(0.46)], [w, y(0.5)], [0, L], [-w, y(0.5)], [-w * 0.22, y(0.46)]]);
    case 'nib': return M([[-w * 0.5, y(0.04)], [w * 0.5, y(0.04)], [w, y(0.5)], [0, L], [-w, y(0.5)]]);
    case 'facet': return M([[0, r0], [w, y(0.36)], [w * 0.64, y(0.94)], [-w * 0.24, L], [-w * 0.96, y(0.6)]]);
    case 'spoon': return mirror([0, r0], [[[w * 0.22, y(0.3)], [w * 0.1, y(0.5)], [w * 0.62, y(0.6)]], [[w * 1.25, y(0.7)], [w * 1.05, L], [0, L]]]);
    case 'fan': return 'M' + P(0, r0) + 'L' + P(w, y(0.86)) + 'Q' + P(0, y(1.06)) + ' ' + P(-w, y(0.86)) + 'Z';
    case 'square': { const y0 = y(0.22), r = w * 0.45; return 'M' + P(-w + r, y0) + 'L' + P(w - r, y0) + 'Q' + P(w, y0) + ' ' + P(w, y0 + r) + 'L' + P(w, L - r) + 'Q' + P(w, L) + ' ' + P(w - r, L) + 'L' + P(-w + r, L) + 'Q' + P(-w, L) + ' ' + P(-w, L - r) + 'L' + P(-w, y0 + r) + 'Q' + P(-w, y0) + ' ' + P(-w + r, y0) + 'Z'; }
    case 'disc': { const c = y(0.64); return C([0, c - w], [[[w * k, c - w], [w, c - w * k], [w, c]], [[w, c + w * k], [w * k, c + w], [0, c + w]], [[-w * k, c + w], [-w, c + w * k], [-w, c]], [[-w, c - w * k], [-w * k, c - w], [0, c - w]]]); }
    case 'heart': return mirror([0, r0], [[[w * 1.1, y(0.24)], [w * 1.16, L], [w * 0.5, L]], [[w * 0.2, L], [0, y(0.9)], [0, y(0.86)]]]);
    case 'moon': return C([0, r0], [[[w * 1.6, y(0.3)], [w * 1.2, y(0.95)], [0, L]], [[-w * 0.2, y(0.7)], [-w * 0.5, y(0.3)], [0, r0]]]);
    case 'drop': return mirror([0, r0], [[[w * 1.2, y(0.34)], [w * 0.86, L], [0, L]]]);
    default: return mirror([0, r0], [[[w * 1.15, y(0.3)], [w * 0.62, y(0.84)], [0, L]]]);   // almond
  }
}
function bloom(p, C, R) {
  const av = BLOOM_K.map((k, i) => axisView(p, i)), u = (i) => clamp((av[i].strong - 50) / 35, 0, 1);
  const code = bloomCode(p), sp = BLOOMS[code] || BLOOMS.DIMV, D = code[0] === 'D', V = code[3] === 'V';
  const hr = D ? 0.1 : 0.2, r0 = hr * 0.92, L = (D ? 0.96 : 0.84) * (0.93 + 0.07 * u(0)), tw = (sp.tw || 0) * (0.7 + 0.6 * u(1)) * Math.PI / 180;
  const f = (v) => v.toFixed(1);
  let major = '', lead = '';
  for (let i = 0; i < sp.n; i++) {
    const th = (sp.ang ? sp.ang[i] : i * 360 / sp.n) * Math.PI / 180 - tw, len = r0 + (L - r0) * (sp.len ? sp.len[i % sp.len.length] : 1);
    const P = (x, y) => { const a = th + tw * Math.pow(clamp((y - r0) / (L - r0), 0, 1.1), 1.3); return f(C + R * (y * Math.sin(a) + x * Math.cos(a))) + ' ' + f(C + R * (-y * Math.cos(a) + x * Math.sin(a))); };
    const d = bloomPetal(Array.isArray(sp.s) ? sp.s[i % sp.s.length] : sp.s, P, r0, len, sp.w);
    if (i) major += d; else lead = d;
  }
  return { major, minor: '', lead, hr: hr * R, ring: V, n: sp.n, code };
}
// 花心：求证 V 是一圈环（底色填充）+ 中心点，信任 T 是实心圆点；sw = 线宽
function bloomHeart(g, cx, cy, ink, bg, sw) {
  return g.ring ? '<circle cx="' + cx + '" cy="' + cy + '" r="' + g.hr.toFixed(1) + '" fill="' + bg + '" stroke="' + ink + '" stroke-width="' + sw + '"/><circle cx="' + cx + '" cy="' + cy + '" r="' + (sw * 1.3).toFixed(1) + '" fill="' + ink + '"/>'
    : '<circle cx="' + cx + '" cy="' + cy + '" r="' + (g.hr * 0.62).toFixed(1) + '" fill="' + ink + '"/>';
}
// 一个类型的代表花（算法说明的 16 型表）：四个维度都取该极、强度 72
const typeP = (code) => ({ v: { D: code[0] === 'D' ? 72 : 28, I: code[1] === 'I' ? 72 : 28, M: code[2] === 'M' ? 72 : 28, V: code[3] === 'V' ? 72 : 28 } });
// 小尺寸花（菜单栏、小组件、分享卡，80 视框）：领瓣并入前排
function bloomGlyph(p) { const g = bloom(p, 40, 36); return { major: g.lead + g.major, minor: '', hr: +g.hr.toFixed(1), ring: g.ring }; }
function glyphSVG(p, size) {
  const g = bloomGlyph(p);
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 80 80" aria-hidden="true" data-bloom="' + bloomCode(p) + '"><path d="' + g.major + '" fill="var(--ink-1)"/>' + bloomHeart(g, 40, 40, 'var(--ink-1)', 'none', 2) + '</svg>';
}
TIPS.sess = (id) => { const s = BYID[id]; if (!s) return ''; return '<b>' + esc(s.title) + '</b>\n<span class="mono" style="opacity:.8;font-size:11px">' + agent(s.a).name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + dur(s.dur) + '</span>'; };
TIPS.def = (k) => ({ n: '会话数：所选范围内开始的会话。', h: '协作时长：会话从第一条消息到最后一次 Agent 输出的时间之和。', m: '你发出的消息：只计你本人输入，不含 Agent 回复。', a: '自主比 = Agent 步数 ÷ 你的消息数。\nAgent 步数 = 工具调用 + 文字回复。', f: '摩擦率 = 纠偏与不满消息 ÷ 你的消息数。\n分类由本地 Agent 判定。' })[k];

