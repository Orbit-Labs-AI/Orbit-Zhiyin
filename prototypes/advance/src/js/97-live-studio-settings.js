/* ============ live binding: A9 生成工坊 · 问本地 Agent · 设置 · 通知（TandemLive studio-settings section） ============
   Loaded after 96-live-bind.js; only active in live mode. The demo pages keep their markup and visual language: live data is
   written into the same structures the demo renders from (CTX / GEN / STEP_DUR / S.notif / S.paused / S.aiCh …) or patched
   into the rendered cards, never into a new layout. A route the gateway does not serve yet (404 / 501), a 503 or an offline
   gateway keeps the demo values, and the page (or card) carries the 示例数据 badge. Real answers (403 consent_required,
   409 preview_stale, 422 …) are shown as they are. Endpoints: .work/be-notes/endpoints.md (ai-runtime, platform-notify,
   platform-core). */
const TLS = { colFrame: null, engine: null, engInit: false, preview: null, previewKey: null, previewBusy: false, limit: null, ctl: null, genDemo: {}, durDemo: null, ask: null, hold: false, attnAt: null, doneT: null };
const TLS_TASK = { Skill: 'generate.skill', Hook: 'generate.hook', '规则': 'generate.rule', '子代理': 'generate.subagent', '工作流': 'generate.glue' };
const TLS_STAGE = { pack: 0, analyse: 1, analyze: 1, draft: 2, check: 3, replay: 4, review: 5, cross: 6 };
const TLS_DONE = ['done', 'ok', 'succeeded', 'completed', 'skipped'];
// notification types (backend names first, then the aliases it accepts) for the matrix rows of settings › 通知
const TLS_KIND = { waiting: ['awaiting_approval', 'waiting'], done: ['done', 'session_done'], stuck: ['failing', 'stuck'], ctx: ['context_pressure', 'ctx'], weekly: ['weekly', 'weekly_report'] };
const TLS_ART_KIND = { skill: 'Skill', hook: 'Hook', rule: '规则', subagent: '子代理', glue: '工作流', command: '命令' };
const tlsKind = (type) => Object.keys(TLS_KIND).find((k) => TLS_KIND[k].indexOf(type) >= 0) || null;
const tlsAgOf = (eid) => Object.keys(TandemLive.AGENT_KEYS).find((a) => TandemLive.AGENT_KEYS[a].indexOf(eid) >= 0) || null;
function tlsRes(path, query) { const r = TL.resource(path, { query }); if (r.dirty && !r.loading) TL.load(r); return r; }
const tlsDemo = (r) => !!(r && r.data == null && r.error && TL.unavailable(r.error));
function tlsBytes(n) { if (n == null || !Number.isFinite(n)) return TLU.DASH; const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; } return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + ' ' + u[i]; }
function tlsDate(ts) { const d = new Date(ts); return isNaN(d) ? TLU.DASH : (d.getMonth() + 1) + '/' + String(d.getDate()).padStart(2, '0'); }
function tlsErr(e, what) { toast(what + '失败：' + (e.message || e.code)); }
// optimistic write against a cached GET resource: patch r.data now, replace it with the answer, roll back on any failure
function tlsWrite(path, patch, req, label, ok) {
  const r = TL.resource(path); const prev = r.data; if (prev == null) return false;
  r.data = Object.assign({}, prev, patch);
  req().then((x) => { if (x && x.data && typeof x.data === 'object') r.data = Object.assign({}, prev, x.data); if (ok) ok(x && x.data); render(); },
    (e) => { r.data = prev; render(); toast(TL.unavailable(e) ? label + '未保存：本地服务暂不可用' : label + '失败：' + (e.message || e.code)); });
  return true;
}

