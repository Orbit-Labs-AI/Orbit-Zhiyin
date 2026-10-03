/* 15-redesign 1d–1e（b12.4–23.0） — STORYBOARD.md v17.
   1d 我们认为，人与 AI 的协作，也值得被重新设计（b12.4–18.0）：点回到 1b 的弧（H3），输入框再次升起，纠正气泡越来越密，
      挂在点的下方（同一点的新气泡把旧的往下推 64px，每点 2 个），每个约 2 拍滚动消失，b16.9 起剩下的从旧到新依次缩回。
   1e So，We Redesign for everyone（b17.8–22.0）：弧展开成 R 420 圆环（H4，polar），环内三行字；b19.2 起虚线圆画进
      AGD.back，半径每帧取 cc 到 (960, 540) 的距离，所以 20-orbit 在 b21.6 收紧圆环时它跟着收，b22.4–23.0 淡出。
   b21.6 起圆环的 key 归 20-orbit；本场景只写 b12.4 与 b17.4 两个 key。 */
'use strict';
css(`
.k .ln.rd-h{font-size:100px}
.k .ln.rd-or>span,.k .rd-or{color:var(--a1)}
.k .ln.rd-so{font-size:56px;font-weight:300;color:rgba(255,255,255,.7);letter-spacing:0}
.k .ln.rd-xl{font-size:96px}
.k .ln.sv b.rd-or{color:var(--a1);-webkit-text-fill-color:var(--a1)}
`);
scene('15-redesign', () => {
  /* ---------- Agent 点 ---------- */
  // H3: same 1.0 beat / stag .06, but the same front-loaded ease as H2 (zero speed at both ends): with E.inOut the dots
  // barely leave scatterC until b12.8, which reads as a dead hold after 1c's text clears, and gm (960, 110 → 492) is
  // still at y ≈ 170 when 「我们认为，」 (y 150) blurs in at b12.8; this way it is at y ≈ 290
  const H3E = (p) => { const s = p * p * (3 - 2 * p); return 1 - Math.pow(1 - s, 3); };
  AGD.key(12.4, 'pts', { pts: AGD.P.arc, r: 40, a: 1, dur: 1.0, stag: .06, ease: H3E });                       // H3
  // H4 starts at b17.4 (not 17.8) so gm, which rises straight up the middle, is above 「So，」 (y 400) before K.big lands it at
  // b18.2; ph 207 = 209 − 5·0.4 keeps the b19.4 landing and the b21.6 angle (228) that 20-orbit hands on from
  AGD.key(17.4, 'ring', { cx: 960, cy: 540, R: 420, ph: 207, spin: 5, r: 40, dur: 1.4, stag: .05, polar: [960, 540] });   // H4

  /* ---------- 1d 文字（三行底边 ≤ 420，b17.2–17.8 一起向上淡出、模糊） ---------- */
  // pacing: the reveals run slower, and while they are up all three lines drift up together at 6 px/beat (no dead
  // hold between the reveal and the exit); line 1 also lifts 36px on its exit (lines 2–3 rise with mask's own exit)
  const drift = (exit) => (el, tl, life, ts) => {
    const q = exit ? E.inOut(clamp((tl - (life - BB(.6))) / BB(.6))) : 0;
    el.style.transform = 'translate(-50%,-50%) translateY(' + (-6 * (ts / BEAT - 12.8) - 36 * q).toFixed(1) + 'px)';
  };
  txt(12.8, 17.8, [['lt', '<span style="color:rgba(255,255,255,.6)">我们认为，</span>']], { x: 960, y: 150, align: 'c' },
    { anim: K.blurIn({ spread: .7, dur: .5, out: .6 }), tick: drift(true) });
  txt(13.2, 17.8, [['hv sv rd-h', '人与 AI 的协作，']], { x: 960, y: 255, align: 'c' }, { inB: 1.4, outB: .6, tick: drift() });
  txt(14.0, 17.8, [['hv rd-h rd-or', '也值得被重新设计']], { x: 960, y: 370, align: 'c' }, { inB: 1.4, outB: .6, tick: drift() });

  /* ---------- 1d 输入框 + 纠正气泡 ---------- */
  // typing ~.1–.2 beats a character, faster as the corrections pile up; the box is never idle: the 4th one is typed
  // but never sent (the box sinks with it at b17.2)
  const c = AGD.chat(12.6, 17.6, { x: 960, y: 880, w: 980 });
  c.type(13.0, '请你修改', .8); c.type(14.05, 'fix', .47); c.type(14.82, '请你继续', .58); c.type(15.8, '看清需求', .9);
  // every correction bubble: [dot, b0, text, send beat | null]; sent ones pop at send + .15 (AGD.chat). Ten bubbles,
  // two per dot (no dot ever holds a third), gaps shrinking from .3 to .1 beats
  const BUB = [
    [1, 14.1, '请你修改', 13.95], [2, 14.4, '不对，重来'], [4, 14.65, '说中文'], [3, 14.82, 'fix', 14.67],
    [3, 15.12, '别动这个文件'], [1, 15.28, '再改一版'], [0, 15.42, '还是报错'], [2, 15.54, 'fix again'],
    [0, 15.66, '请你继续', 15.51], [4, 15.76, '继续']
  ].map(([i, b0, text, send], k) => ({ i, b0, text, send, k }));
  // dx: the left dots lean left, the right dots lean right, gm alternates; sized so no box covers a neighbour's dot
  // or another dot's bubble (box centre = dot + 2·dx, see agBubbles)
  const DX = [() => -60, () => -40, (u) => (BUB.filter((v) => v.i === 2 && v.b0 < u.b0).length % 2 ? 30 : -30), () => 30, () => 60];
  // each bubble pops over PIN beats, stays ≥ 1.2 beats fully readable, shrinks over POUT beats; a natural life of LIFE
  // beats turns it into a rolling stream; whatever would outlive R0 + POUT shrinks back oldest → newest from R0, RS apart
  const PIN = .5, POUT = .35, LIFE = 2.1, R0 = 16.9, RS = .06;
  for (const u of BUB) {
    const same = BUB.filter((v) => v.i === u.i && v.b0 > u.b0);
    u.b1 = u.b0 + LIFE;
    if (same[1]) u.b1 = Math.min(u.b1, same[1].b0 + .3);                                     // a 3rd one: the oldest goes
    u.dx = DX[u.i](u);
  }
  BUB.filter((u) => u.b1 >= R0 + POUT - 1e-6).sort((a, b) => a.b0 - b.b0).forEach((u, k) => { u.b1 = R0 + RS * k + POUT; });
  const slow = [];                                                                           // [AGD_BUB record, b0, b1]
  for (const u of BUB) {
    // newer ones push it down, starting .15 beats before they pop so the old box has cleared the dot by the time the
    // new one is full size
    const push = BUB.filter((v) => v.i === u.i && v.b0 > u.b0 && v.b0 < u.b1 - POUT);
    const dy = (b) => 40 + 18 + 64 * push.reduce((s, v) => s + E.inOut(clamp((b - v.b0 + .15) / .45)), 0);
    const o = { kind: 'fix', dx: u.dx, dy, until: u.b1 };
    if (u.send != null) c.send(u.send, u.i, o); else AGD.bubble(u.i, u.b0, u.b1, u.text, o);
    const r = AGD_BUB[AGD_BUB.length - 1]; slow.push([r, r.b0, r.b1]);
    AGD.pulse(u.i, u.b0, .94, .45);                                                          // flinch: 被打断
  }
  // AGD pops a bubble in .25 beats and shrinks it in .2 (agBubbles reads u.b0 / u.b1 every frame). This drive runs
  // before applyAgents and re-times this scene's records so the pop takes PIN beats and the shrink POUT beats, starting
  // at b0 and ending at b1 as registered (pure function of b, so seeking / --only renders get the same frame)
  every(13.0, 17.8, (p, b) => {
    for (const [r, B0, B1] of slow) {
      r.b0 = b < B0 ? B0 : b < B0 + PIN ? b - (b - B0) * .25 / PIN : B0 + PIN - .25;
      r.b1 = b < B1 - POUT ? B1 - POUT + .2 : b < B1 ? b + .2 - .2 * (b - B1 + POUT) / POUT : B1;
    }
  });

  /* ---------- 1e 虚线圆（#agdBack，跟着 cc 的半径，b22.4–23.0 淡出） ---------- */
  AGD.back(19.2, 23.0, (b) => {
    const p = AGD.pos(0, b), R = Math.hypot(p.x - 960, p.y - 540), ang = Math.atan2(p.x - 960, -(p.y - 540)) * 180 / Math.PI;
    const a = E.inOut(clamp((b - 19.2) / .5)) * (1 - E.inOut(clamp((b - 22.4) / .6)));
    if (a <= .002 || R < 1) return '';
    return '<circle cx="960" cy="540" r="' + R.toFixed(1) + '" fill="none" stroke="#fff" stroke-opacity="' + (.14 * a).toFixed(3) +
      '" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="2 7" transform="rotate(' + ang.toFixed(2) + ' 960 540)"/>';
  });

  /* ---------- 1e 环内三行（fit 640，b21.4–22.0 字距拉开退场） ---------- */
  // pacing: 「So，」 settles over .7 beats and the words cut in .45 beats apart; from b18.4 the three lines push in
  // together (scale 1 → 1.04 about the ring centre, constant speed) so they never sit still under the turning ring.
  // 1.04 keeps the corners of a 640-px line inside the ring's inner edge (radius 380)
  const zoom = (y, own) => (el, tl, life, ts) => {
    const s = 1 + .04 * clamp((ts / BEAT - 18.4) / 3.6), add = ' translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')';
    el.style.transform = (own ? 'translate(-50%,-50%)' : el.style.transform) + add;     // K.words rewrites it every frame, K.big never
  };
  txt(18.2, 22.0, [['hv rd-so', '<span class="w">So，</span>']], { x: 960, y: 400, align: 'c' },
    { anim: K.big({ scale: 3, dur: .7, out: .6, spread: true }), tick: zoom(400, true) });
  txt(18.7, 22.0, [['xl sv rd-xl', '<span class="w">We </span><span class="w">Redesign</span>']], { x: 960, y: 520, align: 'c' },
    { anim: K.words({ at: [0, .45], fit: 640, out: .6, spread: true }), tick: zoom(520) });
  txt(19.6, 22.0, [['xl sv rd-xl', '<span class="w">for <b class="rd-or">everyone</b></span>']], { x: 960, y: 645, align: 'c' },
    { anim: K.words({ at: [0], fit: 640, out: .6, spread: true }), tick: zoom(645) });
});
