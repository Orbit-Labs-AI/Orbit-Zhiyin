/* ============ live binding: status strip + endpoint wiring (TandemLive, js/06-live-client.js; core in 90-live-core.js) ============
   Mock mode (file://, opened on its own) changes nothing. Live mode keeps every polished page: 90-live-core hydrates the
   demo globals from /v1/uiview/facts and page feeds (LV.feed) overwrite page constants right before each render. This file
   only puts the status strip (import progress, service banner, connecting / computing / stale / failed badge) at the top of
   the content and keeps the sidebar footer honest. TL_VIEWS / lvScope / lvView / TL_PAGES / lvKey stay as the round-2
   compatibility surface used by 97-* / 98-* until their slices move to LV.feed. */
const TL_VIEWS = {};
const TL_PAGES = {};
function lvScope() {
  const on = AG.filter((a) => S.agents.has(a.id) && !S.srcOff.has(a.id)).map((a) => a.id);
  return { range: S.range, agents: on.length === AG.length ? null : on, projects: null, tz: TL_TZ };
}
function lvView(page) { const v = TL.view(page, lvScope()); TL_VIEWS[page] = v; return v; }
function lvTable(cols, rows, rowAttr) {
  return '<table class="tl-table"><thead><tr>' + cols.map((c) => '<th' + (c.n ? ' class="n"' : '') + '>' + c.t + '</th>').join('') + '</tr></thead><tbody>' +
    rows.map((r) => '<tr' + (rowAttr ? rowAttr(r) : '') + '>' + cols.map((c) => '<td' + (c.n ? ' class="n"' : '') + '>' + c.v(r) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
}
const lvKey = (route) => (TO_ADV[route] && TL_PAGES[TO_ADV[route]] ? TO_ADV[route] : route);
ACT.lvSess = (el) => { S.lvSess = el.dataset.id; render(); };

// 重新计算 next to a failed analysis: the spine (LV.recompute) and every feed resource of the page that failed the same way
const lvRecBtn = () => '<button type="button" class="btn sm" data-act="lvRecompute" data-tl="recompute" style="margin-left:8px">重新计算</button>';
function lvFailedFeeds(route) {
  const out = [];
  (LV.feeds[route] || []).forEach((f) => lvFeedRes(f).forEach((x) => { if (x.r.state === 'error' && TLU.unavailable(x.r.error) && out.indexOf(x.r) < 0) out.push(x.r); }));
  return out;
}
ACT.lvRecompute = (el) => {
  if (el) el.disabled = true;
  const jobs = [];
  if (LV.failed) jobs.push(LV.recompute());
  const v = TL_VIEWS[lvKey(S.route)];
  const rs = lvFailedFeeds(S.route).concat(v && v.res ? Object.keys(v.res).map((n) => v.res[n]).filter((r) => r.state === 'error' && TLU.unavailable(r.error)) : []);
  rs.forEach((r) => jobs.push(TL.recompute(r, r.section ? null : { sections: [LV_SECTION], scope: { display_timezone: TL_TZ || 'UTC' } }).catch(() => {})));
  if (!jobs.length) LV.loadSpine();
  render();
};
function lvJobNote() {
  const j = LV.job; if (!j || j.elapsed_s == null) return '';
  return ' · 已用 ' + Math.round(j.elapsed_s) + (j.timeout_s ? ' / ' + Math.round(j.timeout_s) : '') + ' 秒';
}
function lvSpineBadge() {
  if (LV.failed) return '<span class="tl-badge" data-tl="unavailable">' + esc(TLU.reason(LV.failed.reason)) + (ALL.length ? ' · 显示上次结果' : '') + '</span>' + lvRecBtn();
  if (LV.state === 'connecting') return '<span class="tl-badge" data-tl="connecting">正在连接本机服务</span>';
  if (LV.state === 'computing') return '<span class="tl-badge" data-tl="computing">分析中' + lvJobNote() + '</span>';
  if (LV.state === 'error') return '<span class="tl-badge" data-tl="error">' + (ALL.length ? '刷新失败 · 显示上次结果' : '读取失败 · 稍后自动重试') + '</span>';
  if (LV.stale) return '<span class="tl-badge" data-tl="stale">分析中 · 显示上次结果</span>';
  return '';
}
function lvStrip(route) {
  const k = lvKey(route);
  const failed = lvFailedFeeds(route);
  const page = TL.isBound(k) ? TLU.badge(TL_VIEWS[k]) + (TL_VIEWS[k] && TLU.unavailable(TL_VIEWS[k].error) ? lvRecBtn() : '')
    : failed.length ? '<span class="tl-badge" data-tl="unavailable">' + esc(TLU.unavailable(failed[0].error)) + '</span>' + lvRecBtn()
      : LV.feedState(route) === 'computing' ? '<span class="tl-badge" data-tl="computing">分析中</span>' : '';
  const b = lvSpineBadge() || page;
  const html = TLU.progress(TL) + TLU.banner(TL) + (b ? '<div>' + b + '</div>' : '');
  return html ? '<div class="tl-strip" data-tl="strip">' + html + '</div>' : '';
}

if (LV.live) {
  TLU.ensureStyle(document);
  const baseRender = render, baseSide = renderSide;
  render = function () {
    LV.pump(S.route);
    baseRender();
    const c = $('#content'); if (!c) return;
    const old = c.querySelector(':scope > [data-tl="strip"]'); if (old) old.remove();
    const strip = lvStrip(S.route);
    if (strip) c.insertAdjacentHTML('afterbegin', strip);
  };
  renderSide = function () {
    baseSide();
    const el = $('#side') && $('#side').querySelector('.sb-foot .pv .row.cap span');
    if (el) el.textContent = LV.state === 'connecting' ? (TL.error ? '本机服务未连接' : '正在连接本机服务') : '已索引 ' + fmt(ALL.length) + ' 个会话 · 本机服务';
  };
  TL.start();
}
