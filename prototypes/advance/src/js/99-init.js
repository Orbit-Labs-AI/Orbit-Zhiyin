/* ============ clock, live counters, init ============ */
let TICK = 0;
setInterval(() => {
  TICK++;
  $$('[data-clock]').forEach((x) => { x.textContent = nowText(); });
  $$('[data-live]').forEach((x) => { x.textContent = liveElapsed(); });
  if (TICK % 4 === 0 && S.sim !== 'idle' && !S.paused) {
    HUD_T++; S.live.tools++;
    $$('[data-hudtool]').forEach((x) => { x.textContent = HUD_TOOLS[HUD_T % HUD_TOOLS.length]; });
    $$('[data-livetools]').forEach((x) => { x.textContent = S.live.tools; });
  }
}, 1000);
// the settings window and the first-run overlay rebuild themselves outside render() (live settings writes, job frames):
// keep their scroll positions and the focused field across every rebuild (F03). A tab change of the settings window and a
// step change of the overlay start at top (the old tab's positions mean nothing in the new one).
{
  const setBase = renderSet;
  let setDrawn = null;   // the tab the window last showed (the tab buttons set S.setTab before they call renderSet)
  renderSet = function () { const keep = uiKeep($('#set')); const r = setBase.apply(this, arguments); if (S.setTab === setDrawn) keep(); setDrawn = S.setTab; return r; };
  // closing the window forgets it: reopening (even on the same tab) starts at top, like a fresh window
  const closeBase = closeSettings;
  closeSettings = function () { setDrawn = null; return closeBase.apply(this, arguments); };
  const obBase = drawOB;
  drawOB = function () { const was = OB && OB.drawn; const keep = uiKeep($('#overlay')); const r = obBase.apply(this, arguments); if (OB && OB.drawn === was) keep(); return r; };
}
// viewport resize: re-clamp the window at once (cheap), redraw the desktop layer after the burst settles
let RZ = null;
window.addEventListener('resize', () => { applyWin(); setPlace(); clearTimeout(RZ); RZ = setTimeout(() => { renderWidgets(); renderHud(); }, 80); });
(function init() {
  document.documentElement.lang = I18N.lang === 'en' ? 'en' : 'zh-CN';   // 02-i18n sets the default; keep them in sync here too
  let h = ''; try { h = decodeURIComponent(location.hash.slice(1)); } catch (e) { h = ''; }
  if (!h && store.native && !ED_SURFACE) h = edLastRoute(S.ed) || '';   // App: back to the last page of the last edition
  if (/^l-/.test(h)) S.ed = 'lite';
  if (PAGES[h]) S.route = h;
  S.route = edRoute(S.route); if (!PAGES[S.route]) S.route = S.ed === 'lite' ? 'l-home' : 'overview';
  $('#win').dataset.ed = S.ed;
  setTheme(S.theme);
  // desktop widgets sit on the desktop layer, left of the window; shown by default on stages ≥ 1500px (as published), where
  // the default window leaves the column free. 「显示 › 桌面小组件」toggles them at any size.
  S.widgets = window.innerWidth >= WIDE_MIN;
  render();
  // the demo welcome says the data is sample data: mock only, never over live data or the native panel / hud / widgets surfaces
  if (!LV.live && !ORBIT.native.surface) setTimeout(() => notify({ t: (I18N.lang === 'en' ? 'Welcome to the Orbit interactive demo' : '欢迎体验 Orbit 交互 Demo'), b: (I18N.lang === 'en' ? 'All data is sample data. The flask icon at the right of the menu bar opens the Demo menu: simulate session events, play the first launch and the persona reveal. Press ' + kb('⌘K') + ' to open the command palette.' : '数据都是示例。菜单栏右侧的烧瓶图标是「演示」菜单，可以模拟会话事件、播放首次启动与人格揭晓；' + kb('⌘K') + ' 打开命令面板。'), a1: (I18N.lang === 'en' ? 'Play first launch' : '播放首次启动'), on1: () => openOnboarding(0), a2: (I18N.lang === 'en' ? 'Got it' : '知道了'), ms: 12000, force: true }), 800);
})();
