/* ============ navigation & render ============ */
// order = the Advance「洞察」sidebar group; ⌥1…⌥9, the 窗口 menu and the palette's 页面 rows all follow it
const ROUTES = [['overview', '概览'], ['persona', '协作人格'], ['sentiment', '情绪语义'], ['projects', '项目习惯'], ['sessions', '会话轨迹'], ['tools', '工具调用'], ['recs', '优化建议'], ['library', '资源库'], ['studio', '生成工坊']];
const PAGES = {};
// RENDER_HOOKS: fn(mainEl, entered) after every page render; entered = true only when go() changed the page (route enter
// motion runs once per visit, not on every filter re-render). go() also translates a route to the current edition
// (edRoute in 26-edition.js), so links such as go('persona') land on the Lite page while Lite is active.
const RENDER_HOOKS = [];
let ROUTE_ENTER = false;
function go(route, keepScroll) {
  edFollow(route); route = edRoute(route);
  if (!PAGES[route]) route = S.ed === 'lite' ? 'l-home' : 'overview';
  if (route !== S.route || !keepScroll) ROUTE_ENTER = true;
  S.route = route; S.sideOver = false; S.winGone = false; closeDD(); tipOff();
  edRemember(route);   // App: the page to come back to next launch (26-edition.js)
  try { history.replaceState(null, '', '#' + route); } catch (e) { /* sandboxed */ }
  // a fresh visit starts the page and each of its panes (88-panes.css) at the top instead of restoring the last scroll
  if (!keepScroll) UI_SCROLLED.forEach((el) => { if (!el.closest('#side')) UI_SCROLLED.delete(el); });
  render();
  if (!keepScroll) { const c = $('#content'); if (c) c.scrollTop = 0; }
}
/* Re-render keeps what the user was doing: every box scrolled inside the sidebar or the page (not only #content — the
   sidebar list, tables and lists with their own scroll) and the focused field (caret and value) are put back on the
   rebuilt DOM, found again by their child-index path (the live strip, re-inserted after each render, is not counted).
   window.__renderCount counts full renders (?debug=render also logs them) so tests can tell a frame patch from a render. */
const UI_SCROLLED = new Set();
['#side', '#main'].forEach((sel) => { const r = $(sel); if (r) r.addEventListener('scroll', (e) => { if (e.target && e.target.nodeType === 1) UI_SCROLLED.add(e.target); }, true); });
const uiKids = (el) => Array.from(el.children).filter((c) => !(c.dataset && c.dataset.tl === 'strip'));
function uiPath(el, root) { const p = []; while (el && el !== root) { const up = el.parentElement; if (!up) return null; p.unshift(uiKids(up).indexOf(el)); el = up; } return el === root ? p : null; }
function uiAt(root, p) { let el = root; for (const i of p) { el = el && uiKids(el)[i]; if (!el) return null; } return el; }
function uiSnap() {
  const roots = [$('#side'), $('#main')], out = { sc: [], f: null };
  UI_SCROLLED.forEach((el) => {
    if (!el.isConnected) { UI_SCROLLED.delete(el); return; }
    if (!el.scrollTop && !el.scrollLeft) return;
    const ri = roots.findIndex((r) => r && r.contains(el)); if (ri < 0) return;
    const p = uiPath(el, roots[ri]); if (p) out.sc.push({ ri, p, tag: el.tagName, cls: el.className, t: el.scrollTop, l: el.scrollLeft });
  });
  const a = document.activeElement;
  if (a && /^(INPUT|TEXTAREA)$/.test(a.tagName)) {
    const ri = roots.findIndex((r) => r && r.contains(a));
    if (ri >= 0) { const p = uiPath(a, roots[ri]); let s0 = null, s1 = null; try { s0 = a.selectionStart; s1 = a.selectionEnd; } catch (e) { /* type without caret */ } if (p) out.f = { ri, p, tag: a.tagName, id: a.id, v: a.value, s0, s1 }; }
  }
  return out;
}
function uiRestore(snap) {
  const roots = [$('#side'), $('#main')];
  snap.sc.forEach((x) => { const el = roots[x.ri] && uiAt(roots[x.ri], x.p); if (el && el.tagName === x.tag && el.className === x.cls) { el.scrollTop = x.t; el.scrollLeft = x.l; UI_SCROLLED.add(el); } });
  const f = snap.f; if (!f || (document.activeElement && document.activeElement !== document.body && document.activeElement.isConnected)) return;
  const el = (f.id && document.getElementById(f.id)) || (roots[f.ri] && uiAt(roots[f.ri], f.p));
  if (!el || el.tagName !== f.tag) return;
  if (el.value !== f.v && !el.value) el.value = f.v;
  el.focus({ preventScroll: true });
  try { if (f.s0 != null) el.setSelectionRange(f.s0, f.s1); } catch (e) { /* type without caret */ }
}
/* uiKeep(root) → restore(): the same promise for a box that rebuilds itself outside render() — the settings window
   (renderSet), the first-run overlay (drawOB) — every scrolled element under root (found again by child-index path, tag
   and class) and the focused field with its caret come back after the rebuild. */
