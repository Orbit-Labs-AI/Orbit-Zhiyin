/* ============ regions: parts of a window that refresh on their own ============
   A page (or the shell) is built from regions: one root element each, tagged data-region="<key>", with the data it reads
   declared as deps. render() rebuilds #main only when the view changes (first render, route, edition); on a page listed in
   RG.pages every other render() — a filter click, a live frame, a feed arrival — re-evaluates the regions instead: a region
   whose dep values are unchanged is skipped, a changed one rebuilds its HTML and, if that differs, is morphed in place
   (rgMorph keeps every unchanged node: scroll boxes, focus, selection, hover, running animations, open menus anchored to
   it). Pages not yet listed keep the page-level render (with the scroll / focus restore of 25-nav.js).
     region(key, deps, fn, opt)  → HTML of fn() with data-region="key" on its root; registers the region. fn must read state
                                   fresh (never close over locals of the page function): it runs again on every refresh.
                                   opt.after(el, first) runs once the element is in the DOM and after every change
                                   (mount charts here); opt.wrap: true wraps several roots in a display:contents box.
     deps                        → strings or functions. 'S.a.b' (state path; Sets / Maps compare by content), 'filters'
                                   (every filter sel() reads), 'facts' (the spine: ALL / AG / PJ), 'feed:<route>' (that
                                   route's LV.feed state), 'live' (connection / analysis status), 'job' (import progress
                                   frames), 'tl' (any TandemLive change), any name bumped with RG.bump(name), or a function
                                   whose return value is compared. '*' means: re-evaluate on every pass.
     RG.refresh(keys, why)       → invalidate dep keys (array / string / '*'); refreshed regions are batched per frame (rAF,
                                   120 ms fallback). RG.refreshNow(keys, why) does it synchronously.
     RG.bump(name, why)          → bump a named version and refresh the regions depending on it.
     RG.memo(name, fn)           → fn() once per pass (shared derived data of several regions: sel(), stats(), …).
     RG.prep(route, fn)          → run fn before each region pass of that route (live feed sync, slate loading).
     rgPut(el, html)             → morph el's children to html (the shell: menu bar, title row, sidebar).
   Debugging: window.__renderCount counts full renders, window.__regionRenders[key] region refreshes, ?debug=render logs
   both with the invalidation source. */
const RG = {
  defs: new Map(), last: new Map(), pages: new Set(), preps: {}, vers: {}, depFns: {}, hooks: [],
  pending: null, only: null, why: [], raf: 0, timer: 0, pass: 0, memos: new Map(), afterQ: [], view: null, busy: false
};
window.__regionRenders = {};
const RG_DEBUG = (() => { try { return new URLSearchParams(location.search).get('debug') === 'render'; } catch (e) { return false; } })();
// every filter sel() / pass() reads (15-derive.js) + the sources that change which agents count
const RG_ALIAS = { filters: ['S.range', 'S.agents', 'S.project', 'S.topic', 'S.outcome', 'S.fric', 'S.hour', 'S.srcOff'] };
function rgExpand(deps) {
  const out = [];
  [].concat(deps == null ? '*' : deps).forEach((d) => { if (typeof d === 'string' && RG_ALIAS[d]) RG_ALIAS[d].forEach((x) => out.push(x)); else out.push(d); });
  return out;
}
const rgJSON = (v) => { try { return JSON.stringify(v, (k, x) => (x instanceof Set ? Array.from(x).sort() : x instanceof Map ? Array.from(x.keys()).sort() : x)); } catch (e) { return String(Math.random()); } };
function rgDepVal(d) {
  if (typeof d === 'function') { try { return rgJSON(d()); } catch (e) { return 'err'; } }
  if (d === '*') return String(RG.pass);
  if (d.slice(0, 2) === 'S.') { let v = S; d.slice(2).split('.').forEach((k) => { v = v == null ? v : v[k]; }); return rgJSON(v); }
  if (d.slice(0, 5) === 'feed:') {
    if (typeof LV === 'undefined' || !LV.live) return '';
    return (LV.feeds[d.slice(5)] || []).map((f) => f.state + '@' + f.stamp).join(',');
  }
  if (d === 'facts') return (typeof LV !== 'undefined' ? LV.rev : 0) + '/' + ALL.length + '/' + AG.length + '/' + PJ.length + '/' + (RG.vers.facts || 0);
  if (RG.depFns[d]) { try { return rgJSON(RG.depFns[d]()); } catch (e) { return 'err'; } }
  return String(RG.vers[d] || 0);
}
const rgSig = (def) => def.deps.map(rgDepVal).join('\u0001');
// one root element carrying data-region; an empty region keeps a hidden placeholder so it can appear later in place
function rgTag(key, html, wrap) {
  html = String(html == null ? '' : html).trim();
  const attr = ' data-region="' + key + '"';
  if (!html) return '<i' + attr + ' hidden></i>';
  if (wrap || !/^<[a-zA-Z]/.test(html)) return '<div' + attr + ' class="rg-wrap" style="display:contents">' + html + '</div>';
  return html.replace(/^<([a-zA-Z][\w-]*)/, (m, t) => '<' + t + attr);
}
function region(key, deps, fn, opt) {
  opt = opt || {};
  const def = { key, deps: rgExpand(deps), fn, after: opt.after || null, wrap: !!opt.wrap };
  RG.defs.set(key, def);
  const sig = rgSig(def);
  const html = rgTag(key, fn(), def.wrap);
  RG.last.set(key, { sig, html });
  if (def.after) RG.afterQ.push([key, true]);
  return html;
}
RG.memo = (name, fn) => { if (!RG.memos.has(name)) RG.memos.set(name, fn()); return RG.memos.get(name); };
RG.begin = () => { RG.pass++; RG.memos.clear(); };
RG.prep = (route, fn) => { (RG.preps[route] = RG.preps[route] || []).push(fn); };
RG.dep = (name, fn) => { RG.depFns[name] = fn; };
RG.el = (key) => document.querySelector('[data-region="' + key + '"]');
// run the queued after(el, first) hooks whose element is now in the DOM (full render: after #main was filled)
RG.runAfter = () => {
  const q = RG.afterQ; RG.afterQ = [];
  q.forEach(([key, first]) => { const def = RG.defs.get(key), el = RG.el(key); if (def && def.after && el) { try { def.after(el, first); } catch (e) { console.error(e); } } });
};

