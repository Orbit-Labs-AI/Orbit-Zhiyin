/* ============ live binding: A9 生成工坊 · 问本地 Agent · 设置 · 通知（OrbitLive studio-settings section） ============
   Loaded after 96-live-bind.js; only active in live mode. The demo pages keep their markup and visual language: live data is
   written into the same structures the demo renders from (CTX / GEN / STEP_DUR / S.notif / S.paused / S.aiCh …) or patched
   into the rendered cards, never into a new layout. Personal data never falls back to demo values: a route the gateway does
   not serve (404 / 501 / 503 / offline) leaves the studio context empty, the generation and ask flows answer honestly that
   the service is unavailable, storage sizes read "—" and the source list falls back to the spine's real agents. Only plain
   configuration defaults (notify matrix, AI 通道) keep their demo values with the 示例数据 badge. Real answers (403
   consent_required → the consent dialog, 409 preview_stale, 422 …) are shown as they are. */
const TLS = { colFrame: null, engine: null, engInit: false, preview: null, previewKey: null, previewBusy: false, limit: null, ctl: null, genDemo: {}, durDemo: null, ask: null, hold: false, attnAt: null, doneT: null };
const TLS_TASK = { Skill: 'generate.skill', Hook: 'generate.hook', '规则': 'generate.rule', '子代理': 'generate.subagent', '工作流': 'generate.glue' };
const TLS_STAGE = { pack: 0, analyse: 1, analyze: 1, draft: 2, check: 3, replay: 4, review: 5, cross: 6 };
const TLS_DONE = ['done', 'ok', 'succeeded', 'completed', 'skipped'];
// notification types (backend names first, then the aliases it accepts) for the matrix rows of settings › 通知
const TLS_KIND = { waiting: ['awaiting_approval', 'waiting'], done: ['just_finished', 'done', 'session_done'], stuck: ['failing', 'stuck'], ctx: ['context_pressure', 'ctx'], weekly: ['weekly', 'weekly_report'] };
const TLS_ART_KIND = { skill: 'Skill', hook: 'Hook', rule: '规则', subagent: '子代理', glue: '工作流', command: '命令' };
const tlsKind = (type) => Object.keys(TLS_KIND).find((k) => TLS_KIND[k].indexOf(type) >= 0) || null;
const tlsAgOf = (eid) => Object.keys(OrbitLive.AGENT_KEYS).find((a) => OrbitLive.AGENT_KEYS[a].indexOf(eid) >= 0) || null;
// display name of an engine id (「Claude Code」, not claude_code): the engines list first, then the app's agent table
const tlsEngName = (id) => {
  if (!id) return null;
  const d = TL.resource('/v1/ai/engines').data; const e = d && d.engines && d.engines.find((x) => x.id === id);
  if (e && e.name) return e.name;
  const a = tlsAgOf(id); const g = a && AG.find((x) => x.id === a); return g ? g.name : String(id).replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
};
function tlsRes(path, query) { const r = TL.resource(path, { query }); if (r.dirty && !r.loading) TL.load(r); return r; }
const tlsDemo = (r) => !!(r && r.data == null && r.error && TL.unavailable(r.error));
function tlsBytes(n) { if (n == null || !Number.isFinite(n)) return TLU.DASH; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; } return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + ' ' + u[i]; }
function tlsDate(ts) { const d = new Date(ts); return isNaN(d) ? TLU.DASH : (d.getMonth() + 1) + '/' + String(d.getDate()).padStart(2, '0'); }
function tlsErr(e, what) { toast(what + '失败：' + (e.message || e.code)); }
// Serialize writes to the same resource. Keep later clicks visible while an earlier request is in flight;
// neither an older response nor a rollback may undo the user's latest choice.
const TLS_WRITES = new Map();
function tlsWriteView(w) {
  let value = w.base;
  w.pending.forEach((p) => { value = p.patch(value); });
  w.resource.data = value;
}
function tlsWrite(path, patch, req, label, ok, field) {
  const r = TL.resource(path); if (r.data == null) return false;
  let w = TLS_WRITES.get(path);
  if (!w) { w = { resource: r, base: r.data, pending: [], tail: Promise.resolve() }; TLS_WRITES.set(path, w); }
  const apply = (value, update) => field ? Object.assign({}, value, { [field]: Object.assign({}, value[field], update) }) : Object.assign({}, value, update);
  const p = { patch: (value) => apply(value, patch) };
  r.mutationVersion = (r.mutationVersion || 0) + 1;
  w.pending.push(p); tlsWriteView(w);
  w.tail = w.tail.then(req).then((x) => {
    w.base = apply(w.base, x && x.data && typeof x.data === 'object' ? x.data : patch);
    if (ok) ok(x && x.data);
  }, (e) => {
    toast(TL.unavailable(e) ? label + '未保存：本地服务暂不可用' : label + '失败：' + (e.message || e.code));
  }).finally(() => {
    r.mutationVersion++;
    w.pending.shift(); tlsWriteView(w);
    if (!w.pending.length) TLS_WRITES.delete(path);
    TLS.stateAt = null;
    render();
  });
  return true;
}

