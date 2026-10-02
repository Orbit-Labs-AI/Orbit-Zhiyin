/* ============ navigation & render ============ */
const ROUTES = [['overview', '概览'], ['persona', '协作人格'], ['sessions', '会话与轨迹'], ['tools', '工具调用'], ['projects', '项目习惯'], ['sentiment', '情绪与语义'], ['recs', '优化建议'], ['library', '资源库'], ['studio', '生成工坊']];
const PAGES = {};
function go(route, keepScroll) {
  if (!PAGES[route]) route = 'overview';
  S.route = route; S.sideOver = false; S.winGone = false; closeDD(); tipOff();
  try { history.replaceState(null, '', '#' + route); } catch (e) { /* sandboxed */ }
  render();
  if (!keepScroll) { const c = $('#content'); if (c) c.scrollTop = 0; }
}
function render() {
  applyWin(); renderMbar(); renderWtop(); renderSide(); renderMain(); renderHud(); renderWidgets();
  if (S.pop) renderPop(); else $('#pop').hidden = true;
  if (!$('#set').hidden) renderSet();
  $('#win').classList.toggle('gone', S.winGone);
  applyWin();
}
function renderMain() {
  const m = $('#main'); const c = $('#content'); const top = c ? c.scrollTop : 0;
  m.innerHTML = PAGES[S.route]();
  const nc = $('#content'); if (nc) nc.scrollTop = top;
  tbarFit();
  if (PAGES[S.route].after) PAGES[S.route].after();
}
/* toolbar overflow, in order: the search field collapses to its icon as soon as the meta text would be clipped; the meta
   then shrinks (ellipsis); items that still do not fit move (right to left) into a » popover. Runs after every page render
   and on 'tandem:layout' (window resize, sidebar toggle). */
function tbarFit() {
  const tb = $('#main .tbar'); if (!tb) return;
  const tr = tb.querySelector('.tright'); if (!tr) return;
  let more = tb.querySelector('.tmore');
  if (more) { const pop = more.querySelector('.tmore-pop'); while (pop.firstChild) tr.appendChild(pop.firstChild); more.remove(); }
  const ts = tb.querySelector('.tsearch'), meta = tb.querySelector('.meta');
  if (ts && !ts.dataset.ico) { ts.classList.remove('ico-only'); if (meta && meta.scrollWidth > meta.clientWidth + 0.5) ts.classList.add('ico-only'); }
  const fits = () => tb.scrollWidth <= tb.clientWidth + 0.5;
  if (fits() || !tr.children.length) return;
  more = document.createElement('div'); more.className = 'tmore';
  more.innerHTML = '<button type="button" class="ib" data-act="tmore" aria-label="更多工具栏项" aria-expanded="false" data-tip="更多工具栏项">' + ic('more') + '</button><div class="tmore-pop" hidden></div>';
  tr.after(more);
  const pop = more.querySelector('.tmore-pop');
  while (!fits() && tr.children.length) pop.prepend(tr.lastElementChild);
}
window.addEventListener('tandem:layout', tbarFit);
/* menu bar: Apple menu, app menus (never fold with the window width), status items: demo (flask) · Tandem · control centre · Wi-Fi · battery · clock */
const APPLE = '<svg width="14" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor"><path d="M16.37 12.7c-.03-2.6 2.13-3.86 2.23-3.92-1.22-1.78-3.11-2.02-3.78-2.05-1.61-.16-3.14.95-3.96.95-.82 0-2.08-.93-3.42-.9-1.76.03-3.38 1.02-4.29 2.6-1.83 3.17-.47 7.87 1.31 10.44.87 1.26 1.91 2.67 3.27 2.62 1.31-.05 1.81-.85 3.4-.85 1.59 0 2.03.85 3.42.82 1.41-.03 2.31-1.28 3.17-2.55 1-1.46 1.41-2.87 1.43-2.95-.03-.01-2.75-1.05-2.78-4.21zM13.76 5.05c.72-.88 1.21-2.1 1.08-3.31-1.04.04-2.3.69-3.05 1.57-.67.78-1.26 2.02-1.1 3.21 1.16.09 2.35-.59 3.07-1.47z"/></svg>';
const SYS_ICONS = '<span class="sysicon" aria-hidden="true"><svg width="16" height="12" viewBox="0 0 16 12" fill="none" stroke="currentColor" stroke-width="1.1"><rect x=".55" y=".55" width="14.9" height="4.9" rx="2.45"/><circle cx="3" cy="3" r="1.5" fill="currentColor" stroke="none"/><rect x=".55" y="6.55" width="14.9" height="4.9" rx="2.45"/><circle cx="13" cy="9" r="1.5" fill="currentColor" stroke="none"/></svg></span>' +
  '<span class="sysicon" aria-hidden="true"><svg width="16" height="12" viewBox="0 0 24 18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M2.5 7a14 14 0 0 1 19 0M5.5 10.5a9.5 9.5 0 0 1 13 0M8.8 14a5 5 0 0 1 6.4 0"/></svg></span>' +
  '<span class="sysicon" aria-hidden="true" style="width:32px"><svg width="26" height="12" viewBox="0 0 26 12"><rect x=".75" y=".75" width="21.5" height="10.5" rx="3" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".55"/><rect x="2.5" y="2.5" width="14" height="7" rx="1.5" fill="currentColor"/><path d="M23.5 4v4a2 2 0 0 0 0-4z" fill="currentColor" opacity=".55"/></svg></span>';