/* ---------- morph: bring a live element in line with freshly parsed markup, keeping identical nodes ---------- */
// keyed children (data-region / id / data-key / data-vz) are matched by key, the rest by position and tag. A chart box
// ([data-vz]) is owned by vizkit: its attributes and contents are left alone (the region's after() re-mounts it).
const rgKey = (n) => (n.nodeType === 1 ? n.getAttribute('data-region') || n.id || n.getAttribute('data-key') || n.getAttribute('data-vz') || null : null);
const rgSame = (a, b) => a.nodeType === b.nodeType && (a.nodeType !== 1 || a.tagName === b.tagName);
function rgAttrs(from, to) {
  Array.from(from.attributes).forEach((a) => { if (!to.hasAttribute(a.name)) from.removeAttribute(a.name); });
  Array.from(to.attributes).forEach((a) => { if (from.getAttribute(a.name) !== a.value) from.setAttribute(a.name, a.value); });
  if (from.tagName === 'INPUT') {
    if (from.type === 'checkbox' || from.type === 'radio') { const c = to.hasAttribute('checked'); if (from.checked !== c) from.checked = c; }
    else if (document.activeElement !== from) { const v = to.getAttribute('value') || ''; if (from.value !== v) from.value = v; }
  }
}
function rgMorph(from, to) {
  if (from.nodeType !== 1) { if (from.nodeValue !== to.nodeValue) from.nodeValue = to.nodeValue; return from; }
  if (!rgSame(from, to)) { from.replaceWith(to); return to; }
  if (from.hasAttribute('data-vz') && from.getAttribute('data-vz') === to.getAttribute('data-vz')) return from;
  rgAttrs(from, to);
  if (from.tagName === 'TEXTAREA') { if (document.activeElement !== from && from.value !== to.value) from.value = to.value; return from; }
  rgKids(from, to);
  return from;
}
function rgKids(from, to) {
  const keyed = new Map();
  for (let c = from.firstChild; c; c = c.nextSibling) { const k = rgKey(c); if (k && !keyed.has(k)) keyed.set(k, c); }
  let cur = from.firstChild;
  Array.from(to.childNodes).forEach((t) => {
    const k = rgKey(t); let m = null;
    if (k) { m = keyed.get(k) || null; if (m && !rgSame(m, t)) m = null; if (m) keyed.delete(k); }
    else {
      // the next unkeyed node of the same kind, looking at most 3 nodes ahead (an inserted / removed sibling)
      let c = cur, n = 0;
      while (c && n < 4) { if (!rgKey(c) && rgSame(c, t)) { m = c; break; } c = c.nextSibling; n++; }
    }
    if (m) { if (m === cur) cur = cur.nextSibling; else from.insertBefore(m, cur); rgMorph(m, t); }
    else from.insertBefore(t, cur);
  });
  while (cur) { const n = cur.nextSibling; from.removeChild(cur); cur = n; }
}
const rgParse = (html) => { const t = document.createElement('template'); t.innerHTML = html; return t.content; };
// el's children := html (first call: plain innerHTML)
function rgPut(el, html) {
  if (!el) return;
  if (!el.firstChild) { el.innerHTML = html; return; }
  rgKids(el, rgParse(html));
}
// a region root := html (one root element)
function rgSwap(el, html) {
  const frag = rgParse(html); const to = frag.firstElementChild;
  if (!to) { el.replaceWith(frag); return null; }
  return rgMorph(el, to);
}

