/* 40-recs 4（b39.4–58.1） — STORYBOARD.md v17「4 优化建议」+ v17.1 T10 / T10′, hand-offs T10 (in) / T11 (out).
   v17.3: 3 beats longer than v17.2 (pitch 2.4 → 3.0, everything after b41.5 later; T11 at b58.0 instead of b55.0).
   Left: the five AGD dots in one short column (x 330, rows 372 … 708 in their compass-rim y order, r 30); when entry n
   comes up from below the dots it links to step forward to x 386, light up and emit the links; the type word wipes in
   left → right as the first link reaches the card (the entry comes out of its dots) and its share starts rolling into its
   counter, all while the card is still below the centre line. Middle: six real recommendation cards of deck 0 (Advance,
   light) in one column that scrolls up at one slow constant speed (163 px/beat, no holds); entry n (big type word + card)
   reaches the centre line at b41.5 + 3n, links to 2–3 Agent dots (solid = the app's recAgents, dashed = a filled-in
   neighbour) and adds its share to one of the two counters on the right (recTotal of the rows that arrived, time / token
   alternating). An entry is sharp from 250 px below to 300 px above the centre line (≈3.4 beats; two entries are sharp
   at once between arrivals, so one can be read to the end while the next comes in). The last entry passes the centre at
   b56.5 and the column keeps rising, easing faster from b57.0, out by b58.1. Dots and counters drift slowly so nothing
   sits frozen. Numbers are read from recPct / recTotal at run time. */
