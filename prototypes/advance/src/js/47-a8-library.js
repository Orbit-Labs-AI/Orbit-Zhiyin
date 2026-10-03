/* ============ A8 library ============ */
// Installed state lives in S.libInst (51-install.js); hidden items in S.libHide — LIB itself is never spliced, so the
// 「和你相似的人」statistics stay put when an item is hidden (BUG-31). Match score = 行为相似 ×0.5 + 痛点覆盖 ×0.3 +
// 社区效果 ×0.2, shown as a three-segment bar everywhere the score appears, so the ring's hidden breakdown is gone (A8-V01).
S.libInst = S.libInst || new Set();
S.libHide = S.libHide || new Set();
S.lib.sort = S.lib.sort || 'pain';
const LIB_W = [['行为相似', 0.5], ['痛点覆盖', 0.3], ['社区效果', 0.2]];
const LIB_SEG = ['var(--ink-1)', 'var(--h3)', 'var(--ink-4)'];
const libParts = (x) => LIB_W.map((w, i) => Math.round(x.sc[i] * w[1]));
const libInst = (x) => S.libInst.has(x.id);
// Share of all anonymous users (not just your persona) that run the item: the peer share is a lift over this (A8-V03).
const libAll = (x) => Math.max(2, Math.round(x.peer * 0.46 + 3));
const LIB_BASE = ['design-review（Skill）', 'browser（MCP）', 'block-claude-md（Hook）', 'commit-format（Hook）', 'zh-default（规则）', 'surge-cli（插件）', 'gh-helper（插件）', 'arxiv-reader（MCP）', 'pdf-tools（插件）', 'latex-lint（Hook）', 'daily-sync（Skill）'];
const libLiveMode = () => { try { return !!LV.live; } catch (e) { return false; } };
// One list behind both the toolbar count and the 已安装 sheet (BUG-29).
function installedItems() {
  const recs = RECS.filter((r) => S.installed.has(r.id)).map((r) => ({ t: r.title.split('：')[0] + '（' + r.type + '，Orbit 安装）', undo: 'uninstall', id: r.id }));
  const libs = LIB.filter(libInst).map((x) => ({ t: x.id + '（' + x.kind + '，资源库）', undo: 'libUninstall', id: x.id }));
  const studio = [...S.libInst].filter((k) => /^studio:/.test(k)).map((k) => ({ t: k.slice(7) + '（生成工坊）', undo: 'studioUninstall', id: k }));
  return recs.concat(libs, studio, libLiveMode() ? [] : LIB_BASE.map((t) => ({ t })));   // live: never the demo installs
}
function matchBar(x, cls) { const p = libParts(x); return '<span class="lb-bar' + (cls ? ' ' + cls : '') + '" role="img" aria-label="匹配度 ' + x.m + '：' + LIB_W.map((w, i) => w[0] + ' ' + p[i]).join('，') + '">' + p.map((v, i) => '<i style="width:' + v + '%;background:' + LIB_SEG[i] + '"></i>').join('') + '</span>'; }
function libBody() {
  const Lb = S.lib; const q = Lb.q.trim().toLowerCase(); const p = personaNow();
  let items = LIB.filter((x) => !S.libHide.has(x.id) && (Lb.kind === '全部' || x.kind === Lb.kind) && (!q || (x.id + x.desc + x.kind + x.why.join('')).toLowerCase().includes(q)));
  if (Lb.tab === 'for') { const key = Lb.sort === 'match' ? (x) => x.m : Lb.sort === 'users' ? (x) => x.users : (x) => x.sc[1] * 1000 + x.m; items.sort((a, b) => key(b) - key(a)); }
  else if (Lb.tab === 'peer') items = items.filter((x) => x.peer).sort((a, b) => b.peer - a.peer);
  else if (Lb.tab === 'hot') items = items.filter((x) => x.users).sort((a, b) => b.users - a.users);
  else items = items.filter((x) => x.local);
  const feat = items.slice(0, 3), more = items.slice(3);
  const getBtn = (x) => libInst(x) ? '<span class="row" style="gap:4px"><span class="tag">已安装</span><button type="button" class="btn sm gh" data-act="libUninstall" data-id="' + x.id + '">撤销</button></span>' : '<button type="button" class="btn sm p" data-act="getLib" data-id="' + x.id + '">' + (x.local ? '安装' : '获取') + '</button>';
  const title = Lb.tab === 'for' ? '为「' + (p.ok ? p.zh : '你') + '」精选' : Lb.tab === 'peer' ? '和你同类型的人在用' : Lb.tab === 'hot' ? '社区热门' : '你的本地 Agent 生成的';
  const sub = Lb.tab === 'for' ? (p.ok ? '依据人格 ' + p.code + '、近 30 天的摩擦和已安装内容' : '人格尚未分类，只按近 30 天的摩擦和已安装内容推荐') : Lb.tab === 'peer' ? '来自开启匿名贡献的同类型用户（示例）' : Lb.tab === 'hot' ? '按安装量排序（示例）' : '只在本机，不上传';
  const sortSeg = Lb.tab === 'for' ? '<div class="seg lb-sort" role="tablist" aria-label="排序">' + [['pain', '解决你的问题'], ['match', '综合匹配'], ['users', '社区安装量']].map((s) => '<button type="button" role="tab" data-act="libSort" data-v="' + s[0] + '" class="' + (Lb.sort === s[0] ? 'on' : '') + '" aria-selected="' + (Lb.sort === s[0]) + '">' + s[1] + '</button>').join('') + '</div>' : '';
  const legend = '<div class="lb-legend cap">匹配度 = ' + LIB_W.map((w, i) => '<span class="row" style="gap:4px"><i style="background:' + LIB_SEG[i] + '"></i>' + w[0] + ' ×' + w[1] + '</span>').join('<span>+</span>') + '</div>';
  const featCard = (x) => { const parts = libParts(x); return '<div class="card lb-card"><div class="lb-head"><div class="mono row cap lb-meta">' + ic(x.icon, 13, 'color:var(--ink-1)') + '<b style="font-family:var(--font-sans);color:var(--ink-2)">' + x.kind + '</b><span>·</span><span>' + x.src + '</span>' + (Lb.tab === 'for' ? '<span style="margin-left:auto" class="mono" data-tf="match|' + x.id + '" tabindex="0">' + (Lb.sort === 'pain' ? '痛点覆盖 <b>' + x.sc[1] + '</b>' : Lb.sort === 'users' ? (x.users ? fmt(x.users) + ' 安装' : '本机') : '匹配 <b>' + x.m + '</b>') + '</span>' : '') + '</div><div class="mono lb-id">' + x.id + '</div><div class="lb-desc">' + esc(x.desc) + '</div>' +
    '<div class="lb-match" data-tf="match|' + x.id + '" tabindex="0"><b class="mono">' + x.m + '</b><span class="col" style="flex:1;gap:3px;min-width:0">' + matchBar(x) + '<span class="mono cap lb-parts">' + LIB_W.map((w, i) => w[0].slice(0, 2) + ' ' + parts[i]).join(' · ') + '</span></span></div></div>' +
    '<div class="lb-body"><span class="eb">解决你的问题</span>' + x.why.map((w) => '<span class="row lb-why">' + ic('check', 13, 'margin-top:2px;color:var(--ink-1);flex:none') + esc(w) + '</span>').join('') + '<div class="row lb-foot"><span class="cap lb-fc">' + x.compat + '</span><span style="flex:1"></span><span class="mono cap lb-fc">' + (x.users ? fmt(x.users) + ' 安装' : '本机') + '</span><span class="row lb-acts"><button type="button" class="btn sm gh" data-act="libHide" data-id="' + x.id + '">不感兴趣</button>' + getBtn(x) + '</span></div></div></div>'; };
  const moreRow = (x) => '<div class="lb-row"><span class="lb-ico">' + ic(x.icon, 15) + '</span><div style="min-width:0"><div class="row" style="gap:6px"><b class="mono lb-nm">' + x.id + '</b><span class="bdg">' + x.kind + '</span>' + (x.local ? '<span class="aib">本地生成</span>' : '') + '</div><div class="cap lb-ell">' + esc(x.desc) + '</div></div><div class="row lb-m" style="gap:6px" data-tf="match|' + x.id + '" tabindex="0">' + matchBar(x, 'sm') + '<b class="mono lb-mv">' + x.m + '</b></div><span class="mono cap lb-users">' + (x.users ? (x.users >= 1000 ? f1(x.users / 1000) + 'k' : x.users) : '本机') + '</span>' + getBtn(x) + '</div>';
  const peers = LIB.filter((x) => x.peer).sort((a, b) => b.peer - a.peer).slice(0, 3);
  return '<div class="frow"><div class="seg" role="tablist" aria-label="浏览方式">' + [['for', '为你推荐'], ['peer', '同类型用户在用'], ['hot', '热门'], ['local', '本地生成']].map((t) => '<button type="button" role="tab" data-act="libTab" data-v="' + t[0] + '" class="' + (Lb.tab === t[0] ? 'on' : '') + '" aria-selected="' + (Lb.tab === t[0]) + '">' + t[1] + '</button>').join('') + '</div><span class="lb-div" aria-hidden="true"></span>' + ['全部', 'Skill', 'Hook', '插件', '子代理', 'MCP'].map((k) => '<button type="button" class="chip sm' + (Lb.kind === k ? ' on' : '') + '" data-act="libKind" data-v="' + k + '" aria-pressed="' + (Lb.kind === k) + '">' + k + '</button>').join('') + '</div>' +
    '<div class="stack"><div class="row" style="align-items:baseline;flex-wrap:wrap;gap:6px 10px"><span class="serif lb-title">' + title + '</span><span class="cap">' + sub + (q ? ' · 搜索「' + esc(Lb.q.trim()) + '」' + items.length + ' 项' : '') + '</span><span style="flex:1"></span>' + sortSeg + '</div>' + legend +
    (feat.length ? '<div class="lib-feat">' + feat.map(featCard).join('') + '</div>' : empty(q ? '没有匹配「' + esc(Lb.q.trim()) + '」的资源。换个关键词，或清空搜索。' : S.libHide.size ? '这一类的资源都被标为「不感兴趣」了。<button type="button" class="lnk" data-act="libUnhide" style="margin-left:6px">恢复</button>' : '没有符合条件的资源')) +
    '<div class="two lb-two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">更多匹配</span><span class="cap">' + (Lb.tab === 'for' ? (Lb.sort === 'pain' ? '按痛点覆盖排序' : Lb.sort === 'users' ? '按社区安装量排序' : '按综合匹配排序') : Lb.tab === 'peer' ? '按同类用户占比排序' : Lb.tab === 'hot' ? '按安装量排序' : '本机生成') + ' · 条为匹配度拆解<span class="lb-ucap">，右列为社区安装量</span></span></div></div><div class="col" style="gap:0">' + (more.length ? more.map(moreRow).join('') : '<span class="cap lb-none">没有更多了</span>') + '</div></div>' +
    '<div class="card pad col lb-peers"><span class="ct">和你相似的人</span><span class="lb-pintro">同为 ' + (p.ok ? p.code : '未分类') + ' 的 <b style="color:var(--ink-1)">1,240</b> 位匿名用户最常装的三项 · 细线 = 全体用户</span>' + peers.map((x) => '<div class="col" style="gap:3px"><div class="row" style="justify-content:space-between;font-size:12px"><b class="mono">' + x.id + '</b><span class="mono" data-tip="同类用户 ' + x.peer + '% · 全体用户 ' + libAll(x) + '% · 提升 ' + f1(x.peer / libAll(x)) + '×">' + x.peer + '%<span class="cap"> vs 全体 ' + libAll(x) + '%</span></span></div><span class="lb-peer" role="img" aria-label="' + x.id + '：同类用户 ' + x.peer + '%，全体用户 ' + libAll(x) + '%"><i style="width:' + x.peer + '%"></i><em style="left:' + libAll(x) + '%"></em></span></div>').join('') + '<div class="row lb-anon">' + ic('shield', 14, 'color:var(--good);margin-top:1px') + '<span>你的匿名贡献：<b>' + (S.anon ? '已开启' : '未开启') + '</b>。开启后只上传人格代码与已装资源名。<button type="button" class="lnk" data-act="openSettings" data-tab="privacy">设置</button></span></div></div></div></div>';
}
PAGES.library = () => tbar('资源库', '', '<label class="row lb-q" style="height:28px;padding:0 10px;border-radius:9px;background:var(--surface);border:1px solid var(--line);color:var(--ink-3)">' + ic('search', 15) + '<span class="vh">搜索资源</span><input id="libQ" type="search" data-in="libQ" placeholder="搜索 Skill、Hook、插件、MCP…" value="' + esc(S.lib.q) + '" style="flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:13px;color:var(--ink-1)"></label><button type="button" class="btn" data-act="libInstalled">已安装 · <span id="libInstN">' + installedItems().length + '</span></button>') +
  '<div class="content" id="content">' + libBody() + '</div>';
