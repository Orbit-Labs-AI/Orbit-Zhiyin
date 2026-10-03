/* 15-redesign 1d–1e（b11.8–23.0） — STORYBOARD.md v17.1（V1 / V2 T4–T6 / V4）.
   1d 但，人与 Agent 的交互本身，也需要被重新定义（v17.2 文案，b12.8–17.8）：b11.8 起 1c 的光标（10-intro 的短列，停在 (1400, 615)）
      「躺倒」向左展开成窄 ∩ 弧 arcD（H3，b13.4 落定 cc (744, 584) … cp (1176, 584)）；输入框从点组中心生出、落到 (960, 880)，
      b17.2–17.6 缩回点组。纠正气泡分两层：cx / ds 挂在点上方（同一点新气泡替换旧的），cc / gm / cp 挂在点下方（新的把旧的
      下推 64px，每点 2 个）；b16.8 起剩下的从最新到最旧依次缩回各自的点。
   1e So，我们做了一个 Assistant / Redesign / Agent Workflow / for everyone（v17.2 文案，b18.2–22.0）：弧展开成 R 420 圆环（H4，polar (960, 700)），环内三行字；b19.2 起虚线圆画进
      AGD.back，半径每帧取 cc 到 (960, 540) 的距离，所以 20-orbit 在 b21.6 收紧圆环时它跟着收，b22.4–23.0 淡出。
   b21.6 起圆环的 key 归 20-orbit；本场景只写 b11.8（H3，在 10-intro 段内，10-intro 不写 b11.8 之后的 key）与 b17.4 两个 key。 */
'use strict';
css(`
.k .ln.rd-h{font-size:100px}
.k .ln.rd-or>span,.k .rd-or{color:var(--a1)}
.k .ln.rd-so{font-size:56px;font-weight:300;color:rgba(255,255,255,.7);letter-spacing:0}
.k .ln.rd-xl{font-size:84px}
.k .ln.sv b.rd-or{color:var(--a1);-webkit-text-fill-color:var(--a1)}
/* v17.2: the connectives 「但，」/「So，…」 share one light small size; 「重新定义」 is an orange .w inside silver type; the
   highlighter word keeps its own white fill so the band sits under the glyphs, not over the silver gradient */
.k .ln.rd-cj{font-size:44px;font-weight:300;color:rgba(255,255,255,.72);letter-spacing:0}
.k .ln.sv .w.rd-or{background:none;color:var(--a1);-webkit-text-fill-color:var(--a1)}
.k .ln.sv .rd-mk{color:#fff;-webkit-text-fill-color:#fff;--mk:rgba(226,96,43,.78)}
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
  // v17.2 copy: 「但，」 / 「人与 Agent 的交互本身，」 / 「也需要被重新定义」. 「但，」 lands alone first, the way 1e's 「So，」
  // does (K.big: soft and large, settled within .4 beats), and the dots flinch with it (r × .9); line 2 rises at b13.4 as
  // the arc lands; the orange highlighter under 「交互本身」 is driven by the correction bubbles (each one moves it a tenth
  // further, so it speeds up as they crowd in, b13.85 → b15.9); line 3: 「也需要被」 rises, then 「重新定义」 (orange)
  // drops in last through the line's mask and settles (scale 1.06 → 1, no flash), landing with the last bubble
  txt(12.8, 17.8, [['rd-cj', '<span class="w">但，</span>']], { x: 960, y: 150, align: 'c' },
    { anim: K.big({ scale: 2.2, dur: .4, out: .6, spread: true }), tick: drift(true) });
  for (let i = 0; i < 5; i++) AGD.pulse(i, 12.8, .9, .5);
  const markBy = (el, b) => {
    const p = BUB.reduce((s, u) => s + E.inOut(clamp((b - u.b0 + .25) / .4)), 0) / BUB.length;
    el.querySelectorAll('.mk').forEach((m) => { m.style.backgroundSize = (p * 100).toFixed(1) + '% .26em'; });
  };
  txt(13.4, 17.8, [['hv sv rd-h', '人与 Agent 的<span class="mk rd-mk">交互本身</span>，']], { x: 960, y: 255, align: 'c' },
    { inB: 1.2, outB: .6, tick: (el, tl, life, ts) => { drift()(el, tl, life, ts); markBy(el, ts / BEAT); } });
  const fall = (o) => (el, tl, life) => {
    const [a, w] = el.querySelectorAll('.w'), q = exitQ(tl, life, o.out);
    const p0 = E.expo(clamp(tl / BB(o.inB))), p1 = E.out(clamp((tl - BB(o.at)) / BB(o.dur)));
    a.style.transform = 'translateY(' + ((1 - p0) * 130 - (1 - q) * 30).toFixed(2) + '%)';
    a.style.opacity = Math.min(1, p0 * 1.4).toFixed(3);
    w.style.transform = 'translateY(' + (-(1 - p1) * 110 - (1 - q) * 30).toFixed(2) + '%) scale(' + lerp(1.06, 1, p1).toFixed(4) + ')';
    w.style.opacity = Math.min(1, p1 * 1.6).toFixed(3);
    leave(el, q, true);
  };
  txt(14.8, 17.8, [['hv sv rd-h', '<span class="w">也需要被</span><span class="w rd-or">重新定义</span>']], { x: 960, y: 370, align: 'c' },
    { anim: fall({ inB: 1.2, at: .6, dur: .5, out: .6 }), tick: drift() });

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

  /* ---------- 1e 环内一行小字 + 三行大字（fit，b21.4–22.0 字距拉开退场） ---------- */
  // v17.2 copy: 「So，我们做了一个 Assistant」 / 「Redesign」 / 「Agent Workflow」 / 「for everyone」. The small line comes
  // first (「So，」 lands soft and large like 1d's 「但，」, the rest follows from lower right), then the three big lines cut
  // in one per .45 beats from b19.0. From b18.4 everything pushes in together (scale 1 → 1.04 about the ring centre,
  // constant speed) so it never sits still under the turning ring; the fit widths keep every line's corners inside the
  // ring's inner edge (radius 380) at 1.04
  const zoom = (y, own) => (el, tl, life, ts) => {
    const s = 1 + .04 * clamp((ts / BEAT - 18.4) / 3.6), add = ' translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')';
    el.style.transform = (own ? 'translate(-50%,-50%)' : el.style.transform) + add;     // K.words rewrites it every frame, K.big never
  };
  txt(18.2, 22.0, [['rd-cj', '<span class="w">So，</span><span class="w">我们做了一个 </span><span class="w">Assistant</span>']],
    { x: 960, y: 362, align: 'c' }, { anim: K.big({ scale: 2.4, dur: .6, fly: .2, out: .6, spread: true }), tick: zoom(362, true) });
  // [beat, y, html, fit]
  for (const [b, y, h, fit] of [[19.0, 462, 'Redesign', 560], [19.45, 568, 'Agent Workflow', 620], [19.9, 674, 'for <b class="rd-or">everyone</b>', 600]]) {
    txt(b, 22.0, [['xl sv rd-xl', '<span class="w">' + h + '</span>']], { x: 960, y, align: 'c' },
      { anim: K.words({ at: [0], fit, out: .6, spread: true }), tick: zoom(y) });
  }
});
