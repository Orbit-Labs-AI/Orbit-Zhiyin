/* ============ live binding: A6 sentiment + command palette search (slice 4) ============
   Mock mode changes nothing: every hook in 45-a6-sentiment.js / 52-palette.js is `LV.live ? … : <mock>` and the feed below
   only registers in live mode.
   - A6: GET /v1/uiview/sentiment (days / agent / project_id / tz, bucket=day) feeds the polished page. Daily server buckets
     are folded into the page's own buckets(S.range); a multi-day (weekly) bucket keeps only the explicit-n weighted median,
     never a made-up P25–P75 band. mood is null until gap G2 lands: glyphs read "—" and, with every bucket null, the mood
     distribution is hidden (only the correction bars remain). Topic / outcome / friction / hour filters are not applied by
     the server (G3), so the page says so. PHRASES / DRIVERS / QUOTES are rewritten in place for the other readers.
   - Palette: routes, projects and sessions come from the local spine at once; GET /v1/search adds sessions, messages,
     commands, files, projects, recommendations and library items (debounced, LRU per query) and each result opens its
     ref.page. Phrase sources on A6 use the same endpoint (kinds=message). Missing endpoints render an honest empty state. */
const LVS = { sent: null, search: LV.lru(30), timer: null, want: null };
const LVS_DAY = 86400000;
const lvsDayIdx = (iso) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - DAY0) / LVS_DAY) : null; };
const lvsMood = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + f1(v));

