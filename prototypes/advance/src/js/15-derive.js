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
// 1 个会话即可出结论（0 个才是空态）；每个维度以 50 为界取一极，恰好 50 归高值一极（D / I / M / V），始终给完整 4 字母
const PERSONA_SOFT_N = 30;
const personaHint = (n) => (n > 0 && n < PERSONA_SOFT_N ? '基于 ' + n + ' 个会话，数据越多越准' : null);
function persona(L, minN) {
  const n = L.length;
  if (!n) return { ok: false, classified: false, n };   // minN 只是「按项目」的标记（live 用它走项目画像），不再是门槛
  const st = stats(L);
  const mins = st.hours * 60 || 1;
  const by = {}; L.forEach((s) => { (by[s.d] = by[s.d] || []).push(s); });
  const days = Object.values(by);
  const avgS = n / days.length;
  const avgA = days.reduce((a, l) => a + new Set(l.map((s) => s.a)).size, 0) / days.length;
  const v = {
    D: clamp(50 + (st.auto - 8) * 5.8, 4, 96),
    I: clamp(sum(L, (s) => PJI[s.p].I * s.dur) / mins, 4, 96),
    M: clamp(20 + 7 * avgS + 5 * avgA - 6, 4, 96),
    V: clamp(sum(L, (s) => PJI[s.p].V * s.dur) / mins, 4, 96)
  };
  const pairs = [['D', 'S'], ['I', 'P'], ['M', 'F'], ['V', 'T']];
  const code = ['D', 'I', 'M', 'V'].map((k, i) => v[k] >= 50 ? pairs[i][0] : pairs[i][1]).join('');
  const t = TYPES[code];
  return { ok: true, classified: !!t, n, v, code, zh: t[0], en: t[1], line: t[2], st, avgS, avgA, conf: n >= 100 ? '高' : n >= PERSONA_SOFT_N ? '中' : '低', hint: personaHint(n) };
}
function axisView(p, i) {
  const ax = AXES[i]; const val = p.v[ax.k];
  const leftIsValue = ax.k !== 'I';
  const pos = leftIsValue ? 100 - val : val;
  const strong = Math.round(Math.max(val, 100 - val));
  const leftWins = leftIsValue ? val >= 50 : val < 50;   // 恰好 50 归高值一极，与 persona() 的字母一致
  return { ax, val, pos, strong, leftWins, letter: leftWins ? ax.L : ax.R, name: leftWins ? ax.Ln : ax.Rn };
}
function fitOf(L) { if (L.length < 5) return null; const st = stats(L); return Math.round(clamp(130 - st.fric * 4 - (st.okKnown ? 100 - st.ok : 0) * 1.0, 20, 98)); }
// a completion / verification rate whose basis may be empty: n = stats().okKnown / verKnown
const pctKnown = (v, n) => (n ? Math.round(v) + '%' : '—');
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

