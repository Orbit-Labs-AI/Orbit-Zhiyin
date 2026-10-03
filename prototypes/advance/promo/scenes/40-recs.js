/* 02 推荐 → 效率（b55.6–84.4）：穿越门里的建议传送带 → 每条的省时汇入「省多少 · 逐条算清」→ 一键安装 → 7 天后 → 前后对比 → 把时间还给你自己
   Shots, keyframes and hand-offs: STORYBOARD.md (KF 5.1–5.13).
   5a  the 12 .rcard cards of deck 0 are re-laid by transforms into a horizontal conveyor (inside #content's clip, so they
       are shrunk in the app and the camera zooms in); the centre card is sharp, the others blur with distance; each card
       that crosses the centre sends a 「省时」 chip on an arc into the headline. The film shows no totals or personal
       figures: the copy describes the product, the app's own cards are what is on screen.
   5b  the headline shrinks into an eyebrow, 重复失败熔断 lifts, its install button is pressed, deck 0 turns away while
       deck 1's install sheet turns in, two presses run the app's real install flow.
   5c  the sheet shrinks into the ▲ install day of the tracking strip, which grows out of that point; seven days fill.
   5d  the camera drops to the three before/after rows: after-dots slide, big figures and green pills ride on the right.
   5e  the card falls back; Apple's formula 「把时间 / 还给 / 你 / 自己」 lands on the drop at b79.4. */
