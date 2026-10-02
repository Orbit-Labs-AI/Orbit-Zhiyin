/* ============ live binding: 菜单栏 · 面板 · HUD · 桌面小组件 · A3 会话操作 · A4 调用明细 · 导出（TandemLive ops section） ============
   Loaded after the 97-live-* bindings; only active in live mode. Nothing gets a new layout:
   - realtime (/v1/analytics/realtime + its SSE stream) drives the demo's own state — S.simBase / S.attn / S.waitOpen → simSettle,
     S.live.{t0, ctx, tools} (getters), HUD_TOOLS, liveBuckets() — and the panel / HUD / widget cards that name a session are
     rebuilt with the same markup from the snapshot (failing command, approval command, context %, the other sessions).
   - A3 (live sessions page): 不计入分析 / 恢复, 复制继续命令, 定位原始日志, the excluded list; A4 (live tools page): click a tool
     row for its calls (/v1/analytics/tool_calls, keyset 加载更多, 全部 / 成功 / 失败).
   - export: report markdown, tool-call CSV and the share card come from /v1/export/*.
   A route the gateway does not serve (404 / 501), a 503 or an offline gateway keeps the demo values with the 示例数据 badge.
   Endpoints: routes_realtime / routes_sessionops (wip/yhyfhgs-backend), routes_export (wip/be-gap-export). */
