/* v6 port: close: your compass, the aurora collapses to one ring, the ring becomes the Orbit mark */
scene('70-close', () => {
  END = 118;
  drive(2, 100.7, 107.6, (p, b) => drawCompass({ deg: 4 * Math.sin((b - 101) * 1.5) * Math.exp(-(b - 101) * .5), speed: 0, mine: 1, grow: 1 + .02 * Math.sin((b - 101) * 1.6), sweep: 1, orbit: 0, settle: 1, tip: 0, needle: 1, core: 1 - E.inOut(lp(b, 104, 1.2)), dial: 1 - E.inOut(lp(b, 104.4, 1.6)), collapse: E.inOut(lp(b, 104.4, 1.6)) }));
  tween(2, 100.9, 2, () => framing(2, 'all', [960, 540, 900, 900]), E.quart, (T) => ({ s: T.s * .3, rz: -80, o: 0, bl: 6 }));
  tween(2, 106.2, .8, () => ({ o: 0 }), E.inOut);
  glowAt(101, .6, 3);
  txt(102, 104.6, [['row md', ['<span>只读本地日志</span>', '<span class="acc">数据不出本机</span>']]], { x: 960, y: 1030, align: 'c' }, { st: .4 });
  glowAt(106, .9, 3);
  txt(109.2, 117.6, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(110.6, 117.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(112.4, 117.6, [['eb', 'for macOS · ActionMesh AI']], { x: 960, y: 865, align: 'c' }, { inB: 1.5, outB: 2 });
  glowAt(115, 0, 2.5);
});
