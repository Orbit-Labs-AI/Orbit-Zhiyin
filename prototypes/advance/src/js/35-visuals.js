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
// 协作人格的花：16 型各一朵。四个维度各管一个花型特征，形状由四字母决定，比例随该轴强度（50 → 85+）微调：
//   M 多线 / F 专注 → 12 瓣 / 5 瓣
//   I 即兴 / P 规划 → 花瓣顺时针旋卷、圆头 / 端正、尖头
//   D 委托 / S 掌舵 → 长瓣、小花心 / 短阔瓣、大花心（花心里一圈舵环）
//   V 求证 / T 信任 → 重瓣（身后再一轮，错开半格）/ 单瓣
// 以 (C, C) 为圆心、R 为最大半径；领瓣（lead）的瓣尖朝 0°（12 点），由调用方整体旋转。major = 其余前排花瓣，minor = 身后一轮，
// hr = 花心半径，helm = 是否画舵环。字母取 p.axes 的结论（live 里未定的轴是「?」），没有时按分值以 50 为界取一极。
const BLOOM_K = ['D', 'I', 'M', 'V'];
function bloomCode(p) { return BLOOM_K.map((k, i) => (p.axes && p.axes[i] && p.axes[i].letter) || axisView(p, i).letter).join(''); }
function bloom(p, C, R) {
  const av = BLOOM_K.map((k, i) => axisView(p, i)), u = (i) => clamp((av[i].strong - 50) / 35, 0, 1);
  const D = av[0].letter === 'D', I = av[1].letter === 'I', M = av[2].letter === 'M', V = av[3].letter === 'V';
  const n = M ? 12 : 5, L = D ? 0.88 + 0.12 * u(0) : 0.78 - 0.06 * u(0), hr = D ? 0.1 : 0.19 + 0.06 * u(0);
  const w = (M ? 0.13 : 0.3) * (D ? 1 : 1.22), tw = I ? (24 + 22 * u(1)) * Math.PI / 180 : 0, r0 = hr * 0.92;
  const f = (v) => v.toFixed(1);
  // 一片花瓣：瓣轴上的点 (x 横向, y 径向) 绕圆心转到 th，旋卷时越靠瓣尖转得越多；即兴的前缘更饱满（风车）
  const pet = (th, len, wid) => {
    const h = len - r0, wr = wid * (I ? 1.18 : 1), wl = wid * (I ? 0.8 : 1), sd = I ? [[1.2, 0.34], [0.86, 1]] : [[1.15, 0.3], [0.62, 0.84]];
    const P = (x, y) => { const a = th + tw * Math.pow(clamp((y - r0) / h, 0, 1.05), 1.3); return f(C + R * (y * Math.sin(a) + x * Math.cos(a))) + ' ' + f(C + R * (-y * Math.cos(a) + x * Math.sin(a))); };
    return 'M' + P(0, r0) + 'C' + P(wr * sd[0][0], r0 + sd[0][1] * h) + ' ' + P(wr * sd[1][0], r0 + sd[1][1] * h) + ' ' + P(0, len) +
      'C' + P(-wl * sd[1][0], r0 + sd[1][1] * h) + ' ' + P(-wl * sd[0][0], r0 + sd[0][1] * h) + ' ' + P(0, r0) + 'Z';
  };
  const st = Math.PI * 2 / n; let major = '', minor = '', lead = '';
  for (let k = 0; k < n; k++) { const d = pet(k * st - tw, L, w * L); if (k) major += d; else lead = d; }
  if (V) for (let k = 0; k < n; k++) minor += pet((k + 0.5) * st - tw, L * (0.8 + 0.1 * u(3)), w * L * 0.92);
  return { major, minor, lead, hr: hr * R, helm: !D, n };
}
// 一个类型的代表花（算法说明的 16 型表）：四个维度都取该极、强度 72
const typeP = (code) => ({ v: { D: code[0] === 'D' ? 72 : 28, I: code[1] === 'I' ? 72 : 28, M: code[2] === 'M' ? 72 : 28, V: code[3] === 'V' ? 72 : 28 } });
// 小尺寸花（菜单栏、小组件、分享卡，80 视框）：领瓣并入前排；花瓣从花心外缘长出，花心不用填底色
function bloomGlyph(p) { const g = bloom(p, 40, 36); return { major: g.lead + g.major, minor: g.minor, hr: +g.hr.toFixed(1) }; }
function glyphSVG(p, size) {
  const g = bloomGlyph(p);
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 80 80" aria-hidden="true" data-bloom="' + bloomCode(p) + '"><path d="' + g.minor + '" fill="var(--h2)"/><path d="' + g.major + '" fill="var(--ink-1)"/>' +
    '<circle cx="40" cy="40" r="' + g.hr + '" fill="none" stroke="var(--ink-1)" stroke-width="1.6"/><circle cx="40" cy="40" r="1.6" fill="var(--ink-1)"/></svg>';
}
TIPS.sess = (id) => { const s = BYID[id]; if (!s) return ''; return '<b>' + esc(s.title) + '</b>\n<span class="mono" style="opacity:.8;font-size:11px">' + agent(s.a).name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + dur(s.dur) + '</span>'; };
TIPS.def = (k) => ({ n: '会话数：所选范围内开始的会话。', h: '协作时长：会话从第一条消息到最后一次 Agent 输出的时间之和。', m: '你发出的消息：只计你本人输入，不含 Agent 回复。', a: '自主比 = Agent 步数 ÷ 你的消息数。\nAgent 步数 = 工具调用 + 文字回复。', f: '摩擦率 = 纠偏与不满消息 ÷ 你的消息数。\n分类由本地 Agent 判定。' })[k];