function uiKeep(root) {
  if (!root || root.hidden) return () => {};
  const sc = [];
  root.querySelectorAll('*').forEach((el) => { if (el.scrollTop || el.scrollLeft) { const p = uiPath(el, root); if (p) sc.push({ p, tag: el.tagName, cls: el.className, t: el.scrollTop, l: el.scrollLeft }); } });
  const a = document.activeElement; let f = null;
  if (a && root.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) { const p = uiPath(a, root); let s0 = null, s1 = null; try { s0 = a.selectionStart; s1 = a.selectionEnd; } catch (e) { /* no caret */ } if (p) f = { p, tag: a.tagName, id: a.id, v: a.value, s0, s1 }; }
  return () => {
    sc.forEach((x) => { const el = uiAt(root, x.p); if (el && el.tagName === x.tag && el.className === x.cls) { el.scrollTop = x.t; el.scrollLeft = x.l; } });
    const cur = document.activeElement;
    if (!f || (cur && cur !== document.body && cur.isConnected)) return;   // focus survived (or moved on purpose): leave it
    const el = (f.id && document.getElementById(f.id)) || uiAt(root, f.p);
    if (!el || el.tagName !== f.tag || !root.contains(el)) return;
    if (el.value !== f.v && !el.value) el.value = f.v;
    el.focus({ preventScroll: true });
    try { if (f.s0 != null) el.setSelectionRange(f.s0, f.s1); } catch (e) { /* no caret */ }
  };
}
// an open dropdown (#dd) whose anchor a render replaced: hang it from the anchor's successor (same path, same act) so it
// stays open where it was instead of floating over a detached chip
function uiDDSnap() {
  if (typeof DD === 'undefined' || !DD || !DD.anchor) return null;
  const roots = [$('#side'), $('#main'), $('#set')]; const a = DD.anchor;
  const ri = roots.findIndex((r) => r && r.contains(a)); if (ri < 0) return null;
  const p = uiPath(a, roots[ri]); return p ? { dd: DD, ri, p, act: a.dataset ? a.dataset.act : null } : null;
}
function uiDDRestore(x) {
  if (!x || DD !== x.dd || x.dd.anchor.isConnected) return;
  const roots = [$('#side'), $('#main'), $('#set')];
  let el = roots[x.ri] && uiAt(roots[x.ri], x.p);
  if ((!el || (x.act && el.dataset.act !== x.act)) && x.act) el = roots[x.ri] && roots[x.ri].querySelector('[data-act="' + x.act + '"]');
  if (!el) return;
  x.dd.anchor = el;
  if (typeof ddPlace === 'function') ddPlace(el, x.dd.align);
}
const UI_DEBUG = (() => { try { return new URLSearchParams(location.search).get('debug') === 'render'; } catch (e) { return false; } })();
window.__renderCount = 0;
function render() {
  window.__renderCount++; if (UI_DEBUG) console.debug('[render]', window.__renderCount, S.route);
  const snap = uiSnap(); const dds = uiDDSnap();
  agentSync();
  applyWin(); renderMbar(); renderWtop(); renderSide(); renderMain(); renderWidgets(); renderHud();
  if (S.pop) renderPop(); else $('#pop').hidden = true;
  if (!$('#set').hidden) renderSet();
  $('#win').classList.toggle('gone', S.winGone);
  // the window rect cannot change while the page renders (stageSize is cached, 22-window.js): re-place only the dependants
  // (toast / sheet / overlay / popover / HUD) against the new content instead of a second applyWin()
  placeDeps();
  uiRestore(snap); uiDDRestore(dds);
  paneSync();
  if (window.__lvRendered) window.__lvRendered();
}
function renderMain() {
  const m = $('#main'); const c = $('#content'); const top = c ? c.scrollTop : 0;
  m.innerHTML = PAGES[S.route]();
  const nc = $('#content'); if (nc) nc.scrollTop = top;
  tbarFit();
  if (PAGES[S.route].after) PAGES[S.route].after();
  const entered = ROUTE_ENTER; ROUTE_ENTER = false;
  RENDER_HOOKS.forEach((fn) => { try { fn(m, entered); } catch (e) { console.error(e); } });
}
/* toolbar overflow, in order: the search field collapses to its icon as soon as the meta text would be clipped; the meta
   then shrinks (ellipsis); items that still do not fit move (right to left) into a » popover. The page title never
   shrinks — a clipped title counts as overflow too (its .grow box hides what sticks out). Runs after every page render
   and on 'orbit:layout' (window resize, sidebar toggle). */
