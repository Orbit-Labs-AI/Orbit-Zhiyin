/* v6 port: the sentiment curve, first person: ride along it while it is drawn, the phrases you say stand up beside it */
scene('20-sentiment', () => {
  const MOOD = 'svg.vz-t-moodcorr', moodCard = (D) => { const s = D.querySelector(MOOD); return s && s.closest('.card'); };
  const headX = (b) => 60 + 760 * E.inOut(lp(b, 14.4, 7.8));                          // svg units
  const ride = (b) => ({ x: 689 + headX(b) - 30, y: 372, s: 3.1, ax: 960, ay: 720, rx: 58, ry: 0, rz: -72, z: 0, o: 1, bl: 0 });
  at(12.9, () => { app(1).go('sentiment'); solo(1, moodCard); });
  tween(1, 13.6, 1.7, () => ride(15.3), E.out, (T) => ({ s: T.s * .14, rz: T.rz - 200, o: 0, bl: 6 }));
  drive(1, 15.3, 22.3, (p, b) => { const r = ride(b), C = decks[1].C; C.x = r.x; C.y = r.y; });
  drive(1, 12.95, 22.6, (p, b, D) => { const s = D.querySelector(MOOD); if (!s) return; clipTo(s, 36, headX(b) + 34, 'path.vz-line, path.vz-cband, circle.vz-pt, text.vz-lbl'); riseRects(s, headX(b) + 34, 214); });
  const PH = [['用中文', 9, '偏好'], ['先只读审查', 5, '规划'], ['方向错误', 3, '纠偏'], ['部署后验证线上', 7, '验证'], ['直接合并', 6, '纠偏'], ['简洁一点', 4, '风格'], ['不要改别的文件', 4, '纠偏'], ['可以，提交吧', 12, '满意']];
  const PHC = { 偏好: 'var(--a2)', 规划: 'var(--a3)', 纠偏: 'var(--a1)', 验证: '#6fcf97', 风格: 'var(--a5)', 满意: '#cfe3e8' };
  at(12.95, () => {
    PH.forEach((ph, i) => {
      const bi = 15 + i * .82, x = 689 + headX(bi) + 40, y = 260 + (i % 2 ? 228 : 4);
      const el = document.createElement('div'); el.className = 'phr'; el.style.left = x + 'px'; el.style.top = y + 'px';
      el.innerHTML = '<i style="background:' + PHC[ph[2]] + '"></i>「' + ph[0] + '」<b>×' + ph[1] + '</b><small>' + ph[2] + '</small>';
      el.dataset.b = bi; decks[1].rig.appendChild(el); (decks[1].phr = decks[1].phr || []).push(el);
    });
  });
  drive(1, 13, 23.2, (p, b) => (decks[1].phr || []).forEach((el) => {     // stand up when the head reaches them
    const q = E.out(lp(b, +el.dataset.b, .6)), C = decks[1].C;
    el.style.opacity = (q * (1 - lp(b, 22.2, .6))).toFixed(3);
    el.style.transform = 'translate(-50%,-100%) rotateZ(' + (-C.rz) + 'deg) rotateX(' + (-C.rx) + 'deg) translateY(' + ((1 - q) * 30).toFixed(1) + 'px) scale(' + (lerp(.6, 1, q) / C.s * 2.6).toFixed(4) + ')';
  }));
  txt(15.4, 21.9, [['eb', 'Sentiment · 情绪与语义'], ['gap'], ['hv sv', '听懂每一句话'], ['lt acc', '本地 Agent 给每条消息打分、归类']], { x: L - 60, y: 170 }, { st: .3, spread: 1, outB: .9 });
  tween(1, 22.2, 1.1, () => ({ o: 0, bl: 8, s: decks[1].C.s * 1.25 }), E.in);
});
