/* 15-redesign 1d–1e（b11.8–27.4） — STORYBOARD.md v17.1（V1 / V2 T4–T6 / V4）.
   v17.3 节奏（看清文字）：本场景比 v17.2 长 2.1 拍——1d 从 b14.1 起的纠正气泡流按 ×1.4 放慢、之后的事件全部后移 1.6 拍，
   1e 在退场前再加 .5 拍；起点不变，交出的圆环形状不变（20-orbit 的 b21.6 key 由 SHIFT 推到 b23.7，见 H4 的 spin）。
   v17.4 节奏（每一幕的字都看清）：再长 2.3 拍——气泡流自 b14.1 起再放慢 ×1.3、寿命 3.15 拍（每个气泡完整可读 ≥ 2.06 拍），
   1d 之后的事件后移 1.3 拍；1e 的三行大字每 .4 拍切一行，退场前再加 1.0 拍。起点不变，交出的圆环形状不变（20-orbit 的
   key 由 SHIFT 推到本场景 b26.0，spin 21/5.7）。下面正文的拍号已是 v17.4 的。
   1d 但，人与 Agent 的交互本身，也需要被重新定义（v17.2 文案，b12.8–20.7）：b11.8 起 1c 的光标（10-intro 的短列，停在 (1400, 615)）
      「躺倒」向左展开成窄 ∩ 弧 arcD（H3，b13.4 落定 cc (744, 584) … cp (1176, 584)，此后整条弧随 1d 文字以 6px/拍 缓缓上移）；
      输入框从点组中心生出、落到 (960, 880)，b20.1–20.5 缩回点组。纠正气泡分两层：cx / ds 挂在点上方（同一点新气泡替换旧的），
      cc / gm / cp 挂在点下方（新的把旧的下推 64px，每点 2 个）；每个气泡完整可读 ≥ 2.06 拍，b18.2 起由旧到新依次缩回，
      b19.7 起剩下的从最新到最旧缩回各自的点。
   1e So，我们做了一个 Assistant / Redesign / Agent Workflow / for everyone（v17.2 文案，b21.1–26.4）：弧展开成 R 420 圆环（H4，polar (960, 700)），环内三行字；b22.1 起虚线圆画进
      AGD.back，半径每帧取 cc 到 (960, 540) 的距离，所以 20-orbit 在（后移后的）b26.0 收紧圆环时它跟着收，b26.8–27.4 淡出。
   v17.5 逐词节奏（总长不变）：每个词组快速进场（≈ .25 拍）后带一点缩放/模糊的落定再停半拍左右——「人与 Agent 的」b13.4 ·「交互本身，」13.85 ·
   「也需要被」15.1 ·「重新定义」15.6（落在 15.9）；「So，」21.1 ·「我们做了一个」21.36 ·「Assistant」21.6（落在 21.84）；三行大字仍硬切，各带 .32 拍落定。
   b26.0 起圆环的 key 归 20-orbit；本场景只写 b11.8（H3，在 10-intro 段内，10-intro 不写 b11.8 之后的 key）与 b20.3 两个 key。
   v17.7 点形态（STORYBOARD「v17.7」F3）：b11.8 1c 的五色分段光标逐段转 90° 倒下（.4 拍），b12.2 圆回带 logo 的 pill、指向将长出的输入框，
   b12.9 起是沿弧切线略扁的珠子（w 2.2，随字上移）；打字时接收该句的点变 caret（hpx 38，逐字 ×1.04 轻跳，框内光标染成该 Agent 色），
   发送前 .2 拍变 tail；每个纠正气泡的点先出尾巴（.15 拍，描边 1.6 + 底色 .15 一拍，代替旧的 .94 缩一下），气泡收回时尾巴先收、点再圆；
   b13.85 ds 变笔头沿荧光笔方向右上滑 24 / 18 px 再回；b15.9「重新定义」落定时弧两端轻压（h .92）；b19.85 五点变 pill 把输入框收回；
   b20.4 起展开成环途中逐个变 bead；虚线圆从五颗珠子处向两侧画出（b22.1–22.9）；三行硬切各让珠子沿环前跳 4°（spin 改 9/5.7，交接角仍 228°）；
   「everyone」落定（b23.0）珠子 glow .5 一拍；三行大字从最近珠子一侧轻移 12 px 进场。
   v18.6 R2「圆形 + 闪烁」：1d 去掉 pill / head / tail 与速度拉伸（noStretch b11.8–27.4），光标倒下后各段直接圆回带 logo 的圆点；
   b12.38 五点 blink（「但，」离开 + 输入框长出），气泡从圆点弹出时该点 blink + 暖色描边（.5 拍正弦），ds 到荧光笔处 b13.95 blink，
   「重新定义」落定 b15.9 cc / cp blink，输入框收回 b20.42 五点 blink；打字 caret 与 1e 珠子保留。 */
