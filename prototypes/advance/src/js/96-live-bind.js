/* ============ live binding (TandemLive, js/06-live-client.js) ============
   Mock mode (file://, opened on its own) changes nothing. Live mode (served by the gateway at /app, or ?live=1) replaces the
   bound pages with API-backed renderers, overlays the sidebar counts and the settings › 数据源 list, and puts the status strip
   (import progress, service banner, stale / computing badge, 示例数据 on pages that are not bound yet) at the top of the content.
   Hooks wrap render / renderSide / renderSet from here; no other file changes. The demo's sel() / stats() / persona() and
   15-derive are not used to show anything on bound pages. */
const TL = TandemLive.create({ onChange: () => render() });
const TLU = TandemLive.ui;
const TL_VIEWS = {};
const TL_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return null; } })();
function tlScope() {
  const on = AG.filter((a) => S.agents.has(a.id) && !S.srcOff.has(a.id)).map((a) => a.id);
  return { range: S.range, agents: on.length === AG.length ? null : on, projects: null, tz: TL_TZ };
}
function tlView(page) { const v = TL.view(page, tlScope()); TL_VIEWS[page] = v; return v; }
function tlTable(cols, rows, rowAttr) {
  return '<table class="tl-table"><thead><tr>' + cols.map((c) => '<th' + (c.n ? ' class="n"' : '') + '>' + c.t + '</th>').join('') + '</tr></thead><tbody>' +
    rows.map((r) => '<tr' + (rowAttr ? rowAttr(r) : '') + '>' + cols.map((c) => '<td' + (c.n ? ' class="n"' : '') + '>' + c.v(r) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
}
const tlKpi = (label, value) => '<div class="tl-card tl-kpi"><b>' + value + '</b><span>' + label + '</span></div>';
function tlPage(title, meta, v, body) { return tbar(title, meta) + '<div class="content" id="content">' + filterRow() + TLU.body(v, body) + '</div>'; }

TL.bind('overview', [{ name: 'ov', path: '/v1/analytics/overview', waitMs: 800 }], (d) => {
  const o = d.ov.overview || {}; const c = o.counts || {}; const u = o.usage || {};
  return { counts: c, usage: u, coverage: d.ov.meta && d.ov.meta.coverage };
});
TL.bind('sessions', (scope) => {
  const res = [{ name: 'list', path: '/v1/analytics/sessions', query: { offset: 0, limit: 50 } }];
  if (S.tlSess) res.push({ name: 'events', path: '/v1/sessions/' + encodeURIComponent(S.tlSess) + '/events', query: { limit: 200 }, scope: false });
  return res;
}, (d) => ({ total: d.list.total, rows: d.list.sessions || [], events: d.events ? d.events.items || [] : null }));
TL.bind('tools', [{ name: 't', path: '/v1/analytics/tools' }], (d) => { const t = d.t.tools || {}; return { totals: t.totals || {}, rows: t.by_tool || [] }; });
TL.bind('projects', [{ name: 'p', path: '/v1/analytics/projects' }], (d) => { const p = d.p.projects || {}; return { status: p.status, rows: p.records || [] }; });

const TL_PAGES = {
  overview() {
    const v = tlView('overview');
    return tlPage('概览', '本机数据 · ' + rangeLabel(), v, (vm) => '<div class="tl-grid" data-tl="overview">' +
      tlKpi('会话', TLU.num(vm.counts.sessions)) + tlKpi('真人消息', TLU.num(vm.counts.human_messages)) + tlKpi('工具调用', TLU.num(vm.counts.tool_calls)) +
      tlKpi('项目', TLU.num(vm.counts.projects)) + tlKpi('活跃天数', TLU.num(vm.counts.active_days)) + tlKpi('模型请求', TLU.num(vm.usage.request_count)) +
      tlKpi('Token', TLU.num(vm.usage.total_tokens)) + tlKpi('费用', TLU.money(vm.usage.cost_usd)) + '</div>');
  },
  sessions() {
    const v = tlView('sessions');
    return tlPage('会话与轨迹', v && v.vm ? TLU.num(v.vm.total) + ' 个会话' : '', v, (vm) => {
      const list = tlTable([
        { t: '会话', v: (s) => esc(s.title || s.session_uid) },
        { t: '消息', n: 1, v: (s) => TLU.num(s.features && s.features.user_message_count) },
        { t: '工具', n: 1, v: (s) => TLU.num(s.features && s.features.tool_call_count) },
        { t: 'Token', n: 1, v: (s) => TLU.num(s.usage && s.usage.total_tokens) }
      ], vm.rows, (s) => ' data-tl-sel data-act="tlSess" data-id="' + esc(s.session_uid) + '"' + (S.tlSess === s.session_uid ? ' class="on"' : ''));
      const ev = vm.events == null ? '<div class="cap">选择一个会话查看事件</div>' : vm.events.length ? vm.events.map((e) => '<div class="tl-ev">#' + TLU.num(e.seq) + ' · ' + TLU.hm(e.ts) + ' · ' + esc(e.kind) + ' · ' + esc(e.summary || '') + '</div>').join('') : TLU.empty('该会话没有事件');
      return '<div class="stack" data-tl="sessions"><div class="tl-card">' + list + '</div><div class="tl-card" data-tl="events">' + ev + '</div></div>';
    });
  },
  tools() {
    const v = tlView('tools');
    return tlPage('工具调用', v && v.vm ? TLU.num(v.vm.totals.call_count) + ' 次调用' : '', v, (vm) => '<div class="stack" data-tl="tools"><div class="tl-grid">' +
      tlKpi('调用', TLU.num(vm.totals.call_count)) + tlKpi('明确失败', TLU.num(vm.totals.known_failure_count)) + tlKpi('状态未知', TLU.num(vm.totals.unknown_status_count)) + tlKpi('失败率', TLU.pct(vm.totals.failure_rate)) + '</div>' +
      '<div class="tl-card">' + tlTable([
        { t: '工具', v: (r) => esc(r.name) }, { t: '调用', n: 1, v: (r) => TLU.num(r.call_count) }, { t: '成功', n: 1, v: (r) => TLU.num(r.known_success_count) },
        { t: '失败', n: 1, v: (r) => TLU.num(r.known_failure_count) }, { t: '未知', n: 1, v: (r) => TLU.num(r.unknown_status_count) }, { t: '中位时长 ms', n: 1, v: (r) => TLU.num(r.median_duration_ms) }
      ], vm.rows) + '</div></div>');
  },
  projects() {
    const v = tlView('projects');
    return tlPage('项目习惯', v && v.vm ? v.vm.rows.length + ' 个项目' : '', v, (vm) => '<div class="tl-card" data-tl="projects">' + tlTable([
      { t: '项目', v: (r) => esc(r.name || r.project_id) }, { t: '会话', n: 1, v: (r) => TLU.num(r.session_count) }, { t: '真人消息', n: 1, v: (r) => TLU.num(r.human_message_count) },
      { t: '工具调用', n: 1, v: (r) => TLU.num(r.tool_call_count) }, { t: '最近', n: 1, v: (r) => TLU.hm(r.last_observed_ts) }
    ], vm.rows) + '</div>');
  }
};
ACT.tlSess = (el) => { S.tlSess = el.dataset.id; render(); };

if (TL.mode === 'live') {
  Object.keys(TL_PAGES).forEach((k) => { PAGES[k] = TL_PAGES[k]; });
  TLU.ensureStyle(document);
  const baseRender = render, baseSide = renderSide, baseSet = renderSet;
  const tlSources = () => { const r = TL.resource('/v1/app/sources'); if (r.dirty && !r.loading) TL.load(r); return r; };
  render = function () {
    baseRender();
    const c = $('#content'); if (!c) return;
    const old = c.querySelector(':scope > [data-tl="strip"]'); if (old) old.remove();
    const strip = TLU.strip(TL, S.route, TL_VIEWS[S.route]);
    if (strip) c.insertAdjacentHTML('afterbegin', strip);
  };
  renderSide = function () {
    baseSide();
    const st = TL.status; const side = $('#side');
    const set = (sel, text) => { const el = side.querySelector(sel); if (el) el.textContent = text; };
    set('[data-r="sessions"] .ct', TLU.num(st && st.counts && st.counts.sessions));
    set('[data-r="projects"] .ct', TLU.num(st && st.counts && st.counts.projects));
    AG.forEach((a) => {
      const keys = TandemLive.AGENT_KEYS[a.id] || [];
      const src = ((st && st.sources) || []).filter((s) => keys.indexOf(String(s.agent || '').toLowerCase()) >= 0);
      const on = src.filter((s) => s.enabled !== false);
      set('.ag[data-a="' + a.id + '"] .ct', !st ? '—' : !src.length ? '—' : !on.length ? '停用' : TLU.num(on.some((s) => s.sessions == null) ? null : on.reduce((n, s) => n + s.sessions, 0)));
    });
    side.querySelectorAll('[data-act="pinProject"] .ct').forEach((el) => { el.textContent = '—'; });
    set('.me .pc', '—');
    set('.sb-foot .pv .row.cap span', st ? '已索引 ' + TLU.num(st.counts && st.counts.sessions) + ' 个会话 · 本机服务' : TL.error ? '本机服务未连接' : '正在连接本机服务');
  };
  renderSet = function () {
    baseSet();
    if ($('#set').hidden || S.setTab !== 'sources') return;
    const card = $$('#set .card').find((x) => { const t = x.querySelector('.ct'); return t && t.textContent === '已检测到的 Agent'; });
    if (!card) return;
    const r = tlSources(); const box = card.lastElementChild;
    box.setAttribute('data-tl', 'sources');
    box.innerHTML = r.data ? ((r.data.sources || []).map((s) => '<div class="srcrow" style="opacity:' + (s.enabled === false ? 0.55 : 1) + '"><div style="min-width:0"><b style="font-size:13px">' + esc(s.name || s.agent) + '</b><div class="cap" style="font-size:11px">' + esc(s.id) + ' · ' + (s.enabled === false ? '已停用' : '已启用') + '</div></div><span class="when">' + TLU.num(s.sessions) + ' 个会话 · ' + TLU.hm(s.last_scan) + '</span></div>').join('') || TLU.empty('尚未发现数据来源'))
      : r.state === 'error' ? TLU.errorCard(r.error) : TLU.skeleton();
  };
  TL.start();
}