/* ---- A6 ---- */
function lvSentApply(d) {
  LVS.sent = d || null;
  if (!d) return;
  // in-place rewrites for other readers (vizkit gallery, A3 mock sayings): real phrases, ok drivers, typical quotes
  const ph = (d.phrases || []).slice().sort((a, b) => b.n - a.n);
  PHRASES.length = 0; ph.slice(0, 8).forEach((p) => PHRASES.push([p.text, p.n, p.category || '其他']));
  DRIVERS.length = 0; (d.drivers || []).filter((x) => x.status === 'ok' && x.diff != null).forEach((x) => DRIVERS.push([x.label, x.diff]));
  const q = (t) => '「' + t + '」';
  QUOTES.neg.length = 0; QUOTES.pos.length = 0; QUOTES.mid.length = 0;
  ph.filter((p) => p.category === '纠偏').forEach((p) => QUOTES.neg.push(q(p.text)));
  (d.friction || []).forEach((f) => (f.typical || []).forEach((t) => { if (QUOTES.neg.indexOf(q(t)) < 0) QUOTES.neg.push(q(t)); }));
  ph.filter((p) => p.category === '验证').forEach((p) => QUOTES.pos.push(q(p.text)));
  ph.filter((p) => p.category !== '纠偏' && p.category !== '验证').slice(0, 6).forEach((p) => QUOTES.mid.push(q(p.text)));
}
if (LV.live) {
  LV.feed('sentiment', (sc) => [{ name: 's', path: LV.withQuery('/v1/uiview/sentiment', {
    days: [7, 30, 90].indexOf(sc.range) >= 0 ? sc.range : Math.min(730, LASTDAY + 1), agent: sc.agents,
    project_id: sc.project && sc.project !== '_none' ? sc.project : null, tz: sc.tz, bucket: 'day' }) }], (d) => lvSentApply(d.s));
}
// the page's view model: {state:'ready'|'pending'|'error', lang, ms, allNull, fr, tp, phrases, drivers, note, scope}
function lvSentView(L) {
  const d = LVS.sent;
  if (!d) { const st = LV.feedState('sentiment'); return { state: st === 'error' ? 'error' : 'pending' }; }
  const mix = d.language_mix || {}; const mn = mix.n || 0; const pc = (k) => Math.round((mix[k] || 0) / mn * 100) + '%';
  const lang = mn ? '你的消息 · 中文 ' + pc('zh') + ' · 英文 ' + pc('en') + ' · 混合 ' + pc('mixed') : '你的消息 · 暂无可分析的消息';
  const byDay = {}; (d.series || []).forEach((x) => { const i = lvsDayIdx(x.bucket); if (i != null) byDay[i] = x; });
  const ms = buckets(S.range).map((bk) => {
    const xs = L.filter((s) => s.d >= bk.a && s.d <= bk.b); const hits = [];
    for (let i = bk.a; i <= bk.b; i++) if (byDay[i]) hits.push(byDay[i]);
    const n = hits.length ? sum(hits, (h) => h.n_sessions || 0) : xs.length; const corr = hits.length ? sum(hits, (h) => h.corr || 0) : sum(xs, (s) => s.corr);
    const withMood = hits.filter((h) => h.p50 != null); let dist = null;
    if (withMood.length === 1 && bk.a === bk.b) { const h = withMood[0]; dist = { n: h.explicit_n || 1, p25: h.p25, p50: h.p50, p75: h.p75 }; }
    else if (withMood.length) { const w = sum(withMood, (h) => h.explicit_n || 1); dist = { n: w, p25: null, p50: sum(withMood, (h) => h.p50 * (h.explicit_n || 1)) / w, p75: null }; }
    return Object.assign({}, bk, { n, corr, xs, dist, mood: dist ? dist.p50 : null });
  });
  const fr = (d.friction || []).filter((f) => f.sessions > 0).slice().sort((a, b) => b.sessions - a.sessions)
    .map((f) => ({ k: f.label || f.type, type: f.type, n: f.sessions, prev: f.prev != null ? f.prev : null, mood: f.avg_balance, typical: f.typical || [], uids: f.session_uids || [] }));
  const tp = (d.topics || []).filter((t) => t.sessions > 0).slice().sort((a, b) => b.sessions - a.sessions)
    .map((t) => ({ k: t.id, label: t.label || t.id, n: t.sessions, mood: t.avg_balance, uids: t.session_uids || [] }));
  const phrases = (d.phrases || []).slice().sort((a, b) => b.n - a.n).slice(0, 8).map((p) => [p.text, p.n, p.category || '其他']);
  const drivers = (d.drivers || []).map((x) => ({ name: x.label, v: x.status === 'ok' ? x.diff : null, n: x.n_a, nb: x.n_b, ci: x.status === 'ok' && x.lo != null && x.hi != null ? Math.abs(x.hi - x.lo) / 2 : 0, status: x.status }));
  const x = []; if (S.topic) x.push('主题'); if (S.outcome) x.push('结果'); if (S.fric) x.push('摩擦'); if (S.hour != null) x.push('时段');
  return { state: 'ready', meta: d.meta || {}, lang, ms, allNull: !ms.some((b) => b.dist), fr, tp, phrases, drivers, note: d.drivers_note || '', scope: x.length ? x.join(' / ') + '筛选不计入情绪统计' : '' };
}
// cards in their own layout while the endpoint is pending / missing (no table, no mock rows)
function lvSentShell(V) {
  const body = (h) => (V.state === 'error' ? '<div class="col" style="gap:6px;padding:8px 0">' + LV.na('暂无数据') + '</div>' : LV.pend(h));
  const card = (t, h) => '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">' + t + '</span></div></div>' + body(h) + '</div>';
  return '<div class="stack" data-lv-sent="' + V.state + '">' + card('情绪分布与纠偏', 236) + '<div class="two sn-two">' + card('摩擦分类', 160) + card('语义主题', 160) + '</div><div class="two" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">' + card('你的高频反馈语', 160) + card('情绪的前因', 160) + '</div></div>';
}
// 摩擦 click: the server taxonomy is not the spine's fric column, so filter only when the spine knows the label;
// otherwise open the newest session of that friction type
function lvFricGo(el) {
  const k = el.dataset.k;
  if (ALL.some((s) => s.fric === k)) return false;
  const V = LVS.view; const f = V && V.fr ? V.fr.find((x) => x.k === k) : null;
  const xs = (f ? f.uids : []).map((u) => BYID[u]).filter(Boolean).sort((a, b) => (b.d - a.d) || (b.h - a.h));
  if (!xs.length) { toast('「' + k + '」的会话不在当前数据中'); return true; }
  ACT.openSession({ dataset: { id: xs[0].id } }); toast('已打开「' + k + '」最近的一次会话（共 ' + f.n + ' 个）');
  return true;
}
function lvFricTip(k) {
  const V = LVS.view; const f = V && V.fr ? V.fr.find((x) => x.k === k) : null;
  if (!f || !f.typical.length) return '';
  return '<b>「' + esc(k) + '」典型表述</b>\n' + f.typical.slice(0, 3).map((t) => '「' + esc(t) + '」').join('\n') + '\n<span style="opacity:.7">' + f.n + ' 个会话 · 点击回看</span>';
}
// phrase sources: /v1/search?kinds=message for the phrase, mapped to spine sessions
function lvPhrase(el) {
  const k = el.dataset.k; const path = LV.withQuery('/v1/search', { q: k.slice(0, 200), kinds: 'message', limit: 20 });
  const show = (res) => {
    const seen = new Set(); const xs = [];
    ((res && res.results) || []).forEach((h) => { const s = BYID[h.session_uid]; if (s && !seen.has(s.id)) { seen.add(s.id); xs.push(s); } });
    xs.sort((a, b) => (b.d - a.d) || (b.h - a.h));
    const top = xs.slice(0, 3);
    openDD(el, [{ h: '「' + k + '」的出处（' + top.length + ' 次 · 已脱敏）' }].concat(top.length ? top.map((s) => ({ t: md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + s.title, v: s.id })) : [{ t: res ? '当前数据中没有出处' : '本机搜索暂不可用', v: null, dis: true }]), (v) => { if (!v) return; ACT.openSession({ dataset: { id: v } }); });
  };
  TL.get(path).then((r) => show(r.data), () => show(null));
}

