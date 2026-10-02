/* v6 port: 01 · Analysis: the compass (缓 → 急 → 缓, one continuous sweep) */
scene('40-persona', () => {
  // needle bearing during the sweep: slow start, two and a half fast turns, a long slow arrival at north (your type)
  const SW0 = 37, SW1 = 46;
  function sweepAt(b) {
    if (b < SW0) return -150;
    const p = lp(b, SW0, SW1 - SW0), e = p < .5 ? 16 * Math.pow(p, 5) : 1 - Math.pow(-2 * p + 2, 5) / 2;     // quintic in-out
    const total = 1080 + 150;                                 // from -150° through about three and a half turns to north
    return -150 + total * e + (b > SW1 ? 4 * Math.sin((b - SW1) * 5) * Math.exp(-(b - SW1) * 2.2) : 0);
  }
  glowAt(33.4, .3, 2);
  drive(2, 33.3, 50.9, (p, b) => {
    const deg = sweepAt(b), speed = (sweepAt(b + .05) - sweepAt(b - .05)) / .1;
    const dip = b < 46 ? E.out(lp(b, 35, 1.4)) : b < 46.35 ? lerp(1, .4, E.inOut(lp(b, 46, .35))) : lerp(.4, 1, E.out(lp(b, 46.35, 1.2)));
    drawCompass({ deg, speed, mine: E.inOut(lp(b, 44.6, 1.6)), grow: dip, sweep: E.inOut(lp(b, 34, 2.4)), orbit: (b - 33.6) * 28 + deg * .3, settle: lp(b, 47, 1.8), tip: E.out(lp(b, 36.4, .8)) * (1 - E.inOut(lp(b, 46.8, .6))), needle: 1 });
  });
  tween(2, 33.6, 2.4, () => framing(2, 'all', [1120, 560, 760, 760]), E.inOut, (T) => ({ rx: 64, rz: 40, s: T.s * .6, o: 0, bl: 5 }));
  txt(34.2, 36.7, [['eb', '01 · Analysis'], ['gap'], ['hv sv', '16 种'], ['hv sv', '协作人格'], ['md acc', '4 个维度 · 8 个极']], { x: L - 30, y: 540 }, { st: .2, outB: .6 });
  tween(2, 36.4, 1.6, () => framing(2, 'all', [960, 540, 900, 900]), E.inOut);
  tween(2, 38, 7.6, () => ({ s: decks[2].C.s * 1.06, rz: -3 }), E.sine);
  txt(36.8, 46.5, [['md', '你是'], ['hv sv', '<span class="slot"><span class="s0"></span><span class="s1"></span></span>'], ['eb', '<span class="slot-c"></span>']], { x: 70, y: 540 }, {
    st: .15, inB: .7, outB: .5, tick: (el, tl, life, t) => {
      const b = t / BEAT, code = b >= 45.4 ? compassData().me.code : personaAt(sweepAt(b), 0).code, D = compassData();
      if (el._c !== code) { el._p = el._c; el._c = code; el._t = t; el.querySelector('.s0').textContent = el._p ? D.TYPES[el._p][0] : ''; el.querySelector('.s1').textContent = D.TYPES[code][0]; el.querySelector('.slot-c').textContent = code.split('').join(' '); }
      const k = E.out(clamp((t - el._t) / (.22 * BEAT)));
      el.querySelector('.s0').style.transform = 'translateY(' + (-k * 105).toFixed(1) + '%)'; el.querySelector('.s0').style.opacity = (1 - k).toFixed(3);
      el.querySelector('.s1').style.transform = 'translateY(' + ((1 - k) * 105).toFixed(1) + '%)'; el.querySelector('.s1').style.opacity = k.toFixed(3);
    }
  });
  // landing on yours: the needle settles at north, the rose folds and blooms with your values, the dial moves aside
  tween(2, 46.6, 1.8, () => framing(2, 'all', [640, 540, 860, 860]), E.inOut);
  glowAt(46, .6, 1.5);
  txt(47.2, 50.4, [['eb', '你的类型 · Your type'], ['gap'], ['xl sv', '<span class="serif">DIMV</span>'], ['md', '指挥家 <span class="serif acc"><i>The Conductor</i></span>'], ['gap'], ['lt', '整段交出，多线并进，亲自验收。'], ['gap'], ['eb', '委托 72 · 即兴 61 · 多线 73 · 求证 67']], { x: R + 40, y: 540, align: 'r' }, { st: .12 });
  tween(2, 50.5, 1.2, () => OUT.far(decks[2].C), E.in);
  glowAt(50.5, 0, 1.2);
});
