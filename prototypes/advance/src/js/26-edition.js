/* ============ editions: Lite / Advance in one app ============ */
// One window, two editions. Advance = the full desktop app (nine pages, filters, every tool). Lite = genius-FXC's focused
// benchmark, cut down to four pages with one big idea each, built from the same components as Advance (sidebar, cards,
// section heads, KPIs, controls). S.ed is persisted ('edition'); the switch sits on top of the sidebar (also 「显示」menu,
// command palette and ⌃⌘L). Routes map both ways, so a link, notification or flow that calls go('persona') lands on the
// matching page of the edition in use; edOpen(route) jumps from Lite into an Advance detail page.
// Switching slides the switch thumb first, then cross-fades sidebar and content (View Transitions; CSS fallback).
// App (native prefs): a fresh install starts in Lite, later launches come back to the edition and the page last used —
// each edition keeps its own last page ('route' = {lite, advance}, main window only). The browser demo keeps Advance and
// the URL hash.
S.ed = store.get('edition', store.native ? 'lite' : 'advance') === 'lite' ? 'lite' : 'advance';
const ED_SURFACE = /[?&]surface=(panel|hud|widgets)(&|$)/.test(location.search || '');
function edLastRoute(ed) {
  const r = store.get('route', null);
  return r && typeof r === 'object' && typeof r[ed] === 'string' ? r[ed] : null;
}
function edRemember(route) {
  if (!store.native || ED_SURFACE) return;
  const ed = /^l-/.test(route) ? 'lite' : 'advance';
  if (edLastRoute(ed) === route) return;
  const r = Object.assign({}, store.get('route', null) || {}); r[ed] = route; store.set('route', r);
}
const LITE_ROUTES = [['l-home', '概览', 'overview'], ['l-persona', '协作画像', 'persona'], ['l-sessions', '会话轨迹', 'sessions'], ['l-recs', '优化建议', 'recs']];
const TO_LITE = { overview: 'l-home', persona: 'l-persona', sessions: 'l-sessions', recs: 'l-recs' };
const TO_ADV = { 'l-home': 'overview', 'l-persona': 'persona', 'l-sessions': 'sessions', 'l-recs': 'recs' };
const ED_NAME = { lite: 'Lite', advance: 'Advance' };
function navRoutes() { return S.ed === 'lite' ? LITE_ROUTES : ROUTES; }
// A page Lite does not have (tools, projects, sentiment, library, studio) is a request for detail: go() switches to Advance
// and says so, instead of dropping the user on the Lite overview.
function edFollow(route) {
  if (S.ed !== 'lite' || TO_LITE[route] || /^l-/.test(route) || !ROUTES.some((r) => r[0] === route)) return;
  S.ed = 'advance'; store.set('edition', 'advance'); $('#win').dataset.ed = 'advance';
  const name = ROUTES.find((r) => r[0] === route)[1];
  setTimeout(() => toast('「' + name + '」在 Advance 中，已切换到 Advance', { act: '回到 Lite', sec: 5, onAct: () => edSet('lite') }), 0);
}
function edRoute(route, ed) {
  ed = ed || S.ed;
  if (ed === 'lite') return TO_LITE[route] || route;
  return TO_ADV[route] || route;
}
function edSwitch() {
  const b = (ed, hint) => '<button type="button" role="radio" data-act="edition" data-v="' + ed + '" aria-checked="' + (S.ed === ed) + '" data-tip="' + hint + '">' + ED_NAME[ed] + '</button>';
  return '<div class="edsw" role="radiogroup" aria-label="界面版本" aria-keyshortcuts="Control+Meta+L"><span class="edsw-thumb" aria-hidden="true"></span>' +
    b('lite', 'Lite：四页，只看最重要的结论 ' + kb('⌃⌘L')) + b('advance', 'Advance：全部页面、筛选与工具 ' + kb('⌃⌘L')) + '</div>';
}
// Lite uses the Advance sidebar components as they are (same groups, rows, Agents list, footer) and only carries fewer pages:
// the two editions differ in how much they show, not in how it looks.
function renderSideLite() {
  const recN = visibleRecs().filter((r) => !S.installed.has(r.id)).length;
  const n = sel({ noExtra: true }).length;
  const nav = (i, ct, bd) => sideNavBtn(LITE_ROUTES[i][0], LITE_ROUTES[i][1], LITE_ROUTES[i][2], ct, bd);
  $('#side').innerHTML = edSwitch() + '<div class="sb-scroll">' +
    sideGroup('insight', '洞察', nav(0) + nav(1) + nav(2, n)) +
    sideGroup('action', '行动', nav(3, '', recN || '')) +
    sideGroup('agents', 'Agents', sideAgents(), '会话') + '</div>' + sideFoot();
}
// edSet(ed, route?): route = the page to land on in the new edition (a menu / notification route). The swap runs after the
// thumb animation, so the target is passed in instead of calling go(route) next to edSet (that go would run first, while
// S.ed is still the old edition, and be overwritten by the swap's own go).
function edSet(ed, route) {
  if (ed !== 'lite' && ed !== 'advance') return;
  if (ed === S.ed) { if (route) go(route); return; }
  const target = route ? edRoute(route, ed) : edRoute(S.route, ed);
  const win = $('#win');
  const swap = () => { S.ed = ed; store.set('edition', ed); win.dataset.ed = ed; closeDD(); go(target); };
  const reduce = !!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  win.dataset.ed = ed;   // the existing thumb slides now; the content follows once it has moved
  if (reduce) { swap(); return; }
  setTimeout(() => {
    if (typeof document.startViewTransition === 'function') {
      win.classList.add('ed-vt');
      let vt = null;
      try { vt = document.startViewTransition(swap); } catch (e) { swap(); }
      const done = () => win.classList.remove('ed-vt');
      if (vt && vt.finished) vt.finished.then(done, done); else done();
    } else {
      swap();
      const m = $('#main'), sd = $('#side');
      [m, sd].forEach((el) => { el.classList.remove('ed-in'); void el.offsetWidth; el.classList.add('ed-in'); });
    }
  }, 170);
}
function edToggle() { edSet(S.ed === 'lite' ? 'advance' : 'lite'); }
// Lite → Advance detail: switch edition, then open the given Advance route (e.g. a session, a tool table)
function edOpen(route) { if (S.ed === 'lite') { const w = $('#win'); w.dataset.ed = 'advance'; S.ed = 'advance'; store.set('edition', 'advance'); } go(route); }
document.addEventListener('keydown', (e) => {
  if (!(e.ctrlKey && e.metaKey && e.code === 'KeyL')) return;
  if (!$('#overlay').hidden || !$('#modal').hidden) return;
  e.preventDefault(); edToggle();
});
