/* Light（全片，最底层）：三团常驻光体（v17，见 STORYBOARD「光影」）。图是路演 PPT 同一套颗粒渐变光斑（light/*.webp）。
   每团整片沿自己的连续路径走：经过手写路点的向心 Catmull-Rom 样条（x、y、宽、强度一起插值；拍 → 样条参数用单调
   Hermite 弧长映射，速度连续，路点处不停顿），叠加慢漂移与呼吸（周期 20–40 拍，不随节拍）和各自的匀速自转。
   光体不读取任何场景对象（不调用 AGD / MARK / elXY / 相机），场景改动不会牵动光。只在 b0–3 淡入、b85.6–88 淡出；
   「衍生」= 原位、原宽度上 2 拍交叉溶解换图。拍号是成片拍（SHIFT 0）。 */
scene('05-light', () => {
  css(`
.light{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.light .lb{position:absolute;left:0;top:0;background:center/contain no-repeat;opacity:0;will-change:transform,opacity}
`);
  const box = document.createElement('div'); box.className = 'light'; stage.insertBefore(box, stage.firstChild);
  // aspect h / w of each image (all 1200 px wide)
  const ASP = { circle: .738, ring: .927, prism: 1.002, warm: .998, wave: .383, ribbon: .738 };
  const GAIN = 1.35, CAP = .7, FADE_IN = [0, 3], FADE_OUT = [85.6, 88];
  // k: [film beat, x, y (centre, stage px), width px, strength]; img: [first image, [beat, next image], …] (2-beat dissolve)
  // spin: own constant turn (deg / beat) on top of the breathing wobble; rot0: starting angle; d: drift phase
  const B = [
    { name: 'A', img: ['circle', [26, 'ring'], [70, 'circle']], spin: .25, rot0: -6, d: 1,
      k: [[0, 1560, 1240, 1200, 0], [4, 1380, 900, 1250, .32], [12, 1150, 700, 1300, .36], [19, 990, 560, 1350, .42], [24, 980, 530, 1300, .46],
        [28, 900, 548, 1200, .36], [33, 620, 560, 1050, .32], [41, 300, 560, 900, .3], [56, 240, 560, 820, .34], [64, 520, 560, 950, .3],
        [72, 960, 540, 1250, .4], [78, 960, 470, 1300, .44], [80, 960, 330, 1250, .44], [88, 960, 300, 1300, 0]] },
    { name: 'B', img: ['prism', [60, 'warm']], spin: -.18, rot0: 8, d: 2,
      k: [[0, 180, -260, 1100, 0], [5, 330, 150, 1150, .34], [13, 860, 100, 1150, .3], [21, 1440, 190, 1100, .32], [31, 1560, 480, 1100, .3],
        [38, 1520, 600, 1100, .3], [46, 1660, 520, 1000, .32], [54, 1600, 640, 1000, .3], [62, 1420, 720, 1050, .34], [69, 1640, 980, 1050, .3],
        [81, 1500, 900, 1000, .26], [88, 1450, 950, 1000, 0]] },
    { name: 'C', img: ['wave', [74, 'ribbon']], spin: .12, rot0: -5, d: 3,
      k: [[0, -200, 1000, 1700, 0], [6, 640, 960, 1800, .3], [14, 1060, 960, 1800, .34], [22, 1400, 1030, 1800, .26], [30, 1780, 1150, 1700, .12],
        [40, 1100, 1080, 1800, .2], [50, 860, 1000, 1900, .26], [60, 900, 1080, 1800, .2], [70, 820, 980, 1700, .26], [77, 950, 770, 1500, .36],
        [84, 965, 740, 1550, .38], [88, 975, 728, 1600, 0]] }
  ];

  // ---- path: centripetal Catmull-Rom (Barry–Goldman) over [x, y, w, strength], knots from the x/y chord ** .5 ----
  function path(k) {
    const n = k.length, beat = k.map((r) => r[0]), P = k.map((r) => r.slice(1));
    // the waypoint strength 0 at b0 / b88 is the fade; the envelope does it, so the spline holds the neighbour's strength
    P[0][3] = P[1][3]; P[n - 1][3] = P[n - 2][3];
    const ext = (a, b) => a.map((v, j) => 2 * v - b[j]);
    const Q = [ext(P[0], P[1]), ...P, ext(P[n - 1], P[n - 2])];
    const T = [0];
    for (let i = 1; i < Q.length; i++) T.push(T[i - 1] + Math.max(1e-3, Math.hypot(Q[i][0] - Q[i - 1][0], Q[i][1] - Q[i - 1][1]) ** .5));
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
    o.at = path(o.k);
    o.layers = {};
    [o.img[0], ...o.img.slice(1).map((x) => x[1])].forEach((im) => {
      if (o.layers[im]) return;
      const el = document.createElement('div'); el.className = 'lb'; el.style.backgroundImage = 'url(light/' + im + '.webp)'; box.appendChild(el); o.layers[im] = el;
    });
  });
  // image weights at beat b: in-place cross-dissolves of 2 beats
  const weights = (o, b) => {
    const w = { [o.img[0]]: 1 };
    o.img.slice(1).forEach(([bs, im]) => { const p = E.sine(clamp((b - bs) / 2)); for (const key in w) w[key] *= 1 - p; w[im] = (w[im] || 0) + p; });
    return w;
  };
  const env = (b) => E.sine(clamp((b - FADE_IN[0]) / (FADE_IN[1] - FADE_IN[0]))) * (1 - E.sine(clamp((b - FADE_OUT[0]) / (FADE_OUT[1] - FADE_OUT[0]))));

  every(0, 90, (p, b) => {
    const e = env(b);
    B.forEach((o) => {
      const [x, y, w, st] = o.at(b), d = o.d, wt = weights(o, b);
      // slow drift and breathing (periods ≈ 26–37 beats, never in time with the music)
      const dx = 26 * Math.sin(b * .19 + d * 1.7), dy = 18 * Math.cos(b * .17 + d * 2.3), sc = 1 + .035 * Math.sin(b * .23 + d);
      const rr = o.rot0 + o.spin * b + 2.5 * Math.sin(b * .2 + d * 3.1);
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