scene('40-recs', () => {
  css(`
.r-or{color:var(--a1)}
.ln.r-tot{overflow:visible}
.ln.r-tot>span{display:inline-flex;align-items:baseline;gap:22px}
.r-tot .r-n{font-variant-numeric:tabular-nums}
.r-tot .r-u{font-size:72px;font-weight:600;letter-spacing:0;color:var(--a1)}
.r-fly{position:absolute;left:0;top:0;font:700 54px var(--mono);color:var(--a1);white-space:nowrap;will-change:transform,opacity;text-shadow:0 4px 24px rgba(0,0,0,.6)}
.ln.r-eb>span{display:inline-flex;align-items:baseline;gap:20px}
.r-eb .r-ebl{font-family:var(--mono);font-size:24px;letter-spacing:.3em;color:rgba(255,255,255,.6)}
.r-eb .r-ebn{font-size:48px;font-weight:700;color:var(--a1);letter-spacing:-.01em}
.k .eb.r-or{color:var(--a1)}
.r-day{font:600 30px var(--mono);color:#fff;letter-spacing:.06em}
.r-dim{color:rgba(255,255,255,.62)}
.r-mn{font-size:40px;color:rgba(255,255,255,.72)}
.ln.r-mv{overflow:visible}
.ln.r-mv>span{display:inline-flex;align-items:center;gap:.3em}
.r-mv .st{color:rgba(255,255,255,.5);font-weight:500}
.r-mv .r-ar{color:rgba(255,255,255,.5);font-weight:400}
.r-mv b{font-weight:700;color:#fff;font-variant-numeric:tabular-nums}
.r-mv .r-un{font-size:40px;font-weight:400;color:rgba(255,255,255,.72)}
.k .pill.r-g{font-size:40px;color:#7fd6a4;background:rgba(127,214,164,.13);border:1.5px solid rgba(127,214,164,.55);margin-left:.25em}
.ln.r-vd{overflow:visible}
.k .pill.r-ok{font:700 40px var(--sans);color:#fff;background:var(--a1);box-shadow:0 14px 40px rgba(226,96,43,.35)}
.ln.r5{overflow:visible}
.ln.r5>span{display:grid;grid-template-columns:auto auto;column-gap:34px;align-items:start;text-align:left}
.r5 .r5-pre{grid-row:1;grid-column:1;display:flex;flex-direction:column;align-items:flex-end;gap:10px;padding-top:58px;font:500 30px var(--mono);letter-spacing:.24em;color:rgba(255,255,255,.72)}
.r5 .r5-pre span{display:block;will-change:transform,opacity}
.r5 .r5-num{grid-row:1;grid-column:2;font-family:var(--display);font-size:300px;line-height:.92;letter-spacing:-.02em;transform-origin:30% 60%;
  background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent;will-change:transform,opacity,filter}
.r5 .r5-u{grid-row:2;grid-column:2;font-size:120px;font-weight:700;line-height:1.1;color:var(--a1);will-change:transform,opacity}
`);
  const RB = 'retry-breaker';
  // tag() scales a top/bottom tag about its own (at·100%) point and then shifts it by at·100% of its scaled width, which
  // lands it (1 − s)·at·width off its anchor whenever at > 0; scaling about the corner puts it back on the anchor
  const pin = (f) => (el, tl, life, t) => { el.style.transformOrigin = '0 0'; if (f) f(el, tl, life, t); };
  const card = (D, id) => D.querySelector('.rcard[data-id="' + id + '"]');
  // both copies stay in the Advance edition, light theme (hand-off contract)
  const advLight = (d) => { const W = decks[d].W; if (W.eval('S.ed') !== 'advance') W.eval("S.ed='advance';store.set('edition','advance');document.querySelector('#win').dataset.ed='advance'"); W.setTheme('light'); };
  // the engine's .promo-card ring loses to the solo shadow rule; give a solo'd promo-card its paper margin back
  const paperCss = (D) => { if (D.getElementById('r-paper')) return; const s = D.createElement('style'); s.id = 'r-paper'; s.textContent = 'html body .promo-solo.promo-card{box-shadow:0 0 0 22px var(--surface),0 30px 90px 22px rgba(0,0,0,.55)!important;border-radius:6px}'; D.head.appendChild(s); };

  // solo() scrolls targets into view, which also scrolls the clipped window and the desk: undo it on every ancestor
  // the app's entrance animations (fill: both) would override the cards' inline transforms: drop them
  const still = (D) => D.getAnimations().forEach((a) => { const t = a.effect && a.effect.target; if (t && t.closest && t.closest('.recs')) a.cancel(); });
  const unscroll = (D) => { for (let e = D.querySelector('#content'); e; e = e.parentElement) { if (e.scrollTop) e.scrollTop = 0; if (e.scrollLeft) e.scrollLeft = 0; } };

  /* ---------- 5a conveyor + total (b55.2–64.6) ---------- */
  // cross = the beat card i is centred and its saving leaves; gaps tighten 0.5 → 0.3 beat; arrival = cross + 0.5
  const N = 12, CROSS = [57.7]; for (let j = 0; j < N - 1; j++) CROSS.push(CROSS[j] + .5 - .2 * j / (N - 2));
  const ARR = CROSS.map((c) => c + .5), LAST = ARR[N - 1];                  // LAST = 62.6; settles at 63.4
  const SETTLE = 63.4, STOP = CROSS[N - 1] + 1.2;                           // conveyor stops at 63.3
  // the conveyor position (index at the centre, a float) as a function of the beat
  const conv = (b) => {
    if (b < 55.2) return -3;
    if (b < CROSS[0]) { const p = (b - 55.2) / (CROSS[0] - 55.2); return -3 + p + 2 * p * p; }   // eases up to 2 cards/beat
    for (let i = 0; i < N - 1; i++) if (b < CROSS[i + 1]) return i + (b - CROSS[i]) / (CROSS[i + 1] - CROSS[i]);
    const q = clamp((b - CROSS[N - 1]) / (STOP - CROSS[N - 1])); return N - 1 + 2 * (1 - (1 - q) * (1 - q));   // decelerates onto card 13 = retry-breaker
  };
  const K0 = .62, PITCH = 294, CX = 1114, CY = 540;                        // in-app scale, spacing, centre (inside #content)
  const CONV = { x: CX, y: CY, s: 2.15, ax: 960, ay: 760, rx: 12, ry: 0, rz: -1.2, z: 0, o: 1, bl: 0 };
  let IDS = [], BASE = {};
  at(54.8, () => {
    advLight(0);
    const a = app(0); a.S.recs.sel = RB; a.S.recs.tab = 'why'; a.S.recs.dim = 'all'; a.S.recs.peek = null; a.go('recs');
    const D = a.D, ct = D.querySelector('#content'); paperCss(D);
    const cs = [...D.querySelectorAll('.rcard')];
    still(D); cs.forEach((c) => { c.style.transform = 'none'; c.style.filter = 'none'; c.style.opacity = ''; });
    if (ct) ct.scrollTop = 0;
    IDS = cs.map((c) => c.dataset.id);
    cs.forEach((c) => { const r = c.getBoundingClientRect(); BASE[c.dataset.id] = { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
    if (IDS.length !== N || IDS.indexOf(RB) !== 1) console.warn('promo 40-recs: expected 12 cards with retry-breaker second', IDS);
    solo(0, IDS.map((id) => (DD) => card(DD, id)));
    unscroll(D);
  });
  tween(0, 55.2, 0, CONV, E.lin, () => ({}));                               // visible only through #hole0 from here on
  // the door opens onto one recommendation: until b56.1 card 0 waits at the belt's centre (the only place inside #content's
  // clip) and the camera holds it big and flat right under the portal's centre (PORTAL[0], the 「建议 →」 click);
  // b56.1–57.7 the camera pulls back (ease-in-out) into the conveyor framing while card 0 rejoins its slot, so the belt
  // starts moving out of that card. HERO = how close the camera still is.
  const PULL0 = 56.1, PULL = 1.6, HERO = (b) => (b < 55.2 || b >= PULL0 + PULL ? 0 : 1 - E.inOut(lp(b, PULL0, PULL)));
  const heroCam = (b, D) => {
    const el = card(D, IDS[0]), P = PORTAL[0] || [1650, 835];
    const w = el ? el.offsetWidth * K0 : 400, h = el ? el.offsetHeight * K0 : 130;
    const s = Math.min(1800 / w, 480 / h);                                  // card ≈ 1800 wide on screen (or 480 tall)
    // the portal centre falls on the card's right part (its saving), so most of the card lies on screen as the door opens
    return { x: CX - conv(b) * PITCH * (1 - HERO(b)) + .2 * w, y: CY, s, ax: P[0], ay: P[1], rx: 0, rz: 0 };
  };
  // lay the cards out every frame: wrap the first two round to the end, focus by distance, then the 5b lift
  drive(0, 54.85, 66.6, (p, b, D) => {
    unscroll(D); still(D);
    const hero = HERO(b);
    if (b >= 55.2 && b < PULL0 + PULL + .1) {                               // the camera owns no tween here (b55.2–64.2)
      const H = heroCam(b, D), C = decks[0].C, k = 1 - hero, ls = Math.exp(lerp(Math.log(H.s), Math.log(CONV.s), k));
      // look-at and anchor blend so the point under the screen follows the card, the zoom blends in log space
      for (const key of ['x', 'y', 'ax', 'ay', 'rx', 'rz']) C[key] = lerp(H[key], CONV[key], k);
      C.s = ls;
    }
    const c0 = conv(b), lift = E.inOut(lp(b, 64.2, .65)), fade = E.inOut(lp(b, 64.3, .6));
    IDS.forEach((id, i) => {
      const el = card(D, id), B = BASE[id]; if (!el || !B) return;
      let u = i - c0; if (u < -6) u += N;
      const d = Math.abs(u) * (i === 0 ? Math.pow(1 - hero, 3) : 1), mine = id === RB;   // card 0 stays sharp while the camera holds it
      const sc = K0 * lerp(1, .9, clamp(d)) * (mine ? 1 + .26 * lift : 1);   // lifted: ≈ 1500 px wide on screen, title ≥ 24 px
      if (i === 0) u *= 1 - hero;                                           // held at the centre (inside #content's clip)
      el.style.transform = 'translate(' + (CX + u * PITCH - B.x).toFixed(1) + 'px,' + (CY - B.y).toFixed(1) + 'px) scale(' + sc.toFixed(4) + ')';
      const bl = Math.min(4.6, d * 2.3) * (mine ? 1 - lift : 1);
      el.style.filter = bl > .05 ? 'blur(' + bl.toFixed(2) + 'px)' : 'none';
      el.style.opacity = ((1 - .16 * Math.min(2, d)) * (mine ? 1 : 1 - fade)).toFixed(3);
      el.style.zIndex = mine ? '3' : '';
    });
  });
  // the savings fly from each centred card on an arc into the total
  const FLY = [];
  every(57.6, 63.4, (p, b) => {
    IDS.forEach((id, i) => {
      const c = CROSS[i], q = lp(b, c, .5);
      let f = FLY[i];
      if (b < c || q >= 1) { if (f && f.el) { f.el.remove(); f.el = null; } return; }
      if (!f) { f = FLY[i] = {}; }
      if (!f.el) { f.el = document.createElement('div'); f.el.className = 'r-fly'; f.el.textContent = '省时'; fxEl.appendChild(f.el); }
      if (!f.a) f.a = elXY(0, (D) => { const e = card(D, id); return e && e.querySelector('.rc-save b'); });
      // the landing point sits just right of 「h / 月」 on the digits' mid-line, measured every frame (the total widens as it
      // rolls); the chip's left edge stops there, so it never covers the digits or the unit, and it shrinks and fades
      // into the unit over the last 40 % of the flight, while the total rolls on its arrival (ARR)
      const u = fxEl.querySelector('.r-tot .r-u'), st = stage.getBoundingClientRect(), z = st.width / 1920;
      let ux = 1180, uy = 330; if (u) { const r = u.getBoundingClientRect(); ux = (r.right - st.left) / z; uy = (r.top + r.height * .5 - st.top) / z; }
      const e = E.inOut(q), sk = E.inOut(lp(q, .6, .4)), s = lerp(.7, 1.1, Math.sin(Math.PI * Math.min(1, e * 1.2))) * lerp(1, .42, sk);
      const hw = f.el.offsetWidth * s / 2, x0 = f.a[0], y0 = f.a[1] - 20, x1 = ux + 26 + hw, y1 = uy, cx = lerp(x0, x1, .5) + 160, cy = Math.min(y0, y1) - 150;
      const x = (1 - e) * (1 - e) * x0 + 2 * (1 - e) * e * cx + e * e * x1, y = (1 - e) * (1 - e) * y0 + 2 * (1 - e) * e * cy + e * e * y1;
      f.el.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) translate(-50%,-50%) scale(' + s.toFixed(3) + ')';
      f.el.style.opacity = (Math.min(1, q * 6) * (1 - E.in(lp(q, .62, .38)))).toFixed(3);
    });
  });
  txt(57.5, 64.5, [['eb', '02 · 推荐 · 按协作人格定制']], { x: 960, y: 150, align: 'c' }, { outB: .5 });
  txt(58.1, 64.5, [['lt', '每条建议都标明能省下的时间']], { x: 960, y: 455, align: 'c' }, { outB: .5 });
  // the headline the savings fly into (no total: the film shows the product, not one person's numbers), then the
  // highlighter sweeps; b64.0–64.6 it shrinks towards the top-left corner, where the eyebrow takes over
  const TOT0 = 57.8;
  txt(TOT0, 64.7, [['xl sv r-tot', '<span class="mk"><span class="r-n">省多少</span><span class="r-u">逐条算清</span></span>']], { x: 960, y: 322, align: 'c' }, {
    anim: K.all(K.rise({ in: .8, out: .3 }), K.mark(SETTLE + .1 - TOT0, .45)),
    tick: (el, tl, life, t) => {
      const b = t / BEAT;
      const q = E.inOut(lp(b, 64.0, .6));
      el.style.transform = 'translate(-50%,-50%) translate(' + (-520 * q).toFixed(1) + 'px,' + (-212 * q).toFixed(1) + 'px) scale(' + lerp(1, .26, q).toFixed(4) + ')';
      el.style.opacity = (1 - E.in(lp(b, 64.15, .35))).toFixed(3);   // gone before the eyebrow rises
    }
  });

  /* ---------- 5b lift → press → flip into the install sheet (b64–69.6) ---------- */
  txt(64.5, 69.7, [['r-eb', '<span class="r-ebl">推荐</span><span class="r-ebn">针对盲点</span>']], { x: L, y: 112 }, { st: 0, outB: .6 });
  tween(0, 64.2, .9, () => ({ ay: 480, rx: 0, rz: 0, s: CONV.s * 1.1 }), E.inOut);
  tag(0, 64.8, 66.15, (D) => card(D, RB), 'top', [['eb r-or', '例如 · 工具 / 环境反复失败']], { gap: 34, at: .5, outB: .3, tick: pin() });
  clickAt(0, 66.0, (D) => { const c = card(D, RB); return c && c.querySelector('[data-act="install"]'); }, () => {}, { bloom: 'var(--a1)', glide: .9 });
  tween(0, 66.1, .32, () => ({ ry: 90, s: decks[0].C.s * .96 }), E.in);
  tween(0, 66.44, 0, { o: 0 }, E.lin);
  at(65.0, () => {
    advLight(1);
    const a = app(1); a.S.recs.sel = RB; a.S.recs.tab = 'why'; a.go('recs');
    if (a.W.eval('S.installed.has("' + RB + '")')) a.W.eval('S.installed.delete("' + RB + '")');
    a.W.openInstall(RB); solo(1, '#modal');
  });
  const SHEET = [960, 420, 1180, 640];
  tween(1, 66.42, .36, () => framing(1, '#modal', SHEET), E.out, () => ({ ry: -90, o: 1 }));
  tween(1, 66.8, 2.6, () => ({ s: decks[1].C.s * 1.03 }), E.sine);
  const press = (a, el) => { a.W.eval('INST && (INST.t = 0)'); a.click(el); };   // runs the app's own flow; a jump in time must not trip its double-click guard
  clickAt(1, 67.4, '#modal .btn.p', press, { glide: 1.0 });
  clickAt(1, 68.4, '#modal .btn.p', press, { glide: .45 });
  txt(66.4, 69.6, [['hv sv', '预览，再写入'], ['md r-or', '<span class="sw"><span>一键安装 · 随时撤销</span><span>已安装 · 开始追踪 7 天</span></span>']], { x: 960, y: 928, align: 'c' }, {
    anim: K.all(K.rise({ st: .25, out: .5 }), K.swap({ at: [68.6 - 66.4], dur: .35 }))
  });

  /* ---------- 5c the sheet shrinks into the ▲ install day; seven days fill (b69–72.6) ---------- */
  const METS = (D) => { const m = D.querySelector('.rc-metric'); return m && m.parentElement; };
  let DAYS = null;
  const daysFrame = () => {
    const r = rectOf(0, '.rc-days'), m = rectOf(0, '.rc-days .mark'), s = 1500 / r.w, mx = m.x + m.w / 2, my = r.y + r.h / 2;
    return { x: mx, y: my, s, ax: 960 + (mx - (r.x + r.w / 2)) * s, ay: 430, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0 };
  };
  at(69.0, () => {
    const a = app(0), S = a.S;
    S.recs.sel = RB; S.recs.tab = 'track'; S.recs.peek = RB;
    S.installed.set(RB, { days: 7, at: 0, target: a.W.eval('RECI["' + RB + '"].target'), scope: 'global' });
    a.go('recs'); paperCss(a.D);
    solo(0, ['.rc-days', METS]); unscroll(a.D);
  });
  // the app's own tracking view at day 7, wound back to the beat: cells after the ▲ fill one by one, the after-dots of
  // the dumbbells wait on the before values until their row's beat
  const DAY0 = 70.5, DAYG = .25, ROW = [73.4, 74.4, 75.4], SLIDE = .9;
  const dayAt = (b) => clamp(Math.floor((b - DAY0) / DAYG) + 1, 0, 7);
  let CUR = 1, DONE = false;
  drive(0, 69.02, 79.6, (p, b, D) => {
    const days = D.querySelector('.rc-days'), lbl = D.querySelector('.rc-dlbl'), mets = METS(D); if (!days) return;
    [days, mets].forEach((e) => e && e.classList.add('promo-card'));
    const k = dayAt(b); CUR = Math.max(1, k); DONE = k >= 7;
    [...days.querySelectorAll('i:not(.base):not(.mark)')].forEach((c, j) => { c.className = j < k ? 'on' : ''; });
    const away = 1 - E.inOut(lp(b, 72.6, .6));
    days.style.opacity = away.toFixed(3); if (lbl) lbl.style.opacity = away.toFixed(3);
    if (mets) mets.style.opacity = E.inOut(lp(b, 72.5, .7)).toFixed(3);
    unscroll(D);
    D.querySelectorAll('.rc-metric').forEach((m, i) => {
      m.querySelectorAll('.rc-mh > .mono, .rc-mh > .rc-d, .rc-mh > .rc-ci').forEach((e) => e.style.setProperty('visibility', 'hidden', 'important'));
      const svg = m.querySelector('svg.vz-t-dumbbell'); if (!svg) return;
      const A = svg.querySelector('circle.vz-pt[data-s="0"]'), Bp = svg.querySelector('circle.vz-pt[data-s="1"]'), ln = svg.querySelector('line.vz-dline'), val = svg.querySelector('text.vz-val');
      if (!A || !Bp) return;
      if (Bp.dataset.cx == null) { Bp.dataset.cx = Bp.getAttribute('cx'); A.dataset.cx = A.getAttribute('cx'); }
      const a0 = +A.dataset.cx, b0 = +Bp.dataset.cx, q = E.inOut(lp(b, ROW[i], SLIDE)), x = lerp(a0, b0, q);
      Bp.setAttribute('cx', x.toFixed(2)); if (ln) ln.setAttribute('x2', x.toFixed(2));
      if (val) val.style.opacity = E.out(lp(b, ROW[i] + SLIDE, .4)).toFixed(3);
    });
  });
  // deck 0 grows out of the ▲ while deck 1's sheet shrinks into it
  tween(0, 69.3, 0, () => { DAYS = daysFrame(); return Object.assign({}, DAYS, { s: DAYS.s * .12, o: 0 }); }, E.lin, () => ({}));
  tween(0, 69.85, .95, () => ({ s: DAYS.s, o: 1 }), E.out);
  tween(1, 69.4, 1.0, () => ({ ax: DAYS ? DAYS.ax : 960, ay: DAYS ? DAYS.ay : 430, s: decks[1].C.s * .025 }), E.inOut);
  tween(1, 69.95, .45, { o: 0 }, E.in);
  txt(69.9, 72.7, [['lt', '装上之后，自动对比前后 7 天']], { x: 960, y: 205, align: 'c' }, { anim: K.blurIn({ out: .5 }) });
  // 「第 k 天」 rides on the cell being filled; the strip's legend sits under it on black (the app's own legend is ink on paper)
  tag(0, 70.0, 72.6, '.rc-days', 'bottom', [['r-day r-dim', '安装前 7 天']], { gap: 112, at: 0, outB: .4 });
  tag(0, 70.0, 72.6, '.rc-days .mark', 'bottom', [['r-day', '▲ 安装日']], { gap: 112, at: .5, outB: .4, tick: pin() });
  tag(0, 70.0, 72.6, '.rc-days', 'bottom', [['r-day r-dim', '安装后 · 第 1 / 7 天']], { gap: 112, at: 1, outB: .4, tick: pin((el) => { const s = el.querySelector('.ln>span'); if (s) s.textContent = CUR >= 7 && DONE ? '安装后 7 天' : '安装后 · 第 ' + CUR + ' / 7 天'; }) });
  tag(0, 70.35, 72.55, (D) => D.querySelectorAll('.rc-days i:not(.base):not(.mark)')[CUR - 1], 'top', [['r-day', '第 1 天']], {
    gap: 112, at: .5, outB: .3, tick: pin((el) => { const s = el.querySelector('.ln>span'); if (s) s.textContent = '第 ' + CUR + ' 天'; })
  });

  /* ---------- 5d before / after rows (b72.5–78.8) ---------- */
  const MET = [660, 560, 1000, 700];
  tween(0, 72.5, 1.0, () => framing(0, METS, MET, { max: 3 }), E.inOut);
  tween(0, 73.5, 4.9, () => ({ s: decks[0].C.s * 1.025 }), E.sine);
  // row figures from the app's own statistics (trackStats: 23 → 7 段, 58 → 17 分钟, 12 → 5 次)
  let ST = [];
  try { ST = decks[0].W.eval('trackStats(RECI["' + RB + '"]).rows').map((m) => ({ name: m.name, a: m.a, b: m.b, unit: m.unit, rel: m.rel })); } catch (e) { console.error('promo 40-recs: trackStats', e); }
  ST.forEach((m, i) => {
    const b0 = ROW[i] - .5;
    tag(0, b0, 78.8, (D) => D.querySelectorAll('.rc-metric')[i], 'right', [['lt r-mn', m.name], ['md r-mv', '<span class="r-ar">安装前 → 安装后</span><span class="pill r-g">' + (m.rel < 0 ? '↓ 减少' : '↑ 增加') + '</span>']], {
      gap: 84, at: .5, tick: (el) => { el.style.textAlign = 'left'; },
      anim: K.all(mask(.14, .9, .5), K.pop(.5 + SLIDE, 0, .3))
    });
  });
  tag(0, 73.0, 78.8, METS, 'bottom', [['eb', '同一批项目 · 前后各 7 天 · 95% 区间']], { gap: 80, at: 0 });
  tag(0, 76.6, 78.8, METS, 'top', [['r-vd', '<span class="pill r-ok">✓ 有效</span>']], {
    gap: 78, at: 1, tick: pin(), anim: K.all(K.pop(0, 0, .3), (el, tl, life) => { el.style.opacity = exitQ(tl, life, .5).toFixed(3); })
  });

  /* ---------- 5e 把时间还给你 (b78.4–84.4) ---------- */
  tween(0, 78.3, .8, () => { const C = decks[0].C; return { rx: 58, s: C.s * .62, ay: C.ay + 300, o: 0, bl: 6 }; }, E.in);
  const PRE = [78.8, 79.1], HIT = 79.4, UNIT = 79.6, F3 = 3 / 60 / BEAT;    // three frames, in beats
  txt(78.7, 83.85, [['r5', '<span class="r5-pre"><span>把时间</span><span>还给</span></span><span class="r5-num">你</span><span class="r5-u">自己</span>']], { x: 960, y: 452, align: 'c' }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT;
      el.querySelectorAll('.r5-pre span').forEach((s, i) => { const q = clamp((b - PRE[i]) / (2 / 60 / BEAT)); s.style.opacity = q.toFixed(3); s.style.transform = 'translateY(' + ((1 - E.out(lp(b, PRE[i], .25))) * 14).toFixed(1) + 'px)'; });
      const n = el.querySelector('.r5-num'), q = lp(b, HIT, .22);
      n.style.opacity = (b >= HIT ? Math.min(1, .35 + q * 4) : 0).toFixed(3);
      n.style.transform = 'scale(' + lerp(1.16, 1, E.out(q)).toFixed(4) + ')';
      n.style.filter = q < 1 ? 'blur(' + ((1 - E.out(q)) * 6).toFixed(1) + 'px)' : 'none';
      n.style.fontWeight = Math.round(lerp(200, 900, clamp((b - HIT) / F3)));
      const u = el.querySelector('.r5-u'), qu = E.out(lp(b, UNIT, .35));
      u.style.opacity = qu.toFixed(3); u.style.transform = 'translateY(' + ((1 - qu) * 40).toFixed(1) + 'px)';
      leave(el, exitQ(tl, life, .55), true);
    }
  });
  txt(80.6, 83.85, [['lt', '按协作人格定制 · 一键安装 · 前后对比验证']], { x: 960, y: 858, align: 'c' }, { anim: K.blurIn({ spread: .6, out: .55, spread2: true }) });
  glowAt(HIT, .9, .5);
  glowAt(80.4, 0, 2.2);
});
