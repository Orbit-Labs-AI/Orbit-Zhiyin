/* Light（全片，最底层）：三团常驻光体（v17，见 STORYBOARD「光影」）。图是路演 PPT 同一套颗粒渐变光斑（light/*.webp）。
   每团整片沿自己的连续路径走：经过手写路点的向心 Catmull-Rom 样条（x、y、宽、强度一起插值；拍 → 样条参数用单调
   Hermite 弧长映射，速度连续，路点处不停顿），叠加慢漂移与呼吸（周期 20–40 拍，不随节拍）和各自的匀速自转。
   光体不读取任何场景对象（不调用 AGD / MARK / elXY / 相机），场景改动不会牵动光。只在 b0–4.5 淡入、END−3.6–END 淡出；
   「衍生」= 原位、原宽度上 2 拍交叉溶解换图。拍号是成片拍（v18.1 起固定，不再按 END 拉伸）。
   v17.7（用户：标志时刻落在纯黑上）：20-orbit 字标段（场景拍 b24.0–31.2）前后各 3–4 拍长淡，光体压到每团 ≤ .15；
   60-close 曲线画起前（场景拍 b70.4–75.4）长淡到 0，此后保持全黑到片尾。时间只按 SHIFT 表换算，不读场景对象。 */
scene('05-light', () => {
  css(`
.light{position:absolute;inset:0;pointer-events:none;overflow:hidden;-webkit-mask-image:radial-gradient(ellipse 70% 75% at 50% 52%,#000 55%,rgba(0,0,0,.35) 100%);mask-image:radial-gradient(ellipse 70% 75% at 50% 52%,#000 55%,rgba(0,0,0,.35) 100%)}
.light .lb{position:absolute;left:0;top:0;background:center/contain no-repeat;opacity:0;will-change:transform,opacity}
`);
  const box = document.createElement('div'); box.className = 'light'; stage.insertBefore(box, stage.firstChild);
  // aspect h / w of each image (all 1200 px wide)
  const ASP = { circle: .738, ring: .927, prism: 1.002, warm: .998, wave: .383, ribbon: .738 };
  // v18.1: ring.webp is a lumpy blob, not a donut — a radial mask (in % of the layer, so it scales with w and turns with the
  // layer about its centre) cuts a soft dark disc, so the rim haloes what sits at the waypoint (1e dot ring, persona dial)
  // v18.2: a band that also fades at its outer edge (closest-side), so the halo rings the dot ring / dial instead of washing the frame
  const MASK = { ring: 'radial-gradient(circle closest-side at 50% 50%, transparent 0 44%, rgba(0,0,0,.6) 52%, #000 58%, #000 74%, transparent 100%)' };
  const GAIN = 1.35, CAP = .7, FADE_IN = [0, 4.5], FADE_TAIL = 3.6;
  // k: [film beat, x, y (centre, stage px), width px, strength]; img: [first image, [beat, next image], …] (3-beat dissolve)
  // spin: own constant turn (deg / beat) on top of the breathing wobble; rot0: starting angle; d: drift phase
  // v18.1: beats are fixed film beats (the v17 88-beat grid × 131.7 / 88 once), so a change of END no longer moves the light.
  const B = [
    // A: ring from b27 haloes the R420 dot ring of the 1e peak (centre 960,540, dark disc ≥ ring), then sits concentric with
    // the persona dial (600,560) and swells at the DIMV reveal; back to circle before recs so no ring under the column / cards
    { name: 'A', img: ['circle', [27, 'ring'], [62.9, 'circle']], spin: .167, rot0: -6, d: 1,
      k: [[0, 1560, 1240, 1200, 0], [6.0, 1380, 900, 1250, .20], [18.0, 1150, 700, 1300, .18], [28.4, 960, 540, 1500, .50], [30.2, 960, 540, 1500, .50], [35.9, 960, 540, 1580, .52],
        [41.9, 900, 548, 1200, .36], [49.4, 720, 560, 1000, .30], [61.4, 600, 560, 1000, .38], [83.8, 240, 560, 820, .42], [88.0, 420, 780, 800, .26], [93.0, 1000, 790, 850, .26], [97.5, 1600, 780, 850, .26], [99.4, 960, 680, 820, .34],
        [108.6, 960, 540, 900, .16], [117.5, 960, 470, 1300, .3], [120.5, 960, 330, 1250, .3], [131.7, 960, 300, 1300, 0]] },
    // B: warm accent near the 1b headline; late swell behind the right side of the centred recs payoff
    { name: 'B', img: ['prism', [90.6, 'warm']], spin: -.12, rot0: 8, d: 2,
      k: [[0, 180, -260, 1100, 0], [7.5, 520, 40, 1150, .28], [19.5, 860, -140, 1150, .16], [31.4, 1440, 190, 1100, .12], [46.4, 1560, 480, 1100, .16],
        [56.9, 1520, 600, 1100, .16], [68.8, 1660, 520, 1000, .24], [80.8, 1880, 560, 1000, .40], [84.8, 1300, 600, 950, .40], [86.9, 1260, 640, 950, .20], [93.6, 1420, 720, 1050, .12],
        [99.8, 1640, 860, 1000, .14], [104.1, 1640, 980, 1050, .10], [122.0, 1500, 900, 1000, .26], [131.7, 1450, 950, 1000, 0]] },
    // C: floor glow under the intro bar (y 1120), then the wave / ribbon low band
    { name: 'C', img: ['wave', [111.5, 'ribbon']], spin: .08, rot0: -5, d: 3,
      k: [[0, -200, 1000, 1700, 0], [9.0, 640, 1120, 1800, .3], [21.0, 1060, 1200, 1800, .30], [32.9, 1400, 1030, 1800, .10], [44.9, 1780, 1150, 1700, .12],
        [59.9, 1100, 1080, 1800, .2], [74.8, 860, 1000, 1900, .26], [90.6, 900, 1080, 1800, .14], [105.6, 820, 980, 1700, .10], [116.0, 950, 770, 1500, .36],
        [126.5, 965, 740, 1550, .38], [131.7, 975, 728, 1600, 0]] }
  ];
  // v18.1 parallax: scripted [film beat, dur, dx, dy, ease], ≈ 1/3 of each foreground move in the same direction
  // (A, B × 1, C × .6; b99.0 dy −40: the trajectory card leaves upward and SKILL.md rises in); the eased sum is an offset that stays (see the waypoint note below). Still no reads of scene objects.
  const PAR = [[6.6, 1.2, 0, -30, 'inOut'], [13.6, 2.0, 70, 0, 'inOut'], [49.7, 1.4, -120, 0, 'inOut'], [86.7, 1.4, 40, 0, 'out'], [99.0, 1.2, -60, -40, 'inOut'], [106.9, 1.0, 0, -40, 'inOut']];
  const par = (b) => PAR.reduce((a, [pb, du, x, y, ez]) => { const q = E[ez](clamp((b - pb) / du)); a[0] += x * q; a[1] += y * q; return a; }, [0, 0]);

  // ---- path: centripetal Catmull-Rom (Barry–Goldman) over [x, y, w, strength], knots from the x/y chord ** .5 (v18.1: at least 12, so a
  // waypoint that holds its place — 1e ring, persona dial — does not make w / strength overshoot) ----
  function path(k) {
    const n = k.length, beat = k.map((r) => r[0]), P = k.map((r) => r.slice(1));
    // the waypoint strength 0 at b0 / b88 is the fade; the envelope does it, so the spline holds the neighbour's strength
    P[0][3] = P[1][3]; P[n - 1][3] = P[n - 2][3];
    const ext = (a, b) => a.map((v, j) => 2 * v - b[j]);
    const Q = [ext(P[0], P[1]), ...P, ext(P[n - 1], P[n - 2])];
    const T = [0];
    for (let i = 1; i < Q.length; i++) T.push(T[i - 1] + Math.max(12, Math.hypot(Q[i][0] - Q[i - 1][0], Q[i][1] - Q[i - 1][1]) ** .5));
    const mix = (a, b, ta, tb, t) => a.map((v, j) => ((tb - t) * v + (t - ta) * b[j]) / (tb - ta));
    const seg = (t) => {
      let i = 0; while (i < n - 2 && t > T[i + 2]) i++;
      const [t0, t1, t2, t3] = [T[i], T[i + 1], T[i + 2], T[i + 3]], [p0, p1, p2, p3] = [Q[i], Q[i + 1], Q[i + 2], Q[i + 3]];
      const a1 = mix(p0, p1, t0, t1, t), a2 = mix(p1, p2, t1, t2, t), a3 = mix(p2, p3, t2, t3, t);
      return mix(mix(a1, a2, t0, t2, t), mix(a2, a3, t1, t3, t), t1, t2, t);
    };
    // arc-length table, so the speed along the curve is set by the beats only (not by the knot spacing)
    const tt = [T[1]], ll = [0], S = [0]; let q = seg(T[1]);
    for (let i = 0; i < n - 1; i++) {
      for (let j = 1; j <= 48; j++) { const t = T[i + 1] + (T[i + 2] - T[i + 1]) * j / 48, c = seg(t); ll.push(ll[ll.length - 1] + Math.hypot(c[0] - q[0], c[1] - q[1])); tt.push(t); q = c; }
      S.push(ll[ll.length - 1]);
    }
    // beat → arc length: monotone cubic Hermite through (beat_i, S_i), so the speed is continuous across waypoints
    const sv = []; for (let i = 0; i < n - 1; i++) sv.push((S[i + 1] - S[i]) / (beat[i + 1] - beat[i]));
    const m = beat.map((_, i) => (i === 0 ? sv[0] : i === n - 1 ? sv[n - 2] : Math.min((sv[i - 1] + sv[i]) / 2, 3 * Math.min(sv[i - 1], sv[i]))));
    return (b) => {
      b = clamp(b, beat[0], beat[n - 1]);
      let i = 0; while (i < n - 2 && b > beat[i + 1]) i++;
      const h = beat[i + 1] - beat[i], u = (b - beat[i]) / h, u2 = u * u, u3 = u2 * u;
      const L = (2 * u3 - 3 * u2 + 1) * S[i] + (u3 - 2 * u2 + u) * h * m[i] + (-2 * u3 + 3 * u2) * S[i + 1] + (u3 - u2) * h * m[i + 1];
      let lo = 0, hi = ll.length - 1; while (hi - lo > 1) { const md = (lo + hi) >> 1; if (ll[md] < L) lo = md; else hi = md; }
      const f = ll[hi] > ll[lo] ? clamp((L - ll[lo]) / (ll[hi] - ll[lo])) : 0;
      return seg(lerp(tt[lo], tt[hi], f));
    };
  }

  B.forEach((o) => {
    // waypoints are screen positions: the PAR offset reached by each waypoint's beat is taken back out of the spline, so a
    // parallax step is a quick extra move with the foreground and the blob still sits on its waypoint afterwards
    o.pk = o.name === 'C' ? .6 : 1;
    o.at = path(o.k.map(([kb, x, y, w, st]) => { const [qx, qy] = par(kb); return [kb, x - qx * o.pk, y - qy * o.pk, w, st]; }));
    o.layers = {};
    [o.img[0], ...o.img.slice(1).map((x) => x[1])].forEach((im) => {
      if (o.layers[im]) return;
      const el = document.createElement('div'); el.className = 'lb'; el.style.backgroundImage = 'url(light/' + im + '.webp)';
      if (MASK[im]) el.style.webkitMaskImage = el.style.maskImage = MASK[im];
      box.appendChild(el); o.layers[im] = el;
    });
  });
  // image weights at beat b: in-place cross-dissolves of 2 beats
  const weights = (o, b) => {
    const w = { [o.img[0]]: 1 };
    o.img.slice(1).forEach(([bs, im]) => { const p = E.sine(clamp((b - bs) / 3)); for (const key in w) w[key] *= 1 - p; w[im] = (w[im] || 0) + p; });
    return w;
  };
  const env = (b) => E.sine(clamp((b - FADE_IN[0]) / (FADE_IN[1] - FADE_IN[0]))) * (1 - E.sine(clamp((b - (END - FADE_TAIL)) / FADE_TAIL)));

  // v17.7: logo moments on pure black (film beats, from the SHIFT table only — no scene objects).
  // DIM: behind the Orbit·知音 wordmark of 20-orbit every blob is scaled to ≤ .15 (DIM_K · CAP), long sine fades either side;
  // DARK: before the close's curve starts drawing, a long fade to 0 that holds to the last frame.
  const OS = SHIFT['20-orbit'] || 0, CS = SHIFT['60-close'] || 0;
  const DIM = [OS + 20.7, OS + 24.0, OS + 31.2, OS + 35.2], DIM_K = .15 / CAP, DARK = [CS + 70.4, CS + 75.4];
  const look = (bf) => {
    const dim = E.sine(clamp((bf - DIM[0]) / (DIM[1] - DIM[0]))) * (1 - E.sine(clamp((bf - DIM[2]) / (DIM[3] - DIM[2]))));
    return lerp(1, DIM_K, dim) * (1 - E.sine(clamp((bf - DARK[0]) / (DARK[1] - DARK[0]))));
  };

  // v18.1: b is the film beat (no stretch); only the fade-out reads END, so it still ends on the last frame.
  every(0, 1e6, (p, bf) => {
    const b = bf, e = env(b) * look(bf), [px, py] = par(b);
    B.forEach((o) => {
      const [x0, y0, w, st] = o.at(b), d = o.d, wt = weights(o, b), x = x0 + px * o.pk, y = y0 + py * o.pk;
      // slow drift and breathing (periods ≈ 40–55 film beats, the v17 speeds × 88 / 131.7, never in time with the music)
      const dx = 26 * Math.sin(b * .127 + d * 1.7), dy = 18 * Math.cos(b * .114 + d * 2.3), sc = 1 + .035 * Math.sin(b * .154 + d);
      const rr = o.rot0 + o.spin * b + 2.5 * Math.sin(b * .134 + d * 3.1);
      const op = Math.min(CAP, Math.max(0, st) * GAIN) * e;
      for (const im in o.layers) {
        const el = o.layers[im], a = op * (wt[im] || 0);
        if (a < .002) { if (el.style.opacity !== '0') el.style.opacity = '0'; continue; }
        const h = w * ASP[im];
        el.style.width = w.toFixed(0) + 'px'; el.style.height = h.toFixed(0) + 'px';
        el.style.transform = 'translate(' + (x + dx - w / 2).toFixed(1) + 'px,' + (y + dy - h / 2).toFixed(1) + 'px) rotate(' + rr.toFixed(2) + 'deg) scale(' + sc.toFixed(4) + ')';
        el.style.opacity = a.toFixed(3);
      }
    });
  });
});
