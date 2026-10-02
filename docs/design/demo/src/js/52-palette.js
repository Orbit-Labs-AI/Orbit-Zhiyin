/* ============ command palette ============ */
let PAL = null;
function palActions() {
  const ctx = S.route === 'persona' ? 'persona' : S.route === 'recs' ? 'recs' : S.route === 'tools' ? 'tools' : S.route === 'sessions' ? 'session' : 'overview';
  return [
    { t: '切换到' + (isDark() ? '浅色' : '深色') + '外观', icon: 'eye', run: () => { setTheme(isDark() ? 'light' : 'dark'); render(); } },
    { t: '问本地 Agent', icon: 'spark', run: () => openAsk(ctx) },
    { t: '导出分享卡', k: kb('⌘⇧S'), icon: 'share', run: () => openShare() },
    { t: '导出报告', k: kb('⌘⇧E'), icon: 'file', run: () => openReport() },
    { t: '导出工具明细 CSV', icon: 'down', run: () => openCSV() },
    { t: '打开设置', k: kb('⌘,'), icon: 'settings', run: () => openSettings() },
    { t: '重新索引', k: kb('⌥R'), icon: 'sync', run: () => reindex() },
    { t: (S.hud.show ? '隐藏' : '显示') + '悬浮组件', k: kb('⌥⌘P'), icon: 'eye', run: () => toggleHud() },
    { t: '打开菜单栏面板', k: kb('⌃⌥T'), icon: 'bell', run: () => { S.pop = true; render(); } },
    { t: (S.widgets ? '隐藏' : '显示') + '桌面小组件', icon: 'grid', run: () => { S.widgets = !S.widgets; render(); } },
    { t: '播放人格揭晓', icon: 'persona', run: () => openReveal() },
    { t: '播放首次启动', icon: 'spark', run: () => openOnboarding(0) },
    { t: '清除所有筛选', icon: 'filter', run: () => ACT.clearAllFilters() },
    { t: '部署相关会话', icon: 'sessions', run: () => { S.topic = 'design'; S.sess.q = '部署'; go('sessions'); } },
    { t: '键盘快捷键', k: '?', icon: 'info', run: () => openKeys() }
  ];
}
function palItems(q) {
  q = q.trim().toLowerCase();
  const m = (t) => !q || String(t).toLowerCase().includes(q);
  const out = [];
  ROUTES.forEach((r, i) => { if (m(r[1]) || m(r[0])) out.push({ g: '页面', t: r[1], k: kb('⌥' + (i + 1)), icon: r[0], run: () => go(r[0]) }); });
  if (q) PJ.forEach((p) => { if (m(p.name) || m(p.path)) out.push({ g: '项目', t: p.name, sub: p.path, icon: 'projects', run: () => { S.proj.sel = p.id; go('projects'); } }); });
  ALL.filter((s) => sourceEnabled(s) && (q ? m(s.title) || m(PJI[s.p].name) : s.d >= 119)).sort((a, b) => (b.d - a.d) || (b.h - a.h) || (b.mi - a.mi)).slice(0, q ? 6 : 4)
    .forEach((s) => out.push({ g: '会话', t: s.title, sub: agent(s.a).name + ' · ' + PJI[s.p].name + ' · ' + md(s.d) + ' ' + hm(s.h, s.mi), icon: 'sessions', run: () => { S.sess.sel = s.id; S.sess.mode = 'single'; S.sess.q = ''; go('sessions'); } }));
  RECS.filter((r) => m(r.title) || m(r.type) || m(r.why)).slice(0, q ? 5 : 3).forEach((r) => out.push({ g: '建议', t: r.title, sub: r.type + ' · ' + LEVELS[r.lvl] + ' · ' + r.gain, icon: r.icon, run: () => ACT.openRec({ dataset: { id: r.id } }) }));
  palActions().filter((a) => m(a.t)).forEach((a) => out.push(Object.assign({ g: '操作' }, a)));
  return out;
}
function openPalette() {
  PAL = { q: '', i: 0, items: [] };
  openModal('<label class="row" style="padding:12px 14px;border-bottom:1px solid var(--line)">' + ic('search', 16, 'color:var(--ink-3)') + '<span class="vh">命令面板搜索</span><input id="palQ" data-in="palQ" autofocus placeholder="搜索页面、会话、项目、建议与操作…" autocomplete="off" style="flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:15px;color:var(--ink-1)"><span class="kbd">Esc</span></label><div id="palList" role="listbox" aria-label="结果" style="max-height:min(420px,58vh);overflow:auto;padding:6px"></div><div class="row cap" style="padding:8px 14px;border-top:1px solid var(--hair);font-size:11px;gap:14px;flex-wrap:wrap"><span>↑↓ 选择</span><span>↩ 打开</span><span>Esc 关闭</span><span style="margin-left:auto">试试输入「部署」</span></div>', 'pal');
  MODAL_KEY = 'palette'; drawPal();
}
function drawPal() {
  const box = $('#palList'); if (!box) return;
  PAL.items = palItems(PAL.q); PAL.i = clamp(PAL.i, 0, Math.max(0, PAL.items.length - 1));
  let g = null;
  box.innerHTML = PAL.items.length ? PAL.items.map((it, i) => { const h = it.g !== g ? '<div class="eb" style="padding:8px 10px 4px">' + it.g + '</div>' : ''; g = it.g; return h + '<button type="button" role="option" data-act="palPick" data-i="' + i + '" aria-selected="' + (i === PAL.i) + '" class="palrow' + (i === PAL.i ? ' on' : '') + '">' + ic(I[it.icon] ? it.icon : 'chevr', 15) + '<span style="flex:1;min-width:0;display:flex;flex-direction:column"><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(it.t) + '</span>' + (it.sub ? '<span class="cap" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(it.sub) + '</span>' : '') + '</span>' + (it.k ? '<span class="mono cap" style="font-size:11px">' + esc(it.k) + '</span>' : '') + '</button>'; }).join('') : '<div class="cap" style="padding:28px;text-align:center">没有匹配「' + esc(PAL.q) + '」的结果</div>';
  const on = box.querySelector('.on'); if (on) on.scrollIntoView({ block: 'nearest' });
}
Object.assign(ACT, {
  palQ: (el) => { PAL.q = el.value; PAL.i = 0; drawPal(); },
  palPick: (el) => { const it = PAL.items[+el.dataset.i]; closeModal(); if (it) it.run(); }
});

