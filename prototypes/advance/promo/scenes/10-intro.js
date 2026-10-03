/* 10-intro 1a–1c（b0–12.6） — STORYBOARD.md v17「1a」「1b」「1c」与 K2 H0–H2.
   1a 现在，每天无数人在使用 AI Agent（b0–4.2）：5 个 AGD 点依次弹出到 scatterA，两行字逐词落下，点随字轻呼吸。
   1b 从想法到交付（b4–8.8）：点收拢到 arc，输入框打字发送 3 次 + 各点自己冒出 prompt 气泡；b6.6 起 12 个 App 图标
      从 5 个点和输入框中心沿弧线喷出，落到椭圆光环（960, 520, rx 760, ry 380）上缓慢公转。
   1c We Are Redesigning Everything（b8.6–12.6）：点退到 scatterC；两行大字逐词硬切，每个词把光环上最近的 3 个图标
      吸近 40px 再弹回；b10.3 起图标转向朝外并缩到 .7，b11.8 沿径向飞出画面。b12.6 前本场景的图标与文字全部清空，
      b12.4 起的 AGD key 归 15-redesign。
   图标画在 #agdBack（AGD.back，在 Agent 点之下），所以它们是从点和输入框「后面」迸出来的。 */
scene('10-intro', () => {
  css(`
.ln.lt.in-now{color:rgba(255,255,255,.6)}
.in-big{font-size:120px}
.in-t1{font-size:132px}
.in-w1{font-size:120px}
.in-ev{font-size:150px;color:var(--a1)}
`);
  const D2R = Math.PI / 180;

  /* ---------- 1a（b0–4.2） ---------- */
  // H0: pop in one after another every .25 beat (E.back over .3 beats) — b0.2 … b1.5
  AGD.key(0.2, 'pts', { pts: AGD.P.scatterA, r: 40, dur: .01, stag: .25 });
  // 1a.2: 「现在，」 blurs in at b0.5; the headline adds a word on b0.9 / 1.4 / 1.9 / 2.4 (hard cut, refits to 1600)
  // 1a.3: both lines leave b3.6–4.2 — fade + blur, drifting up 60 px
  const up60 = (tl, life) => -60 * E.inOut(clamp((tl - (life - BB(.6))) / BB(.6)));
  txt(0.5, 4.2, [['lt in-now', '现在，']], { x: 960, y: 430, align: 'c' }, {
    anim: K.blurIn({ out: .6 }),
    tick: (el, tl, life) => { el.style.transform = 'translate(-50%,-50%) translateY(' + up60(tl, life).toFixed(1) + 'px)'; }
  });
  txt(0.5, 4.2, [['hv sv in-big', '<span class="w">每天</span><span class="w">无数人</span><span class="w">在使用</span><span class="w"> AI Agent</span>']],
    { x: 960, y: 540, align: 'c' }, { anim: K.words({ at: [.4, .9, 1.4, 1.9], fit: 1600, shrink: [[3.1, 1, 0, -60, .6]], out: .6 }) });
  // every dot that is already out breathes (1.06, .4 beats) as each word lands
  for (const w of [0.9, 1.4, 1.9, 2.4]) for (let i = 0; i < 5; i++) if (0.2 + .25 * i + .3 <= w) AGD.pulse(i, w + .03 * i, 1.06, .4);
  // H1: radial gather onto the arc above the input box (b3.8 → 4.94)
  AGD.key(3.8, 'pts', { pts: AGD.P.arc, r: 40, dur: .9, stag: .06 });

  /* ---------- 1b（b4–8.8） ---------- */
  const c = AGD.chat(4.0, 7.2, { x: 960, y: 760, w: 980 });
  txt(4.1, 7.0, [['hv sv in-t1', '从想法到交付']], { x: 960, y: 250, align: 'c' });   // masked rise; leaves b6.4–7.0, up ≈ 40 px
  // A bubble above a dot sits at dy = −r − 18; when a second one arrives on the same dot the older one is pushed up a slot.
  // gm's sent prompt hangs below it instead (pushing gm's own bubble up would run into the headline).
  const ABOVE = -40 - 18, SLOT = 72;
  const pushUp = (tp) => (b) => ABOVE - SLOT * E.inOut(clamp((b - tp + .1) / .3));   // clears the slot as the new one pops at tp
  c.type(4.4, '做一个记账 App', .55); c.send(5.0, 0, { until: 6.9, dy: pushUp(6.3) });
  c.type(5.1, '写份路演稿', .4); c.send(5.55, 2, { until: 7.0, dy: 40 + 14 });
  c.type(5.65, '生成产品官网', .45); c.send(6.15, 4, { until: 7.3 });
  // the dots' own prompts (kind 'ask', ≈ 1.2 beats; the late ones retract in turn b6.8–7.3 as the icons burst)
  AGD.bubble(1, 4.8, 6.0, '做个数据看板');
  AGD.bubble(2, 5.3, 6.5, '画一套图标');
  AGD.bubble(3, 5.8, 7.05, '写个爬虫');
  AGD.bubble(4, 6.1, 7.15, '整理会议纪要', { dy: pushUp(6.3) });
  AGD.bubble(0, 6.3, 7.25, '做个小游戏');
  for (const [i, b] of [[0, 5.15], [1, 4.8], [2, 5.3], [2, 5.7], [3, 5.8], [4, 6.1], [4, 6.3], [0, 6.3]]) AGD.glow(i, b, b + .5, .8);

  /* ---------- 1b.3 – 1c: the App icons ---------- */
  // 12 rounded tiles (88 px, dark glass, white line glyphs drawn here — no third-party marks), in ring order θ = 30k.
  // Phase: at b≈10.5 the two top slots straddle 12 o'clock, so gm's dot (scatterC 960, 110) never sits on an icon.
  const G = [
    'M-10-16h13l9 9v23h-22z M3-16v9h9 M-5-4h5 M-5 3h12 M-5 10h12',                                             // document
    'M-17-12h34v22h-34z M0 10v6 M-7 16h14 M-4-6.5l9 5.5-9 5.5z',                                                 // slides
    'M-7-11l-11 11 11 11 M7-11l11 11-11 11 M3.5-16l-7 32',                                                      // code
    'M0-16a16 16 0 1 0 .01 0z M-16 0h32 M0-16c-9 9-9 23 0 32 M0-16c9 9 9 23 0 32',                               // web
    'M-17 15h34 M-11 11v-9 M-3.5 11v-19 M4 11v-13 M11.5 11v-24',                                                // bar chart
    'M-17-13h34v26h-34z M-17 9l10-10 9 9 6-5 9 8 M8-5.5a3.5 3.5 0 1 0 .01 0z',                                  // image
    'M-16-13h32v26h-32z M-16-4h32 M-16 5h32 M-5-13v26 M6-13v26',                                                // table
    'M-17-13h34v26h-34z M-10-5l6 5-6 5 M1 6h9',                                                                  // terminal
    'M-17-11h34v22h-34z M-17-11l17 13 17-13',                                                                    // mail
    'M-16-11h32v26h-32z M-16-3h32 M-9-16v8 M9-16v8 M-8 6h.01 M0 6h.01 M8 6h.01',                                 // calendar
    'M-4 12v-24l15-4v24 M-8.5 7.5a4.5 4.5 0 1 0 .01 0z M6.5 3.5a4.5 4.5 0 1 0 .01 0z',                            // music
    'M0-17l15 8v17l-15 8-15-8v-17z M-15-9l15 8 15-8 M0-1v17'                                                     // cube
  ];
  const ORDER = [0, 4, 7, 2, 9, 1, 8, 3, 10, 5, 11, 6];          // which glyph sits at ring slot k
  const HC = [960, 520], HRX = 760, HRY = 380, SPIN = 4, B0 = 6.6;
  const SRC = [2, 3, 3, 4, 4, 5, 5, 0, 0, 1, 1, 2];              // slot k sprays from dot i (5 = the input box), nearest bearing
  const T0 = SRC.map((s, k) => (s === 5 ? 6.6 : 6.68) + .3 * hash01(k, 21));   // launch beats (box first); all land by b7.9
  const R0 = SRC.map((s, k) => (k % 2 ? 1 : -1) * (16 + 10 * hash01(k, 23)));  // tilt in flight, settles with a small bounce
  const th = (k, b) => 30 * k + SPIN * (b - B0);
  const halo = (deg) => [HC[0] + HRX * Math.sin(deg * D2R), HC[1] - HRY * Math.cos(deg * D2R)];
  // 1c.3: as each word lands, the 3 nearest icons are drawn 40 px toward it and spring back. Word centres follow the
  // line as K.words refits it (We alone → We Are → the full line, 1150 px; Everything on the second line).
  const WORDS = [[8.8, 960, 470], [9.3, 1067, 470], [9.8, 1182, 470], [10.3, 960, 615]].map(([w, x, y]) => {
    const d = SRC.map((_, k) => { const q = halo(th(k, w)); return [Math.hypot(q[0] - x, q[1] - y), k]; }).sort((a, b) => a[0] - b[0]);
    return { w, x, y, near: d.slice(0, 3).map((e) => e[1]) };
  });
  const pullF = (u) => (u <= 0 || u >= 1 ? 0 : u < .28 ? E.out(u / .28) : 1 - ease.back((u - .28) / .72));
  function icon(k, b) {
    const t0 = T0[k]; if (b < t0) return null;
    const p = clamp((b - t0) / .9);
    let [x, y] = halo(th(k, b)), s = 1, rot = 0, a = 1;
    if (p < 1) {                                                  // flight: quadratic arc bowed away from the ring centre
      const S = SRC[k] < 5 ? (() => { const q = AGD.pos(SRC[k], t0); return [q.x, q.y]; })() : [960, 760];
      const dx = x - S[0], dy = y - S[1], L = Math.hypot(dx, dy) || 1, mx = (S[0] + x) / 2, my = (S[1] + y) / 2;
      let nx = -dy / L, ny = dx / L; if (nx * (mx - HC[0]) + ny * (my - HC[1]) < 0) { nx = -nx; ny = -ny; }
      const C = [mx + nx * .2 * L, my + ny * .2 * L], e = E.out(p), v = 1 - e;
      x = v * v * S[0] + 2 * v * e * C[0] + e * e * x; y = v * v * S[1] + 2 * v * e * C[1] + e * e * y;
      s = lerp(.3, 1, ease.back(p)); rot = R0[k] * (1 - E.out(p)); a = Math.min(1, p * 3);
    } else {
      const q = clamp((b - t0 - .9) / .25); rot = -R0[k] * .3 * Math.pow(Math.sin(Math.PI * q), 2);
    }
    // H2: the dots cross the halo on their way out — icons near a dot ease aside (soft, continuous), never under it
    const wr = clamp((b - t0 - .9) / .3);
    if (wr > 0) for (let i = 0; i < 5; i++) {
      const d = AGD.pos(i, b); if (d.a <= .01) continue;
      const ux = x - d.x, uy = y - d.y, l = Math.hypot(ux, uy) || 1, push = Math.max(0, 115 - l);
      if (push > 0) { const f = wr * push * push / 115; x += ux / l * f; y += uy / l * f; }
    }
    for (const W of WORDS) if (W.near.includes(k)) {
      const f = pullF((b - W.w) / .7); if (!f) continue;
      const ux = W.x - x, uy = W.y - y, l = Math.hypot(ux, uy) || 1; x += ux / l * 40 * f; y += uy / l * 40 * f;
    }
    a *= lerp(1, .6, E.inOut(clamp((b - 8.6) / .2)));             // 1c.1: down to 60 %
    const q2 = E.inOut(clamp((b - 10.3) / 1.5));                  // 1c.3: turn to face outward, shrink to .7
    if (q2 > 0) { const az = Math.atan2(x - HC[0], -(y - HC[1])) / D2R; rot = lerp(rot, az, q2); s *= lerp(1, .7, q2); }
    const q3 = E.in(clamp((b - 11.8) / .8));                      // 1c.4: fly out along the radius and fade
    if (q3 > 0) { x = HC[0] + (x - HC[0]) * (1 + 1.4 * q3); y = HC[1] + (y - HC[1]) * (1 + 1.4 * q3); a *= 1 - q3; }
    return { x, y, s, rot, a };
  }
  const DEFS = '<defs><linearGradient id="inIcG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b2e35" stop-opacity=".94"/>' +
    '<stop offset="1" stop-color="#14161a" stop-opacity=".94"/></linearGradient></defs>';
  AGD.back(B0, 12.6, (b) => {
    let s = DEFS;
    // the halo itself: a faint ellipse that draws in as the icons land, dims with them and fades before they fly out
    const hv = E.inOut(clamp((b - 6.9) / 1.0)), ha = .09 * lerp(1, .6, E.inOut(clamp((b - 8.6) / .2))) * (1 - E.inOut(clamp((b - 11.6) / .6)));
    if (hv > 0 && ha > .002) s += '<path d="M960 140A760 380 0 0 1 960 900A760 380 0 0 1 960 140" fill="none" stroke="#fff" stroke-opacity="' + ha.toFixed(3) + '" stroke-width="1.5" pathLength="1" stroke-dasharray="' + hv.toFixed(4) + ' 2"/>';
    for (let k = 0; k < 12; k++) {
      const q = icon(k, b); if (!q || q.a <= .002) continue;
      s += '<g transform="translate(' + q.x.toFixed(1) + ' ' + q.y.toFixed(1) + ') rotate(' + q.rot.toFixed(2) + ') scale(' + q.s.toFixed(4) + ')" opacity="' + q.a.toFixed(3) + '">' +
        '<rect x="-44" y="-44" width="88" height="88" rx="22" fill="url(#inIcG)" stroke="#fff" stroke-opacity=".17" stroke-width="1.5"/>' +
        '<path d="M-30-43.2h60" stroke="#fff" stroke-opacity=".08" stroke-width="1.5"/>' +
        '<path d="' + G[ORDER[k]] + '" fill="none" stroke="#fff" stroke-opacity=".92" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" transform="scale(1.02)"/></g>';
    }
    return s;
  });

  /* ---------- 1c（b8.6–12.6） ---------- */
  // H2: radial out to the edges, beyond the halo (b8.4 → 9.8)
  // Same 1.2 beats / stag .05 as K2, but front-loaded (smoothstep into a cubic ease-out, still zero speed at both ends):
  // with plain E.inOut gm is still at y ≈ 468 at b8.8, right under 「We」 (960, 470); this way it is at y ≈ 340.
  const H2E = (p) => { const s = p * p * (3 - 2 * p); return 1 - Math.pow(1 - s, 3); };
  AGD.key(8.4, 'pts', { pts: AGD.P.scatterC, r: 30, a: .55, dur: 1.2, stag: .05, ease: H2E });
  // 1c.2: two lines, one hard cut per word (b8.8 We / 9.3 Are / 9.8 Redesigning / 10.3 Everything); 1c.4: the letters
  // drift apart as both lines leave (b12.0–12.6)
  txt(8.8, 12.6, [['xl sv in-w1', '<span class="w">We</span><span class="w"> Are</span><span class="w"> Redesigning</span>']],
    { x: 960, y: 470, align: 'c' }, { anim: K.words({ at: [0, .5, 1.0], fit: 1150, out: .6, spread: true }) });
  txt(10.3, 12.6, [['xl in-ev', '<span class="w">Everything</span>']], { x: 960, y: 615, align: 'c' },
    { anim: K.words({ at: [0], out: .6, spread: true }) });
});
