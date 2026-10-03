/* ============ native window drag regions ============ */
// Native shell only (window.__ORBIT_NATIVE__, main surface): the host's MainWindow (apps/desktop/Orbit.swift) drags the real
// window from a 3–8px ring inside every edge and from the 38px title strip, and asks the page where it must not do that.
// This reports, in viewport px (= window points): noDrag — interactive elements (buttons, fields, links, selects, [data-act],
// …) and scroll-bar knobs that touch a drag zone; drag — extra blank header areas (#wtop, .tbar, the sidebar above the edition
// switch). Interactive elements inside those rects stay noDrag, so the host's hit test is: noDrag wins, then drag / ring.
// Re-reported (throttled) on resize, 'orbit:layout', route changes, scrolling and DOM changes of #win / #overlay / #modal.
(function nativeDrag() {
  const flag = window.__ORBIT_NATIVE__;
  if (!flag || /[?&]surface=/.test(location.search || '')) return;
  const RING = 8, TITLE = 38, SB = 16;
  const INTERACTIVE = 'button,a[href],input,textarea,select,label,summary,[role="button"],[role="slider"],[role="tab"],[role="switch"],[role="checkbox"],[role="radio"],[role="option"],[role="menuitem"],[contenteditable=""],[contenteditable="true"],[tabindex]:not([tabindex="-1"]),[data-act]';
  const handler = () => { try { return window.webkit.messageHandlers.orbit; } catch (e) { return null; } };
  let last = '', timer = 0, pending = false;
  const box = (r) => [Math.floor(r.left), Math.floor(r.top), Math.ceil(r.width), Math.ceil(r.height)];
  const meets = (r, z) => r.left < z.left + z.width && r.left + r.width > z.left && r.top < z.top + z.height && r.top + r.height > z.top;
  function shown(el, r) {
    if (r.width < 1 || r.height < 1) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.pointerEvents !== 'none' && +cs.opacity > 0.01;
  }
  function measure() {
    const W = window.innerWidth, H = window.innerHeight;
    const drag = [];
    const add = (el) => { if (!el) return; const r = el.getBoundingClientRect(); if (shown(el, r)) drag.push(r); };
    add(document.getElementById('wtop'));
    document.querySelectorAll('#win .tbar').forEach(add);
    const side = document.getElementById('side'), sw = side && side.querySelector('.edsw');
    if (side && sw) {
      const a = side.getBoundingClientRect(), b = sw.getBoundingClientRect();
      if (b.top - a.top > 4 && shown(side, a)) drag.push({ left: a.left, top: a.top, width: a.width, height: b.top - a.top });
    }
    const zones = [{ left: 0, top: 0, width: W, height: TITLE }, { left: 0, top: 0, width: RING, height: H }, { left: W - RING, top: 0, width: RING, height: H },
      { left: 0, top: H - RING, width: W, height: RING }].concat(drag);
    const noDrag = [];
    document.querySelectorAll(INTERACTIVE).forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width < 1 || !zones.some((z) => meets(r, z)) || !shown(el, r)) return;
      noDrag.push(box(r));
    });
    // scroll bars of scrollers that reach an edge (overlay scroll bars sit on the scroller's right / bottom inner edge)
    document.querySelectorAll('#win *, #overlay *, #modal *').forEach((el) => {
      const sy = el.scrollHeight > el.clientHeight + 1, sx = el.scrollWidth > el.clientWidth + 1;
      if (!sy && !sx) return;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      // only the knob (± 8px) keeps its clicks, so the rest of the edge ring beside a long scroller still drags the window
      if (sy && /(auto|scroll)/.test(cs.overflowY) && r.right >= W - RING - SB) {
        const len = Math.max(32, r.height * el.clientHeight / el.scrollHeight), at = r.top + (r.height - len) * el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
        noDrag.push(box({ left: r.right - SB, top: at - 8, width: SB, height: len + 16 }));
      }
      if (sx && /(auto|scroll)/.test(cs.overflowX) && r.bottom >= H - RING - SB) {
        const len = Math.max(32, r.width * el.clientWidth / el.scrollWidth), at = r.left + (r.width - len) * el.scrollLeft / Math.max(1, el.scrollWidth - el.clientWidth);
        noDrag.push(box({ left: at - 8, top: r.bottom - SB, width: len + 16, height: SB }));
      }
    });
    return { noDrag: noDrag.slice(0, 400), drag: drag.map(box) };
  }
  function report() {
    timer = 0; pending = false;
    const h = handler(); if (!h) return;
    let m; try { m = measure(); } catch (e) { return; }
    const sig = JSON.stringify(m); if (sig === last) return;
    last = sig;
    try { h.postMessage(Object.assign({ type: 'dragRegions' }, m)); } catch (e) { /* host gone */ }
  }
  function soon() {
    if (pending) return; pending = true;
    timer = setTimeout(() => requestAnimationFrame(report), 200);
  }
  window.addEventListener('resize', soon);
  window.addEventListener('orbit:layout', soon);
  window.addEventListener('hashchange', soon);
  window.addEventListener('scroll', soon, true);
  window.addEventListener('transitionend', soon, true);
  window.addEventListener('load', soon);
  const start = () => {
    if (typeof MutationObserver === 'function') {
      const mo = new MutationObserver(soon);
      ['win', 'overlay', 'modal', 'set'].forEach((id) => { const el = document.getElementById(id); if (el) mo.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden'] }); });
    }
    soon();
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
