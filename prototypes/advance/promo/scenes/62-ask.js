/* v6 port: 04 · Ask (build) */
scene('62-ask', () => {
  shot(1, 84, 90.5, { sel: '#modal', box: [1310, 560, 980, 760], inn: 'rise', inDur: 1.4, out: 'near', outDur: 1, push: 1.14, prep: (a) => { a.go('overview'); a.W.openAsk('overview'); } });
  clickAt(1, 85.4, '[data-act="askPick"]', (a, el) => a.click(el));
  glowAt(84, .5, 2);
  txt(84.5, 90.5, [['eb', '04 · Ask'], ['gap'], ['hv sv', '问你自己的'], ['hv ai', '本地 Agent'], ['gap'], ['lt', '数据不出本机 · 0 B 上传']], { x: L, y: 540 }, { st: .5, spread: 1, outB: .8 });
  glowAt(90, 0, 1.5);
});