if (TL.mode === 'live') {
  /* ---------- A9 生成工坊 ---------- */
  TL.bind('studio', [{ name: 'engines', path: '/v1/ai/engines', scope: false }], (d) => d.engines);
  const engines = () => { const v = TL_VIEWS.studio; const d = v && v.res.engines.data; return d && d.engines ? d : null; };
  const tlsEngine = () => { const d = engines(); if (!d) return null; if (TLS.engine) return TLS.engine; const e = d.engines.find((x) => tlsAgOf(x.id) === S.studio.agent); return e ? e.id : d.default_engine; };
  const tlsSel = () => { const items = {}; CTX.forEach((c) => { items[c[0]] = !!S.studio.ctx[c[0]]; }); return { items }; };
  const tlsPreviewKey = () => [S.studio.type, tlsEngine(), S.studio.tpl, JSON.stringify(tlsSel())].join('|');
  function tlsApplyPreview(d) {
    if (!TLS.ctxDemo) TLS.ctxDemo = CTX.slice();
    const redact = TLS.ctxDemo.find((c) => c[0] === 'redact');
    CTX.length = 0;
    (d.items || []).forEach((it) => {
      CTX.push([it.key, it.label || it.key, (it.consent === 'missing' ? '需要授权 · ' : '') + (it.desc || ''), it.tokens || 0]);
      CTX_HITS[it.key] = it.redaction_hits || 0;
      CTX_SAMPLE[it.key] = (it.preview || []).map((l) => String(l).replace(/\{\{/g, '{ {'));
      if (S.studio.ctx[it.key] == null) S.studio.ctx[it.key] = !!it.enabled;
    });
    if (redact) CTX.push(redact);
    TLS.limit = d.input_budget || null;
  }
  function tlsPreview(force) {
    const key = tlsPreviewKey();
    if (TLS.previewBusy || (!force && TLS.previewKey === key)) return;
    TLS.previewKey = key; TLS.previewBusy = true;
    TL.send('POST', '/v1/ai/preview', { task_id: TLS_TASK[S.studio.type], engine: tlsEngine(), selection: tlsSel(), goal: S.studio.goal, goal_source: 'ask', template: S.studio.tpl })
      .then((r) => { TLS.preview = r.data; tlsApplyPreview(r.data || {}); }, (e) => { TLS.preview = null; if (!TL.unavailable(e)) toast('上下文预览失败：' + (e.message || e.code)); })
      .then(() => { TLS.previewBusy = false; if (tlsPreviewKey() !== TLS.previewKey) tlsPreview(); else { refreshStudio(); refreshCtx(); } });
  }
  // same markup as the demo's token stack, with the gateway's input budget
  const tlsTokBarBase = tokBar;
  tokBar = function () {
    if (!TLS.limit) return tlsTokBarBase();
    const L = TLS.limit; const tok = ctxTokens(); const scale = Math.max(tok, L) * 1.08; const over = tok > L;
    const segs = CTX.filter((c) => c[3] && S.studio.ctx[c[0]]).map((c) => '<span class="st-seg ' + esc(c[0]) + '" style="width:' + (c[3] / scale * 100) + '%" title="' + esc(c[1]) + ' ≈ ' + f1(c[3] / 1000) + 'k"></span>').join('');
    return '<div class="st-tok' + (over ? ' over' : '') + '" id="stTok" role="img" aria-label="上下文包 ≈ ' + f1(tok / 1000) + 'k tokens，上限 ' + f1(L / 1000) + 'k' + (over ? '，已超出' : '') + '"><div class="st-tok-bar">' + segs + '<span class="st-tok-lim" style="left:' + (L / scale * 100) + '%"></span></div>' +
      '<div class="row st-tok-cap"><span class="mono' + (over ? ' crit' : '') + '" data-tok>≈ ' + f1(tok / 1000) + 'k tokens</span><span class="mono cap">上限 ' + f1(L / 1000) + 'k' + (over ? ' · 超出 ' + f1((tok - L) / 1000) + 'k，原始片段会被截断' : ' · ' + Math.round(tok / L * 100) + '%') + '</span></div></div>';
  };
  const tlsStudioBase = PAGES.studio; const tlsStudioAfter = PAGES.studio.after;
  PAGES.studio = function () {
    const v = lvView('studio'); const d = engines();
    TLS.studioDemo = tlsDemo(v.res.engines);
    if (d && !TLS.engInit) { TLS.engInit = true; TLS.engine = d.default_engine || null; const a = tlsAgOf(TLS.engine); if (a) S.studio.agent = a; }
    if (d) tlsPreview();
    let html = tlsStudioBase();
    if (d) html = html.replace('已检测：Claude Code · Codex · Gemini CLI · DeepSeek · Copilot', '已检测：' + esc(d.engines.map((e) => e.name + (!e.available ? '（不可用）' : e.logged_in === false ? '（未登录）' : '')).join(' · ')));
    return html;
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
    if (TL.unavailable(e) && !run.live.id) {   // the gateway has no AI routes yet: run the demo workflow instead
      S.studio.run = null; tlsRunReset(); TLS.studioDemo = true; toast('本地服务暂不提供生成接口，改用示例流程');
      tlsStartBase(el); return;
    }
    const det = e.detail || {}; let opt;
    const msg = e.code === 'consent_required' ? '需要授权：' + (det.missing || []).join('、') : e.code === 'preview_stale' ? '上下文已变化，已重新打包，请再点一次「开始生成」'
      : e.code === 'budget_exhausted' ? '今日 AI 预算已用完' + (det.daily_cap != null ? '（上限 $' + det.daily_cap + '）' : '') : e.code === 'over_budget' ? '上下文超出预算（' + TLU.num(det.total_tokens) + ' / ' + TLU.num(det.input_budget) + ' tokens）'
        : e.code === 'engine_unavailable' ? '执行者不可用（' + ({ not_installed: '未安装', not_logged_in: '未登录' }[det.reason] || det.reason || e.code) + '）' : e.code === 'ai_disabled' ? 'AI 已在设置中关闭' : (e.message || e.code);
    if (e.code === 'consent_required' || e.code === 'ai_disabled') opt = { act: '去设置', onAct: () => openSettings('analysis') };
    if (e.code === 'preview_stale') tlsPreview(true);
    run.stopped = true; run.log.push('! ' + msg); refreshStudio(); renderSide(); toast(msg, opt);
  }
  const tlsStartBase = ACT.studioStart;
  ACT.studioStart = (el, ev) => {
    const d = engines(); if (!d) { tlsRunReset(); return tlsStartBase(el, ev); }
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
    TL.send('POST', '/v1/ai/jobs', { task_id: TLS_TASK[type], engine: eid, template: run.tpl, goal: S.studio.goal, goal_source: 'ask', selection: tlsSel(), preview_digest: TLS.preview ? TLS.preview.preview_digest : undefined }, { signal: ctl.signal })
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
  const tlsHistBase = ACT.studioHistory;
  ACT.studioHistory = (el) => {
    TL.send('GET', '/v1/ai/artifacts', null, { query: { limit: 20 } }).then((r) => {
      const xs = Array.isArray(r.data) ? r.data : (r.data && r.data.items) || [];
      openModal(modalHead('历史产物', '由生成工坊产出的内容；草稿与已归档的都在这里') + '<div class="mb col" style="gap:6px" data-tl="artifacts">' + (xs.length ? xs.map((a) => '<div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--hair);font-size:13px"><span>' + esc((TLS_ART_KIND[a.kind] || a.kind) + ' · ' + (a.name || a.title || a.artifact_id)) + '</span><span class="cap mono">' + esc({ draft: '草稿', blocked: '已拦截', archived: '已归档' }[a.status] || a.status || '') + ' · ' + tlsDate(a.created_at) + '</span></div>').join('') : '<div class="cap" style="padding:12px 0">还没有产物</div>') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
    }, (e) => { if (TL.unavailable(e)) tlsHistBase(el); else tlsErr(e, '读取历史产物'); });
  };

  /* ---------- 问本地 Agent ---------- */
  const tlsAskOpenBase = openAsk;
  openAsk = function (ctx) {
    TLS.ask = null; tlsAskOpenBase(ctx); if (!ASK) return;
    const c = ASK.ctx;
    TL.send('GET', '/v1/ai/ask/presets', null, { query: { context: c } }).then((r) => {
      const xs = Array.isArray(r.data) ? r.data : (r.data && (r.data.items || r.data.presets)) || [];
      const first = $('#modal [data-act="askPick"]');
      if (!xs.length || !ASK || ASK.ctx !== c || !first) return;
      TLS.ask = { ctx: c, presets: xs };
      const box = first.parentElement; box.setAttribute('data-tl', 'ask-presets');
      box.innerHTML = xs.map((p, i) => '<button type="button" class="chip sm" data-act="askPick" data-i="' + i + '">' + esc(p.question) + '</button>').join('');
      $$('#modal .mh .cap').forEach((x) => { x.textContent = x.textContent.replace(' · Demo 中为预置回答', ''); });
    }, () => { /* demo presets stay */ });
  };
  const tlsAnswer = (d) => (d.answer || '') + ((d.refs || []).length ? '\n\n引用：' + d.refs.map((r) => r.kind + ' ' + r.id).join('、') : '');
  function tlsThinking(q) { const a = $('#askA'); if (a) a.innerHTML = '<div class="mono cap" style="font-size:11px;margin-bottom:6px">问：' + esc(q) + '</div><span class="cap" data-tl="ask-wait">本地 Agent 正在回答…</span>'; }
  function tlsAsk(body, q, fallback) {
    clearInterval(ASKT); tlsThinking(q);
    TL.send('POST', '/v1/ai/ask', body).then((r) => {
      const d = r.data || {};
      if (d.answer != null) return d;
      if (!d.job_id) return { answer: '' };
      return TL.pollJob(d.job_id, null).then((job) => { if (TLS_DONE.indexOf(job.status) < 0) throw Object.assign(new Error((job.error && (job.error.message || job.error.code)) || '回答失败'), { status: 500, code: 'job_' + job.status }); return job.result || {}; });
    }).then((d) => { if (ASK) askStream(q, tlsAnswer(d)); }, (e) => {
      if (TL.unavailable(e)) { fallback(); return; }
      if (ASK) askStream(q, '无法回答：' + (e.message || e.code) + (e.code === 'consent_required' ? '\n\n到 设置 › 分析 授权后再试。' : ''));
    });
  }
  const tlsPickBase = ACT.askPick;
  ACT.askPick = (el) => {
    const a = TLS.ask; if (!a || !ASK || a.ctx !== ASK.ctx) return tlsPickBase(el);
    const p = a.presets[+el.dataset.i]; if (!p) return;
    tlsAsk({ context: a.ctx, preset_index: p.index }, p.question, () => { const i = +el.dataset.i; if (ASKQ[ASK.ctx][i]) askStream(ASKQ[ASK.ctx][i], askAnswer(ASK.ctx, i)); });
  };
  const tlsSendBase = ACT.askSend;
  ACT.askSend = (el) => {
    const inp = $('#askIn'); const q = inp ? inp.value.trim() : ''; if (!q || !ASK) return tlsSendBase(el);
    tlsAsk({ context: ASK.ctx, question: q }, q, () => { if (inp) inp.value = q; tlsSendBase(el); });
    if (inp) inp.value = '';
  };

  /* ---------- 设置：分析 / 隐私 / 数据源 / 通知 / 关于 ---------- */
  const R = { col: '/v1/platform/collection', pol: '/v1/notifications/policy', snz: '/v1/notifications/snooze', attn: '/v1/notifications/attention', con: '/v1/ai/consent', sto: '/v1/platform/storage', tel: '/v1/platform/telemetry', hea: '/v1/platform/health' };
  const polKey = (m, k) => TLS_KIND[k].find((t) => m && Object.prototype.hasOwnProperty.call(m, t)) || null;
  const CLS = { sum: 'summary', snip: 'snippets', raw: 'raw' };
  const MODE_IN = { off: 'stats', stats: 'stats', agent: 'agent', ollama: 'ollama' }; const MODE_OUT = { stats: 'off', agent: 'agent', ollama: 'ollama' };
  const conEngine = (d) => TLS.engine || d.default_engine;
  // server state → the demo's S fields (skipped while a demo handler is mid-way, see TLS.hold)
  function tlsSync() {
    if (TLS.hold) return;
    const col = tlsRes(R.col), pol = tlsRes(R.pol), snz = tlsRes(R.snz), attn = tlsRes(R.attn);
    // a collection frame is newer than a GET that was already in flight: it patches the cached answer once it lands
    if (col.data && TLS.colFrame != null) { col.data = Object.assign({}, col.data, { paused: TLS.colFrame }); TLS.colFrame = null; }
    if (col.data) S.paused = !!col.data.paused;
    if (pol.data && pol.data.matrix) NEV.forEach((e) => { const k = polKey(pol.data.matrix, e[0]); if (k) { const ch = pol.data.matrix[k] || []; S.notif[e[0]] = ['banner', 'hud', 'badge'].map((x) => (ch.indexOf(x) >= 0 ? 1 : 0)); } });
    if (snz.data) S.hud.mute = (snz.data.items || []).some((x) => x.scope === 'global' && Date.parse(x.until) > Date.now());
    if (attn.data && attn.updatedAt !== TLS.attnAt) {
      TLS.attnAt = attn.updatedAt;
      const has = (k) => (attn.data.items || []).some((i) => tlsKind(i.type) === k);
      ['stuck', 'ctx'].forEach((k) => { if (has(k)) S.attn.add(k); else S.attn.delete(k); });
      S.waitOpen = has('waiting'); simSettle();
    }
    const con = S.setTab === 'analysis' && !$('#set').hidden ? tlsRes(R.con) : TL.resource(R.con);
    if (con.data) { const g = (con.data.grants || {})[conEngine(con.data)] || {}; S.aiCh = { sum: !!g.summary, snip: !!g.snippets, raw: !!g.raw }; if (MODE_IN[con.data.mode]) S.engine = MODE_IN[con.data.mode]; }
  }
  const hold = (fn) => { TLS.hold = true; try { fn(); } finally { TLS.hold = false; } };
  const matrixFromS = (prev) => { const m = Object.assign({}, prev || {}); NEV.forEach((e) => { m[polKey(prev, e[0]) || TLS_KIND[e[0]][0]] = ['banner', 'hud', 'badge'].filter((x, i) => S.notif[e[0]][i]); }); return m; };
  const setCard = (title) => $$('#set .card').find((x) => { const t = x.querySelector('.ct'); return t && t.textContent === title; });
  const cardHTML = (title, sub, inner, tl) => '<div class="card" data-tl="' + tl + '"><div class="row" style="padding:12px 14px 0;flex-wrap:wrap;align-items:flex-start"><div style="flex:1;min-width:200px"><div class="ct">' + title + '</div>' + (sub ? '<div class="cap" style="font-size:11px">' + sub + '</div>' : '') + '</div></div><div style="padding:10px 14px 14px">' + inner + '</div></div>';
  function sample(title) { const c = setCard(title); const t = c && c.querySelector('.ct'); if (t && !c.querySelector('[data-tl="sample"]')) t.insertAdjacentHTML('beforeend', ' ' + TLU.sample()); }
  const kv = (l, v) => '<div class="row" style="padding:5px 0;border-bottom:1px solid var(--hair);font-size:12px"><span style="flex:1;min-width:0">' + l + '</span>' + v + '</div>';
  function tlsSetPost() {
    const t = S.setTab;
    if (t === 'sources' && tlsDemo(TL.resource(R.col))) sample('索引方式');
    if (t === 'notify') { if (tlsDemo(TL.resource(R.pol))) sample('投递矩阵'); if (tlsDemo(TL.resource(R.snz))) sample('暂停提醒'); }
    if (t === 'analysis' && tlsDemo(TL.resource(R.con))) sample('AI 通道');
    if (t === 'analysis') {
      const d = TL.resource(R.con).data; const c = setCard('AI 通道');
      if (d && c && d.settings && d.settings.daily_usd_cap != null) c.lastElementChild.insertAdjacentHTML('beforeend', '<div class="cap" data-tl="ai-cap" style="font-size:11px;margin-top:8px">每日 AI 预算上限 ' + TLU.money(d.settings.daily_usd_cap) + ' · 授权对象：' + esc(conEngine(d)) + '</div>');
    }
    if (t === 'privacy') {
      const r = tlsRes(R.sto); const c = setCard('数据存储');
      if (tlsDemo(r)) sample('数据存储');
      else if (r.data && c) {
        const d = r.data; const top = c.querySelector('.row .mono'); const b = c.querySelector('b.mono');
        if (top) top.textContent = d.home || top.textContent; if (b) b.textContent = tlsBytes(d.total_bytes);
        c.lastElementChild.firstElementChild.insertAdjacentHTML('beforeend', '<div class="col" style="gap:0" data-tl="storage">' + (d.components || []).map((x) => kv(esc(x.label || x.id) + (x.rebuildable ? ' <span class="cap" style="font-size:11px">可重建</span>' : ''), '<b class="mono" style="font-size:12px">' + (x.approx ? '≈ ' : '') + tlsBytes(x.bytes) + '</b>')).join('') + '</div>');
      }
    }
    if (t === 'about') {
      const h = tlsRes(R.hea), tel = tlsRes(R.tel); const body = $('#set .body'); if (!body) return;
      const ver = body.querySelector('.mono.cap'); if (h.data && ver) ver.textContent = (h.data.version || '—') + ' · 已运行 ' + Math.round((h.data.uptime_s || 0) / 60) + ' 分钟';
      let html = '';
      if (h.data) html += cardHTML('运行状况', ({ ok: '正常', degraded: '部分降级', fail: '异常' }[h.data.status] || h.data.status) + ' · ' + TLU.hm(h.data.generated_at), '<div class="col" style="gap:0">' + (h.data.checks || []).map((x) => kv(esc(x.id) + (x.detail ? ' <span class="cap" style="font-size:11px">' + esc(x.detail) + '</span>' : ''), '<span class="mono" style="font-size:12px;color:var(' + (x.status === 'ok' ? '--good' : x.status === 'warn' ? '--warn' : '--crit') + ')">' + esc(x.status) + '</span>')).join('') + '</div>', 'health');
      if (tel.data || h.data) {
        const d = tel.data;
        html += cardHTML('诊断', '指标只存本机；导出诊断包供排查问题时附上', '<div class="col" style="gap:8px">' + (d ? '<div class="row" style="gap:10px">' + swBtn(d.enabled, 'tlsTel', '', '记录本机性能指标') + '<span style="font-size:13px">记录本机性能指标</span><span class="cap" style="font-size:11px">保留 ' + TLU.num(d.retention_days) + ' 天 · ' + TLU.num(d.stats && d.stats.rows) + ' 行 · ' + tlsBytes(d.stats && d.stats.bytes_est) + '</span></div>' : '') +
          '<div class="row" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn sm" data-act="tlsDiag">导出诊断包</button>' + (d ? '<button type="button" class="btn sm dg" data-act="tlsTelClear">清除指标数据</button>' : '') + '</div></div>', 'diagnostics');
      }
      if (html) body.insertAdjacentHTML('beforeend', '<div class="col" style="gap:12px;margin-top:4px">' + html + '</div>');
    }
  }
  const tlsSetBase = renderSet;
  renderSet = function () { if (!$('#set').hidden) tlsSync(); tlsSetBase(); if (!$('#set').hidden) tlsSetPost(); };

  const wrap = (name, fn) => { const base = ACT[name]; ACT[name] = (el, ev) => fn(base, el, ev); };
  wrap('setPause', (base, el, ev) => {
    const to = !S.paused;
    tlsWrite(R.col, { paused: to }, () => TL.send('POST', R.col + '/' + (to ? 'pause' : 'resume'), to ? { reason: 'user' } : {}), to ? '暂停采集' : '恢复采集', (d) => { if (d && d.catch_up_job_id) toast('已恢复采集，正在补采暂停期间的会话'); });
    base(el, ev);
  });
  wrap('setAiCh', (base, el, ev) => {
    const r = TL.resource(R.con); if (!r.data) return base(el, ev);
    const eng = conEngine(r.data); const cls = CLS[el.dataset.k]; const g = Object.assign({}, (r.data.grants || {})[eng]); g[cls] = !g[cls];
    tlsWrite(R.con, { grants: Object.assign({}, r.data.grants, { [eng]: g }) }, () => TL.send('PUT', R.con, { grants: { [eng]: { [cls]: g[cls] } } }), 'AI 通道授权', (d) => { if (d && (d.cancelled_jobs || []).length) toast('已撤回授权，取消了 ' + d.cancelled_jobs.length + ' 个进行中的任务'); });
    renderSet();
  });
  wrap('setEngine', (base, el, ev) => { const mode = MODE_OUT[el.dataset.v]; tlsWrite(R.con, { mode }, () => TL.send('PUT', R.con, { mode }), '切换分析引擎'); base(el, ev); });
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
    TL.send('POST', '/v1/notifications/test', {}).then(() => { if (!TL.events.connected) base(el, ev); else toast('已发送测试通知'); }, (e) => { if (TL.unavailable(e)) base(el, ev); else tlsErr(e, '发送测试通知'); });
  });
  Object.assign(ACT, {
    tlsTel: () => { const r = TL.resource(R.tel); if (!r.data) return; const to = !r.data.enabled; tlsWrite(R.tel, { enabled: to }, () => TL.send('PUT', R.tel, { enabled: to }), to ? '开启指标记录' : '关闭指标记录'); renderSet(); },
    tlsTelClear: () => TL.send('DELETE', R.tel + '/data').then((x) => { toast('已清除 ' + TLU.num(x.data && x.data.deleted_rows) + ' 行指标数据'); TL.invalidate((r) => r.path === R.tel); }, (e) => tlsErr(e, '清除指标数据')),
    tlsDiag: () => { toast('正在导出诊断包…'); TL.send('POST', '/v1/platform/diagnostics/export', {}).then((x) => toast('诊断包已导出：' + ((x.data && x.data.path) || '')), (e) => tlsErr(e, '导出诊断包')); }
  });

  /* ---------- notify frames → banner / HUD / 菜单栏角标 ---------- */
  function tlsNotify(d) {
    const k = tlsKind(d.type); const ch = d.channels || [];
    const toHud = ch.indexOf('hud') >= 0 && !S.hud.mute, toBadge = ch.indexOf('badge') >= 0;
    const set = (v) => { if (toHud) S.hudSim = v; if (toBadge) S.sim = v; };
    if (k && (toHud || toBadge)) {
      if (k === 'done') { set('done'); clearTimeout(TLS.doneT); TLS.doneT = setTimeout(() => { simClear('done'); render(); }, 8000); }
      else if (k === 'waiting') { S.waitOpen = true; set('waiting'); }
      else if (k === 'stuck' || k === 'ctx') { S.attn.add(k); set(k); }
    }
    if (ch.indexOf('banner') >= 0) notify({ t: d.title || '通知', b: d.body || '', force: true, a1: '查看', on1: () => { S.pop = true; render(); }, a2: '稍后', on2: () => { if (d.id) TL.send('POST', '/v1/notifications/' + encodeURIComponent(d.id) + '/ack', { snooze_s: 3600 }).catch(() => {}); } });
    render();
  }
  TL.on('event', (ev) => {
    const d = ev.data || {};
    if (ev.name === 'notification') tlsNotify(d);
    else if (ev.name === 'attention') TL.invalidate((r) => r.path === R.attn);
    else if (ev.name === 'service' && d.name === 'collection') { TLS.colFrame = d.state === 'paused'; S.paused = TLS.colFrame; }
  });

  /* ---------- status strip on the studio (refreshStudio redraws #main without the 96 render wrapper) ---------- */
  function tlsStrip() {
    if (S.route !== 'studio') return;
    const c = $('#content'); if (!c) return;
    let s = c.querySelector(':scope > [data-tl="strip"]');
    if (!s) { const h = TLU.strip(TL, 'studio', TL_VIEWS.studio); if (h) c.insertAdjacentHTML('afterbegin', h); s = c.querySelector(':scope > [data-tl="strip"]'); }
    if (s && TLS.studioDemo && !s.querySelector('[data-tl="sample"]')) s.insertAdjacentHTML('beforeend', '<div>' + TLU.sample() + '</div>');
  }
  RENDER_HOOKS.push(() => tlsStrip());
  const tlsRenderBase = render;
  render = function () { tlsSync(); tlsRenderBase(); tlsStrip(); };
}
