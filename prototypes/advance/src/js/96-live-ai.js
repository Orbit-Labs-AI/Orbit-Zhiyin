/* ==== live AI narratives ====
   人格页 lede 下的「AI 解读 / 重新生成」→ narrate.persona；会话轨迹页「让 Agent 复盘」→ narrate.session_review。
   都是 POST /v1/ai/jobs 真实提交给所选本地 Agent，轮询（ai.job 帧到达时立即刷新）显示阶段与日志，可「停止」（cancel）。
   只有模型写成的结果（source 不是 template / empty）才显示并标紫色 AI；模型输出没通过校验（fallback）、未开启 AI、
   未授权、引擎不可用、超出今日预算都在原位如实说明，不把规则模板当 AI 结果显示。Demo 模式不挂这些入口。
   另：设置 › 分析「导入后自动生成 AI 概览」开关（settings.auto_overview，默认关，打开前先说明并征得同意），
   以及自动概览作业完成后让概览重新读取。 */
const LVAI = { runs: {}, done: {}, fail: {} };   // key → 进行中的作业 / 模型结果 / 失败说明（本次打开 App 内有效）
const LVAI_STAGE = { pack: '整理脱敏材料', draft: '本地 Agent 撰写', check: '校验数字与引用' };
const LVAI_ERR = {
  ai_disabled: 'AI 未开启：在 设置 › 分析 选择执行者后再试',
  engine_unavailable: '本地 Agent 不可用（未安装或未登录）',
  budget_exhausted: '今日 AI 花费已达上限，明天再试或在 设置 › 分析 调整上限',
  over_budget: '上下文超出预算，暂时无法生成',
  invalid_scope: '当前范围无法生成'
};
const LVAI_MECH = { rule: '写进规则', hook: '加 Hook', skill: '封装 Skill', subagent: '交给子代理', workflow: '改做法' };
function lvaiEngine(id) { return id ? (typeof tlsEngName === 'function' ? tlsEngName(id) : id) : '本地 Agent'; }
function lvaiWhen(d) {
  const t = d.at ? new Date(d.at) : null;
  return lvaiEngine(d.engine) + ' 撰写' + (d.cached ? '（同一输入的已有结果）' : '') + (t ? ' · ' + (t.getMonth() + 1) + '/' + t.getDate() + ' ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0') : '');
}
function lvaiRedraw() { if (typeof render === 'function') render(); }
// 进行中：阶段名 + 最近一行日志，原位刷新（不整页重绘）
function lvaiProgress(run, job) {
  const st = (job.stages || []).filter((x) => x.status === 'running').pop();
  const line = (job.log || []).slice(-1)[0];
  run.msg = run.stop ? '正在停止…' : (st ? LVAI_STAGE[st.id] || st.id : job.status === 'queued' ? '排队中' : '本地 Agent 处理中') + '…';
  run.line = line ? String(line).slice(0, 120) : '';
  const box = $('[data-aikey="' + CSS.escape(run.key) + '"]');
  if (box) { const m = box.querySelector('[data-aimsg]'); if (m) m.textContent = run.msg; const l = box.querySelector('[data-ailine]'); if (l) l.textContent = run.line; }
}
function lvaiStart(key, body, what) {
  if (LVAI.runs[key]) { toast(what + '正在生成'); return; }
  const run = LVAI.runs[key] = { key, msg: '已提交给本地 Agent…', line: '', job: null, stop: false };
  delete LVAI.fail[key];
  lvaiRedraw();
  const end = (fail) => { if (fail) LVAI.fail[key] = fail; if (LVAI.runs[key] === run) delete LVAI.runs[key]; lvaiRedraw(); };
  TL.send('POST', '/v1/ai/jobs', body).then((r) => {
    const d = r.data || {}; if (!d.job_id) throw Object.assign(new Error('没有返回作业'), { code: 'no_job' });
    run.job = d.job_id;
    if (run.stop) lvaiCancel(run);
    return TL.pollJob(d.job_id, (job) => lvaiProgress(run, job));
  }).then((job) => {
    const res = job.result || {};
    if (job.status === 'ok' && res.source && res.source !== 'template' && res.source !== 'empty') {
      LVAI.done[key] = { result: res, engine: job.engine, at: job.finished_at || Date.now(), cached: res.source === 'cache' || !!job.cached };
      toast(what + '已生成'); end(null); return;
    }
    if (job.status === 'ok' || job.status === 'fallback') {
      const st = (job.stages || []).find((x) => x.status === 'failed');
      end(res.source === 'empty' ? '没有可交给模型的数据，未生成' + what : '模型这次没有写出可用的' + what + (st && st.message ? '（' + st.message + '）' : '') + '，未显示模板内容');
    } else if (job.status === 'cancelled') end('已停止，未生成' + what);
    else end(what + '生成失败：' + (job.error || job.status));
  }, (e) => {
    let msg = LVAI_ERR[e.code] || (TL.unavailable(e) ? '本地服务暂不提供 AI 生成' : what + '生成失败：' + (e.message || e.code));
    if (e.code === 'consent_required') msg = '需要先授权这些数据类：' + (((e.detail && e.detail.missing) || e.missing || []).join('、') || '—');
    if (['consent_required', 'ai_disabled', 'budget_exhausted'].indexOf(e.code) >= 0) toast(msg, { act: '去设置', onAct: () => openSettings('analysis') });
    end(msg);
  });
}
function lvaiCancel(run) { return TL.send('POST', '/v1/ai/jobs/' + encodeURIComponent(run.job) + '/cancel', {}).catch((e) => toast('停止失败：' + (e.message || e.code))); }
// 生成中 / 失败 两种状态的共用行（失败用中性色，不挂 AI 标记）
function lvaiState(key) {
  const run = LVAI.runs[key];
  if (run) return '<div class="col" style="gap:2px;margin-top:8px" role="status" aria-live="polite"><div class="row" style="gap:8px;font-size:12px"><span class="spin" style="width:10px;height:10px"></span><span data-aimsg>' + esc(run.msg) + '</span><button type="button" class="btn sm gh" data-act="aiStop" data-k="' + esc(key) + '"' + (run.stop ? ' disabled' : '') + '>停止</button></div><div class="cap mono" data-ailine style="font-size:11px;min-height:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(run.line) + '</div></div>';
  if (LVAI.fail[key]) return '<div class="row cap" style="gap:6px;margin-top:8px;font-size:12px">' + ic('info', 12) + '<span>' + esc(LVAI.fail[key]) + '</span></div>';
  return '';
}

