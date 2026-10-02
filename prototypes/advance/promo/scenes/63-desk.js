/* v6 port: the smaller features (急): one wall of desktop pieces filling the screen, each one acts in turn */
scene('63-desk', () => {
  const DESK = ['#widgets', '#hud', '#notes', '.edsw'];
  at(90.3, () => { const a = app(0); a.W.closeModal(); a.S.widgets = true; a.S.hud.show = true; a.S.sim = 'running'; a.go('overview'); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); solo(0, DESK); });
  const WIDE = () => Object.assign(framing(0, ['#widgets', '#hud', '.edsw'], [960, 560, 1500, 900]), { s: 1.12, x: 800, y: 500, rx: 14, ry: -12, rz: -3 });
  tween(0, 90.8, 1.6, WIDE, E.quart, IN.plane);
  tag(0, 91.4, 93.6, '#widgets', 'right', [['hv sv', '桌面小组件'], ['lt acc', '人格 · 今日 · 本周 · 最值得做']], { gap: 60 });
  at(92.6, () => { const a = app(0); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.simEvent('waiting'); });
  tween(0, 92.6, 1.1, () => Object.assign(framing(0, '#notes .nt', [1200, 380, 900, 400], { max: 2 }), { rx: 8, ry: 10, rz: 2 }), E.inOut);
  tag(0, 93, 94.6, '#notes .nt', 'left', [['md sv', '第一时间提醒'], ['lt acc', '会话等你确认时']], { gap: 50 });
  at(94, () => { app(0).W.openPalette(); solo(0, DESK.concat('#modal')); });
  drive(0, 94.4, 95.4, (p, b, D) => { const q = D.querySelector('#palQ'); if (!q) return; const s = '部署'.slice(0, Math.floor(p * 2.99)); if (q.value !== s) { q.value = s; q.dispatchEvent(new Event('input', { bubbles: true })); } });
  tween(0, 94, 1.1, () => Object.assign(framing(0, '#modal', [960, 470, 900, 640], { max: 1.8 }), { rx: 10, ry: -6, rz: -2 }), E.inOut);
  tag(0, 94.4, 95.8, '#modal', 'bottom', [['md sv', '⌘K'], ['lt acc', '任何页面、会话与操作']], { at: .5 });
  at(95.6, () => { app(0).W.closeModal(); solo(0, DESK); });
  tween(0, 95.8, 1.1, () => Object.assign(framing(0, '.edsw', [960, 600, 1000, 300], { max: 3.2 }), { rx: 18, ry: 8, rz: 0 }), E.inOut);
  clickAt(0, 96.6, '[data-act="edition"][data-v="lite"]', (a) => a.W.edSet('lite'));
  at(97.2, () => { const a = app(0); a.S.hud.show = true; a.S.sim = 'running'; a.render(); });
  tag(0, 96, 97.4, '.edsw', 'bottom', [['md sv', 'Lite / Advance'], ['lt acc', '一键切换 · ⌃⌘L']], { at: .5, gap: 50 });
  tween(0, 97.4, 1.1, () => Object.assign(framing(0, '#hud', [900, 560, 1100, 400], { max: 2.6 }), { rx: 12, ry: -10, rz: 2 }), E.inOut);
  clickAt(0, 97.9, '#hudPill', (a, el) => a.click(el));
  tag(0, 97.7, 99, '#hud', 'right', [['md sv', '悬浮组件'], ['lt acc', '会话运行时，陪在桌面一角']], { gap: 50 });
  tween(0, 98.8, 1.2, WIDE, E.inOut);
  at(99.2, () => { app(0).W.setTheme('dark'); });
  tag(0, 99.3, 100.6, '#widgets', 'right', [['hv sv', '深色模式'], ['lt acc', '跟随系统外观']], { gap: 60 });
  tween(0, 100.6, 1.3, () => ({ rz: 80, s: decks[0].C.s * .3, o: 0, bl: 6 }), E.inOut);
});
