/* ============ editions: Lite / Advance in one app ============ */
// One window, two editions. Advance = the full desktop app (nine pages, filters, every tool). Lite = genius-FXC's focused
// benchmark, cut down to four pages with one big idea each. S.ed is persisted ('edition'); the switch sits on top of the
// sidebar (also 「显示」menu, command palette and ⌃⌘L). Routes map both ways, so a link, notification or flow that calls
// go('persona') lands on the matching page of the edition in use; edOpen(route) jumps from Lite into an Advance detail page.
// Switching slides the switch thumb first, then cross-fades sidebar and content (View Transitions; CSS fallback).
S.ed = store.get('edition', 'advance') === 'lite' ? 'lite' : 'advance';
const LITE_ROUTES = [['l-home', '概览', 'overview'], ['l-persona', '协作画像', 'persona'], ['l-sessions', '会话轨迹', 'sessions'], ['l-recs', '优化建议', 'recs']];
const TO_LITE = { overview: 'l-home', persona: 'l-persona', sessions: 'l-sessions', recs: 'l-recs', library: 'l-recs', studio: 'l-recs', tools: 'l-home', projects: 'l-home', sentiment: 'l-home' };
const TO_ADV = { 'l-home': 'overview', 'l-persona': 'persona', 'l-sessions': 'sessions', 'l-recs': 'recs' };
const ED_NAME = { lite: 'Lite', advance: 'Advance' };
function navRoutes() { return S.ed === 'lite' ? LITE_ROUTES : ROUTES; }
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
function renderSideLite() {
  const recN = visibleRecs().filter((r) => !S.installed.has(r.id)).length;
  const n = sel({ noExtra: true }).length;
  const sub = { 'l-home': rangeLabel() + ' · ' + n + ' 个会话', 'l-persona': (personaNow().ok ? personaNow().code + ' · ' + personaNow().zh : '样本不足'), 'l-sessions': '关键任务与时间线', 'l-recs': recN + ' 条待处理' };
  const items = LITE_ROUTES.map((r, i) => '<button type="button" data-act="go" data-r="' + r[0] + '"' + (S.route === r[0] ? ' aria-current="page"' : '') + '><span class="ln-i">' + ic(r[2], 17) + '</span><span class="ln-t"><span class="lb">' + r[1] + '</span><span class="ln-s">' + esc(sub[r[0]]) + '</span></span><span class="ln-k">' + kb('⌥' + (i + 1)) + '</span></button>').join('');
  $('#side').innerHTML = edSwitch() + '<div class="sb-scroll"><div class="nav lnav">' + items + '</div>' +
    '<button type="button" class="ln-more" data-act="edition" data-v="advance">' + ic('grid', 14) + '<span>需要明细、筛选与工具？<b>切到 Advance</b></span></button></div>' + sideFoot();
}
function edSet(ed) {
  if (ed !== 'lite' && ed !== 'advance') return;
  if (ed === S.ed) return;
  const target = edRoute(S.route, ed);
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