if (LV.live) {
  ACT.aiStop = (el) => {
    const run = LVAI.runs[el.dataset.k]; if (!run || run.stop) return;
    run.stop = true; run.msg = '正在停止…'; lvaiRedraw();
    if (run.job) lvaiCancel(run);
  };

  /* ---- 人格页：lede 下的 AI 解读（narrate.persona）----
     交给模型的画像就是页面上显示的这一份（类型、四轴字母与强度、会话数、验证占比），所以解读不会说成另一个类型。 */
  const perKey = (p) => ['persona', S.persona.period, Array.from(S.agents).sort().join(','), S.project || '', p.code, p.n].join('|');
  const perProfile = (p, st) => {
    const axes = {};
    AXES.forEach((ax, i) => { const a = axisView(p, i); axes[ax.k] = { letter: p.code[i] === '?' ? '?' : a.letter, name: p.code[i] === '?' ? '未定型' : a.name, value: a.strong }; });
    const rates = { sessions: p.n };
    if (st && st.per != null) rates.messages_per_session = Math.round(st.per * 10) / 10;
    if (st && st.verKnown && st.verify != null) rates.verify_pct = Math.round(st.verify);
    return { code: p.code, type_name: p.zh, experimental: true, axes, rates };
  };
  window.perAiBlock = function (p, st) {
    if (!p || !p.ok) return '';
    CUR.perSt = st;
    const key = perKey(p); const d = LVAI.done[key]; const run = LVAI.runs[key];
    const btn = run ? '' : '<button type="button" class="btn sm gh" data-act="perAi" data-tip="把页面上的画像（类型、四轴强度、会话数）脱敏后交给所选本地 Agent 写一段解读；会调用其模型服务，计入今日 AI 花费">' + ic('spark', 12) + (d ? '重新生成' : 'AI 解读') + '</button>';
    let body = '';
    if (d && !run) {
      const r = d.result;
      body = '<div class="col" style="gap:6px;margin-top:8px;padding:10px 12px;border:1px solid var(--line);border-radius:10px;background:var(--surface)">' +
        '<div class="row" style="gap:8px;flex-wrap:wrap"><span class="aib">' + ic('spark', 11) + 'AI</span><b style="font-size:14px">' + esc(r.headline || '') + '</b></div>' +
        ((r.traits || []).length ? '<div class="row" style="gap:6px;flex-wrap:wrap">' + r.traits.map((t) => '<span class="tag">' + esc(t.text) + '</span>').join('') + '</div>' : '') +
        (r.tradeoffs || []).map((t) => '<div style="font-size:13px;color:var(--ink-2)"><b class="mono" style="color:var(--ink-1)">' + esc(t.axis) + '</b> ' + esc(t.text) + '</div>').join('') +
        (r.blind_spots || []).map((b) => '<div style="font-size:13px;color:var(--ink-2)">盲点：' + esc(b.text) + '</div>').join('') +
        '<div class="cap" style="font-size:11px">' + esc(lvaiWhen(d)) + ((r.caveats || []).length ? ' · ' + esc(r.caveats.join('；')) : '') + '</div></div>';
    }
    return '<div class="pe-ai" data-aikey="' + esc(key) + '"><div class="row" style="gap:8px">' + btn + '</div>' + lvaiState(key) + body + '</div>';
  };
  ACT.perAi = () => {
    const p = CUR.persona; if (!p || !p.ok) { toast('画像还没算出来，暂时无法解读'); return; }
    const key = perKey(p); const profile = perProfile(p, CUR.perSt || p.st || null);
    lvaiStart(key, { task_id: 'narrate.persona', fresh: !!LVAI.done[key], params: { key, profile } }, 'AI 解读');
  };

  /* ---- 会话轨迹：让 Agent 复盘（narrate.session_review）---- */
  const revKey = (s) => 'review|' + s.id;
  A3H.review = function (s) {
    if (!s) return '';
    const key = revKey(s); const d = LVAI.done[key]; const run = LVAI.runs[key];
    if (!d && !run && !LVAI.fail[key]) return '';
    let body = '';
    if (d && !run) {
      const r = d.result;
      body = '<p style="margin:6px 0 0;font-size:14px;font-weight:600">' + esc(r.summary || '') + '</p>' +
        '<div class="col" style="gap:4px;margin-top:6px">' + (r.findings || []).map((f) => '<div style="font-size:13px"><b>' + esc(f.title || '') + '</b> <span style="color:var(--ink-2)">' + esc(f.text || '') + '</span></div>').join('') + '</div>' +
        ((r.lessons || []).length ? '<div class="col" style="gap:4px;margin-top:8px"><span class="eb">下次可以这样</span>' + r.lessons.map((l) => '<div class="row" style="gap:6px;font-size:13px">' + (LVAI_MECH[l.mechanism] ? '<span class="tag">' + LVAI_MECH[l.mechanism] + '</span>' : '') + '<span>' + esc(l.text) + '</span></div>').join('') + '</div>' : '') +
        '<div class="cap" style="font-size:11px;margin-top:8px">' + esc(lvaiWhen(d)) + ((r.caveats || []).length ? ' · ' + esc(r.caveats.join('；')) : '') + '</div>';
    }
    return '<div class="card pad" data-aikey="' + esc(key) + '"><div class="row"><span class="ct">Agent 复盘</span>' + (d && !run ? '<span class="aib">' + ic('spark', 11) + 'AI</span>' : '') + '<span class="grow"></span>' + (run ? '' : '<button type="button" class="btn sm gh" data-act="sessReview">' + (d ? '重新复盘' : '再试一次') + '</button>') + '</div>' + lvaiState(key) + body + '</div>';
  };
  ACT.sessReview = () => {
    const s = BYID[S.sess.sel]; if (!s) return;
    const key = revKey(s);
    lvaiStart(key, { task_id: 'narrate.session_review', fresh: !!LVAI.done[key], params: { session_uid: s.id } }, '复盘');
  };

  /* ---- 自动概览：设置开关 + 完成后刷新 ---- */
  // 自动概览作业不发完成通知（params.auto）；ai.job 帧报告 narrate.overview 结束时让概览重新读取，卡片才换成 AI 文字
  TL.on('event', (ev) => {
    const d = ev.data || {};
    if (ev.name === 'ai.job' && d.task_id === 'narrate.overview' && d.status === 'ok' && !LV.ovRegen) {
      TL.invalidate((x) => String(x.path).indexOf('/v1/uiview/overview') === 0);
    }
  });
  const AUTO_TXT = '导入完成后，Orbit 会把概览（近 30 天、无筛选）的脱敏统计摘要交给你在上面选的本地 Agent，由它经自己的模型服务写一段 AI 解读。会计入今日 AI 花费，受每日上限约束，每天最多自动生成 3 次。';
  window.lvaiAutoRow = function (d) {
    if (!d || !d.settings) return '';
    const on = !!d.settings.auto_overview; const off = d.mode === 'stats';
    return '<div class="col" data-tl="auto-ov" style="gap:4px;margin-top:10px"><div class="row" style="gap:10px">' + swBtn(on, 'tlsAutoOv', off && !on ? ' disabled' : '', '导入后自动生成 AI 概览') + '<span style="font-size:13px">导入后自动生成 AI 概览</span></div>' +
      '<div class="cap" style="font-size:11px">' + (off ? 'AI 未开启：选择执行者后才能打开。' : '') + esc(AUTO_TXT) + '</div></div>';
  };
  const CON = '/v1/ai/consent';
  const autoSet = (to) => {
    const r = TL.resource(CON); if (!r.data) { toast('正在读取 AI 设置，请稍后再试'); return; }
    const prev = r.data;
    r.data = Object.assign({}, prev, { settings: Object.assign({}, prev.settings, { auto_overview: to }) }); renderSet();
    TL.send('PUT', CON, { settings: { auto_overview: to } }).then(() => { toast(to ? '已开启：下次导入完成后自动生成 AI 概览' : '已关闭自动生成 AI 概览'); TL.invalidate((q) => q.path === CON); },
      (e) => { r.data = prev; renderSet(); toast(TL.unavailable(e) ? '未保存：本地服务暂不可用' : '未保存：' + (e.message || e.code)); });
  };
  ACT.tlsAutoOv = () => {
    const d = TL.resource(CON).data; if (!d || !d.settings) return;
    if (d.settings.auto_overview) { autoSet(false); return; }
    if (d.mode === 'stats') { toast('AI 未开启：先选择执行者'); return; }
    openModal(modalHead('导入后自动生成 AI 概览', '默认关闭 · 需要你的同意') + '<div class="mb col"><p style="margin:0;font-size:13px;line-height:1.6">' + esc(AUTO_TXT) + '</p><p class="cap" style="margin:0">发送的只有脱敏后的统计与片段摘要，不含原始会话；Orbit 不自带云端模型、不经过 Orbit 服务器。随时可以在这里关闭。</p></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="tlsAutoOvGo">同意并开启</button></div>');
  };
  ACT.tlsAutoOvGo = () => { closeModal(); autoSet(true); };
}
