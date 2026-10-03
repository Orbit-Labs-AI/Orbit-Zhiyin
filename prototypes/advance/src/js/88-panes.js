/* ============ pane scrolling (styles/88-panes.css) ============ */
// Master–detail pages scroll per pane. After every render (25-nav.js, after the scroll positions are put back) and after the
// sessions page's partial pick (42-a3-sessions.js) this keeps the selected session row / rec card visible inside its own
// list pane, and starts the detail pane at the top when the selection changed. Only the pane moves: scrollIntoView would
// also scroll #content and the window. Route changes start every pane at the top (go() in 25-nav.js).
const PANES = [
  { list: '.sess>.card>.slist', item: '.srow.sel', detail: '.sess>.stack' },
  { list: '.recs>.stack', item: '.rcard.sel', detail: '.recs>:last-child' }
];
function paneReveal(el, pane) {
  if (!el || !pane || pane.scrollHeight <= pane.clientHeight + 1) return;
  const r = el.getBoundingClientRect(), p = pane.getBoundingClientRect(), pad = 8;
  if (r.top < p.top + pad) pane.scrollTop -= p.top + pad - r.top;
  else if (r.bottom > p.bottom - pad) pane.scrollTop += Math.min(r.bottom - p.bottom + pad, r.top - p.top - pad);
}
function paneSync() {
  const m = $('#main'); if (!m) return;
  const last = paneSync.last || (paneSync.last = {});
  PANES.forEach((d, i) => {
    const list = m.querySelector(d.list); if (!list) { delete last[i]; return; }
    const sel = $$(d.item, list); const key = S.route + '|' + sel.map((x) => x.dataset.id || '').join(',');
    if (last[i] === key) return;
    const was = last[i]; last[i] = key;
    if (was && was.split('|')[0] === S.route) { const det = m.querySelector(d.detail); if (det) det.scrollTop = 0; }
    if (sel[0]) paneReveal(sel[0], list);
  });
}