/* ---------- refresh ---------- */
function rgMatch(def, keys) {
  if (keys === '*') return true;
  return def.deps.some((d) => d === '*' || typeof d === 'function' || keys.has(d) || (typeof d === 'string' && Array.from(keys).some((k) => d.indexOf(k + '.') === 0 || k.indexOf(d + '.') === 0)));
}
function rgFlushKeys(keys, why) {
  if (RG.busy) { RG.refresh(keys === '*' ? '*' : Array.from(keys), why); return 0; }
  RG.busy = true; let n = 0;
  try {
    RG.begin();
    (RG.preps[S.route] || []).forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
    Array.from(RG.defs.keys()).forEach((key) => {
      const def = RG.defs.get(key); if (!def) return;
      const el = RG.el(key);
      if (!el) { RG.defs.delete(key); RG.last.delete(key); return; }
      if (!rgMatch(def, keys)) return;
      const last = RG.last.get(key) || {};
      const sig = rgSig(def);
      if (sig === last.sig) return;
      const html = rgTag(key, def.fn(), def.wrap);
      RG.last.set(key, { sig, html });
      // same markup but new inputs: the region's after() still runs (a chart box is empty markup; its data lives in after)
      if (html === last.html) { if (def.after) RG.afterQ.push([key, false]); return; }
      const old = $$('[data-count]', el).map((x) => x.dataset.count);
      const nel = rgSwap(el, html) || RG.el(key);
      n++; window.__regionRenders[key] = (window.__regionRenders[key] || 0) + 1;
      if (RG_DEBUG) console.debug('[region]', key, '←', why || (keys === '*' ? '*' : Array.from(keys).join(',')));
      if (nel) {
        RG.hooks.forEach((fn) => { try { fn(nel, key, old); } catch (e) { console.error(e); } });
        if (def.after) RG.afterQ.push([key, false]);
      }
    });
    RG.runAfter();
  } finally { RG.busy = false; }
  if (n && typeof window !== 'undefined') window.dispatchEvent(new CustomEvent('tandem:regions', { detail: { n } }));
  return n;
}
RG.refresh = function (keys, why) {
  if (keys === '*' || RG.pending === '*') RG.pending = '*';
  else { RG.pending = RG.pending || new Set(); (keys instanceof Set ? Array.from(keys) : [].concat(keys)).forEach((k) => RG.pending.add(k)); }
  if (why) RG.why.push(why);
  if (RG.raf || RG.timer) return;
  if (typeof requestAnimationFrame === 'function') RG.raf = requestAnimationFrame(RG.flush);
  RG.timer = setTimeout(RG.flush, 120);   // rAF is paused in a hidden WKWebView
};
RG.flush = function () {
  if (RG.raf) { cancelAnimationFrame(RG.raf); RG.raf = 0; }
  if (RG.timer) { clearTimeout(RG.timer); RG.timer = 0; }
  const keys = RG.pending; RG.pending = null; const why = RG.why.join(' · '); RG.why = [];
  return keys ? rgFlushKeys(keys, why) : 0;
};
RG.refreshNow = (keys, why) => rgFlushKeys(keys === '*' ? '*' : new Set(keys instanceof Set ? keys : [].concat(keys)), why);
RG.bump = (name, why) => { RG.vers[name] = (RG.vers[name] || 0) + 1; RG.refresh([name], why || name); };
// the current page is region-built and already on screen: render() may refresh it instead of rebuilding #main
RG.viewKey = () => S.ed + '|' + S.route;
RG.canRefresh = () => RG.pages.has(S.route) && RG.view === RG.viewKey() && !!document.getElementById('content');
