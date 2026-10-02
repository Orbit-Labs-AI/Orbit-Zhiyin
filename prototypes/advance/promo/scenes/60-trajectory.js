/* v6 port: 03 · Trajectory: the playhead runs one session start to end, the phases are named as it passes */
scene('60-trajectory', () => {
  const tlsvg = '.tl-card svg.vz-t-timeline';
  at(62.5, () => { app(0).go('sessions'); solo(0, '.tl-card'); });
  tween(0, 63, 2, () => framing(0, '.tl-card', [1310, 540, 1040, 900]), E.quart, IN.plane);
  txt(63.4, 65.6, [['eb', '03 · Trajectory'], ['gap'], ['hv sv', '卡在哪一刻'], ['md acc', '逐秒回放，一眼看清']], { x: L, y: 540 }, { st: .25, outB: .5 });
  drive(0, 64.6, 68.6, (p, b) => { const a = app(0); if (a.S.sess.playing) a.W.eval('stopPlay()'); a.S.sess.ph = a.W.eval('traj(BYID[S.sess.sel]).T') * E.inOut(lp(b, 64.8, 3.6)); a.W.eval('tlFrame(true)'); });
  tween(0, 65.1, 1.4, () => framing(0, tlsvg, [1250, 500, 1300, 700], { max: 4, px: .18 }), E.inOut);
  drive(0, 66.5, 68.6, (p, b, D) => { const ph = D.querySelector(tlsvg + ' .vz-playhead'), card = D.querySelector('.tl-card'); if (!ph) return; const C = decks[0].C, lim = card.getBoundingClientRect().left - (680 - C.ax) / C.s; C.x = Math.min(lim, lerp(C.x, ph.getBoundingClientRect().left + 30, .12)); });   // ride with the playhead, but keep the card clear of the caption
  const PHASE = { '探索': ['读代码，找入口', ''], '规划': ['拆成 5 步', ''], '实施': ['纠偏 2 次', 'warn'], '部署': ['同一命令连续失败 4 次', 'crit'], '验证': ['上线验证通过 · 42 分钟', 'good'] };
  txt(65.8, 68.7, [['md sv', '<span class="ph-n"></span>'], ['lt', '<span class="ph-d"></span>']], { x: L, y: 880 }, {
    inB: .5, outB: .3, tick: (el, tl, life, t) => {
      const D = decks[0].D, svg = D && D.querySelector(tlsvg), ph = svg && svg.querySelector('.vz-playhead'); if (!ph) return;
      const px = ph.getBoundingClientRect().left; let cur = '探索';
      [...svg.querySelectorAll('text')].filter((x) => PHASE[x.textContent]).forEach((x) => { if (x.getBoundingClientRect().left - 14 <= px) cur = x.textContent; });
      if (el.dataset.p !== cur) { el.dataset.p = cur; el.querySelector('.ph-n').textContent = cur; const d = el.querySelector('.ph-d'); d.textContent = PHASE[cur][0]; d.className = 'ph-d ' + PHASE[cur][1]; el._t = t; }
      const k = E.out(clamp((t - (el._t || 0)) / (.25 * BEAT))); el.querySelectorAll('.ln>span').forEach((s) => { s.style.transform = 'translateY(' + ((1 - k) * 40).toFixed(1) + '%)'; s.style.opacity = k.toFixed(3); });
    }
  });
  const inspector = (D) => [...D.querySelectorAll('.tl-card div')].filter((e) => e.textContent.includes('事件检视') && e.getBoundingClientRect().width < 360).sort((a, b) => a.textContent.length - b.textContent.length).pop();
  tween(0, 68.6, 1.4, () => Object.assign(framing(0, inspector, [760, 560, 900, 620], { max: 3 }), { ry: 12 }), E.inOut);
  tag(0, 68.9, 70.9, inspector, 'right', [['hv sv', '每次失败'], ['md acc', '都留有现场']], { gap: 80 });
  tween(0, 71, .9, () => OUT.up(decks[0].C), E.in);
});
