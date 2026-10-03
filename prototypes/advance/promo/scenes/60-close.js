/* 7 收尾（b100.6–113, deck 2 + the mark）. STORYBOARD.md KF 7.1–7.4.
   Your compass (DIMV) turns in from the centre; the bezel, rose and needle fade while the aurora collapses into one
   ring (b102.8–104.4); the ring grows its inner turn (orbitAt from CLOSE.ring), rises into the icon and the end card
   writes itself under it; everything fades out by b113. */
scene('60-close', () => {
  END = 113;
  Object.assign(CLOSE, { ring: 104.2, rise: 106.0, settle: 108.4, sway: 102.4, out: 111.6, outDur: 1.4 });
  const C0 = 102.8, C1 = 104.4;                                    // the collapse
  // KF 7.1–7.2: the compass, needle settling with a small damped wobble; core and dial fade, the aurora pulls in
  drive(2, 100.7, 105.7, (p, b) => drawCompass({
    deg: 4 * Math.sin((b - 101) * 1.5) * Math.exp(-(b - 101) * .5), speed: 0, mine: 1, grow: 1 + .02 * Math.sin((b - 101) * 1.6),
    sweep: 1, orbit: 0, settle: 1, tip: 0, needle: 1,
    core: 1 - E.inOut(lp(b, C0, 1.0)), dial: 1 - E.inOut(lp(b, C0, 1.3)), collapse: E.inOut(lp(b, C0, C1 - C0))
  }));
  tween(2, 100.8, 2, () => framing(2, 'all', [960, 540, 900, 900]), E.quart, (T) => ({ s: T.s * .3, rz: -80, o: 0, bl: 6 }));
  // hand-over: the collapsed ring (radius 300 in compass units) and orbitAt's ring (R0 = 300 × the deck's zoom) sit on
  // the same circle; the mark grows its outer turn first (from its tail inwards), so the compass ring stays until that
  // turn is closed (≈ b105) and then fades under it
  tween(2, 104.6, .6, () => ({ o: 0 }), E.inOut);
  glowAt(101, .6, 2);
  glowAt(CLOSE.ring, .9, 2);
  // KF 7.4: end card under the risen mark (it settles at cy 410, R 215); all of it leaves with the mark b111.6–113
  const OUT = END - CLOSE.out;
  css(`
.ec-line{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.02em}
.ec-line b{color:var(--a1);font-weight:700}
.ec-by{font-family:var(--mono);font-size:26px;letter-spacing:.3em;color:rgba(255,255,255,.55)}
`);
  txt(107.6, END, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.2, outB: OUT });
  txt(108.6, END, [['ec-line', '认识你的协作方式，省下 <b>15.6% 的协作时间</b>']], { x: 960, y: 800, align: 'c' }, { anim: K.all(K.blurIn({ spread: .5, dur: .35, out: OUT })) });
  txt(109.6, END, [['ec-by', 'for macOS · ActionMesh AI']], { x: 960, y: 885, align: 'c' }, { inB: 1, outB: OUT });
  glowAt(CLOSE.out, 0, OUT);
});
