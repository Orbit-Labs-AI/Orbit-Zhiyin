/* ============ derived data ============ */
function win(range) { const L = LASTDAY; return range === 7 ? [L - 6, L] : range === 30 ? [L - 29, L] : range === 90 ? [L - 89, L] : [Math.max(0, Math.min(FIRSTDAY, L)), L]; }
function prevWin(range) { if (!range) return null; const w = win(range); const a = w[0] - range; return a < 0 ? null : [a, w[0] - 1]; }
// Agent filter model: the default is every imported agent (S.agents = all of AG). Only an explicit deselection is remembered
// (S.agentOff, ids); agents that show up later join the filter unless the user unchecked them. agentSync() records the user's
// choice from S.agents (ids no longer in AG stay in agentOff until picked again); agentApply() rebuilds S.agents from AG
// and agentOff after AG changes (live hydrate, a restored store) and heals a stale pick: an empty result means all.
function agentSync() {
  const off = new Set(Array.from(S.agentOff).filter((id) => !AGI[id]));
  AG.forEach((a) => { if (!S.agents.has(a.id)) off.add(a.id); });
  S.agentOff = off;
}
function agentApply() {
  let on = AG.filter((a) => !S.agentOff.has(a.id)).map((a) => a.id);
  if (!on.length) { on = AG.map((a) => a.id); S.agentOff = new Set(); }
  S.agents = new Set(on);
}
function sourceEnabled(s) { return !S.srcOff.has(s.a); }
function base(s) { return !s.live && S.agents.has(s.a) && sourceEnabled(s); }
function pass(s, o) {
  if (!base(s)) return false;
  const p = o.project !== undefined ? o.project : S.project;
  if (p && s.p !== p) return false;
  if (o.agent && s.a !== o.agent) return false;
  if (!o.noExtra) {
    if (S.topic && s.topic !== S.topic) return false;
    if (S.outcome && s.out !== S.outcome) return false;
    if (S.fric && s.fric !== S.fric) return false;
    if (S.hour != null && s.h !== S.hour) return false;
  }
  return true;
}
function sel(o) { o = o || {}; const w = o.win || win(o.range != null ? o.range : S.range); return ALL.filter((s) => s.d >= w[0] && s.d <= w[1] && pass(s, o)); }
// 人格的唯一口径（BUG-06）：只按时间窗、Agent 与项目取会话；主题 / 结果 / 摩擦 / 时段这些会话级筛选不计入，
// 否则同一时刻侧栏（personaNow）、A1 人格卡与 A2 会算出不同的四字母码。页面在显示时注明哪些筛选未计入（personaScopeNote）。
function personaScope(w) { return sel({ win: w || win(S.range), noExtra: true }); }
function personaScopeNote() {
  const x = [];
  if (S.topic) x.push('主题'); if (S.outcome) x.push('结果'); if (S.fric) x.push('摩擦'); if (S.hour != null) x.push('时段');
  return x.length ? x.join(' / ') + '筛选不计入人格' : '';
}
function stats(L) {
  const n = L.length, mins = sum(L, (s) => s.dur), msgs = sum(L, (s) => s.msgs), tools = sum(L, (s) => s.tools);
  const errors = sum(L, (s) => s.errors), corr = sum(L, (s) => s.corr);
  // live rows carry observed steps (uiview/derive.py); the demo rows keep the tools × 1.54 stand-in
  const stepped = L.some((s) => s.steps != null), steps = stepped ? sum(L, (s) => s.steps || 0) : 0;
  // live rows may carry no outcome / verify signal (null): rates use only the sessions that have one; okKnown / verKnown = 0
  // means unknown, shown as「—」(pctKnown) instead of a made-up 0 %
  const okKnown = L.filter((s) => s.out === 'ok' || s.out === 'part' || s.out === 'fail').length, verKnown = L.filter((s) => s.verify != null).length;
  return { n, hours: mins / 60, msgs, tools, errors, corr, tok: sum(L, (s) => s.tok), auto: msgs ? (stepped ? steps / msgs : tools * 1.54 / msgs) : 0, fric: msgs ? corr / msgs * 100 : 0, per: n ? msgs / n : 0, verify: verKnown ? L.filter((s) => s.verify).length / verKnown * 100 : 0, verKnown, ok: okKnown ? L.filter((s) => s.out === 'ok').length / okKnown * 100 : 0, okKnown, err: tools ? errors / tools * 100 : 0 };
}
// ===== 协作人格 · 多信号口径（与 uiview/persona_signals.py 同一份锚点、权重与统计量；示例与 live 共用）=====
// 每个维度综合多个信号：信号先经有界分段线性锚点映射到 0–100（高 = D / I / M / V 一极），再按权重加权平均；
// 缺数据的信号退出、其余权重重新归一化。统计量全部可加（按会话 / 按天），任意 Agent 子集 = 各 Agent 统计量之和。
// 1 个会话即可出结论（0 个才是空态）；每个维度以 50 为界取一极，恰好 50 归高值一极，始终给完整 4 字母。
const PERSONA_SOFT_N = 30;
const personaHint = (n) => (n > 0 && n < PERSONA_SOFT_N ? '基于 ' + n + ' 个会话，数据越多越准' : null);
const PSTEP = 5, PZ = 1.96;
// [key, axis, weight, kind, unit, anchors, label]
const PSIG = [
  ['steps', 'D', 0.50, 'ratio', 'turn', [[0, 5], [1, 95]], '单轮自主步数（≥ 5 步的轮次占比）'],
  ['msgs', 'D', 0.25, 'mean', 'session', [[1, 80], [3, 65], [8, 50], [20, 25], [50, 10]], '每会话消息数（越少越委托）'],
  ['stops', 'D', 0.25, 'ratio', 'turn', [[0, 65], [0.1, 50], [0.25, 25], [0.5, 8], [1, 5]], '打断与中止率（越高越掌舵）'],
  ['struct', 'I', 0.35, 'ratio', 'session', [[0, 5], [1, 95]], '开场未写执行顺序 / 验收标准的占比'],
  ['spec', 'I', 0.20, 'ratio', 'session', [[0, 60], [0.15, 45], [0.4, 20], [1, 5]], '开场引用规格 / 计划文件的占比（越高越规划）'],
  ['length', 'I', 0.15, 'mean', 'session', [[0, 85], [20, 85], [80, 62], [200, 40], [600, 18], [1500, 10]], '首条消息长度（越长越规划）'],
  ['redirect', 'I', 0.30, 'mean', 'session', [[0, 35], [0.1, 55], [0.25, 75], [0.5, 92], [1, 95]], '中途改向（纠偏消息占比）'],
  ['parallel', 'M', 0.35, 'ratio', 'day', [[0, 5], [1, 95]], '同日 ≥ 2 个 Agent 或会话时间重叠的天数占比'],
  ['per_day', 'M', 0.25, 'mean', 'day', [[1, 20], [2, 40], [3, 52], [5, 70], [10, 90]], '每日会话数'],
  ['agents_day', 'M', 0.25, 'mean', 'day', [[1, 30], [2, 70], [3, 88], [5, 95]], '同日使用的 Agent 数'],
  ['subagents', 'M', 0.15, 'ratio', 'session', [[0, 40], [0.1, 55], [0.3, 75], [0.6, 92], [1, 95]], '子代理并行度（≥ 2 个子代理同时运行的会话占比）'],
  ['verify', 'V', 0.70, 'ratio', 'turn', [[0, 5], [0.05, 25], [0.3, 50], [0.6, 85], [1, 95]], '你要求测试 / 编译 / 检查的轮次占比（Agent 自行跑的不算）'],
  ['rework', 'V', 0.30, 'ratio', 'session', [[0, 40], [0.1, 60], [0.25, 80], [0.5, 95], [1, 95]], '回滚与重做率（有回滚 / 重做的会话占比）']
];
const PSIGK = {}; PSIG.forEach((x) => { PSIGK[x[0]] = x; });
function pl(x, an) {
  if (x <= an[0][0]) return an[0][1];
  for (let i = 1; i < an.length; i++) if (x <= an[i][0]) { const [x0, y0] = an[i - 1], [x1, y1] = an[i]; return y0 + (y1 - y0) * (x - x0) / (x1 - x0); }
  return an[an.length - 1][1];
}
// one session's contributions: ratio signals as (k, n) clusters, mean signals as a mapped score
function psContrib(s) {
  const r = {}, m = {};
  if (s.dn) { r.steps = [s.dk || 0, s.dn]; r.verify = [s.vk || 0, s.dn]; }
  if (s.kn) r.stops = [s.ik || 0, s.kn];
  const oa = s.oa != null ? s.oa : s.op;   // 旧快照只有 op（开场是否结构化）
  if (oa != null) r.struct = [oa ? 0 : 1, 1];
  if (s.os != null) r.spec = [s.os ? 1 : 0, 1];
  if (s.sc != null) r.subagents = [s.sc >= 2 ? 1 : 0, 1];
  if (s.rb != null) r.rework = [s.rb ? 1 : 0, 1];
  // live 行把未知的 msgs / corr 记成 0 供别处求和；这里取线上原值，未知就是未知（与后端一致）
  const msgs = s.raw ? s.raw.msgs : s.msgs, corr = s.raw ? s.raw.corr : s.corr;
  if (msgs) { m.msgs = pl(msgs, PSIGK.msgs[5]); if (msgs >= 2 && corr != null) m.redirect = pl(Math.min(1, corr / msgs), PSIGK.redirect[5]); }
  if (s.ol != null) m.length = pl(s.ol, PSIGK.length[5]);
  return { r, m };
}
const psEmpty = () => { const o = { n: 0, r: {}, m: {}, days: {} }; PSIG.forEach((x) => { if (x[3] === 'ratio') o.r[x[0]] = [0, 0, 0, 0, 0, 0]; else o.m[x[0]] = [0, 0, 0]; }); return o; };
const psAddR = (a, k, n) => { a[0] += k; a[1] += n; a[2]++; a[3] += k * k; a[4] += k * n; a[5] += n * n; };
const psAddM = (a, v) => { a[0] += v; a[1] += v * v; a[2]++; };
// sufficient statistics of a session list (additive; per-day map {d: [sessions, agents, overlap]})
function psSuff(L) {
  const o = psEmpty(), by = {};
  L.forEach((s) => {
    const c = psContrib(s); o.n++;
    for (const k in c.r) psAddR(o.r[k], c.r[k][0], c.r[k][1]);
    for (const k in c.m) psAddM(o.m[k], c.m[k]);
    if (s.d != null) (by[s.d] = by[s.d] || []).push(s);
  });
  for (const d in by) {
    const xs = by[d], sp = xs.filter((s) => s.t0 != null && s.t1 != null).map((s) => [s.t0, s.t1]).sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    let ov = 0, end = null; for (const [a, b] of sp) { if (end != null && a < end) { ov = 1; break; } end = end == null ? b : Math.max(end, b); }
    o.days[d] = [xs.length, new Set(xs.map((s) => s.a)).size, ov];
  }
  return o;
}
// sum of blocks with disjoint agent sets (two agents on one day already make it multi-thread, so OR-ing overlap is exact)
function psCombine(parts) {
  const o = psEmpty();
  parts.forEach((p) => {
    o.n += p.n;
    for (const k in o.r) o.r[k] = o.r[k].map((v, i) => v + p.r[k][i]);
    for (const k in o.m) o.m[k] = o.m[k].map((v, i) => v + p.m[k][i]);
    for (const d in p.days) { const c = o.days[d] = o.days[d] || [0, 0, 0]; c[0] += p.days[d][0]; c[1] += p.days[d][1]; c[2] = c[2] || p.days[d][2] ? 1 : 0; }
  });
  return o;
}
// one block per agent, cached by that agent's slice of the list (count + first / last id + data revision): toggling
// other agents in the sidebar reuses the cached blocks and only sums them — nothing is precomputed per subset
const PS_CACHE = new Map();
function psByAgent(L) {
  const g = {}; L.forEach((s) => { (g[s.a] = g[s.a] || []).push(s); });
  const rev = typeof LV !== 'undefined' && LV.live ? LV.rev : 0, out = {};
  if (PS_CACHE.size > 400) PS_CACHE.clear();
  for (const a in g) {
    const xs = g[a], key = rev + '|' + a + '|' + xs.length + '|' + xs[0].id + '|' + xs[xs.length - 1].id + '|' + xs.reduce((t, s) => (t * 31 + (typeof s.d === 'number' ? s.d : 0) + (s.msgs || 0) + (s.dn || 0)) % 1000000007, 7);
    let b = PS_CACHE.get(key); if (!b) { b = psSuff(xs); PS_CACHE.set(key, b); }
    out[a] = b;
  }
  return out;
}
function psWilson(p, n) {
  if (n <= 0) return [0, 1];
  const z = PZ, den = 1 + z * z / n, c = (p + z * z / (2 * n)) / den, h = z * Math.sqrt(Math.max(0, p * (1 - p) / n + z * z / (4 * n * n))) / den;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
function psSignal(key, a) {
  const [, , w, kind, unit, an, label] = PSIGK[key];
  if (kind === 'ratio') {
    const [k, n, m, kk, kn, nn] = a; if (n <= 0) return null;
    const p = k / n, ss = kk - 2 * p * kn + p * p * nn;
    const vr = m > 1 ? m / (m - 1) * Math.max(0, ss) / (n * n) : 0;
    const ne = vr > 0 ? Math.min(n, p * (1 - p) / vr) : Math.min(n, m);
    const [lo, hi] = psWilson(p, ne), x = pl(lo, an), y = pl(hi, an);
    return { key, label, weight: w, unit, kind, raw: p, score: pl(p, an), lo: Math.min(x, y), hi: Math.max(x, y), n, ne };
  }
  const [sm, s2, m] = a; if (m <= 0) return null;
  const mean = sm / m, sd = m > 1 ? Math.sqrt(Math.max(0, (s2 - m * mean * mean) / (m - 1))) : null, half = PZ * (sd != null ? sd / Math.sqrt(m) : 25);
  return { key, label, weight: w, unit, kind, raw: null, score: mean, lo: Math.max(0, mean - half), hi: Math.min(100, mean + half), n: m, ne: m };
}
function psDays(o) {
  const r = [0, 0, 0, 0, 0, 0], pd = [0, 0, 0], ad = [0, 0, 0];
  Object.values(o.days).forEach(([n, ag, ov]) => { psAddR(r, ag >= 2 || ov ? 1 : 0, 1); psAddM(pd, pl(n, PSIGK.per_day[5])); psAddM(ad, pl(ag, PSIGK.agents_day[5])); });
  return { parallel: r, per_day: pd, agents_day: ad };
}
const PS_HI = { D: ['D', 'S'], I: ['I', 'P'], M: ['M', 'F'], V: ['V', 'T'] };
const PS_LR = { D: ['D 委托', '掌舵 S'], I: ['P 规划', '即兴 I'], M: ['M 多线', '专注 F'], V: ['V 求证', '信任 T'] };
const PS_UNIT = { D: 'turn', I: 'session_opening', M: 'active_day', V: 'turn' };
const PS_PRIMARY = { D: 'steps', I: 'struct', M: 'parallel', V: 'verify' };
function psAxis(o, ax) {
  const k = ax.k, dd = psDays(o);
  const sigs = PSIG.filter((x) => x[1] === k).map((x) => psSignal(x[0], dd[x[0]] || (x[3] === 'ratio' ? o.r[x[0]] : o.m[x[0]]))).filter(Boolean);
  let value = null, lo = 0, hi = 100, agree = null;
  if (sigs.length) {
    const W = sigs.reduce((t, x) => t + x.weight, 0);
    value = sigs.reduce((t, x) => t + x.weight * x.score, 0) / W;
    const se = Math.sqrt(sigs.reduce((t, x) => t + (x.weight * (x.hi - x.lo) / (2 * PZ)) ** 2, 0)) / W;
    lo = Math.max(0, value - PZ * se); hi = Math.min(100, value + PZ * se);
    const side = value >= 50; agree = sigs.reduce((t, x) => t + x.weight * (x.score === 50 ? 0.5 : (x.score >= 50) === side ? 1 : 0), 0) / W;
  }
  const r1 = (x) => Math.round(x * 10) / 10, prim = k === 'M' ? dd.parallel : o.r[PS_PRIMARY[k]];
  const letter = (value == null ? 50 : value) >= 50 ? PS_HI[k][0] : PS_HI[k][1];
  return { k, value: value == null ? null : r1(value), lo: r1(lo), hi: r1(hi), n_units: prim[1], k_units: prim[0], unit: PS_UNIT[k], letter,
    state: value == null ? 'no_data' : 'settled', strong: value == null ? null : Math.round(Math.max(value, 100 - value)), left: PS_LR[k][0], right: PS_LR[k][1],
    dim: ax.dim, q: ax.q, sig: sigs.length ? sigs.map((x) => x.label).join(' · ') : '暂无可用信号', agree: agree == null ? null : Math.round(agree * 100) / 100,
    signals: sigs.map((x) => ({ key: x.key, label: x.label, weight: x.weight, score: r1(x.score), raw: x.raw, n: x.n, unit: x.unit })),
    decided: value != null && (lo >= 55 || hi <= 45) };
}
// persona from sufficient statistics; conf from the session count, one level lower when the signals disagree
function personaFromSuff(o) {
  const n = o.n, days = Object.keys(o.days).length;
  if (!n) return { ok: false, classified: false, n, days, conf: '低' };
  const axes = AXES.map((ax) => psAxis(o, ax));
  const ag = axes.filter((a) => a.agree != null), consistency = ag.length ? Math.round(ag.reduce((t, a) => t + a.agree, 0) / ag.length * 100) / 100 : null;
  let lv = n >= 100 ? 2 : n >= PERSONA_SOFT_N ? 1 : 0; if (consistency != null && consistency < 0.7) lv = Math.max(0, lv - 1);
  const code = axes.map((a) => a.letter).join(''), t = TYPES[code];
  return { ok: true, classified: !!t, n, days, code, zh: t[0], en: t[1], line: t[2], hint: personaHint(n), consistency,
    v: axes.reduce((m, a) => { m[a.k] = a.value == null ? 50 : a.value; return m; }, {}), axes, conf: ['低', '中', '高'][lv], decided_axes: axes.filter((a) => a.decided).length };
}
// a session list → persona: per-agent blocks of the list, summed (so an agent subset never needs its own pass)
function personaCompose(L) { return personaFromSuff(psCombine(Object.values(psByAgent(L)))); }
function persona(L, minN) {
  const n = L.length;
  if (!n) return { ok: false, classified: false, n };   // minN 只是「按项目」的标记（live 用它走项目画像），不再是门槛
  const p = personaCompose(L);
  const st = stats(L);
  const by = {}; L.forEach((s) => { (by[s.d] = by[s.d] || []).push(s); });
  const days = Object.values(by);
  p.st = st; p.avgS = n / days.length; p.avgA = days.reduce((a, l) => a + new Set(l.map((s) => s.a)).size, 0) / days.length;
  return p;
}
function axisView(p, i) {
  const ax = AXES[i]; const val = p.v[ax.k];
  const leftIsValue = ax.k !== 'I';
  const pos = leftIsValue ? 100 - val : val;
  const strong = Math.round(Math.max(val, 100 - val));
  const leftWins = leftIsValue ? val >= 50 : val < 50;   // 恰好 50 归高值一极，与 persona() 的字母一致
  return { ax, val, pos, strong, leftWins, letter: leftWins ? ax.L : ax.R, name: leftWins ? ax.Ln : ax.Rn };
}
// 契合度只在两项信号都在时计分：没有完成信号（okKnown = 0）或没有用户消息（摩擦率无从算起）就是 null，界面显示「—」
// 并说明原因（fitWhy），不能把「没有数据」算成满分
function fitOf(L) { if (L.length < 5) return null; const st = stats(L); if (!st.okKnown || !st.msgs) return null; return Math.round(clamp(130 - st.fric * 4 - (100 - st.ok) * 1.0, 20, 98)); }
function fitWhy(st, n) { return n < 5 ? '样本少（' + n + ' 个会话），不计分' : !st.okKnown ? '没有完成信号，不计分' : !st.msgs ? '没有你发出的消息，摩擦率无从计算，不计分' : ''; }
// a completion / verification rate whose basis may be empty: n = stats().okKnown / verKnown
const pctKnown = (v, n) => (n ? Math.round(v) + '%' : '—');
// 摩擦率 / 自主比的分母是你发出的消息：msgs = 0 时是未知「—」，不是 0（live 行可能没有用户消息）
const fricTxt = (st) => (st.msgs ? f1(st.fric) + '%' : '—');
const autoTxt = (st) => (st.msgs ? f1(st.auto) : '—');
// 「AI」only for text a model wrote: live insights carry basis (l0_template = rule template); the same test as 92-live-sessions
const insIsAI = (ins) => !LV.live || !!(ins && /\b(ai|llm|model)\b/i.test(String(ins.basis || '').replace(/_/g, ' ')));
// the head badge of an insight block: purple AI, or a neutral「规则」tag for template text
const insBadge = (ai, label) => ai ? '<span class="aib">' + ic('spark', 11) + label + '</span>' : '<span class="row" style="gap:6px;flex:none;white-space:nowrap"><span class="eb">' + label.replace(/^AI ?/, '') + '</span><span class="tag" data-tip="由规则模板生成，不是 AI">规则</span></span>';
function buckets(range) {
  const w = win(range); const n = w[1] - w[0] + 1;
  if (n <= 31) return Array.from({ length: n }, (_, i) => ({ a: w[0] + i, b: w[0] + i, lbl: md(w[0] + i) }));
  const out = []; let a = w[0];
  while (a <= w[1]) { const b = Math.min(w[1], a + (6 - wd(a))); out.push({ a, b, lbl: md(a) }); a = b + 1; }
  return out;
}
function series(L, range, metric) {
  return buckets(range).map((bk) => {
    const v = AG.map((ag) => { const xs = L.filter((s) => s.a === ag.id && s.d >= bk.a && s.d <= bk.b); return metric === 'h' ? sum(xs, (s) => s.dur) / 60 : metric === 'tok' ? sum(xs, (s) => s.tok) / 1e6 : xs.length; });
    return Object.assign({}, bk, { v });
  });
}
function heat(L) { const H = Array.from({ length: 7 }, () => new Array(24).fill(0)); const C = Array.from({ length: 7 }, () => new Array(24).fill(0)); L.forEach((s) => { H[wd(s.d)][s.h] += s.msgs; C[wd(s.d)][s.h] += s.corr; }); return { H, C }; }
function toolRows(L) {
  const T = sum(L, (s) => s.tools);
  return TOOLS.map((t) => { const n = Math.round(T * t[1] / 9860); return { name: t[0], n, err: t[2], fails: Math.round(n * t[2]), avg: t[3], ap: t[4], cmds: t[5] }; });
}
function moodSeries(L, range) {
  return buckets(range).map((bk) => { const xs = L.filter((s) => s.d >= bk.a && s.d <= bk.b); const m = sum(xs, (s) => s.msgs); return Object.assign({}, bk, { n: xs.length, mood: m ? sum(xs, (s) => s.mood * s.msgs) / m : null, corr: sum(xs, (s) => s.corr), xs }); });
}
function countBy(L, key) { const m = {}; L.forEach((s) => { const k = s[key]; if (k != null) m[k] = (m[k] || 0) + 1; }); return m; }
function regress(pts) {
  const n = pts.length; if (n < 3) return null;
  const mx = sum(pts, (p) => p.x) / n, my = sum(pts, (p) => p.y) / n;
  const sxx = sum(pts, (p) => (p.x - mx) ** 2), syy = sum(pts, (p) => (p.y - my) ** 2), sxy = sum(pts, (p) => (p.x - mx) * (p.y - my));
  if (!sxx || !syy) return null;
  const b = sxy / sxx; return { b, a: my - b * mx, r: sxy / Math.sqrt(sxx * syy), n };
}
// one pass over L groups the rows by project (and counts them per agent) instead of filtering L once per project / agent
function projRows(L) {
  const by = new Map(), ai = {}; AG.forEach((a, j) => { ai[a.id] = j; });
  PJ.forEach((p) => by.set(p.id, { xs: [], split: new Array(AG.length).fill(0) }));
  L.forEach((s) => { const g = by.get(s.p); if (!g) return; g.xs.push(s); const j = ai[s.a]; if (j != null) g.split[j]++; });
  return PJ.map((p) => {
    const g = by.get(p.id); const xs = g.xs;
    return { p, xs, st: stats(xs), split: g.split, pers: persona(xs, 8) };
  });
}
function visibleRecs() { return RECS.filter((r) => r.aud <= S.recs.aud && !S.recs.gone.has(r.id)); }
// Visible recs (recOrder) and the open, not installed ones (recTop) in the order a surface shows them: A1 / menubar take visibleRecs() order, Lite sorts by saving.
// Live mode (97-live-recs.js) puts the backend's stable top slate for that surface first.
function recOrder(surface) { return surface === 'lite' ? liteOrder() : visibleRecs(); }
function recTop(surface) { return recOrder(surface).filter((r) => !S.installed.has(r.id)); }

