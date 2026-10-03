/* 15-redesign 1d–1e（b12.4–23.0） — STORYBOARD.md v17.
   1d 我们认为，人与 AI 的协作，也值得被重新设计（b12.4–18.0）：点回到 1b 的弧（H3），输入框再次升起，纠正气泡越来越密，
      挂在点的下方（同一点的新气泡把旧的往下推 64px，最多叠 2 个），b16.8 起从新到旧依次缩回。
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
  AGD.key(12.4, 'pts', { pts: AGD.P.arc, r: 40, a: 1, dur: 1.0, stag: .06 });                                   // H3
  // H4 starts at b17.4 (not 17.8) so gm, which rises straight up the middle, is above 「So，」 (y 400) before K.big lands it at
  // b18.2; ph 207 = 209 − 5·0.4 keeps the b19.4 landing and the b21.6 angle (228) that 20-orbit hands on from
  AGD.key(17.4, 'ring', { cx: 960, cy: 540, R: 420, ph: 207, spin: 5, r: 40, dur: 1.4, stag: .05, polar: [960, 540] });   // H4

  /* ---------- 1d 文字（三行底边 ≤ 420，b17.2–17.8 一起向上淡出、模糊） ---------- */
  const lift = () => (el, tl, life) => {                                                 // exit drifts up 36px
    const q = E.inOut(clamp((tl - (life - BB(.6))) / BB(.6)));
    el.style.transform = 'translate(-50%,-50%) translateY(' + (-36 * q).toFixed(1) + 'px)';
  };
  txt(12.8, 17.8, [['lt', '<span style="color:rgba(255,255,255,.6)">我们认为，</span>']], { x: 960, y: 150, align: 'c' },
    { anim: K.blurIn({ spread: .45, dur: .3, out: .6 }), tick: lift() });
  txt(13.2, 17.8, [['hv sv rd-h', '人与 AI 的协作，']], { x: 960, y: 255, align: 'c' }, { inB: .9, outB: .6 });
  txt(14.0, 17.8, [['hv rd-h rd-or', '也值得被重新设计']], { x: 960, y: 370, align: 'c' }, { inB: .9, outB: .6 });

  /* ---------- 1d 输入框 + 纠正气泡 ---------- */
  const c = AGD.chat(12.6, 17.6, { x: 960, y: 880, w: 980 });
  c.type(13.4, '请你修改', .35); c.type(13.9, 'fix', .2); c.type(14.25, '请你继续', .3);
  // every correction bubble: [dot, b0, text, send beat | null]; sent ones pop at send + .15 (AGD.chat)
  const BUB = [
    [1, 13.95, '请你修改', 13.8], [2, 14.0, '不对，重来'], [3, 14.3, 'fix', 14.15], [4, 14.5, '说中文'],
    [0, 14.75, '请你继续', 14.6], [3, 14.9, '别动这个文件'], [0, 15.2, '还是报错'], [1, 15.5, '再改一版'],
    [2, 15.7, 'fix again'], [4, 15.9, '继续'], [3, 16.1, '回滚'], [0, 16.25, '看清需求'], [1, 16.4, '请你修改']
  ].map(([i, b0, text, send], k) => ({ i, b0, text, send, k }));
  // dx: the left dots lean left, the right dots lean right, gm alternates; sized so no box covers a neighbour's dot
  // or another dot's bubble (box centre = dot + 2·dx, see agBubbles)
  const DX = [() => -60, () => -40, (u) => (BUB.filter((v) => v.i === 2 && v.b0 < u.b0).length % 2 ? 30 : -30), () => 30, () => 60];
  const HOLD = 1.1, R0 = 16.8;                                                               // ~1 beat each; b16.8 = 1d.3
  for (const u of BUB) {
    const same = BUB.filter((v) => v.i === u.i && v.b0 > u.b0);
    u.b1 = u.b0 + HOLD;
    if (same[1]) u.b1 = Math.min(u.b1, same[1].b0 + .2);                                     // a 3rd one: the oldest goes
    u.dx = DX[u.i](u);
  }
  // 1d.3: whatever is still up at b16.8 shrinks back newest → oldest, .2 beats each, .05 apart
  BUB.filter((u) => u.b1 >= R0 - 1e-6).sort((a, b) => b.b0 - a.b0).forEach((u, k) => { u.b1 = R0 + .05 * k + .2; });
  for (const u of BUB) {
    const push = BUB.filter((v) => v.i === u.i && v.b0 > u.b0 && v.b0 < u.b1 - .2);          // newer ones push it down
    const dy = (b) => 40 + 18 + 64 * push.reduce((s, v) => s + E.inOut(clamp((b - v.b0) / .25)), 0);
    const o = { kind: 'fix', dx: u.dx, dy, until: u.b1 };
    if (u.send != null) c.send(u.send, u.i, o); else AGD.bubble(u.i, u.b0, u.b1, u.text, o);
    AGD.pulse(u.i, u.b0, .94, .3);                                                           // flinch: 被打断
  }

  /* ---------- 1e 虚线圆（#agdBack，跟着 cc 的半径，b22.4–23.0 淡出） ---------- */
  AGD.back(19.2, 23.0, (b) => {
    const p = AGD.pos(0, b), R = Math.hypot(p.x - 960, p.y - 540), ang = Math.atan2(p.x - 960, -(p.y - 540)) * 180 / Math.PI;
    const a = E.inOut(clamp((b - 19.2) / .5)) * (1 - E.inOut(clamp((b - 22.4) / .6)));
    if (a <= .002 || R < 1) return '';
    return '<circle cx="960" cy="540" r="' + R.toFixed(1) + '" fill="none" stroke="#fff" stroke-opacity="' + (.14 * a).toFixed(3) +
      '" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="2 7" transform="rotate(' + ang.toFixed(2) + ' 960 540)"/>';
  });

  /* ---------- 1e 环内三行（fit 640，b21.4–22.0 字距拉开退场） ---------- */
  txt(18.2, 22.0, [['hv rd-so', '<span class="w">So，</span>']], { x: 960, y: 400, align: 'c' },
    { anim: K.big({ scale: 3, dur: .45, out: .6, spread: true }) });
  txt(18.6, 22.0, [['xl sv rd-xl', '<span class="w">We </span><span class="w">Redesign</span>']], { x: 960, y: 520, align: 'c' },
    { anim: K.words({ at: [0, .4], fit: 640, out: .6, spread: true }) });
  txt(19.4, 22.0, [['xl sv rd-xl', '<span class="w">for <b class="rd-or">everyone</b></span>']], { x: 960, y: 645, align: 'c' },
    { anim: K.words({ at: [0], fit: 640, out: .6, spread: true }) });
});
