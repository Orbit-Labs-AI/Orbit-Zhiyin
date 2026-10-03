/* 40-recs 4（b39.4–63.1） — STORYBOARD.md v17「4 优化建议」+ v17.1 T10 / T10′, hand-offs T10 (in) / T11 (out).
   v17.3: 3 beats longer than v17.2 (pitch 2.4 → 3.0, everything after b41.5 later; T11 at b58.0 instead of b55.0).
   v17.5: 5 beats longer (start unchanged; T11 at b63.0). Intro card first (+4.5): the badges peel off the persona dial
   row by row (b38.5–40.76, r176b) and, as each of the top three rows comes home, it writes one line out of a link at x 540
   (b39.85 / 39.99 / 40.13):「02 · 优化建议」/「根据你的使用习惯，智能推荐」(silver, heavy) /「提高效率」(orange); they
   stay, drifting up 12 px, while the column breathes in three soft pulse waves (b41.6 / 42.7 / 43.8); at b44.5 the three
   lines rise, then slide left and shrink together into the top-left eyebrow slot (eyebrow 160,100; the two lines below
   it at 26 px; 1.1 beats) as the first entry's dots step forward and emit it (b45.0); the counters come in behind the headline's tail.
   The last entry also gets .5 beat more before the column leaves (+.5 at the end).
   Left: the five AGD dots in one short column (x 330, rows 372 … 708 in their compass-rim y order, r 30); when entry n
   comes up from below the dots it links to step forward to x 386, light up and emit the links; the type word wipes in
   left → right as the first link reaches the card (the entry comes out of its dots) and its share starts rolling into its
   counter, all while the card is still below the centre line. Middle: six real recommendation cards of deck 0 (Advance,
   light) in one column that scrolls up at one slow constant speed (163 px/beat, no holds); entry n (big type word + card)
   reaches the centre line at b46.0 + 3n, links to 2–3 Agent dots (solid = the app's recAgents, dashed = a filled-in
   neighbour) and adds its share to one of the two counters on the right (recTotal of the rows that arrived, time / token
   alternating). An entry is sharp from 260 px below to 320 px above the centre line (≈3.6 beats; two entries are sharp
   at once between arrivals, so one can be read to the end while the next comes in). The last entry passes the centre at
   b61.0 and the column keeps rising, easing faster from b61.9, out by b63.1. Dots and counters drift slowly so nothing
   sits frozen. Numbers are read from recPct / recTotal at run time; an entry adds to its own measured share (time / token
   alternating where both exist; think-medium has none — the app says 未估算 — and adds nothing).
   v17.7 shapes (STORYBOARD F3 (4)): in the column the dots are bullets (rows 3–4 morph on landing b40.52 / 40.66); rows 0–2
   stretch into pills aimed at their intro line as their links start (b39.5 / 39.64 / 39.78) and land as bullets; the
   three waves are a pill breath (w 2 → 2.3); each linked dot is a pill aimed at its card from link start, then a bullet
   with a ✓ (thin for a dashed link) from emission + .4 (b45.4 / 47.9 / 50.9 / 53.9 / 56.9 / 59.9), held 1.4 beats; all
   back to round badges b62.3–62.96 so the merge (b63.0, 50-tools) closes them into the orb. Counter rolls enter left → right.
   v18.2: +.8 beat at the end (payoff held to b63.4, exit b63.4–64.0; round badges b62.8, close b63.2, merge b63.8). */
