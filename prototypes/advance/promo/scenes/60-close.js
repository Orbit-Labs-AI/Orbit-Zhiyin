/* 7 收尾（b100.6–113, deck 2 + the mark）. STORYBOARD.md KF 7.1–7.4.
   Your compass (DIMV) turns in from the centre; the bezel, flower and badges fade while the band collapses into one
   ring (b102.8–104.4); the ring tips back into an orbit with the five Agent planets on it (b104.2–105.4), the spiral
   grows along it from its tail (orbitAt from CLOSE.grow), rises to the 45° icon view and the end card writes itself
   under the bare mark; everything fades out by b113. */
scene('60-close', () => {
  END = 113;
  Object.assign(CLOSE, { ring: 104.2, orbit: 104.2, grow: 105.0, rise: 106.6, settle: 108.4, out: 111.6, outDur: 1.4, tilt: 64 });
  const C0 = 102.8, C1 = 104.4;                                    // the collapse
  // KF 7.1–7.2: the compass, the flower settling on your type with a small damped wobble; core and dial fade, the band pulls in
  drive(2, 100.7, 105.7, (p, b) => drawCompass({
    deg: 11.25 + 4 * Math.sin((b - 101) * 1.5) * Math.exp(-(b - 101) * .5), mine: 1, grow: 1 + .02 * Math.sin((b - 101) * 1.6),
    sweep: 1, orbit: 0, spin: b - 60, settle: 1, needle: 1,   // the Agent layers keep circling, each at its own speed
    core: 1 - E.inOut(lp(b, C0, 1.0)), dial: 1 - E.inOut(lp(b, C0, 1.3)), collapse: E.inOut(lp(b, C0, C1 - C0))
  }));
  tween(2, 100.8, 2, () => framing(2, 'all', [960, 540, 900, 900]), E.quart, (T) => ({ s: T.s * .3, rz: -80, o: 0, bl: 6 }));
  // hand-over: the collapsed ring (radius 300 in compass units) tips back by CLOSE.tilt into an orbit; orbitAt's ring
  // (R0 = 300 × the deck's zoom, pitch 90° − tilt) lies on the same ellipse and grows its outer turn first, so the
  // compass ring stays until that turn is drawn and then fades under it
  tween(2, CLOSE.orbit, 1.2, () => ({ rx: CLOSE.tilt }), E.inOut);
  tween(2, 105.6, .8, () => ({ o: 0 }), E.inOut);
  glowAt(101, .6, 2);
  glowAt(CLOSE.ring, .9, 2);
  // KF 7.4: end card under the bare 45° mark (it settles at cy 410, R 215); all of it leaves with the mark b111.6–113
  const OUT = END - CLOSE.out;
  css(`
.ec-line{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.02em}
.ec-line b{color:var(--a1);font-weight:700}
.ec-by{font-family:var(--mono);font-size:26px;letter-spacing:.3em;color:rgba(255,255,255,.55)}
`);
  txt(108.6, END, [['ec-line', '认识你的协作方式，让 <b>Agent</b> 更懂你']], { x: 960, y: 720, align: 'c' }, { anim: K.all(K.blurIn({ spread: .5, dur: .35, out: OUT })) });
  txt(109.6, END, [['ec-by', 'for macOS · ActionMesh AI']], { x: 960, y: 800, align: 'c' }, { inB: 1, outB: OUT });
  glowAt(CLOSE.out, 0, OUT);
});
