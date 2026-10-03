"use strict";
/* ============ utilities ============ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = (n) => Math.round(n).toLocaleString('en-US');
const f1 = (n) => (Math.round(n * 10) / 10).toFixed(1);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sum = (arr, fn) => arr.reduce((a, x) => a + fn(x), 0);
function rng(seed) { let s = seed | 0; return () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function hash(str) { let h = 2166136261; for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); } return h | 0; }
// UI preferences. Browser: localStorage 'orbit-demo:*' only. Native shell with the "prefs" feature: the WKWebView store is
// non-persistent (and the gateway port changes every launch), so the host keeps <data home>/ui-prefs.json, injects it as
// window.__ORBIT_PREFS__ at document start, and store.get reads that; store.set still writes localStorage and also posts
// {type:'prefs', set:{key: value|null}} (merged per key, debounced; null deletes). Surfaces share one file and only send the
// keys they changed; 'orbit:prefs' carries other surfaces' changes into this page's copy.
const store = (() => {
  const LS = 'orbit-demo:';
  const handler = () => { try { return window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.orbit; } catch (e) { return null; } };
  const nat = window.__ORBIT_NATIVE__;
  const p0 = window.__ORBIT_PREFS__;
  const native = !!(nat && typeof nat === 'object' && Array.isArray(nat.features) && nat.features.indexOf('prefs') >= 0 && handler());
  const cache = native ? Object.assign({}, p0 && typeof p0 === 'object' && !Array.isArray(p0) ? p0 : {}) : null;
  let pending = null, timer = null;
  function flush() {
    clearTimeout(timer); timer = null;
    if (!pending) return;
    const set = pending; pending = null;
    try { handler().postMessage({ type: 'prefs', set }); } catch (e) { /* host gone */ }
  }
  if (native) {
    window.addEventListener('orbit:prefs', (e) => {
      const set = (e && e.detail && e.detail.set) || {};
      Object.keys(set).forEach((k) => { if (set[k] == null) delete cache[k]; else cache[k] = set[k]; });
    });
    window.addEventListener('pagehide', flush);
  }
  return {
    native,
    get(k, d) {
      if (native) return Object.prototype.hasOwnProperty.call(cache, k) ? cache[k] : d;
      try { const v = localStorage.getItem(LS + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
    },
    set(k, v) {
      try { localStorage.setItem(LS + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ }
      if (!native) return;
      if (v == null) delete cache[k]; else cache[k] = JSON.parse(JSON.stringify(v));
      (pending = pending || {})[k] = v == null ? null : cache[k];
      clearTimeout(timer); timer = setTimeout(flush, 150);
    },
    flush
  };
})();
const I = {
  overview: 'M4 4h6v8H4zM14 4h6v5h-6zM14 13h6v7h-6zM4 16h6v4H4z',
  persona: 'M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2M9 15c1.5 1.3 4.5 1.3 6 0M9 10h.01M15 10h.01',
  sessions: 'M3 12h4l3-7 4 14 3-7h4',
  tools: 'M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.4 2.4-2.6-.4-.4-2.6z',
  projects: 'M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z',
  sentiment: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M8.5 14a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01',
  recs: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.2h5c0-.9.4-1.7 1.1-2.2A6 6 0 0 0 12 3z',
  library: 'M21 8l-9-5-9 5 9 5zM3 8v8l9 5 9-5V8M12 13v8',
  studio: 'M4 20l10-10M14.5 4l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9zM19 11l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z',
  search: 'M10.5 4a6.5 6.5 0 1 0 0 13a6.5 6.5 0 1 0 0-13zM20 20l-4.6-4.6',
  sidebar: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM9.5 5v14',
  shield: 'M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5c-4.3-1.2-7.5-4.9-7.5-9.5V6zM9 12l2 2 4-4',
  sync: 'M20 11a8 8 0 0 0-14.6-4.4M4 4v3.6h3.6M4 13a8 8 0 0 0 14.6 4.4M20 20v-3.6h-3.6',
  settings: 'M4 7h9M17 7h3M4 17h3M11 17h9M15 5v4M9 15v4',
  share: 'M12 15V3M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7',
  spark: 'M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  chev: 'M6 9l6 6 6-6',
  chevr: 'M9 6l6 6-6 6',
  plus: 'M12 5v14M5 12h14',
  x: 'M6 6l12 12M18 6L6 18',
  bot: 'M7 8h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3zM12 4v4M9.5 14h.01M14.5 14h.01',
  okc: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M8 12.5l2.7 2.7L16 10',
  alert: 'M12 4L2.5 20h19zM12 10v4.5M12 17.5h.01',
  half: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 3v18',
  xc: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M9 9l6 6M15 9l-6 6',
  clock: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 7.5V12l3 2',
  bolt: 'M13 3L5 13.5h6.5L10.5 21 19 10.5h-6.5z',
  book: 'M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6M9 10.5h4',
  rule: 'M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8zM14 3v5h5M8.5 13h7M8.5 16.5h5',
  file: 'M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8zM14 3v5h5',
  gauge: 'M3.5 17a8.5 8.5 0 1 1 17 0M12 17l4-5',
  branch: 'M6 4a2 2 0 1 0 0 4a2 2 0 1 0 0-4M6 16a2 2 0 1 0 0 4a2 2 0 1 0 0-4M18 6a2 2 0 1 0 0 4a2 2 0 1 0 0-4M6 8v8M18 10c0 3.5-2.5 5-6 5H8',
  puzzle: 'M9 4.5a2 2 0 0 1 4 0V6h3.5a1 1 0 0 1 1 1v3.5h1.5a2 2 0 0 1 0 4h-1.5V18a1 1 0 0 1-1 1H13v-1.5a2 2 0 0 0-4 0V19H5.5a1 1 0 0 1-1-1v-3.5H6a2 2 0 0 0 0-4H4.5V7a1 1 0 0 1 1-1H9z',
  plug: 'M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4',
  term: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 9.5l3 2.5-3 2.5M12.5 15H17',
  copy: 'M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM16 9V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3',
  down: 'M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14',
  play: 'M7 4.5v15l12-7.5z',
  pause: 'M8 5v14M16 5v14',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  info: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 11v5M12 7.5h.01',
  grid: 'M4 5h16v14H4zM4 10h16M4 14.5h16M10 5v14',
  chart: 'M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3',
  grad: 'M2.5 9.5L12 5l9.5 4.5L12 14zM6.5 11.5v4.5c3 2.3 8 2.3 11 0v-4.5M21.5 9.5V15',
  bell: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15zM10 20.5a2.2 2.2 0 0 0 4 0',
  lock: 'M6.5 11h11a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 18.5v-6A1.5 1.5 0 0 1 6.5 11zM8 11V7.5a4 4 0 0 1 8 0V11',
  eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6a3 3 0 1 0 0-6',
  filter: 'M4 5h16l-6.2 7.6V19l-3.6 1.8v-8.2z',
  db: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  collapse: 'M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7',
  minus: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0M8 12h8',
  undo: 'M9 14L4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11',
  ext: 'M14 4h6v6M20 4l-8.5 8.5M18 13.5V19a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5.5',
  burger: 'M4 7h16M4 12h16M4 17h16',
  flask: 'M9 3h6M10 3v6.2L4.7 18.4A1.5 1.5 0 0 0 6 20.7h12a1.5 1.5 0 0 0 1.3-2.3L14 9.2V3M7.5 15h9',
  slash: 'M12 7a5 5 0 1 0 0 10a5 5 0 1 0 0-10M5 19L19 5'
};
// unknown names (live data: e.g. recommend/narrate.py emits icon 'flow') fall back instead of writing d="undefined"
const IC_ALIAS = { flow: 'branch' };
function ic(n, s, st) { return '<svg class="ico" width="' + (s || 16) + '" height="' + (s || 16) + '" viewBox="0 0 24 24" aria-hidden="true"' + (st ? ' style="' + st + '"' : '') + '><path d="' + (I[n] || I[IC_ALIAS[n]] || I.rule) + '"/></svg>'; }
// 菜单栏状态项 GLYPH 与 App 图标 appIcon(px) 用官方 logo 矢量，见 01-brand.js（tools/brand-icon.mjs 生成）

