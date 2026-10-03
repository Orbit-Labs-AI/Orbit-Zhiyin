/* ============ live persona + A1 overview feed (slice 1) ============
   Mock mode: nothing here runs (LV.live is false), persona() stays the demo formula and PERIODS keeps the demo months.
   Live mode:
   - persona(L, minN) → personaLive: a JS port of uiview/persona.py (letter = value ≥ 50 → high pole, no undetermined band) when
     the rows carry the G1 unit counts (dk / dn / vk / op / t0 / t1). Until facts ships them, L is matched against the
     scopes the server can answer (7 / 30 / 90 / all, the last four calendar months, under the current Agent / project
     filters) and the memoised GET /v1/uiview/persona for that scope is returned; months come from that payload's
     months[]. A single-project subset uses /v1/uiview/projects[].persona. Any other subset → {ok:false} (样本不足).
   - PERIODS is rebuilt from LASTDAY's calendar months (keys YYYY-MM, which the server accepts as period=).
   - LV.ov: the /v1/uiview/overview payload for the current scope (tools top, insight); tiles / trend / heat stay
     client-derived from the spine (same formulas; parity is tested against the server).
   - LV.reveal(period): GET /v1/uiview/persona/reveal for the reveal overlay (candidates when the code is not settled). */
const LVP = { full: new Map(), mini: {}, proj: new Map(), sigKey: null, sigs: null };
const lvpSig = (L) => (L && L.length ? L.length + '|' + L[0].id + '|' + L[L.length - 1].id : '0');
// last 4 calendar months ending at LASTDAY's month: {k: 'YYYY-MM', m, y, a, b} (day indices clipped to the spine)
function lvMonths(count) {
  const t = new Date(DAY0 + LASTDAY * 86400000); const y = t.getUTCFullYear(), mo = t.getUTCMonth(); const out = [];
  for (let back = (count || 4) - 1; back >= 0; back--) {
    const f = Date.UTC(y, mo - back, 1), l = Date.UTC(y, mo - back + 1, 0); const d = new Date(f);
    out.push({ k: d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'), m: d.getUTCMonth() + 1, y: d.getUTCFullYear(),
      a: Math.max(0, Math.round((f - DAY0) / 86400000)), b: Math.min(LASTDAY, Math.round((l - DAY0) / 86400000)) });
  }
  return out;
}
function lvBuildPeriods() {
  if (!LV.live) return;
  Object.keys(PERIODS).forEach((k) => { delete PERIODS[k]; });
  lvMonths().forEach((m) => { PERIODS[m.k] = [m.a, m.b, m.m + ' 月']; });
  PERIODS['90'] = [Math.max(0, LASTDAY - 89), LASTDAY, '近 90 天'];
  PERIODS.all = [0, LASTDAY, '全部'];
  if (!PERIODS[S.persona.period]) S.persona.period = '90';
  LVP.sigKey = null;
}
// month keys the A2 / Lite evolution rows show (mock: the demo's four months)
function peMonthKeys() { return LV.live ? lvMonths().map((m) => m.k) : ['jun', 'jul', 'aug', 'sep']; }
const peCurMonth = () => { const k = peMonthKeys(); return k[k.length - 1]; };