/* ---- palette search ---- */
const LVS_GROUP = { session: '会话', message: '消息', command: '命令', file: '文件', project: '项目', recommendation: '建议', catalog: '资源库', inventory: '资源库', event: '消息' };
const LVS_ICON = { session: 'sessions', message: 'sessions', command: 'term', file: 'file', project: 'projects', recommendation: 'recs', catalog: 'library', inventory: 'library', event: 'sessions' };
function lvSearchFetch(q) {
  if (LVS.search.get(q)) return;
  const e = LVS.search.set(q, { state: 'pending', data: null });
  TL.get(LV.withQuery('/v1/search', { q, limit: 20 })).then((r) => { e.state = 'ready'; e.data = r.data || { results: [] }; },
    (err) => { e.state = 'error'; e.error = err; }).then(() => { if (PAL && PAL.q.trim() === q && !$('#modal').hidden) drawPal(); });
}
function lvSearchGet(q) {
  const hit = LVS.search.get(q); if (hit) return hit;
  clearTimeout(LVS.timer); LVS.want = q;
  LVS.timer = setTimeout(() => { if (LVS.want === q) lvSearchFetch(q); }, 140);
  return { state: 'pending' };
}
// ref.page → screen
function lvOpenRef(h) {
  const ref = h.ref || {}; const page = ref.page; const id = ref.id || h.id;
  if (page === 'session') { const sid = BYID[id] ? id : h.session_uid; if (BYID[sid]) { ACT.openSession({ dataset: { id: sid } }); return; } toast('该会话不在当前数据中（可能已排除或来源已停用）'); return; }
  if (page === 'project') { const pid = PJI[id] ? id : h.project_id; if (PJI[pid]) { S.proj.sel = pid; go('projects'); } else { go('projects'); toast('该项目在当前范围内没有会话'); } return; }
  if (page === 'recs') { const r = RECI[id] || RECS.find((x) => x.key === ref.rec_key || x.rec_key === ref.rec_key); if (r) { ACT.openRec({ dataset: { id: r.id } }); return; } go('recs'); return; }
  if (page === 'library' || page === 'local_library') { if (page === 'local_library') S.lib.tab = 'local'; S.lib.q = h.title || ''; go('library'); return; }
  toast('无法打开这条结果');
}
// server rows for palItems: [{g, t, sub, icon, run}] in palette group order, deduped against the local spine rows
function lvSearchItems(q, have) {
  if (!q) return [];
  const e = lvSearchGet(q);
  if (e.state === 'pending') return [{ g: '搜索', t: '正在搜索本机索引…', icon: 'search', pend: true, run: () => {} }];
  if (e.state === 'error') return [{ g: '搜索', t: '本机搜索暂不可用', sub: (e.error && (e.error.code || e.error.status)) ? '错误 ' + (e.error.code || e.error.status) : '', icon: 'info', run: () => {} }];
  const res = (e.data && e.data.results) || []; const out = [];
  const order = ['session', 'project', 'message', 'command', 'file', 'recommendation', 'catalog', 'inventory', 'event'];
  order.forEach((kind) => res.filter((h) => h.kind === kind).forEach((h) => {
    const key = kind === 'project' ? 'p:' + (h.project_id || h.id) : kind === 'session' ? 's:' + (h.session_uid || h.id) : kind + ':' + h.id;
    if (have.has(key)) return; have.add(key);
    const s = BYID[h.session_uid]; const ag = h.agent ? LV.agentOf(h.agent) : null;
    const when = s ? md(s.d) + ' ' + hm(s.h, s.mi) : '';
    const sub = kind === 'session' ? [ag && (AGI[ag.id] || ag).name, s && PJI[s.p] && PJI[s.p].name, when].filter(Boolean).join(' · ')
      : kind === 'project' ? (PJI[h.project_id] && PJI[h.project_id].path) || ''
      : [h.snippet && h.snippet !== h.title ? h.snippet : null, s ? s.title : null, when].filter(Boolean).join(' · ');
    out.push({ g: LVS_GROUP[kind] || '结果', t: h.title || h.snippet || h.id, sub, icon: LVS_ICON[kind] || 'search', run: () => lvOpenRef(h) });
  }));
  if (e.data && e.data.partial && e.data.partial.length && !out.length) out.push({ g: '搜索', t: '索引仍在建立，结果可能不完整', icon: 'info', run: () => {} });
  return out;
}
function lvRuleGoal() {
  const V = LVS.view; const xs = V && V.phrases ? V.phrases.filter((p) => p[2] === '纠偏').slice(0, 4) : [];
  return '把我的高频纠偏写成 AGENTS.md 规则' + (xs.length ? '：' + xs.map((p) => '「' + p[0] + '」').join('') : '') + '。';
}
// merge the server rows into the palette list: a hit joins the end of its group when that group is already listed
function lvSearchMerge(out, q, have) {
  lvSearchItems(q, have).forEach((it) => {
    let at = -1; for (let i = out.length - 1; i >= 0; i--) if (out[i].g === it.g) { at = i; break; }
    if (at < 0) out.push(it); else out.splice(at + 1, 0, it);
  });
}
