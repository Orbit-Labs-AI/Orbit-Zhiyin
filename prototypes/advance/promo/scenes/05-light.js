/* Light（全片，最底层）：路演 PPT 同一套颗粒渐变光斑（light/*.webp，取自 Orbit 路演稿），在纯黑上为每段垫一两块
   柔光，像 PPT 那样大、偏离中心、常常半出画，透明度低于内容，不抢字。每块光斑只在自己的段落出现，段与段之间用 2 拍左右的
   交叉淡换和位移衔接，平时缓慢漂移、呼吸、微转（没有闪烁，也不随节拍跳动）。
   拍号写成「场景 + 场景拍」，经 SHIFT 换算成成片拍，所以场景改了时长，光影跟着走。 */
scene('05-light', () => {
  css(`
.light{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.light .lb{position:absolute;left:0;top:0;background:center/contain no-repeat;opacity:0;will-change:transform,opacity}
`);
  const F = (sc, b) => b + (SHIFT[sc] || 0);
  const box = document.createElement('div'); box.className = 'light'; stage.insertBefore(box, stage.firstChild);
  // [file, width px, aspect h / w]
  const IMG = { circle: [1200, .738], brain: [1200, .603], prism: [1198, 1.002], wave: [1200, .383], warm: [1200, .998], ring: [1200, .927], ribbon: [1200, .738] };
  // each blob: keyframes [film beat, x, y (centre, stage px), w (px), opacity, rotate (deg)]; between keys it eases (sine)
  const B = [
    // 片头：一块蓝色圆光从下方升到标志背后，字标展开时略放大，下潜时随镜头冲大并淡出
    { img: 'circle', drift: 1, k: [[F('10-open', 5.5), 1080, 900, 1300, 0, -6], [F('10-open', 8.6), 1040, 560, 1250, .42, -2], [F('10-open', 14), 980, 520, 1500, .5, 3], [F('10-open', 18.7), 960, 540, 1600, .42, 6], [F('10-open', 20.5), 960, 540, 3400, 0, 14]] },
    // 情绪：脑形光斑在右下，被推穿时滑出
    { img: 'brain', drift: 2, k: [[F('20-sentiment', 14.0), 1700, 980, 1500, 0, 4], [F('20-sentiment', 15.4), 1500, 860, 1500, .4, 0], [F('20-sentiment', 20.6), 1380, 800, 1600, .4, -4], [F('20-sentiment', 21.8), 1100, 640, 2000, 0, -8]] },
    // 人格：橙蓝棱光在罗盘背后；罗盘左移揭晓时跟到左侧，缩成优势卡旁的小光，穿越门时冲大淡出
    { img: 'prism', drift: 3, k: [[F('30-persona', 25.0), 1300, 640, 1100, 0, -10], [F('30-persona', 27.0), 1260, 560, 1250, .46, -4], [F('30-persona', 45.6), 1220, 560, 1300, .5, 6], [F('30-persona', 47.6), 700, 560, 1300, .5, 2], [F('30-persona', 57.0), 640, 580, 1350, .5, -2], [F('30-persona', 58.6), 380, 580, 760, .42, -6], [F('30-persona', 64.7), 420, 560, 820, .4, -8], [F('30-persona', 66.2), 700, 540, 2600, 0, -16]] },
    // 推荐：上方一条波形光托住滚动的数字
    { img: 'wave', drift: 4, k: [[F('40-recs', 55.0), 1500, 40, 1900, 0, -4], [F('40-recs', 56.6), 1300, 140, 2000, .44, -2], [F('40-recs', 67.0), 1100, 160, 2100, .44, 2], [F('40-recs', 68.6), 900, 60, 2200, 0, 4]] },
    // 安装：暖色光在左下
    { img: 'warm', drift: 5, k: [[F('40-recs', 67.6), 160, 1080, 1000, 0, 8], [F('40-recs', 69.0), 260, 900, 1050, .36, 4], [F('40-recs', 77.6), 320, 860, 1100, .36, -2], [F('40-recs', 79.0), 120, 1080, 1100, 0, -6]] },
    // 前后对比：环形光在右上，图表与数字之间
    { img: 'ring', drift: 6, k: [[F('40-recs', 78.0), 1700, 120, 1000, 0, -6], [F('40-recs', 79.4), 1520, 260, 1150, .38, -2], [F('40-recs', 85.8), 1440, 300, 1200, .38, 3], [F('40-recs', 87.0), 1300, 360, 1400, 0, 8]] },
    // 把时间还给你自己：一道彩带横过「你」的背后，和 PPT 结尾页一样
    { img: 'ribbon', drift: 7, k: [[F('40-recs', 86.2), 1060, 640, 1300, 0, -8], [F('40-recs', 87.3), 980, 560, 1450, .5, -3], [F('40-recs', 91.6), 940, 540, 1550, .5, 2], [F('40-recs', 92.8), 900, 520, 1800, 0, 6]] },
    // 收尾：蓝色圆光回到标志背后，随片尾一起淡出
    { img: 'circle', drift: 8, k: [[F('60-close', 101.0), 960, 760, 1200, 0, 8], [F('60-close', 104.0), 980, 520, 1300, .4, 2], [F('60-close', 111.6), 960, 470, 1450, .42, -2], [F('60-close', 113.0), 960, 470, 1500, 0, -4]] }
  ];
  const ease = E.sine, GAIN = 1.35;                    // overall strength against black (the PPT blobs read dull below ≈ .5)
  B.forEach((o) => {
    const el = document.createElement('div'); el.className = 'lb'; el.style.backgroundImage = 'url(light/' + o.img + '.webp)'; box.appendChild(el); o.el = el;
  });
  const at = (k, b) => {
    if (b <= k[0][0]) return k[0];
    for (let i = 1; i < k.length; i++) if (b <= k[i][0]) { const p = ease((b - k[i - 1][0]) / (k[i][0] - k[i - 1][0])); return k[i].map((v, j) => (j ? lerp(k[i - 1][j], v, p) : b)); }
    return k[k.length - 1];
  };
  every(0, 200, (p, b) => {
    B.forEach((o) => {
      const k = o.k, live = b >= k[0][0] && b <= k[k.length - 1][0];
      if (!live) { if (o.el.style.opacity !== '0') o.el.style.opacity = '0'; return; }
      const [, x, y, w, op, r] = at(k, b), d = o.drift, h = w * IMG[o.img][1];
      // slow drift and breathing (periods of 20–40 beats, never in time with the music)
      const dx = 26 * Math.sin(b * .19 + d * 1.7), dy = 18 * Math.cos(b * .15 + d * 2.3), sc = 1 + .035 * Math.sin(b * .23 + d), rr = r + 2.5 * Math.sin(b * .11 + d * 3.1);
      o.el.style.width = w.toFixed(0) + 'px'; o.el.style.height = h.toFixed(0) + 'px';
      o.el.style.transform = 'translate(' + (x + dx - w / 2).toFixed(1) + 'px,' + (y + dy - h / 2).toFixed(1) + 'px) rotate(' + rr.toFixed(2) + 'deg) scale(' + sc.toFixed(4) + ')';
      o.el.style.opacity = Math.min(.7, op * GAIN).toFixed(3);
    });
  });
});