/* ---- G1 port of uiview/persona.py (used when facts rows carry dk / dn / vk / op / t0 / t1) ---- */
function lvWilson(k, n) {
  if (n <= 0) return [0, 1];
  const z = 1.96, p = k / n, den = 1 + z * z / n, c = (p + z * z / (2 * n)) / den;
  const h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den;
  return [Math.max(0, c - h), Math.min(1, c + h)];
}
const lvHasUnits = (L) => L.length > 0 && L.every((s) => s.dn != null);
function lvUnits(L) {
  let dk = 0, dn = 0, vk = 0, ik = 0, inn = 0; const byDay = {};
  L.forEach((s) => {
    dk += s.dk || 0; dn += s.dn || 0; vk += s.vk || 0;
    if (s.op != null) { inn++; if (s.op === 0) ik++; }
    (byDay[s.d] = byDay[s.d] || []).push(s);
  });
  let multi = 0; const days = Object.values(byDay);
  days.forEach((xs) => {
    if (new Set(xs.map((s) => s.a)).size >= 2) { multi++; return; }
    const sp = xs.filter((s) => s.t0 != null && s.t1 != null).map((s) => [s.t0, s.t1]).sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    let end = null; for (const [a, b] of sp) { if (end != null && a < end) { multi++; return; } end = end == null ? b : Math.max(end, b); }
  });
  return { D: [dk, dn], I: [ik, inn], M: [multi, days.length], V: [vk, dn] };
}
const LVP_LR = { D: ['D 委托', '掌舵 S'], I: ['P 规划', '即兴 I'], M: ['M 多线', '专注 F'], V: ['V 求证', '信任 T'] };
const LVP_HI = { D: ['D', 'S'], I: ['I', 'P'], M: ['M', 'F'], V: ['V', 'T'] };
function lvPersonaCompute(L, minN) {
  const n = L.length; const days = new Set(L.map((s) => s.d)).size;
  if (!n) return { ok: false, classified: false, n, days, conf: '低' };
  const u = lvUnits(L);
  const axes = AXES.map((ax) => {
    const k = ax.k, kk = u[k][0], nn = u[k][1];
    const value = nn ? 100 * kk / nn : null; let [lo, hi] = lvWilson(kk, nn); lo = Math.round(lo * 1000) / 10; hi = Math.round(hi * 1000) / 10;
    const letter = (value == null ? 50 : value) >= 50 ? LVP_HI[k][0] : LVP_HI[k][1], state = value == null ? 'no_data' : 'settled';
    return { k, value: value == null ? null : Math.round(value * 10) / 10, lo, hi, n_units: nn, k_units: kk, letter, state,
      strong: value == null ? null : Math.round(Math.max(value, 100 - value)), left: LVP_LR[k][0], right: LVP_LR[k][1], dim: ax.dim, q: ax.q, sig: ax.sig };
  });
  const code = axes.map((a) => a.letter).join('');
  const t = TYPES[code];
  return { ok: true, classified: !!t, n, days, code, zh: t[0], en: t[1], line: t[2], hint: personaHint(n),
    v: axes.reduce((o, a) => { o[a.k] = a.value == null ? 50 : a.value; return o; }, {}), axes, conf: n >= 100 ? '高' : n >= PERSONA_SOFT_N ? '中' : '低', method: 'client-port' };
}

// per-axis evidence for the client port (same shape and formulas as uiview/persona.py evidence(); BUG R4-03)
const LVP_UNIT = { D: 'turn', I: 'session_opening', M: 'active_day', V: 'turn' };
function lvEvidence(L, p, st) {
  const hist = (vals, n, max) => { const out = new Array(n).fill(0); vals.forEach((v) => { out[Math.max(0, Math.min(n - 1, Math.floor(v / max * n)))]++; }); return out; };
  const byDay = {}; L.forEach((s) => { (byDay[s.d] = byDay[s.d] || []).push(s); }); const days = Object.values(byDay);
  const avgS = days.length ? L.length / days.length : 0, avgA = days.length ? days.reduce((a, xs) => a + new Set(xs.map((s) => s.a)).size, 0) / days.length : 0;
  const pp = {}; L.forEach((s) => { const e = pp[s.p == null ? '' : s.p] = pp[s.p == null ? '' : s.p] || [0, 0, 0, 0];
    if (s.op != null) { e[0] += s.op; e[1]++; } e[2] += s.vk || 0; e[3] += s.dn || 0; });
  const pname = (k) => (k && PJI[k] ? PJI[k].name : '未归属');
  const rank = (a, b) => Object.keys(pp).filter((k) => pp[k][b]).map((k) => [pp[k][a] / pp[k][b], k]).sort((x, y) => x[0] - y[0] || (x[1] < y[1] ? -1 : x[1] > y[1] ? 1 : 0));
  const plan = rank(0, 1), check = rank(2, 3);
  const ax = {}; p.axes.forEach((a) => { ax[a.k] = a; }); const openN = ax.I.n_units || 1;
  return {
    D: { txt: '每会话 ' + f1(st.per) + ' 条消息 · 单轮平均 ' + f1(st.auto) + ' 步', vals: hist(L.map((s) => s.msgs || 0), 10, 20), lbl: '消息数 0 → 20+ 的会话数' },
    I: { txt: '结构化开场占 ' + Math.round((openN - ax.I.k_units) / openN * 100) + '%', vals: plan.map((x) => Math.round(x[0] * 100)), lbl: '项目结构化开场占比 · 低 → 高', projects: plan.map((x) => pname(x[1])) },
    M: { txt: '日均 ' + f1(avgS) + ' 个会话 · 同日 ' + f1(avgA) + ' 个 Agent', vals: hist(days.map((xs) => xs.length), 8, 8), lbl: '每日会话数 1 → 8+ 的天数' },
    V: { txt: Math.round(st.verify) + '% 会话要求或运行了验证', vals: check.map((x) => Math.round(x[0] * 100)), lbl: '项目验证轮次占比 · 低 → 高', projects: check.map((x) => pname(x[1])) },
  };
}

