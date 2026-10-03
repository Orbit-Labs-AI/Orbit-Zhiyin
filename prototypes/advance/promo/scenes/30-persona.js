/* 01 人格分析（b21.2–71.4）：会话 → 粒子 → 罗盘 → 领瓣在 3 个示例类型上逐个停留 → 落定你的类型并揭晓 → 优势与盲点 → 点「建议 →」打开穿越门
   Shots, keyframes and hand-offs: STORYBOARD.md. Decks: 2 = the promo's compass, 1 = the app's persona page (4f only).
   Particles are drawn on a canvas between #orbit and #fx; they are projected through deck 2's camera by hand, in an fx
   anim (fx anims run after the cameras are applied, so particles and dial never drift apart by a frame). */
scene('30-persona', () => {
  css(`
.pe-cv{position:absolute;left:0;top:0;width:1920px;height:1080px;pointer-events:none}
.pe-glow{position:absolute;left:0;top:0;width:1100px;height:1100px;margin:-550px 0 0 -550px;border-radius:50%;pointer-events:none;opacity:0;
  background:radial-gradient(closest-side,rgba(120,195,212,.38),rgba(80,150,168,.12) 50%,transparent)}
.pe-num .pe-w{display:inline-block;font-size:150px;font-weight:700;letter-spacing:.02em}
.pe-num .ln.lt{margin-top:14px}
.pe-or>span{color:var(--a1)}
.pe-code{font-family:var(--type);font-weight:700;font-size:34px;letter-spacing:.32em;color:var(--acc)}
.pe-code>span{color:var(--acc)}
.tag.left .pchip.col{align-items:flex-end}
.k.pe-blk{transform-origin:100% 50%}
.pe-name i{color:var(--orbit)}
.lt.pe-sc{font-size:48px}
`);
  // lead-petal bearing (deg) — the same timings are used by music.py (a soft close and a bloom per change, no ticks).
  // After the band reveal the closed bud keeps turning (no stop: its speed carries over and eases down) onto the first
  // example type and opens there. Every change is the same move: the flower turns 202.5° at an even speed (short
  // ramps at both ends) while it closes into the bud and opens again as the next type, the swap at the smallest bud.
  // The three stops are 202.5° apart, so both changes look alike; each example holds ≈ 2.1 s for its caption. It
  // lands on the middle of your type's sector (OFF = (index of DIMV + .5) × 22.5).
  const OFF = 11.25, MOVE = 3.6, RAMP = .22;
  const typeDeg = (code) => (CODES.indexOf(code) + .5) * 22.5;
  // [code, beat it arrives (fully open), bearing]; it leaves a stop MOVE beats before the next arrival
  const STOPS = [['SIMT', 33.9, typeDeg('SIMT')], ['DPMV', 39.9, typeDeg('DPMV') + 360], ['DIMV', 45.9, typeDeg('DIMV') + 720]];
  // later beats of this scene move with the longer browse (X), the longer reveal (Y) and the longer strengths card (Z)
  const X = STOPS[2][1] - 43.4, Y = X + 1.5, Z = Y + 1;
  // 0..1 progress with an even speed between two short eased ramps (velocity: a trapezoid)
  const even = (u) => { const r = RAMP, v = 1 / (1 - r); if (u <= 0) return 0; if (u >= 1) return 1; if (u < r) return v * u * u / (2 * r); if (u > 1 - r) return 1 - v * (1 - u) * (1 - u) / (2 * r); return v * (u - r / 2); };
  // 4b: before the browse the closed bud runs once round at an even speed (from 210° back to 210°), revealing the band
  const N0 = 27.2, N1 = 29.4, SW0 = N1;
  const needle4b = (b) => -510 + 360 * clamp((b - N0) / (N1 - N0));
  // { deg, k: the stop shown (index), open: 0 bud .. 1 open, twist }
  function browse(b) {
    if (b < STOPS[0][1]) {                                   // the first turn: a Hermite curve from the reveal's speed to rest
      const p0 = -150 + OFF, p1 = STOPS[0][2], T = STOPS[0][1] - SW0, v0 = 360 / (N1 - N0) * T, u = clamp((b - SW0) / T);
      const deg = (2 * u ** 3 - 3 * u * u + 1) * p0 + (u ** 3 - 2 * u * u + u) * v0 + (-2 * u ** 3 + 3 * u * u) * p1;
      return { deg, k: 0, open: E.sine(lp(b, STOPS[0][1] - 1.8, 1.8)), twist: 0 };
    }
    for (let i = 1; i < STOPS.length; i++) {
      const at = STOPS[i][1], go = at - MOVE;
      if (b < go) return { deg: STOPS[i - 1][2], k: i - 1, open: 1, twist: 0 };
      if (b < at) {
        const u = (b - go) / MOVE, deg = STOPS[i - 1][2] + (STOPS[i][2] - STOPS[i - 1][2]) * even(u);
        return { deg, k: u < .5 ? i - 1 : i, open: 1, twist: 0, wave: { a: CODES.indexOf(STOPS[i - 1][0]), b: CODES.indexOf(STOPS[i][0]), u } };
      }
    }
    return { deg: STOPS[STOPS.length - 1][2], k: STOPS.length - 1, open: 1, twist: 0 };
  }
  const needleAt = (b) => (b < SW0 ? needle4b(b) + OFF : browse(b).deg);
  // the Agent layers turn with the flower: a slow drift, plus one even turn (each layer by its own CP.SPIN × SPINK)
  // exactly while the petals fold and open, so the whole dial changes with the type
  const SPINK = 14;
  const spinAt = (b) => .12 * (b - 27) + SPINK * (even(lp(b, STOPS[0][1] - 1.8, 1.8)) + STOPS.slice(1).reduce((v, x) => v + even(lp(b, x[1] - MOVE, MOVE)), 0));

  const D0 = compassData(), ME = D0.me, STR = 'DIMV'.split('').map((x, i) => axisOf(ME.v, i));

  /* ---------- 4a: three words rise out of the vanishing point (b21.2–25.6): what Orbit reads, not how much of it ---------- */
  const NUMS = [['会话', '逐个读取'], ['消息', '逐条理解'], ['操作', '逐步还原']];
  NUMS.forEach((n, i) => {
    const x = 440 + i * 520, b0 = 21.4 + i * .4;
    txt(b0, i ? 25.4 : 25.2, [['', '<span class="pe-w">' + n[0] + '</span>'], ['lt', n[1]]], { x, y: 520, align: 'c' }, {
      tag: 'pnum' + i, style: 'line-height:1',
      anim: (el, tl, life, t) => {
        const b = t / BEAT, p = E.out(lp(b, b0, .8));
        el.classList.add('pe-num');
        el.querySelectorAll('.ln').forEach((x) => { x.style.overflow = 'visible'; });
        // out: 消息 and 操作 blur away; 会话 snaps off as its particles take over
        const q = i ? 1 - E.inOut(lp(b, 24.6, .8)) : 1 - lp(b, 25.0, .12);
        const u = el.querySelector('.ln.lt'); if (u) u.style.opacity = (i ? 1 : 1 - E.out(lp(b, 24.7, .3))).toFixed(3);
        el.style.transform = 'translate(-50%,-50%) translate(' + ((960 - x) * (1 - p)).toFixed(1) + 'px,' + (20 * (1 - p)).toFixed(1) + 'px) scale(' + lerp(.3, 1, p).toFixed(4) + ')';
        el.style.opacity = (Math.min(1, p * 1.6) * q).toFixed(3);
        const bl = (1 - p) * 10 + (i ? (1 - q) * 10 : 0);
        el.style.filter = bl > .05 ? 'blur(' + bl.toFixed(1) + 'px)' : 'none';
      }
    });
  });
  txt(21.8, 25.0, [['eb', '本机读取 · 多种 Agent']], { x: 960, y: 360, align: 'c' }, { anim: K.blurIn({ spread: .5, out: .5 }) });

  /* ---------- 4b: 会话 → particles on a tilted orbit → the compass (b24.9–30) ---------- */
  const W0 = decks[0].W, AGID = W0.eval('AG').map((a) => a.id), HEX = ['#e2602b', '#2a78d6', '#009f6b', '#c27800', '#d0658f'];
  const SES = D0.L.map((s) => ({ ag: AGID.indexOf(s.a), deg: D0.cls.by[s.id].a }))
    .sort((a, b) => a.ag - b.ag || a.deg - b.deg);
  const PT = SES.map((s, i) => {
    const frac = (((s.deg - 210 - OFF) % 360) + 360) % 360 / 360;
    return { c: s.ag, beta: s.deg, rr: CP.R0 + CP.RH * (.15 + .6 * hash01(i, 21)), ro: 418 + 34 * hash01(i, 22), ph: hash01(i, 23) * 360, w: 70 + 30 * hash01(i, 24), land: N0 + (N1 - N0) * frac, dl: hash01(i, 25) * .18 };
  });
  // compass point (800 × 800 frame) → stage px through deck 2's camera (same maths as the CSS: perspective · Z · X · Y · Z)
  function proj(px, py) {
    const C = decks[2].C, R = Math.PI / 180;
    let X = (px - C.x) * C.s, Y = (py - C.y) * C.s, Z = 0, a = C.rz * R;
    [X, Y] = [X * Math.cos(a) - Y * Math.sin(a), X * Math.sin(a) + Y * Math.cos(a)];
    a = C.ry * R; [X, Z] = [X * Math.cos(a) + Z * Math.sin(a), -X * Math.sin(a) + Z * Math.cos(a)];
    a = C.rx * R; [Y, Z] = [Y * Math.cos(a) - Z * Math.sin(a), Y * Math.sin(a) + Z * Math.cos(a)];
    Z += C.z; const w = 1 - Z / 2400;
    return [C.ax + X / w, C.ay + Y / w];
  }
  // where particle i is on the compass plane at beat b (compass px), or null before it orbits
  function onDial(P, b) {
    const s0 = P.land - .9;
    const orb = (bb) => P.ph + P.w * (bb - 25);
    if (b < s0) { const a = orb(b); return [cpt(P.ro, a), 1]; }
    if (b < P.land) {
      const q = (b - s0) / .9, A0 = orb(s0); let Ab = P.beta; while (Ab < A0 + 70) Ab += 360;
      const a = A0 + P.w * .9 * q * (1 - q) + (Ab - A0) * E.inOut(q), r = lerp(P.ro, P.rr, E.inOut(q));
      return [cpt(r, a), 1];
    }
    return [cpt(P.rr, P.beta), 2];
  }
  // glyph points of the first word (会话): sampled from it as it is on screen when it breaks
  let GLY = null;
  function glyphs() {
    if (GLY) return GLY;
    const f = fx.find((x) => x.tag === 'pnum0'), o = f && f.el && f.el.querySelector('.pe-w');
    const st = stage.getBoundingClientRect(), z = st.width / 1920;
    let box = [440 - 150, 400, 300, 150];
    if (o) { const r = o.getBoundingClientRect(); box = [(r.left - st.left) / z, (r.top - st.top) / z, r.width / z, r.height / z]; }
    const cv = document.createElement('canvas'); cv.width = Math.ceil(box[2]); cv.height = Math.ceil(box[3]);
    const g = cv.getContext('2d'); g.fillStyle = '#fff'; g.textBaseline = 'middle'; g.textAlign = 'center';
    g.font = '700 ' + Math.round(box[3]) + 'px ' + getComputedStyle(document.body).fontFamily;
    g.fillText(NUMS[0][0], cv.width / 2, cv.height * .54);
    const px = g.getImageData(0, 0, cv.width, cv.height).data, ins = [];
    for (let y = 0; y < cv.height; y += 3) for (let x = 0; x < cv.width; x += 3) if (px[(y * cv.width + x) * 4 + 3] > 128) ins.push([box[0] + x, box[1] + y]);
    GLY = PT.map((P, i) => ins.length ? ins[Math.floor(hash01(i, 31) * ins.length)] : [box[0] + box[2] * hash01(i, 32), box[1] + box[3] * hash01(i, 33)]);
    GLY.c = [box[0] + box[2] / 2, box[1] + box[3] / 2];
    return GLY;
  }
  let CV = null, SPR = null;
  function canvas() {
    if (CV) return CV;
    CV = document.createElement('canvas'); CV.className = 'pe-cv'; stage.insertBefore(CV, fxEl);
    const dpr = window.devicePixelRatio || 1; CV.width = 1920 * dpr; CV.height = 1080 * dpr; CV.dpr = dpr;
    SPR = HEX.map((h) => { const c = document.createElement('canvas'); c.width = c.height = 48; const g = c.getContext('2d'), gr = g.createRadialGradient(24, 24, 0, 24, 24, 24); gr.addColorStop(0, h); gr.addColorStop(.25, h + 'cc'); gr.addColorStop(1, h + '00'); g.fillStyle = gr; g.fillRect(0, 0, 48, 48); return c; });
    return CV;
  }
  function stagePos(P, i, b) {
    const G = glyphs(), b0 = 25.0 + P.dl, q = lp(b, b0, .85);
    if (b < b0) return [G[i][0], G[i][1]];
    const d = onDial(P, b), tgt = proj(d[0][0], d[0][1]);
    if (q >= 1) return tgt;
    const dx = G[i][0] - G.c[0], dy = G[i][1] - G.c[1], L = Math.hypot(dx, dy) || 1, k = 120 * Math.sin(Math.PI * Math.min(1, q * 1.4)) * (.6 + .8 * hash01(i, 34));
    const out = [G[i][0] + dx / L * k, G[i][1] + dy / L * k], e = E.inOut(q);
    return [lerp(out[0], tgt[0], e), lerp(out[1], tgt[1], e)];
  }
  txt(24.95, 30.4, [['', '']], { x: 0, y: 0 }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT, cv = canvas(), g = cv.getContext('2d');
      g.setTransform(cv.dpr, 0, 0, cv.dpr, 0, 0); g.clearRect(0, 0, 1920, 1080);
      if (b < 25.0 || b > 30.3) return;
      g.globalCompositeOperation = 'lighter';
      PT.forEach((P, i) => {
        const pos = stagePos(P, i, b), prev = stagePos(P, i, b - .025);
        let a = 1, r = 3.4;
        if (b >= P.land) { const f = lp(b, P.land, .7); a = 1 - E.in(f); r = 3.4 + 2.4 * (1 - f) * (f < .15 ? f / .15 : 1); a *= .8; }
        if (a <= .01) return;
        g.globalAlpha = a * .55; g.strokeStyle = HEX[P.c]; g.lineWidth = 2.6; g.lineCap = 'round';
        g.beginPath(); g.moveTo(prev[0], prev[1]); g.lineTo(pos[0], pos[1]); g.stroke();
        g.globalAlpha = a; g.drawImage(SPR[P.c], pos[0] - r * 3, pos[1] - r * 3, r * 6, r * 6);
        g.globalAlpha = a * .9; g.fillStyle = '#fff'; g.beginPath(); g.arc(pos[0], pos[1], r * .42, 0, 7); g.fill();
      });
      g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    }
  });
  txt(25.3, 26.5, [['lt', '每个会话，落到它的方位']], { x: 960, y: 760, align: 'c' }, { anim: K.blurIn({ spread: .35, out: .4 }) });

  // the camera: the dial starts as the tilted orbit (rx 76°, rz −8°: an ellipse about 520 × 120 px) and flips face-on
  tween(2, 24.9, 0, { x: 400, y: 400, s: 1.2, ax: 960, ay: 540, rx: 76, ry: 0, rz: -8, z: 0, o: 1, bl: 0 });
  tween(2, 25.6, 1.8, () => framing(2, 'all', [1180, 540, 820, 820]), E.inOut);
  tween(2, 27.6, 9, () => ({ s: decks[2].C.s * 1.035 }), E.sine);

  /* ---------- 4c–4e: the compass, one draw per frame (b24.9–57.5) ---------- */
  // the bud closes and turns with the band reveal (b27.2–29.4), opens as the sweep starts, and hands over to your own
  // flower when it lands (b44)
  drive(2, 24.9, 61.5 + Z, (p, b) => {
    const deg = needleAt(b), w = b < SW0 ? null : browse(b);
    drawCompass({
      deg, mine: E.inOut(lp(b, 44 + X, 1.4)), grow: w ? w.open : 0, fi: w ? CODES.indexOf(STOPS[w.k][0]) : null, twist: w ? w.twist : 0, wave: w && w.wave,
      sweep: b < 30 ? clamp((needle4b(b) + 510) / 360) : 1, sweepFrom: 210 + OFF,
      orbit: (b - 27) * 28 + deg * .3, spin: spinAt(b), settle: E.inOut(lp(b, 44.8 + X, 1.6)),
      needle: E.out(lp(b, 26.9, .5)), core: E.out(lp(b, 26.7, 1)), dial: E.out(lp(b, 25.7, .9)),
      ticks: E.inOut(lp(b, 26.4, 1.2)), trace: lp(b, 26.4, 1.2), traceA: 1 - E.out(lp(b, 27.5, .5))
    });
  });

  /* 4b text: 01 · 人格分析 / 16 种协作人格 / 4 个维度 · 8 个极 (left, compass on the right). It comes in from b27.0,
     while the bezel flips up and the left half is empty, so all of it is readable from b28.1 to b33.2 (2.5 s) */
  txt(27.0, 44.2 + X, [['eb', '01 · 人格分析']], { x: 150, y: 300 }, { outB: .6 });
  txt(27.1, 32.4, [['hv sv', '16 种'], ['hv sv', '协作人格']], { x: 150, y: 490 }, { st: .2, inB: .8, outB: .5 });
  txt(27.4, 32.4, [['lt acc', '4 个维度 · 8 个极']], { x: 150, y: 680 }, { anim: K.blurIn({ spread: .4, out: .5 }) });

  /* 4c: one caption stays through the browse (name, code, the first clause of the app's one-liner). On each change the
     four letters roll like a split-flap board — every column at the same even speed through D S I P M F V T, at least
     once round, so the columns stop one after another — while the name and the line swap at the change's midpoint.
     It leaves just after your type lands, before the dial moves left for the reveal. */
  const FLAP = 'DSIPMFVT', STEP = .2;                     // beats per letter
  const flapPos = (b, c) => {                             // column c: position on the FLAP drum (fractional) at beat b
    let pos = FLAP.indexOf(STOPS[0][0][c]);
    for (let i = 1; i < STOPS.length; i++) {
      const go = STOPS[i][1] - MOVE + .1, to = FLAP.indexOf(STOPS[i][0][c]), dist = 8 + ((to - pos % 8) + 8) % 8;
      if (b <= go) break;
      pos = pos % 8 + Math.min(dist, (b - go) / STEP);
    }
    return pos % 8;
  };
  // the name on its own letterboard: each character cell rolls (same even speed) through a few other type-name
  // characters to the next name's character, cell c passing 5 + c of them, so the cells stop left to right
  const NSTEP = .18, NPOOL = [...new Set(Object.values(D0.TYPES).map((t) => t[0]).join('').split(''))];
  const nameOf = (i) => [...D0.TYPES[STOPS[i][0]][0]];
  const nameStrip = (i, c) => {                           // switch i (1, 2): cell c's characters, from the old name to the new
    const fill = Array.from({ length: 5 + c }, (_, j) => NPOOL[Math.floor(hash01(i * 7 + c, 40 + j) * NPOOL.length)]);
    return [nameOf(i - 1)[c] || '', ...fill, nameOf(i)[c] || ''];
  };
  function nameFlap(x, c, b) {
    let i = 0; for (let s = 1; s < STOPS.length; s++) if (b >= STOPS[s][1] - MOVE + .1) i = s;
    const strip = i ? nameStrip(i, c) : [nameOf(0)[c] || ''], key = i + ':' + c;
    if (x.dataset.key !== key) { x.dataset.key = key; x.innerHTML = strip.map((ch) => '<i>' + (ch || '&nbsp;') + '</i>').join(''); }
    const pos = i ? Math.min(strip.length - 1, (b - (STOPS[i][1] - MOVE + .1)) / NSTEP) : 0;
    x.style.transform = 'translateY(' + (-pos * 1.2).toFixed(4) + 'em)';
  }
  css(`.ln>span.pe-nb{display:inline-flex}
.pe-nc{display:inline-block;width:1em;height:1.2em;overflow:hidden;position:relative;vertical-align:top}
.pe-ns{position:absolute;left:0;top:0;width:100%;display:flex;flex-direction:column;will-change:transform}
.pe-ns i{display:block;height:1.2em;line-height:1.2em;text-align:center;font-style:normal;background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}`);
  const stopAt = (b) => { let k = 0; for (let i = 1; i < STOPS.length; i++) if (b >= STOPS[i][1] - MOVE / 2) k = i; return k; };
  const swapQ = (b) => { for (let i = 1; i < STOPS.length; i++) { const m = STOPS[i][1] - MOVE / 2; if (Math.abs(b - m) < .6) return Math.abs(b - m) / .6; } return 1; };
  const drum = FLAP + FLAP[0];
  const flapHTML = [0, 1, 2, 3].map((c) => '<span class="pe-fc"><span class="pe-fs" data-c="' + c + '">' + drum.split('').map((x) => '<i>' + x + '</i>').join('') + '</span></span>').join('');
  css(`.pe-flap{display:inline-flex;gap:.22em}
.pe-fc{display:inline-block;width:.86em;height:1.2em;overflow:hidden;position:relative;vertical-align:top}
.pe-fs{position:absolute;left:0;top:0;width:100%;display:flex;flex-direction:column;will-change:transform}
.pe-fs i{display:block;height:1.2em;line-height:1.2em;text-align:center;font-style:normal;color:var(--acc)}
.pe-code.pe-fl{letter-spacing:0}
.pe-sw2{display:inline-block;will-change:opacity,filter}`);
  txt(STOPS[0][1] - .35, STOPS[2][1] + 1.4, [['lt dim', '16 种之一'], ['hv', '<span class="pe-nb">' + [0, 1, 2, 3].map((c) => '<span class="pe-nc"><span class="pe-ns" data-c="' + c + '"></span></span>').join('') + '</span>'], ['pe-code pe-fl', '<span class="pe-flap">' + flapHTML + '</span>'], ['lt', '<span class="pe-sw2 pe-ol"></span>']], { x: 150, y: 530 }, {
    st: .08, inB: .6, outB: .5,
    tick: (el, tl, life, t) => {
      const b = t / BEAT, k = stopAt(b), T = D0.TYPES[STOPS[k][0]], q = swapQ(b);
      const ol = el.querySelector('.pe-ol');
      if (ol && ol.dataset.k !== String(k)) { ol.dataset.k = String(k); ol.textContent = T[2].split('，')[0]; }
      if (ol) { ol.style.opacity = q.toFixed(3); ol.style.filter = q < .98 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none'; }
      el.querySelectorAll('.pe-ns').forEach((x) => nameFlap(x, +x.dataset.c, b));
      el.querySelectorAll('.pe-fs').forEach((x) => { x.style.transform = 'translateY(' + (-flapPos(b, +x.dataset.c) * 1.2).toFixed(4) + 'em)'; });
    }
  });

  /* ---------- 4e: settle, glow, reveal (b44–52) ---------- */
  const glow = document.createElement('div'); glow.className = 'pe-glow'; stage.insertBefore(glow, glowEl.nextSibling);
  every(43.4 + X, 46.2 + X, (p, b) => {
    const c = proj(400, 400), q = b < 44 + X ? E.out(lp(b, 43.6 + X, .4)) : 1 - E.inOut(lp(b, 44.4 + X, 1.3));
    glow.style.transform = 'translate(' + c[0].toFixed(1) + 'px,' + c[1].toFixed(1) + 'px) scale(' + (decks[2].C.s * lerp(.85, 1.05, q)).toFixed(3) + ')';
    glow.style.opacity = (q * .9).toFixed(3);
  });
  tween(2, 45.0 + X, 1.6, () => framing(2, 'all', [640, 540, 860, 860]), E.inOut);
  tween(2, 46.7 + X, 6.8 + Y - X, () => ({ s: decks[2].C.s * 1.03 }), E.sine);
  // the right block (right-aligned at x = 1800); during b53.5–54.3 it shrinks into the top-right eyebrow
  const shrink = (y) => (el, tl, life, t) => {
    const b = t / BEAT, q = E.inOut(lp(b, 53.5 + Y, .8)), sc = lerp(1, .22, q), dy = (y - 90) * (sc - 1);
    el.style.transform = 'translate(-100%,-50%) translate(0,' + dy.toFixed(1) + 'px) scale(' + sc.toFixed(4) + ')';
    el.style.transformOrigin = '100% 50%';
    if (q > 0) { el.style.opacity = (1 - E.in(q)).toFixed(3); el.style.filter = q > .02 ? 'blur(' + (q * 6).toFixed(1) + 'px)' : 'none'; }
  };
  const BLK = { x: 1800, align: 'r' };
  const SWBOX = [1320, 560, 850, 960], EBY = 90;   // 4f: the card's screen box and the top-right eyebrow's y
  txt(45.2 + X, 54.3 + Y, [['eb', '你的协作人格 · YOUR TYPE']], Object.assign({ y: 300 }, BLK), { anim: K.all(K.rise({ out: .01 }), shrink(300)) });
  txt(45.4 + X, 54.3 + Y, [['xl sv tcode', ME.code]], Object.assign({ y: 432 }, BLK), { anim: K.all(K.centerOut({ step: .12, dur: .4, out: 0 }), shrink(432)) });
  txt(46.4 + X, 54.3 + Y, [['md pe-name', ME.zh + ' <span class="display"><i>' + ME.en + '</i></span>']], Object.assign({ y: 590 }, BLK), { anim: K.all(K.rise({ out: .01 }), shrink(590)) });
  // decode with a narrow start spacing: the line is right-aligned, so its extra width grows left towards the dial
  // the first clause of the app's one-liner for the type (TYPES[code][2])
  txt(47.0 + X, 54.3 + Y, [['lt', ME.line.split('，')[0] + '。']], Object.assign({ y: 680 }, BLK), { anim: K.all(K.decode({ step: .05, dur: .4, out: 0, from: .15 }), shrink(680)) });
  txt(47.6 + X, 54.3 + Y, [['lt pe-sc', STR.map((a, i) => CPD.AXES[i][a.letter === CPD.AXES[i].L ? 'Ln' : 'Rn']).join(' · ')]], Object.assign({ y: 780 }, BLK), { anim: K.all(K.blurIn({ spread: .4, out: 0 }), shrink(780)) });
  // leaves by b60.2, before the opening portal (centred on 「建议 →」) reaches the top right
  txt(53.9 + Y, 60.2 + Z, [['eb', ME.code + ' · ' + ME.zh]], { x: 1800, y: EBY, align: 'r' }, { inB: .7, outB: .5 });

  /* ---------- 4f: 优势与盲点 → 「建议 →」 → portal (b53.5–61.4; rows every .45 beat, the card held ≈ 1.5 s before the click) ---------- */
  const swCard = (D) => { const s = D.querySelector('.pe-sw'); return s && s.closest('.card'); };
  const recLnk = (D) => { const r = [...D.querySelectorAll('.pe-sw .pe-swr')].find((e) => e.textContent.includes('工具 / 环境失败')); return r && r.querySelector('.lnk'); };
  // scroll the card into the copy's own view first: solo()'s scrollIntoView would otherwise also scroll the promo stage
  const unscroll = () => { for (const e of [document.scrollingElement, stage, ...document.querySelectorAll('.hole, .cam')]) if (e && (e.scrollTop || e.scrollLeft)) { e.scrollTop = 0; e.scrollLeft = 0; } };
  at(50.0 + Y, () => {
    const a = app(1); a.go('persona'); const c = swCard(a.D), sc = a.D.getElementById('content');
    if (c && sc) sc.scrollTop += c.getBoundingClientRect().top - 120;
    solo(1, swCard); unscroll();
  });
  every(50.0 + Y, 61.6 + Z, unscroll);
  // the card in its own px: top, left, width, and where each row ends (the card is stretched by its grid row, so its
  // lower part is empty: the film frames and shows only the card down to the last row plus the card's own padding)
  const PADB = 16;
  const swGeo = (D) => {
    const c = swCard(D), rows = c ? [...c.querySelectorAll('.pe-sw .pe-swr')] : [];
    if (!c || !rows.length) return null;
    const r = c.getBoundingClientRect(), top = (e) => e.getBoundingClientRect().top - r.top, bot = (e) => e.getBoundingClientRect().bottom - r.top;
    return { c, r, rows, head: top(rows[0]) - 6, bots: rows.map(bot), tops: rows.map(top), full: bot(rows[rows.length - 1]) + PADB };
  };
  // frame the card as it is when complete (header to last row + padding) into box [cx, cy, w, h]
  const frameSW = (box) => {
    const g = swGeo(decks[1].D); if (!g) return framing(1, swCard, box);
    const [cx, cy, w, h] = box, s = Math.min(w / g.r.width, h / g.full);
    return { x: g.r.left + g.r.width / 2, y: g.r.top + g.full / 2, s, ax: cx, ay: cy, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0 };
  };
  // the tags sit beside their own group of rows (the card's left edge, the rows' height), not beside the whole card
  const swGroup = (i0, i1) => (D) => {
    const g = swGeo(D); if (!g) return null;
    return { getBoundingClientRect: () => ({ left: g.r.left, right: g.r.right, width: g.r.width, top: g.r.top + g.tops[i0], bottom: g.r.top + g.bots[i1], height: g.bots[i1] - g.tops[i0] }) };
  };
  tween(2, 53.5 + Y, 1.2, () => framing(2, 'all', [360, 560, 480, 480]), E.inOut);
  tween(1, 53.9 + Y, .9, () => frameSW(SWBOX), E.quart, (T) => ({ ay: T.ay + 260, z: -420, rx: 24, s: T.s * .94, o: 0, bl: 8 }));
  tween(1, 54.8 + Y, 4.8 + Z - Y, () => ({ s: decks[1].C.s * 1.012 }), E.sine);
  // rows one by one from b53.0, every 0.3 beat; ✓ / ⚠ icons pop. The card grows with them: it is clipped just below the
  // last row that has started to come in (plus the card's padding), like a reply card that gets longer line by line
  drive(1, 49.9 + Y, 61.6 + Z, (p, b, D) => {
    const g = swGeo(D);
    if (g) {
      let bot = g.head;
      g.bots.forEach((y, i) => { bot = lerp(bot, y, E.out(lp(b, 54.5 + Y + i * .45, .3))); });
      const cut = b >= 61.55 + Z ? 0 : Math.max(0, g.r.height - bot - PADB);
      g.c.style.clipPath = cut > .5 ? 'inset(0 0 ' + cut.toFixed(1) + 'px 0 round 0 0 12px 12px)' : '';
    }
    const rows = D.querySelectorAll('.pe-sw .pe-swr');
    rows.forEach((r, i) => {
      const q = E.out(lp(b, 54.5 + Y + i * .45, .4)), ic = r.querySelector('svg');
      r.style.opacity = Math.min(1, q * 1.5).toFixed(3); r.style.transform = 'translateX(' + ((1 - q) * 26).toFixed(1) + 'px)';
      if (ic) { const k = lp(b, 54.55 + Y + i * .45, .3); ic.style.transform = 'scale(' + (k >= 1 ? 1 : lerp(.2, 1, ease.back(k))).toFixed(3) + ')'; ic.style.transformOrigin = '50% 50%'; }
    });
    const sep = D.querySelector('.pe-sw .pe-swsep'); if (sep) sep.style.opacity = lp(b, 55.8 + Y, .3).toFixed(3);
    const l = recLnk(D); if (l) l.style.textDecoration = b >= 59.15 + Z && b < 61.6 + Z ? 'underline' : '';
  });
  // tags scale about their anchor (the engine's left-side transform-origin drifts when the camera zoom is far from 1)
  const anchor0 = (el) => { el.style.transformOrigin = '0 0'; };
  tag(1, 54.6 + Y, 60.4 + Z, swGroup(0, 2), 'left', [['lt', '看清优势']], { at: .5, gap: 34, anim: K.all(mask(.14, .9, .5), anchor0) });
  tag(1, 55.9 + Y, 60.4 + Z, swGroup(3, 5), 'left', [['lt pe-or', '也看清盲点'], ['lt pe-or', '每个都有解法']], { at: .5, gap: 34, anim: K.all(mask(.14, .9, .5), anchor0) });
  clickAt(1, 59.6 + Z, recLnk, () => {}, { bloom: 'var(--a1)' });
  portal(0, 59.7 + Z, 1.3, () => elXY(1, recLnk), 2300, E.in, .6, 'rgba(226,96,43,.95)');
  // the door cuts through decks 1 and 2 as well (they sit above deck 0), and they drift forward and blur away
  let PC = null;
  every(59.1 + Z, 61.5 + Z, (p, b) => {
    if (!PC) PC = elXY(1, recLnk);
    const q = clamp((b - 59.7 - Z) / 1.3), r = 2300 * E.in(q);
    for (const h of ['#hole1', '#hole2']) {
      const el = $(h), m = b < 59.7 + Z || b >= 61.15 + Z ? '' : 'radial-gradient(circle at ' + PC[0].toFixed(1) + 'px ' + PC[1].toFixed(1) + 'px,transparent ' + r.toFixed(1) + 'px,#000 ' + (r + 2).toFixed(1) + 'px)';
      el.style.maskImage = m; el.style.webkitMaskImage = m;
    }
  });
  tween(1, 59.8 + Z, 1.25, () => ({ s: decks[1].C.s * 1.12, bl: 10, o: 0 }), E.in);
  tween(2, 59.8 + Z, 1.25, () => ({ s: decks[2].C.s * 1.1, bl: 10, o: 0 }), E.in);
  // leave deck 1 tidy for whoever uses it next
  at(61.6 + Z, () => { const D = decks[1].D, c = swCard(D); if (c) c.style.clipPath = ''; D.querySelectorAll('.pe-sw .pe-swr, .pe-sw .pe-swsep').forEach((r) => { r.style.opacity = ''; r.style.transform = ''; }); });
});
