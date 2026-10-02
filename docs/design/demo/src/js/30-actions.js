/* ============ actions ============ */
const ACT = {};
document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!$('#dd').hidden && !e.target.closest('#dd') && (!el || el.dataset.act !== 'menu' || !el.closest('.mbar'))) closeDD();
  if (S.pop && !e.target.closest('#pop') && !e.target.closest('.glyph')) { S.pop = false; $('#pop').hidden = true; renderMbar(); }
  if (!el) return;
  const fn = ACT[el.dataset.act];
  if (fn) { e.preventDefault(); fn(el, e); }
});
document.addEventListener('input', (e) => { const el = e.target.closest('[data-in]'); if (el && ACT[el.dataset.in]) ACT[el.dataset.in](el, e); });
document.addEventListener('change', (e) => { const el = e.target.closest('[data-chg]'); if (el && ACT[el.dataset.chg]) ACT[el.dataset.chg](el, e); });
$('#scrim').addEventListener('click', closeModal);
Object.assign(ACT, {
  go: (el) => go(el.dataset.r),
  drawer: () => { S.drawer = !S.drawer; $('#win').classList.toggle('drawer', S.drawer); },
  rail: () => { S.rail = !S.rail; render(); },
  closeModal: () => closeModal(),
  toastAct: () => { const t = $('#toast'); if (t.onAct) t.onAct(); t.hidden = true; clearInterval(toastTimer); },
  noteClose: (el) => { const n = document.getElementById(el.dataset.n); if (n) n.remove(); },
  noteAct: (el) => { const n = document.getElementById(el.dataset.n); if (!n) return; const fn = el.dataset.k === '1' ? n._n.on1 : n._n.on2; n.remove(); if (fn) fn(); },
  range: (el) => { S.range = +el.dataset.v; render(); },
  agentToggle: (el, e) => {
    const id = el.dataset.a;
    if (S.srcOff.has(id)) { toast(agent(id).name + ' 已在设置中停用，先到「设置 › 数据源」启用'); return; }
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
    openDD(el, MENUS[el.dataset.m](), (v) => { if (typeof v === 'function') v(); });
  },
  winClose: () => { S.winGone = true; render(); toast('主窗口已关闭 · 从菜单栏面板或 ⌘1 重新打开', { act: '重新打开', onAct: () => go(S.route) }); },
  winMin: () => { S.winGone = true; render(); toast('已最小化 · 点「恢复」或按 ⌘1', { act: '恢复', onAct: () => go(S.route) }); },
  winMax: () => { S.max = !S.max; render(); },
  pop: () => { S.pop = !S.pop; render(); }
});
const MENUS = {
  app: () => [{ t: '关于 Tandem', v: () => openAbout() }, { t: '偏好设置…', k: '⌘,', v: () => openSettings() }, { sep: 1 }, { t: S.paused ? '恢复采集' : '暂停采集', v: () => { S.paused = !S.paused; render(); toast(S.paused ? '已暂停采集，菜单栏图标显示斜线状态' : '已恢复采集'); } }, { sep: 1 }, { t: '退出 Tandem', k: '⌘Q', v: () => toast('这是 Demo：退出不可用') }],
  file: () => [{ t: '导出报告…', k: '⌘⇧E', v: () => openReport() }, { t: '导出分享卡…', k: '⌘⇧S', v: () => openShare() }, { t: '导出工具明细 CSV…', v: () => openCSV() }],
  view: () => [{ h: '外观' }, { t: '跟随系统', on: S.theme === 'system', v: () => { setTheme('system'); render(); } }, { t: '浅色', on: S.theme === 'light', v: () => { setTheme('light'); render(); } }, { t: '深色', on: S.theme === 'dark', v: () => { setTheme('dark'); render(); } }, { sep: 1 }, { t: '悬浮组件', k: '⌥⌘P', on: S.hud.show, v: () => toggleHud() }, { t: '桌面小组件', on: S.widgets, v: () => { S.widgets = !S.widgets; render(); } }, { t: '侧边栏', k: '⌃⌘S', on: !S.rail, v: () => { S.rail = !S.rail; render(); } }, { sep: 1 }, { t: S.max ? '退出全屏' : '进入全屏', v: () => { S.max = !S.max; render(); } }],
  window: () => [{ t: '主窗口', k: '⌘1', v: () => go(S.route) }, { t: '命令面板', k: '⌘K', v: () => openPalette() }, { t: '设置', k: '⌘,', v: () => openSettings() }, { sep: 1 }].concat(ROUTES.map((r, i) => ({ t: r[1], k: '⌥' + (i + 1), on: S.route === r[0], v: () => go(r[0]) }))),
  help: () => [{ t: '键盘快捷键', k: '?', v: () => openKeys() }, { t: '重新播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { sep: 1 }, { t: '关于这个 Demo', v: () => openAbout() }],
  demo: () => [{ h: '模拟事件（会触发通知、菜单栏与悬浮组件）' }, { t: '会话完成', v: () => simEvent('done') }, { t: '有会话等你确认', v: () => simEvent('waiting') }, { t: '同一命令连续失败', v: () => simEvent('stuck') }, { t: '上下文即将压缩', v: () => simEvent('ctx') }, { t: '每周报告已生成', v: () => simEvent('weekly') }, { t: '发现新的数据来源', v: () => simEvent('newsrc') }, { sep: 1 }, { t: '播放首次启动', v: () => openOnboarding(0) }, { t: '播放人格揭晓', v: () => openReveal() }, { sep: 1 }, { t: '重置演示数据', v: () => resetDemo() }],
  all: () => MENUS.app().concat([{ sep: 1 }], MENUS.file(), [{ sep: 1 }], MENUS.view(), [{ sep: 1 }], MENUS.help())
};