/* ---- server payload → the demo's persona shape (+ axes / server extras) ---- */
function lvAvg(L) {
  const by = {}; L.forEach((s) => { (by[s.d] = by[s.d] || []).push(s); }); const d = Object.values(by);
  return { avgS: d.length ? L.length / d.length : 0, avgA: d.length ? d.reduce((a, l) => a + new Set(l.map((s) => s.a)).size, 0) / d.length : 0 };
}
function lvShape(b, L) {
  if (!b || !b.ok) return { ok: false, classified: false, n: b && b.n != null ? b.n : L ? L.length : 0, server: b || null };
  const v = {}; ['D', 'I', 'M', 'V'].forEach((k) => { const x = b.v && b.v[k]; v[k] = x == null ? 50 : x; });
  const t = TYPES[b.code];
  const out = Object.assign({}, b, { ok: true, classified: b.classified != null ? !!b.classified : !!t, n: b.n, v, code: b.code,
    zh: b.zh || (t ? t[0] : '—'), en: b.en || (t ? t[1] : ''), line: b.line || (t ? t[2] : ''), hint: b.hint !== undefined ? b.hint : personaHint(b.n),
    conf: b.conf || (b.n >= 100 ? '高' : b.n >= PERSONA_SOFT_N ? '中' : '低'), axes: b.axes || [], server: b });
  if (L) { out.st = stats(L); Object.assign(out, lvAvg(L)); }
  return out;
}
// the scopes the server answers: {period, w}; matched to a row list by signature (cached per spine rev + filters)
function lvpScopes() {
  const ag = Array.from(S.agents).sort().join(',') + '/' + Array.from(S.srcOff).sort().join(',');
  const key = LV.rev + '|' + LASTDAY + '|' + ag + '|' + (S.project || '');
  if (LVP.sigKey === key) return LVP.sigs;
  const m = new Map();
  const add = (period, w) => { const sg = lvpSig(sel({ win: w, noExtra: true })); if (!m.has(sg)) m.set(sg, period); };
  [7, 30, 90].forEach((r) => add(String(r), win(r)));
  add('all', [0, LASTDAY]);
  lvMonths().forEach((x) => add(x.k, [x.a, x.b]));
  LVP.sigKey = key; LVP.sigs = m;
  return m;
}
function lvpQuery(period) {
  const sc = LV.scope();
  return { period, agents: sc.agents ? sc.agents.join(',') : null, project: sc.project || null, display_timezone: TL_TZ || 'UTC' };
}
// days= only for a window the gateway reports ready (auto otherwise); kept out of the cache key so a window switch
// refetches in place and the last persona stays on screen until the wider one arrives
const lvpDays = (period) => LV.daysFor(LV.periodDays(period));
const lvpKey = (period) => JSON.stringify(lvpQuery(period));
// full /v1/uiview/persona payload for a period under the current filters → {state, data}; refetches (keeping the last
// data on screen) when the spine revision moved
function lvpFetch(period, path, store) {
  const key = lvpKey(period) + path;
  let e = store.get(key);
  const days = lvpDays(period);
  if (e && ((e.rev === LV.rev && e.days === days) || e.loading)) return e;
  if (!e) { e = { rev: null, loading: false, data: null, state: 'pending' }; store.set(key, e); }
  e.loading = true; const rev = LV.rev; e.days = days;
  TL.get(path, { query: Object.assign(lvpQuery(period), { days }) }).then((res) => {
    e.loading = false;
    if (res.state === 'computing' || res.data == null) { e.loading = true; setTimeout(() => { e.loading = false; e.rev = null; TL.changed(); }, 1200); return; }
    e.rev = rev; e.data = res.data; e.state = 'ready';
    if (path === '/v1/uiview/persona') {
      (res.data.months || []).forEach((x) => { LVP.mini[lvpKey(x.k)] = x; });
    }
  }, (err) => {
    e.loading = false; e.rev = rev; e.state = e.data ? 'ready' : 'error'; e.error = err;
    // 422 analysis_scope_too_large: the window is too big → refetch with 30 days (then 7)
    if (err && err.code === 'analysis_scope_too_large' && !LV.tooLarge.has(days != null ? days : LV.window ? LV.window.days : 0)) { LV.scopeTooLarge(days); e.rev = null; e.state = e.data ? 'ready' : 'pending'; }
  }).then(() => TL.changed());
  return e;
}
LV.personaFor = function (period, L) {
  const e = lvpFetch(period, '/v1/uiview/persona', LVP.full);
  if (e.data) return lvShape(e.data, L);
  if (e.state === 'error') return { ok: false, classified: false, n: L ? L.length : 0, error: true };
  return { ok: false, classified: false, n: L ? L.length : 0, pending: true };
};
LV.reveal = function (period) { return lvpFetch(period, '/v1/uiview/persona/reveal', LVP.full); };
// single-project subsets: /v1/uiview/projects[].persona (persona_pending until the backend computes it → 样本不足)
function lvProjPersona(pid, L) {
  const sc = LV.scope(); const path = LV.withQuery('/v1/uiview/projects', { range: sc.range, agent: sc.agents, display_timezone: TL_TZ || 'UTC' });
  let e = LVP.proj.get(path);
  if (!e || (e.rev !== LV.rev && !e.loading)) {
    e = e || { rev: null, loading: false, map: {} }; LVP.proj.set(path, e); e.loading = true; const rev = LV.rev;
    TL.get(path).then((res) => {
      e.loading = false; if (res.data == null) return; e.rev = rev; e.map = {};
      (res.data.projects || []).forEach((p) => { e.map[p.project_id || p.id] = p.persona || null; });
    }, () => { e.loading = false; e.rev = rev; }).then(() => TL.changed());
  }
  const pp = e.map[pid];
  if (pp && pp.code && pp.v) return lvShape(Object.assign({ ok: true, n: pp.n || L.length }, pp), L);
  return { ok: false, classified: false, n: L.length };
}
function personaLive(L, minN) {
  L = L || [];
  if (lvHasUnits(L)) {
    const p = lvPersonaCompute(L, minN);
    if (p.ok) { p.st = stats(L); Object.assign(p, lvAvg(L)); const ev = lvEvidence(L, p, p.st); p.axes.forEach((a) => { a.unit = LVP_UNIT[a.k]; a.evidence = ev[a.k]; }); }
    return p;
  }
  if (!L.length) return { ok: false, classified: false, n: 0 };
  const period = lvpScopes().get(lvpSig(L));
  if (period) {
    const full = LVP.full.get(lvpKey(period) + '/v1/uiview/persona');
    if (full && full.data) return lvShape(full.data, L);
    const mini = LVP.mini[lvpKey(period)];
    if (mini) return lvShape(mini, L);
    // calendar months arrive with a period payload's months[]; only an explicitly shown month (A2) fetches its own
    if (/^\d{4}-\d{2}$/.test(period)) return { ok: false, classified: false, n: L.length, pending: true };
    return LV.personaFor(period, L);
  }
  const p0 = L[0].p;
  if (minN && L.every((s) => s.p === p0)) return lvProjPersona(p0, L);
  return { ok: false, classified: false, n: L.length };
}

