/* ============ navigation & render ============ */
const ROUTES = [['overview', '概览'], ['persona', '协作人格'], ['sessions', '会话与轨迹'], ['tools', '工具调用'], ['projects', '项目习惯'], ['sentiment', '情绪与语义'], ['recs', '优化建议'], ['library', '资源库'], ['studio', '生成工坊']];
const PAGES = {};
function go(route, keepScroll) {
  if (!PAGES[route]) route = 'overview';
  S.route = route; S.drawer = false; S.winGone = false; closeDD(); tipOff();
  try { history.replaceState(null, '', '#' + route); } catch (e) { /* sandboxed */ }
  render();
  if (!keepScroll) { const c = $('#content'); if (c) c.scrollTop = 0; }
}
function render() {
  renderMbar(); renderSide(); renderMain(); renderHud(); renderWidgets();
  if (S.pop) renderPop(); else $('#pop').hidden = true;
  if (!$('#set').hidden) renderSet();
  const w = $('#win');
  w.classList.toggle('rail', S.rail); w.classList.toggle('drawer', S.drawer); w.classList.toggle('gone', S.winGone);
  desk.classList.toggle('wide', S.widgets && window.innerWidth >= 1500); desk.classList.toggle('max', S.max);
}
function renderMain() {
  const m = $('#main'); const c = $('#content'); const top = c ? c.scrollTop : 0;
  m.innerHTML = PAGES[S.route]();
  const nc = $('#content'); if (nc) nc.scrollTop = top;
  if (PAGES[S.route].after) PAGES[S.route].after();
}
function renderMbar() {
  const badge = S.paused || S.sim === 'idle' ? 'transparent' : S.sim === 'stuck' ? 'var(--crit-m)' : S.sim === 'waiting' || S.sim === 'ctx' ? 'var(--warn-m)' : S.sim === 'done' ? 'var(--good-m)' : 'var(--a1)';
  const shape = S.sim === 'waiting' ? 'border-radius:1.5px' : S.sim === 'stuck' ? 'border-radius:1.5px;transform:rotate(45deg)' : '';
  $('#mbar').innerHTML = '<button type="button" class="app" data-act="menu" data-m="app">Tandem</button><span class="menus"><button type="button" data-act="menu" data-m="file">文件</button><button type="button" data-act="menu" data-m="view">显示</button><button type="button" data-act="menu" data-m="window">窗口</button><button type="button" data-act="menu" data-m="help">帮助</button></span><button type="button" class="compact" data-act="menu" data-m="all">菜单</button><span class="sp"></span><button type="button" class="demo" data-act="menu" data-m="demo">演示 ▾</button><button type="button" class="glyph" data-act="pop" aria-label="打开菜单栏面板" aria-expanded="' + S.pop + '"' + (S.pop ? ' style="background:var(--field)"' : '') + '>' + GLYPH + (S.paused || S.sim === 'idle' ? '' : '<span class="badge" style="background:' + badge + ';' + shape + '"></span>') + '</button><span class="sys"><svg class="opt" width="16" height="12" viewBox="0 0 24 18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M2.5 7a14 14 0 0 1 19 0M5.5 10.5a9.5 9.5 0 0 1 13 0M8.8 14a5 5 0 0 1 6.4 0"/></svg><svg class="opt" width="24" height="12" viewBox="0 0 24 12" aria-hidden="true"><rect x=".75" y=".75" width="19.5" height="10.5" rx="3" fill="none" stroke="currentColor" stroke-width="1.2" opacity=".6"/><rect x="2.5" y="2.5" width="12" height="7" rx="1.5" fill="currentColor"/></svg><span class="mono" data-clock style="font-size:12px">' + nowText() + '</span></span>';
}
function renderSide() {
  const n = sel({ noExtra: true }).length;
  const recN = visibleRecs().filter((r) => !S.installed.has(r.id)).length;
  const navBtn = (id, label, icon, ct, bd) => '<button type="button" data-act="go" data-r="' + id + '"' + (S.route === id ? ' aria-current="page"' : '') + ' data-tip="' + (S.rail ? label : '') + '">' + ic(icon) + '<span class="lb">' + label + '</span>' + (bd ? '<span class="bd">' + bd + '</span>' : ct ? '<span class="ct">' + ct + '</span>' : '') + '</button>';
  const agCount = (id) => sel({ noExtra: true, agent: id, project: S.project }).length;
  $('#side').innerHTML =
    '<div class="lights"><button type="button" class="r" data-act="winClose" aria-label="关闭窗口"></button><button type="button" class="y" data-act="winMin" aria-label="最小化"></button><button type="button" class="g" data-act="winMax" aria-label="缩放窗口"></button><span style="flex:1"></span><button type="button" class="ib" data-act="rail" aria-label="收起侧边栏" style="color:var(--ink-3)">' + ic('sidebar') + '</button></div>' +
    '<button type="button" class="search" data-act="palette" aria-label="搜索（⌘K）">' + ic('search', 14) + '<span>搜索会话、项目、建议</span><span class="k mono" style="font-size:10px;border:1px solid var(--line);border-radius:4px;padding:2px 4px">⌘K</span></button>' +
    '<div class="sect">洞察</div><div class="nav">' + navBtn('overview', '概览', 'overview') + navBtn('persona', '协作人格', 'persona') + navBtn('sessions', '会话与轨迹', 'sessions', n) + navBtn('tools', '工具调用', 'tools') + navBtn('projects', '项目习惯', 'projects', 9) + navBtn('sentiment', '情绪与语义', 'sentiment') + '</div>' +
    '<div class="sect">行动</div><div class="nav">' + navBtn('recs', '优化建议', 'recs', '', recN || '') + navBtn('library', '资源库', 'library') + navBtn('studio', '生成工坊', 'studio', S.studio.run && !S.studio.run.done ? '运行中' : '') + '</div>' +
    '<div class="sect"><span>Agents</span><span style="font-weight:500">会话</span></div><div class="nav">' + AG.map((a) => '<button type="button" class="ag' + (S.agents.has(a.id) && !S.srcOff.has(a.id) ? '' : ' off') + '" data-act="agentToggle" data-a="' + a.id + '" data-tip="点击：只看 ' + a.name + '；⌥ 点击：加入或移出筛选" aria-pressed="' + S.agents.has(a.id) + '"><span class="dot" style="background:' + a.c + '"></span><span class="lb">' + a.name + '</span><span class="ct">' + agCount(a.id) + '</span></button>').join('') + '</div>' +
    '<div class="sect">置顶项目</div><div class="nav">' + ['confluo', 'latentskill', 'teamhub'].map((id) => '<button type="button" data-act="pinProject" data-p="' + id + '"' + (S.project === id ? ' aria-current="page"' : '') + '>' + ic('projects') + '<span class="lb">' + PJI[id].name + '</span><span class="ct">' + sel({ noExtra: true, project: id }).length + '</span></button>').join('') + '</div>' +
    '<div class="foot"><button type="button" class="privacy" data-act="openSettings" data-tab="privacy"><span class="row" style="align-items:flex-start;gap:8px">' + ic('shield', 16, 'color:var(--good);margin-top:1px') + '<span style="display:flex;flex-direction:column"><b style="font-size:12.5px">仅本地处理</b><span class="cap" style="font-size:11px">0 B 上传 · 脱敏规则 ' + Object.values(S.rules).filter(Boolean).length + ' 条生效</span></span></span><span class="row cap" style="font-size:11px;gap:8px">' + ic('sync', 14) + (S.paused ? '采集已暂停' : '已索引 ' + fmt(2416 + S.extraSrc.length * 37) + ' 个会话 · ' + (S.index === 'live' ? '实时' : S.index === 'hour' ? '每小时' : '手动')) + '</span></button>' +
    '<div class="me"><span class="av">yh</span><div style="flex:1;min-width:0"><div style="font-size:12.5px;font-weight:600">yhyfhgs</div><div class="mono cap" style="font-size:10.5px">' + (personaNow().ok ? personaNow().code + ' · ' + personaNow().zh : '样本不足') + '</div></div><button type="button" class="ib" data-act="openSettings" aria-label="偏好设置" style="color:var(--ink-3)">' + ic('settings') + '</button></div></div>';
}
function personaNow() { return persona(sel({ noExtra: true })); }
function tbar(title, meta, right) {
  return '<div class="tbar"><button type="button" class="ib burger" data-act="drawer" aria-label="打开导航">' + ic('burger') + '</button><div class="grow"><h1>' + title + '</h1>' + (meta ? '<span class="meta">' + meta + '</span>' : '') + '</div>' + (right || '') + '</div>';
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
    '<button type="button" class="chip" data-act="agentMenu">' + ic('bot', 14, 'color:var(--ink-3)') + agLbl + ic('chev', 12, 'color:var(--ink-3)') + '</button>' +
    '<button type="button" class="chip' + (S.project ? ' on' : '') + '" data-act="projectMenu">' + ic('projects', 14) + '项目 · ' + (S.project ? PJI[S.project].name : '全部 9') + ic('chev', 12) + '</button>' +
    chips.map((c) => '<button type="button" class="chip on" data-act="clearFilter" data-k="' + c[0] + '" aria-label="移除筛选：' + esc(c[1]) + '">' + esc(c[1]) + ic('x', 12) + '</button>').join('') +
    '<button type="button" class="chip dash" data-act="addFilter">' + ic('plus', 13) + '添加筛选</button><span style="flex:1"></span>' + (right || '') + '</div>';
}
function agentLegendItems() { return AG.map((a) => ({ t: a.name, v: a.id, on: S.agents.has(a.id) })); }
function empty(msg) { return '<div class="card pad" style="text-align:center;color:var(--ink-3);padding:40px 16px">' + msg + '</div>'; }

