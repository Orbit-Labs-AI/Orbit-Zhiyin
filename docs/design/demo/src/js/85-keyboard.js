/* ============ keyboard ============ */
// Dispatch order: palette / dropdown / reveal specifics → Escape chain (overlay, sheet, menu, panel, HUD, settings, sidebar
// overlay) → page hook PAGES[S.route].keys(e) (return true = handled; skipped while a sheet, overlay or menu is open or the
// settings window is key) → Return in a sheet = default button → global shortcuts.
// Demo bindings (browser-safe; the App uses ⌘ where noted): ⌥1–9 pages (⌘1–9), ⌥0 main window (⌘0), ⌃⌘S sidebar, ⌃⌘F full
// screen, ⌘M minimise, ⌘K palette, ⌘, settings, ⇧⌘S share card, ⇧⌘E report, ⌥⌘P HUD, ⌃⌥T panel, ⌥R reindex (⌘R), ⌥T chart/table
// (⌘T), ⌘F find, ⌘↩ main action, ⌘Z undo install, ⌘[ back, ? shortcuts, Space play/pause (sessions).
document.addEventListener('keydown', (e) => {
  const tg = e.target; const tag = (tg.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select' || tg.isContentEditable;
  const mod = e.metaKey || e.ctrlKey;
  const modalOpen = !$('#modal').hidden, ovOpen = !$('#overlay').hidden, setOpen = !$('#set').hidden;
  if (MODAL_KEY === 'palette' && modalOpen && PAL) {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); PAL.i = clamp(PAL.i + (e.key === 'ArrowDown' ? 1 : -1), 0, Math.max(0, PAL.items.length - 1)); drawPal(); return; }
    if (e.key === 'Enter') { e.preventDefault(); const it = PAL.items[PAL.i]; closeModal(); if (it) it.run(); return; }
  }
  if (tg.id === 'askIn' && e.key === 'Enter' && !e.isComposing) { e.preventDefault(); ACT.askSend(); return; }
  if (DD && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault(); const bs = $$('#dd button[data-i]:not([disabled])'); if (!bs.length) return;
    let i = bs.findIndex((b) => b.classList.contains('act')); bs.forEach((b) => b.classList.remove('act'));
    i = i < 0 ? (e.key === 'ArrowDown' ? 0 : bs.length - 1) : (i + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length;
    bs[i].classList.add('act'); bs[i].scrollIntoView({ block: 'nearest' }); return;
  }
  if (DD && e.key === 'Enter') { const b = $('#dd button.act'); if (b) { e.preventDefault(); b.click(); return; } }
  if (OVL === 'reveal' && REV && !REV.done) { if (e.key !== 'Tab') { e.preventDefault(); revealSkip(); } return; }
  if (e.key === 'Escape') {
    if (ovOpen) { closeOverlay(); render(); return; }
    if (modalOpen) { clearInterval(ASKT); closeModal(); return; }
    if (DD) { closeDD(); return; }
    if (S.pop) { S.pop = false; render(); return; }
    if (S.hud.open) { S.hud.open = false; renderHud(); return; }
    if (setOpen && S.keyWin === 'set') { closeSettings(); return; }
    if (S.sideOver) { S.sideOver = false; applyWin(); renderWtop(); return; }
  }
  if (!modalOpen && !ovOpen && !DD && S.keyWin === 'main') {
    const pg = PAGES[S.route];
    if (pg && typeof pg.keys === 'function' && pg.keys(e) === true) { if (!e.defaultPrevented) e.preventDefault(); return; }
  }
  if (modalOpen && MODAL_HOST && e.key === 'Enter' && !e.isComposing && tag !== 'textarea' && tag !== 'button' && tag !== 'a' && !e.shiftKey && !mod) {
    const p = $$('#modal .mf .btn.p:not([disabled])').pop(); if (p) { e.preventDefault(); p.click(); return; }
  }
  if (tg.id === 'hudPill' && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); S.hud.open = !S.hud.open; renderHud(); const p = $('#hudPill'); if (p) p.focus(); return; }
  if (ovOpen) return;
  if (e.ctrlKey && e.altKey && e.code === 'KeyT') { e.preventDefault(); S.pop = !S.pop; render(); return; }
  if (e.ctrlKey && e.metaKey && e.code === 'KeyS') { e.preventDefault(); toggleSide(); return; }
  if (e.ctrlKey && e.metaKey && e.code === 'KeyF') { e.preventDefault(); winFullToggle(); return; }
  if (mod && e.altKey && e.code === 'KeyP') { e.preventDefault(); toggleHud(); return; }
  if (mod && !e.altKey && !e.shiftKey && e.code === 'KeyK') { e.preventDefault(); if (MODAL_KEY === 'palette' && modalOpen) closeModal(); else { closeModal(); openPalette(); } return; }
  if (mod && e.key === ',') { e.preventDefault(); closeModal(); openSettings(); return; }
  if (mod && e.shiftKey && e.code === 'KeyS') { e.preventDefault(); closeModal(); openShare(); return; }
  if (mod && e.shiftKey && e.code === 'KeyE') { e.preventDefault(); closeModal(); openReport(); return; }
  if (modalOpen) return;
  if (mod && !e.shiftKey && !e.altKey && e.code === 'KeyZ' && !typing) { e.preventDefault(); undoInstall(); return; }
  if (mod && !e.altKey && e.code === 'KeyF') { e.preventDefault(); findCmd(); return; }
  if (mod && e.key === 'Enter') { e.preventDefault(); mainAction(); return; }
  if (mod && !e.altKey && !e.shiftKey && e.code === 'KeyM' && !typing) { e.preventDefault(); ACT.winMin(); return; }
  if ((mod || e.altKey) && e.code === 'BracketLeft' && !typing) { e.preventDefault(); goBack(); return; }
  if (e.altKey && !mod && /^Digit[1-9]$/.test(e.code)) { e.preventDefault(); go(ROUTES[+e.code.slice(5) - 1][0]); return; }
  if (e.altKey && !mod && e.code === 'Digit0') { e.preventDefault(); showMain(); return; }
  if (e.altKey && !mod && e.code === 'KeyR') { e.preventDefault(); reindex(); return; }
  if (e.altKey && !mod && e.code === 'KeyT') { e.preventDefault(); if (S.route === 'overview') { S.view = S.view === 'chart' ? 'table' : 'chart'; render(); toast(S.view === 'chart' ? '已切换为图表' : '已切换为表格'); } else toast('图表 ↔ 表格只在概览页可用'); return; }
  if (typing) return;
  if (e.key === '?') { e.preventDefault(); openKeys(); return; }
  if (e.key === ' ' && S.route === 'sessions' && !tg.closest('button,a,input,textarea,select,[tabindex]')) { e.preventDefault(); ACT.playToggle(); }
});