function renderMbar() {
  const badge = S.paused || S.sim === 'idle' ? 'transparent' : S.sim === 'stuck' ? 'var(--crit-m)' : S.sim === 'waiting' || S.sim === 'ctx' ? 'var(--warn-m)' : S.sim === 'done' ? 'var(--good-m)' : 'var(--a1)';
  const shape = S.sim === 'waiting' ? 'border-radius:1.5px' : S.sim === 'stuck' ? 'border-radius:1.5px;transform:rotate(45deg)' : '';
  const m = (id, label) => '<button type="button" data-act="menu" data-m="' + id + '">' + label + '</button>';
  $('#mbar').innerHTML = '<button type="button" class="apple" data-act="menu" data-m="apple" aria-label="Apple 菜单">' + APPLE + '</button><button type="button" class="app" data-act="menu" data-m="app">Tandem</button>' + m('file', '文件') + m('edit', '编辑') + m('view', '显示') + m('window', '窗口') + m('help', '帮助') +
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
/* sidebar: collapsible groups in a scrolling middle, one-line footer (privacy + settings) */
function renderSide() {
  const n = sel({ noExtra: true }).length;
  const recN = visibleRecs().filter((r) => !S.installed.has(r.id)).length;
  const navBtn = (id, label, icon, ct, bd) => '<button type="button" data-act="go" data-r="' + id + '"' + (S.route === id ? ' aria-current="page"' : '') + '>' + ic(icon) + '<span class="lb">' + label + '</span>' + (bd ? '<span class="bd">' + bd + '</span>' : ct ? '<span class="ct">' + ct + '</span>' : '') + '</button>';
  const group = (id, title, inner, right) => { const open = S.sideOpen[id] !== false; return '<div class="sect"><button type="button" class="sh" data-act="sideGroup" data-g="' + id + '" aria-expanded="' + open + '">' + title + ic('chev', 10, open ? '' : 'transform:rotate(-90deg)') + '</button>' + (right && open ? '<span class="sr">' + right + '</span>' : '') + '</div>' + (open ? '<div class="nav">' + inner + '</div>' : ''); };
  const agCount = (id) => sel({ noExtra: true, agent: id, project: S.project }).length;
  const agents = AG.map((a) => { const off = S.srcOff.has(a.id); const dim = !off && !S.agents.has(a.id); return '<button type="button" class="ag' + (off ? ' off' : dim ? ' dim' : '') + '" data-act="agentToggle" data-a="' + a.id + '" data-tip="' + (off ? a.name + ' 已在设置中停用' : '点击：只看 ' + a.name + '；⌥ 点击：加入或移出筛选') + '" aria-pressed="' + (S.agents.has(a.id) && !off) + '">' + (off ? ic('slash', 14, 'margin:0 1px') : '<span class="dot" style="background:' + a.c + '"></span>') + '<span class="lb">' + a.name + '</span><span class="ct">' + (off ? '停用' : agCount(a.id)) + '</span></button>'; }).join('');
  const pins = ['confluo', 'latentskill', 'teamhub'].map((id) => '<button type="button" data-act="pinProject" data-p="' + id + '"' + (S.project === id ? ' aria-current="page"' : '') + '>' + ic('projects') + '<span class="lb">' + PJI[id].name + '</span><span class="ct">' + sel({ noExtra: true, project: id }).length + '</span></button>').join('');
  const idx = S.paused ? '采集已暂停' : '已索引 ' + fmt(2416 + S.extraSrc.length * 37) + ' · ' + (S.index === 'live' ? '实时' : S.index === 'hour' ? '每小时' : '手动');
  $('#side').innerHTML = '<div class="sb-scroll">' +
    group('insight', '洞察', navBtn('overview', '概览', 'overview') + navBtn('persona', '协作人格', 'persona') + navBtn('sessions', '会话与轨迹', 'sessions', n) + navBtn('tools', '工具调用', 'tools') + navBtn('projects', '项目习惯', 'projects', 9) + navBtn('sentiment', '情绪与语义', 'sentiment')) +
    group('action', '行动', navBtn('recs', '优化建议', 'recs', '', recN || '') + navBtn('library', '资源库', 'library') + navBtn('studio', '生成工坊', 'studio', S.studio.run && !S.studio.run.done ? '运行中' : '')) +
    group('agents', 'Agents', agents, '会话') +
    group('pins', '置顶项目', pins) + '</div>' +
    '<div class="sb-foot"><button type="button" class="pv" data-act="openSettings" data-tab="privacy" data-tip="仅本地处理 · 0 B 上传 · 脱敏规则 ' + Object.values(S.rules).filter(Boolean).length + ' 条生效">' + ic('shield', 14, 'color:var(--good)') + '<span>仅本地 · ' + idx + '</span></button><button type="button" class="ib" data-act="openSettings" aria-label="设置" data-tip="设置 ' + kb('⌘,') + '">' + ic('settings', 15) + '</button></div>';
}
function personaNow() { return persona(sel({ noExtra: true })); }
/* page toolbar: lives on the window's 52px title row (title 15px semibold, meta, page items, global search → command palette) */
function tbar(title, meta, right) {
  const hasInput = /<input\b/i.test(right || '');
  return '<div class="tbar"><div class="grow"><h1>' + title + '</h1>' + (meta ? '<span class="meta">' + meta + '</span>' : '') + '</div>' + (right ? '<div class="tright">' + right + '</div>' : '') +
    '<button type="button" class="tsearch' + (hasInput ? ' ico-only" data-ico="1' : '') + '" data-act="palette" aria-label="搜索（' + kb('⌘K') + '）" data-tip="搜索会话、项目、建议与操作 ' + kb('⌘K') + '">' + ic('search', 14) + '<span>搜索</span><kbd>' + kb('⌘K') + '</kbd></button></div>';
}
function rangeLabel() { return S.range === 7 ? '近 7 天' : S.range === 30 ? '近 30 天' : S.range === 90 ? '近 90 天' : '全部历史'; }
function winLabel() { const w = win(S.range); const a = dayDate(w[0]), b = dayDate(w[1]); const f = (x) => x.getUTCFullYear() + '-' + String(x.getUTCMonth() + 1).padStart(2, '0') + '-' + String(x.getUTCDate()).padStart(2, '0'); return f(a) + ' — ' + f(b).slice(5); }
function filterRow(right) {
  const agN = AG.filter((a) => S.agents.has(a.id)).length;
  const agLbl = agN === AG.length ? 'Agent · 全部 5' : agN === 1 ? 'Agent · ' + AG.find((a) => S.agents.has(a.id)).name : 'Agent · ' + agN + ' 个';
  const chips = [];
  if (S.topic) chips.push(['topic', '主题 · ' + TOPICS[S.topic]]);
  if (S.outcome) chips.push(['outcome', '结果 · ' + ({ ok: '完成', part: '部分完成', fail: '放弃' })[S.outcome]]);
  if (S.fric) chips.push(['fric', '摩擦 · ' + S.fric]);
  if (S.hour != null) chips.push(['hour', '时段 · ' + S.hour + ':00–' + (S.hour + 1) + ':00']);
  return '<div class="frow"><div class="seg" role="group" aria-label="时间范围">' + [[7, '7 天'], [30, '30 天'], [90, '90 天'], [0, '全部']].map((x) => '<button type="button" data-act="range" data-v="' + x[0] + '" class="' + (S.range === x[0] ? 'on' : '') + '" aria-pressed="' + (S.range === x[0]) + '">' + x[1] + '</button>').join('') + '</div>' +
    '<button type="button" class="chip' + (agN !== AG.length ? ' on' : '') + '" data-act="agentMenu">' + ic('bot', 14, agN === AG.length ? 'color:var(--ink-3)' : '') + agLbl + ic('chev', 11, agN === AG.length ? 'color:var(--ink-3)' : '') + '</button>' +
    '<button type="button" class="chip' + (S.project ? ' on' : '') + '" data-act="projectMenu">' + ic('projects', 14) + '项目 · ' + (S.project ? PJI[S.project].name : '全部 9') + ic('chev', 11) + '</button>' +
    chips.map((c) => '<button type="button" class="chip on" data-act="clearFilter" data-k="' + c[0] + '" aria-label="移除筛选：' + esc(c[1]) + '">' + esc(c[1]) + ic('x', 12) + '</button>').join('') +
    '<button type="button" class="chip dash" data-act="addFilter">' + ic('plus', 13) + '添加筛选</button><span style="flex:1"></span>' + (right || '') + '</div>';
}
function agentLegendItems() { return AG.map((a) => ({ t: a.name, v: a.id, on: S.agents.has(a.id) })); }
function empty(msg) { return '<div class="card pad" style="text-align:center;color:var(--ink-3);padding:40px 16px">' + msg + '</div>'; }