scene('40-recs', () => {
  css(`
.ln.xl.r4-w{font-size:128px;line-height:1}
.ln.r4-n{font-size:96px;font-weight:700;line-height:1;color:var(--acc);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.ln.lt.r4-s{font-size:28px;color:rgba(255,255,255,.55)}
`);
  const IDS = ['retry-breaker', 'remove-figma', 'acceptance', 'pr-wrapup', 'headless', 'think-medium'];
  const WORD = ['Hook', 'MCP', 'Prompt', 'Skill', 'Workflow', 'Thinking'];
  const FLD = ['t', 'k', 't', 'k', 't', 'k'];                    // which counter each entry adds to
  const PIT = 3.0, ARR = IDS.map((_, n) => 41.5 + PIT * n);      // beat entry n reaches the centre line (41.5 … 56.5)
  const GAP = 490, CX = 540, CY = 540, CW = 820;                 // entry pitch (screen px), card left / centre line, card width
  // dot i → row = its y rank on the compass rim at b39.4 (order 'y', H11). The 0.0.4 dial puts the badges at the data's
  // bearings (demo: cc 43 / cx 62 / gm 288 / ds 118 / cp 221° → rows cc cx gm ds cp), not at the v17 spots V2 assumed
  // ([1, 3, 4, 2, 0] sent cp from the bottom of the rim to the top row and gm down through ds / cp: the dots crossed and
  // bunched at b40.4). Same ranking as cpBadge (y = C − R·cos θ); the centre row (gm here) lands on (330, 540) for T11.
  const ORD = (() => {
    let pl = []; try { pl = compassData().sets.base.pl || []; } catch (e) { /* no compass data: index order */ }
    const y = [0, 1, 2, 3, 4].map((i) => -Math.cos((pl[i] ?? i * 72 + 18) * Math.PI / 180)), o = [];
    [0, 1, 2, 3, 4].sort((p, q) => y[p] - y[q]).forEach((d, r) => { o[d] = r; });
    return o;
  })();
  const ROWDOT = ORD.map((_, r) => ORD.indexOf(r));              // row → dot
  const sel = (id) => '.rcard[data-id="' + id + '"]';
  const card = (D, id) => D.querySelector(sel(id));

  /* ---------- T10: the dots leave the compass rim and close into one short column (ranked by their y on the compass,
     so no paths cross; the centre row lands on the centre line, where T11 merges the column) ---------- */
  const COLX = 330, STEP_X = 56;                                 // column x; a linked dot steps forward to 386
  AGD.key(39.4, 'column', { x: COLX, y0: 372, gap: 84, r: 30, order: ORD, dur: 1.6, stag: .08, arc: 20 });

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
  // link window: from 1.9 beats before entry n reaches the centre line (the card ≈310 px below it, coming into focus; the
  // first one at b40.6, as the dots land in the column) until the next entry's links start (the last until its exit)
  const LIVE = IDS.map((_, n) => [n ? ARR[n] - 1.9 : 40.6, n < 5 ? ARR[n] + 1.05 : 57.5]);
  // emission beat (b41, 43, 46, 49, 52, 55): the first link reaches the card, the type word wipes in, the dots pulse and
  // the entry's share starts rolling into its counter
  const EV = IDS.map((_, n) => LIVE[n][0] + .4);
  const toCard = (id) => (b) => { const p = elXY(0, sel(id), 0, .5); return [p[0] - 4, p[1]]; };
  IDS.forEach((id, n) => {
    const [b0, b1] = LIVE[n], all = [...LINKS[n].solid.map((i) => [i, false]), ...LINKS[n].dash.map((i) => [i, true])];
    all.forEach(([i, dashed], k) => {
      AGD.link(b0 + k * .1, b1, i, toCard(id), { bend: .45, draw: .55, out: .45, pulse: 2, dash: dashed ? '3 6' : undefined });
      AGD.glow(i, EV[n] - .2, b1 - .3, .9);
      AGD.pulse(i, EV[n] - .05, 1.08, .6);
    });
  });
  // T10′: from .3 beats before entry n reaches the centre line, the dots it links to step forward 330 → 386 (E.io .4) and
  // light up (a 1), the rest stay at 330 / a .6; they step back over the .4 beats before their links retract. The column
  // breathes (±4 / ±8 px, 7–9.5-beat periods) so no dot stands frozen; the follow blends out by b58.0, so the merge (T11)
  // starts from the exact column (the centre row at (330, 540))
  const near = (i, b, d) => {
    let v = 0;
    IDS.forEach((_, n) => {
      if (!LINKS[n].solid.includes(i) && !LINKS[n].dash.includes(i)) return;
      const [b0, b1] = LIVE[n];
      v = Math.max(v, Math.min(E.inOut(lp(b, b0, d)), 1 - E.inOut(lp(b, b1 - d, d))));
    });
    return v;
  };
  AGD.follow(40.9, 58.0, (i, b, q) => {
    const h = hash01(i, 11), px = 7 + 2.5 * hash01(i, 12), py = 7.5 + 2 * hash01(i, 13);
    return { a: .6 + .4 * near(i, b, .3), x: q.x + STEP_X * near(i, b, .4) + 4 * Math.sin(2 * Math.PI * (b / px + h)), y: q.y + 8 * Math.sin(2 * Math.PI * (b / py + h * 1.7)) };
  }, { blend: .4 });

  /* ---------- deck 0: six cards in one column (b40.0 set-up, b40.3–58.1 on screen: the first card rises while the dots still fly, H11;
     it starts fading in as the dial (gone b40.25) and the persona column (gone b40.2) leave, so the dots never fly over an empty frame) ---------- */
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
  tween(0, 40.3, 0, () => CAM || { x: 400, y: 500, s: 2, ax: CX, ay: CY, o: 1 }, E.lin);

  // scroll position u (entries): entry n's centre is at CY + GAP·(n − u). One constant 163 px/beat from b40.25 (no
  // stop-and-go, no hold); from b57.0 an E.in term adds .6 entry so the column eases faster up and out while it fades
  // (gone by b58.1: the trajectory card enters at b58.4, H12)
  const U = (b) => (b - ARR[0]) / PIT + .6 * E.in(lp(b, 57.0, 1.1));
  const FOC = IDS.map(() => ({ a: 0, bl: 0 }));                  // per entry: opacity and blur, shared by its card and its word
  const MK = { t: 'rc', k: 'rk' };
  drive(0, 40.25, 58.1, (p, b, D) => {
    still(D); unscroll(D);
    const u = U(b), gIn = E.out(lp(b, 40.3, .9)), gOut = 1 - E.inOut(lp(b, 57.4, .7));
    IDS.forEach((id, n) => {
      const el = card(D, id); if (!el) return;
      narrow(el);
      const B = base(el), dy = GAP * (n - u), hs = B.h * S0, top = CY + dy - (hs - 152) / 2;   // entry = 128 px word + 24 px + card, centred on dy
      const appTop = Y0 + (top - CY) / S0, ad = Math.abs(dy), tx = X0 - B.x, ty = appTop - B.y;
      el.dataset.r4x = tx.toFixed(1); el.dataset.r4y = ty.toFixed(1);
      el.style.transform = 'translate(' + tx.toFixed(1) + 'px,' + ty.toFixed(1) + 'px)';
      // sharp from 250 px below to 300 px above the centre line (≈3.4 beats at 163 px/beat; above −300 the word starts to
      // leave the frame), then dims and blurs 6 px per 360 px (≤1 px within 60 px more: ≈4.1 beats readable)
      const af = dy < 0 ? Math.max(0, ad - 300) : Math.max(0, ad - 250), a = clamp(1 - .65 * af / 360) * gIn * gOut, bl = 6 * af / 360 + 6 * (1 - gOut);
      FOC[n] = { a, bl };
      el.style.opacity = a.toFixed(3);
      el.style.filter = bl > .05 ? 'blur(' + (bl / S0).toFixed(2) + 'px)' : 'none';
      // the card's own 省时 / token figure is swept by a marker as its share lands in the counter
      const f = FLD[n], fig = el.querySelector('.rc-save b[data-ck="' + MK[f] + ':' + id + '"]') || el.querySelector('.rc-save b:' + (f === 't' ? 'first-of-type' : 'last-of-type'));
      if (fig) {
        const w = E.inOut(lp(b, EV[n] - .1, .9)) * 100;
        fig.style.backgroundImage = w > .1 ? 'linear-gradient(rgba(226,96,43,.34),rgba(226,96,43,.34))' : '';
        fig.style.backgroundRepeat = 'no-repeat'; fig.style.backgroundPosition = '0 88%'; fig.style.backgroundSize = w.toFixed(1) + '% .5em';
      }
    });
  });
  tween(0, 58.08, 0, { o: 0 }, E.lin);

  // the type word of each entry rides 24 px above its card's top-left corner, blurred and dimmed with it. It is not on
  // screen before its entry is emitted: it wipes in left → right (.35 beats, soft 15 % edge) from the moment the first link
  // reaches the card's left edge (link start + .4: the link is drawn to ≈98 %, the stepping dot has landed at 386)
  const WIPE = EV;
  IDS.forEach((id, n) => {
    const b0 = WIPE[n] - .05, b1 = Math.min(58.1, n < 5 ? ARR[n] + 3.5 : 58.1);
    txt(b0, b1, [['xl sv r4-w', WORD[n]]], { x: CX, y: -400 }, {
      anim: (el, tl, life, t) => {
        const F = FOC[n], p = elXY(0, sel(id), 0, 0), w = E.inOut(lp(t / BEAT, WIPE[n], .35));
        el.style.left = p[0].toFixed(1) + 'px'; el.style.top = (p[1] - 24).toFixed(1) + 'px';
        el.style.transform = 'translate(0,-100%)';
        el.style.opacity = F.a.toFixed(3);
        el.style.filter = F.bl > .05 ? 'blur(' + F.bl.toFixed(2) + 'px)' : 'none';
        const m = w >= 1 ? 'none' : 'linear-gradient(90deg,#000 ' + (115 * w - 15).toFixed(1) + '%,transparent ' + (115 * w).toFixed(1) + '%)';
        el.style.maskImage = m; el.style.webkitMaskImage = m;
      }
    });
  });

  /* ---------- eyebrow and the two running totals ---------- */
  txt(40.2, 58.1, [['eb', '02 · 优化建议']], { x: 160, y: 100 }, { outB: .6 });
  const pct = (v) => v <= 0 ? '0.0%' : v < 10 ? v.toFixed(1) + '%' : Math.round(v) + '%';   // = fmtPct above .1 %; no「<0.1%」mid-roll
  const val = (f, b) => STEP.reduce((v, s, n) => v + (s.f === f ? s.d * E.out(lp(b, EV[n] - .1, 1.2)) : 0), 0);   // 1.2-beat roll from the emission
  const num = (f) => (el, tl, life, t) => { const n = el.querySelector('.r4-v'); if (n) n.textContent = pct(val(f, t / BEAT)); };
  // the counter block drifts up 40 px over the scene (mask in / out unchanged), so it never stands frozen between rolls
  const drift = (outB) => { const m = mask(.18, 1, outB); return (el, tl, life, t) => { m(el, tl, life); el.style.transform = 'translate(-50%,-50%) translateY(' + (-40 * lp(t / BEAT, 40.4, 17.7)).toFixed(2) + 'px)'; }; };
  txt(40.4, 58.1, [['eb', '协作时间']], { x: 1640, y: 390, align: 'c' }, { anim: drift(.7) });
  txt(40.55, 58.1, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1640, y: 470, align: 'c' }, { anim: drift(.7), tick: num('t') });
  txt(40.7, 58.1, [['eb', 'Token']], { x: 1640, y: 650, align: 'c' }, { anim: drift(.7) });
  txt(40.85, 58.1, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1640, y: 730, align: 'c' }, { anim: drift(.7), tick: num('k') });
  txt(41.0, 58.1, [['lt r4-s', '预计节省 · 按真实轨迹估算的占比']], { x: 1640, y: 880, align: 'c' }, { anim: drift(.7) });
});