if (TL.mode === 'live') {
  /* ---------- A9 生成工坊 ---------- */
  // no demo context in live mode: the items keep their keys and switches, everything else waits for POST /v1/ai/preview
  [['sum', '相关会话摘要', '只含结构化统计与 AI 摘要，不含原文'], ['fric', '摩擦与纠偏统计', '等待上下文预览'], ['rules', '现有规则文件', '等待上下文预览'], ['raw', '原始对话片段', '默认关闭；开启后逐条确认']].forEach((x) => {
    const c = CTX.find((y) => y[0] === x[0]); if (c) { c[1] = x[1]; c[2] = x[2]; c[3] = 0; } CTX_HITS[x[0]] = 0; CTX_SAMPLE[x[0]] = [];
  });
  // the demo's prefilled goal quotes a demo rec (「PR 收尾」): live starts with an empty goal until the user writes one or
  // picks a real rec (recToStudio sets goal + from)
  if (S.studio.from === 'A7 建议「PR 收尾」') { S.studio.goal = ''; S.studio.from = ''; }
  Object.assign(STUDIO_COPY, { mine: '从你的会话提炼可执行规则', replay: '历史会话回放 · 第二视角评分', hist: 0, detected: '正在检测本地 Agent…' });
  ctxBundle = function () { return TLS.preview || { goal: S.studio.goal, type: S.studio.type, items: [] }; };
  TL.bind('studio', [{ name: 'engines', path: '/v1/ai/engines', scope: false }], (d) => d.engines);
  const engines = () => { const v = TL_VIEWS.studio; const d = v && v.res.engines.data; return d && d.engines ? d : null; };
  const tlsEngine = () => { const d = engines(); if (!d) return null; if (TLS.engine) return TLS.engine; const e = d.engines.find((x) => tlsAgOf(x.id) === S.studio.agent); return e ? e.id : d.default_engine; };
  studioRunner = function () {
    const d = engines(); const id = tlsEngine(); const e = d && id ? d.engines.find((x) => x.id === id) : null;
    return e ? { name: e.name || id, cli: e.name || id } : agent(S.studio.agent);
  };
  const tlsSel = () => { const items = {}; CTX.forEach((c) => { items[c[0]] = !!S.studio.ctx[c[0]]; }); return { items }; };
  // a typed goal is a manual goal: the gateway then searches the index for it (evidence) and packs the text itself; an
  // empty goal stays 'ask' (a manual one is a 422 goal_required) so the item list still renders before the user writes one
  const tlsGoal = () => { const g = S.studio.goal.trim(); return { goal: g, goal_source: g ? 'manual' : 'ask' }; };
  const tlsPreviewKey = () => [S.studio.type, tlsEngine(), S.studio.tpl, JSON.stringify(tlsSel()), S.studio.goal.trim()].join('|');
  // the pack previews are compact dumps (`key: value` per field, JSON-quoted strings): drop empty fields, unquote strings,
  // name the fields, and leave out the goal's own bookkeeping (source) — the goal text is what gets sent
  const TLS_FIELD = { text: '', command_heads: '命令', file_exts: '文件类型', verify_commands: '验证命令', failure_runs: '连续失败' };
  function tlsPrevLines(key, lines) {
    const out = [];
    (lines || []).forEach((l0) => {
      const l = String(l0); const m = /^([A-Za-z_][\w.]*): (.*)$/.exec(l);
      if (!m) { out.push(l); return; }
      const k = m[1]; let v = m[2].trim();
      if (/^(\[\]|\{\}|""|null|none|None)$/.test(v)) return;
      if (key === 'goal' && k === 'source') return;
      if (/^".*"$/.test(v)) { try { v = JSON.parse(v); } catch (e) { v = v.slice(1, -1); } }
      const name = TLS_FIELD[k] != null ? TLS_FIELD[k] : k;
      out.push(name ? name + ' · ' + v : v);
    });
    return out;
  }
  function tlsApplyPreview(d) {
    if (!TLS.ctxDemo) TLS.ctxDemo = CTX.slice();
    const redact = TLS.ctxDemo.find((c) => c[0] === 'redact');
    CTX.length = 0;
    (d.items || []).forEach((it) => {
      CTX.push([it.key, it.label || it.key, (it.consent === 'missing' ? '需要授权 · ' : '') + (it.desc || ''), it.tokens || 0]);
      CTX_HITS[it.key] = it.redaction_hits || 0;
      CTX_SAMPLE[it.key] = tlsPrevLines(it.key, it.preview).map((l) => l.replace(/\{\{/g, '{ {'));
      if (S.studio.ctx[it.key] == null) S.studio.ctx[it.key] = !!it.enabled;
    });
    if (redact) CTX.push(redact);
    TLS.limit = d.input_budget || null;
  }
  function tlsPreview(force) {
    const key = tlsPreviewKey();
    if (TLS.previewBusy || (!force && TLS.previewKey === key)) return;
    TLS.previewKey = key; TLS.previewBusy = true; const keys = CTX.map((c) => c[0]).join(',');
    TL.send('POST', '/v1/ai/preview', Object.assign({ task_id: TLS_TASK[S.studio.type], engine: tlsEngine(), selection: tlsSel(), template: S.studio.tpl }, tlsGoal()))
      .then((r) => { TLS.preview = r.data; tlsApplyPreview(r.data || {}); }, (e) => { TLS.preview = null; if (!TL.unavailable(e)) toast('上下文预览失败：' + (e.message || e.code)); })
      .then(() => { TLS.previewBusy = false; if (tlsPreviewKey() !== TLS.previewKey) tlsPreview(); else tlsPreviewShow(keys); });
  }
  // while the user is typing the goal a full re-render would drop the IME composition: patch the stack bar, the preview
  // sheet and the per-item sizes in place when the item set is unchanged
  function tlsPreviewShow(keys) {
    const a = document.activeElement; const rows = $$('#main .st-ctx');
    if (!(a && a.id === 'studioGoal') || keys !== CTX.map((c) => c[0]).join(',') || rows.length !== CTX.length) { refreshStudio(); refreshCtx(); return; }
    refreshCtx();
    rows.forEach((row) => {
      const inp = row.querySelector('input[data-k]'); const c = inp && CTX.find((x) => x[0] === inp.dataset.k); const t = row.querySelector(':scope > .mono.cap');
      if (c && t) t.textContent = c[3] ? tokS(c[3]) : '';
    });
  }
  // the goal is part of the pack: re-preview shortly after the user stops typing
  const tlsGoalBase = ACT.studioGoal;
  ACT.studioGoal = (el) => { tlsGoalBase(el); clearTimeout(TLS.goalT); TLS.goalT = setTimeout(() => { if (S.route === 'studio' && engines()) tlsPreview(); }, 450); };
  // same markup as the demo's token stack, with the gateway's input budget
  const tlsTokBarBase = tokBar;
  tokBar = function () {
    if (!TLS.limit) return tlsTokBarBase();
    const L = TLS.limit; const tok = ctxTokens(); const scale = Math.max(tok, L) * 1.08; const over = tok > L;
    const segs = CTX.filter((c) => c[3] && S.studio.ctx[c[0]]).map((c) => '<span class="st-seg ' + esc(c[0]) + '" style="width:' + (c[3] / scale * 100) + '%" title="' + esc(c[1]) + ' ≈ ' + tokS(c[3]) + '"></span>').join('');
    return '<div class="st-tok' + (over ? ' over' : '') + '" id="stTok" role="img" aria-label="上下文包 ≈ ' + tokK(tok) + ' tokens，上限 ' + f1(L / 1000) + 'k' + (over ? '，已超出' : '') + '"><div class="st-tok-bar">' + segs + '<span class="st-tok-lim" style="left:' + (L / scale * 100) + '%"></span></div>' +
      '<div class="row st-tok-cap"><span class="mono' + (over ? ' crit' : '') + '" data-tok>≈ ' + tokK(tok) + ' tokens</span><span class="mono cap">上限 ' + f1(L / 1000) + 'k' + (over ? ' · 超出 ' + f1((tok - L) / 1000) + 'k，原始片段会被截断' : ' · ' + tokPct(tok, L)) + '</span></div></div>';
  };
  const tlsStudioBase = PAGES.studio; const tlsStudioAfter = PAGES.studio.after;
  PAGES.studio = function () {
    const v = lvView('studio'); const d = engines();
    TLS.studioDemo = tlsDemo(v.res.engines);
    if (d && !TLS.engInit) { TLS.engInit = true; TLS.engine = d.default_engine || null; const a = tlsAgOf(TLS.engine); if (a) S.studio.agent = a; }
    if (d) tlsPreview();
    STUDIO_COPY.detected = d ? esc(d.engines.map((e) => e.name + (!e.available ? '（不可用）' : e.logged_in === false ? '（未登录）' : '')).join(' · ') || '没有可用的本地 Agent')
      : TLS.studioDemo ? '本地服务暂不提供生成接口' : '正在检测本地 Agent…';
    const arts = tlsRes('/v1/ai/artifacts', { limit: 20 });
    STUDIO_COPY.hist = Array.isArray(arts.data) ? arts.data.length : (arts.data && arts.data.items ? arts.data.items.length : 0);
    return tlsStudioBase();
  };
  PAGES.studio.after = tlsStudioAfter;

  function tlsRunReset() {
    Object.keys(TLS.genDemo).forEach((k) => { GEN[k] = TLS.genDemo[k]; }); TLS.genDemo = {};
    if (TLS.durDemo) TLS.durDemo.forEach((x, i) => { STEP_DUR[i] = x; });
    if (TLS.ctl) { TLS.ctl.abort(); TLS.ctl = null; }
  }
  function tlsApplyJob(run, job) {
    if (S.studio.run !== run) return;
    run.live.job = job;
    const seq = TPLS[run.tpl].seq; let pos = 0;
    (job.stages || []).forEach((st) => {
      const i = TLS_STAGE[st.id]; const k = i == null ? -1 : seq.indexOf(i); if (k < 0) return;
      if (TLS_DONE.indexOf(st.status) >= 0) { if (st.duration_ms != null) STEP_DUR[i] = st.duration_ms / 1000; pos = Math.max(pos, Math.min(k + 1, seq.length - 1)); }
      else if (st.status === 'running') pos = k;
    });
    run.pos = pos; run.step = seq[pos];
    run.log = run.head.concat(job.log || []);
    refreshStudio();
  }
  function tlsApplyArtifact(run, a) {
    const type = S.studio.type; const files = (a && a.files) || []; const lines = [];
    files.forEach((f, n) => { if (n) lines.push(['', ' '], ['# ' + f.target + '（' + f.action + '）', ' ']); (f.lines || []).forEach((l) => lines.push([l.text, l.mark === 'ai' ? 'ai' : l.mark === '+' ? '+' : ' '])); });
    GEN[type] = { file: files[0] ? files[0].target : GEN[type].file, lines };
    run.art = a; run.lines = lines.length;
    const seq = TPLS[run.tpl].seq; run.pos = seq.length - 1; run.step = seq[run.pos];
    run.log.push('› 产物 ' + a.artifact_id + ' · ' + (tlsBlocked(run) ? '安全扫描拦截，不能安装' : '等你审阅'));
  }
  const tlsBlocked = (run) => !!(run && run.art && (run.art.status === 'blocked' || (run.art.checks && run.art.checks.scan && run.art.checks.scan.status === 'blocked')));
  function tlsRunFail(run, e, el) {
    if (TL.unavailable(e) && !run.live.id) {   // the gateway has no AI job route: say so, never run the demo workflow
      S.studio.run = null; tlsRunReset(); refreshStudio(); renderSide(); toast('本地服务暂不提供生成接口，无法开始生成'); return;
    }
    if (e.code === 'consent_required') tlsConsentDialog(e.detail || {}, el);
    const det = e.detail || {}; let opt;
    const msg = e.code === 'consent_required' ? '需要授权：' + (det.missing || []).join('、') : e.code === 'preview_stale' ? '上下文已变化，已重新打包，请再点一次「开始生成」'
      : e.code === 'budget_exhausted' ? '今日 AI 预算已用完' + (det.daily_cap != null ? '（上限 $' + det.daily_cap + '）' : '') : e.code === 'over_budget' ? '上下文超出预算（' + TLU.num(det.total_tokens) + ' / ' + TLU.num(det.input_budget) + ' tokens）'
        : e.code === 'engine_unavailable' ? '执行者不可用（' + ({ not_installed: '未安装', not_logged_in: '未登录' }[det.reason] || det.reason || e.code) + '）' : e.code === 'ai_disabled' ? 'AI 已在设置中关闭' : (e.message || e.code);
    if (e.code === 'ai_disabled') opt = { act: '去设置', onAct: () => openSettings('analysis') };
    if (e.code === 'preview_stale') tlsPreview(true);
    run.stopped = true; run.log.push('! ' + msg); refreshStudio(); renderSide(); if (e.code !== 'consent_required') toast(msg, opt);
  }
  // 403 consent_required: the real consent dialog (grant the missing data classes for this engine, then retry)
  const CLS_NAME = { summary: '结构化统计', snippets: '脱敏片段', rules: '规则文件段落', raw: '原文' };
  function tlsConsentDialog(det, el) {
    const miss = det.missing || []; const eid = det.engine || tlsEngine();
    TLS.consent = { miss, eid, el };
    openModal(modalHead('需要授权', '这次生成要把下列内容交给 ' + esc(tlsEngName(eid) || '本地 Agent') + '；传出前都先过脱敏规则') + '<div class="mb col" style="gap:6px" data-tl="consent">' +
      miss.map((k) => '<div class="row" style="gap:8px;padding:6px 0;border-bottom:1px solid var(--hair);font-size:13px">' + ic('shield', 13, 'color:var(--good)') + '<span style="flex:1">' + esc(CLS_NAME[k] || k) + '</span><span class="mono cap" style="font-size:11px">' + esc(k) + '</span></div>').join('') +
      '</div><div class="mf"><button type="button" class="btn" data-act="tlsConsentSet">去设置</button><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="tlsConsentOk">授权并重试</button></div>');
  }
  Object.assign(ACT, {
    tlsConsentSet: () => { closeModal(); openSettings('analysis'); },
    tlsConsentOk: () => {
      const c = TLS.consent; if (!c) return closeModal();
      const g = {}; c.miss.forEach((k) => { g[k] = true; });
      TL.send('PUT', '/v1/ai/consent', { grants: { [c.eid]: g } }).then(() => { closeModal(); TL.invalidate((r) => r.path === '/v1/ai/consent'); S.studio.run = null; ACT.studioStart(c.el); }, (e) => tlsErr(e, '授权'));
    }
  });
  const tlsStartBase = ACT.studioStart;
  ACT.studioStart = (el, ev) => {
    const d = engines();
    if (!d) { toast(TLS.studioDemo ? '本地服务暂不提供生成接口，无法开始生成' : '正在检测本地 Agent，稍后再试'); return; }
    const r0 = S.studio.run; if (r0 && !r0.done && !r0.stopped) { toast('正在生成中，先停止再重新开始'); return; }
    if (!S.studio.goal.trim()) { toast('先写一句目标'); const t = $('#studioGoal'); if (t) t.focus(); return; }
    if (ctxEmpty()) { toast('上下文包是空的：至少勾选一项再生成'); return; }
    const eid = tlsEngine(); const eng = d.engines.find((x) => x.id === eid);
    if (eng && !eng.available) { toast(eng.name + ' 不可用：未安装或未登录，换一个执行者'); return; }
    tlsRunReset();
    const type = S.studio.type; TLS.genDemo[type] = GEN[type]; GEN[type] = { file: GEN[type].file, lines: [] };
    if (!TLS.durDemo) TLS.durDemo = STEP_DUR.slice();
    const ctl = TLS.ctl = new AbortController();
    const seq = TPLS[S.studio.tpl].seq;
    const run = S.studio.run = { tpl: S.studio.tpl, pos: 0, step: seq[0], lines: 0, log: [], head: ['$ POST /v1/ai/jobs · ' + TLS_TASK[type] + ' · ' + eid], done: false, stopped: false, installed: null, live: { id: null, job: null } };
    run.log = run.head.slice(); refreshStudio(); renderSide();
    TL.send('POST', '/v1/ai/jobs', { task_id: TLS_TASK[type], engine: eid, template: run.tpl, goal: tlsGoal().goal, goal_source: tlsGoal().goal_source, selection: tlsSel(), preview_digest: TLS.preview ? TLS.preview.preview_digest : undefined }, { signal: ctl.signal })
      .then((res) => {
        const j = res.data || {}; run.live.id = j.job_id;
        run.head.push('› 任务 ' + j.job_id + (j.cached ? ' · 命中缓存' : '') + (j.estimate ? ' · 预计 ' + f1((j.estimate.tokens || 0) / 1000) + 'k tokens · ' + TLU.money(j.estimate.cost_usd) : ''));
        run.log = run.head.slice(); refreshStudio();
        return TL.pollJob(j.job_id, (job) => tlsApplyJob(run, job), { signal: ctl.signal });
      })
      .then((job) => {
        if (S.studio.run !== run) return null;
        if (job.artifact_id) return TL.send('GET', '/v1/ai/artifacts/' + encodeURIComponent(job.artifact_id), null, { signal: ctl.signal }).then((a) => tlsApplyArtifact(run, a.data || {}));
        if (TLS_DONE.indexOf(job.status) < 0) { run.stopped = true; run.log.push('! 任务' + ({ cancelled: '已取消', canceled: '已取消' }[job.status] || '失败') + (job.error ? '：' + (job.error.message || job.error.code || job.error) : '')); }
        return null;
      })
      .then(() => {
        if (S.studio.run !== run) return;
        if (!run.stopped) { run.done = true; notify({ t: '生成完成：' + stFile(), b: tlsBlocked(run) ? '安全扫描拦截了这份产物，不能安装。' : '自检结果已就绪，等你审阅后安装。', a1: '去审阅', on1: () => go('studio') }); }
        refreshStudio(); renderSide();
      })
      .catch((e) => { if (e.name === 'AbortError' || S.studio.run !== run) return; tlsRunFail(run, e, el); });
  };
  const tlsStopBase = ACT.studioStop;
  ACT.studioStop = (el) => {
    const r = S.studio.run; if (!r || !r.live) return tlsStopBase(el);
    if (r.done || r.stopped) return;
    if (TLS.ctl) { TLS.ctl.abort(); TLS.ctl = null; }
    r.stopped = true; r.log.push('› 已停止：前 ' + r.pos + ' 步结果保留为草稿'); refreshStudio(); renderSide();
    if (r.live.id) TL.send('POST', '/v1/ai/jobs/' + encodeURIComponent(r.live.id) + '/cancel', {}).then((x) => { r.log.push('› 任务 ' + r.live.id + ' · ' + ((x.data && x.data.status) || 'cancelled')); refreshStudio(); }, (e) => tlsErr(e, '取消任务'));
    toast('已停止，已产出的部分保留为草稿');
  };
  const artOf = () => { const r = S.studio.run; return r && r.live && r.art && r.art.artifact_id ? r.art : null; };
  const tlsEditorBase = ACT.studioEditor;
  ACT.studioEditor = (el, ev) => {
    const a = artOf(); if (!a) return S.studio.run && S.studio.run.live ? toast('产物还没生成，暂时没有可打开的文件') : tlsEditorBase(el, ev);
    TL.send('POST', '/v1/ai/artifacts/' + encodeURIComponent(a.artifact_id) + '/materialize', {}).then((x) => {
      const d = x.data || {}; toast('草稿已写入 ' + (d.dir || ''), { act: '在 Finder 中显示', onAct: () => ORBIT.native.request('reveal', { path: d.dir }) });
      if (d.dir) ORBIT.native.post('reveal', { path: d.dir });
    }, (e) => tlsErr(e, '写出草稿'));
  };
  const tlsSaveBase = ACT.studioSave;
  ACT.studioSave = (el, ev) => {
    const a = artOf(); if (!a) return S.studio.run && S.studio.run.live ? toast('产物还没生成') : tlsSaveBase(el, ev);
    TL.send('POST', '/v1/ai/artifacts/' + encodeURIComponent(a.artifact_id) + '/to_library', {}).then(() => {
      TL.invalidate((r) => r.path.indexOf('/v1/catalog') === 0 || r.path === '/v1/ai/artifacts');
      S.history.unshift({ t: S.studio.type + ' · ' + stFile() + '（资源库）', when: '刚刚', kind: 'studio' });
      toast('已存入资源库 ›「本地生成」', { act: '去看看', onAct: () => { S.lib.tab = 'local'; go('library'); } });
    }, (e) => tlsErr(e, '存入资源库'));
  };
  const tlsInstallBase = ACT.studioInstall;
  ACT.studioInstall = (el, ev) => { if (tlsBlocked(S.studio.run)) { toast('安全扫描拦截了这份产物，不能安装'); return; } return tlsInstallBase(el, ev); };
  const tlsAgentBase = ACT.studioAgent;
  ACT.studioAgent = (el) => {
    const d = engines(); if (!d) return tlsAgentBase(el);
    openDD(el, d.engines.map((e) => ({ t: e.name + (e.available ? (e.version ? ' · ' + e.version : '') : ' · 不可用'), v: e.id, on: e.id === tlsEngine(), dis: !e.available })), (eid) => {
      TLS.engine = eid; const a = tlsAgOf(eid); if (a) S.studio.agent = a; render();
      tlsWrite('/v1/ai/consent', { default_engine: eid }, () => TL.send('PUT', '/v1/ai/consent', { default_engine: eid }), '切换执行者');
    });
  };
  // self-check rows from the artifact's checks (same row markup as the demo); before the artifact arrives they only track the stages
  const tlsChecksBase = checkRows;
  checkRows = function (run, seq) {
    if (!run || !run.live) return tlsChecksBase(run, seq);
    const ch = (run.art && run.art.checks) || null;
    const CH = [{ id: 'spec', key: 'lint', name: '规范', step: 3 }, { id: 'safe', key: 'scan', name: '安全', step: 3 }, { id: 'replay', key: 'replay', name: '回放 dry-run', step: 4 }, { id: 'judge', key: 'judge', name: 'judge', step: 4 }];
    return CH.map((c) => {
      const k = seq.indexOf(c.step); const x = ch ? ch[c.key] || { status: 'skipped' } : null;
      let st = k < 0 ? 'skip' : x ? (x.status === 'skipped' || x.status === 'untriggered' ? 'skip' : 'ok') : k < run.pos || run.done ? 'ok' : k === run.pos && !run.stopped ? 'cur' : 'pend';
      const bad = !!x && (x.status === 'fail' || x.status === 'blocked');
      let body;
      if (k < 0) body = '<span class="rs">已跳过 · ' + esc(TPLS[run.tpl].name) + '</span>';
      else if (!x) body = '<span class="rs">' + (st === 'cur' ? '检查中…' : st === 'ok' ? '已完成 · 等待产物' : '等待') + '</span>';
      else if (st === 'skip') body = '<span class="rs">已跳过' + (c.key === 'judge' ? ' · judge 未启用' : x.status === 'untriggered' ? ' · 历史会话里没有触发场景' : '') + '</span>';
      else if (c.key === 'lint') body = '<span class="rs">' + ((x.issues || []).length ? esc(x.issues.slice(0, 2).map((i) => i.message || i.code).join('；')) : '结构与命名检查通过') + '</span>';
      else if (c.key === 'scan') body = '<span class="rs"' + (bad ? ' style="color:var(--crit)"' : '') + '>' + (bad ? '拦截：' + esc((x.hits || []).map((h) => h.rule + (h.excerpt ? ' · ' + h.excerpt : '')).join('；')) : '未发现危险命令或凭据读取') + '</span>';
      else if (c.key === 'replay') body = '<div class="st-rp">' + (x.sessions || []).map((s) => '<span class="t" title="' + esc(s.session_uid) + '">' + esc(s.title || s.session_uid) + '</span><span class="row" style="gap:4px;color:var(' + (s.result === 'pass' ? '--good' : '--crit') + ')">' + ic(s.result === 'pass' ? 'check' : 'x', 12) + (s.result === 'pass' ? '通过' : '未通过') + '</span><span class="cap w">' + esc(s.reason || '') + '</span>').join('') + '</div>';
      else body = '<span class="rs">' + esc(x.status) + '</span>';
      if (bad) st = 'pend';
      return '<div class="st-chk ' + st + '" data-chk="' + c.id + '">' + ic(bad ? 'alert' : st === 'ok' ? 'okc' : st === 'cur' ? 'clock' : 'minus', 14, 'color:' + (bad ? 'var(--crit)' : st === 'ok' ? 'var(--good)' : st === 'cur' ? 'var(--ai)' : 'var(--ink-4)')) + '<span class="nm">' + c.name + '</span>' + body + '</div>';
    }).join('');
  };
  ACT.studioHistory = (el) => {
    TL.send('GET', '/v1/ai/artifacts', null, { query: { limit: 20 } }).then((r) => {
      const xs = Array.isArray(r.data) ? r.data : (r.data && r.data.items) || [];
      openModal(modalHead('历史产物', '由生成工坊产出的内容；草稿与已归档的都在这里') + '<div class="mb col" style="gap:6px" data-tl="artifacts">' + (xs.length ? xs.map((a) => '<div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--hair);font-size:13px"><span>' + esc((TLS_ART_KIND[a.kind] || a.kind) + ' · ' + (a.name || a.title || a.artifact_id)) + '</span><span class="cap mono">' + esc({ draft: '草稿', blocked: '已拦截', archived: '已归档' }[a.status] || a.status || '') + ' · ' + tlsDate(a.created_at) + '</span></div>').join('') : '<div class="cap" style="padding:12px 0">还没有产物</div>') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
    }, (e) => { if (TL.unavailable(e)) toast('本地服务暂不提供历史产物'); else tlsErr(e, '读取历史产物'); });
  };

  /* ---------- 问本地 Agent ---------- */
  const ASK_TEMPLATES = [['', '自由提问'], ['analyze.collaboration', '协作与反馈'], ['analyze.quality', '验证与交付'], ['analyze.workflow', '流程与工具'], ['analyze.cost', '成本与时间']];
  function tlsAskScope() {
    const scope = LV.scope(); const end = Date.now();
    const range = scope.range > 0 ? scope.range : 0;
    const start = range ? new Date(new Date(end).getFullYear(), new Date(end).getMonth(), new Date(end).getDate() - range + 1).getTime() : 0;
    const out = { start_ms: start, end_ms: end, excluded_session_uids: Array.from(S.excluded || []) };
    if (scope.project) out.project_id = scope.project;
    if (scope.agents != null) out.source_ids = OrbitLive.sourceIdsFor(scope.agents, TL.status);
    return out;
  }
  function tlsCancelQuestion() {
    const q = TLS.question; if (!q) return;
    TLS.question = null; q.ctl.abort();
    if (q.job) TL.send('POST', '/v1/ai/jobs/' + encodeURIComponent(q.job) + '/cancel', {}).catch(() => {});
  }
  const tlsCloseAskBase = closeModal;
  closeModal = function () { if (MODAL_KEY === 'ask') { tlsCancelQuestion(); clearInterval(ASKT); } tlsCloseAskBase(); };
  const tlsAskOpenBase = openAsk;
  openAsk = function (ctx) {
    tlsCancelQuestion();
    TLS.ask = null; tlsAskOpenBase(ctx); if (!ASK) return;
    const owner = ASK, c = ASK.ctx;
    ASK.scope = tlsAskScope(); ASK.session_uid = c === 'session' ? S.sess.sel : null; ASK.template = '';
    const input = $('#askIn');
    if (input) input.parentElement.insertAdjacentHTML('beforebegin', '<label class="row" style="gap:8px;font-size:12px">分析方式<select id="askTemplate" data-chg="askTemplate" style="' + FIELD + ';width:auto">' + ASK_TEMPLATES.map((t) => '<option value="' + t[0] + '">' + t[1] + '</option>').join('') + '</select><span class="cap">沿用当前时间、项目与 Agent 范围</span></label>');
    TL.send('GET', '/v1/ai/ask/presets', null, { query: { context: c, session_uid: ASK.session_uid } }).then((r) => {
      const xs = Array.isArray(r.data) ? r.data : (r.data && (r.data.items || r.data.presets)) || [];
      const first = $('#modal [data-act="askPick"]');
      if (!xs.length || ASK !== owner || MODAL_KEY !== 'ask' || !first) return;
      TLS.ask = { ctx: c, presets: xs };
      const box = first.parentElement; box.setAttribute('data-tl', 'ask-presets');
      box.innerHTML = xs.map((p, i) => '<button type="button" class="chip sm" data-act="askPick" data-i="' + i + '">' + esc(p.question) + '</button>').join('');
    }, () => { /* the generic questions stay; answers still go through POST /v1/ai/ask */ });
  };
  // 来源如实写在回答末尾：预置问题是规则模板在本机查询出的（没有调用模型）；自由提问与专业分析由本地 Agent 作答；
  // 模型失败时后端回 status=fallback 与说明文字，照样显示说明，不当成回答
  const tlsAskSrc = (d) => d.source === 'ai' || d.source === 'cache' ? '本地 Agent 回答' + (d.source === 'cache' ? '（缓存）' : '') + ' · 只发送了脱敏后的查询结果'
    : d.error_code ? '本地 Agent 没有答成（' + d.error_code + '），以上是说明，不是回答'
    : d.analysis_session && d.analysis_session.validation === 'fallback' ? '没有通过校验的 AI 分析 · 以上是本机统计给出的保底说明'
    : '规则模板 · 在本机查询你的数据生成，没有调用模型';
  const tlsAnswer = (d) => (d.summary != null ? [d.summary, ...(d.findings || []).map((f) => (f.kind === 'hypothesis' ? '待验证的推测：' : '观察：') + f.text + ((f.evidence_ids || []).length ? '\n证据：' + f.evidence_ids.join('、') : '')), (d.next_steps || []).length ? '下一步：\n' + d.next_steps.join('\n') : '', (d.limitations || []).length ? '分析边界：\n' + d.limitations.join('\n') : ''].filter(Boolean).join('\n\n') : (d.answer || '') + ((d.refs || []).length ? '\n\n引用：' + d.refs.map((r) => r.kind + ' ' + r.id).join('、') : '')) + '\n\n— ' + tlsAskSrc(d);
  function tlsThinking(q, preset) { const a = $('#askA'); if (a) a.innerHTML = '<div class="mono cap" style="font-size:11px;margin-bottom:6px">问：' + esc(q) + '</div><span class="cap" data-tl="ask-wait">' + (preset ? '正在本机查询…' : '本地 Agent 正在回答…') + '</span>'; }
  function tlsAsk(body, q) {
    tlsCancelQuestion();
    const request = { owner: ASK, ctl: new AbortController(), job: null }; TLS.question = request;
    const current = () => TLS.question === request && ASK === request.owner && MODAL_KEY === 'ask';
    const task = ASK.template;
    const preset = !task && body.preset_index != null;
    body = Object.assign({}, body, { scope: ASK.scope, session_uid: ASK.session_uid });
    const path = task ? '/v1/ai/jobs' : '/v1/ai/ask';
    const payload = task ? { task_id: task, scope: ASK.scope, goal: q, goal_source: 'ask', params: { question: q, session_uid: ASK.session_uid } } : body;
    clearInterval(ASKT); tlsThinking(q, preset);
    TL.send('POST', path, payload).then((r) => {
      const d = r.data || {};
      if (!current()) { if (d.job_id) TL.send('POST', '/v1/ai/jobs/' + encodeURIComponent(d.job_id) + '/cancel', {}).catch(() => {}); return null; }
      if (d.answer != null) return d;
      if (!d.job_id) throw Object.assign(new Error('没有返回作业'), { status: 500, code: 'no_job' });
      request.job = d.job_id;
      return TL.pollJob(d.job_id, null, { signal: request.ctl.signal }).then((job) => {
        request.job = null;
        if (job.status === 'fallback' && job.result) return job.result;
        if (TLS_DONE.indexOf(job.status) < 0) throw Object.assign(new Error(job.status === 'cancelled' ? '已取消' : (job.error && (job.error.message || job.error.code || job.error)) || '回答失败'), { status: 500, code: 'job_' + job.status });
        return job.result || {};
      });
    }).then((d) => { if (current() && d) { TLS.question = null; askStream(q, tlsAnswer(d)); } }, (e) => {
      if (!current() || e.name === 'AbortError') return;
      TLS.question = null;
      if (TL.unavailable(e)) { askStream(q, '本地服务暂不提供问答接口，暂时无法回答。'); return; }
      askStream(q, '无法回答：' + (e.message || e.code) + (e.code === 'consent_required' ? '\n\n到 设置 › 分析 授权后再试。' : ''));
    });
  }
  ACT.askTemplate = (el) => { if (ASK && ASK_TEMPLATES.some((t) => t[0] === el.value)) ASK.template = el.value; };
  ACT.askPick = (el) => {
    if (!ASK) return;
    const a = TLS.ask; const i = +el.dataset.i;
    if (!a || a.ctx !== ASK.ctx) { const q = ASKQ[ASK.ctx][i]; if (q) tlsAsk({ context: ASK.ctx, question: q }, q); return; }   // generic question, real answer
    const p = a.presets[i]; if (!p) return;
    tlsAsk({ context: a.ctx, preset_index: p.index }, p.question);
  };
  const tlsSendBase = ACT.askSend;
  ACT.askSend = (el) => {
    const inp = $('#askIn'); const q = inp ? inp.value.trim() : ''; if (!q || !ASK) return tlsSendBase(el);
    tlsAsk({ context: ASK.ctx, question: q }, q);
    if (inp) inp.value = '';
  };

  /* ---------- 设置：通用 / 数据源 / 隐私 / 分析 / 通知 / 关于 ---------- */
  const R = { col: '/v1/platform/collection', pol: '/v1/notifications/policy', snz: '/v1/notifications/snooze', attn: '/v1/notifications/attention', con: '/v1/ai/consent', tel: '/v1/platform/telemetry', hea: '/v1/platform/health',
    state: '/v1/app/state', disc: '/v1/app/discovery', about: '/v1/app/about', data: '/v1/app/data', rules: '/v1/privacy/rules', eng: '/v1/ai/engines', usage: '/v1/ai/usage', rec: '/v1/platform/recommend', tmap: '/v1/app/tool_map' };
  const polKey = (m, k) => TLS_KIND[k].find((t) => m && Object.prototype.hasOwnProperty.call(m, t)) || null;
  const CLS = { sum: 'summary', snip: 'snippets', raw: 'raw' };
  // the gateway's modes are stats | agent | api; 仅统计 is 'stats' (never 'off'), there is no Ollama mode yet
  const MODE_IN = { off: 'stats', stats: 'stats', agent: 'agent', api: 'agent' }; const MODE_OUT = { stats: 'stats', agent: 'agent' };
  const SYNC_IN = { off: 'manual', hour: 'hour', live: 'live' }; const SYNC_OUT = { manual: 'off', hour: 'hour', live: 'live' };
  const conEngine = (d) => TLS.engine || d.default_engine || (Object.keys(d.grants || {})[0] || null);
  const setOpen = () => !$('#set').hidden;
  // settings tab → the resources it reads (loaded only while that tab is open)
  const TAB_RES = { general: ['state'], sources: ['state', 'disc', 'col', 'about'], privacy: ['rules', 'data'], analysis: ['con', 'usage', 'rec', 'eng'], notify: ['pol', 'snz'], about: ['about', 'hea', 'tel'] };
  // server state → the demo's S fields (skipped while a demo handler is mid-way, see TLS.hold)
  function tlsSync() {
    if (TLS.hold) return;
    TLS_WRITES.forEach(tlsWriteView);
    if (setOpen()) (TAB_RES[S.setTab] || []).forEach((k) => tlsRes(R[k]));
    const col = tlsRes(R.col), pol = tlsRes(R.pol), snz = tlsRes(R.snz), attn = tlsRes(R.attn), st = tlsRes(R.state);
    // a collection frame is newer than a GET that was already in flight: it patches the cached answer once it lands
    if (col.data && TLS.colFrame != null) { col.data = Object.assign({}, col.data, { paused: TLS.colFrame }); TLS.colFrame = null; }
    if (col.data) S.paused = !!col.data.paused;
    if (st.data && st.data.settings && st.updatedAt !== TLS.stateAt) {
      TLS.stateAt = st.updatedAt; const g = st.data.settings;
      if (SYNC_IN[g.sync_mode]) S.index = SYNC_IN[g.sync_mode];
      if (typeof g.weekly_report === 'boolean') S.weekly = g.weekly_report;
      // the server's default range applies once per load, unless this browser already chose one (store 'range')
      if (!TLS.rangeInit) { TLS.rangeInit = true; if (typeof g.default_range_days === 'number' && store.get('range', null) == null && [0, 7, 30, 90].indexOf(g.default_range_days) >= 0) S.range = g.default_range_days; }
    }
    if (pol.data && pol.data.matrix) NEV.forEach((e) => { const k = polKey(pol.data.matrix, e[0]); if (k) { const ch = pol.data.matrix[k] || []; S.notif[e[0]] = ['banner', 'hud', 'badge'].map((x) => (ch.indexOf(x) >= 0 ? 1 : 0)); } });
    if (snz.data) S.hud.mute = (snz.data.items || []).some((x) => x.scope === 'global' && Date.parse(x.until) > Date.now());
    // the realtime snapshot owns S.attn / S.waitOpen once it is in (98-live-ops tloApply runs before every render); applying the
    // attention list on top would leave it clobbered until some later render, which the unchanged-state skip may never run
    if (attn.data && attn.updatedAt !== TLS.attnAt && !(TL.ops && TL.ops.rt)) {
      TLS.attnAt = attn.updatedAt;
      const has = (k) => (attn.data.items || []).some((i) => tlsKind(i.type) === k);
      ['stuck', 'ctx'].forEach((k) => { if (has(k)) S.attn.add(k); else S.attn.delete(k); });
      S.waitOpen = has('waiting'); simSettle();
    }
    const con = TL.resource(R.con);
    if (con.data) { const g = (con.data.grants || {})[conEngine(con.data)] || {}; S.aiCh = { sum: !!g.summary, snip: !!g.snippets, raw: !!g.raw }; if (MODE_IN[con.data.mode]) S.engine = MODE_IN[con.data.mode]; }
  }
  const hold = (fn) => { TLS.hold = true; try { fn(); } finally { TLS.hold = false; } };
  const matrixFromS = (prev) => { const m = Object.assign({}, prev || {}); NEV.forEach((e) => { m[polKey(prev, e[0]) || TLS_KIND[e[0]][0]] = ['banner', 'hud', 'badge'].filter((x, i) => S.notif[e[0]][i]); }); return m; };
  const setCard = (title) => $$('#set .card').find((x) => { const t = x.querySelector('.ct'); return t && t.textContent.indexOf(title) === 0; });
  const cardHTML = (title, sub, inner, tl) => '<div class="card" data-tl="' + tl + '"><div class="row set-ch"><div style="flex:1;min-width:200px"><div class="ct">' + title + '</div>' + (sub ? '<div class="cap set-cs">' + sub + '</div>' : '') + '</div></div><div class="set-cb">' + inner + '</div></div>';
  function sample(title) { const c = setCard(title); const t = c && c.querySelector('.ct'); if (t && !c.querySelector('[data-tl="sample"]')) t.insertAdjacentHTML('beforeend', ' ' + TLU.sample()); }
  const kv = (l, v) => '<div class="row" style="padding:5px 0;border-bottom:1px solid var(--hair);font-size:12px"><span style="flex:1;min-width:0">' + l + '</span>' + v + '</div>';
  const ago = (ts) => { if (!ts) return '—'; const m = Math.round((Date.now() - ts) / 60000); return m < 1 ? '刚刚' : m < 60 ? m + ' 分钟前' : m < 1440 ? Math.round(m / 60) + ' 小时前' : Math.round(m / 1440) + ' 天前'; };
  // PATCH /v1/app/settings, optimistic on the cached /v1/app/state
  function tlsSetting(patch, label) {
    if (!tlsWrite(R.state, patch, () => TL.send('PATCH', '/v1/app/settings', patch), label, null, 'settings')) {
      tlsRes(R.state); toast(label + '未保存：正在读取设置，请稍后重试');
    }
  }

  // 数据源: one row per discovered source (GET /v1/app/discovery), else the spine's agents without a status
  const discList = () => { const d = TL.resource(R.disc).data; return Array.isArray(d) ? d : d && (d.sources || d.items) || null; };
  const ST_SRC = { available: ['正常', 'okc', 'var(--good)'], empty: ['没有会话文件', 'minus', 'var(--ink-3)'], permission_denied: ['无权限读取', 'alert', 'var(--warn)'] };
  srcRows = function () {
    const disc = discList(); const st = TL.resource(R.state).data; const conf = {}; ((st && st.sources) || []).forEach((x) => { conf[x.id] = x; });
    const look = (agentId) => { const m = lvAgentOf(agentId); const a = AGI[m.id]; const slot = m.slot; return { m, a, c: a ? a.c : slot ? 'var(--a' + slot + ')' : 'var(--a0)', t: a ? a.t : slot ? 'var(--a' + slot + 't)' : 'var(--a0t)' }; };
    if (!disc) return AG.map((a) => ({ name: esc(a.name), ver: esc(a.ver || ''), path: esc(a.path || '—'), n: fmt(a.all || 0), st: ['—', 'minus', 'var(--ink-3)', '—'], on: true, t: a.t, c: a.c, attrs: ' data-ag="' + esc(a.key || a.id) + '" disabled' }));
    // discovery is the union of the default roots and the configured ones: an agent that has a configured or non-empty
    // root does not also list its empty, never-enabled default (a duplicate「没有会话文件」row for the same agent)
    const real = (x) => x.enabled || conf[x.id] || x.status !== 'empty';
    const has = new Set(disc.filter(real).map((x) => x.agent));
    return disc.filter((x) => real(x) || !has.has(x.agent)).map((x) => {
      const L = look(x.agent); const s0 = ST_SRC[x.status] || [esc(x.status || '—'), 'minus', 'var(--ink-3)']; const c = conf[x.id] || {};
      const env = (LV.env || []).find((e) => e.agent === x.agent);
      return { name: esc(L.m.name), ver: esc((env && env.version) || (L.a && L.a.ver !== '—' ? L.a.ver : '') || ''), path: esc(tlsPath(x.root)), n: fmt(L.a ? L.a.all : 0), st: s0.concat([c.last_import_at ? ago(c.last_import_at) : x.files != null ? x.files + ' 个文件' : '—']), on: !!x.enabled, t: L.t, c: L.c,
        attrs: ' data-src="' + esc(x.id) + '" data-ag="' + esc(x.agent) + '" data-root="' + esc(x.root || '') + '"' };
    });
  };
  // a root as the row shows it: the user's home reads「~」and a long path keeps its head and tail, so「· N 个会话」stays visible
  function tlsPath(root) {
    if (!root) return '—';
    const p = String(root).replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, '~');
    if (p.length <= 40) return p;
    const seg = p.split('/'); const tail = seg.slice(-2).join('/');
    return (seg[0] || '/' + seg[1]) + '/…/' + (tail.length > 32 ? '…' + tail.slice(-31) : tail);
  }
  srcMissing = function () {
    const ab = TL.resource(R.about).data; const disc = discList();
    if (!disc) return [];   // discovery not answered yet: nothing is known to be missing
    // discovery and the about mappers spell agents differently (claude / claude_code, dsh / deepseek …): compare UI ids
    const norm = (k) => lvAgentOf(k).id || k;
    const have = new Set(disc.map((x) => norm(x.agent)).concat(AG.map((a) => a.id))); const maps = (ab && ab.components && ab.components.mappers) || [];
    if (maps.length) LV.mappers = maps;   // the gateway's connector registry: what can be imported at all (D9)
    const seen = new Set();
    return maps.filter((k) => { const id = norm(k); if (have.has(id) || seen.has(id)) return false; seen.add(id); return true; })
      .map((k) => ({ name: lvAgentOf(k).name, v: k, hint: '未检测到 · 可以手动指定会话目录' }));
  };
  // the sidebar counts root sessions (ALL); storage.counts.sessions also counts sub-agent sessions, so it is labelled as such
  srcIndexed = function () {
    const st = TL.resource(R.state).data; const all = st && st.storage && st.storage.counts ? +st.storage.counts.sessions || 0 : 0;
    return '已索引 ' + fmt(ALL.length) + ' 个会话' + (all > ALL.length ? '（含子会话共 ' + fmt(all) + ' 个）' : '');
  };

  // 隐私: rules from GET /v1/privacy/rules; the test box asks POST /v1/privacy/preview (nothing stored)
  ruleRows = function () {
    const d = TL.resource(R.rules).data; if (!d || !d.rules) return [];
    return d.rules.map((r) => ({ k: r.id, label: esc(r.label) + (r.locked ? ' <span class="cap" style="font-size:11px">始终开启</span>' : ''), ph: tlsPh(r), on: !!r.enabled, locked: !!r.locked }));
  };
  // home_user replaces /Users/<name> with「~」: a lone ~ in the mono column reads as a dash, so it shows what it stands for
  function tlsPh(r) { const ph = r.placeholder || ''; return /user/i.test(r.id || '') && ph.length <= 1 ? '[user] → ' + (ph || '~') : ph || (/user/i.test(r.id || '') ? '[user]' : ''); }
  redact = function (text) {
    const d = TL.resource(R.rules).data; if (!d) return { n: 0, html: esc(text) };
    const p = TLS.rd; if (!p || p.text !== text) { tlsPreviewRules(text); return { n: p ? p.n : 0, html: p ? p.html : esc(text) }; }
    return p;
  };
  function tlsPreviewRules(text) {
    clearTimeout(TLS.rdT);
    TLS.rdT = setTimeout(() => TL.send('POST', '/v1/privacy/preview', { text }).then((x) => {
      const d = x.data || {}; const rules = (TL.resource(R.rules).data || {}).rules || [];
      let html = esc(d.text != null ? d.text : text);
      rules.map((r) => r.placeholder).filter(Boolean).sort((a, b) => b.length - a.length).forEach((ph) => { html = html.split(esc(ph)).join('\u0001' + esc(ph) + '\u0002'); });
      TLS.rd = { text, n: d.n != null ? d.n : (d.hits || []).length, html: html.replace(/\u0001/g, '<mark class="rd">').replace(/\u0002/g, '</mark>') };
      if (S.ruleSample === text) { const o = $('#rdOut'); if (o) o.innerHTML = TLS.rd.html; const c = $('#rdN'); if (c) c.textContent = '命中 ' + TLS.rd.n + ' 处'; }
    }, (e) => { if (!TL.unavailable(e)) tlsErr(e, '预览脱敏'); }), 200);
  }

  function tlsSetPost() {
    const t = S.setTab;
    if (t === 'notify') { if (tlsDemo(TL.resource(R.pol))) sample('投递矩阵'); if (tlsDemo(TL.resource(R.snz))) sample('暂停提醒'); }
    if (t === 'analysis') {
      if (tlsDemo(TL.resource(R.con))) sample('AI 通道');
      const d = TL.resource(R.con).data, u = TL.resource(R.usage).data, rc = TL.resource(R.rec).data, rl = TL.resource(R.rules).data; const c = setCard('AI 通道');
      if (c && (d || u)) c.lastElementChild.insertAdjacentHTML('beforeend', '<div class="cap" data-tl="ai-cap" style="font-size:11px;margin-top:8px">' +
        (u ? '今日 ' + TLU.money(u.today_cost_usd) + ' · 近 30 天 ' + TLU.num(u.totals && u.totals.calls) + ' 次调用' + (u.totals && u.totals.unknown_calls ? '（' + TLU.num(u.totals.unknown_calls) + ' 次没有价格，按保守单价计入预算）' : '') + ' · ' : '') + '每日 AI 预算上限 ' + TLU.money(d && d.settings && d.settings.daily_usd_cap != null ? d.settings.daily_usd_cap : u ? u.daily_cap : null) + (d ? ' · 授权对象：' + esc(tlsEngName(conEngine(d)) || '未选择') : '') + '</div>');
      const e = setCard('分析引擎'); if (e && rc && rc.level) e.lastElementChild.insertAdjacentHTML('beforeend', '<div class="cap" data-tl="ai-rec" style="font-size:11px;margin-top:8px">按本机配置建议：' + esc(rc.level) + (rc.ai_generate ? ' · 可以使用生成工坊' : '') + '</div>');
      const cnt = c && $$('.cap', c).find((x) => x.textContent.indexOf('当前启用') === 0); if (cnt && rl) cnt.textContent = '当前启用 ' + rl.active_count + ' 条脱敏规则';
    }
    if (t === 'privacy') {
      const r = TL.resource(R.data); const c = setCard('数据存储'); const rules = TL.resource(R.rules);
      if (!rules.data) { const rc = setCard('脱敏规则'); const box = rc && rc.querySelector('.set-cb'); if (box && !box.querySelector('[data-lv]')) box.insertAdjacentHTML('afterbegin', rules.error ? LV.na(TL.unavailable(rules.error) ? '本地服务暂不提供脱敏规则' : '读取失败') : LV.pend(80)); }
      if (c) {
        const d = r.data; const top = c.querySelector('.row .mono'); const b = c.querySelector('b.mono');
        if (top) top.textContent = d ? d.home : '—'; if (b) b.textContent = d ? tlsBytes(d.total_bytes) : '—';
        if (d) c.lastElementChild.firstElementChild.insertAdjacentHTML('beforeend', '<div class="col" style="gap:0" data-tl="storage">' + (d.components || []).map((x) => kv(esc(x.label || x.id) + (x.rebuildable ? ' <span class="cap" style="font-size:11px">可重建</span>' : ''), '<b class="mono" style="font-size:12px">' + (x.approx ? '≈ ' : '') + tlsBytes(x.bytes) + '</b>')).join('') + '</div>');
      }
    }
    if (t === 'about') {
      const h = TL.resource(R.hea), tel = TL.resource(R.tel), ab = TL.resource(R.about); const body = $('#set .body'); if (!body) return;
      const ver = body.querySelector('.mono.cap'); const nat = ORBIT.native.info;
      if (ver) ver.textContent = ((nat && nat.app) || (ab.data && ab.data.app && ab.data.app.version) || (h.data && h.data.version) || '—') + (ab.data && ab.data.app ? ' · 服务 ' + ab.data.app.version : '') + (h.data ? ' · 已运行 ' + Math.round((h.data.uptime_s || 0) / 60) + ' 分钟' : '');
      let html = '';
      if (h.data) html += cardHTML('运行状况', ({ ok: '正常', degraded: '部分降级', fail: '异常' }[h.data.status] || h.data.status) + ' · ' + TLU.hm(h.data.generated_at), '<div class="col" style="gap:0">' + (h.data.checks || []).map((x) => kv(esc(x.id) + (x.detail && typeof x.detail !== 'object' ? ' <span class="cap" style="font-size:11px">' + esc(x.detail) + '</span>' : ''), '<span class="mono" style="font-size:12px;color:var(' + (x.status === 'ok' ? '--good' : x.status === 'warn' ? '--warn' : '--crit') + ')">' + esc(x.status) + '</span>')).join('') + '</div>', 'health');
      if (ab.data && ab.data.components) { const cp = ab.data.components; html += cardHTML('组件版本', esc((ab.data.runtime && ('Python ' + ab.data.runtime.python + ' · ' + ab.data.runtime.platform + ' ' + ab.data.runtime.arch)) || ''), '<div class="col" style="gap:0">' + ['db_schema_version', 'analytics_version', 'redaction_version', 'mapper_version', 'catalog_contract'].filter((k) => cp[k] != null).map((k) => kv(esc(k), '<span class="mono" style="font-size:12px">' + esc(cp[k]) + '</span>')).join('') + kv('mappers', '<span class="mono" style="font-size:12px">' + esc((cp.mappers || []).join(' · ')) + '</span>') + '</div>', 'about'); }
      if (tel.data || h.data) {
        const d = tel.data;
        html += cardHTML('诊断', '指标只存本机；导出诊断包供排查问题时附上', '<div class="col" style="gap:8px">' + (d ? '<div class="row" style="gap:10px">' + swBtn(d.enabled, 'tlsTel', '', '记录本机性能指标') + '<span style="font-size:13px">记录本机性能指标</span><span class="cap" style="font-size:11px">保留 ' + TLU.num(d.retention_days) + ' 天 · ' + TLU.num(d.stats && d.stats.rows) + ' 行 · ' + tlsBytes(d.stats && d.stats.bytes_est) + '</span></div>' : '') +
          '<div class="row" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn sm" data-act="tlsDiag">导出诊断包</button><button type="button" class="btn sm" data-act="setFinder">打开数据目录</button>' + (d ? '<button type="button" class="btn sm dg" data-act="tlsTelClear">清除指标数据</button>' : '') + '</div></div>', 'diagnostics');
      }
      if (html) body.insertAdjacentHTML('beforeend', '<div class="col" style="gap:12px;margin-top:4px">' + html + '</div>');
    }
  }
  const tlsSetBase = renderSet;
  renderSet = function () { if (setOpen()) tlsSync(); tlsSetBase(); if (setOpen()) tlsSetPost(); };

  const wrap = (name, fn) => { const base = ACT[name]; ACT[name] = (el, ev) => fn(base, el, ev); };
  // 通用 / 统计 / 每周报告 / 索引方式 → PATCH /v1/app/settings (外观 stays local: the gateway has no theme key)
  wrap('setRange', (base, el, ev) => { base(el, ev); tlsSetting({ default_range_days: S.range }, '默认时间范围'); });
  // patch the cached state before the demo handler re-renders: a resync still pending from the previous PATCH would
  // otherwise put the old server value back into S (a second click on 每周报告 sent true again instead of false)
  wrap('setWeekly', (base, el, ev) => { tlsSetting({ weekly_report: !S.weekly }, '每周报告'); base(el, ev); });
  wrap('setIdx', (base, el, ev) => { if (SYNC_OUT[el.dataset.v]) tlsSetting({ sync_mode: SYNC_OUT[el.dataset.v] }, '索引方式'); base(el, ev); });
  wrap('setReindex', (base, el, ev) => {
    TL.send('POST', '/v1/app/jobs', { kind: 'import' }).then(() => toast('已开始重新索引'), (e) => toast(e.code === 'job_conflict' ? '已有导入任务在进行' : TL.unavailable(e) ? '本地服务暂不可用，未能重新索引' : '重新索引失败：' + (e.message || e.code)));
  });
  // 数据源: enable / disable one source (POST /v1/app/sources), add a folder (slice 7's LVN.addSource, else chooseFolder)
  wrap('setSrc', (base, el, ev) => {
    const id = el.dataset.src, agentId = el.dataset.ag, root = el.dataset.root; if (!id) return;
    const r = TL.resource(R.disc); const prev = r.data; const list = discList() || []; const x = list.find((y) => y.id === id); if (!x) return;
    const to = !x.enabled; r.data = list.map((y) => (y.id === id ? Object.assign({}, y, { enabled: to }) : y)); renderSet();
    TL.send('POST', '/v1/app/sources', { agent: agentId, root, enabled: to }).then(() => { toast(lvAgentOf(agentId).name + (to ? ' 已启用，下次索引时导入' : ' 已停用：不再导入新会话，已有数据保留')); TL.invalidate((q) => q.path === R.state || q.path === R.disc); },
      (e) => { r.data = prev; renderSet(); tlsErr(e, to ? '启用来源' : '停用来源'); });
  });
  const GUESS = [[/\.claude\b|claude/i, 'claude_code'], [/\.codex\b|codex/i, 'codex'], [/opencode/i, 'opencode'], [/kimi/i, 'kimi'], [/hermes/i, 'hermes'], [/\bdsh\b|deepseek/i, 'dsh'], [/\.pi\b|\/pi\b/i, 'pi'], [/gemini/i, 'gemini'], [/copilot/i, 'copilot']];
  wrap('setAddSrc', (base, el, ev) => {
    const agentId = el && el.dataset && el.dataset.v && el.dataset.v !== '自定义' ? el.dataset.v : null;
    if (window.LVN && typeof window.LVN.addSource === 'function') return window.LVN.addSource({ agent: agentId, from: 'settings' });
    ORBIT.native.request('chooseFolder', { purpose: 'source', agent: agentId || undefined }).then((f) => {
      if (!f || f.cancelled || !f.path) return;
      const ag = agentId || (GUESS.find((g) => g[0].test(f.path)) || [])[1];
      if (!ag) { toast('认不出这个文件夹属于哪个 Agent：在「未检测到」那一行点「指定…」'); return; }
      if (!LV.importable(ag)) { toast(lvAgentOf(ag).name + ' 暂不支持导入会话：Orbit 还没有它的会话连接器'); return; }
      return TL.send('POST', '/v1/app/sources', { agent: ag, root: f.path, enabled: true }).then((x) => {
        const src = x.data || {}; TL.invalidate((q) => q.path === R.state || q.path === R.disc);
        toast('已添加 ' + lvAgentOf(ag).name + ' 来源，正在索引');
        return TL.send('POST', '/v1/app/jobs', { kind: 'import', source_ids: src.id ? [src.id] : undefined }).catch(() => {});
      }, (e) => tlsErr(e, '添加来源'));
    });
  });
  wrap('setMap', (base, el, ev) => {
    TL.send('GET', R.tmap).then((x) => {
      if (!setOpen() || S.setTab !== 'sources') return;   // answered after the user left the tab: no late sheet over another tab
      const d = x.data || {}; const ags = AG.filter((a) => (d.kinds || []).some((k) => (k.names || []).some((n) => lvAgentOf(n.agent).id === a.id)));
      openModal(modalHead('工具名映射表', '各 Agent 的工具名归一后才能跨 Agent 统计 · 规则 ' + esc(d.version || '')) + '<div class="mb scroll-x" data-tl="tool-map"><table class="tbl"><thead><tr><th>统一名</th>' + ags.map((a) => '<th>' + esc(a.short) + '</th>').join('') + '</tr></thead><tbody>' +
        (d.kinds || []).map((k) => '<tr><td style="font-weight:600">' + esc(k.label || k.kind) + '</td>' + ags.map((a) => '<td class="mono" style="font-size:12px">' + esc((k.names || []).filter((n) => n.agent && lvAgentOf(n.agent).id === a.id).map((n) => n.name).join(' · ') || '—') + '</td>').join('') + '</tr>').join('') + '</tbody></table></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide');
    }, (e) => toast(TL.unavailable(e) ? '本地服务暂不提供工具名映射表' : '读取映射表失败：' + (e.message || e.code)));
  });
  wrap('setPause', (base, el, ev) => {
    const to = !S.paused; const label = to ? '暂停采集' : '恢复采集';
    const req = () => TL.send('POST', R.col + '/' + (to ? 'pause' : 'resume'), to ? { reason: 'user' } : {});
    const after = (d) => { if (d && d.catch_up_job_id) toast('已恢复采集，正在补采暂停期间的会话'); if (TL.ops) TL.ops.realtime().catch(() => {}); };
    // resuming: the last realtime snapshot still says collection_paused until the next frame; drop that so 98 keeps the switch
    const unpause = () => { const rt = TL.ops && TL.ops.rt; if (!to && rt && (rt.status === 'paused' || rt.reason === 'collection_paused')) TL.ops.rt = Object.assign({}, rt, { status: 'idle', reason: null }); };
    if (tlsWrite(R.col, { paused: to }, req, label, after)) { unpause(); base(el, ev); return; }
    // the collection setting is not loaded here (menu-bar panel / HUD / widgets surface): write first, flip after the answer
    req().then((x) => { TL.invalidate((r) => r.path === R.col); unpause(); S.paused = to; render(); toast(to ? '已暂停采集' : '已恢复采集'); after(x && x.data); },
      (e) => toast(TL.unavailable(e) ? label + '未保存：本地服务暂不可用' : label + '失败：' + (e.message || e.code)));
  });
  // 隐私
  wrap('setRule', (base, el, ev) => {
    const r = TL.resource(R.rules); if (!r.data) return;
    const k = el.dataset.k; const x = (r.data.rules || []).find((y) => y.id === k); if (!x || x.locked) return;
    TLS.rd = null;
    tlsWrite(R.rules, { rules: r.data.rules.map((y) => (y.id === k ? Object.assign({}, y, { enabled: !x.enabled }) : y)) }, () => TL.send('PUT', R.rules, { enabled: { [k]: !x.enabled } }), '保存脱敏规则');
    renderSet();
  });
  wrap('setTestIn', (base, el, ev) => { S.ruleSample = el.value; if (TL.resource(R.rules).data) tlsPreviewRules(el.value); else base(el, ev); });
  wrap('setFinder', (base, el, ev) => {
    const d = TL.resource(R.data).data; const home = d && d.home;
    if (!home) { tlsRes(R.data); toast('还没拿到数据目录位置，稍后再试'); return; }
    ORBIT.native.request('reveal', { path: home });
  });
  wrap('setClear', (base, el, ev) => {
    TL.send('GET', R.data).then((x) => {
      const d = x.data || {}; TLS.clear = d; const word = d.confirm_word || '清除';
      const comp = {}; (d.components || []).forEach((c) => { comp[c.id] = c.label || c.id; });
      openModal(modalHead('清除全部数据？', esc(d.note || '会删除索引、分析结果与备份，不会动各 Agent 自己的会话日志')) + '<div class="mb col" style="gap:8px" data-tl="clear"><div class="cap" style="font-size:12px">将删除：' + esc((d.will_delete || []).map((k) => comp[k] || k).join('、')) + ' · 共 ' + tlsBytes(d.total_bytes) + '</div>' +
        (d.installs_active ? '<div class="cap" style="font-size:12px;color:var(--warn)">还有 ' + d.installs_active + ' 个已安装的组件，清除不会撤销它们</div>' : '') +
        '<label for="clrIn" style="font-size:13px">输入 <b class="mono">' + esc(word) + '</b> 以确认：</label><input id="clrIn" data-in="setClearIn" autocomplete="off" style="' + FIELD + ';height:28px;font-size:13px"></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" id="clrBtn" data-act="setClearDo" disabled style="background:var(--crit);border-color:var(--crit);color:#fff">清除全部数据</button></div>');
    }, (e) => toast(TL.unavailable(e) ? '本地服务暂不提供清除数据' : '读取数据目录失败：' + (e.message || e.code)));
  });
  wrap('setClearIn', (base, el, ev) => { const b = $('#clrBtn'); if (b) b.disabled = el.value.trim() !== ((TLS.clear && TLS.clear.confirm_word) || '清除'); });
  function tlsClear(cancel) {
    const inp = $('#clrIn'); const word = inp ? inp.value.trim() : (TLS.clear && TLS.clear.confirm_word) || '清除';
    TL.send('POST', '/v1/app/data/clear', cancel ? { confirm: word, cancel_jobs: true } : { confirm: word }).then(() => { closeModal(); toast('已清除。重启 Orbit 后从头导入'); TL.invalidate(); },
      (e) => { if (e.code === 'job_active') toast('有任务正在进行', { act: '取消任务并清除', onAct: () => tlsClear(true) }); else tlsErr(e, '清除数据'); });
  }
  wrap('setClearDo', () => tlsClear(false));
  // 分析
  wrap('setAiCh', (base, el, ev) => {
    const r = TL.resource(R.con); if (!r.data) return base(el, ev);
    const eng = conEngine(r.data); if (!eng) { toast('先选一个执行者'); return; }
    const cls = CLS[el.dataset.k]; const g = Object.assign({}, (r.data.grants || {})[eng]); g[cls] = !g[cls];
    tlsWrite(R.con, { grants: Object.assign({}, r.data.grants, { [eng]: g }) }, () => TL.send('PUT', R.con, { grants: { [eng]: { [cls]: g[cls] } } }), 'AI 通道授权', (d) => { if (d && (d.cancelled_jobs || []).length) toast('已撤回授权，取消了 ' + d.cancelled_jobs.length + ' 个进行中的任务'); });
    renderSet();
  });
  wrap('setEngine', (base, el, ev) => {
    const mode = MODE_OUT[el.dataset.v];
    if (!mode) { toast('本机模型（Ollama）还没有接入，暂时只能选「仅统计」或「本地 Agent」'); return; }
    tlsWrite(R.con, { mode }, () => TL.send('PUT', R.con, { mode }), '切换分析引擎'); base(el, ev);
  });
  // 通知
  wrap('setNotif', (base, el, ev) => {
    const r = TL.resource(R.pol); if (!r.data) return base(el, ev);
    hold(() => base(el, ev));
    const m = matrixFromS(r.data.matrix); const k = polKey(r.data.matrix, el.dataset.e) || TLS_KIND[el.dataset.e][0];
    tlsWrite(R.pol, { matrix: m }, () => TL.send('PUT', R.pol, { matrix: { [k]: m[k] } }), '保存通知设置');
  });
  wrap('setNotifPreset', (base, el, ev) => {
    const r = TL.resource(R.pol); if (!r.data) return base(el, ev);
    hold(() => base(el, ev));
    tlsWrite(R.pol, { matrix: matrixFromS(r.data.matrix) }, () => TL.send('PUT', R.pol, {}, { query: { preset: el.dataset.v === 'quiet' ? 'quiet' : 'all' } }), '应用通知预设');
  });
  wrap('setMute', (base, el, ev) => {
    const to = !S.hud.mute; const until = new Date(Date.now() + 86400000).toISOString();
    tlsWrite(R.snz, { items: to ? [{ scope: 'global', until }] : [] }, () => (to ? TL.send('POST', R.snz, { seconds: 86400, scope: 'global' }) : TL.send('DELETE', R.snz, null, { query: { scope: 'global' } })).then((x) => ({ data: { items: to ? [x.data || { scope: 'global', until }] : [] } })), to ? '暂停提醒' : '恢复提醒');
    base(el, ev);
  });
  wrap('setTestNotif', (base, el, ev) => {
    TLS.testAt = Date.now();   // the frame of POST /v1/notifications/test (type system) goes to the system as well
    TL.send('POST', '/v1/notifications/test', {}).then(() => { if (!TL.events.connected) base(el, ev); else toast('已发送测试通知'); }, (e) => { if (TL.unavailable(e)) base(el, ev); else tlsErr(e, '发送测试通知'); });
  });
  wrap('setUpdate', () => { const ab = TL.resource(R.about).data; const u = ab && ab.update; toast(u && u.available ? '有新版本 ' + u.available : u && u.checked_at ? '已是最新版本' : '还没有检查过更新'); });
  Object.assign(ACT, {
    tlsTel: () => { const r = TL.resource(R.tel); if (!r.data) return; const to = !r.data.enabled; tlsWrite(R.tel, { enabled: to }, () => TL.send('PUT', R.tel, { enabled: to }), to ? '开启指标记录' : '关闭指标记录'); renderSet(); },
    tlsTelClear: () => TL.send('DELETE', R.tel + '/data').then((x) => { toast('已清除 ' + TLU.num(x.data && x.data.deleted_rows) + ' 行指标数据'); TL.invalidate((r) => r.path === R.tel); }, (e) => tlsErr(e, '清除指标数据')),
    // diagnostics: the gateway's report (GET /v1/platform/diagnostics) saved through the host's save panel (browser: download)
    tlsDiag: () => {
      toast('正在导出诊断包…');
      TL.send('GET', '/v1/platform/diagnostics').then((x) => {
        const d = new Date(); const stamp = d.getFullYear() + String(d.getMonth() + 1).padStart(2, '0') + String(d.getDate()).padStart(2, '0') + '-' + String(d.getHours()).padStart(2, '0') + String(d.getMinutes()).padStart(2, '0');
        return ORBIT.native.request('save', { filename: 'orbit-diagnostics-' + stamp + '.json', mime: 'application/json', text: JSON.stringify(x.data, null, 2) });
      }).then((r) => {
        if (!r || r.cancelled) return;
        if (r.ok === false) { toast('导出诊断包失败：' + (r.error || '未知原因')); return; }
        toast(r.path ? '诊断包已保存：' + r.path : '诊断包已下载', r.path ? { act: '在 Finder 中显示', onAct: () => ORBIT.native.request('reveal', { path: r.path }) } : undefined);
      }, (e) => toast(TL.unavailable(e) ? '本地服务暂不提供诊断导出' : '导出诊断包失败：' + (e.message || e.code)));
    }
  });

  /* ---------- notify frames → banner / HUD / 菜单栏角标 ---------- */
  // In the native shell a banner raised while Orbit is not the focused app (window hidden, or visible on another screen
  // behind another app) also goes to the system (notify → UNUserNotification). n.system (测试 / 预览通知) always goes, with
  // force:true, so the first authorisation prompt can appear; a {delivered:false, reason} reply is shown instead of swallowed.
  const tlsNotifyBase = notify;
  notify = function (n) {
    tlsNotifyBase(n);
    if (!ORBIT.native.isNative || (S.paused && !n.force)) return;
    let away = true; try { away = document.hidden || !document.hasFocus(); } catch (e) { /* keep away */ }
    if (!n.system && !away) return;
    const msg = { id: n.id || undefined, title: n.t || '', body: n.b || '' };
    if (!n.system) { ORBIT.native.post('notify', msg); return; }
    msg.force = true;
    NATV.ask('notify', msg, 5000, 'orbit:notified').then((r) => {
      if (r && r.delivered === false) {
        if (/denied|not.?authori[sz]ed/i.test(r.reason || '')) S.notifAuth = 'denied';
        toast('系统通知没有送达：' + (r.reason === 'denied' ? '通知权限已关闭，在「设置 › 通知」中打开' : r.reason || '原因未知'));
        renderSet();
      } else if (r && r.delivered) NATV.notifGet();
    }, () => { /* an older host does not answer: the post itself went out */ });
  };
  // 菜单栏角标 in the native shell: the kinds delivered on the badge channel, pruned once they are no longer open; posted as
  // statusBadge {state: none | info | warn} on change (paused → none). The simulated menu bar (S.sim) is hidden in body.native.
  TLS.badgeK = new Set(); TLS.badgeSent = null;
  function tlsBadge() {
    if (!NATV.has('statusBadge')) return;
    const K = TLS.badgeK;
    if (K.has('waiting') && !S.waitOpen) K.delete('waiting');
    ['stuck', 'ctx'].forEach((k) => { if (K.has(k) && !S.attn.has(k)) K.delete(k); });
    const st = S.paused || !K.size ? 'none' : K.has('waiting') || K.has('stuck') ? 'warn' : 'info';
    if (st !== TLS.badgeSent) { TLS.badgeSent = st; ORBIT.native.post('statusBadge', { state: st }); }
  }
  function tlsNotify(d) {
    const k = tlsKind(d.type); const ch = d.channels || [];
    const toHud = ch.indexOf('hud') >= 0 && !S.hud.mute, toBadge = ch.indexOf('badge') >= 0;
    const set = (v) => { if (toHud) S.hudSim = v; if (toBadge) S.sim = v; };
    if (k && toBadge) TLS.badgeK.add(k);
    if (k && (toHud || toBadge)) {
      if (k === 'done') { set('done'); clearTimeout(TLS.doneT); TLS.doneT = setTimeout(() => { simClear('done'); TLS.badgeK.delete('done'); render(); }, 8000); }
      else if (k === 'waiting') { S.waitOpen = true; set('waiting'); }
      else if (k === 'stuck' || k === 'ctx') { S.attn.add(k); set(k); }
    }
    if (ch.indexOf('banner') >= 0) notify({ id: d.id, t: d.title || '通知', b: d.body || '', force: true, system: d.type === 'system' && Date.now() - (TLS.testAt || 0) < 15000, a1: '查看', on1: () => { S.pop = true; render(); }, a2: '稍后', on2: () => { if (d.id) TL.send('POST', '/v1/notifications/' + encodeURIComponent(d.id) + '/ack', { snooze_s: 3600 }).catch(() => {}); } });
    render();
  }
  TL.on('event', (ev) => {
    const d = ev.data || {};
    if (ev.name === 'notification') tlsNotify(d);
    else if (ev.name === 'attention') TL.invalidate((r) => r.path === R.attn);
    else if (ev.name === 'service' && d.name === 'collection') { TLS.colFrame = d.state === 'paused'; S.paused = TLS.colFrame; tlsBadge(); }
  });

  /* ---------- status strip on the studio (refreshStudio redraws #main without the 96 render wrapper) ---------- */
  function tlsStrip() {
    if (S.route !== 'studio') return;
    const c = $('#content'); if (!c) return;
    let s = c.querySelector(':scope > [data-tl="strip"]');
    if (!s) { const h = TLU.strip(TL, 'studio', TL_VIEWS.studio); if (h) c.insertAdjacentHTML('afterbegin', h); s = c.querySelector(':scope > [data-tl="strip"]'); }
  }
  RENDER_HOOKS.push(() => tlsStrip());
  const tlsRenderBase = render;
  render = function () { tlsSync(); tlsRenderBase(); tlsStrip(); tlsBadge(); };
}
