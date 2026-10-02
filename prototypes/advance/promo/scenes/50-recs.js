/* v6 port: 02 · Recommend (缓): twelve suggestions on a tilted column add up the hours they save */
scene('50-recs', () => {
  const rcards = (D) => [...D.querySelectorAll('.rcard')], SAVE = [], RECB = 50.9, RECG = .5;
  at(49.9, () => {
    const a = app(0); a.go('recs'); solo(0, (D) => D.querySelector('.rcard').parentElement);
    rcards(a.D).forEach((c) => { const n = c.querySelector('[data-count]'), m = c.textContent.match(/≈\s*[\d.]+\s*(h|min)/); SAVE.push(n ? +n.dataset.count / (m && m[1] === 'min' ? 60 : 1) : 0); });
  });
  drive(0, 49.95, 57.6, (p, b, D) => {
    const cs = rcards(D);
    cs.forEach((c, i) => { const q = E.out(lp(b, RECB + i * RECG, .7)); c.style.opacity = q.toFixed(3); c.style.transform = 'translateX(' + ((1 - q) * 80).toFixed(1) + 'px)'; });
    const ct = D.querySelector('#content'); if (ct && cs[1]) { const step = cs[1].offsetTop - cs[0].offsetTop || 178; ct.scrollTop = Math.max(0, (b - RECB) / RECG - 2.4) * step * .92; }
  });
  tween(0, 50.4, 1.6, () => Object.assign(framing(0, [(D) => rcards(D)[0], (D) => rcards(D)[2]], [1260, 540, 820, 940], { max: 2.2 }), { ry: -14, rz: -3 }), E.quart, IN.rise);
  txt(50.8, 56.9, [['eb', '02 · Recommend'], ['gap'], ['xl sv', '<span class="cnt">0.0</span><span style="font-size:.38em;letter-spacing:0"> h / 月</span>'], ['md acc', '每月省下的时间'], ['gap'], ['lt', '<span class="cnt-n">0</span> / 12 条建议 · 按节省时间排序']], { x: L, y: 540 }, {
    st: .15, tick: (el, tl, life, t) => {
      const b = t / BEAT; let sum = 0, n = 0;
      SAVE.forEach((h, i) => { const q = E.out(lp(b, RECB + i * RECG + .25, .55)); sum += h * q; if (q > .5) n++; });
      el.querySelector('.cnt').textContent = sum.toFixed(1); el.querySelector('.cnt-n').textContent = n;
    }
  });
  tween(0, 57, 1, () => OUT.up(decks[0].C), E.in);
  // the top suggestion installs: modal above, words below
  const recDetail = (D) => smallest(D, '#main .card', '每月节省');
  at(56.6, () => { const a = app(1); a.go('recs'); const d = recDetail(a.D); const btn = d && d.querySelector('[data-act="install"]'); if (btn) btn.click(); solo(1, '#modal'); });
  tween(1, 57.3, 1.5, () => Object.assign(framing(1, '#modal', [960, 420, 1180, 640]), { rx: 14 }), E.quart, IN.rise);
  tween(1, 58.8, 4, () => ({ rx: 4, s: decks[1].C.s * 1.04 }), E.sine);
  txt(57.8, 62.7, [['row hv', ['<span class="sv-t">预览，</span>', '<span class="sv-t">再写入</span>']], ['md acc', '一键安装 · 随时撤销 · 装上后追踪 7 天效果']], { x: 960, y: 930, align: 'c' }, { st: .3 });
  clickAt(1, 59.4, '#modal .btn.p', (a, el) => a.click(el));
  clickAt(1, 61, '#modal .btn.p', (a, el) => a.click(el));
  tween(1, 62.8, .9, () => OUT.up(decks[1].C), E.in);
});