'use strict';
css(`
.k .ln.rd-h{font-size:100px}
.k .ln.rd-or>span,.k .rd-or{color:var(--a1)}
.k .ln.rd-so{font-size:56px;font-weight:300;color:rgba(255,255,255,.7);letter-spacing:0}
.k .ln.rd-xl{font-size:94px}
/* v18.1: 1e's So line — silver, a step under the peak (36 px, 500); 「So，」 lands alone at the ring centre first, so the
   line may not clip it on its way up to its slot */
.k .ln.rd-s1{font-size:52px;font-weight:600;letter-spacing:0;overflow:visible}
/* v18.5: 「Assistant」 one step up (60 px, pure white) — the answer the line gives */
.k .ln.rd-s1 .w.rd-w{font-size:60px;margin-left:.12em;letter-spacing:-.015em}
/* the bigger line must stay inside the ring's inner edge (≈ 380): the full-width comma gives back part of its blank half
   and the CJK run sits a hair tighter, and the line sits 10 px lower (y 362) where the ring is wider */
.k .ln.rd-s1 .w:first-child{margin-right:-.3em}
.k .ln.rd-s1 .w:nth-child(2){letter-spacing:-.05em}
/* v18.5 QA: those three trims give back ≈ 20 px, so the cx bead (b31–33) no longer grazes 「So」 */
/* v18.2: the So line is 48 px / 600 and 「Assistant」 is pure white (no silver gradient), so the line reads as the answer */
.k .ln.sv .w.rd-w{background:none;color:#fff;-webkit-text-fill-color:#fff}
.k .ln.sv b.rd-or{color:var(--a1);-webkit-text-fill-color:var(--a1)}
/* v17.2: the connectives 「但，」/「So，…」 share one light small size; 「重新定义」 is an orange .w inside silver type; the
   highlighter word keeps its own white fill so the band sits under the glyphs, not over the silver gradient */
/* v18.5: 「但，」 is the story's pivot, so it matches the So line's weight (52 px / 600, silver at α 1) */
.k .ln.rd-cj{font-size:52px;font-weight:600;letter-spacing:0;overflow:visible}
.k .ln.sv .w.rd-or{background:none;color:var(--a1);-webkit-text-fill-color:var(--a1)}
.k .ln.sv .rd-mk{color:#fff;-webkit-text-fill-color:#fff;--mk:rgba(226,96,43,.78)}
`);
scene('15-redesign', () => {
  /* ---------- Agent 点 ---------- */
  // front-loaded but zero speed at both ends: the dots move off as soon as the previous content clears
  const H3E = (p) => { const s = p * p * (3 - 2 * p); return 1 - Math.pow(1 - s, 3); };
  // v18.1: the arc sits 24 px lower (cc / cp land at y 608) so the cx / ds bubbles above it clear 「也需要被重新定义」, now at y 395
  // H3 (T4): from 1c's caret (column x 1400, y 547 … 683, r 16) the column lies down to the left into the 1d arc; cc, top
  // of the caret, travels furthest and leaves first (stag .05), the path bows up 40px. Lands b13.4 at cc (744, 584) /
  // cx (852, 566) / gm (960, 560) / ds (1068, 566) / cp (1176, 584), r 34, while 1c's icons fly out the other way
  // v17.3: from b13.4 the arc rises with the 1d lines (6 px/beat, the same drift), so the dots and their bubbles never sit
  // frozen while the stream is read; by H4 (b20.3) it is 41 px higher, which only helps gm clear the lines above
  // v18.3: the arc no longer rises with the lines — at 6 px/beat it lifted the cx / ds bubbles to y ≈ 430, onto
  // 「重新定义」; level, their tops stay ≥ 460 (the dots are never still: tails, carets, the pen keep them moving)
  AGD.key(11.8, 'arc', { ...AGD.P.arcD, cy: AGD.P.arcD.cy + 24, dur: 1.4, stag: .05, arc: 40, ease: H3E }); // H3
  // H4 (T6): polar about (960, 700), below the arc, so the bearings 298 / 321 / 0 / 39 / 62° open clockwise without
  // crossing: gm rises straight up the middle, cc / cp swing out and down like a flower opening. ph 207 = 209 − 5·0.4
  // keeps the v17 landing points and the angle (228) that 20-orbit hands on from. v17.4: this key moved b19.0 → b20.3 and
  // 20-orbit's ring key (its b21.6) is pushed to b26.0 of this scene by SHIFT, so the spin is 21° over 5.7 beats: the
  // ring still reaches 228 exactly at the hand-off. H3E instead of E.inOut: T6 has gm above y 300 by b20.9, before
  // 「So，」 (y 400) lands (with E.inOut it would still be at y ≈ 506 and cross the word at b21.1); H3E puts it at y ≈ 320
  // at b20.9 and clears line 3 (bottom 420) only after the 1d lines are gone (b20.7)
  // v17.7: each of 1e's three hard cuts (CUT, v18.2: b22.5 / 22.9 / 23.3) steps the beads 4° on along the ring (.2 beat, E.inOut, no
  // rebound); the spin gives those 12° back (9° over 5.7 beats), so the ring still hands on at 228° (b26.0)
  // v18.2: the three cuts moved 21.9 / 22.3 / 22.7 → 22.5 / 22.9 / 23.3 so the whole So line holds alone ≥ .5 beat first
  const CUT = [22.5, 22.9, 23.3];
  const JUMP = (b) => 4 * CUT.reduce((s, t) => s + E.inOut(clamp((b - t) / .2)), 0);
  // v18.1 slow push on the 1e peak: ring + So line + three lines scale 1 → 1.04 about the ring centre from the first hard
  // cut (CUT[0], v18.2: b22.5) to b25.7 (E.sine), then hold at 1.04 into 20-orbit's b26.0 key; the beads ride the scaled radius so they
  // stay matched with the dashed circle and the type
  const PUSH = (b) => 1 + .04 * E.sine(clamp((b - CUT[0]) / (25.7 - CUT[0])));
  AGD.key(20.3, 'ring', { cx: 960, cy: 540, R: (b) => 420 * PUSH(b), ph: (b) => 207 + JUMP(b), spin: 9 / 5.7, r: 40, dur: 1.6, stag: .05, polar: [960, 700], ease: H3E }); // H4

  /* ---------- 1d 文字（三行底边 ≤ 420，b20.1–20.7 一起向上淡出、模糊） ---------- */
  // pacing: the reveals run slower, and while they are up all three lines drift up together at 6 px/beat (no dead
  // hold between the reveal and the exit); line 1 also lifts 36px on its exit (lines 2–3 rise with mask's own exit)
  const drift = (exit) => (el, tl, life, ts) => {
    const q = exit ? E.inOut(clamp((tl - (life - BB(.6))) / BB(.6))) : 0;
    el.style.transform = 'translate(-50%,-50%) translateY(' + (-6 * (ts / BEAT - 12.8) - 36 * q).toFixed(1) + 'px)';
  };
  // v17.2 copy: 「但，」 / 「人与 Agent 的交互本身，」 / 「也需要被重新定义」. 「但，」 lands alone first, the way 1e's 「So，」
  // does (K.big: soft and large, settled within .4 beats), and the dots flinch with it (r × .9); line 2 rises at b13.4 as
  // the arc lands; the orange highlighter under 「交互本身」 is driven by the correction bubbles (each one moves it a tenth
  // further, so it speeds up as they crowd in, b13.85 → b17.3); line 3: 「也需要被」 rises (b15.1), then 「重新定义」
  // (orange) drops in last through the line's mask and settles (scale 1.06 → 1, no flash), landing (b16.5) among the
  // last bubbles and readable 3.6 beats before the exit (b20.1); line 2 reads 5.5 beats, 「但，」 6.9
  // v17.5 word-by-word rhythm: every phrase steps in where it will stand — it opens fast (d beats, E.out) out of a
  // 6 px blur and 24 px low, lands at s0× and settles to 1 by d + .16, then sits still (the lines' 6 px/beat drift goes
  // on) until the next phrase: [beat in the line, d, s0] per .w
  const step = (W, o = {}) => (el, tl, life) => {
    el.querySelectorAll('.w').forEach((w, i) => {
      if (!W[i]) return;                                                                    // null: another form owns it
      const [a, d, s0] = W[i], u = (tl - BB(a)) / BEAT, p = E.out(clamp(u / d)), z = E.out(clamp(u / (d + .16)));
      w.style.opacity = Math.min(1, p * 1.5).toFixed(3);
      w.style.filter = p < .999 ? 'blur(' + ((1 - p) * 6).toFixed(1) + 'px)' : 'none';
      w.style.transform = z < .999 ? 'translateY(' + ((1 - p) * (o.dy ?? 24)).toFixed(1) + 'px) scale(' + lerp(s0, 1, z).toFixed(4) + ')' : '';
      w.style.transformOrigin = '50% 58%';
    });
    leave(el, exitQ(tl, life, o.out ?? .6), true);
  };
  // v18.5: 「但，」 comes in at b12.35 (film 19.25), under the title's exit: it blurs in (K.blurIn) 40 px above the dot
  // row (y ≈ 490) and rises to its slot (y 150) in .5 beat (E.out), so the pivot word is launched by the dots; whole at
  // b12.85, it holds alone ≈ .3 beat before 「人与 Agent 的」 (b13.15). The dots flinch as it leaves them (r × .9)
  const RISE = 340;
  const cjRise = (el, tl) => el.querySelectorAll('.w').forEach((w) => {
    // v18.5 QA: hold at the dot row while the blur clears (≈ .1 beat), then rise — a .5-beat E.out from tl 0 had moved
    // half way up before the word was visible, so it read as appearing at the top, not leaving the dots
    const p = E.out(clamp((tl - BB(.08)) / BB(.42)));
    w.style.transform = p < .999 ? 'translateY(' + ((1 - p) * RISE).toFixed(1) + 'px)' : '';
  });
  txt(12.35, 20.7, [['sv rd-cj', '<span class="w">但，</span>']], { x: 960, y: 150, align: 'c' },
    { anim: K.all(K.blurIn({ spread: .05, dur: .2, out: .6, spread2: true }), cjRise), tick: drift(true) });
  // v18.6 R2: no flinch — the round dots blink once as 「但，」 leaves them and the input box grows out of them (b12.38)
  AGD.blink('all', 12.38, { stag: .03 });
  const markBy = (el, b) => {
    const p = BUB.reduce((s, u) => s + E.inOut(clamp((b - u.b0 + .25) / .4)), 0) / BUB.length;
    el.querySelectorAll('.mk').forEach((m) => { m.style.backgroundSize = (p * 100).toFixed(1) + '% .26em'; });
  };
  // v17.5: 「人与 Agent 的」 b13.4 → 「交互本身，」 b13.85 (whole by b14.1, was 14.6)
  // v18.5: 「人与 Agent 的」 b13.4 → 13.15 (.3 beat after 「但，」 is whole); 「交互本身，」 stays at b13.85
  txt(13.15, 20.7, [['hv sv rd-h', '<span class="w">人与 Agent 的</span><span class="w"><span class="mk rd-mk">交互本身</span>，</span>']], { x: 960, y: 255, align: 'c' },
    { anim: step([[0, .24, 1.07], [.7, .26, 1.08]]), tick: (el, tl, life, ts) => { drift(true)(el, tl, life, ts); markBy(el, ts / BEAT); } });
  // v17.5: both halves are quick steps with the same settle — 「也需要被」 rises (E.out .26, b15.1), 「重新定义」 drops in
  // half a beat later (.3, lands b15.9) and comes to rest from 1.1× (the punchline lands firmer)
  const fall = (o) => (el, tl, life) => {
    const [a, w] = el.querySelectorAll('.w'), q = exitQ(tl, life, o.out);
    const p0 = E.out(clamp(tl / BB(o.inB))), p1 = E.out(clamp((tl - BB(o.at)) / BB(o.dur)));
    const z0 = E.out(clamp(tl / BB(o.inB + .16))), z1 = E.out(clamp((tl - BB(o.at)) / BB(o.dur + .2)));
    a.style.transform = 'translateY(' + ((1 - p0) * 130 - (1 - q) * 30).toFixed(2) + '%) scale(' + lerp(1.06, 1, z0).toFixed(4) + ')';
    a.style.filter = p0 < .999 ? 'blur(' + ((1 - p0) * 5).toFixed(1) + 'px)' : 'none';
    a.style.opacity = Math.min(1, p0 * 1.4).toFixed(3);
    w.style.transform = 'translateY(' + (-(1 - p1) * 110 - (1 - q) * 30).toFixed(2) + '%) scale(' + lerp(1.1, 1, z1).toFixed(4) + ')';
    w.style.transformOrigin = '50% 58%';
    w.style.opacity = Math.min(1, p1 * 1.6).toFixed(3);
    leave(el, q, true);
  };
  txt(15.1, 20.7, [['hv sv rd-h', '<span class="w">也需要被</span><span class="w">重新定义</span>']], { x: 960, y: 395, align: 'c' },
    { anim: fall({ inB: .26, at: .5, dur: .3, out: .6 }), tick: drift() });

  /* ---------- 1d 输入框 + 纠正气泡 ---------- */
  // v17.7: typed one character at a time (10-intro's typeOn: .22–.28 beat a key, hash01 jitter, the caret solid while
  // it types), each line whole ≈ .2–.25 beat before its send (same send beats as before): 请你修改 b12.95–13.75 (sent
  // 13.95) · fix 14.55–15.02 (15.26) · 请你继续 15.8–16.54 (16.78); the box is never idle: the 4th one is typed but
  // never sent (17.15–17.93, readable 2.17 beats, the box sinks with it at b20.1)
  // the box grows out of the dots' centroid ((960, ≈570) at b12.6, the arc still landing) down to (960, 880) by b13.2,
  // and shrinks back into it over b20.1–20.5
  const c = AGD.chat(12.5, 20.5, { x: 960, y: 880, w: 980, from: AGD.centroid, to: AGD.centroid });
  // v17.7: [dot that becomes the caret, first key, text, seed, send beat | null (the 4th is never sent: cp keeps the caret
  // until the box retracts)]; the box caret takes that Agent's colour while its line shows
  const TY = [[1, 12.95, '请你修改', 41, 13.95], [2, 14.55, 'fix', 42, 15.26], [1, 15.8, '请你继续', 43, 16.78], [4, 17.15, '看清需求', 44, null]]
    .map(([i, k0, text, seed, send]) => { const K = typeOn(c, k0, text, seed); c.types[c.types.length - 1].ci = i; return { i, K, send }; });
  // v18.7 D4 QA: each typing dot rides the box caret (AGD.caretRide, below) from its first key to .05 after its send; its
  // bubbles stay where they hang on the arc meanwhile: HOME is the dot's arc slot (its position just before / after the
  // ride, interpolated), off() the shift that holds a bubble there while the dot is in the box
  const RIDE = TY.map((w) => ({ i: w.i, b0: w.K[0], b1: (w.send != null ? w.send - .2 : 19.85) + .25 }));
  const HOME = (i, b) => {
    const z = RIDE.find((r) => r.i === i && b >= r.b0 - .01 && b < r.b1 + .01); if (!z) return AGD.pos(i, b);
    const p = AGD.pos(i, z.b0 - .02), q = AGD.pos(i, z.b1 + .02), u = clamp((b - z.b0) / (z.b1 - z.b0));
    return { x: lerp(p.x, q.x, u), y: lerp(p.y, q.y, u) };
  };
  const off = (i, b) => { if (!RIDE.some((r) => r.i === i && b >= r.b0 - .01 && b < r.b1 + .01)) return { x: 0, y: 0 }; const p = AGD.pos(i, b), h = HOME(i, b); return { x: h.x - p.x, y: h.y - p.y }; };
  // every correction bubble: [dot, b0, text, send beat | null]; sent ones pop at send + .15 (AGD.chat). Ten bubbles, two
  // per dot, gaps shrinking from .55 to .19 beats (v17.4: the v17.3 stream from b14.1 slowed × 1.3 more, so every one
  // can be read). T5 layers: cx / ds (UP) hang above their dots, a newer one replacing the older (AGD's replace; while
  // the new one pops over PIN the old one shrinks back into the dot), so each of them holds its pair as far apart as the
  // stream allows (14.1 / 16.93 and 14.55 / 17.12: the older one readable 2.33 / 2.07 beats); cc / gm / cp hang below,
  // the newer one pushing the older down 64px (replace: false), at most 2 stacked
  const BUB = [
    [1, 14.1, '请你修改', 13.95], [3, 14.55, '不对，重来'], [4, 15.08, '说中文'], [2, 15.41, 'fix', 15.26],
    [0, 15.96, '别动这个文件'], [4, 16.25, '再改一版'], [0, 16.5, '还是报错'], [2, 16.73, 'fix again'],
    [1, 16.93, '请你继续', 16.78], [3, 17.12, '继续']
  ].map(([i, b0, text, send], k) => ({ i, b0, text, send, k }));
  // T5 tail anchors (dot x + dx, the box centre is dot x + 2·dx, see agBubbles): above cx 812 / ds 1108 (dy −r − 18,
  // boxes y ≈ 446–506 under line 3, bottom 420); below cc 690 / gm 960 / cp 1230 (dy r + 18, boxes from y ≈ 620, two
  // stacked reach ≈ 770, above the input box's top edge 836)
  const UP = [false, true, false, true, false], DX = [-54, -40, 0, 40, 54], R = AGD.P.arcD.r;
  // each bubble pops over PIN beats, stays ≥ 2.06 beats fully readable (2.3 for a natural life, enough for
  // 「别动这个文件」), shrinks over POUT beats; a natural life of LIFE beats turns it into a rolling stream (b17.9–19.9,
  // oldest first, so something is always moving while the stream is read); whatever would outlive R0 + POUT shrinks back
  // newest → oldest from R0 (T5: b19.7–20.1), RS apart, the last one gone before H4 sets off (b20.3)
  const PIN = .5, POUT = .35, LIFE = 3.15, R0 = 19.7, RS = .05;
  for (const u of BUB) {
    const same = BUB.filter((v) => v.i === u.i && v.b0 > u.b0);
    u.b1 = u.b0 + LIFE;
    if (same[1]) u.b1 = Math.min(u.b1, same[1].b0 + .3);                                     // a 3rd one: the oldest goes
  }
  // v18.1: at most 6 bubbles up at once — as a new one pops, the oldest still up starts shrinking back into its dot
  // (arrivals unchanged; cx / ds bubbles already replaced on their dot do not count)
  const shown = (v, b) => b >= v.b0 && b < v.b1 - POUT && !(UP[v.i] && BUB.some((w) => w.i === v.i && w.b0 > v.b0 && b >= w.b0));
  for (const u of BUB) {
    const on = BUB.filter((v) => v !== u && shown(v, u.b0));
    if (on.length >= 6) { const old = on.sort((p, q) => p.b0 - q.b0)[0]; old.b1 = u.b0 + POUT; }
  }
  BUB.filter((u) => u.b1 >= R0 + POUT - 1e-6).sort((a, b) => b.b0 - a.b0).forEach((u, k) => { u.b1 = R0 + RS * k + POUT; });
  const slow = [];                                                                           // [AGD_BUB record, b0, b1]
  for (const u of BUB) {
    let o;
    // v18.3: a box above its dot is ≈ 77 px from tail tip to top, so its top is clamped to y ≥ 460 (clear of line 3)
    if (UP[u.i]) o = { kind: 'fix', dx: (b) => DX[u.i] + off(u.i, b).x, dy: (b) => Math.max(-R - 18, 460 + 77 - HOME(u.i, b).y) + off(u.i, b).y, until: u.b1 };
    else {
      // newer ones push it down, starting .15 beats before they pop so the old box has cleared the dot by the time the
      // new one is full size
      const push = BUB.filter((v) => v.i === u.i && v.b0 > u.b0 && v.b0 < u.b1 - POUT);
      const dy = (b) => R + 18 + 64 * push.reduce((s, v) => s + E.inOut(clamp((b - v.b0 + .15) / .45)), 0) + off(u.i, b).y;
      o = { kind: 'fix', dx: (b) => DX[u.i] + off(u.i, b).x, dy, until: u.b1, replace: false };
    }
    if (u.send != null) c.send(u.send, u.i, o); else AGD.bubble(u.i, u.b0, u.b1, u.text, o);
    const r = AGD_BUB[AGD_BUB.length - 1]; slow.push([r, r.b0, r.b1]);
  }
  // AGD pops a bubble in .25 beats and shrinks it in .2 (agBubbles reads u.b0 / u.b1 every frame). This drive runs
  // before applyAgents and re-times this scene's records so the pop takes PIN beats and the shrink POUT beats, starting
  // at b0 and ending at b1 as registered (pure function of b, so seeking / --only renders get the same frame)
  every(13.0, 20.7, (p, b) => {
    for (const [r, B0, B1] of slow) {
      r.b0 = b < B0 ? B0 : b < B0 + PIN ? b - (b - B0) * .25 / PIN : B0 + PIN - .25;
      r.b1 = b < B1 - POUT ? B1 - POUT + .2 : b < B1 ? b + .2 - .2 * (b - B1 + POUT) / POUT : B1;
    }
  });

  /* ---------- v17.7 Agent 点形态（STORYBOARD「v17.7」F3 1c 末条 / 1d / 1e） ---------- */
  // v18.6 R2「圆形 + 闪烁」: through 1d the dots stay round Agent badges — no pill pulls, no comet head, no bubble tails,
  // no velocity stretch. One state per dot: the typing caret (R3, kept) > the round dot. Every bubble pops from its dot
  // with a blink; as all of them are corrections (kind 'fix'), the blink is warm — the rim warms and thickens for
  // ≈ .5 beat (sine), no tail, no flinch
  const bump = (b, t, len) => { const u = (b - t) / len; return u > 0 && u < 1 ? Math.sin(Math.PI * u) : 0; };
  const plate = (b, t0, t1, ramp) => Math.min(E.inOut(clamp((b - t0) / ramp)), E.inOut(clamp((t1 - b) / ramp)));
  const POP = (u) => (u.send != null ? u.send + .15 : u.b0);
  const wb = (i) => (b) => BUB.filter((u) => u.i === i).reduce((v, u) => Math.max(v, bump(b, POP(u) - .05, .5)), 0);
  const REST = (i) => ({ warm: (b) => wb(i)(b), ring: (b) => 1 + .5 * wb(i)(b), vs: 0 });
  for (const u of BUB) AGD.blink(u.i, POP(u), { v: .7 });
  const WIN = TY.map((w) => ({ i: w.i, t0: w.K[0] - .2, t1: w.send != null ? w.send - .2 : 19.85, w }));
  for (const w of WIN) {
    AGD.morph(w.t0, w.i, 'caret', { rot: 0, hpx: (b) => 38 * (1 + .04 * AGD.beatPulse(b, w.w.K)), dur: .25 });
    AGD.morph(w.t1, w.i, 'dot', { ...REST(w.i), dur: .3 });                                   // the caret rounds back
    // v18.7 D4 QA: as in 10-intro, the caret IS the box's caret (it used to stand as a logo-less bar in its arc slot
    // beside the box's own caret); it lifts after the last key (t1 + .25) and rounds back into its badge in flight
    AGD.caretRide(w.i, w.w.K[0], w.t1 + .25, c, { dx: 2 });                    // = RIDE
  }
  // 「重新定义」 lands (b15.9): the arc's low ends (cc / cp) blink (was a press of their height)
  AGD.blink([0, 4], 15.9, { k: 1.08 });
  // b18.7 hand-off (F3 1c): 1c's five-colour caret falls over — every segment turns 90° (.24 beat) as the arc opens —
  // then its segments round back into the round dots (.5 beat, E.out, the logos return; v18.6: no pill phase); the box
  // grows out of them with a blink (b12.38, above)
  AGD.morph(11.8, 'all', 'caret', { hpx: 24, rot: 90, dur: .24, stag: .03 });
  for (let i = 0; i < 5; i++) AGD.morph(12.04 + .03 * i, i, 'dot', { ...REST(i), dur: .5, ease: E.out });
  // the box shrinks back into the dots (b20.1–20.5): they blink as it lands
  AGD.blink('all', 20.42, { stag: .03 });
  AGD.noStretch(11.8, 27.4);
  // the highlighter (「交互本身」, from b13.85): ds (v18.6: round, no comet head; it blinks as it reaches the band) rises from the arc onto the band under 「交互本身」
  // (b13.72–14.0, as 「交互本身」 steps in), rides the tip of the stroke as it starts to draw (x 1010 + 402·progress, the line's 6 px/beat drift) and
  // drops back onto the arc by b14.5, before its own bubble (b14.55). v18.1: was a 24 / 18 px nudge ≈ 300 px below the band
  const hm = (b) => E.inOut(clamp((b - 13.72) / .28)) * (1 - E.inOut(clamp((b - 14.2) / .3)));
  const tipX = (b) => 1010 + 402 * BUB.reduce((s, u) => s + E.inOut(clamp((b - u.b0 + .25) / .4)), 0) / BUB.length;
  AGD.follow(13.5, 14.6, (i, b, q) => {
    if (i !== 3) return null;
    const h = hm(b), tx = tipX(b) - 10, ty = 328 - 6 * (b - 12.8);                         // just under the band, nose at the tip
    return { x: lerp(q.x, tx, h), y: lerp(q.y, ty, h) };
  }, { blend: .05 });
  AGD.blink(3, 13.95, { v: .6 });
  // 1e: on the way out to the ring each dot becomes a bead (ls .85) threaded on the dashed circle; 「everyone」 lands
  // (b23.0) with a beat of glow
  AGD.morph(20.4, 'all', 'bead', { ls: .85, dur: .8, stag: .05, glow: (b) => .5 * plate(b, CUT[2] + .3, CUT[2] + 1.3, .3) });

  /* ---------- 1e 虚线圆（#agdBack，跟着 cc 的半径，b26.8–27.4 淡出） ---------- */
  // 1e → 2 hand-off: while the three lines spread out (b25.8–26.4) the circle brightens .24 → .32 (v17.7: was .14, too faint to see it drawn out of the beads), so in b26.4–26.9,
  // before the spiral shows, the screen is the ring tightening with the dots (R 420 → 300), not five loose dots; the
  // spiral's tail then starts on this very circle (R 300) as it fades (20-orbit's b21.6 / b22.4, pushed 4.4 by SHIFT)
  // v17.7: the circle is drawn out of the five beads — from each bead's bearing both ways (36° each, b22.1–22.9), so
  // it closes halfway between them; the arcs ride with the beads (their bearings each frame) and their radius
  AGD.back(21.0, 27.4, (b) => {
    // v18.1: drawn out of the beads as they land (b21.0–21.7, each arc at its own bead's radius until they agree), fully
    // closed by b21.7 (before the first hard cut), .32 → .4 so it reads as a line, not a haze
    const a = E.inOut(clamp((b - 21.0) / .3)) * (1 - E.inOut(clamp((b - 26.8) / .6))) * (.32 + .08 * E.inOut(clamp((b - 25.8) / .7)));
    const s = 36.4 * E.out(clamp((b - 21.0) / .7));
    if (a <= .002 || s < .2) return '';
    let d = '';
    for (let i = 0; i < 5; i++) {
      const q = AGD.pos(i, b), R = Math.hypot(q.x - 960, q.y - 540), g = Math.atan2(q.x - 960, -(q.y - 540)) * 180 / Math.PI;
      if (R < 1) continue;
      const P = (h) => (960 + R * Math.sin(h * Math.PI / 180)).toFixed(1) + ' ' + (540 - R * Math.cos(h * Math.PI / 180)).toFixed(1);
      d += 'M' + P(g) + 'A' + R.toFixed(1) + ' ' + R.toFixed(1) + ' 0 0 1 ' + P(g + s) + 'M' + P(g) + 'A' + R.toFixed(1) + ' ' + R.toFixed(1) + ' 0 0 0 ' + P(g - s);
    }
    return '<path d="' + d + '" fill="none" stroke="#fff" stroke-opacity="' + a.toFixed(3) +
      '" stroke-width="2" stroke-linecap="round" stroke-dasharray="3 6"/>';
  });

  /* ---------- 1e 环内一行小字 + 三行大字（fit，b25.8–26.4 字距拉开退场） ---------- */
  // v17.2 copy: 「So，我们做了一个 Assistant」 / 「Redesign」 / 「Agent Workflow」 / 「for everyone」. The small line comes
  // first (「So，」 lands soft and large like 1d's 「但，」, the rest follows from lower right), then the three big lines cut
  // in one per .4 beats from b21.9 and all stay until b25.8 (small line 3.7, Redesign 3.9, Agent Workflow 3.5, for
  // everyone 3.1 beats readable). From b21.3 everything pushes in together (scale 1 → 1.04 about the ring centre,
  // constant speed) so it never sits still under the turning ring; the fit widths keep every line's corners inside the
  // ring's inner edge (radius 380) at 1.04
  // v18.1: the push is PUSH (v18.2: b22.5–25.7, E.sine, the ring scales with it), so before the first cut the type sits still
  // v18.3: the exit (b25.8–26.4, as the ring starts to close) is a push-through — the type goes on from 1.04 to 1.10
  // about the ring centre with the same E.inOut as its fade, so it passes the camera instead of blurring in place
  const XP = (b) => lerp(1, 1.10 / 1.04, E.inOut(clamp((b - 25.8) / .6)));
  const zoom = (y, own) => (el, tl, life, ts) => {
    const s = PUSH(ts / BEAT) * XP(ts / BEAT), add = ' translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')';
    el.style.transform = (own ? 'translate(-50%,-50%)' : el.style.transform) + add;     // K.words rewrites it every frame, K.big never
  };
  // v18.1: 「So，」 comes in at b20.6 at the ring centre (soft and large, as the 1d lines leave and the box shrinks into
  // the dots there), so the ring is never empty; at b20.95–21.35 it rises to its slot at the head of the line and the
  // rest of the line follows it in (「我们做了一个」 21.45, 「Assistant」 21.65)
  // v18.2: the rise is one .6-beat E.inOut (b20.9–21.5) on scale and translate together (was .4 beat, ≈ 4 frames at
  // its middle, read as a jump); 「我们做了一个」 wipes in only as 「So，」 arrives (b21.45), 「Assistant」 (white) at b21.62
  // v18.5: 52 px / 600 with a 60 px 「Assistant」, 10 px lower (y 352 → 362) so its ends clear the ring's inner edge
  const SO_Y = 362;
  const soRise = (el, tl) => {
    const w = el.querySelector('.w'), u = tl / BEAT, p = E.out(clamp(u / .3)), m = E.inOut(clamp((u - .3) / .6));
    const dx = el.offsetWidth / 2 - (w.offsetLeft + w.offsetWidth / 2), dy = 540 - SO_Y;
    w.style.transform = 'translate(' + (dx * (1 - m)).toFixed(1) + 'px,' + (dy * (1 - m)).toFixed(1) + 'px) scale(' + (lerp(1.9, 1, p) * lerp(2.2, 1, m)).toFixed(4) + ')';
    w.style.transformOrigin = '50% 60%';
    w.style.filter = p < .999 ? 'blur(' + ((1 - p) * 14).toFixed(1) + 'px)' : 'none';
    w.style.opacity = Math.min(1, p * 2).toFixed(3);
  };
  // v18.2 QA: 「Assistant」 lands from 1.04× (was 1.1×: at 48 px its centre-origin scale ate the space after 「一个」 for ≈ .1 beat)
  txt(20.6, 26.4, [['sv rd-s1', '<span class="w">So，</span><span class="w">我们做了一个</span><span class="w rd-w">Assistant</span>']],
    { x: 960, y: SO_Y, align: 'c' }, { anim: K.all(soRise, step([null, [.85, .24, 1.07], [1.02, .22, 1.04]], { dy: 18 })), tick: zoom(SO_Y, true) });
  // v17.5: each big line still cuts in hard (K.words), then settles from 1.06× (.32 beat) before the next one
  // v17.7: and it comes in 12 px from the side of the bead nearest it (the ring's bearings at its cut, landed), as if
  // that bead set it down inside the ring
  const fromBead = (b, y) => {
    let best = null;
    for (let i = 0; i < 5; i++) {
      const g = (207 + JUMP(b + .2) + 72 * i + 9 / 5.7 * (b - 20.3)) * Math.PI / 180, x = 960 + 420 * Math.sin(g), yy = 540 - 420 * Math.cos(g);
      const d = Math.hypot(x - 960, yy - y); if (!best || d < best.d) best = { d, ux: (x - 960) / d, uy: (yy - y) / d };
    }
    return best;
  };
  const settle = (u) => (el, tl) => el.querySelectorAll('.w').forEach((w) => {
    const z = E.out(clamp(tl / BB(.32))), n = 12 * (1 - z);
    w.style.transform = z < .999 ? 'translate(' + (u.ux * n).toFixed(2) + 'px,' + (u.uy * n).toFixed(2) + 'px) scale(' + lerp(1.06, 1, z).toFixed(4) + ')' : '';
    w.style.filter = z < .5 ? 'blur(' + ((1 - z * 2) * 3).toFixed(1) + 'px)' : 'none';
  });
  // [beat, y, html, fit]
  for (const [b, y, h, fit] of [[CUT[0], 460, 'Redesign', 740], [CUT[1], 568, 'Agent Workflow', 740], [CUT[2], 676, 'for <b class="rd-or">everyone</b>', 740]]) {
    txt(b, 26.4, [['xl sv rd-xl', '<span class="w">' + h + '</span>']], { x: 960, y, align: 'c' },
      { anim: K.all(K.words({ at: [0], fit, out: .6, spread: true }), settle(fromBead(b, y))), tick: zoom(y) });
  }
});
