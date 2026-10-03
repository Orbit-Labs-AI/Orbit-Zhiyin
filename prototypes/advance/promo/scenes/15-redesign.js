/* 15-redesign 1d–1e（b11.8–23.0） — STORYBOARD.md v17.1（V1 / V2 T4–T6 / V4）.
   1d 我们认为，人与 AI 的协作，也值得被重新设计（b12.4–18.0）：b11.8 起 1c 的光标（10-intro 的短列，停在 (1400, 615)）
      「躺倒」向左展开成窄 ∩ 弧 arcD（H3，b13.4 落定 cc (744, 584) … cp (1176, 584)）；输入框从点组中心生出、落到 (960, 880)，
      b17.2–17.6 缩回点组。纠正气泡分两层：cx / ds 挂在点上方（同一点新气泡替换旧的），cc / gm / cp 挂在点下方（新的把旧的
      下推 64px，每点 2 个）；b16.8 起剩下的从最新到最旧依次缩回各自的点。
   1e So，We Redesign for everyone（b17.8–22.0）：弧展开成 R 420 圆环（H4，polar (960, 700)），环内三行字；b19.2 起虚线圆画进
      AGD.back，半径每帧取 cc 到 (960, 540) 的距离，所以 20-orbit 在 b21.6 收紧圆环时它跟着收，b22.4–23.0 淡出。
   b21.6 起圆环的 key 归 20-orbit；本场景只写 b11.8（H3，在 10-intro 段内，10-intro 不写 b11.8 之后的 key）与 b17.4 两个 key。 */
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
  // front-loaded but zero speed at both ends: the dots move off as soon as the previous content clears
  const H3E = (p) => { const s = p * p * (3 - 2 * p); return 1 - Math.pow(1 - s, 3); };
  // H3 (T4): from 1c's caret (column x 1400, y 547 … 683, r 16) the column lies down to the left into the 1d arc; cc, top
  // of the caret, travels furthest and leaves first (stag .05), the path bows up 40px. Lands b13.4 at cc (744, 584) /
  // cx (852, 566) / gm (960, 560) / ds (1068, 566) / cp (1176, 584), r 34, while 1c's icons fly out the other way
  AGD.key(11.8, 'arc', { ...AGD.P.arcD, dur: 1.4, stag: .05, arc: 40, ease: H3E });                            // H3
  // H4 (T6): polar about (960, 700), below the arc, so the bearings 298 / 321 / 0 / 39 / 62° open clockwise without
  // crossing: gm rises straight up the middle, cc / cp swing out and down like a flower opening. ph 207 = 209 − 5·0.4
  // keeps the v17 landing points and the b21.6 angle (228) that 20-orbit hands on from. H3E instead of E.inOut: T6 has
  // gm above y 300 by b18.0, before 「So，」 (y 400) lands (with E.inOut it would still be at y ≈ 506 and cross the word
  // at b18.2); H3E puts it at y ≈ 320 at b18.0 and clears line 3 (bottom 420) only after the 1d lines are gone (b17.8)
  AGD.key(17.4, 'ring', { cx: 960, cy: 540, R: 420, ph: 207, spin: 5, r: 40, dur: 1.6, stag: .05, polar: [960, 700], ease: H3E }); // H4

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
  // the box grows out of the dots' centroid ((960, ≈570) at b12.6, the arc still landing) down to (960, 880) by b13.2,
  // and shrinks back into it over b17.2–17.6
  const c = AGD.chat(12.6, 17.6, { x: 960, y: 880, w: 980, from: AGD.centroid, to: AGD.centroid });
  c.type(13.0, '请你修改', .8); c.type(14.05, 'fix', .47); c.type(14.82, '请你继续', .58); c.type(15.8, '看清需求', .9);
  // every correction bubble: [dot, b0, text, send beat | null]; sent ones pop at send + .15 (AGD.chat). Ten bubbles, two
  // per dot, gaps shrinking from .3 to .1 beats. T5 layers: cx / ds (UP) hang above their dots, a newer one replacing
  // the older (AGD's replace; while the new one pops over PIN the old one shrinks back into the dot), so each of them
  // holds its pair as far apart as the stream allows (14.1 / 15.66 and 14.4 / 15.76); cc / gm / cp hang below, the
  // newer one pushing the older down 64px (replace: false), at most 2 stacked
  const BUB = [
    [1, 14.1, '请你修改', 13.95], [3, 14.4, '不对，重来'], [4, 14.65, '说中文'], [2, 14.82, 'fix', 14.67],
    [0, 15.12, '别动这个文件'], [4, 15.28, '再改一版'], [0, 15.42, '还是报错'], [2, 15.54, 'fix again'],
    [1, 15.66, '请你继续', 15.51], [3, 15.76, '继续']
  ].map(([i, b0, text, send], k) => ({ i, b0, text, send, k }));
  // T5 tail anchors (dot x + dx, the box centre is dot x + 2·dx, see agBubbles): above cx 812 / ds 1108 (dy −r − 18,
  // boxes y ≈ 446–506 under line 3, bottom 420); below cc 690 / gm 960 / cp 1230 (dy r + 18, boxes from y ≈ 620, two
  // stacked reach ≈ 770, above the input box's top edge 836)
  const UP = [false, true, false, true, false], DX = [-54, -40, 0, 40, 54], R = AGD.P.arcD.r;
  // each bubble pops over PIN beats, stays ≥ 1.2 beats fully readable, shrinks over POUT beats; a natural life of LIFE
  // beats turns it into a rolling stream; whatever would outlive R0 + POUT shrinks back newest → oldest from R0 (T5:
  // b16.8–17.2), RS apart, the last one gone by b17.4 as H4 sets off
  const PIN = .5, POUT = .35, LIFE = 2.1, R0 = 16.8, RS = .05;
  for (const u of BUB) {
    const same = BUB.filter((v) => v.i === u.i && v.b0 > u.b0);
    u.b1 = u.b0 + LIFE;
    if (same[1]) u.b1 = Math.min(u.b1, same[1].b0 + .3);                                     // a 3rd one: the oldest goes
  }
  BUB.filter((u) => u.b1 >= R0 + POUT - 1e-6).sort((a, b) => b.b0 - a.b0).forEach((u, k) => { u.b1 = R0 + RS * k + POUT; });
  const slow = [];                                                                           // [AGD_BUB record, b0, b1]
  for (const u of BUB) {
    let o;
    if (UP[u.i]) o = { kind: 'fix', dx: DX[u.i], dy: -R - 18, until: u.b1 };
    else {
      // newer ones push it down, starting .15 beats before they pop so the old box has cleared the dot by the time the
      // new one is full size
      const push = BUB.filter((v) => v.i === u.i && v.b0 > u.b0 && v.b0 < u.b1 - POUT);
      const dy = (b) => R + 18 + 64 * push.reduce((s, v) => s + E.inOut(clamp((b - v.b0 + .15) / .45)), 0);
      o = { kind: 'fix', dx: DX[u.i], dy, until: u.b1, replace: false };
    }
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
  // 1e → 2 hand-off: while the three lines spread out (b21.4–22.0) the circle brightens .14 → .32, so in b22.0–22.5,
  // before the spiral shows, the screen is the ring tightening with the dots (R 420 → 300), not five loose dots; the
  // spiral's tail then starts on this very circle (R 300) as it fades
  AGD.back(19.2, 23.0, (b) => {
    const p = AGD.pos(0, b), R = Math.hypot(p.x - 960, p.y - 540), ang = Math.atan2(p.x - 960, -(p.y - 540)) * 180 / Math.PI;
    const a = E.inOut(clamp((b - 19.2) / .5)) * (1 - E.inOut(clamp((b - 22.4) / .6))) * (.14 + .18 * E.inOut(clamp((b - 21.4) / .7)));
    if (a <= .002 || R < 1) return '';
    return '<circle cx="960" cy="540" r="' + R.toFixed(1) + '" fill="none" stroke="#fff" stroke-opacity="' + a.toFixed(3) +
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