function tbarFit() {
  const tb = $('#main .tbar'); if (!tb) return;
  const tr = tb.querySelector('.tright'); if (!tr) return;
  let more = tb.querySelector('.tmore');
  if (more) { const pop = more.querySelector('.tmore-pop'); while (pop.firstChild) tr.appendChild(pop.firstChild); more.remove(); }
  const ts = tb.querySelector('.tsearch'), meta = tb.querySelector('.meta'), grow = tb.querySelector('.grow');
  // plain-text meta (or a single plain <span> inside it) can be shortened part by part
  const mt = !meta ? null : !meta.children.length ? meta : meta.children.length === 1 && !meta.firstElementChild.children.length && meta.textContent === meta.firstElementChild.textContent ? meta.firstElementChild : null;
  if (meta) meta.hidden = false;
  if (mt) { if (mt.dataset.full == null) mt.dataset.full = mt.textContent; mt.textContent = mt.dataset.full; }
  const clipped = () => meta && meta.scrollWidth > meta.clientWidth + 0.5;
  if (ts && !ts.dataset.ico) { ts.classList.remove('ico-only'); if (clipped()) ts.classList.add('ico-only'); }
  // a clipped meta drops whole trailing「 · 」parts instead of cutting a date in half; if even the first part does not fit
  // the meta is hidden. Either way the full line stays in the tooltip (on the meta, or on the title when the meta is gone).
  const h1 = tb.querySelector('h1'); if (h1) delete h1.dataset.tip;
  if (mt) {
    const parts = mt.dataset.full.split(' · ');
    while (clipped() && parts.length > 1) { parts.pop(); mt.textContent = parts.join(' · '); }
    if (clipped()) { meta.hidden = true; if (h1) h1.dataset.tip = mt.dataset.full; }
    if (mt.textContent !== mt.dataset.full) meta.dataset.tip = mt.dataset.full; else delete meta.dataset.tip;
  }
  const fits = () => tb.scrollWidth <= tb.clientWidth + 0.5 && (!grow || grow.scrollWidth <= grow.clientWidth + 0.5);
  if (fits() || !tr.children.length) return;
  more = document.createElement('div'); more.className = 'tmore';
  more.innerHTML = '<button type="button" class="ib" data-act="tmore" aria-label="更多工具栏项" aria-expanded="false" data-tip="更多工具栏项">' + ic('more') + '</button><div class="tmore-pop" hidden></div>';
  tr.after(more);
  const pop = more.querySelector('.tmore-pop');
  while (!fits() && tr.children.length) pop.prepend(tr.lastElementChild);
}
window.addEventListener('orbit:layout', tbarFit);
/* menu bar: Apple menu, app menus (never fold with the window width), status items: demo (flask) · Orbit · control centre · Wi-Fi · battery · clock */
const APPLE = '<svg width="14" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M16.37 12.7c-.03-2.6 2.13-3.86 2.23-3.92-1.22-1.78-3.11-2.02-3.78-2.05-1.61-.16-3.14.95-3.96.95-.82 0-2.08-.93-3.42-.9-1.76.03-3.38 1.02-4.29 2.6-1.83 3.17-.47 7.87 1.31 10.44.87 1.26 1.91 2.67 3.27 2.62 1.31-.05 1.81-.85 3.4-.85 1.59 0 2.03.85 3.42.82 1.41-.03 2.31-1.28 3.17-2.55 1-1.46 1.41-2.87 1.43-2.95-.03-.01-2.75-1.05-2.78-4.21zM13.76 5.05c.72-.88 1.21-2.1 1.08-3.31-1.04.04-2.3.69-3.05 1.57-.67.78-1.26 2.02-1.1 3.21 1.16.09 2.35-.59 3.07-1.47z"/></svg>';
const SYS_ICONS = '<span class="sysicon" aria-hidden="true"><svg width="16" height="12" viewBox="0 0 16 12" fill="none" stroke="currentColor" stroke-width="1.1"><rect x=".55" y=".55" width="14.9" height="4.9" rx="2.45"/><circle cx="3" cy="3" r="1.5" fill="currentColor" stroke="none"/><rect x=".55" y="6.55" width="14.9" height="4.9" rx="2.45"/><circle cx="13" cy="9" r="1.5" fill="currentColor" stroke="none"/></svg></span>' +
  '<span class="sysicon" aria-hidden="true"><svg width="16" height="12" viewBox="0 0 24 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M2.5 7a14 14 0 0 1 19 0M5.5 10.5a9.5 9.5 0 0 1 13 0M8.8 14a5 5 0 0 1 6.4 0"/></svg></span>' +
  '<span class="sysicon" aria-hidden="true" style="width:32px"><svg width="26" height="12" viewBox="0 0 26 12"><rect x=".75" y=".75" width="21.5" height="10.5" rx="3" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".55"/><rect x="2.5" y="2.5" width="14" height="7" rx="1.5" fill="currentColor"/><path d="M23.5 4v4a2 2 0 0 0 0-4z" fill="currentColor" opacity=".55"/></svg></span>';
