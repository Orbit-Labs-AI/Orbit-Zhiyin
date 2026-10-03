/* 40-recs 4（b39.4–55.6） — STORYBOARD.md v17「4 优化建议」, hand-offs H11 (in) / H12 (out).
   Left: the five AGD dots in one column (x 220, cp 260 / cc 400 / ds 540 / cx 680 / gm 820). Middle: six real recommendation
   cards of deck 0 (Advance, light) in one column that scrolls up evenly; entry n (big type word + card) reaches the centre
   line at b42 + 2n, links to 2–3 Agent dots (solid = the app's recAgents, dashed = a filled-in neighbour) and adds its
   share to one of the two counters on the right (recTotal of the rows that arrived, time / token alternating). The last
   entry holds b52.4–54.2, then the column scrolls out. Numbers are read from recPct / recTotal at run time. */
scene('40-recs', () => {
  css(`
.ln.xl.r4-w{font-size:128px;line-height:1}
.ln.r4-n{font-size:96px;font-weight:700;line-height:1;color:var(--acc);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.ln.lt.r4-s{font-size:28px;color:rgba(255,255,255,.55)}
`);
  const IDS = ['retry-breaker', 'remove-figma', 'acceptance', 'pr-wrapup', 'headless', 'think-medium'];
  const WORD = ['Hook', 'MCP', 'Prompt', 'Skill', 'Workflow', 'Thinking'];
  const FLD = ['t', 'k', 't', 'k', 't', 'k'];                    // which counter each entry adds to
  const ARR = IDS.map((_, n) => 42 + 2 * n);                     // beat entry n reaches the centre line
  const GAP = 490, CX = 540, CY = 540, CW = 820;                 // entry pitch (screen px), card left / centre line, card width
  const ORD = [1, 3, 4, 2, 0];                                   // dot i → row (= order 'y' from the compass, H11)
  const ROWDOT = [4, 0, 3, 1, 2];                                // row → dot
  const sel = (id) => '.rcard[data-id="' + id + '"]';
  const card = (D, id) => D.querySelector(sel(id));

  /* ---------- H11: the dots leave the compass rim and stand in one column ---------- */
  AGD.key(39.4, 'column', { x: 220, y0: 260, gap: 140, r: 36, order: ORD, dur: 1.6, stag: .1, arc: 30 });

  /* ---------- app data (read once; nothing hard-coded) ---------- */
  const W = decks[0].W;
  let PCT = IDS.map(() => null), AGS = IDS.map(() => [0]), TOT = { t: [], k: [] };
  try {
    PCT = IDS.map((id) => W.eval('recPct(' + JSON.stringify(id) + ')'));
    AGS = IDS.map((id) => W.eval('recAgents(RECI[' + JSON.stringify(id) + '])').map((a) => AGID.indexOf(a)).filter((i) => i >= 0));
    // each counter: recTotal of its own rows that have arrived (alternatives on one problem take the best, then add)
    for (const f of ['t', 'k']) {
      const mine = IDS.filter((_, n) => FLD[n] === f);
      TOT[f] = mine.map((_, j) => +W.eval('(recTotal(' + JSON.stringify(mine.slice(0, j + 1)) + '.map((id) => RECI[id])) || {}).' + f) || 0);
    }
  } catch (e) { console.error('promo 40-recs: app data', e); }
  IDS.forEach((id, n) => { if (!PCT[n] || PCT[n][FLD[n]] == null) console.warn('promo 40-recs: no ' + FLD[n] + ' share for', id); });
  // per entry: the rise of its counter when it arrives
  const STEP = IDS.map((_, n) => { const f = FLD[n], j = IDS.slice(0, n).filter((__, m) => FLD[m] === f).length; return { f, d: (TOT[f][j] || 0) - (j ? TOT[f][j - 1] || 0 : 0) }; });

  /* ---------- which dots each entry links to ---------- */
  // solid = the Agents the app says the rec applies to (more than 3: hash01 picks 3); a single one gets a dashed neighbour
  // row (「可转换使用」); two entries in a row never link the same set
  const LINKS = [];
  let prevSet = '';
  IDS.forEach((id, n) => {
    let solid = AGS[n].length ? AGS[n].slice() : [0], dash = [];
    if (solid.length > 3) solid = solid.slice().sort((p, q) => hash01(n * 7 + p) - hash01(n * 7 + q)).slice(0, 3);
    if (solid.length === 1) {
      const r = ORD[solid[0]], nb = [r - 1, r + 1].filter((x) => x >= 0 && x <= 4).map((x) => ROWDOT[x]);
      if (hash01(n * 7 + solid[0]) >= .5) nb.reverse();
      const key = (d) => [...solid, d].sort().join();
      dash = [nb.find((d) => key(d) !== prevSet) ?? nb[0]];
    }
    prevSet = [...solid, ...dash].sort().join();
    LINKS.push({ solid, dash });
  });
  const LIVE = IDS.map((_, n) => [ARR[n] - .15, n < 5 ? ARR[n] + 1.3 : 54.5]);   // link window (retracts 1 beat after it leaves)
  const toCard = (id) => (b) => { const p = elXY(0, sel(id), 0, .5); return [p[0] - 4, p[1]]; };
  IDS.forEach((id, n) => {
    const [b0, b1] = LIVE[n], all = [...LINKS[n].solid.map((i) => [i, false]), ...LINKS[n].dash.map((i) => [i, true])];
    all.forEach(([i, dashed], k) => {
      AGD.link(b0 + k * .06, b1, i, toCard(id), { bend: .45, draw: .35, out: .3, pulse: 2, dash: dashed ? '3 6' : undefined });
      AGD.glow(i, ARR[n] - .1, b1 - .3, .9);
      AGD.pulse(i, ARR[n] - .05, 1.08, .5);
    });
  });
  // the dots that are linked light up, the rest sit at a .6
  const lit = (i, b) => {
    let v = 0;
    IDS.forEach((_, n) => {
      if (!LINKS[n].solid.includes(i) && !LINKS[n].dash.includes(i)) return;
      const [b0, b1] = LIVE[n];
      v = Math.max(v, Math.min(E.inOut(lp(b, b0, .3)), 1 - E.inOut(lp(b, b1 - .3, .3))));
    });
    return v;
  };
  AGD.follow(41.4, 55.0, (i, b) => ({ a: .6 + .4 * lit(i, b) }), { blend: .6 });

  /* ---------- deck 0: six cards in one column (b40.0 set-up, b40.6–55.4 on screen: the first card rises while the dots still fly, H11) ---------- */
  const advLight = (d) => { const Wd = decks[d].W; if (Wd.eval('S.ed') !== 'advance') Wd.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); Wd.setTheme('light'); };
  const still = (D) => D.getAnimations().forEach((a) => { const t = a.effect && a.effect.target; if (t && t.closest && t.closest('.recs')) a.cancel(); });
  const unscroll = (D) => { for (let e = D.querySelector('#content'); e; e = e.parentElement) { if (e.scrollTop) e.scrollTop = 0; if (e.scrollLeft) e.scrollLeft = 0; } };
  // the app lays the list out 820 px wide; a narrower card (WA app px) wraps into a taller, readable block at CW on screen
  const WA = 440, S0 = CW / WA;
  let CAM = null, X0 = 400, Y0 = 500;
  // a card's untransformed top-left (app px): its live rect minus the translate this scene put on it (survives re-renders
  // and the list's own scrolling, which solo() changes)
  const base = (el) => { const r = el.getBoundingClientRect(); return { x: r.left - (+el.dataset.r4x || 0), y: r.top - (+el.dataset.r4y || 0), h: r.height }; };
  const narrow = (el) => { if (el.style.width !== WA + 'px') { el.style.width = WA + 'px'; el.style.maxWidth = WA + 'px'; el.style.flex = 'none'; } };
  at(40.0, () => {
    advLight(0);
    const a = app(0), R = a.S.recs;
    R.aud = 2; R.lv = new Set([1, 2, 3, 4]); R.sel = 'ro-allow'; R.dim = 'all'; R.peek = null; R.tab = 'why';
    a.go('recs');
    const D = a.D; still(D); unscroll(D);
    IDS.forEach((id) => { const c = card(D, id); if (!c) console.warn('promo 40-recs: no card', id); });
    solo(0, IDS.map((id) => (DD) => card(DD, id))); unscroll(D);
    const cs = IDS.map((id) => card(D, id)).filter(Boolean), cont = D.querySelector('#content'), cr = cont ? cont.getBoundingClientRect() : { top: 0, height: 1000 };
    cs.forEach(narrow);
    if (cs.length) X0 = Math.min(...cs.map((c) => base(c).x));
    Y0 = cr.top + cr.height / 2;                                  // the column runs through the middle of #content (it clips)
    CAM = { x: X0, y: Y0, s: S0, ax: CX, ay: CY, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 };
    if (DEBUG) console.warn('promo 40-recs layout', JSON.stringify({ S0, X0, Y0, H: cs.map((c) => base(c).h) }));
  });
  tween(0, 40.6, 0, () => CAM || { x: 400, y: 500, s: 2, ax: CX, ay: CY, o: 1 }, E.lin);

  // scroll position u (entries): entry n's centre is at CY + GAP·(n − u). Even 245 px/beat; eases into the hold on the
  // last entry (b51 → 52.4), holds to b54.2, then accelerates up and out
  const herm = (s, p0, m0, p1) => { const s2 = s * s, s3 = s2 * s; return (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * m0 + (3 * s2 - 2 * s3) * p1; };
  const U = (b) => b < 51 ? (b - 42) / 2 : b < 52.4 ? herm((b - 51) / 1.4, 4.5, .7, 5) : b < 54.2 ? 5 : 5 + 2.2 * E.in(lp(b, 54.2, 1.4));
  const FOC = IDS.map(() => ({ a: 0, bl: 0 }));                  // per entry: opacity and blur, shared by its card and its word
  const MK = { t: 'rc', k: 'rk' };
  drive(0, 40.55, 55.4, (p, b, D) => {
    still(D); unscroll(D);
    const u = U(b), gIn = E.out(lp(b, 40.6, .9)), gOut = 1 - E.inOut(lp(b, 54.6, .8));
    IDS.forEach((id, n) => {
      const el = card(D, id); if (!el) return;
      narrow(el);
      const B = base(el), dy = GAP * (n - u), hs = B.h * S0, top = CY + dy - (hs - 152) / 2;   // entry = 128 px word + 24 px + card, centred on dy
      const appTop = Y0 + (top - CY) / S0, ad = Math.abs(dy), tx = X0 - B.x, ty = appTop - B.y;
      el.dataset.r4x = tx.toFixed(1); el.dataset.r4y = ty.toFixed(1);
      el.style.transform = 'translate(' + tx.toFixed(1) + 'px,' + ty.toFixed(1) + 'px)';
      const a = clamp(1 - .65 * ad / 400) * gIn * gOut, bl = 6 * ad / 400 + 6 * (1 - gOut);
      FOC[n] = { a, bl };
      el.style.opacity = a.toFixed(3);
      el.style.filter = bl > .05 ? 'blur(' + (bl / S0).toFixed(2) + 'px)' : 'none';
      // the card's own 省时 / token figure is swept by a marker as its share lands in the counter
      const f = FLD[n], fig = el.querySelector('.rc-save b[data-ck="' + MK[f] + ':' + id + '"]') || el.querySelector('.rc-save b:' + (f === 't' ? 'first-of-type' : 'last-of-type'));
      if (fig) {
        const w = E.inOut(lp(b, ARR[n], .5)) * 100;
        fig.style.backgroundImage = w > .1 ? 'linear-gradient(rgba(226,96,43,.34),rgba(226,96,43,.34))' : '';
        fig.style.backgroundRepeat = 'no-repeat'; fig.style.backgroundPosition = '0 88%'; fig.style.backgroundSize = w.toFixed(1) + '% .5em';
      }
    });
  });
  tween(0, 55.38, 0, { o: 0 }, E.lin);

  // the type word of each entry rides 24 px above its card's top-left corner, blurred and dimmed with it
  IDS.forEach((id, n) => {
    const b0 = Math.max(40.55, ARR[n] - 3.4), b1 = Math.min(55.4, n < 5 ? ARR[n] + 3.4 : 55.4);
    txt(b0, b1, [['xl sv r4-w', WORD[n]]], { x: CX, y: -400 }, {
      anim: (el) => {
        const F = FOC[n], p = elXY(0, sel(id), 0, 0);
        el.style.left = p[0].toFixed(1) + 'px'; el.style.top = (p[1] - 24).toFixed(1) + 'px';
        el.style.transform = 'translate(0,-100%)';
        el.style.opacity = F.a.toFixed(3);
        el.style.filter = F.bl > .05 ? 'blur(' + F.bl.toFixed(2) + 'px)' : 'none';
      }
    });
  });

  /* ---------- eyebrow and the two running totals ---------- */
  txt(40.2, 55.2, [['eb', '02 · 优化建议']], { x: 160, y: 100 }, { outB: .6 });
  const pct = (v) => v <= 0 ? '0.0%' : v < 10 ? v.toFixed(1) + '%' : Math.round(v) + '%';   // = fmtPct above .1 %; no「<0.1%」mid-roll
  const val = (f, b) => STEP.reduce((v, s, n) => v + (s.f === f ? s.d * E.out(lp(b, ARR[n], .8)) : 0), 0);
  const num = (f) => (el, tl, life, t) => { const n = el.querySelector('.r4-v'); if (n) n.textContent = pct(val(f, t / BEAT)); };
  txt(40.4, 55.4, [['eb', '协作时间']], { x: 1640, y: 390, align: 'c' }, { outB: .8 });
  txt(40.55, 55.4, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1640, y: 470, align: 'c' }, { outB: .8, tick: num('t') });
  txt(40.7, 55.4, [['eb', 'Token']], { x: 1640, y: 650, align: 'c' }, { outB: .8 });
  txt(40.85, 55.4, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1640, y: 730, align: 'c' }, { outB: .8, tick: num('k') });
  txt(41.0, 55.4, [['lt r4-s', '预计节省 · 按真实轨迹估算的占比']], { x: 1640, y: 880, align: 'c' }, { outB: .8 });
});