/* ---- A1 overview feed: tools top + insight for the current scope ---- */
LV.ov = null;
if (LV.live) {
  persona = personaLive;
  lvBuildPeriods();
  S.ov.synced = '已同步';
  const h0 = LV.hydrate;
  LV.hydrate = function (spine) { const r = h0.call(this, spine); lvBuildPeriods(); LV.syncedAt = Date.now(); return r; };
  // days = the range's window once the gateway reports it ready (全部 → 0); auto otherwise, with the strip's hint
  LV.feed(['overview', 'l-home'], (sc) => [{ name: 'ov', path: LV.withQuery('/v1/uiview/overview', { range: sc.range, agents: sc.agents ? sc.agents.join(',') : null, project: sc.project,
    topic: sc.topic, outcome: sc.outcome, fric: sc.fric, hour: sc.hour, display_timezone: sc.tz || 'UTC', days: LV.daysFor(LV.rangeDays(sc.range)) }) }],
  (d) => { LV.ov = d.ov || null; });

  /* 「AI 生成 / 重新生成」：POST /v1/ai/jobs 提交 narrate.overview（scope 即 insight.ai_scope，fresh 跳过缓存，
     真实调用一次本地 Agent），轮询到结束后让 overview 重新读取；卡片只在后端读回模型写成的结果
     （basis=ai_narrative）时才换成 AI 文字。未开启 AI、引擎不可用、未授权、超出今日花费上限、模型输出未通过校验
     都如实提示，卡片保持规则模板，不在前端重放旧文字冒充新结果。 */
  const OV_REGEN_ERR = {
    ai_disabled: 'AI 未开启：在 设置 › 分析 选择执行者后再生成',
    engine_unavailable: '本地 Agent 不可用（未安装或未登录），卡片保持规则模板',
    budget_exhausted: '今日 AI 花费已达上限，明天再试或在 设置 › 分析 调整上限',
    over_budget: '上下文超出预算，暂时无法生成',
    invalid_scope: '当前范围无法生成 AI 解读'
  };
  LV.ovRegen = null;
  ACT.regen = () => {
    const ins = LV.ov && LV.ov.insight;
    if (!ins || !ins.ai_scope) { toast('「全部」或带筛选的视图暂不生成 AI 解读：切到 7 / 30 / 90 天并清除筛选'); return; }
    if (LV.ovRegen) { toast('AI 解读正在生成'); return; }
    const scope = {}; Object.keys(ins.ai_scope).forEach((k) => { if (ins.ai_scope[k] != null) scope[k] = ins.ai_scope[k]; });
    const say = (h) => { const g = $('[data-aigen]'); if (g) g.innerHTML = h; };
    const spin = (t) => say('<span class="spin" style="width:10px;height:10px;vertical-align:-1px"></span> ' + esc(t));
    const run = LV.ovRegen = { key: JSON.stringify(scope) };
    const back = () => { if (LV.ovRegen === run) LV.ovRegen = null; if (S.route === 'overview' || S.route === 'l-home') render(); };
    spin('已提交给本地 Agent…');
    TL.send('POST', '/v1/ai/jobs', { task_id: 'narrate.overview', scope, fresh: true }).then((r) => {
      const d = r.data || {}; if (!d.job_id) throw Object.assign(new Error('没有返回作业'), { code: 'no_job' });
      return TL.pollJob(d.job_id, (job) => { if (job.status === 'running') spin('本地 Agent 生成中…'); });
    }).then((job) => {
      if (job.status === 'ok') {
        TL.invalidate((x) => String(x.path).indexOf('/v1/uiview/overview') === 0);
        toast('AI 解读已更新');
      } else if (job.status === 'fallback') {
        const st = (job.stages || []).find((x) => x.status === 'failed');
        toast('模型这次没有写出可用的解读' + (st && st.message ? '（' + st.message + '）' : '') + '，卡片保持规则模板');
      } else if (job.status === 'cancelled') toast('AI 解读已取消');
      else toast('AI 解读生成失败：' + (job.error || job.status));
      back();
    }, (e) => {
      if (e.code === 'consent_required') toast('需要先授权这些数据类：' + ((e.detail && e.detail.missing) || []).join('、'), { act: '去授权', onAct: () => openSettings('analysis') });
      else if (TL.unavailable(e) && !OV_REGEN_ERR[e.code]) toast('本地服务暂不提供 AI 解读，卡片保持规则模板');
      else toast(OV_REGEN_ERR[e.code] || ('AI 解读生成失败：' + (e.message || e.code)), e.code === 'ai_disabled' || e.code === 'budget_exhausted' ? { act: '去设置', onAct: () => openSettings('analysis') } : undefined);
      back();
    });
  };
}
