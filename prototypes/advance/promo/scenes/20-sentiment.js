/* 3 情绪：听懂每一句话（b12.9–21.6, deck 1）. STORYBOARD.md KF 3.1–3.4.
   First person on the sentiment chart: it spins in out of the mark's hole and becomes a road; the camera rides along
   the time axis while the curve, the band and the correction bars are drawn ahead of it and the phrases you say stand
   up beside it as signposts; then the camera pushes through towards the vanishing point and the deck is gone by b21.6. */
scene('20-sentiment', () => {
  const MOOD = 'svg.vz-t-moodcorr', moodCard = (D) => { const s = D.querySelector(MOOD); return s && s.closest('.card'); };
  const RIDE0 = 14.4, RIDE1 = 20.4, PUSH = 20.4, GONE = 21.6;
  // the chart's box in deck 1's frame (measured once the page is up; 689/238 was the v6 layout)
  let SV = null; const sv = () => { if (SV) return SV; const s = decks[1].D.querySelector(MOOD); if (!s) return { x: 689, y: 238 }; const r = s.getBoundingClientRect(); return (SV = { x: r.left, y: r.top }); };
  // the drawing head (svg units) runs at an even pace
  const headX = (b) => 60 + 790 * lp(b, RIDE0 - .4, RIDE1 - RIDE0 + .6);
  // the road: tilted back ~50° (v6 had 58°) so the band and the bars stay readable
  // the drawing head is the camera's anchor: what is drawn trails behind it towards the lower right, the road ahead
  // recedes to the upper left, and the lower left stays free for the title
  const ride = (b) => ({ x: sv().x + headX(b) + 10, y: sv().y + 134, s: 2.2, ax: 1360, ay: 420, rx: 50, ry: 0, rz: -106, z: 0, o: 1, bl: 0 });
  at(12.9, () => { app(1).go('sentiment'); solo(1, moodCard); SV = null; });
  // KF 3.1: spins in out of the hole (1.6 beats)
  tween(1, 13.4, 1.6, () => ride(15.0), E.out, (T) => ({ s: T.s * .14, rz: T.rz - 200, o: 0, bl: 6 }));
  // ride, then KF 3.4 the push-through: the zoom grows exponentially (2.5×) towards the far end of the road while it
  // blurs (0 → 12 px) and fades; the anchor drifts up to the screen centre, where the next scene's numbers start
  drive(1, 15.0, GONE, (p, b) => {
    const r = ride(b), C = decks[1].C, q = lp(b, PUSH, GONE - PUSH), e = E.in(q);
    C.x = r.x + 40 * e; C.y = r.y; C.s = r.s * Math.pow(2.5, e); C.ay = lerp(r.ay, 540, E.inOut(q)); C.ax = lerp(r.ax, 960, E.inOut(q));
    C.bl = 12 * E.inOut(q); C.o = q >= 1 ? 0 : 1 - E.in(clamp(q * 1.05));
  });
  drive(1, 12.95, GONE, (p, b, D) => { const s = D.querySelector(MOOD); if (!s) return; clipTo(s, 36, headX(b) + 34, 'path.vz-line, path.vz-cband, circle.vz-pt, text.vz-lbl'); riseRects(s, headX(b) + 34, 214); });
  // KF 3.2–3.3: eight signposts, one every 0.7 beat from b14.8 (a blip each in the soundtrack), last one b19.7
  const PH = [['用中文', 9, '偏好'], ['先只读审查', 5, '规划'], ['方向错误', 3, '纠偏'], ['部署后验证线上', 7, '验证'], ['直接合并', 6, '纠偏'], ['简洁一点', 4, '风格'], ['不要改别的文件', 4, '纠偏'], ['可以，提交吧', 12, '满意']];
  const PHC = { 偏好: 'var(--a2)', 规划: 'var(--a3)', 纠偏: 'var(--a1)', 验证: '#6fcf97', 风格: 'var(--a5)', 满意: '#cfe3e8' };
  at(12.95, () => {
    PH.forEach((ph, i) => {
      const bi = 14.8 + i * .7, x = sv().x + headX(bi) + 20, y = sv().y - 40;      // all on the road's left edge, hanging outwards
      const el = document.createElement('div'); el.className = 'phr'; el.style.left = x + 'px'; el.style.top = y + 'px';
      el.innerHTML = '<i style="background:' + PHC[ph[2]] + '"></i>「' + ph[0] + '」<b>×' + ph[1] + '</b><small>' + ph[2] + '</small>';
      el.dataset.b = bi; decks[1].rig.appendChild(el); (decks[1].phr = decks[1].phr || []).push(el);
    });
  });
  drive(1, 13, GONE + .2, (p, b) => (decks[1].phr || []).forEach((el) => {     // stand up on their beat, counter-turned to face the camera, right end on the edge
    const q = E.out(lp(b, +el.dataset.b, .4)), C = decks[1].C;
    // each one fades 1.3 beats after it stood up, before the road carries it down into the title's corner
    const gone = E.inOut(lp(b, +el.dataset.b + 1.3, .5));
    el.style.opacity = b >= GONE ? '0' : (q * (1 - gone)).toFixed(3);
    el.style.transformOrigin = '0 0';
    el.style.transform = 'rotateZ(' + (-C.rz) + 'deg) rotateX(' + (-C.rx) + 'deg) scale(' + (lerp(.6, 1, ease.back(q)) / C.s * 2.3).toFixed(4) + ') translate(calc(-100% - 10px),' + (-100 + (1 - q) * 60).toFixed(1) + '%)';
  }));
  // title block at the lower left, clear of the road and the signposts; leaves with its letters drifting apart b19.8–20.4
  const TX = 110;
  txt(15.4, 20.4, [['eb', 'Sentiment · 情绪与语义']], { x: TX, y: 850 }, { inB: .8, outB: .6, spread: 1 });
  txt(15.7, 20.4, [['hv', '听懂每一句话']], { x: TX, y: 925 }, { anim: K.blurIn({ spread: .6, dur: .35, out: .6, spread2: true }) });
  txt(16.4, 20.4, [['lt', '<span style="color:var(--a1)">本地 Agent 给每条消息打分、归类</span>']], { x: TX, y: 1000 }, { inB: .8, outB: .6, spread: 1 });
});