scene('40-recs', () => {
  css(`
.ln.xl.r4-w{font-size:128px;line-height:1}
.ln.r4-n{font-size:96px;font-weight:700;line-height:1;color:var(--acc);letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.ln.lt.r4-s{font-size:30px;color:rgba(255,255,255,.7)}
.ln.r4-l{font-size:36px;font-weight:600;color:rgba(255,255,255,.86);letter-spacing:.04em}
.ln.r4-h{font-size:88px;font-weight:700;letter-spacing:-.01em;line-height:1.08}
.ln.r4-a{font-size:64px;font-weight:600;letter-spacing:.02em;color:var(--a1)}
`);
  const IDS = ['retry-breaker', 'remove-figma', 'acceptance', 'pr-wrapup', 'headless', 'think-medium'];
  const WORD = ['Hook', 'MCP', 'Prompt', 'Skill', 'Workflow', 'Thinking'];
  const PREF = ['t', 'k', 't', 'k', 't', 'k'];                   // which counter each entry would add to (time / token alternating)
  const PIT = 3.0, ARR = IDS.map((_, n) => 46.0 + PIT * n);      // beat entry n reaches the centre line (46.0 … 61.0)
  const S4 = 44.5, MV = 1.1, OUT4 = 63.1;                        // intro → eyebrow slot move (b44.5–45.6); scene clear
  // v18.1 payoff (b61.7–62.35): the last card blurs out, the two counters glide to the centre at 1.5×, the orange line
  // 「提高效率」wipes in on their left and the caption settles under them — one large centred % statement (shares only, never
  // hours). v18.2: held .8 beat longer (whole statement readable b62.35–63.4, exit b63.4–64.0, film b86.3–86.9, before
  // 50-tools' trajectory card fades in at film b87.05); the dot merge and the hand-off move with it (+.8)
  const PO = 61.7, POD = .65, POX = .6, POUT = 64.0, PE = (b) => E.inOut(lp(b, PO, POD));
  // v18.1: the column is framed ≈1.35× closer than v17.7 (card body 12 app px → ≈30 px on screen, footer 11 → ≈27 px): the
  // cards are 1000 px wide at x 520 (right edge 1520, the counters sit right of it at 1720), the entry pitch follows the
  // tallest entry (set at b40.0, ≥ 490), so the 3-beat cadence is unchanged and only the scroll speed in px grows
  let GAP = 490; const CX = 520, CY = 540, CW = 1000;            // entry pitch (screen px), card left / centre line, card width
  const KG = () => GAP / 490;                                    // v17.7 pixel windows scale with the pitch
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
  // r176b: the badges peel off the still-revolving rim one row at a time (top row first, .14 beat apart, from b38.5 =
  // 30-persona CO − .9, .7 beat before the reveal block starts to leave) and glide 1.7 beats (E.inOut, bowing up ≤ 14 px)
  // into the column, growing r 18·s → 30. Each path starts from the badge's live rim position (cpBadge: the dial is
  // collapsing towards the column meanwhile, so the rows still on it close in with it) — the five stay one converging
  // group and no two paths cross (closest pair ≥ 20 px apart, edge to edge).
  // The key itself switches at once (dur ≈ 0); the live x / y0 / r carry the whole move.
  const PEEL = 38.5, PST = .14, PD = 1.7, PARC = 14;
  const peel = (b, i) => E.inOut(clamp((b - PEEL - PST * ORD[i]) / PD));
  const rim = (b, i, k) => { const e = peel(b, i); return e >= 1 ? null : cpBadge(i)[k]; };
  AGD.key(PEEL, 'column', {
    x: (b, i) => { const e = peel(b, i), q = rim(b, i, 'x'); return q == null ? COLX : lerp(q, COLX, e); },
    y0: (b, i) => { const e = peel(b, i), q = rim(b, i, 'y'), y = 372 + 84 * ORD[i]; return (q == null ? y : lerp(q, y, e)) - PARC * 4 * e * (1 - e); },
    gap: 0, r: (b, i) => { const e = peel(b, i), q = rim(b, i, 'r'); return q == null ? 30 : lerp(q, 30, e); },
    a: (b, i) => { const e = peel(b, i), q = rim(b, i, 'a'); return q == null ? 1 : lerp(q, 1, e); },
    order: ORD, dur: .001, stag: 0
  });
  const ROWIN = [0, 1, 2].map((r) => PEEL + PST * r + 1.05);    // row r's dot is ≈ 70 % home: it starts writing intro line r (links b39.55 / 39.69 / 39.83)
  // v17.7 F3 (4): in the column the dots are list bullets (rounded squares, ring 1.4, logo whole). Rows 3–4 turn into them
  // over the last .4 beat of their glide (b40.52 / 40.66); rows 0–2 get there through their intro pill (below)
  [3, 4].forEach((r) => AGD.morph(PEEL + PST * r + PD - .4, ROWDOT[r], 'bullet', { dur: .5 }));

  /* ---------- app data (read once; nothing hard-coded) ---------- */
  const W = decks[0].W;
  let PCT = IDS.map(() => null), AGS = IDS.map(() => [0]), TOT = { t: [], k: [] };
  const FLD = PREF.slice();
  try {
    PCT = IDS.map((id) => W.eval('recPct(' + JSON.stringify(id) + ')'));
    // the counter each entry really adds to: its preferred one if the app measured that share, else the other; none when
    // the app has no share at all (think-medium: reasoning tokens are not logged apart, the card itself says 未估算)
    PCT.forEach((p, n) => { const o = PREF[n] === 't' ? 'k' : 't'; FLD[n] = p && p[PREF[n]] != null ? PREF[n] : p && p[o] != null ? o : null; });
    AGS = IDS.map((id) => W.eval('recAgents(RECI[' + JSON.stringify(id) + '])').map((a) => AGID.indexOf(a)).filter((i) => i >= 0));
    // each counter: recTotal of its own rows that have arrived (alternatives on one problem take the best, then add)
    for (const f of ['t', 'k']) {
      const mine = IDS.filter((_, n) => FLD[n] === f);
      TOT[f] = mine.map((_, j) => +W.eval('(recTotal(' + JSON.stringify(mine.slice(0, j + 1)) + '.map((id) => RECI[id])) || {}).' + f) || 0);
    }
  } catch (e) { console.error('promo 40-recs: app data', e); }
  // per entry: the rise of its counter when it arrives (none for an entry without a share)
  const STEP = IDS.map((_, n) => { const f = FLD[n]; if (!f) return { f: null, d: 0 }; const j = IDS.slice(0, n).filter((__, m) => FLD[m] === f).length; return { f, d: (TOT[f][j] || 0) - (j ? TOT[f][j - 1] || 0 : 0) }; });

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
  // first one 1.4 beats before, b44.6, as the intro lines start moving up out of its way) until the next entry's links
  // start (the last until its exit)
  // v18.1: the last entry's links retract with its card (b61.9, card fading from b61.5) instead of pointing at the empty payoff frame
  const LIVE = IDS.map((_, n) => [ARR[n] - (n ? 1.9 : 1.4), n < 5 ? ARR[n] + 1.05 : 61.9]);
  // emission beat (b45.0, 47.5, 50.5, 53.5, 56.5, 59.5): the first link reaches the card, the type word wipes in, the dots
  // pulse and the entry's share starts rolling into its counter
  const EV = IDS.map((_, n) => LIVE[n][0] + .4);
  const toCard = (id) => (b) => { const p = elXY(0, sel(id), 0, .5); return [p[0] - 4, p[1]]; };
  IDS.forEach((id, n) => {
    const [b0, b1] = LIVE[n], all = [...LINKS[n].solid.map((i) => [i, false]), ...LINKS[n].dash.map((i) => [i, true])];
    all.forEach(([i, dashed], k) => {
      AGD.link(b0 + k * .1, b1, i, toCard(id), { bend: .45, draw: .55, out: .45, pulse: 2, dash: dashed ? '3 6' : undefined });
      AGD.pulse(i, EV[n] - .05, 1.08, .6);
      // v17.7: as it steps forward and its link starts, the dot stretches into a pill aimed at the card (the link leaves
      // from its tip); once the type word has wiped in it settles back into a bullet with a ✓ (solid link = full tick,
      // dashed = a thin 1.2 px one): this entry uses these Agents. The tick holds 1.4 beats, then draws back out
      AGD.morph(b0 + k * .1, i, 'pill', { w: 2.6, aim: toCard(id), dur: .4 });
      AGD.morph(EV[n] + .4, i, 'bullet', { tick: 1, tickW: dashed ? 1.2 : 2, dur: .45, hold: 1.4, back: .35, to: 'bullet' });
    });
  });
  // (f) glow: one window per run of consecutive entries a dot links to (EV − .2 … b1 − .3, joined when the next starts
  // < .9 beat after the last ends), so a shared dot stays lit across the hand-over instead of dipping for .5 beat
  [0, 1, 2, 3, 4].forEach((i) => {
    const w = [];
    IDS.forEach((_, n) => {
      if (!LINKS[n].solid.includes(i) && !LINKS[n].dash.includes(i)) return;
      const g0 = EV[n] - .2, g1 = LIVE[n][1] - .3, l = w[w.length - 1];
      if (l && g0 - l[1] < .9) l[1] = g1; else w.push([g0, g1]);
    });
    w.forEach(([g0, g1]) => AGD.glow(i, g0, g1, .9));
  });
  // T11 (v18.1, +.8 in v18.2): the column leaves its bullets for round badges from b62.8 and, from b63.2 (just before the
  // payoff exits), closes on its centre row at MERGE (330, 540) — a tight stack 22 px apart by b63.8,
  // where 50-tools' merge key takes the live positions into the orb. No static five-dot column on an empty frame
  AGD.morph(62.8, ROWDOT, 'dot', { dur: .5, stag: .04 });
  AGD.key(63.2, 'column', { x: 330, y0: 540 - 2 * 22, gap: 22, r: 30, a: 1, order: ORD, dur: .6, stag: 0 });
  // T10′: from .3 beats before entry n reaches the centre line, the dots it links to step forward 330 → 386 (E.io .4) and
  // light up (a 1), the rest stay at 330 / a .6; they step back over the .4 beats before their links retract. The column
  // breathes (±4 / ±8 px, 7–9.5-beat periods) so no dot stands frozen; the follow blends out by b63.0, so the merge (T11)
  // starts from the exact column (the centre row at (330, 540)). During the intro card all five sit at a .8 and pulse in
  // three soft waves down the column (r ×1.08 with a faint glow, b41.6 / 42.7 / 43.8, .12 beat per row)
  // v17.7: each wave is a small pill breath of the bullet (w 2 → 2.3 → 2 along x, logo whole) instead of the r pulse
  [41.6, 42.7, 43.8].forEach((w) => ROWDOT.forEach((i, r) => { const b = w + .12 * r; AGD.morph(b, i, 'bullet', { w: 2.3, dur: .35, hold: .05, back: .4, to: 'bullet' }); AGD.glow(i, b + .15, b + .45, .35); }));
  // a dot linked by two consecutive entries stays forward across the hand-over (its windows touch: b1 → b1 + .05), instead
  // of stepping back to 330 / a .6 and forward again within ≈.5 beat (a visible dip at b69.9 / 72.9 / 75.9 / 78.9)
  const WIN = [0, 1, 2, 3, 4].map((i) => {
    const w = [];
    IDS.forEach((_, n) => {
      if (!LINKS[n].solid.includes(i) && !LINKS[n].dash.includes(i)) return;
      const [b0, b1] = LIVE[n], l = w[w.length - 1];
      if (l && b0 - l[1] < .5) l[1] = b1; else w.push([b0, b1]);
    });
    return w;
  });
  const near = (i, b, d) => {
    let v = 0;
    for (const [b0, b1] of WIN[i]) v = Math.max(v, Math.min(E.inOut(lp(b, b0, d)), 1 - E.inOut(lp(b, b1 - d, d))));
    return v;
  };
  AGD.follow(40.9, 63.8, (i, b, q) => {
    const h = hash01(i, 11), px = 7 + 2.5 * hash01(i, 12), py = 7.5 + 2 * hash01(i, 13), ia = 1 - E.inOut(lp(b, S4, .8));
    return { a: .6 + .4 * Math.max(near(i, b, .3), .5 * ia), x: q.x + STEP_X * near(i, b, .4) + 4 * Math.sin(2 * Math.PI * (b / px + h)), y: q.y + 8 * Math.sin(2 * Math.PI * (b / py + h * 1.7)) };
  }, { blend: .4 });

  /* ---------- deck 0: six cards in one column (b40.0 set-up, b43.8–63.1 on screen: the frame between the dial / persona column
     leaving (b40.2–40.25) and the first card belongs to the intro card; the first card fades in from below during its last
     .7 beat) ---------- */
  const advLight = (d) => { const Wd = decks[d].W; if (Wd.eval('S.ed') !== 'advance') Wd.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); Wd.setTheme('light'); };
  const still = (D) => D.getAnimations().forEach((a) => { const t = a.effect && a.effect.target; if (t && t.closest && t.closest('.recs')) a.cancel(); });
  const unscroll = (D) => { for (let e = D.querySelector('#content'); e; e = e.parentElement) { if (e.scrollTop) e.scrollTop = 0; if (e.scrollLeft) e.scrollLeft = 0; } };
  // the app lays the list out 820 px wide; a narrower card (WA app px) wraps into a taller, readable block at CW on screen
  const WA = 400, S0 = CW / WA;
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
    if (cs.length) GAP = Math.max(490, Math.ceil(Math.max(...cs.map((c) => base(c).h)) * S0 + 152 + 80));   // tallest entry + 80 px air
    Y0 = cr.top + cr.height / 2;                                  // the column runs through the middle of #content (it clips)
    CAM = { x: X0, y: Y0, s: S0, ax: CX, ay: CY, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 };
    if (DEBUG) console.warn('promo 40-recs layout', JSON.stringify({ S0, X0, Y0, GAP, H: cs.map((c) => base(c).h) }));
  });
  tween(0, 40.3, 0, () => CAM || { x: 400, y: 500, s: 2, ax: CX, ay: CY, o: 1 }, E.lin);

  // scroll position u (entries): entry n's centre is at CY + GAP·(n − u). One constant 163 px/beat (no stop-and-go, no
  // hold; the column is below the frame / transparent during the intro); from b61.9 an E.in term adds .6 entry so the
  // column eases faster up and out while it fades (gone by b63.1, H12)
  const U = (b) => (b - ARR[0]) / PIT + .6 * E.in(lp(b, 61.9, 1.2));
  const FOC = IDS.map(() => ({ a: 0, bl: 0 }));                  // per entry: opacity and blur, shared by its card and its word
  const MK = { t: 'rc', k: 'rk' };
  drive(0, 40.25, OUT4, (p, b, D) => {
    still(D); unscroll(D);
    const u = U(b), gIn = E.out(lp(b, S4 - .7, 1.2)), gOut = 1 - E.inOut(lp(b, PO - .2, .5));
    IDS.forEach((id, n) => {
      const el = card(D, id); if (!el) return;
      narrow(el);
      const B = base(el), dy = GAP * (n - u), hs = B.h * S0, top = CY + dy - (hs - 152) / 2;   // entry = 128 px word + 24 px + card, centred on dy
      const appTop = Y0 + (top - CY) / S0, ad = Math.abs(dy), tx = X0 - B.x, ty = appTop - B.y;
      el.dataset.r4x = tx.toFixed(1); el.dataset.r4y = ty.toFixed(1);
      el.style.transform = 'translate(' + tx.toFixed(1) + 'px,' + ty.toFixed(1) + 'px)';
      // sharp from 260 px below to 320 px above the centre line (≈3.6 beats at 163 px/beat; above −320 the word starts to
      // leave the frame), then dims and blurs 6 px per 360 px (≤1 px within 60 px more: ≈4.3 beats readable)
      const kg = KG(), af = (dy < 0 ? Math.max(0, ad - 320 * kg) : Math.max(0, ad - 260 * kg)) / kg, a = clamp(1 - .65 * af / 360) * gIn * gOut, bl = 6 * af / 360 + 6 * (1 - gOut);
      FOC[n] = { a, bl };
      el.style.opacity = a.toFixed(3);
      el.style.filter = bl > .05 ? 'blur(' + (bl / S0).toFixed(2) + 'px)' : 'none';
      // the card's own 省时 / token figure is swept by a marker as its share lands in the counter
      const f = FLD[n], fig = f ? el.querySelector('.rc-save b[data-ck="' + MK[f] + ':' + id + '"]') || el.querySelector('.rc-save b:' + (f === 't' ? 'first-of-type' : 'last-of-type')) : null;
      if (fig) {
        const w = E.inOut(lp(b, EV[n] - .1, .9)) * 100;
        fig.style.backgroundImage = w > .1 ? 'linear-gradient(rgba(226,96,43,.34),rgba(226,96,43,.34))' : '';
        fig.style.backgroundRepeat = 'no-repeat'; fig.style.backgroundPosition = '0 88%'; fig.style.backgroundSize = w.toFixed(1) + '% .5em';
      }
    });
  });
  tween(0, OUT4 - .02, 0, { o: 0 }, E.lin);

  // the type word of each entry rides 24 px above its card's top-left corner, blurred and dimmed with it. It is not on
  // screen before its entry is emitted: it wipes in left → right (.35 beats, soft 15 % edge) from the moment the first link
  // reaches the card's left edge (link start + .4: the link is drawn to ≈98 %, the stepping dot has landed at 386)
  const WIPE = EV;
  IDS.forEach((id, n) => {
    const b0 = WIPE[n] - .05, b1 = Math.min(OUT4, n < 5 ? ARR[n] + 3.5 : OUT4);
    txt(b0, b1, [['xl sv r4-w', WORD[n]]], { x: CX, y: -400 }, {
      anim: (el, tl, life, t) => {
        const F = FOC[n], p = elXY(0, sel(id), 0, 0), w = E.inOut(lp(t / BEAT, WIPE[n], .35));
        el.style.left = p[0].toFixed(1) + 'px'; el.style.top = (p[1] - 24).toFixed(1) + 'px';
        el.style.transform = 'translate(0,-100%)';
        // v18.1 QA: at the 1.34× framing the 128 px word reaches the top edge while its card is still sharp (≈1 beat cut
        // in half at b70.5 / 73.5 / 76.5 / 82.5): it fades out as its top nears the frame edge (gone at −10 px) instead
        el.style.opacity = (F.a * clamp((p[1] - 24 - 128 + 10) / 100)).toFixed(3);
        el.style.filter = F.bl > .05 ? 'blur(' + F.bl.toFixed(2) + 'px)' : 'none';
        const m = w >= 1 ? 'none' : 'linear-gradient(90deg,#000 ' + (115 * w - 15).toFixed(1) + '%,transparent ' + (115 * w).toFixed(1) + '%)';
        el.style.maskImage = m; el.style.webkitMaskImage = m;
      }
    });
  });

  /* ---------- intro card → eyebrow, and the two running totals ---------- */
  // the three lines are written out of the dot column as it arrives (r176b): when row r's dot is ≈ 70 % home a link
  // grows from it to the left edge of line r (x 530; rows 0–2 sit level with the eyebrow / headline / orange line), and
  // .3 beat later, as the link lands and the dot settles, the line wipes in left → right (soft 15 % edge) while sliding
  // 28 px out of the link (E.out); the dot pulses as it emits, and the link retracts .9 beat after. The lines then drift up
  // 12 px while they hold (headline written by b40.6, readable ≈3.9 beats at full size, as before), then move and shrink
  // together into the top-left eyebrow slot (no stagger, so the lines never overlap mid-move) and stay there, small, until the scene leaves.
  // The rise leads the slide left by .25 beat (both .85 beats), so the lines pass above the dot column's top row instead
  // of over it, and the orange line is far above the first type word, which wipes in at b45.0 from y ≈480
  [['eb', '02 · 优化建议', 370, 100, 1, .4],
   ['sv r4-h', '根据你的使用习惯，智能推荐', 466, 146, 26 / 88, .6],
   ['r4-a', '提高效率', 584, 182, 26 / 64, .45]].forEach(([cls, html, y0, y1, k1, wd], r) => {
    const m0 = mask(.18, .001, .6), wb = ROWIN[r] + .3, i = ROWDOT[r];
    const my = (b) => E.inOut(lp(b, S4, MV - .25)), ly = (b) => lerp(y0 - 12 * lp(b, 40.3, S4 - 40.3), y1, my(b));
    AGD.link(ROWIN[r], wb + .9, i, (b) => [530, ly(b)], { bend: .45, draw: .3, out: .4, pulse: 1 });
    AGD.pulse(i, wb - .05, 1.08, .5); AGD.glow(i, wb - .1, wb + .35, .35);
    // v17.7: as its link starts the gliding dot stretches into a pill aimed at the line's start (the link leaves its tip,
    // the line wipes out of the link), then lands as a bullet .5 beat after the line starts writing
    AGD.morph(ROWIN[r] - .05, i, 'pill', { w: 2.6, aim: (b) => [530, ly(b)], dur: .3, hold: .55, back: .4, to: 'bullet' });
    // v18.2: only the eyebrow (row 0) settles in the top-left slot (24 px mono); the headline and the orange line rise
    // and slide with it but fade to 0 over the move (gone by S4 + .75) instead of resting there as 26 px small print.
    // Payoff: the orange line (row 2) wipes in again left → right on the left of the centred counters (x 500, level with
    // the numerals, 1.1×); the eyebrow fades out as the payoff starts
    const fin = r === 2, m1 = fin ? mask(.18, .001, POX) : m0;
    txt(wb - .02, fin ? POUT : OUT4, [[cls, html]], { x: 540, y: y0 }, {
      anim: (el, tl, life, t) => {
        m1(el, tl, life);
        const b = t / BEAT, mx = E.inOut(lp(b, S4 + .25, MV - .25)), pe = PE(b), pay = fin && b >= PO;
        const w = pay ? E.inOut(lp(b, PO + .1, .5)) : E.inOut(lp(b, wb, wd)), fo = r ? 1 - E.inOut(lp(b, S4, .75)) : 1;
        let k = lerp(1, k1, my(b)), x = lerp(540, 160, mx) - 28 * (1 - E.out(lp(b, wb, wd + .4))), y = ly(b);
        if (pay) { x = 440 - 24 * (1 - E.out(lp(b, PO + .1, .7))); y = 480; k = 1.1; }
        el.style.opacity = (pay ? 1 : fin ? fo : fo * (1 - pe)).toFixed(3);
        el.style.filter = !pay && fo < .999 ? 'blur(' + (6 * (1 - fo)).toFixed(2) + 'px)' : 'none';
        el.style.left = x.toFixed(1) + 'px'; el.style.top = y.toFixed(1) + 'px';
        el.style.transformOrigin = '0 50%'; el.style.transform = 'translate(0,-50%) scale(' + k.toFixed(4) + ')';
        const m = w >= 1 ? 'none' : 'linear-gradient(90deg,#000 ' + (115 * w - 15).toFixed(1) + '%,transparent ' + (115 * w).toFixed(1) + '%)';
        el.style.maskImage = m; el.style.webkitMaskImage = m;
      }
    });
  });
  const pct = (v) => v <= 0 ? '0.0%' : v < 10 ? v.toFixed(1) + '%' : Math.round(v) + '%';   // = fmtPct above .1 %; no「<0.1%」mid-roll
  const val = (f, b) => STEP.reduce((v, s, n) => v + (s.f === f ? s.d * E.out(lp(b, EV[n] - .1, 1.2)) : 0), 0);   // 1.2-beat roll from the emission
  // v17.7: each roll enters the way its links flow (left → right): the figure slides in from 4 px left out of a 2 px blur
  const num = (f) => (el, tl, life, t) => {
    const nd = el.querySelector('.r4-v'); if (!nd) return;
    const b = t / BEAT; nd.textContent = pct(val(f, b));
    let g = 0; STEP.forEach((s, n) => { if (s.f === f && s.d > 0) { const u = lp(b, EV[n] - .1, .7); if (u > 0 && u < 1) g = Math.max(g, 1 - E.out(u)); } });
    nd.style.display = 'inline-block';
    nd.style.transform = g > .002 ? 'translateX(' + (-4 * g).toFixed(2) + 'px)' : '';
    nd.style.filter = g > .02 ? 'blur(' + (2 * g).toFixed(2) + 'px)' : '';
  };
  // the counter block drifts up 40 px over the scene, so it never stands frozen between rolls. It comes in behind the moving
  // headline's right end (b44.85 on) as the first entry is emitted. v18.1: it sits at x 1720 (right of the 1000 px cards);
  // the Token half stays dark until its first share starts rolling (b47.4 in the demo data: no「0.0 %」beside Hook's own
  // token 1.6 %), then masks in; at the payoff (PO) every piece glides to its place in the centred statement
  // [x0, y0, k0, x1, y1, k1]: right column → centre (numerals 1.5×, the caption grows from .8 to 1)
  // v18.2: each numeral gets a 36 px Chinese label under it (协作时间 / Token 用量) instead of the mono label above it
  const POS = { tl: [1720, 535, 1, 940, 600, 1], tv: [1720, 450, 1, 940, 480, 1.5], kl: [1720, 785, 1, 1370, 600, 1],
    kv: [1720, 700, 1, 1370, 480, 1.5], cap: [1720, 880, .75, 1155, 680, 1] };
  // the Token half lags .12 beat behind the time half, so the two numerals never pass over each other on the way in
  const place = (key, lag = 0) => { const m = mask(.18, 1, POX), [x0, y0, k0, x1, y1, k1] = POS[key]; return (el, tl, life, t) => {
    m(el, tl, life);
    const b = t / BEAT, pe = E.inOut(lp(b, PO + lag, POD)), dy = -40 * lp(b, 44.85, 18.25) * (1 - pe);
    el.style.left = lerp(x0, x1, pe).toFixed(1) + 'px'; el.style.top = (lerp(y0, y1, pe) + dy).toFixed(1) + 'px';
    el.style.transform = 'translate(-50%,-50%) scale(' + lerp(k0, k1, pe).toFixed(4) + ')';
  }; };
  const KN = STEP.findIndex((st) => st.f === 'k'), KB = KN >= 0 ? EV[KN] - .1 : 45.1;   // first token roll
  txt(45.05, POUT, [['r4-l', '协作时间']], { x: 1720, y: 535, align: 'c' }, { anim: place('tl') });
  txt(44.9, POUT, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1720, y: 450, align: 'c' }, { anim: place('tv'), tick: num('t') });
  txt(KB + .1, POUT, [['r4-l', 'Token 用量']], { x: 1720, y: 785, align: 'c' }, { anim: place('kl', .12) });
  txt(KB, POUT, [['r4-n', '<span class="r4-v">0.0%</span>']], { x: 1720, y: 700, align: 'c' }, { anim: place('kv', .12), tick: num('k') });
  txt(45.35, POUT, [['lt r4-s', '预计可节省的占比 · 按真实轨迹估算']], { x: 1720, y: 880, align: 'c' }, { anim: place('cap', .2) });
});
