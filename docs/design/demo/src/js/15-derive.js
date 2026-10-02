/* ============ derived data ============ */
function win(range) { return range === 7 ? [113, 119] : range === 30 ? [90, 119] : range === 90 ? [30, 119] : [0, 119]; }
function prevWin(range) { if (!range) return null; const w = win(range); const a = w[0] - range; return a < 0 ? null : [a, w[0] - 1]; }
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
function stats(L) {
  const n = L.length, mins = sum(L, (s) => s.dur), msgs = sum(L, (s) => s.msgs), tools = sum(L, (s) => s.tools);
  const errors = sum(L, (s) => s.errors), corr = sum(L, (s) => s.corr);
  return { n, hours: mins / 60, msgs, tools, errors, corr, tok: sum(L, (s) => s.tok), auto: msgs ? tools * 1.54 / msgs : 0, fric: msgs ? corr / msgs * 100 : 0, per: n ? msgs / n : 0, verify: n ? L.filter((s) => s.verify).length / n * 100 : 0, ok: n ? L.filter((s) => s.out === 'ok').length / n * 100 : 0, err: tools ? errors / tools * 100 : 0 };
}
function persona(L, minN) {
  const n = L.length;
  if (n < (minN || 30) || !n) return { ok: false, classified: false, n };
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
  const code = ['D', 'I', 'M', 'V'].map((k, i) => v[k] >= 55 ? pairs[i][0] : v[k] <= 45 ? pairs[i][1] : '?').join('');
  const t = TYPES[code];
  return { ok: true, classified: !!t, n, v, code, zh: t ? t[0] : '尚未定型', en: t ? t[1] : 'Undetermined', line: t ? t[2] : '有维度落在 45–55 之间，暂不下结论。', st, avgS, avgA, conf: n >= 100 ? '高' : n >= 30 ? '中' : '低' };
}
function axisView(p, i) {
  const ax = AXES[i]; const val = p.v[ax.k];
  const leftIsValue = ax.k !== 'I';
  const pos = leftIsValue ? 100 - val : val;
  const strong = Math.round(Math.max(val, 100 - val));
  const leftWins = pos < 50;
  return { ax, val, pos, strong, leftWins, letter: leftWins ? ax.L : ax.R, name: leftWins ? ax.Ln : ax.Rn };
}
function fitOf(L) { if (L.length < 5) return null; const st = stats(L); return Math.round(clamp(130 - st.fric * 4 - (100 - st.ok) * 1.0, 20, 98)); }
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
function projRows(L) {
  return PJ.map((p) => {
    const xs = L.filter((s) => s.p === p.id); const st = stats(xs);
    const split = AG.map((a) => xs.filter((s) => s.a === a.id).length);
    return { p, xs, st, split, pers: persona(xs, 8) };
  });
}
function visibleRecs() { return RECS.filter((r) => r.aud <= S.recs.aud && !S.recs.gone.has(r.id)); }

