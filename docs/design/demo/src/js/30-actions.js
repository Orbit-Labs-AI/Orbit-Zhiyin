/* ============ actions ============ */
const ACT = {};
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!$('#dd').hidden && !e.target.closest('#dd') && (!el || el.dataset.act !== 'menu' || !el.closest('.mbar'))) closeDD();
  if (S.pop && !e.target.closest('#pop') && !e.target.closest('[data-act="pop"]')) { S.pop = false; $('#pop').hidden = true; renderMbar(); }
  if (!e.target.closest('.tmore')) $$('.tmore-pop:not([hidden])').forEach((p) => { p.hidden = true; p.previousElementSibling.setAttribute('aria-expanded', 'false'); });
  if (!el) return;
  const fn = ACT[el.dataset.act];
  if (fn) { e.preventDefault(); fn(el, e); }
});
document.addEventListener('input', (e) => { const el = e.target.closest('[data-in]'); if (el && ACT[el.dataset.in]) ACT[el.dataset.in](el, e); });
document.addEventListener('change', (e) => { const el = e.target.closest('[data-chg]'); if (el && ACT[el.dataset.chg]) ACT[el.dataset.chg](el, e); });
$('#scrim').addEventListener('click', closeModal);
const demoOnly = () => toast('这是 Demo：系统功能不可用');
function editCmd(c) { toast(({ cut: '剪切', copy: '拷贝', paste: '粘贴', selectAll: '全选' })[c] + '：在文本框里直接按 ' + kb({ cut: '⌘X', copy: '⌘C', paste: '⌘V', selectAll: '⌘A' }[c])); }
function findCmd() { const q = $('#sessQ') || $('#libQ'); if (q) { q.focus(); q.select(); } else openPalette(); }
Object.assign(ACT, {
  go: (el) => go(el.dataset.r),
  sideToggle: () => toggleSide(),
  sideScrim: () => { S.sideOver = false; applyWin(); renderWtop(); },
  sideGroup: (el) => { const g = el.dataset.g; S.sideOpen[g] = S.sideOpen[g] === false; saveSide(); renderSide(); },
  tmore: (el) => { const pop = el.nextElementSibling; pop.hidden = !pop.hidden; el.setAttribute('aria-expanded', String(!pop.hidden)); },
  closeModal: () => closeModal(),
  toastAct: () => { const t = $('#toast'); if (t.onAct) t.onAct(); t.hidden = true; clearInterval(toastTimer); },
  noteClose: (el) => noteDismiss(document.getElementById(el.dataset.n)),
  noteAct: (el) => { const n = document.getElementById(el.dataset.n); if (!n) return; const fn = el.dataset.k === '1' ? n._n.on1 : n._n.on2; noteDismiss(n); if (fn) fn(); },
  range: (el) => { S.range = +el.dataset.v; render(); },
  agentToggle: (el, e) => {
    const id = el.dataset.a;
    if (S.srcOff.has(id)) { toast(agent(id).name + ' 已在设置中停用，先到「设置 › 数据源」启用', { act: '打开设置', onAct: () => openSettings('sources') }); return; }
    if (e.altKey) { if (S.agents.has(id) && S.agents.size > 1) S.agents.delete(id); else S.agents.add(id); }
    else if (S.agents.size === 1 && S.agents.has(id)) AG.forEach((a) => S.agents.add(a.id));
    else { S.agents.clear(); S.agents.add(id); }
    render();
  },
  agentMenu: (el) => openDD(el, [{ h: '多选；全部取消时恢复全部' }].concat(agentLegendItems()).concat([{ sep: 1 }, { t: '全部 Agent', v: '*' }]), (v) => {
    if (v === '*') AG.forEach((a) => S.agents.add(a.id));
    else if (S.agents.has(v)) { S.agents.delete(v); if (!S.agents.size) AG.forEach((a) => S.agents.add(a.id)); } else S.agents.add(v);
    render();
  }, { keep: true, refresh: () => [{ h: '多选；全部取消时恢复全部' }].concat(agentLegendItems()).concat([{ sep: 1 }, { t: '全部 Agent', v: '*' }]) }),
  projectMenu: (el) => openDD(el, [{ t: '全部项目', v: null, on: !S.project }, { sep: 1 }].concat(PJ.map((p) => ({ t: p.name, v: p.id, on: S.project === p.id, k: String(sel({ noExtra: true, project: p.id }).length) }))), (v) => { S.project = v; render(); }),
  addFilter: (el) => openDD(el, [{ h: '主题' }].concat(Object.keys(TOPICS).map((k) => ({ t: TOPICS[k], v: 't:' + k, on: S.topic === k }))).concat([{ sep: 1 }, { h: '结果' }, { t: '完成', v: 'o:ok', on: S.outcome === 'ok' }, { t: '部分完成', v: 'o:part', on: S.outcome === 'part' }, { t: '放弃', v: 'o:fail', on: S.outcome === 'fail' }]), (v) => {
    const k = v.slice(2); if (v[0] === 't') S.topic = S.topic === k ? null : k; else S.outcome = S.outcome === k ? null : k; render();
  }),
  clearFilter: (el) => { const k = el.dataset.k; if (k === 'hour') S.hour = null; else S[k] = null; render(); },
  pinProject: (el) => { S.proj.sel = el.dataset.p; go('projects'); },
  palette: () => openPalette(),
  menu: (el) => {
    if (DD && DD.anchor === el) { closeDD(); return; }
    openDD(el, MENUS[el.dataset.m](), (v) => { if (typeof v === 'function') v(); }, { align: el.dataset.m === 'demo' ? 'right' : undefined });
  },
  winClose: () => { S.winGone = true; render(); toast('主窗口已关闭 · 从菜单栏面板或 ' + kb('⌥0') + ' 重新打开', { act: '重新打开', onAct: () => showMain() }); },
  winMin: () => { S.winGone = true; render(); toast('已最小化 · 点「恢复」或按 ' + kb('⌥0'), { act: '恢复', onAct: () => showMain() }); },
  winZoom: (el, e) => { if (e && e.altKey) winZoomToggle(); else winFullToggle(); },
  winFull: () => winFullToggle(),
  pop: () => { S.pop = !S.pop; render(); }
});
/* menus: menu-bar titles → MENUS[id]() items {t, k, on, dis, sep, h, sub, v}. Shortcut labels match 85-keyboard.js:
   pages ⌥1–9 (⌘1–9 in the app), main window ⌥0 (⌘0), sidebar ⌃⌘S, full screen ⌃⌘F, minimise ⌘M. */
