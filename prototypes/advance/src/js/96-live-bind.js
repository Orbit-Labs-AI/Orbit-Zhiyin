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

function lvSpineBadge() {
  if (LV.state === 'connecting') return '<span class="tl-badge" data-tl="connecting">正在连接本机服务</span>';
  if (LV.state === 'computing') return '<span class="tl-badge" data-tl="computing">分析中</span>';
  if (LV.state === 'error') return '<span class="tl-badge" data-tl="error">' + (ALL.length ? '刷新失败 · 显示上次结果' : '读取失败 · 稍后自动重试') + '</span>';
  if (LV.stale) return '<span class="tl-badge" data-tl="stale">分析中 · 显示上次结果</span>';
  return '';
}
function lvStrip(route) {
  const k = lvKey(route);
  const page = TL.isBound(k) ? TLU.badge(TL_VIEWS[k]) : LV.feedState(route) === 'computing' ? '<span class="tl-badge" data-tl="computing">分析中</span>' : '';
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