function renderMbar() {
  const badge = S.paused || S.sim === 'idle' ? 'transparent' : S.sim === 'stuck' ? 'var(--crit-m)' : S.sim === 'waiting' || S.sim === 'ctx' ? 'var(--warn-m)' : S.sim === 'done' ? 'var(--good-m)' : 'var(--a1)';
  const shape = S.sim === 'waiting' ? 'border-radius:1.5px' : S.sim === 'stuck' ? 'border-radius:1.5px;transform:rotate(45deg)' : '';
  const m = (id, label) => '<button type="button" data-act="menu" data-m="' + id + '">' + label + '</button>';
  $('#mbar').innerHTML = '<button type="button" class="apple" data-act="menu" data-m="apple" aria-label="Apple 菜单">' + APPLE + '</button><button type="button" class="app" data-act="menu" data-m="app">Orbit</button>' + m('file', '文件') + m('edit', '编辑') + m('view', '显示') + m('window', '窗口') + m('help', '帮助') +
    '<span class="sp"></span><span class="status"><button type="button" class="glyph" data-act="menu" data-m="demo" aria-label="演示菜单" data-tip="演示菜单：模拟会话事件、播放首次启动与人格揭晓">' + ic('flask', 15) + '<span class="mark" style="background:var(--ai)"></span></button>' +
    '<button type="button" class="glyph' + (S.pop ? ' on' : '') + '" data-act="pop" aria-label="打开菜单栏面板" aria-expanded="' + S.pop + '">' + GLYPH + (S.paused || S.sim === 'idle' ? '' : '<span class="badge' + (S.sim === 'running' ? ' live' : '') + '" style="background:' + badge + ';' + shape + '"></span>') + '</button>' +
    SYS_ICONS + '<span class="clock" data-clock>' + nowText() + '</span></span>';
}
/* title row: traffic lights + sidebar toggle (floats over the sidebar material, stays when the sidebar is hidden) */
function renderWtop() {
  const narrow = $('#win').classList.contains('narrow');
  const shown = narrow ? S.sideOver : S.side;
  $('#wtop').innerHTML = '<div class="lights" role="group" aria-label="窗口控制"><button type="button" class="r" data-act="winClose" aria-label="关闭窗口"></button><button type="button" class="y" data-act="winMin" aria-label="最小化"></button><button type="button" class="g" data-act="winZoom" aria-label="' + (S.win.full ? '退出全屏' : '进入全屏；按住 ⌥ 点击为缩放') + '"></button></div>' +
    '<button type="button" class="ib sbtoggle" data-act="sideToggle" aria-label="' + (shown ? '隐藏侧边栏' : '显示侧边栏') + '" aria-pressed="' + shown + '" aria-keyshortcuts="Control+Meta+S" data-tip="' + (shown ? '隐藏侧边栏' : '显示侧边栏') + ' ' + kb('⌃⌘S') + '">' + ic('sidebar') + '</button>';
}
/* sidebar: collapsible groups in a scrolling middle; fixed footer = the index indicator light (state dot · session count · index mode,
   no card, on the sidebar's own background) and the user row (avatar · account · persona code), compacted onto the type scale */
