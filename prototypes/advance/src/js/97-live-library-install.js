/* ============ live binding: A8 资源库 + 安装流程 (library-install; OrbitLive C.li, js/06-live-client.js) ============
   Live mode only; mock mode changes nothing. The library page keeps the demo's classes and layout (tabs + kind chips, three
   feature cards, 更多匹配 rows, a right-hand card) with catalog data: tabs map to sort / origin (local = 本地生成), kind chips to
   kind filters with facet counts, the search box to /v1/catalog/search (debounced), 加载更多 to next_cursor. A card opens the
   item detail (README, versions, risk, related). 获取 runs the real install sheet: plan (+ fetch) → preview diff with
   per-target / per-unit selection → confirm (risk override when required) → apply with the confirmed preview_digest; a 409
   preview_stale re-previews and asks again. 撤销 reverts through the ledger. When the catalog or install routes are missing,
   not implemented, unavailable or offline (C.li.degraded) the page and the sheet fall back to the demo with 示例数据 (the
   catalog is seed content, not personal data); the 已安装 sheet never falls back to demo rows (it is personal).
   Slice 5 (v0.0.1): agent names come from LV.agentOf (real ids: claude_code, codex, dsh, pi, kimi, hermes, opencode, …);
   bundled seed items (item_id seed:*) carry 示例数据, real catalog rows never do; the first visit starts one catalog sync
   (POST /v1/catalog/sync) when no network source was ever synced and shows its progress; external links (source, README,
   manual install links) go through ORBIT.native openExternal (browser fallback: window.open). */
