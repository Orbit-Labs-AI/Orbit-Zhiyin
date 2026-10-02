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
// viewport resize: re-clamp the window at once (cheap), redraw the desktop layer after the burst settles
let RZ = null;
window.addEventListener('resize', () => { applyWin(); setPlace(); clearTimeout(RZ); RZ = setTimeout(() => { renderWidgets(); renderHud(); }, 80); });
(function init() {
  document.documentElement.lang = 'zh-CN';
  let h = ''; try { h = decodeURIComponent(location.hash.slice(1)); } catch (e) { h = ''; }
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
  if (!LV.live && !ORBIT.native.surface) setTimeout(() => notify({ t: '欢迎体验 Orbit 交互 Demo', b: '数据都是示例。菜单栏右侧的烧瓶图标是「演示」菜单，可以模拟会话事件、播放首次启动与人格揭晓；' + kb('⌘K') + ' 打开命令面板。', a1: '播放首次启动', on1: () => openOnboarding(0), a2: '知道了', ms: 12000, force: true }), 800);
})();