/* sidebar building blocks, shared by both editions (Advance shows every group, Lite the same groups with fewer pages) */
const sideNavBtn = (id, label, icon, ct, bd) => '<button type="button" data-act="go" data-r="' + id + '"' + (S.route === id ? ' aria-current="page"' : '') + '>' + ic(icon) + '<span class="lb">' + label + '</span>' + (bd ? '<span class="bd">' + bd + '</span>' : ct ? '<span class="ct">' + ct + '</span>' : '') + '</button>';
// SIDE_EXTRA(): optional row under the edition switch, shared by both editions (live: import progress / reopen onboarding)
let SIDE_EXTRA = null;
const sideExtra = () => (SIDE_EXTRA ? SIDE_EXTRA() : '');
const sideGroup = (id, title, inner, right) => { const open = S.sideOpen[id] !== false; return '<div class="sect"><button type="button" class="sh" data-act="sideGroup" data-g="' + id + '" aria-expanded="' + open + '">' + title + ic('chev', 10, open ? '' : 'transform:rotate(-90deg)') + '</button>' + (right && open ? '<span class="sr">' + right + '</span>' : '') + '</div>' + (open ? '<div class="nav">' + inner + '</div>' : ''); };
// sidebar agents (B): 未接入 (never imported: source off and no sessions at all) vs 停用 (imported, then turned off in settings);
// an agent with no sessions in the selected range fades (.idle) instead of looking like a filter choice
function agentState(a) { return S.srcOff.has(a.id) ? (a.all ? 'off' : 'none') : 'on'; }
// Agents list = a multi-select over S.agents (the same set the filter-row Agent menu edits; live requests carry the subset,
// LV.scope / lvScope): a click checks or unchecks the row, the 「仅此」 button that appears on hover (or ⌥ click) keeps only
// that agent, and the group head offers 「全部」 while a subset is picked. Unchecking the last one brings every agent back.
// Each row shows the agent's own logo (34-agent-logos.js) in its identity colour; unchecked rows fade it, 停用 / 未接入 rows
// draw it in grey with the state as the count.
const agentOnIds = () => AG.filter((a) => agentState(a) === 'on').map((a) => a.id);
const agentPickedIds = () => agentOnIds().filter((id) => S.agents.has(id));
function agentIcon(a, st) { return '<svg class="ag-ic" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">' + agGlyph(a.id, 8, 8, 13, st === 'on' ? a.c : 'var(--ink-4)') + '</svg>'; }
function sideAgents() {
  // each row counts its own sessions whether or not it is checked (sel() would give 0 for an unchecked agent), so the
  // number says what checking it adds
  const w = win(S.range);
  const agCount = (id) => ALL.reduce((n, s) => n + (!s.live && s.a === id && s.d >= w[0] && s.d <= w[1] && (!S.project || s.p === S.project) ? 1 : 0), 0);
  const onIds = agentOnIds(), picked = agentPickedIds();
  return AG.map((a) => {
    const st = agentState(a), off = st !== 'on', n = off ? 0 : agCount(a.id);
    const on = !off && S.agents.has(a.id), dim = !off && !on, idle = on && !n;
    const last = on && picked.length === 1;
    const only = !off && onIds.length > 1 && !last;
    const pk = on && picked.length < onIds.length; // a subset is picked: checked rows get the sidebar's light selected tint
    const tip = st === 'none' ? a.name + ' 还没有接入：到「设置 › 数据源」启用后导入' : st === 'off' ? a.name + ' 已在设置中停用' :
      (idle ? rangeLabel() + '内没有会话 · ' : '') + (last ? '点击：恢复全部 Agent' : on ? '点击：移出筛选' : '点击：加入筛选') + (only ? '；⌥ 点击：只看 ' + a.name : '');
    return '<div class="ag' + (off ? ' off' : dim ? ' dim' : idle ? ' idle' : '') + (pk ? ' pk' : '') + '" data-a="' + a.id + '">' +
      '<button type="button" class="ag-b" data-act="agentToggle" data-a="' + a.id + '" data-tip="' + esc(tip) + '" aria-pressed="' + on + '">' + agentIcon(a, st) + '<span class="lb">' + esc(a.name) + '</span><span class="ct">' + (st === 'none' ? '未接入' : st === 'off' ? '停用' : n) + '</span></button>' +
      (only ? '<button type="button" class="ag-only" data-act="agentOnly" data-a="' + a.id + '" aria-label="只看 ' + esc(a.name) + '" data-tip="只看 ' + esc(a.name) + '">仅此</button>' : '') + '</div>';
  }).join('');
}
// group head of the Agents list: the count column label, or 「全部」 while only some agents are picked
function sideAgentsRight() { return agentPickedIds().length < agentOnIds().length ? '<button type="button" class="sr-btn" data-act="agentAll" data-tip="恢复全部 Agent">全部</button>' : '会话'; }
/* pinned projects (F26): the user pins / unpins a project from the sidebar row (hover pin button) or the 项目习惯 page
   (row pin, detail 置顶 button); S.pins is kept in the UI prefs (store 'pins': native prefs in the App, localStorage in the
   browser — the same in live and demo). Without manual pins the group shows the rule it uses: the 3 projects with the most
   sessions in the selected range and Agent filter, named in the group head. Ids not (yet) in PJ stay stored and are skipped. */