TIPS.match = (id) => { const x = LIB.find((y) => y.id === id); if (!x) return ''; const p = libParts(x); return '<b>匹配度 ' + x.m + ' = 加权得分</b>' + LIB_W.map((w, i) => '\n' + w[0] + ' <b class="mono">' + x.sc[i] + '</b> × ' + w[1] + ' = ' + p[i]).join(''); };
// Typing re-renders only the results, never the toolbar that holds the input, and waits for the IME to finish composing
// (BUG-32: a full re-render per keystroke broke pinyin composition and the caret).
function libRefresh() { const c = $('#content'); if (c && S.route === 'library') c.innerHTML = libBody(); }
Object.assign(ACT, {
  libTab: (el) => { S.lib.tab = el.dataset.v; render(); },
  libKind: (el) => { S.lib.kind = el.dataset.v; render(); },
  libSort: (el) => { S.lib.sort = el.dataset.v; render(); },
  libQ: (el, e) => { S.lib.q = el.value; if (e && e.isComposing) return; libRefresh(); },
  libHide: (el) => { const id = el.dataset.id; if (!LIB.find((x) => x.id === id)) return; S.libHide.add(id); render(); toast('已隐藏 ' + id + '，同类资源会降权', { act: '撤销', sec: 8, onAct: () => { S.libHide.delete(id); render(); } }); },
  libUnhide: () => { S.libHide.clear(); render(); },
  getLib: (el) => { const x = LIB.find((y) => y.id === el.dataset.id); if (x) openInstall(x.rec, x); },
  libUninstall: (el) => { const id = el.dataset.id; if (!S.libInst.has(id)) return; S.libInst.delete(id); if (LAST_INSTALL && LAST_INSTALL.lib === id) LAST_INSTALL = null; S.instLog.unshift({ t: '撤销 ' + id, when: '刚刚' }); closeModal(); render(); toast('已撤销「' + id + '」，文件已从备份恢复'); },
  studioUninstall: (el) => { S.libInst.delete(el.dataset.id); closeModal(); render(); toast('已撤销，文件已从备份恢复'); },
  libInstalled: () => { const items = installedItems(); openModal(modalHead('已安装 · ' + items.length, '扫描自 ~/.claude、~/.codex、~/.gemini 与项目目录') + '<div class="mb col" style="gap:6px">' + items.map((it) => { const k = it.t.indexOf('（'); return '<div class="row lb-irow"><span class="lb-inm"><b class="mono">' + esc(it.t.slice(0, k)) + '</b><span class="cap">' + esc(it.t.slice(k)) + '</span></span>' + (it.undo ? '<button type="button" class="btn sm" data-act="' + it.undo + '" data-id="' + esc(it.id) + '">撤销</button>' : '<span class="cap">手动安装</span>') + '</div>'; }).join('') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>'); }
});
