/* 03-wordmark — 品牌字标展开（helper，不注册场景；20-orbit 用它在 45° 标志与翻平之间插入「Orbit·知音」）.
   原样使用 docs/design/logo/kit/motion/orbit-reveal.html：预计算的帧是标志绕自身轴转一圈、从 pitch 45° 倾到字标的 O
   （pitch 75°）并滑到 O 的位置；之后 rbit·知音 逐字升起。时序照搬 kit：转 1500 ms（T 拍）、字母自转动的 75 %（1125 ms）起
   每个 110 ms 错开、各 420 ms 升起 24 px（kit 在 880 px 宽时的 24 px = 字标坐标 63 单位）；收回时倒序（最后一个字先走）。
   帧与字母都在字标自己的坐标里（viewBox 38.9 40 2322.1 428.3）。恢复自 v16 promo.js（b83c3dcb）的 REVEAL / revealSVG /
   matchFrame，只是画到自己的 SVG 层 #wordmark（紧贴 #orbit 之上、Agent 点 #agd 之下）。标志本身不重画：帧来自 logo kit，
   转身前后的 orbitSVG 姿态由 place() 精确对齐到第 0 帧。
   WORDMARK.place(pose)   orbitSVG 的 ICON 姿态 { R, cx, cy }（yaw 20 / pitch 45）→ 让第 0 帧与它重合的字标摆放 { cx, cy, k }
   WORDMARK.svg(o)        o = { cx, cy, k（屏幕 px / 字标单位）, v（转身 0..1）, b, on, off（字母起落拍）, a } → SVG 字符串
   WORDMARK.add(h)        本帧画进 #wordmark（每帧由 orbitAt 清空）
   WORDMARK.T / .ms(ms)   转身拍数 / 毫秒换拍 */
'use strict';
const WORDMARK = (() => {
  const W = { url: '../../../docs/design/logo/kit/motion/orbit-reveal.html', vb: [38.9, 40, 2322.1, 428.3], F: null, L: null, D: 0, T: 1.5 / BEAT, h: '' };
  W.ms = (ms) => ms / 1000 / BEAT;
  W.ready = fetch(W.url).then((r) => r.text()).then((h) => {
    const doc = new DOMParser().parseFromString(h, 'text/html'), js = doc.querySelector('script').textContent;
    W.F = JSON.parse(/const F=(\[.*?\]),N=/s.exec(js)[1]);
    W.D = +/D=(-?[\d.]+)/.exec(js)[1];
    W.T = +/T=(\d+)/.exec(js)[1] / 1000 / BEAT;
    W.L = [...doc.querySelectorAll('path.l')].map((p) => ({ d: p.getAttribute('d'), i: +/--i:(\d+)/.exec(p.getAttribute('style'))[1], j: +/--j:(\d+)/.exec(p.getAttribute('style'))[1] }));
  }).catch((e) => console.error('promo: wordmark frames', e));
  // own layer right above the mark
  const el = document.createElementNS(SVGNS, 'svg');
  el.id = 'wordmark'; el.setAttribute('class', 'orbit'); el.setAttribute('viewBox', '0 0 1920 1080'); el.setAttribute('aria-hidden', 'true');
  orbEl.after(el);
  W.add = (h) => { W.h += h; };
  // the frame loop clears and fills the layer around the mark track (markAt callbacks call W.add)
  const orbitAt0 = orbitAt;
  orbitAt = function (bf) { W.h = ''; orbitAt0(bf); if (el.innerHTML !== W.h) el.innerHTML = W.h; };
  // the script boots only once the frames are in (render.mjs waits for PROMO.ready)
  const boot0 = boot;
  boot = function () { W.ready.then(() => boot0(), () => boot0()); };

  W.svg = (o) => {
    if (!W.F || o.a <= .001) return '';
    const [x, y, w, h] = W.vb, mx = x + w / 2, my = y + h / 2, F = W.F, N = F.length, v = clamp(o.v);
    let g = '<g opacity="' + o.a.toFixed(3) + '" fill="' + MARK_INK + '" transform="translate(' + o.cx.toFixed(2) + ' ' + o.cy.toFixed(2) + ') scale(' + o.k.toFixed(5) + ') translate(' + (-mx) + ' ' + (-my) + ')">';
    g += '<path d="' + F[Math.round(v * (N - 1))] + '" transform="translate(' + (W.D * (1 - v)).toFixed(2) + ' 0)"/>';
    for (const l of W.L) {
      const pin = E.out(clamp((o.b - o.on - W.ms(l.i * 110)) / W.ms(420)));
      const pout = o.off == null ? 0 : E.out(clamp((o.b - o.off - W.ms(l.j * 110)) / W.ms(420))), p = pin * (1 - pout);
      if (p > .001) g += '<path d="' + l.d + '" opacity="' + p.toFixed(3) + '" transform="translate(0 ' + (63 * (1 - p)).toFixed(2) + ')"/>';
    }
    return g + '</g>';
  };
  // bounding boxes: of a reveal frame (wordmark units) and of orbitSVG at a pose with R = 1 around (0, 0)
  const BOX = {};
  const boxOf = (d) => { const p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', d); el.appendChild(p); const r = p.getBBox(); p.remove(); return r; };
  const unitBox = (yaw, pitch) => {
    const key = yaw + '/' + pitch; if (BOX[key]) return BOX[key];
    const m = /d="([^"]+)"/.exec(orbitSVG({ t: 1, yaw, pitch, R: 1000, cx: 0, cy: 0, a: 1 }));
    const r = boxOf(m[1]); return (BOX[key] = { x: r.x / 1000, y: r.y / 1000, w: r.width / 1000, h: r.height / 1000 });
  };
  // inverse of v16 matchFrame for frame 0 (drawn shifted by D): the wordmark placement whose frame 0 sits exactly where
  // orbitSVG draws the mark at { R, cx, cy } (yaw / pitch default to the icon view)
  W.place = (pose, yaw = 20, pitch = 45) => {
    const [x, y, w, h] = W.vb, f = BOX.F0 || (BOX.F0 = boxOf(W.F[0])), u = unitBox(yaw, pitch), R = pose.R, k = R * u.w / f.width;
    return { k, cx: pose.cx + u.x * R - (f.x + W.D - (x + w / 2)) * k, cy: pose.cy + u.y * R - (f.y - (y + h / 2)) * k };
  };
  return W;
})();
