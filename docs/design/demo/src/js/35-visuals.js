/* ============ shared visuals ============ */
const agent = (id) => AGI[id];
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
function petal(C, deg, L) {
  const a = deg * Math.PI / 180, w = 0.42;
  const tip = pt(C, L, a), c1 = pt(C, L * 0.62, a + w), c2 = pt(C, L * 0.62, a - w);
  return 'M' + C + ' ' + C + 'Q' + c1[0].toFixed(1) + ' ' + c1[1].toFixed(1) + ' ' + tip[0].toFixed(1) + ' ' + tip[1].toFixed(1) + 'Q' + c2[0].toFixed(1) + ' ' + c2[1].toFixed(1) + ' ' + C + ' ' + C + 'Z';
}
const DIRS = { D: 0, S: 180, I: 90, P: 270, M: 45, F: 225, V: 315, T: 135 };
function petals(p, C, scale) {
  let major = '', minor = '';
  const vals = { D: p.v.D, S: 100 - p.v.D, I: p.v.I, P: 100 - p.v.I, M: p.v.M, F: 100 - p.v.M, V: p.v.V, T: 100 - p.v.V };
  Object.keys(DIRS).forEach((k) => { const big = vals[k] >= 50; const d = petal(C, DIRS[k], (16 + vals[k] * 0.56) * scale); if (big) major += d; else minor += d; });
  return { major, minor };
}
function glyphSVG(p, size) {
  const g = petals(p, 40, 0.68);
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 80 80" aria-hidden="true"><path d="' + g.minor + '" fill="var(--h2)"/><path d="' + g.major + '" fill="var(--ink-1)"/></svg>';
}
function fpSVG(L, p, size, opt) {
  opt = opt || {};
  const C = 200;
  let hours = '';
  const hc = new Array(24).fill(0); L.forEach((s) => { hc[s.h]++; });
  const hm2 = Math.max(1, ...hc);
  for (let k = 0; k < 48; k++) { const h = Math.floor(k / 2); const v = (k % 2 === 0 ? hc[h] : (hc[h] + hc[(h + 1) % 24]) / 2) / hm2; const a = (k + 0.5) / 48 * Math.PI * 2; const p1 = pt(C, 100, a), p2 = pt(C, 104 + v * 24, a); hours += 'M' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + 'L' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1); }
  const dots = L.map((s) => { const a = (s.h + s.mi / 60) / 24 * Math.PI * 2; const q = pt(C, 140 + Math.min(s.dur, 126) / 126 * 40, a); const r = (2.3 + Math.min(s.msgs, 20) / 20 * 2).toFixed(1); return '<circle class="fpd" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="' + r + '" fill="' + agent(s.a).c + '" stroke="var(--surface)" stroke-width="1.2"' + (opt.interactive ? ' data-tf="sess|' + s.id + '" data-act="openSession" data-id="' + s.id + '" style="cursor:pointer"' : '') + '/>'; }).join('');
  const g = petals(p, C, 1);
  const lbl = opt.labels ? Object.keys(DIRS).map((k) => { const vals = { D: p.v.D, S: 100 - p.v.D, I: p.v.I, P: 100 - p.v.I, M: p.v.M, F: 100 - p.v.M, V: p.v.V, T: 100 - p.v.V }; const q = pt(C, 16 + vals[k] * 0.56 + 11, DIRS[k] * Math.PI / 180); return '<text x="' + q[0].toFixed(1) + '" y="' + (q[1] + 4).toFixed(1) + '" text-anchor="middle" font-size="11" font-family="var(--mono)" font-weight="' + (vals[k] >= 50 ? 700 : 500) + '" fill="' + (vals[k] >= 50 ? 'var(--ink-1)' : 'var(--ink-3)') + '">' + k + '</text>'; }).join('') + [['00', 0], ['06', 90], ['12', 180], ['18', 270]].map((h) => { const q = pt(C, 194, h[1] * Math.PI / 180); return '<text x="' + q[0].toFixed(1) + '" y="' + (q[1] + 3.5).toFixed(1) + '" text-anchor="middle" font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)">' + h[0] + '</text>'; }).join('') : '';
  return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 400 400" role="img" aria-label="协作指纹：内核是四个维度，中环是 24 小时节律，外环每个点是一个会话" style="overflow:visible;max-width:100%;height:auto"><circle cx="200" cy="200" r="186" fill="var(--surface)" stroke="var(--line)"/><circle cx="200" cy="200" r="132" fill="none" stroke="var(--hair)"/><circle cx="200" cy="200" r="96" fill="none" stroke="var(--line)"/><circle cx="200" cy="200" r="68" fill="var(--bg)" stroke="var(--hair)"/><g class="hours"><path d="' + hours + '" fill="none" stroke="var(--ink-3)" stroke-width="3.2" stroke-linecap="round"/></g><g class="dots">' + dots + '</g><g class="pet"><path d="' + g.minor + '" fill="var(--h2)"/><path d="' + g.major + '" fill="var(--ink-1)"/></g><circle cx="200" cy="200" r="5" fill="var(--surface)" stroke="var(--ink-1)" stroke-width="1.5"/>' + lbl + '</svg>';
}
TIPS.sess = (id) => { const s = BYID[id]; if (!s) return ''; return '<b>' + esc(s.title) + '</b>\n<span class="mono" style="opacity:.8;font-size:11px">' + agent(s.a).name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + dur(s.dur) + '</span>'; };
TIPS.def = (k) => ({ n: '会话数：所选范围内开始的会话。', h: '协作时长：会话从第一条消息到最后一次 Agent 输出的时间之和。', m: '你发出的消息：只计你本人输入，不含 Agent 回复。', a: '自主比 = Agent 步数 ÷ 你的消息数。\nAgent 步数 = 工具调用 + 文字回复。', f: '摩擦率 = 纠偏与不满消息 ÷ 你的消息数。\n分类由本地 Agent 判定。' })[k];