const TLO = { demo: false, started: false, d: null, doneUid: null, tc: null, repSeq: 0, share: null };
const TLO_AG = (s) => {
  const id = Object.keys(TandemLive.AGENT_KEYS).find((k) => TandemLive.AGENT_KEYS[k].indexOf(String((s && s.agent) || '').toLowerCase()) >= 0);
  return id ? agent(id) : { name: (s && s.agent) || '—', short: (s && s.agent) || '—', c: 'var(--ink-3)' };
};
const TLO_EXCL = '/v1/sessions/excluded';
const TLO_REASON = { test: '测试会话', private: '隐私', duplicate: '重复', other: '其他' };
const tloCmd = (s) => (s.approval && s.approval.command) || s.current_tool || '—';
const tloWait = (s) => Math.max(1, Math.round(((s.approval && s.approval.wait_s) || s.running_s || 0) / 60));
function tloToday() { const d = new Date(); return (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日 周' + '日一二三四五六'[d.getDay()]; }
function tloRes(path, query) { const r = TL.resource(path, { query }); if (r.dirty && !r.loading) TL.load(r); return r; }
function tloOpen(uid) { if (!uid) return; S.pop = false; S.hud.open = false; S.lvSess = uid; go('sessions'); }
function tloSample(sel) { const h = $(sel); if (h && !h.querySelector('[data-tl="sample"]')) h.insertAdjacentHTML('beforeend', ' ' + TLU.sample()); }

if (TL.mode === 'live') {
  const H = TandemLive.ops;
  TLS_KIND.done.push('just_finished');   // realtime's notify type for a finished session → the 完成 channel of the matrix

  /* ---------- realtime → the demo's ambient state ---------- */
  function tloStart() {
    if (TLO.started) return; TLO.started = true;
    TL.ops.realtime().then(() => TL.ops.startStream(), (e) => {
      if (TL.unavailable(e)) { TLO.demo = true; render(); return; }
      setTimeout(() => { TLO.started = false; tloStart(); }, 15000);
    });
  }
  function tloApply() {
    if (TLO.demo || !TL.ops.rt) { TLO.d = null; return; }
    const d = TLO.d = TL.ops.derive();
    S.simBase = d.active.length ? 'running' : 'idle';
    if (d.failing.length) S.attn.add('stuck'); else S.attn.delete('stuck');
    if (d.ctx.length) S.attn.add('ctx'); else S.attn.delete('ctx');
    S.waitOpen = d.waiting.length > 0;
    if (d.finished.length) TLO.doneUid = d.finished[0].session_uid;
    simSettle();
    HUD_TOOLS.length = 0; HUD_TOOLS.push(d.primary ? (d.primary.current_tool || '—') : '—');
  }
  // the running session's numbers follow the snapshot; without one the demo values stay
  ['t0', 'ctx', 'tools'].forEach((k) => {
    let v = S.live[k];
    Object.defineProperty(S.live, k, {
      configurable: true, enumerable: true, set: (x) => { v = x; },
      get: () => {
        const p = TLO.d && TLO.d.primary; if (!p) return v;
        if (k === 't0') return p.since || v;
        if (k === 'ctx') { const c = H.rtCtxPct(p); return c == null ? 0 : c; }
        return ((p.lanes && p.lanes.tool) || []).length;
      }
    });
  });
  const tloLiveSession = liveSession;
  liveSession = function () { const d = TLO.d; if (!d) return tloLiveSession(); return d.primary && !S.paused ? BYID[LIVE_ID] : null; };
  const tloBucketsBase = liveBuckets;
  liveBuckets = function (minutes, bucketSec) {
    const p = TLO.d && TLO.d.primary; if (!p) return tloBucketsBase(minutes, bucketSec);
    const b = H.rtBuckets(p, Date.now(), minutes, bucketSec); return { b, n: b.length, from: 0, now: minutes };
  };
  const tloCtxBar = ctxBar;
  ctxBar = function (pct, opt) { const p = TLO.d && TLO.d.primary; if (p && (!opt || opt.th == null)) opt = Object.assign({}, opt, { th: H.rtCtxTh(p) }); return tloCtxBar(pct, opt); };

  /* ---------- menu-bar panel ---------- */
  const tloPopLive = popLiveCard;
  popLiveCard = function () {
    const d = TLO.d; if (!d) return tloPopLive();
    const s = d.primary; if (!s || S.paused) return '';
    const ag = TLO_AG(s);
    return '<div class="sec col" style="gap:6px" data-tl="rt-live"><div class="row"><span class="dot live" style="background:' + ag.c + '"></span><b style="font-size:13px">' + esc(ag.name) + '</b><span class="cap">· ' + esc(s.project || '—') + '</span><span style="flex:1"></span><span class="mono" style="font-size:12px" data-live>' + liveElapsed() + '</span></div><div style="font-size:13px;font-weight:600">' + esc(s.title || s.session_uid) + '</div><div class="row cap" style="font-size:12px;min-width:0"><span class="aib">进行中</span><span class="mono" data-hudtool style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(HUD_TOOLS[0]) + '</span><span style="flex:1"></span><span class="mono" style="font-size:11px">工具 <b data-livetools>' + S.live.tools + '</b></span></div>' +
      ctxBar(S.live.ctx) +
      '<div class="row" style="margin-top:4px"><button type="button" class="btn sm" data-act="popTraj">查看轨迹</button><button type="button" class="btn sm gh" data-act="hudMute">' + (S.hud.mute ? '恢复提醒' : '暂停提醒') + '</button></div></div>';
  };
  const secOf = (sel) => { const b = $('#pop ' + sel); return b ? b.closest('.sec') : null; };
  const otherRow = (s) => { const ag = TLO_AG(s); const st = s.state === 'just_finished' ? '刚刚完成 ✓' : s.state === 'failing' ? '连续失败' : s.state === 'awaiting_approval' ? '等你确认' : '运行中 ' + Math.round((s.running_s || 0) / 60) + 'm';
    return '<button type="button" class="sec row" data-act="tloSess" data-id="' + esc(s.session_uid) + '" data-tl="rt-other" style="width:100%;border:0;border-top:1px solid var(--hair);background:none;text-align:left;font-size:12px"><span class="dot" style="background:' + ag.c + '"></span><span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(ag.short + ' · ' + (s.project || '—') + ' · ' + (s.title || s.session_uid)) + '</span><span class="mono cap" style="font-size:11px">' + st + '</span></button>'; };
  const tloPopBase = renderPop;
  renderPop = function () {
    tloPopBase();
    if (TLO.demo) { tloSample('#pop b'); return; }
    const d = TLO.d; if (!d) return;
    const meta = $('#pop .mono.cap');
    if (meta) meta.textContent = meta.textContent.replace(/^\d+ 月 \d+ 日 周./, tloToday()).replace(/· \d+ 会话 · .+$/, '· ' + TLU.num(d.today.sessions_started) + ' 会话').replace('还没有会话', d.today.sessions_started ? TLU.num(d.today.sessions_started) + ' 会话 · 没有运行中的' : '还没有会话');
    const f = d.failing[0]; const stuck = secOf('[data-act="popStuckSess"]');
    if (stuck && f) {
      const fx = f.failure || {}; const ag = TLO_AG(f);
      stuck.setAttribute('data-tl', 'rt-failing');
      stuck.innerHTML = '<div class="row">' + ic('alert', 15, 'color:var(--crit)') + '<b style="font-size:13px">同一命令连续失败 ' + TLU.num(fx.n) + ' 次</b></div><div class="cap" style="font-size:12px">' + esc(ag.short + ' · ' + (f.project || '—')) + ' · ' + TLU.hm(f.since) + ' 开始</div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--sunken)">' + esc(fx.command_head || f.current_tool || '—') + '</div>' + (fx.cause_hint ? '<div style="font-size:12px;color:var(--ink-2)">可能原因：' + esc(fx.cause_hint) + '</div>' : '') + '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="popTerm">在终端中处理</button><button type="button" class="btn sm" data-act="tloSess" data-id="' + esc(f.session_uid) + '">打开会话</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="stuck">忽略 1 小时</button></div>';
    }
    const c = d.ctx[0]; const cs = secOf('[data-act="popIgnore"][data-k="ctx"]');
    if (cs && c) {
      const pct = H.rtCtxPct(c) || 0;
      cs.setAttribute('data-tl', 'rt-ctx');
      cs.innerHTML = '<div class="row">' + ic('gauge', 15, 'color:var(--warn)') + '<b style="font-size:13px">上下文即将压缩</b><span style="flex:1"></span><b class="mono" style="color:var(--warn)">' + pct + '%</b></div><div class="cap" style="font-size:12px">' + esc(TLO_AG(c).name + ' · ' + (c.project || '—') + ' · ' + (c.title || '')) + '</div>' + tloCtxBar(pct, { th: H.rtCtxTh(c) }) + '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudTip">复制「先总结进度」提示语</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="ctx">忽略</button></div>';
    }
    const w = d.waiting[0]; const ws = secOf('[data-act="hudGo"][data-v="waiting"]');
    if (ws && w) {
      ws.setAttribute('data-tl', 'rt-waiting');
      ws.innerHTML = '<div class="row"><span style="width:9px;height:9px;border-radius:2px;background:var(--warn-m)"></span><b style="font-size:13px">' + esc(TLO_AG(w).name + ' · ' + (w.project || '—')) + '</b><span style="flex:1"></span><span class="cap" style="font-size:11px">等你确认 · ' + tloWait(w) + ' 分钟</span></div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--surface)">' + esc(tloCmd(w)) + '</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudGo" data-v="waiting">在终端中处理</button><span class="cap" style="font-size:11px">Tandem 不会代你批准</span></div>';
    }
    // the demo's fixed「另一个会话」row → the next live session (or the one that just finished)
    const other = $('#pop [data-act="popSess"][data-id="sess-1001-0903"]');
    if (other) { const s = d.others.find((x) => x.state === 'running') || d.finished[0]; if (s) other.outerHTML = otherRow(s); else other.remove(); }
    const done = $('#pop [data-act="popSess"][data-id="' + DONE_ID + '"]');
    if (done && TLO.doneUid) { const s = d.finished[0]; done.dataset.act = 'tloSess'; done.dataset.id = TLO.doneUid; if (s) done.dataset.tip = s.title || s.session_uid; }
  };

  /* ---------- HUD ---------- */
  const tloPill = hudPill;
  hudPill = function () {
    const d = TLO.d; if (!d) return tloPill();
    const st = S.hudSim;
    if (st === 'stuck' && d.failing[0]) { const s = d.failing[0]; return ic('alert', 16, 'color:#ff7d74') + '<b>同一命令失败 ' + TLU.num((s.failure || {}).n) + ' 次</b><span style="color:var(--hud-ink-3);font-size:12px">' + esc(TLO_AG(s).short + ' · ' + (s.project || '—')) + '</span><button type="button" class="hb" data-act="hudGo" data-v="stuck">查看原因</button>'; }
    if (st === 'waiting' && d.waiting[0]) { const s = d.waiting[0]; return '<span style="width:10px;height:10px;border-radius:2px;background:#f3b843;flex:none"></span><b>' + esc(TLO_AG(s).short) + '</b><span style="color:var(--hud-ink-2)">请求执行 ' + esc(tloCmd(s)) + '</span><button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>'; }
    if (st === 'done' && d.finished[0]) { const s = d.finished[0]; return ic('okc', 16, 'color:#5dd08a') + '<b>完成</b><span style="color:var(--hud-ink-2)">' + esc(s.project || s.title || '') + '</span><button type="button" class="hb" data-act="hudTraj">查看</button>'; }
    if (st === 'ctx' && d.ctx[0]) { const s = d.ctx[0]; return ic('gauge', 16, 'color:#f3b843') + '<b>上下文 ' + (H.rtCtxPct(s) || 0) + '%</b><span style="color:var(--hud-ink-2)">' + esc(s.project || '—') + ' 即将压缩</span><button type="button" class="hb" data-act="hudTip">复制提示语</button>'; }
    const p = d.primary; if (!p) return tloPill();
    // running: the demo pill (density from liveBuckets, elapsed from S.live.t0) with the live project and the other sessions
    const n = d.others.length;
    return tloPill().replace(/^(<span class="dot live"[^>]*?background:)[^;"]+/, '$1' + TLO_AG(p).c).replace(/<b>[^<]*<\/b>/, '<b>' + esc(p.project || '—') + '</b>')
      .replace(/<span class="mono" style="font-size:11px;color:var\(--hud-ink-3\)" data-tip="[^"]*">\+1<\/span>$/, n ? '<span class="mono" style="font-size:11px;color:var(--hud-ink-3)" data-tip="另有 ' + n + ' 个会话在进行">+' + n + '</span>' : '');
  };
  const tloHud = renderHud;
  renderHud = function () {
    tloHud();
    const d = TLO.d; const p = d && d.primary; const c = p && $('#hud .hcard'); if (!c) return;
    const ag = TLO_AG(p); const head = c.firstElementChild;
    c.setAttribute('data-tl', 'rt-hud');
    if (head) { const dot = head.querySelector('.dot'); const b = head.querySelector('b'); const sp = b && b.nextElementSibling; if (dot) dot.style.background = ag.c; if (b) b.textContent = ag.name; if (sp) sp.textContent = '· ' + (p.project || '—'); }
    const t = c.querySelector('.serif'); if (t) t.textContent = p.title || p.session_uid;
    const lbl = Array.from(c.querySelectorAll('span')).find((x) => /^另外 \d+ 个会话$/.test(x.textContent));
    if (lbl) {
      const box = lbl.parentElement; const xs = d.others.concat(d.finished).slice(0, 3);
      if (!xs.length) box.remove();
      else box.innerHTML = '<span style="font-size:11px;color:var(--hud-ink-3)">另外 ' + xs.length + ' 个会话</span>' + xs.map((s) => {
        const a = TLO_AG(s); const act = s.state === 'awaiting_approval' ? '<button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>' : s.state === 'failing' ? '<button type="button" class="hb" data-act="hudGo" data-v="stuck">查看原因</button>' : '<button type="button" class="hg" data-act="tloSess" data-id="' + esc(s.session_uid) + '">打开轨迹</button>';
        const st = s.state === 'awaiting_approval' ? ' · <span style="color:#f3b843">等你确认 ' + tloWait(s) + ' 分钟</span>' : s.state === 'failing' ? ' · <span style="color:#ff7d74">连续失败</span>' : s.state === 'just_finished' ? ' · 刚刚完成' : ' · 进行中';
        return '<div class="row" style="font-size:12px"><span class="dot" style="background:' + a.c + '"></span><span style="flex:1;min-width:0">' + esc(a.short + ' · ' + (s.project || '—')) + st + '</span>' + act + '</div>';
      }).join('');
    }
  };

  /* ---------- desktop widgets ---------- */
  const tloWg = renderWidgets;
  renderWidgets = function () {
    tloWg();
    const d = TLO.d; if (!d) return;
    const sq = $('#widgets [data-act="wgGo"][data-r="sessions"]');
    if (sq) {
      const big = sq.querySelector('.mono'); if (big) big.textContent = TLU.num(d.today.sessions_started);
      const sub = big && big.nextElementSibling; if (sub) sub.textContent = '会话 · 今天已结束 ' + TLU.num(d.today.sessions_finished);
      const row = sq.querySelector(':scope > .row'); const p = d.primary;
      if (row && p) row.innerHTML = '<span class="dot live" style="background:' + TLO_AG(p).c + '"></span>' + (S.numOnly ? d.active.length + ' 个运行中' : esc(p.project || '—') + ' · <span class="mono" data-live>' + liveElapsed() + '</span>');
    }
    const lv = $('#widgets [data-act="wgLive"]'); const p = d.primary;
    if (lv && p) {
      const ag = TLO_AG(p); const l = lv.querySelector('.lbl'); const dot = lv.querySelector('.dot'); const t = l && l.parentElement.nextElementSibling;
      if (l) l.textContent = '运行中 · ' + ag.name; if (dot) dot.style.background = ag.c; if (t && !S.numOnly) t.textContent = p.title || p.session_uid;
    }
  };

  /* ---------- actions on live sessions ---------- */
  const wrap = (name, fn) => { const base = ACT[name]; ACT[name] = (el, ev) => fn(base, el, ev); };
  const sessOf = (k) => { const d = TLO.d; return d ? (k === 'stuck' ? d.failing[0] : k === 'ctx' ? d.ctx[0] : k === 'waiting' ? d.waiting[0] : null) : null; };
  wrap('popTraj', (base, el, ev) => { const p = TLO.d && TLO.d.primary; if (!p) return base(el, ev); tloOpen(p.session_uid); });
  wrap('wgLive', (base, el, ev) => { const p = TLO.d && TLO.d.primary; if (!p) return base(el, ev); tloOpen(p.session_uid); });
  wrap('popStuckSess', (base, el, ev) => { const s = sessOf('stuck'); if (!s) return base(el, ev); tloOpen(s.session_uid); });
  wrap('hudTraj', (base, el, ev) => {
    const d = TLO.d; if (!d) return base(el, ev);
    const done = (S.hudSim === 'done' || S.sim === 'done') && TLO.doneUid; if (done) simClear('done');
    tloOpen(done ? TLO.doneUid : d.primary && d.primary.session_uid);
  });
  wrap('popTerm', (base, el, ev) => { const s = sessOf('stuck'); if (!s) return base(el, ev); toast('到 ' + TLO_AG(s).name + ' 所在的终端里处理；Tandem 不会代你执行命令'); });
  wrap('hudGo', (base, el, ev) => {
    const s = sessOf(el.dataset.v); if (!s || el.dataset.v !== 'waiting') return base(el, ev);
    simClear('waiting'); render(); toast('到 ' + TLO_AG(s).name + ' 所在的终端里确认「' + tloCmd(s) + '」；批准仍由你完成');
  });
  // 忽略: dismiss on the gateway (1 hour), then clear locally as the demo does; the next snapshot keeps it hidden
  wrap('popIgnore', (base, el, ev) => {
    const s = sessOf(el.dataset.k); if (!s) return base(el, ev);
    TL.ops.dismiss(s.session_uid, 3600).catch((e) => { if (!TL.unavailable(e)) toast('忽略失败：' + (e.message || e.code)); });
    base(el, ev);
  });
  ACT.tloSess = (el) => tloOpen(el.dataset.id);

  /* ---------- A3 会话：不计入分析 · 继续命令 · 原始日志 ---------- */
  const excludedSet = () => { const r = TL.resource(TLO_EXCL); return new Set(((r.data && r.data.items) || []).map((i) => i.session_uid)); };
  function tloSessPatch(m) {
    const box = m.querySelector('[data-tl="sessions"]'); if (!box) return;
    const r = tloRes(TLO_EXCL); const ex = excludedSet();
    box.querySelectorAll('tr[data-act="lvSess"]').forEach((tr) => { if (ex.has(tr.dataset.id) && tr.cells[0]) tr.cells[0].insertAdjacentHTML('beforeend', ' <span class="tl-badge" data-tl="excluded">不计入分析</span>'); });
    const evc = box.querySelector('[data-tl="events"]');
    if (evc && S.lvSess) evc.insertAdjacentHTML('afterbegin', '<div class="row" data-tl="sess-ops" style="gap:8px;flex-wrap:wrap;margin-bottom:8px"><button type="button" class="btn sm" data-act="tloExclude">' + (ex.has(S.lvSess) ? '恢复计入分析' : '不计入分析') + '</button><button type="button" class="btn sm" data-act="tloResume">' + ic('term', 13) + '复制继续命令</button><button type="button" class="btn sm" data-act="tloLocate">定位原始日志</button></div>');
    const items = (r.data && r.data.items) || [];
    if (items.length) box.insertAdjacentHTML('afterend', '<div class="tl-card" data-tl="excluded-list" style="margin-top:12px"><div class="cap" style="margin-bottom:6px">不计入分析的会话 · ' + TLU.num(r.data.count) + '</div>' + lvTable([
      { t: '会话', v: (s) => esc(s.title || s.session_uid) }, { t: '原因', v: (s) => esc(TLO_REASON[s.reason] || s.reason || TLU.DASH) },
      { t: '排除于', n: 1, v: (s) => TLU.hm(s.excluded_at) }, { t: '', n: 1, v: (s) => '<button type="button" class="btn sm" data-act="tloInclude" data-id="' + esc(s.session_uid) + '">恢复</button>' }
    ], items) + '</div>');
  }
  const opErr = (what) => (e) => toast(TL.unavailable(e) ? '本地服务暂不支持' + what : what + '失败：' + (e.message || e.code));
  const exclChanged = () => TL.invalidate((r) => r.path === TLO_EXCL || r.section != null);
  function tloInclude(uid) { TL.ops.include(uid).then(() => { toast('已恢复计入分析'); exclChanged(); }, opErr('恢复计入分析')); }
  Object.assign(ACT, {
    tloExclude: (el) => {
      const uid = S.lvSess; if (!uid) return;
      if (excludedSet().has(uid)) return tloInclude(uid);
      openDD(el, [{ h: '不计入分析的原因' }].concat(Object.keys(TLO_REASON).map((k) => ({ t: TLO_REASON[k], v: k }))), (reason) => {
        TL.ops.exclude(uid, reason).then(() => { toast('已排除：这个会话不再计入分析'); exclChanged(); }, opErr('排除会话'));
      });
    },
    tloInclude: (el) => tloInclude(el.dataset.id),
    tloResume: () => {
      const uid = S.lvSess; if (!uid) return;
      TL.ops.resume(uid).then((d) => {
        const c = (d.commands || [])[0];
        if (!d.available || !c) { toast(H.RESUME_OFF[d.disabled_reason] || '暂时不能继续这个会话'); return; }
        copyText(c.shell, '继续命令' + (c.verified === false ? '（' + (c.note || '参数待验证') + '）' : ''));
      }, opErr('生成继续命令'));
    },
    tloLocate: () => {
      const uid = S.lvSess; if (!uid) return;
      TL.ops.locate(uid).then((d) => {
        const files = d.files || [];
        openModal(modalHead('原始日志位置', '只读：Tandem 不会改动这些文件') + '<div class="mb col" style="gap:6px" data-tl="locate">' + (files.length ? files.map((f) => '<div class="row" style="padding:7px 0;border-bottom:1px solid var(--hair);gap:10px"><div style="flex:1;min-width:0"><div class="mono" style="font-size:12px;word-break:break-all">' + esc(f.path) + '</div><div class="cap" style="font-size:11px">' + esc(f.agent || '') + ' · ' + (f.exists ? tlsBytes(f.size) : '文件已不存在') + (f.revealable ? '' : ' · 不在数据源目录内') + '</div></div>' + (f.exists ? '<button type="button" class="btn sm" data-act="tloCopyPath" data-p="' + esc(f.path) + '">复制路径</button>' : '') + '</div>').join('') : '<div class="cap" style="padding:12px 0">没有找到原始记录</div>') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
      }, opErr('定位原始日志'));
    },
    tloCopyPath: (el) => copyText(el.dataset.p, '路径')
  });
  TL.on('event', (ev) => { if (ev.name === 'exclusions.changed') { exclChanged(); if (TLO.tc) tloCalls(true); } });

  /* ---------- A4 工具：调用明细 ---------- */
  function tloCalls(reset) {
    const t = TLO.tc; if (!t) return;
    if (t.ctl) t.ctl.abort();
    if (reset) { t.items = []; t.cursor = null; t.more = false; }
    t.busy = true; t.err = null; const ctl = t.ctl = new AbortController();
    TL.ops.toolCalls({ name: t.name, status: t.status, cursor: t.cursor, limit: 50 }, { signal: ctl.signal }).then((d) => {
      if (TLO.tc !== t || t.ctl !== ctl) return;
      t.items = t.items.concat(d.items || []); t.cursor = d.next_cursor || null; t.more = !!d.has_more;
    }, (e) => { if (e.name === 'AbortError' || TLO.tc !== t) return; t.err = e; }).then(() => { if (t.ctl === ctl) { t.busy = false; t.ctl = null; render(); } });
    render();
  }
  const ST = { success: '成功', completed: '成功', failed: '失败', error: '失败' };
  function tloCallsCard() {
    const t = TLO.tc;
    const seg = [['all', '全部'], ['ok', '成功'], ['failed', '失败']].map((x) => '<button type="button" class="btn sm' + (t.status === x[0] ? ' p' : '') + '" data-act="tloToolSt" data-v="' + x[0] + '" aria-pressed="' + (t.status === x[0]) + '">' + x[1] + '</button>').join('');
    let body;
    if (t.err && !t.items.length) body = TL.unavailable(t.err) ? '<div class="cap" style="padding:12px 0">本地服务暂不提供调用明细</div>' : TLU.errorCard(t.err);
    else if (!t.items.length) body = t.busy ? TLU.skeleton() : TLU.empty('没有符合条件的调用');
    else body = lvTable([
      { t: '时间', v: (c) => TLU.hm(c.started_at) }, { t: '会话', v: (c) => esc(c.title || c.session_uid) },
      { t: '状态', v: (c) => '<span style="color:var(' + (ST[c.status] === '失败' ? '--crit' : ST[c.status] ? '--good' : '--ink-3') + ')">' + esc(ST[c.status] || c.status || '未知') + '</span>' },
      { t: '时长 ms', n: 1, v: (c) => TLU.num(c.duration_ms) }, { t: '参数', v: (c) => '<span class="mono" style="font-size:11.5px">' + esc(c.args_summary || (c.files || []).join(' ') || TLU.DASH) + '</span>' }
    ], t.items, (c) => ' data-tl-sel data-act="tloSess" data-id="' + esc(c.session_uid) + '"') +
      (t.more ? '<div class="row" style="justify-content:center;margin-top:8px"><button type="button" class="btn sm" data-act="tloToolMore"' + (t.busy ? ' disabled' : '') + '>' + (t.busy ? '加载中…' : '加载更多') + '</button></div>' : '');
    return '<div class="tl-card" data-tl="tool-calls"><div class="row" style="gap:8px;flex-wrap:wrap;margin-bottom:8px"><b style="font-size:13px">' + esc(t.name) + '</b><span class="cap">调用明细 · 参数已脱敏</span><span style="flex:1"></span>' + seg + '</div>' + body + '</div>';
  }
  function tloToolsPatch(m) {
    const box = m.querySelector('[data-tl="tools"]'); if (!box) return;
    box.querySelectorAll('.tl-card table tbody tr').forEach((tr) => {
      const name = tr.cells[0] ? tr.cells[0].textContent : ''; if (!name) return;
      tr.setAttribute('data-tl-sel', ''); tr.dataset.act = 'tloTool'; tr.dataset.name = name;
      if (TLO.tc && TLO.tc.name === name) tr.classList.add('on');
    });
    if (TLO.tc) box.insertAdjacentHTML('beforeend', tloCallsCard());
  }
  Object.assign(ACT, {
    tloTool: (el) => { const name = el.dataset.name; if (TLO.tc && TLO.tc.name === name) { if (TLO.tc.ctl) TLO.tc.ctl.abort(); TLO.tc = null; render(); return; } TLO.tc = { name, status: 'all', items: [], cursor: null, more: false, busy: false, err: null, ctl: null }; tloCalls(true); },
    tloToolSt: (el) => { if (!TLO.tc || TLO.tc.status === el.dataset.v) return; TLO.tc.status = el.dataset.v; tloCalls(true); },
    tloToolMore: () => { if (TLO.tc && TLO.tc.more && !TLO.tc.busy) tloCalls(false); }
  });
  RENDER_HOOKS.push((m) => {
    const k = lvKey(S.route);
    if (k === 'sessions') tloSessPatch(m);
    else if (k === 'tools') tloToolsPatch(m);
  });

  /* ---------- 导出：报告 · CSV · 分享卡 ---------- */
  const fromTs = () => TandemLive.recs.scopeBody(lvScope(), TL.status).from_ts;
  function tloReport() {
    const ta = $('#repText'); if (!ta) return;
    const seq = ++TLO.repSeq; CUR.report = ''; ta.value = '正在由本地服务生成报告…';
    TL.ops.report(S.rep, lvScope()).then((d) => {
      const t = $('#repText'); if (seq !== TLO.repSeq || !t) return;
      CUR.report = d.markdown || ''; t.value = CUR.report; t.setAttribute('data-tl', 'report');
    }, (e) => {
      const t = $('#repText'); if (seq !== TLO.repSeq || !t) return;
      CUR.report = reportMD(); t.value = CUR.report;
      if (TL.unavailable(e)) tloSample('#modal .mh h2'); else toast('生成报告失败：' + (e.message || e.code));
    });
  }
  const tloRepOpen = openReport;
  openReport = function () { tloRepOpen(); tloReport(); };
  wrap('repSec', (base, el, ev) => { base(el, ev); tloReport(); });
  const tloCsvOpen = openCSV;
  openCSV = function () {
    tloCsvOpen();
    const ta = $('#modal textarea'); if (!ta) return;
    CUR.csv = ''; ta.value = '正在读取工具调用明细…';
    TL.ops.csv('tool_calls', { from_ts: fromTs(), limit: 500 }).then((text) => {
      const t = $('#modal textarea'); if (!t) return;
      CUR.csv = text; t.value = text; t.setAttribute('data-tl', 'csv');
      const cap = $('#modal .mh .cap'); if (cap) cap.textContent = rangeLabel() + ' · tool_calls · ' + Math.max(0, text.split('\n').filter(Boolean).length - 1) + ' 行（最多 500 行）· 复制后可以粘贴到表格软件';
    }, (e) => {
      const t = $('#modal textarea'); if (!t) return;
      const rows = toolRows(sel()); CUR.csv = ['tool,calls,error_rate,failures,avg_duration,approval_rate'].concat(rows.map((r) => [r.name, r.n, (r.err * 100).toFixed(1) + '%', r.fails, r.avg, Math.round(r.ap * 100) + '%'].join(','))).join('\n'); t.value = CUR.csv;
      if (TL.unavailable(e)) tloSample('#modal .mh h2'); else toast('读取 CSV 失败：' + (e.message || e.code));
    });
  };
  // share card: the same card markup, filled from the gateway's payload (code, type, copy, stats); per-axis strengths are not
  // in the payload, so the card always uses the「隐藏具体数字」axis row
  function tloPersona(code) { const v = {}; ['D', 'I', 'M', 'V'].forEach((k, i) => { v[k] = code[i] === k ? 70 : 30; }); return { v, code }; }
  function tloShareCard(d) {
    const dk = S.shareDark, nn = S.shareNoNum; const p = tloPersona(d.code);
    const C = dk ? { bg: '#131417', ink: '#f1f1f3', ink2: '#c3c6cc', ink3: '#8f949c', line: 'rgba(255,255,255,.14)', mj: '#f1f1f3', mn: '#4a4d54' } : { bg: '#f5f4f0', ink: '#17181b', ink2: '#45484f', ink3: '#62666f', line: '#dcd9d2', mj: '#17181b', mn: '#c0bdb5' };
    const g = petals(p, 40, 0.68); const hl = (d.copy && d.copy.headline) || ''; const cut = hl.indexOf('，') + 1;
    const q = cut > 0 ? [hl.slice(0, cut), hl.slice(cut)] : [hl, ''];
    const en = ((d.copy && d.copy.lines && d.copy.lines[0]) || '').split(' · ')[1] || '';
    const stats = (d.stats || []).filter((s) => !s.hidden && s.value != null);
    return '<div class="sharecard" data-tl="share-card" style="background:' + C.bg + ';color:' + C.ink + '"><div style="position:relative;height:100%;padding:7cqw 7.5cqw 6.5cqw;display:flex;flex-direction:column">' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:2cqw"><span style="font:700 2.6cqw/1 var(--mono);letter-spacing:.32em">TANDEM</span><span style="font-size:2.5cqw;color:' + C.ink3 + '">我的 AI 协作人格 · 近 30 天</span></div>' +
      '<svg viewBox="0 0 80 80" style="position:absolute;right:5cqw;top:12cqw;width:32cqw;height:32cqw" aria-hidden="true"><path d="' + g.minor + '" fill="' + C.mn + '"/><path d="' + g.major + '" fill="' + C.mj + '"/></svg>' +
      '<div style="display:flex;gap:3.4cqw;margin-top:9cqw;align-items:flex-end;position:relative">' + AXES.map((ax, i) => { const L = d.code[i]; return '<div style="display:flex;flex-direction:column;gap:.8cqw"><span style="font:600 14cqw/.9 var(--serif)">' + esc(L) + '</span><span style="font-size:2.6cqw;color:' + C.ink2 + '">' + (L === ax.L ? ax.Ln : ax.Rn) + '</span></div>'; }).join('') + '</div>' +
      '<div style="margin-top:7cqw;font:600 8.4cqw/1.05 var(--serif)">' + esc(d.type_name || '') + '</div><div style="font:italic 400 3.6cqw/1.3 var(--serif);color:' + C.ink3 + ';margin-top:1cqw">' + esc(en) + '</div>' +
      '<div style="margin-top:5cqw;font:500 4.6cqw/1.5 var(--serif)">「' + esc(q[0]) + '<br>' + esc(q[1]) + '」</div>' +
      (nn || !stats.length ? '' : '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2cqw;margin-top:6cqw;padding-top:4cqw;border-top:1px solid ' + C.line + '">' + stats.map((x) => '<div><div style="font:600 5.4cqw/1.1 var(--mono)">' + TLU.num(x.value) + '</div><div style="font-size:2.4cqw;color:' + C.ink3 + ';margin-top:.6cqw">' + esc(x.label) + '</div></div>').join('') + '</div>') +
      '<div style="margin-top:auto;display:flex;align-items:flex-end;gap:3cqw"><div style="flex:1;min-width:0"><div style="font-size:3.4cqw;font-weight:600">测测你和 AI 是哪种搭档</div><div style="font-size:2.3cqw;color:' + C.ink3 + ';margin-top:1cqw">' + esc(d.disclaimer || '') + ' · 全部分析在本机完成</div></div>' + qrSVG(d.code, C) + '</div></div></div>';
  }
  function tloShareBody() {
    const d = TLO.share; const n = (d.stats || []).find((s) => s.label === '会话');
    return '<div style="flex:1 1 300px;max-width:360px;min-width:0">' + tloShareCard(d) + '</div><div class="col" style="flex:1 1 220px;gap:14px;min-width:0"><div class="col" style="gap:6px"><span class="eb">外观</span><div class="seg" role="radiogroup" aria-label="外观"><button type="button" role="radio" aria-checked="' + S.shareDark + '" data-act="shareTheme" data-v="dark" class="' + (S.shareDark ? 'on' : '') + '">深色</button><button type="button" role="radio" aria-checked="' + !S.shareDark + '" data-act="shareTheme" data-v="light" class="' + (!S.shareDark ? 'on' : '') + '">浅色</button></div></div><div class="row" style="gap:10px">' + swBtn(S.shareNoNum, 'shareNum', '', '隐藏具体数字') + '<span style="font-size:12.5px">隐藏具体数字</span></div><div class="col" style="gap:4px"><span class="eb">周期</span><span style="font-size:12.5px">近 30 天' + (n && n.value != null ? ' · ' + TLU.num(n.value) + ' 个会话' : '') + '</span><span class="cap" style="font-size:11.5px">' + esc(d.disclaimer || '') + '</span></div><div class="col" style="gap:4px;padding:10px 12px;border-radius:9px;background:var(--sunken);font-size:12px;line-height:1.55;color:var(--ink-2)"><b style="color:var(--ink-1)">包含</b>类型代号、四个维度' + (S.shareNoNum ? '' : '、会话数与活跃天数') + '<b style="color:var(--ink-1);margin-top:4px">不包含</b>项目名、会话标题与任何对话原文</div></div>';
  }
  const shareOpts = (save) => ({ hideNumbers: S.shareNoNum, theme: S.shareDark ? 'dark' : 'light', save });
  const tloShareOpen = openShare;
  openShare = function () {
    TLO.share = null;
    TL.ops.shareCard(shareOpts(false)).then((d) => {
      if (d.freshness === 'computing') { toast('协作画像正在计算，稍后再试'); return; }
      if (!d.eligible) { toast(H.BLOCKED[d.blocked_reason] || '暂时不能生成分享卡'); return; }
      TLO.share = d;
      openModal(modalHead('导出分享卡', '1080 × 1350 · 适合朋友圈、小红书与 X') + '<div class="mb" id="shareBody" style="display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start">' + tloShareBody() + '</div><div class="mf"><button type="button" class="btn" data-act="shareCopy">' + ic('copy', 13) + '复制分享文案</button><button type="button" class="btn p" data-act="shareSave">' + ic('down', 13) + '保存图片</button></div>', 'wide');
      MODAL_KEY = 'share';
    }, (e) => { if (TL.unavailable(e)) { tloShareOpen(); if (MODAL_KEY === 'share') tloSample('#modal .mh h2'); } else toast('生成分享卡失败：' + (e.message || e.code)); });
  };
  const shareLive = () => TLO.share && MODAL_KEY === 'share' && $('#shareBody');
  wrap('shareTheme', (base, el, ev) => { if (!shareLive()) return base(el, ev); S.shareDark = el.dataset.v === 'dark'; $('#shareBody').innerHTML = tloShareBody(); });
  wrap('shareNum', (base, el, ev) => { if (!shareLive()) return base(el, ev); S.shareNoNum = !S.shareNoNum; $('#shareBody').innerHTML = tloShareBody(); });
  wrap('shareCopy', (base, el, ev) => {
    const d = shareLive() && TLO.share; if (!d) return base(el, ev); const n = (d.stats || []).find((s) => s.label === '会话');
    copyText('我的 AI 协作人格是 ' + d.code + '「' + d.type_name + '」：' + ((d.copy && d.copy.lines && d.copy.lines[1]) || '') + (S.shareNoNum || !n || n.value == null ? '' : '（近 30 天 · ' + n.value + ' 个会话）') + ' —— 来自 Tandem，全部分析在本机完成。', '分享文案');
  });
  wrap('shareSave', (base, el, ev) => {
    if (!shareLive()) return base(el, ev);
    TL.ops.shareCard(shareOpts(true)).then((d) => toast('已存为分享卡快照' + (d.snapshot_id ? '（' + d.snapshot_id.slice(0, 8) + '）' : '') + '；PNG 由 App 生成'), (e) => toast(TL.unavailable(e) ? '本地服务暂不支持保存分享卡' : '保存失败：' + (e.message || e.code)));
  });

  const tloRender = render;
  render = function () { tloApply(); tloRender(); };
  tloStart();
}