// lastVm: the previous filter's result, kept on screen while a new tab / kind / search loads (no layout jump)
S.li = { q: '', qT: 0, lastVm: null, more: null, detail: null, inst: new Map(), errAt: 0, degraded: false, sync: null };
const LI_ICON = { skill: 'book', hook: 'bolt', plugin: 'plug', marketplace: 'plug', subagent: 'bot', mcp_server: 'puzzle', command: 'file', rule: 'file', workflow: 'branch' };
const LI_AGENT = { claude_code: 'Claude Code', codex: 'Codex', gemini: 'Gemini CLI', gemini_cli: 'Gemini CLI', copilot: 'Copilot CLI', deepseek: 'DeepSeek' };
const LI_TAB_LABEL = [['for', '最近更新'], ['peer', '高星'], ['hot', '热门'], ['local', '本地生成']];
const LI_RISK = { safe: '安全', caution: '需留意', dangerous: '高风险' };
const liAgentName = (a) => { const m = typeof LV !== 'undefined' && LV.agentOf ? LV.agentOf(a) : null; return m && m.slot ? m.name : LI_AGENT[a] || (m && m.name) || a; };
const liAgents = (xs) => (xs && xs.length ? xs.map(liAgentName).join(' · ') : '—');
// bundled seed rows (item_id seed:*) are sample content until the first network sync replaces them
const liSeed = (x) => /^seed:/.test(String((x && x.item_id) || ''));
const liSeedTag = (x) => (liSeed(x) ? TLU.sample() : '');
// external link: the native host opens it in the default browser (openExternal); the browser build falls back to window.open
const liLink = (url, label, cls) => '<button type="button" class="' + (cls || 'lnk') + '" data-act="liOpen" data-url="' + esc(url) + '">' + label + '</button>';
// card text: the item's own summary; a search hit without one gets its snippet minus the index's `key: value` tag dump
const LI_TAGDUMP = /(?:^|\s)(?:agent|command|dimension|domain|file_type|friction|software|tag|kind|lang|language|topic|scene|tool|ftype|cmd):\s*\S+/gi;
const liDesc = (x) => { const t = String(x.summary || x.snippet || ''); return t.replace(LI_TAGDUMP, '').replace(/\s{2,}/g, ' ').trim(); };
const liSrc = (x) => x.official ? esc(!x.author || /^orbit$/i.test(x.author) ? 'Orbit' : x.author) + ' 官方' : x.origin === 'local' ? '本地生成' : esc(x.author || '社区') + ' · ' + esc(x.license || '许可未知');
const liReq = () => TL.li.listRequest({ tab: S.lib.tab, kind: S.lib.kind, q: S.li.q });
const liReqKey = (r) => r.path + '|' + JSON.stringify(r.query);
const liInvalidate = () => TL.invalidate((r) => /^\/v1\/(catalog|install)\//.test(r.path));
const liDay = (v) => { if (v == null) return '—'; const d = new Date(typeof v === 'number' ? v : Date.parse(v)); return isNaN(d) ? '—' : (d.getMonth() + 1) + '/' + d.getDate(); };

TL.bind('library', () => {
  const r = liReq(), f = TL.li.facetsRequest({ tab: S.lib.tab });
  // the distribution card follows the kind chip (the backend keeps the kind facet itself unfiltered, so chip counts stay whole)
  const ks = TL.li.helpers.LI_KINDS[S.lib.kind] || []; const fp = f.path + (ks.length ? '?' + ks.map((k) => 'kind=' + encodeURIComponent(k)).join('&') : '');
  return [{ name: 'list', path: r.path, query: r.query, scope: false }, { name: 'facets', path: fp, query: f.query, scope: false }];
}, (d) => ({ items: d.list.items || [], next: d.list.next_cursor || null, total: d.list.total, search: !!S.li.q, facets: d.facets || {} }));

// Install state (optional): marks installed cards with their install_id and feeds the toolbar count; never blocks the page.
function liState() { const r = TL.resource('/v1/install/state'); if (r.dirty && !r.loading) TL.load(r); return r; }
function liInstalledId(x) {
  if (S.li.inst.has(x.item_id)) return S.li.inst.get(x.item_id);
  const st = liState().data; const row = st && (st.items || []).find((i) => i.source_type === 'catalog' && i.source_id === x.item_id && !/^(reverted|archived)$/.test(i.state));
  return row ? row.install_id : null;
}
function liItems(vm) {
  const key = liReqKey(liReq()); const more = S.li.more && S.li.more.key === key ? S.li.more.items : [];
  return vm.items.concat(more).filter((x) => !S.libHide.has(x.item_id));
}
function liGetBtn(x) {
  const iid = liInstalledId(x);
  if (iid || x.installed) return '<span class="row" style="gap:4px"><span class="tag">已安装</span>' + (iid ? '<button type="button" class="btn sm gh" data-act="liRevert" data-id="' + esc(iid) + '">撤销</button>' : '') + '</span>';
  return '<button type="button" class="btn sm p" data-act="getLib" data-id="' + esc(x.item_id) + '">' + (x.origin === 'local' ? '安装' : '获取') + '</button>';
}
function liFeat(x) {
  return '<div class="card lb-card" data-tl-item="' + esc(x.item_id) + '" data-act="liDetail" data-id="' + esc(x.item_id) + '" style="cursor:pointer"><div class="lb-head"><div class="mono row cap lb-meta">' + ic(LI_ICON[x.kind] || 'file', 13, 'color:var(--ink-1)') + '<b style="font-family:var(--font-sans);color:var(--ink-2)">' + esc(TL.li.kindLabel(x.kind)) + '</b><span>·</span><span>' + liSrc(x) + '</span>' + liSeedTag(x) + '</div>' +
    '<div class="mono lb-id"><button type="button" class="lnk" data-act="liDetail" data-id="' + esc(x.item_id) + '" style="font:inherit;color:inherit;text-align:left">' + esc(x.name) + '</button></div><div class="lb-desc">' + esc(liDesc(x)) + '</div>' +
    '<div class="lb-match"><b class="mono">' + TLU.num(x.risk_level) + '</b><span class="col" style="flex:1;gap:3px;min-width:0"><span class="mono cap lb-parts">风险等级' + (x.risk && x.risk.length ? ' · ' + esc(x.risk.join('、')) : ' · 无敏感权限') + '</span><span class="mono cap lb-parts">' + (x.version ? 'v' + esc(x.version) + ' · ' : '') + '更新于 ' + liDay(x.updated_at) + '</span></span></div></div>' +
    '<div class="lb-body"><span class="eb">适用 Agent</span>' + ((x.agents && x.agents.length ? x.agents : [null]).map((a) => '<span class="row lb-why">' + ic('check', 13, 'margin-top:2px;color:var(--ink-1);flex:none') + (a ? esc(liAgentName(a)) : '未声明') + '</span>').join('')) +
    '<div class="row lb-foot"><span class="cap lb-fc">' + (x.stars != null ? TLU.num(x.stars) + ' Star' : '—') + '</span><span style="flex:1"></span><span class="mono cap lb-fc">' + (x.installs ? fmt(x.installs) + ' 安装' : x.origin === 'local' ? '本机' : '—') + '</span><span class="row lb-acts"><button type="button" class="btn sm gh" data-act="libHide" data-id="' + esc(x.item_id) + '">不感兴趣</button>' + liGetBtn(x) + '</span></div></div></div>';
}
function liRow(x) {
  return '<div class="lb-row" data-tl-item="' + esc(x.item_id) + '" data-act="liDetail" data-id="' + esc(x.item_id) + '" style="cursor:pointer"><span class="lb-ico">' + ic(LI_ICON[x.kind] || 'file', 15) + '</span><div style="min-width:0"><div class="row" style="gap:6px"><button type="button" class="lnk mono lb-nm" data-act="liDetail" data-id="' + esc(x.item_id) + '" style="font-weight:700;color:var(--ink-1)">' + esc(x.name) + '</button><span class="bdg">' + esc(TL.li.kindLabel(x.kind)) + '</span>' + (x.origin === 'local' ? '<span class="aib">本地生成</span>' : '') + liSeedTag(x) + '</div><div class="cap lb-ell">' + esc(liDesc(x)) + '</div></div>' +
    '<div class="row lb-m" style="gap:6px"><span class="mono cap">风险</span><b class="mono lb-mv">' + TLU.num(x.risk_level) + '</b></div><span class="mono cap lb-users">' + (x.installs ? (x.installs >= 1000 ? f1(x.installs / 1000) + 'k' : x.installs) : x.origin === 'local' ? '本机' : '—') + '</span>' + liGetBtn(x) + '</div>';
}
function liBody(vm) {
  const items = liItems(vm), feat = items.slice(0, 3), more = items.slice(3), fc = vm.facets || {};
  const kindCount = (k) => { const ks = TL.li.helpers.LI_KINDS[k]; if (!ks) return fc.total; return (fc.kind || []).filter((r) => ks.indexOf(r.value) >= 0).reduce((n, r) => n + r.count, 0); };
  const q = S.li.q; const shown = vm.items.length + (S.li.more && S.li.more.key === liReqKey(liReq()) ? S.li.more.items.length : 0);
  const title = q ? '搜索「' + esc(q) + '」' : S.lib.tab === 'local' ? '你的本地 Agent 生成的' : S.lib.tab === 'hot' ? '按安装量' : S.lib.tab === 'peer' ? '按 Star 数' : '资源目录';
  const sub = q ? '混合检索 · ' + items.length + ' 项' : S.lib.tab === 'local' ? '只在本机，不上传' : '共 ' + TLU.num(vm.total != null ? vm.total : fc.total) + ' 项 · 本机资源目录';
  const moreBtn = q ? '' : S.li.more && S.li.more.loading ? '<span class="cap" data-tl="lib-more">正在加载…</span>' : (S.li.more && S.li.more.key === liReqKey(liReq()) ? S.li.more.next : vm.next) ? '<button type="button" class="btn sm" data-act="liMore" data-tl="lib-more">加载更多 · 已显示 ' + shown + ' / ' + TLU.num(vm.total != null ? vm.total : fc.total) + '</button>' : '';
  // the kind facet stays unfiltered (whole catalog) while fc.total follows the kind chip: shares use the all-kind total so a
  // filtered view never shows >100% (R4-01); the selected kinds are marked instead
  const kinds = (fc.kind || []).slice(0, 5); const allKinds = (fc.kind || []).reduce((n, r) => n + (r.count || 0), 0);
  const tot = Math.max(1, allKinds, fc.total || 0); const selKs = TL.li.helpers.LI_KINDS[S.lib.kind] || null;
  return '<div data-tl="library">' + liSyncBanner() + '<div class="frow"><div class="seg" role="tablist" aria-label="浏览方式">' + LI_TAB_LABEL.map((t) => '<button type="button" role="tab" data-act="libTab" data-v="' + t[0] + '" class="' + (S.lib.tab === t[0] ? 'on' : '') + '" aria-selected="' + (S.lib.tab === t[0]) + '">' + t[1] + '</button>').join('') + '</div><span class="lb-div" aria-hidden="true"></span>' +
    ['全部', 'Skill', 'Hook', '插件', '子代理', 'MCP'].map((k) => { const n = kindCount(k); return '<button type="button" class="chip sm' + (S.lib.kind === k ? ' on' : '') + '" data-act="libKind" data-v="' + k + '" aria-pressed="' + (S.lib.kind === k) + '">' + k + (n != null ? ' <span class="mono cap">' + TLU.num(n) + '</span>' : '') + '</button>'; }).join('') + '</div>' +
    '<div class="stack"><div class="row" style="align-items:baseline;flex-wrap:wrap;gap:6px 10px"><span class="serif" style="font-size:18px;font-weight:600">' + title + '</span><span class="cap">' + sub + '</span></div>' +
    (feat.length ? '<div class="lib-feat">' + feat.map(liFeat).join('') + '</div>' : empty(q ? '没有匹配「' + esc(q) + '」的资源。换个关键词，或清空搜索。' : S.lib.tab === 'local' ? '还没有本地生成的资源。在 生成工坊 里生成并通过自检后会出现在这里。' : '没有符合条件的资源')) +
    '<div class="two lb-two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">更多资源</span><span class="cap">' + (q ? '按相关度排序' : S.lib.tab === 'hot' ? '按安装量排序' : S.lib.tab === 'peer' ? '按 Star 排序' : '按更新时间排序') + ' · 中列为风险等级<span class="lb-ucap">，右列为安装量</span></span></div></div><div class="col" style="gap:0">' + (more.length ? more.map(liRow).join('') : '<span class="cap">没有更多了</span>') + '</div>' + (moreBtn ? '<div class="row" style="justify-content:center;padding-top:10px">' + moreBtn + '</div>' : '') + '</div>' +
    '<div class="card pad col lb-peers" data-tl="lib-facets"><span class="ct">目录分布</span><span class="lb-pintro">当前筛选下共 <b style="color:var(--ink-1)">' + TLU.num(fc.total) + '</b> 项' + (selKs && allKinds ? '，全部类型共 <b style="color:var(--ink-1)">' + TLU.num(tot) + '</b> 项' : '') + '，按类型：</span>' +
    (kinds.length ? kinds.map((r) => { const p = Math.max(0, Math.min(100, Math.round(r.count / tot * 100))); const dim = selKs && selKs.indexOf(r.value) < 0; return '<div class="col" data-tl="lib-facet" data-pct="' + p + '" style="gap:3px' + (dim ? ';opacity:.55' : '') + '"><div class="row" style="justify-content:space-between;font-size:12px"><b class="mono">' + esc(TL.li.kindLabel(r.value)) + '</b><span class="mono">' + TLU.num(r.count) + '<span class="cap"> · ' + p + '%</span></span></div><span class="lb-peer" role="img" aria-label="' + esc(TL.li.kindLabel(r.value)) + '：' + r.count + ' 项"><i style="width:' + p + '%"></i></span></div>'; }).join('') : '<span class="cap">—</span>') +
    '<span class="cap">许可：' + ((fc.license || []).slice(0, 3).map((r) => esc(r.value) + ' ' + TLU.num(r.count)).join(' · ') || '—') + '</span>' +
    '<div class="row lb-anon">' + ic('shield', 14, 'color:var(--good);margin-top:1px') + '<span>资源目录保存在本机；安装前先预览每一处变更，写入前自动备份，可随时撤销。</span></div></div></div></div></div>';
}
/* ---- first visit: one catalog sync when no network source was ever synced (fresh install: only the bundled seed + KB) ---- */
function liSyncBanner() {
  const y = S.li.sync; if (!y || !/^(starting|running|failed)$/.test(y.state)) return '';
  if (y.state === 'failed') return '<div class="row lb-anon" data-tl="lib-sync" data-state="failed" role="status">' + ic('alert', 14, 'color:var(--warn-m);margin-top:1px') + '<span>首次同步资源目录没有完成（' + esc((y.error && (y.error.message || y.error.code)) || '网络不可用') + '），先显示内置条目。<button type="button" class="lnk" data-act="liSyncRetry">重试</button></span></div>';
  return '<div class="row lb-anon" data-tl="lib-sync" data-state="running" role="status" aria-live="polite">' + ic('sync', 14, 'margin-top:1px') + '<span>正在首次同步资源目录' + (y.total ? ' · 已完成 <b class="mono">' + y.done + ' / ' + y.total + '</b> 个来源' : '') + '。完成前先显示内置条目（标有示例数据）。</span></div>';
}
function liSyncPaint() { const b = $('#content [data-tl="lib-sync"]'); if (b) b.outerHTML = liSyncBanner() || '<span hidden></span>'; else if (S.route === 'library' && MODAL_KEY == null) render(); }
function liSyncCount(st) {
  const by = (st && st.coverage && st.coverage.by_source) || {};
  const net = Object.keys(by).filter((k) => by[k].enabled !== false && !/^(bundle|kb)$/.test(by[k].kind || ''));
  return { net, done: net.filter((k) => by[k].last_ok_at || by[k].error).length, ever: net.some((k) => by[k].last_ok_at) || (st && st.last_sync_at != null) };
}
function liSyncPoll() {
  const y = S.li.sync; if (!y || y.state !== 'running') return;
  clearTimeout(y.timer);
  y.timer = setTimeout(() => {
    if (S.li.sync !== y) return;
    const job = y.job ? TL.li.send('GET', '/v1/catalog/jobs/' + encodeURIComponent(y.job)).then((r) => r.data, () => null) : Promise.resolve(null);
    Promise.all([TL.li.send('GET', '/v1/catalog/status').then((r) => r.data, () => null), job]).then(([st, jb]) => {
      if (S.li.sync !== y) return;
      if (st) { const c = liSyncCount(st); y.total = c.net.length; y.done = c.done; }
      const fin = jb ? /^(completed|failed|cancelled)$/.test(jb.status) : !y.job && st && st.last_sync_at != null;
      if (fin || Date.now() - y.t0 > 10 * 60000) {
        y.state = jb && jb.status !== 'completed' && !(st && liSyncCount(st).ever) ? 'failed' : 'done';
        if (y.state === 'failed') y.error = { message: (jb && jb.error) || '部分来源同步失败' };
        liInvalidate(); liSyncPaint(); if (S.route === 'library' && MODAL_KEY == null) render(); return;
      }
      liSyncPaint(); liSyncPoll();
    });
  }, y.every || 2500);
}
function liSyncStart(total) {
  const y = S.li.sync = { state: 'running', job: null, total: total || 0, done: 0, t0: Date.now(), every: 2500 };
  liSyncPaint();
  return TL.li.send('POST', '/v1/catalog/sync', {}).then((r) => { if (S.li.sync !== y) return; y.job = (r.data && r.data.job_id) || null; liSyncPoll(); }, (e) => {
    if (S.li.sync !== y) return;
    if (e.status === 409) { liSyncPoll(); return; }   // another catalog job is already syncing: follow it through /status
    y.state = TL.li.degraded(e) ? 'done' : 'failed'; y.error = e; liSyncPaint();
  });
}
function liSyncCheck() {
  if (S.li.sync) return;
  S.li.sync = { state: 'checking' };
  TL.li.send('GET', '/v1/catalog/status').then((r) => {
    const st = r.data || {}; const c = liSyncCount(st);
    if (c.ever || !c.net.length) { S.li.sync = { state: 'done' }; return; }
    liSyncStart(c.net.length);
  }, () => { S.li.sync = { state: 'done' }; });
}
const LI_DEMO_PAGE = PAGES.library;
function liPage() {
  const v = lvView('library');
  S.li.degraded = !!(v && !v.vm && v.state === 'error' && TL.li.degraded(v.error));
  if (S.li.degraded) {
    if (!S.li.errAt) S.li.errAt = Date.now();
    else if (Date.now() - S.li.errAt > 15000) { S.li.errAt = 0; TL.invalidate((r) => r.path.indexOf('/v1/catalog/') === 0); }
    return LI_DEMO_PAGE();
  }
  S.li.errAt = 0;
  if (v && v.vm) liSyncCheck();
  const st = liState(); const n = st.data ? (st.data.items || []).filter((i) => !/^(reverted|archived)$/.test(i.state)).length : null;
  return tbar('资源库', v && v.vm ? TLU.num(v.vm.total != null ? v.vm.total : v.vm.facets.total) + ' 项' : '', '<label class="row lb-q" style="height:28px;padding:0 10px;border-radius:9px;background:var(--surface);border:1px solid var(--line);color:var(--ink-3)">' + ic('search', 15) + '<span class="vh">搜索资源</span><input id="libQ" type="search" data-in="libQ" placeholder="搜索 Skill、Hook、插件、MCP…" value="' + esc(S.lib.q) + '" style="flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:13px;color:var(--ink-1)"></label><button type="button" class="btn" data-act="libInstalled">已安装 · <span id="libInstN">' + TLU.num(n) + '</span></button>') +
    '<div class="content" id="content">' + (v && !v.vm && v.state === 'loading' && S.li.lastVm ? liBody(S.li.lastVm) : TLU.body(v, (vm) => { S.li.lastVm = vm; return liBody(vm); })) + '</div>';
}
const liCard = (id) => { const v = TL_VIEWS.library; return v && v.vm ? liItems(v.vm).concat(v.vm.items).find((x) => x.item_id === id) || null : null; };

/* ---- item detail ---- */
function liDetailDraw(id) {
  const D = S.li.detail; if (!D || D.id !== id || MODAL_KEY !== 'libDetail') return;
  const x = D.data || D.card || { name: id };
  const head = modalHead(esc(x.name || id), x.kind ? esc(TL.li.kindLabel(x.kind)) + ' · ' + liSrc(x) + (x.version ? ' · v' + esc(String(x.version).slice(0, 12)) : '') + ' · 更新于 ' + liDay(x.updated_at) + liSeedTag(x) : '');
  if (!D.data) {
    const body = D.error ? (TL.li.degraded(D.error) ? '<div class="cap">' + TLU.sample() + ' 本机资源目录暂不可用，只显示列表中的摘要。</div><div class="lb-desc">' + esc(x.summary || '') + '</div>' : TLU.errorCard(D.error)) : TLU.skeleton();
    openModal(head + '<div class="mb col" style="gap:10px" data-tl="lib-detail">' + body + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">关闭</button></div>', 'wide'); MODAL_KEY = 'libDetail'; return;
  }
  const p = x.permissions || {}; const ins = x.install || {};
  const q = x.quality; const qNames = { source_read: '已读取来源', license_declared: '许可明确', body_available: '正文可用', compatibility_listed: '兼容范围明确', source_version_recorded: '固定版本可追溯' };
  const quality = q && Number.isFinite(q.score) ? '<div class="col" data-tl="lib-quality" style="gap:6px;padding:10px;border:1px solid var(--line);border-radius:8px"><b style="font-size:13px">资料完整度 ' + Math.round(q.score * 100) + ' / 100</b><div class="row" style="flex-wrap:wrap;gap:6px">' + Object.keys(qNames).map((k) => '<span class="tag">' + esc(qNames[k]) + ' · ' + ((q.dimensions || {})[k] ? '有' : '待补') + '</span>').join('') + '</div><span class="cap" style="font-size:11px">反映来源与文档是否齐全，实际适用性和效果需要验证。</span></div>' : '';
  const facts = [['类型', esc(TL.li.kindLabel(x.kind))], ['许可', esc(x.license || '未知')], ['作者', esc(x.author || '—')], ['Agent', esc(liAgents(x.agents))], ['风险', TLU.num(p.level != null ? p.level : x.risk_level) + (p.flags && p.flags.length ? ' · ' + esc(p.flags.join('、')) : '') + (p.estimate ? '<span class="cap">（估计）</span>' : '')], ['工具', esc((p.allowed_tools || []).join('、') || '—')], ['环境变量', esc((p.declared_env || []).join('、') || '—')], ['常驻', x.resident_tokens_est != null ? '约 ' + TLU.num(x.resident_tokens_est) + ' token' : '—']];
  const readme = x.readme ? '<div class="code" data-tl="lib-readme" style="max-height:min(260px,36vh)">' + x.readme.split('\n').map((l, i) => '<div><span class="n">' + (i + 1) + '</span><span class="t">' + (esc(l) || ' ') + '</span></div>').join('') + '</div>' : '<div class="cap" data-tl="lib-readme">许可不允许内嵌正文' + (x.url ? '，' + liLink(x.url, '查看来源') : '') + '</div>';
  const versions = (x.versions || []).length ? x.versions.slice(0, 8).map((r) => '<div class="row" style="justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--hair);font-size:12.5px;gap:8px"><b class="mono" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(String(r.version || r.version_id || '—').slice(0, 24)) + '</b><span class="mono cap">' + esc((r.commit_sha || '').slice(0, 7) || '—') + ' · ' + TLU.num(r.size) + ' B · ' + liDay(r.created_at) + '</span></div>').join('') : '<span class="cap">—</span>';
  const related = (x.related || []).slice(0, 5).map((r) => '<button type="button" class="chip sm" data-act="liDetail" data-id="' + esc(r.card.item_id) + '">' + esc(r.card.name) + '<span class="cap"> · ' + esc(r.relation === 'similar' ? '相似' : r.relation) + '</span></button>').join('');
  const why = !ins.installable ? (!ins.license_ok ? '许可不允许自动安装' : '该资源当前不可安装') : '';
  openModal(head + '<div class="mb col" style="gap:12px" data-tl="lib-detail"><div class="lb-desc">' + esc(x.summary || '') + '</div>' +
    '<div class="form" style="grid-template-columns:64px minmax(0,1fr);gap:6px 12px">' + facts.map((f) => '<span class="l">' + f[0] + '</span><span style="font-size:12.5px;min-width:0;word-break:break-word">' + f[1] + '</span>').join('') + '</div>' +
    quality + '<span class="eb">README</span>' + readme + '<span class="eb">版本</span><div data-tl="lib-versions">' + versions + '</div>' + (related ? '<span class="eb">相关资源</span><div class="row" style="flex-wrap:wrap;gap:6px">' + related + '</div>' : '') + '</div>' +
    '<div class="mf">' + (String(x.item_id).indexOf('local:') === 0 ? '<button type="button" class="btn gh" data-act="liRemoveLocal" data-id="' + esc(x.item_id) + '">移除本地条目</button>' : '') + (x.url ? liLink(x.url, ic('ext', 13) + '查看来源', 'btn gh') : '') + '<span style="flex:1"></span>' + (why ? '<span class="cap">' + why + '</span>' : '') + '<button type="button" class="btn" data-act="closeModal">关闭</button>' + (liInstalledId(x) ? '<span class="tag">已安装</span>' : '<button type="button" class="btn p" data-act="getLib" data-id="' + esc(x.item_id) + '"' + (why ? ' disabled' : '') + '>获取</button>') + '</div>', 'wide');
  MODAL_KEY = 'libDetail';
}

/* ---- install sheet (live) ---- */
const LI_STEPS = ['预览变更', '确认写入', '已写入', '7 天追踪'];
// R4-06: backend warnings arrive as codes (inventory_refresh_failed, already_present:<inv>:<name>, …): say them in words
const LI_WARN = { inventory_refresh_failed: '「已安装」列表暂未刷新，稍后会自动更新；文件已写入。', tracking_unavailable: '暂时无法开始 7 天追踪，安装本身不受影响。',
  exposure_unavailable: '暂时无法记录这次推荐的曝光，安装本身不受影响。', artifact_status_unavailable: '暂时无法更新生成工坊里的状态，安装本身不受影响。' };
function liWarn(w) {
  const s = String(w == null ? '' : w); if (LI_WARN[s]) return LI_WARN[s];
  const ap = /^already_present:([^:]*):(.*)$/.exec(s); if (ap) return '「' + (ap[2] || '该资源') + '」已经存在于 ' + (liAgentName(ap[1]) || '本机') + '，会跳过重复的部分。';
  return /^[a-z0-9_.:-]+$/.test(s) ? '后端返回了一条未识别的提示，安装结果以上方列表为准。' : s;
}
const liWarnRows = (ws) => { const out = (ws || []).map(liWarn); return out.filter((w, i) => w && out.indexOf(w) === i).map((w) => '<div class="cap" data-tl="inst-warn">' + esc(w) + '</div>').join(''); };
// the backend reports the backup dir as an absolute path with an unresolved <install_id> token: show it like the targets (~)
function liHomeOf(pv) {
  const t = ((pv && pv.targets) || []).find((x) => x.path && x.display && /^~\//.test(x.display) && x.path.endsWith(x.display.slice(1)));
  return t ? t.path.slice(0, t.path.length - t.display.length + 1) : null;
}
function liTilde(p, home) {
  let s = String(p || ''); if (!s) return s;
  if (home && (s === home || s.startsWith(home + '/'))) s = '~' + s.slice(home.length);
  else s = s.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, '~');
  return s;
}
const liBackupDir = (pv, iid) => { const d = pv && pv.backup_dir; if (!d) return '—'; const s = liTilde(d, liHomeOf(pv)); return iid ? s.replace('<install_id>', iid) : s.replace(/\/?<install_id>$/, '') + '/（本次安装编号）'; };
const liUniq = (xs, key) => xs.filter((x, i) => xs.findIndex((y) => key(y) === key(x)) === i);
function liProg(step) { return '<div class="inst-steps">' + LI_STEPS.map((s, i) => '<span class="' + (i + 1 < step ? 'done' : i + 1 === step ? 'cur' : '') + '"><span class="mono k">' + (i + 1 < step ? '✓' : i + 1) + '</span>' + s + '</span>' + (i < LI_STEPS.length - 1 ? '<i></i>' : '')).join('') + '</div>'; }
function liDiff(t) {
  return '<div class="code" style="max-height:min(260px,36vh)">' + t.lines.map((l) => l.gap ? '<div><span class="n">⋯</span><span class="t cap"> </span></div>' :
    '<div class="' + (l.op === '+' ? 'add' : l.op === 'ai' ? 'ai' : '') + '"' + (l.op === '-' ? ' style="background:var(--crit-bg)"' : '') + '><span class="n">' + (l.op === '+' ? '+' : l.op === '-' ? '−' : l.op === 'ai' ? '✦' : TLU.num(l.n)) + '</span><span class="t"' + (l.op === '-' ? ' style="text-decoration:line-through;color:var(--crit)"' : '') + '>' + (esc(l.text) || ' ') + '</span></div>').join('') + '</div>';
}
function liDraw() {
  const st = INST, x = st.card, name = esc(x.name);
  const close = '<button type="button" class="btn" data-act="closeModal">' + (st.step === 3 ? '完成' : '取消') + '</button>';
  let html;
  if (st.error) {
    const msg = st.error.code === 'risk_blocked' ? '风险等级过高，已阻止写入。' : st.error.code === 'locked' ? '另一次安装正在进行，稍后再试。' : st.error.code === 'nothing_to_apply' ? '没有选中任何要写入的内容。' : null;
    html = modalHead('安装 ' + name, '没有写入任何文件') + liProg(Math.max(1, st.step)) + '<div class="mb col" style="gap:10px" data-tl="inst-error">' + (msg ? '<div class="tl-banner crit" role="alert">' + msg + '</div>' : TLU.errorCard(st.error)) + '</div><div class="mf">' + (st.preview ? '<button type="button" class="btn gh" data-act="instBack">返回预览</button>' : '') + close + '</div>';
  } else if (st.step === 0) {
    html = modalHead('预览变更 · ' + name, '正在生成安装计划…') + liProg(1) + '<div class="mb" data-tl="inst-loading">' + TLU.skeleton() + '</div><div class="mf">' + close + '</div>';
  } else if (st.step === 9) {
    const pl = st.plan || {};
    html = modalHead('安装 ' + name, pl.status === 'link_only' ? '该资源只能按来源说明手动安装' : '没有可自动写入的目标') + '<div class="mb col" style="gap:8px" data-tl="inst-manual" data-status="' + esc(pl.status || '') + '">' + (st.reason ? '<div class="tl-banner" role="status" data-tl="inst-reason">' + esc(st.reason) + '</div>' : '') + liWarnRows(pl.warnings) + (pl.links || []).map((u) => liLink(u, esc(u), 'lnk mono')).join('') + '</div><div class="mf">' + close + '</div>';
  } else if (st.step === 1) {
    const pv = st.preview, ts = TL.li.helpers.liTargets(pv), tot = pv.totals || {};
    const sc = $('#modal .mb'); const top = sc ? sc.scrollTop : 0;
    const blocks = ts.map((t) => {
      const off = st.sel.disabled.has(t.idx);
      const unitsBox = t.units.length > 1 ? '<div class="row" style="flex-wrap:wrap;gap:6px 12px">' + t.units.map((u) => { const chosen = st.sel.units[t.idx] ? st.sel.units[t.idx].has(u.id) : u.selected !== false; return '<label class="row cap" style="gap:4px"><input type="checkbox" data-chg="liUnit" data-i="' + t.idx + '" data-u="' + esc(u.id) + '"' + (chosen ? ' checked' : '') + (off ? ' disabled' : '') + ' style="accent-color:var(--ink-1)">' + esc(u.label || u.id) + '</label>'; }).join('') + '</div>' : '';
      return '<div class="col" style="gap:6px" data-tl="inst-target" data-idx="' + t.idx + '"><div class="row" style="padding:6px 10px;border-radius:8px;background:var(--sunken);gap:8px"><input type="checkbox" data-chg="liTarget" data-i="' + t.idx + '"' + (off ? '' : ' checked') + (t.mappable ? '' : ' disabled') + ' aria-label="写入 ' + esc(t.display) + '" style="accent-color:var(--ink-1)">' + ic('file', 14) + '<span class="mono" style="font-size:12px;flex:1;min-width:0;word-break:break-all">' + esc(t.display) + '</span><span class="tag">' + esc(liAgentName(t.agent)) + '</span><span class="mono cap">+' + t.adds + (t.dels ? ' −' + t.dels : '') + '</span></div>' +
        (t.conflict ? '<div class="tl-banner crit">' + esc(t.conflict.message || t.conflict.code) + '</div>' : '') + (!t.mappable ? '<div class="cap">' + esc(t.reason || '该 Agent 不支持此类资源') + '</div>' : off ? '<div class="cap">已取消，不写入这个文件</div>' : unitsBox + liDiff(t)) + '</div>';
    }).join('');
    const risk = pv.risk || {};
    html = modalHead('预览变更 · ' + name, '将修改 ' + TLU.num(tot.files) + ' 个文件 · <b class="mono" style="color:var(--good)">+' + TLU.num(tot.adds) + ' 行</b>' + (tot.dels ? ' · <b class="mono" style="color:var(--crit)">−' + TLU.num(tot.dels) + ' 行</b>' : '') + ' · 风险 ' + esc(LI_RISK[risk.level] || risk.level || '—') + ' · 确认前不会改动任何文件') + liProg(1) +
      '<div class="mb col" style="gap:12px" data-tl="inst-preview">' + (st.notice ? '<div class="tl-banner" role="alert" data-tl="inst-stale">' + esc(st.notice) + '</div>' : '') + blocks + liWarnRows(pv.warnings) +
      '<div class="cap" style="font-size:11.5px">取消勾选的文件或片段不会写入；紫色 ✦ 行是按你的会话改写的内容。' + (st.busy ? ' <b data-tl="inst-busy">正在更新预览…</b>' : '') + '</div></div>' +
      '<div class="mf">' + close + '<button type="button" class="btn p" data-act="instNext" autofocus' + (!pv.can_apply || st.busy || !tot.files ? ' disabled' : '') + '>下一步</button></div>';
    openModal(html, 'wide'); MODAL_KEY = 'install';
    const nc = $('#modal .mb'); if (nc) nc.scrollTop = top;
    return;
  } else if (st.step === 2) {
    const pv = st.preview, tot = pv.totals || {}, risk = pv.risk || {};
    const paths = liUniq(TL.li.helpers.liTargets(pv).filter((t) => !st.sel.disabled.has(t.idx) && t.mappable), (t) => t.display);
    const blocked = pv.requires_override && !st.overrideRisk;
    html = modalHead('写入 ' + paths.length + ' 个文件？', '修改前会自动备份，随时可以撤销') + liProg(2) +
      '<div class="mb col" style="gap:12px" data-tl="inst-confirm"><div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:8px 12px"><span class="l">写入</span><span class="mono col code-t" style="font-size:12px;word-break:break-all;gap:2px">' + paths.map((t) => esc(t.display)).join('<br>') + '</span><span class="l">备份</span><span class="mono" style="font-size:12px;color:var(--ink-3);word-break:break-all">' + esc(liBackupDir(pv)) + '</span><span class="l">变更</span><span class="mono" style="font-size:12px">+' + TLU.num(tot.adds) + (tot.dels ? ' / −' + TLU.num(tot.dels) : '') + ' 行</span><span class="l">风险</span><span style="font-size:12px">' + esc(LI_RISK[risk.level] || risk.level || '—') + (risk.flags && risk.flags.length ? ' · ' + esc(risk.flags.join('、')) : '') + '</span></div>' +
      (pv.requires_override ? '<label class="row" style="align-items:flex-start;gap:8px;padding:10px 12px;border-radius:9px;border:1px solid var(--line)"><input type="checkbox" data-chg="liOverride"' + (st.overrideRisk ? ' checked' : '') + ' style="margin-top:2px;accent-color:var(--ink-1)"><span class="col" style="gap:2px"><b style="font-size:12.5px">我已了解风险，仍然写入</b><span class="cap" style="font-size:11.5px">该资源的风险等级需要你明确确认。</span></span></label>' : '') +
      (pv.requires_trust ? '<div class="row cap" style="font-size:11.5px">' + ic('info', 13, 'margin-top:2px') + '<span>写入后需要在对应 Agent 里信任该项目配置才会生效。</span></div>' : '') +
      '<div class="row cap" style="font-size:11.5px;align-items:flex-start">' + ic('info', 13, 'margin-top:2px') + '<span>这是整个流程里唯一真正写盘的一步，写入的是预览中确认过的内容。</span></div></div>' +
      '<div class="mf"><button type="button" class="btn gh" data-act="instBack">返回</button>' + close + '<button type="button" class="btn p" data-act="instDo" autofocus' + (blocked || st.busy ? ' disabled' : '') + '>' + (st.busy ? '正在写入…' : '确认写入') + '</button></div>';
  } else {
    const r = st.result || {}; const left = r.undo_until_ms ? Math.max(0, Math.ceil((r.undo_until_ms - Date.now()) / 1000)) : 0;
    html = modalHead('已写入 ' + TLU.num((r.written || []).length) + ' 个文件', left && left <= 600 ? left + ' 秒内可直接撤销' : '可在「已安装」里随时撤销') + liProg(3) +
      '<div class="mb col" style="gap:10px" data-tl="inst-done">' + liUniq(r.written || [], (w) => w.display || w.path).map((w) => '<div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:4px 12px"><span class="l">写入</span><span class="mono code-t" style="font-size:12px;word-break:break-all">' + esc(w.display || w.path) + '</span><span class="l">备份</span><span class="mono" style="font-size:12px;color:var(--ink-3);word-break:break-all">' + esc(w.backup_path ? liTilde(w.backup_path, liHomeOf(st.preview)) : '新建文件，撤销时删除') + '</span></div>').join('') +
      liWarnRows(r.warnings) + (r.requires_trust_note ? '<div class="cap">' + esc(r.requires_trust_note) + '</div>' : '') +
      '<div class="row" style="gap:8px;padding:10px 12px;border-radius:9px;background:var(--sunken);font-size:12.5px;align-items:flex-start">' + ic('clock', 14, 'margin-top:2px') + '<span><b>' + (r.state === 'observing' ? '观察期已开始' : '已安装') + '</b><span class="cap" style="display:block;margin-top:2px">安装记录 ' + esc(r.install_id) + ' 已写入台账。</span></span></div></div>' +
      '<div class="mf"><button type="button" class="btn" data-act="instUndo">撤销</button><span style="flex:1"></span><button type="button" class="btn p" data-act="instClose" autofocus>完成</button></div>';
  }
  openModal(html, 'wide'); MODAL_KEY = 'install';
}
function liRepreview() {
  const st = INST; st.busy = true; liDraw();
  TL.li.preview(st.plan.plan_id, st.sel).then((pv) => { if (INST !== st) return; st.preview = pv; st.busy = false; liDraw(); }, (e) => { if (INST !== st) return; st.busy = false; st.error = e; liDraw(); });
}
function liDemoExtra(x) { return { id: x.name, kind: TL.li.kindLabel(x.kind), desc: x.summary || '', src: x.origin === 'local' ? '本地生成' : (x.license || '社区'), compat: liAgents(x.agents), rec: null }; }
function liInstall(x) {
  // x.source: {type: 'candidate' | 'catalog' | 'artifact', id}; x.surface: where the install started (A7 | lite | A8 | A9)
  const st = { live: true, card: x, step: 0, t: Date.now(), sel: { disabled: new Set(), units: {} }, busy: true, overrideRisk: false, surface: x.surface || 'A8' };
  INST = st; liDraw();
  TL.li.prepare(x.source || { type: 'catalog', id: x.item_id }, { itemAgents: x.agents, defaultOff: (plan) => (plan.targets || []).filter((t) => t.agent !== (plan.agents || [])[0]).map((t) => t.idx) }).then((r) => {
    if (INST !== st) return;
    st.plan = r.plan; st.preview = r.preview; st.reason = r.reason || null; st.busy = false; st.step = r.preview ? 1 : 9;
    if (r.sel) st.sel.disabled = new Set(r.sel.disabled);
    liDraw();
  }, (e) => {
    if (INST !== st) return;
    if (TL.li.degraded(e) && !x.source) { INST = null; closeModal(); liBase.openInstall(null, liDemoExtra(x)); if (MODAL_KEY === 'install') liMarkSample(); return; }
    st.busy = false; st.error = e; liDraw();
  });
}
function liUndo(iid, title) {
  return TL.li.revert(iid).then((r) => {
    S.li.inst.forEach((v, k) => { if (v === iid) S.li.inst.delete(k); });
    S.instLog.unshift({ t: '撤销 ' + (title || iid), when: '刚刚' });
    liInvalidate(); closeModal(); render(); toast(r.ok === false ? '部分文件未能撤销，请查看「已安装」' : '已撤销「' + (title || iid) + '」，文件已从备份恢复');
    return r.ok !== false;
  }, (e) => {
    const d = e.detail || {}; const bad = (d.results || []).filter((x) => x.status !== 'reverted' && x.status !== 'already_reverted');
    openModal(modalHead('无法自动撤销', e.code === 'revert_refused' ? '这些文件在安装后被改动过，Orbit 不会覆盖你的修改' : esc(e.message || e.code)) + '<div class="mb col" style="gap:8px" data-tl="revert-refused">' + bad.map((x) => '<div class="col" style="gap:4px"><span class="mono code-t" style="font-size:12px">' + esc(x.path) + '</span>' + (x.diff && x.diff.lines ? liDiff({ lines: x.diff.lines.map((l) => ({ n: l.n, op: l.op, text: String(l.text == null ? '' : l.text), gap: !!l.gap })) }) : '') + (x.manual_steps || []).map((s) => '<span class="cap">· ' + esc(s) + '</span>').join('') + '</div>').join('') + (bad.length ? '' : TLU.errorCard(e)) + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">知道了</button></div>');
    return false;
  });
}

/* ---- installed sheet (install state + ledger) ---- */
function liInstalledSheet(more) {
  const S2 = S.li.sheet = more ? S.li.sheet : { state: null, ledger: [], next: null, error: null };
  const draw = () => {
    if (S.li.sheet !== S2) return;
    const live = (S2.state ? S2.state.items || [] : []).filter((i) => i.state !== 'archived');
    const rows = live.map((i) => '<div class="row" style="justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--hair);font-size:13px;gap:8px"><span style="min-width:0">' + esc(i.title || i.source_id) + '<span class="cap">（' + esc(TL.li.kindLabel(i.kind)) + '，' + esc(liAgents(i.agents)) + '）</span></span><span class="row" style="gap:6px"><span class="tag">' + esc({ installed: '已安装', observing: '观察中', kept: '已保留', idle: '闲置', reverted: '已撤销' }[i.state] || i.state) + '</span>' + (i.state === 'reverted' ? '' : '<button type="button" class="btn sm" data-act="liRevert" data-id="' + esc(i.install_id) + '">撤销</button>') + '</span></div>').join('');
    const led = S2.ledger.map((e) => '<div class="tl-ev">' + liDay(e.ts) + ' ' + TLU.hm(e.ts) + ' · ' + esc(e.action) + ' · ' + esc(e.op || '') + ' · ' + esc(e.path || '') + '</div>').join('');
    openModal(modalHead('已安装 · ' + (S2.state ? live.filter((i) => i.state !== 'reverted').length : '…'), '来自本机安装台账') + '<div class="mb col" style="gap:6px" data-tl="installed">' + (S2.error ? (TL.li.degraded(S2.error) ? '<div class="cap" data-lv="na">本机安装台账暂不可用，稍后再试。</div>' : TLU.errorCard(S2.error)) : !S2.state ? TLU.skeleton() : rows || '<span class="cap">还没有通过 Orbit 安装的资源</span>') +
      '<span class="eb" style="margin-top:8px">操作记录</span><div data-tl="ledger">' + (led || '<span class="cap">—</span>') + '</div>' + (S2.next ? '<button type="button" class="btn sm" data-act="liLedgerMore">加载更早</button>' : '') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
    MODAL_KEY = 'libInstalled';
  };
  if (!more) draw();
  const jobs = more ? [Promise.resolve(null), TL.li.ledger({ limit: 20, before: S2.next })] : [TL.li.state(), TL.li.ledger({ limit: 20 })];
  Promise.all(jobs).then(([st, lg]) => { if (st) S2.state = st; S2.ledger = S2.ledger.concat(lg.entries || []); S2.next = lg.next || null; draw(); }, (e) => {
    if (S.li.sheet !== S2) return;
    S2.error = e; draw();   // personal data: an honest error / empty sheet, never the demo list
  });
}

const liBase = { openInstall, libInstalled: ACT.libInstalled, studioInstall: ACT.studioInstall, studioUndo: ACT.studioUndo };
// A9 生成工坊「安装」: a reviewed AI artifact goes through the same sheet with source {type: 'artifact'}; without a live
// artifact (mock run, job still running) the demo sheet stays.
function liStudioInstall(el, e) {
  const run = S.studio && S.studio.run; const art = run && run.live && run.art && run.art.artifact_id ? run.art : null;
  if (!art || typeof liInstall !== 'function') return liBase.studioInstall(el, e);
  if (!run.done) { toast('生成完成后才能安装'); return; }
  if (run.installed) { toast('已经安装过了；要重装先撤销'); return; }
  liInstall({ item_id: 'art:' + art.artifact_id, name: art.title || art.name || (S.studio.type + ' · ' + art.artifact_id), kind: art.kind || null, summary: art.summary || '', source: { type: 'artifact', id: art.artifact_id }, surface: 'A9',
    onDone: (res) => { run.installed = res.install_id; run.liveInstall = res.install_id; if (typeof refreshStudio === 'function') refreshStudio(); } });
}
function liStudioUndo(el, e) {
  const run = S.studio && S.studio.run;
  if (!run || !run.liveInstall) return liBase.studioUndo(el, e);
  liUndo(run.liveInstall, S.studio.type).then((ok) => { if (ok) { run.installed = null; run.liveInstall = null; if (typeof refreshStudio === 'function') refreshStudio(); } });
}
// A demo sheet opened while the live routes are degraded carries the 示例数据 badge under its title.
function liMarkSample() { const mh = $('#modal .mh h2'); if (mh && !$('#modal [data-tl="sample"]')) mh.insertAdjacentHTML('afterend', '<div>' + TLU.sample() + '</div>'); }
if (TL.mode === 'live') {
  PAGES.library = TL_PAGES.library = liPage;
  const base = Object.assign({}, ACT), baseDraw = drawInstall, r96 = render;
  const isLive = () => !S.li.degraded && TL_VIEWS.library && TL_VIEWS.library.vm;
  const liveInst = () => INST && INST.live;
  drawInstall = function () { if (liveInst()) return liDraw(); baseDraw(); if (S.li.degraded && S.route === 'library') liMarkSample(); };
  render = function () {
    r96();
    if (S.route !== 'library' || !S.li.degraded) return;
    // no status strip on screen (nothing else to report): add one so the demo catalog still carries its 示例数据 badge
    const c = $('#content'); if (!c) return;
    const strip = c.querySelector(':scope > [data-tl="strip"]');
    if (!strip) c.insertAdjacentHTML('afterbegin', '<div class="tl-strip" data-tl="strip"><div>' + TLU.sample() + '</div></div>');
    else if (!strip.querySelector('[data-tl="sample"]')) strip.insertAdjacentHTML('beforeend', '<div>' + TLU.sample() + '</div>');
  };
  Object.assign(ACT, {
    libQ: (el, e) => {
      S.lib.q = el.value; if (e && e.isComposing) return;
      if (!isLive()) return base.libQ(el, e);
      clearTimeout(S.li.qT); S.li.qT = setTimeout(() => { S.li.q = S.lib.q.trim(); const c = $('#content'); if (c && S.route === 'library') { renderMain(); const q = $('#libQ'); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } } }, 280);
    },
    libHide: (el) => { if (!isLive()) return base.libHide(el); const id = el.dataset.id; S.libHide.add(id); render(); toast('已隐藏这一项', { act: '撤销', sec: 8, onAct: () => { S.libHide.delete(id); render(); } }); },
    liMore: () => {
      const v = TL_VIEWS.library; if (!v || !v.vm) return;
      const r = liReq(), key = liReqKey(r);
      const m = S.li.more && S.li.more.key === key ? S.li.more : (S.li.more = { key, items: [], next: v.vm.next, loading: false });
      if (m.loading || !m.next) return;
      m.loading = true; render();
      TL.li.send('GET', r.path, null, { query: Object.assign({}, r.query, { cursor: m.next }) }).then((res) => { m.items = m.items.concat(res.data.items || []); m.next = res.data.next_cursor || null; }, (e) => toast('加载失败：' + (e.message || e.code))).then(() => { m.loading = false; if (S.route === 'library') render(); });
    },
    liDetail: (el) => {
      const id = el.dataset.id; const card = liCard(id);
      S.li.detail = { id, card, data: null, error: null };
      MODAL_KEY = 'libDetail'; liDetailDraw(id);
      TL.li.item(id).then((d) => { if (S.li.detail && S.li.detail.id === id) { S.li.detail.data = d; liDetailDraw(id); } }, (e) => { if (S.li.detail && S.li.detail.id === id) { S.li.detail.error = e; liDetailDraw(id); } });
    },
    liRemoveLocal: (el) => { const id = el.dataset.id; TL.li.removeLocal(id).then(() => { closeModal(); liInvalidate(); render(); toast('已从本地资源目录移除'); }, (e) => toast('移除失败：' + (e.message || e.code))); },
    getLib: (el) => {
      const card = isLive() ? liCard(el.dataset.id) || (S.li.detail && S.li.detail.id === el.dataset.id ? S.li.detail.data || S.li.detail.card : null) : null;
      if (!card) return base.getLib(el);
      if (liInstalledId(card)) { toast('「' + card.name + '」已经安装'); return; }
      liInstall(Object.assign({}, card, { surface: S.route === 'l-library' || /^l-/.test(S.route) ? 'lite' : 'A8' }));
    },
    liRevert: (el) => { const id = el.dataset.id; liUndo(id, null).then(() => { if (S.li.sheet) liInstalledSheet(); }); },
    libInstalled: () => liInstalledSheet(false),
    studioInstall: liStudioInstall, studioUndo: liStudioUndo,
    liOpen: (el) => { const url = el.dataset.url; if (/^https?:\/\//.test(url || '')) ORBIT.native.request('openExternal', { url }); },
    liSyncRetry: () => { S.li.sync = null; liSyncStart(0); },
    liLedgerMore: () => liInstalledSheet(true),
    liTarget: (el) => { if (!liveInst() || INST.busy) return; const i = +el.dataset.i; if (el.checked) INST.sel.disabled.delete(i); else INST.sel.disabled.add(i); INST.notice = null; liRepreview(); },
    liUnit: (el) => {
      if (!liveInst() || INST.busy) return; const i = +el.dataset.i; const t = (INST.preview.targets || []).find((x) => x.idx === i); if (!t) return;
      const set = INST.sel.units[i] || (INST.sel.units[i] = new Set(t.units.filter((u) => u.selected !== false).map((u) => u.id)));
      if (el.checked) set.add(el.dataset.u); else set.delete(el.dataset.u);
      INST.notice = null; liRepreview();
    },
    liOverride: (el) => { if (liveInst()) { INST.overrideRisk = el.checked; liDraw(); } },
    instNext: (el, e) => { if (!liveInst()) return base.instNext(el, e); if (INST.busy || INST.step !== 1 || Date.now() - INST.t < 400) return; INST.step = 2; INST.t = Date.now(); liDraw(); },
    instBack: (el, e) => { if (!liveInst()) return base.instBack(el, e); if (INST.busy || Date.now() - INST.t < 400) return; INST.error = null; INST.step = 1; INST.t = Date.now(); liDraw(); },
    instDo: (el, e) => {
      if (!liveInst()) return base.instDo(el, e);
      const st = INST; if (st.busy || st.step !== 2 || Date.now() - st.t < 400) return;
      st.busy = true; liDraw();
      TL.li.apply(st).then((r) => {
        if (INST !== st) return; st.busy = false; st.t = Date.now();
        if (r.stale) { st.preview = r.preview; st.step = 1; st.notice = '文件在预览之后被改动过，已按当前内容重新生成预览，请再确认一次。'; liDraw(); return; }
        st.result = r.result; st.step = 3; S.li.inst.set(st.card.item_id, r.result.install_id);
        if (st.card.onDone) st.card.onDone(r.result);
        S.instLog.unshift({ t: '安装 ' + st.card.name, when: '刚刚', target: (r.result.written || []).map((w) => w.display).join('、') });
        liInvalidate(); renderMain(); liDraw();
      }, (err) => { if (INST !== st) return; st.busy = false; st.error = err; liDraw(); });
    },
    instUndo: (el, e) => { if (!liveInst()) return base.instUndo(el, e); const st = INST; if (!st.result || Date.now() - st.t < 400) return; INST = null; liUndo(st.result.install_id, st.card.name); },
    instClose: (el, e) => { if (!liveInst()) return base.instClose(el, e); const st = INST; if (Date.now() - st.t < 400) return; closeModal(); INST = null; render(); if (st.result) toast('已安装「' + st.card.name + '」', { act: '撤销', sec: 10, onAct: () => liUndo(st.result.install_id, st.card.name) }); }
  });
}