S.pins = (() => { const v = store.get('pins', []); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; })();
const pinsManual = () => S.pins.filter((id) => PJI[id]);
const isPinned = (id) => S.pins.indexOf(id) >= 0;
function pinsAuto() { return PJ.filter((p) => p.id !== '_none').map((p) => ({ id: p.id, n: sel({ noExtra: true, project: p.id }).length })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n).slice(0, 3).map((x) => x.id); }
function pinToggle(id) {
  if (!id || id === '_none') return; // '_none' = live sessions without a project: not a project, so not pinnable
  const i = S.pins.indexOf(id); if (i >= 0) S.pins.splice(i, 1); else S.pins.push(id);
  store.set('pins', S.pins.slice());
  render();
  toast(i >= 0 ? '已取消置顶「' + (PJI[id] ? PJI[id].name : id) + '」' : '已置顶「' + (PJI[id] ? PJI[id].name : id) + '」到侧栏');
}
function sidePinsRight() {
  if (pinsManual().length) return '<span data-tip="你置顶的项目（悬停项目点图钉取消）。全部取消后，自动显示' + rangeLabel() + '会话最多的 3 个项目">已置顶</span>';
  return '<span data-tip="没有手动置顶时，自动显示' + rangeLabel() + '（按当前 Agent 筛选）会话最多的 3 个项目；悬停项目点图钉可置顶">' + rangeLabel() + '会话最多</span>';
}
function sidePins() {
  const man = pinsManual(), ids = man.length ? man : pinsAuto();
  const busy = dataBusy();
  if (!ids.length) return '<div class="sb-note">' + (busy ? (busy.err ? busyThen(busy) : '分析完成后显示') : rangeLabel() + '内没有项目会话') + '</div>';
  return ids.map((id) => { const pin = isPinned(id); return '<div class="pjp" data-p="' + esc(id) + '"><button type="button" data-act="pinProject" data-p="' + esc(id) + '"' + (S.project === id ? ' aria-current="page"' : '') + '>' + ic('projects') + '<span class="lb">' + esc(PJI[id].name) + '</span><span class="ct">' + sel({ noExtra: true, project: id }).length + '</span></button>' +
    (id === '_none' ? '' : '<button type="button" class="pin-b' + (pin ? ' on' : '') + '" data-act="pinToggle" data-p="' + esc(id) + '" aria-pressed="' + pin + '" aria-label="' + (pin ? '取消置顶 ' : '置顶 ') + esc(PJI[id].name) + '" data-tip="' + (pin ? '取消置顶' : '置顶到侧栏') + '">' + ic('pin', 13) + '</button>') + '</div>'; }).join('');
}
function renderSide() {
  if (S.ed === 'lite') { renderSideLite(); return; }
  const n = sel({ noExtra: true }).length;
  const recN = visibleRecs().filter((r) => !S.installed.has(r.id)).length;
  const navBtn = sideNavBtn, group = sideGroup;
  $('#side').innerHTML = edSwitch() + sideExtra() + '<div class="sb-scroll">' +
    group('insight', '洞察', navBtn('overview', '概览', 'overview') + navBtn('persona', '协作人格', 'persona') + navBtn('sentiment', '情绪语义', 'sentiment') + navBtn('projects', '项目习惯', 'projects', PJ.length) + navBtn('sessions', '会话轨迹', 'sessions', n) + navBtn('tools', '工具调用', 'tools')) +
    group('action', '行动', navBtn('recs', '优化建议', 'recs', '', recN || '') + navBtn('library', '资源库', 'library') + navBtn('studio', '生成工坊', 'studio', S.studio.run && !S.studio.run.done ? '运行中' : '')) +
    group('agents', 'Agents', sideAgents(), sideAgentsRight()) +
    group('pins', '置顶项目', sidePins(), sidePinsRight()) + '</div>' + sideFoot();
}
// the published footer, shared by both editions: index indicator light (live / paused / manual) + session count, then the user row
// sideIdx() → { st: 'live' | 'busy' | 'off' | 'err', n: session count or null, t: state label }; live mode (96-live-bind) swaps in the
// gateway's connection state and its session count, then falls through to sideMode (S.paused / S.index mirror collection.paused / sync_mode)
function sideMode(n) {
  if (S.paused) return { st: 'off', n: null, t: '采集已暂停' };
  return { st: S.index === 'live' ? 'live' : 'off', n, t: S.index === 'live' ? '实时' : S.index === 'hour' ? '每小时' : '手动' };
}
function sideIdx() { return sideMode(2416 + S.extraSrc.length * 37); }
function sideFoot() {
  const x = sideIdx(), me = personaNow();
  return '<div class="sb-foot"><button type="button" class="pv" data-act="openSettings" data-tab="sources" data-st="' + x.st + '" data-tip="打开设置 › 数据源">' +
    '<span class="pv-dot" aria-hidden="true"></span>' + (x.n == null ? '' : '<span class="pv-n">' + fmt(x.n) + ' 个会话</span><span class="pv-sep" aria-hidden="true">·</span>') + '<span class="pv-t">' + x.t + '</span></button>' +
    '<div class="me"><span class="av" aria-hidden="true">' + esc(ME.av) + '</span><div style="flex:1;min-width:0"><div class="nm">' + esc(ME.name) + '</div><div class="mono cap pc">' + (me.ok ? glyphSVG(me, 14) + '<span class="pc-t"><span class="tcode">' + me.code + '</span> · ' + me.zh + '</span>' : persNone(me)) + '</div></div><button type="button" class="ib" data-act="openSettings" aria-label="设置" data-tip="设置 ' + kb('⌘,') + '">' + ic('settings', 15) + '</button></div></div>';
}
function personaNow() { return persona(sel({ noExtra: true })); }
/* page toolbar: lives on the window's 52px title row (title 15px semibold, meta, page items, global search → command palette) */
// pages whose numbers all come from the sessions: while nothing is published yet (dataBusy, F08) their title meta says what is
// happening instead of 「0 次调用 · 0 种工具」 / 「0 个会话」
const BUSY_META_ROUTES = ['overview', 'persona', 'sentiment', 'projects', 'sessions', 'tools', 'l-home', 'l-persona', 'l-sessions'];
function tbar(title, meta, right) {
  if (BUSY_META_ROUTES.indexOf(S.route) >= 0) { const b = dataBusy(); if (b) meta = busyMeta(b); }
  const hasInput = /<input\b/i.test(right || '');
  return '<div class="tbar"><div class="grow"><h1>' + title + '</h1>' + (meta ? '<span class="meta">' + meta + '</span>' : '') + '</div>' + (right ? '<div class="tright">' + right + '</div>' : '') +
    '<button type="button" class="tsearch' + (hasInput ? ' ico-only" data-ico="1' : '') + '" data-act="palette" aria-label="搜索（' + kb('⌘K') + '）" data-tip="搜索会话、项目、建议与操作 ' + kb('⌘K') + '">' + ic('search', 14) + '<span>搜索</span><kbd>' + kb('⌘K') + '</kbd></button></div>';
}
function rangeLabel() { return S.range === 7 ? '近 7 天' : S.range === 30 ? '近 30 天' : S.range === 90 ? '近 90 天' : '全部历史'; }
function winLabel() { const w = win(S.range); const a = dayDate(w[0]), b = dayDate(w[1]); const f = (x) => x.getUTCFullYear() + '-' + String(x.getUTCMonth() + 1).padStart(2, '0') + '-' + String(x.getUTCDate()).padStart(2, '0'); return f(a) + ' — ' + f(b).slice(5); }
function filterRow(right) {
  const agN = AG.filter((a) => S.agents.has(a.id)).length;
  const fBusy = !!dataBusy();   // F08: counts are not known yet — no 「全部 0」
  const agLbl = agN === AG.length ? 'Agent · 全部' + (AG.length && !fBusy ? ' ' + AG.length : '') : agN === 1 ? 'Agent · ' + AG.find((a) => S.agents.has(a.id)).name : 'Agent · ' + agN + ' 个';
  const chips = [];
  if (S.topic) chips.push(['topic', '主题 · ' + TOPICS[S.topic]]);
  if (S.outcome) chips.push(['outcome', '结果 · ' + ({ ok: '完成', part: '部分完成', fail: '放弃' })[S.outcome]]);
  if (S.fric) chips.push(['fric', '摩擦 · ' + S.fric]);
  if (S.hour != null) chips.push(['hour', '时段 · ' + S.hour + ':00–' + (S.hour + 1) + ':00']);
  return '<div class="frow"><div class="seg" role="group" aria-label="时间范围">' + [[7, '7 天'], [30, '30 天'], [90, '90 天'], [0, '全部']].map((x) => '<button type="button" data-act="range" data-v="' + x[0] + '" class="' + (S.range === x[0] ? 'on' : '') + '" aria-pressed="' + (S.range === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
    '<button type="button" class="chip' + (agN !== AG.length ? ' on' : '') + '" data-act="agentMenu">' + ic('bot', 14, agN === AG.length ? 'color:var(--ink-3)' : '') + agLbl + ic('chev', 11, agN === AG.length ? 'color:var(--ink-3)' : '') + '</button>' +
    '<button type="button" class="chip' + (S.project ? ' on' : '') + '" data-act="projectMenu">' + ic('projects', 14) + '项目 · ' + (S.project ? PJI[S.project].name : '全部' + (!fBusy && (!LV.live || LV.state === 'ready' || LV.state === 'empty') ? ' ' + PJ.length : '')) + ic('chev', 11) + '</button>' +
    chips.map((c) => '<button type="button" class="chip on" data-act="clearFilter" data-k="' + c[0] + '" aria-label="移除筛选：' + esc(c[1]) + '">' + esc(c[1]) + ic('x', 12) + '</button>').join('') +
    '<button type="button" class="chip dash" data-act="addFilter">' + ic('plus', 13) + '添加筛选</button>' + (right ? '<span class="frow-r">' + right + '</span>' : '') + '</div>' + rangeWidenNote();
}
function agentLegendItems() { return AG.map((a) => { const st = agentState(a); return { t: a.name, v: a.id, on: S.agents.has(a.id), k: st === 'none' ? '未接入' : st === 'off' ? '停用' : String(sel({ noExtra: true, agent: a.id }).length) }; }); }
// range widening (A): the selected range has no sessions while a wider one has some (e.g. a first import of only older
// sessions) → offer 扩大到 90 天 / 看全部历史. Advance pages get it under the filter row, Lite (no filter row) in empty().
function rangeWider() {
  if (S.range === 0 || !ALL.length || sel({ noExtra: true }).length) return [];
  const w90 = S.range < 90 && sel({ range: 90, noExtra: true }).length > 0;
  return sel({ range: 0, noExtra: true }).length ? (w90 ? [90, 0] : [0]) : [];
}
function rangeWidenBtns() {
  const w = rangeWider(); if (!w.length) return '';
  return '<div class="row range-widen">' + w.map((r, i) => '<button type="button" class="btn' + (i === 0 ? ' p' : '') + '" data-act="range" data-v="' + r + '">' + (r === 0 ? '看全部历史' : '扩大到 ' + r + ' 天') + '</button>').join('') + '</div>';
}
function rangeWidenNote() {
  const b = rangeWidenBtns(); if (!b) return '';
  return '<div class="card pad range-note" data-range-note><span>' + rangeLabel() + '内没有会话 · 全部历史共 ' + fmt(sel({ range: 0, noExtra: true }).length) + ' 个</span>' + b + '</div>';
}
// 画像不可用时的短词：1 个会话就能出画像（F04），所以 0 个会话写「还没有会话」而不是「样本不足」
function persNone(p) { const b = dataBusy(); return b ? busyShort(b) : p && p.pending ? '计算中' : p && p.error ? '暂时取不到' : '还没有会话'; }
/* F08: live mode with nothing on screen yet because the data is still on its way — connecting, importing, being organised
   (projection_pending) or analysed (202). That is not 「没有会话」: titles and empty cards say what is happening instead, with
   the imported count from /v1/status when the gateway reports one. null in demo, once any session is shown, and once the
   spine has answered for real (ready / empty). A spine that failed before showing anything (a library imported by an older
   version: 409 rebuild_required / 422 schema obsolete; any other failed read or analysis) is not 「没有会话」 either: err is
   set and the slots say 暂时取不到 / 重建完成后… instead of 计算中 (busyShort / busyThen). */
function dataBusy() {
  let lv = null; try { lv = LV; } catch (e) { return null; }
  if (!lv || !lv.live || ALL.length) return null;
  const st = (TL.status && TL.status.counts) || {}; const n = st.sessions || 0;
  const j = TL.job; const importing = !!j && j.kind === 'import' && ['queued', 'pending', 'running'].indexOf(j.status) >= 0;
  if (lv.state === 'connecting') return TL.error ? { k: 'offline', t: '本机服务未连接', n: 0 } : { k: 'connecting', t: '正在连接本机服务…', n: 0 };
  if (importing) return { k: 'importing', t: '正在导入会话…', n };
  if (lv.pending) return { k: 'pending', t: '正在整理数据…', n };
  if (lv.state === 'computing') return { k: 'computing', t: '正在分析会话…', n };
  if (lv.state === 'error') {
    const e = lv.error || {}; const pi = (TL.status && TL.status.projection_info) || {};
    const rebuild = e.code === 'rebuild_required' || /obsolete|rebuild/i.test(e.message || '') || pi.state === 'invalid';
    return rebuild ? { k: 'rebuild', t: '数据需要按新版本重建', n, err: true } : { k: 'error', t: '数据暂时读不出来', n, err: true };
  }
  return null;
}
// the short slot word and the 「shows by itself when …」 clause of a busy state that is a failure (err), not progress
const busyShort = (b) => (b && b.err ? '暂时取不到' : '计算中');
const busyThen = (b) => (b && b.k === 'rebuild' ? '重建完成后自动显示' : '恢复读取后自动显示');
// one line for titles / empty cards: 「正在分析会话… · 已导入 26 个会话 · 已用 12 / 60 秒」
function busyNote(b) {
  b = b || dataBusy(); if (!b) return '';
  let p = '';
  if (b.k === 'computing' && typeof lvSpineProgress === 'function') { try { p = lvSpineProgress(); } catch (e) { p = ''; } }
  return b.t + (b.n ? ' · 已导入 ' + fmt(b.n) + ' 个会话' : '') + p;
}
// the title meta while busy: the calm status instead of 「0 个会话 · 还没有接入 Agent」
function busyMeta(b) { b = b || dataBusy(); return b ? (b.n ? '已导入 ' + fmt(b.n) + ' 个会话 · ' : '') + (b.k === 'computing' ? '分析中' : b.k === 'importing' ? '导入中' : b.k === 'pending' ? '整理中' : b.t) : ''; }
function busyCard(b) { b = b || dataBusy(); return '<div class="card pad" data-lv="busy" role="status" style="text-align:center;color:var(--ink-3);padding:40px 16px">' + esc(busyNote(b)) + '<div class="cap" style="margin-top:6px">' + (b && b.err ? busyThen(b) : '完成后自动显示') + '，不用刷新</div></div>'; }
function empty(msg) { return dataBusy() ? busyCard() : '<div class="card pad" style="text-align:center;color:var(--ink-3);padding:40px 16px">' + msg + (S.ed === 'lite' ? rangeWidenBtns() : '') + '</div>'; }
