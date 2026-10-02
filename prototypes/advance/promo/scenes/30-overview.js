/* v6 port: numbers roll, then fly into the KPI tiles; the tiles open into the overview wall */
scene('30-overview', () => {
  const NUMS = [[186, '', '个会话'], [142, 'h', '小时协作'], ['1,284', '', '条消息']];
  const TB = [960, 600, 1700, 420], morph = [];
  at(25.8, () => {
    const T = framing(0, '.tiles', TB);
    NUMS.forEach((n, i) => {
      const f = fx.find((x) => x.tag === 'num' + i); const span = f && f.el && f.el.querySelector('.odo'); if (!span) return;
      const v = decks[0].D.querySelectorAll('.tiles .vz-kpi .v')[i]; if (!v) return;
      const r = v.getBoundingClientRect(), k = stage.getBoundingClientRect().width / 1920, s0 = span.getBoundingClientRect();
      const tx = T.ax + (r.left - T.x) * T.s, ty = T.ay + (r.top + r.height / 2 - T.y) * T.s;
      const sx = (s0.left - stage.getBoundingClientRect().left) / k, sy = (s0.top + s0.height / 2 - stage.getBoundingClientRect().top) / k;
      morph[i] = { dx: tx - sx, dy: ty - sy, sc: (r.height * T.s) / (s0.height / k) };
    });
  });
  NUMS.forEach((n, i) => {
    const b0 = 22.3 + i * .5;
    txt(b0, 27.7, [['', '<span class="odo">' + odo(n[0]) + '</span><span class="odo-u">' + n[1] + '</span>'], ['lt', n[2]]], { x: 960 + (i - 1) * 520, y: 520, align: 'c' }, {
      anim: (el, tl, life, t) => {
        const b = t / BEAT, m = E.inOut(lp(b, 25.9, 1.45)), mv = morph[i], inP = E.expo(clamp(tl / (.9 * BEAT)));
        el.style.opacity = (inP * (1 - E.inOut(lp(b, 27.35, .3)))).toFixed(3);
        rollOdo(el, b, b0, 1.9);
        const o = el.querySelector('.odo'); o.style.transformOrigin = '0 50%';
        const ink = Math.round(lerp(255, 23, Math.pow(m, 3))); o.style.color = 'rgb(' + ink + ',' + ink + ',' + Math.round(lerp(255, 27, Math.pow(m, 3))) + ')';
        o.style.transform = mv ? 'translate(' + (mv.dx * m).toFixed(1) + 'px,' + (mv.dy * m).toFixed(1) + 'px) scale(' + lerp(1, mv.sc, m).toFixed(4) + ')' : '';
        el.querySelectorAll('.odo-u, .ln.lt').forEach((x) => { x.style.opacity = (1 - E.out(lp(b, 25.7, .6))).toFixed(3); });
        el.style.transform = 'translate(-50%,-50%) translateY(' + ((1 - inP) * 40).toFixed(1) + 'px)';
        el.querySelectorAll('.ln').forEach((x) => { x.style.overflow = 'visible'; });
      }, tag: 'num' + i
    });
  });
  txt(22.5, 25.8, [['eb', 'Overview · 近 30 天']], { x: 960, y: 330, align: 'c' });
  const trend = byText('.card.pad', 'Agent 使用趋势'), bars = (D) => { const c = trend(D); return c && c.querySelector('svg.vz-t-bar'); };
  const WALL = ['.tiles', '#aiCard', '.ov-out', trend, '.ov-pers'];
  at(21.6, () => { const a = app(0); a.S.ov.stack = 'stacked'; a.go('overview'); solo(0, '.tiles'); });
  drive(0, 21.6, 27.9, (p, b, D) => D.querySelectorAll('.tiles .vz-kpi .v').forEach((v, i) => {
    if (v.dataset.count) v.textContent = Number(v.dataset.count).toLocaleString('en-US', { maximumFractionDigits: 1 });
    v.style.opacity = i < 3 ? E.inOut(lp(b, 27.35, .3)).toFixed(3) : '';
  }));
  drive(0, 21.6, 31, (p, b, D) => { const s = bars(D); if (s) growBars(s, b, 28.6, .07, .5); });
  tween(0, 25.9, 1.6, () => framing(0, '.tiles', TB), E.inOut, (T) => ({ s: T.s * .96, o: 0, bl: 4 }));
  at(27.6, () => solo(0, WALL));
  tween(0, 27.8, 2.4, () => Object.assign(framing(0, WALL, [1180, 560, 1360, 800]), { rx: 20, ry: -18, rz: -5 }), E.inOut);
  tween(0, 30.2, 3.4, () => ({ rx: 12, ry: 6, rz: 2, s: decks[0].C.s * 1.05 }), E.sine);
  tag(0, 28.4, 33.2, '.tiles', 'left', [['eb', 'Overview'], ['gap'], ['md sv', '186 个会话'], ['lt acc', '142 小时 · 5 个 Agent']], { st: .2, gap: 80 });
  tag(0, 29, 33.2, '#aiCard', 'top', [['eb', 'AI 解读 · 本地 Agent 一句话说透']], { at: 0 });
  tag(0, 29.4, 33.2, trend, 'left', [['md sv', '五个 Agent'], ['lt acc', '一张图对齐']], { at: .5, gap: 95 });
  tag(0, 30, 33.2, '.ov-pers', 'bottom', [['lt', '你的协作人格 →']], { at: 1 });
  tween(0, 33.3, 2, () => ({ rz: -70, s: decks[0].C.s * .45, o: 0, bl: 6, ax: 900 }), E.inOut);
});