const MENUS = {
  apple: () => [{ t: '关于本机', v: demoOnly }, { sep: 1 }, { t: '系统设置…', v: demoOnly }, { t: 'App Store…', v: demoOnly }, { sep: 1 }, { t: '最近使用的项目', sub: 1, v: demoOnly }, { sep: 1 }, { t: '强制退出…', k: '⌥⌘⎋', v: demoOnly }, { sep: 1 }, { t: '睡眠', v: demoOnly }, { t: '重新启动…', v: demoOnly }, { t: '关机…', v: demoOnly }, { sep: 1 }, { t: '锁定屏幕', k: '⌃⌘Q', v: demoOnly }, { t: '退出登录…', k: '⇧⌘Q', v: demoOnly }],
  app: () => [{ t: '关于 Tandem', v: () => openAbout() }, { sep: 1 }, { t: '设置…', k: '⌘,', v: () => openSettings() }, { sep: 1 }, { t: S.paused ? '恢复采集' : '暂停采集', v: () => { S.paused = !S.paused; render(); toast(S.paused ? '已暂停采集，菜单栏图标不再显示状态角标' : '已恢复采集'); } }, { sep: 1 }, { t: '服务', sub: 1, v: demoOnly }, { sep: 1 }, { t: '隐藏 Tandem', k: '⌘H', v: () => ACT.winMin() }, { t: '隐藏其他', k: '⌥⌘H', v: demoOnly }, { t: '全部显示', v: () => showMain() }, { sep: 1 }, { t: '退出 Tandem', k: '⌘Q', v: () => toast('这是 Demo：退出不可用') }],
  file: () => [{ t: '导出报告…', k: '⇧⌘E', v: () => openReport() }, { t: '导出分享卡…', k: '⇧⌘S', v: () => openShare() }, { t: '导出工具明细 CSV…', v: () => openCSV() }, { sep: 1 }, { t: '关闭窗口', k: '⌘W', v: () => ACT.winClose() }],
  edit: () => [{ t: '撤销', k: '⌘Z', v: () => undoInstall() }, { t: '重做', k: '⇧⌘Z', dis: true }, { sep: 1 }, { t: '剪切', k: '⌘X', v: () => editCmd('cut') }, { t: '拷贝', k: '⌘C', v: () => editCmd('copy') }, { t: '粘贴', k: '⌘V', v: () => editCmd('paste') }, { t: '全选', k: '⌘A', v: () => editCmd('selectAll') }, { sep: 1 }, { t: '查找…', k: '⌘F', v: () => findCmd() }],
  view: () => [{ h: '外观' }, { t: '跟随系统', on: S.theme === 'system', v: () => { setTheme('system'); render(); } }, { t: '浅色', on: S.theme === 'light', v: () => { setTheme('light'); render(); } }, { t: '深色', on: S.theme === 'dark', v: () => { setTheme('dark'); render(); } }, { sep: 1 }, { t: '悬浮组件', k: '⌥⌘P', on: S.hud.show, v: () => toggleHud() }, { t: '桌面小组件', on: S.widgets, v: () => { S.widgets = !S.widgets; render(); } }, { t: (winNarrow() ? S.sideOver : S.side) ? '隐藏侧边栏' : '显示侧边栏', k: '⌃⌘S', v: () => toggleSide() }, { sep: 1 }, { t: S.win.full ? '退出全屏' : '进入全屏', k: '⌃⌘F', v: () => winFullToggle() }],
  window: () => [{ t: '最小化', k: '⌘M', v: () => ACT.winMin() }, { t: S.win.zoom ? '恢复缩放' : '缩放', v: () => winZoomToggle() }, { sep: 1 }, { t: '主窗口', k: kb('⌥0'), on: !S.winGone, v: () => showMain() }, { t: '命令面板', k: '⌘K', v: () => openPalette() }, { t: '设置', k: '⌘,', v: () => openSettings() }, { sep: 1 }].concat(ROUTES.map((r, i) => ({ t: r[1], k: kb('⌥' + (i + 1)), on: S.route === r[0], v: () => go(r[0]) }))),
  help: () => [{ t: '键盘快捷键', k: '?', v: () => openKeys() }, { t: '重新播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { sep: 1 }, { t: '关于这个 Demo', v: () => openAbout() }],
  demo: () => [{ h: '模拟事件（会触发通知、菜单栏与悬浮组件）' }, { t: '会话完成', v: () => simEvent('done') }, { t: '有会话等你确认', v: () => simEvent('waiting') }, { t: '同一命令连续失败', v: () => simEvent('stuck') }, { t: '上下文即将压缩', v: () => simEvent('ctx') }, { t: '每周报告已生成', v: () => simEvent('weekly') }, { t: '发现新的数据来源', v: () => simEvent('newsrc') }, { sep: 1 }, { t: '播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { sep: 1 }, { t: '重置演示数据', v: () => resetDemo() }]
};
