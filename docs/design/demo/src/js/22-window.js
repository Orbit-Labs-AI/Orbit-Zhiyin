/* ============ window manager ============ */
// The stage (#desk) is fixed; the main window is S.win = {x, y, w, h, zoom, full}. All four null = the published layout:
// the window fills the stage under the menu bar with 24px side / 18px top and bottom margins and, at ≥ 1500px with the
// desktop widgets shown, starts right of the widget column (24 + 364 + 24) so the widgets stay visible on the desktop layer.
// An untouched window keeps following the viewport; once the user moves or resizes it the rect is explicit and persisted
// (localStorage 'win') and only gets clamped to the stage. winRect() turns S.win into the effective rect: "win" (never below
// WIN_MIN), "zoom" (fills the area under the menu bar), "full" (fills the stage, menu bar slides away, ⌃⌘F / green light)
// or "fit" (stage smaller than WIN_MIN + margins, e.g. 820px wide: 16px margins, the inner layout adapts through
// container queries). applyWin() writes the rect, keeps the sidebar flags coherent (a window narrower than SIDE_MIN_WIN
// hides the sidebar and shows it as an overlay on demand) and fires window 'tandem:layout' whenever the content size or
// the sidebar changed — pages and vizkit re-measure on it. Drag the title row to move, 8px edges / corners to resize,
// double-click to zoom.
const MB_H = 24, WIN_MIN = { w: 900, h: 600 }, STAGE_PAD = 16, SIDE_MIN_WIN = 900;
const WIN_GAP = { x: 24, y: 18 }, WG_COL = 24 + 364 + 24, WIDE_MIN = 1500;
let WIN_LAST = null, WIN_SIG = '';
(function loadShell() {
  const w = store.get('win', null);
  if (w && typeof w === 'object') { ['x', 'y', 'w', 'h'].forEach((k) => { if (typeof w[k] === 'number' && isFinite(w[k])) S.win[k] = w[k]; }); if (w.zoom === true) S.win.zoom = true; }
  const sd = store.get('side', null);
  if (sd && typeof sd === 'object') { if (typeof sd.show === 'boolean') S.side = sd.show; if (sd.open && typeof sd.open === 'object') Object.keys(S.sideOpen).forEach((k) => { if (typeof sd.open[k] === 'boolean') S.sideOpen[k] = sd.open[k]; }); }
  ['n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se'].forEach((d) => { const h = document.createElement('div'); h.className = 'rz'; h.dataset.rz = d; h.setAttribute('aria-hidden', 'true'); $('#win').appendChild(h); });
})();
function stageSize() { return { w: desk.clientWidth, h: desk.clientHeight }; }
function winRect() {
  const st = stageSize(), W = S.win;
  if (W.full) return { x: 0, y: 0, w: st.w, h: st.h, mode: 'full' };
  const areaH = st.h - MB_H;
  if (W.zoom) return { x: 0, y: MB_H, w: st.w, h: areaH, mode: 'zoom' };
  const maxW = st.w - STAGE_PAD * 2, maxH = areaH - STAGE_PAD * 2;
  if (maxW < WIN_MIN.w || maxH < WIN_MIN.h) return { x: STAGE_PAD, y: MB_H + STAGE_PAD, w: Math.max(240, maxW), h: Math.max(240, maxH), mode: 'fit' };
  const left = widgetsWide() ? WG_COL : WIN_GAP.x;
  const w = clamp(W.w == null ? st.w - left - WIN_GAP.x : W.w, WIN_MIN.w, maxW), h = clamp(W.h == null ? areaH - WIN_GAP.y * 2 : W.h, WIN_MIN.h, maxH);
  const x = W.x == null ? Math.min(left, st.w - w) : clamp(W.x, 0, st.w - w);
  const y = W.y == null ? Math.min(MB_H + WIN_GAP.y, st.h - h) : clamp(W.y, MB_H, st.h - h);
  return { x, y, w, h, mode: 'win' };
}
// the desktop widgets get their own column left of the window only when the stage is wide enough (≥ 1500px, as published)
function widgetsWide() { return S.widgets && stageSize().w >= WIDE_MIN; }
function applyWin() {
  const r = winRect(); const w = $('#win');
  w.style.left = r.x + 'px'; w.style.top = r.y + 'px'; w.style.width = r.w + 'px'; w.style.height = r.h + 'px';
  w.dataset.mode = r.mode;
  desk.classList.toggle('fs', r.mode === 'full'); if (r.mode !== 'full') desk.classList.remove('mbpeek');
  w.classList.toggle('zoomed', r.mode === 'zoom');
  const narrow = r.w < SIDE_MIN_WIN; if (!narrow) S.sideOver = false;
  const sideShown = narrow ? S.sideOver : S.side;
  w.classList.toggle('narrow', narrow); w.classList.toggle('nosb', !sideShown); w.classList.toggle('sbover', narrow && S.sideOver);
  w.classList.toggle('inactive', S.keyWin !== 'main');
  WIN_LAST = r;
  const sig = [r.w, r.h, r.mode, sideShown].join('|');
  if (sig !== WIN_SIG) { WIN_SIG = sig; layoutChanged(); }
  placeDeps();
}
function layoutChanged() {
  const r = WIN_LAST || winRect(); const m = $('#main');
  const detail = { win: { x: r.x, y: r.y, w: r.w, h: r.h, mode: r.mode }, side: !$('#win').classList.contains('nosb'), main: { w: m ? m.clientWidth : 0, h: m ? m.clientHeight : 0 } };
  try { window.dispatchEvent(new CustomEvent('tandem:layout', { detail })); } catch (e) { /* ignore */ }
}
function placeDeps() { toastPlace(); sheetPlace(); overlayPlace(); if (S.pop) popPlace(); hudPlace(); }
function overlayPlace() {
  const o = $('#overlay'); if (o.hidden) return;
  const d = desk.getBoundingClientRect();
  if (S.winGone || S.win.full) { o.style.left = '0px'; o.style.top = '0px'; o.style.width = d.width + 'px'; o.style.height = d.height + 'px'; o.style.borderRadius = '0'; return; }
  const r = $('#win').getBoundingClientRect();
  o.style.left = Math.round(r.left - d.left) + 'px'; o.style.top = Math.round(r.top - d.top) + 'px'; o.style.width = Math.round(r.width) + 'px'; o.style.height = Math.round(r.height) + 'px'; o.style.borderRadius = getComputedStyle($('#win')).borderRadius;
}
function saveWin() { store.set('win', { x: S.win.x, y: S.win.y, w: S.win.w, h: S.win.h, zoom: !!S.win.zoom }); }
function saveSide() { store.set('side', { show: S.side, open: S.sideOpen }); }
function winNarrow() { return (WIN_LAST || winRect()).w < SIDE_MIN_WIN; }
function toggleSide() { if (winNarrow()) S.sideOver = !S.sideOver; else { S.side = !S.side; S.sideOver = false; saveSide(); } applyWin(); renderWtop(); }
function winZoomToggle() { if (S.win.full) return; S.win.zoom = !S.win.zoom; saveWin(); applyWin(); renderWtop(); }
function winFullToggle() { S.win.full = !S.win.full; S.sideOver = false; applyWin(); renderWtop(); renderWidgets(); }
function showMain() { S.winGone = false; S.pop = false; S.keyWin = 'main'; render(); }
function keyWinApply() { $('#win').classList.toggle('inactive', S.keyWin !== 'main'); $('#set').classList.toggle('inactive', S.keyWin !== 'set'); }
document.addEventListener('pointerdown', (e) => {
  const set = e.target.closest('#set'), win = e.target.closest('#win');
  if (set && S.keyWin !== 'set') { S.keyWin = 'set'; keyWinApply(); }
  else if (win && S.keyWin !== 'main') { S.keyWin = 'main'; keyWinApply(); }
}, true);
/* move (title row) and resize (edge handles) of the main window */
let WDRAG = null;
const BAR_SKIP = 'button,input,select,textarea,a,label,[role="button"],.tsearch,.chip,.seg';
$('#win').addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  const rz = e.target.closest('.rz');
  const bar = !rz && e.target.closest('.tbar,.wtop') && !e.target.closest(BAR_SKIP);
  if (!rz && !bar) return;
  const r = winRect(); if (r.mode !== 'win') return;
  // no preventDefault and no pointer capture yet: both would retarget the click / dblclick that zooms the window
  WDRAG = { kind: rz ? 'rz' : 'move', dir: rz ? rz.dataset.rz : '', sx: e.clientX, sy: e.clientY, r0: { x: r.x, y: r.y, w: r.w, h: r.h }, moved: false, id: e.pointerId };
});
document.addEventListener('pointermove', (e) => {
  if (!WDRAG) return;
  const dx = e.clientX - WDRAG.sx, dy = e.clientY - WDRAG.sy; const st = stageSize(), r0 = WDRAG.r0;
  if (!WDRAG.moved) { if (Math.hypot(dx, dy) < 3) return; WDRAG.moved = true; try { $('#win').setPointerCapture(WDRAG.id); } catch (err) { /* ignore */ } }
  // moving also pins the current size: from here on the window is the user's and no longer follows the viewport
  if (WDRAG.kind === 'move') { S.win.x = clamp(r0.x + dx, 0, Math.max(0, st.w - r0.w)); S.win.y = clamp(r0.y + dy, MB_H, Math.max(MB_H, st.h - r0.h)); S.win.w = r0.w; S.win.h = r0.h; }
  else {
    const d = WDRAG.dir; let x = r0.x, y = r0.y, w = r0.w, h = r0.h;
    if (d.includes('e')) w = clamp(r0.w + dx, WIN_MIN.w, st.w - r0.x);
    if (d.includes('s')) h = clamp(r0.h + dy, WIN_MIN.h, st.h - r0.y);
    if (d.includes('w')) { x = clamp(r0.x + dx, 0, r0.x + r0.w - WIN_MIN.w); w = r0.x + r0.w - x; }
    if (d.includes('n')) { y = clamp(r0.y + dy, MB_H, r0.y + r0.h - WIN_MIN.h); h = r0.y + r0.h - y; }
    S.win.x = x; S.win.y = y; S.win.w = w; S.win.h = h;
  }
  applyWin();
});
function winDragEnd() { if (!WDRAG) return; const d = WDRAG; WDRAG = null; try { $('#win').releasePointerCapture(d.id); } catch (err) { /* ignore */ } if (d.moved) saveWin(); }
document.addEventListener('pointerup', winDragEnd);
document.addEventListener('pointercancel', winDragEnd);
$('#win').addEventListener('dblclick', (e) => { if (e.target.closest('.tbar,.wtop') && !e.target.closest(BAR_SKIP)) winZoomToggle(); });
$('#win').addEventListener('transitionend', (e) => { if (e.target !== $('#win')) return; if (e.propertyName === 'grid-template-columns' || e.propertyName === 'transform') { layoutChanged(); placeDeps(); } });
/* settings panel: drag by its title row (position kept in S.setPos, re-clamped on resize by setPlace()) */
let PDRAG = null;
$('#set').addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || !e.target.closest('.ptop') || e.target.closest('button')) return;
  const el = $('#set'); const r = el.getBoundingClientRect(), d = desk.getBoundingClientRect();
  PDRAG = { sx: e.clientX, sy: e.clientY, x0: r.left - d.left, y0: r.top - d.top, w: r.width, h: r.height, moved: false, id: e.pointerId };
});
document.addEventListener('pointermove', (e) => {
  if (!PDRAG) return; const st = stageSize();
  if (!PDRAG.moved) { if (Math.hypot(e.clientX - PDRAG.sx, e.clientY - PDRAG.sy) < 3) return; PDRAG.moved = true; try { $('#set').setPointerCapture(PDRAG.id); } catch (err) { /* ignore */ } }
  S.setPos = { x: clamp(PDRAG.x0 + e.clientX - PDRAG.sx, 0, Math.max(0, st.w - PDRAG.w)), y: clamp(PDRAG.y0 + e.clientY - PDRAG.sy, MB_H, Math.max(MB_H, st.h - PDRAG.h)) };
  setPlace(); sheetPlace();
});
function setDragEnd() { if (!PDRAG) return; const d = PDRAG; PDRAG = null; try { $('#set').releasePointerCapture(d.id); } catch (err) { /* ignore */ } }
document.addEventListener('pointerup', setDragEnd);
document.addEventListener('pointercancel', setDragEnd);
/* full screen: the menu bar peeks back when the pointer touches the top edge */
document.addEventListener('mousemove', (e) => {
  if (!desk.classList.contains('fs')) return;
  if (e.clientY <= 2) desk.classList.add('mbpeek');
  else if (e.clientY > 40 && $('#dd').hidden && !S.pop) desk.classList.remove('mbpeek');
});
new MutationObserver(() => overlayPlace()).observe($('#overlay'), { attributes: true, attributeFilter: ['hidden'] });
