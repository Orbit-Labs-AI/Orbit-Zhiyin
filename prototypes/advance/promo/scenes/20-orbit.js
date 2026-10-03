/* 20-orbit 2（b21.6–28.2） — STORYBOARD.md v17「2」与「转场关键帧」H5–H9、M1–M5.
   圆环收紧加速 → 环自己长成俯视螺旋（尾端落在虚线圆上）→ 立起成 45° Orbit 标志（ICON），点落到标志外的倾斜轨道
   → 停 1.4 拍 → 翻平、放大、顺时针转半圈，尾端停在罗盘描边光起点 (960, 212) → 光离开时淡出。
   本场景只拥有标志（markAt M1–M5，到 b28.2）与 AGD 的 b21.6 / b23.8 两个 key；不碰 deck 2（归 30-persona）、
   不画虚线圆（归 15-redesign）。b26.4 的 compass key 按交接表由接手方 30-persona 写；它没写时这里补上（见下）。 */
scene('20-orbit', () => {
  const PC = [960, 540];

  /* ---------- Agent 点（K1 相位链：228 → 294 → b26.4 时 Φ ≡ 0） ---------- */
  // 2.1 / H5：圆环 R 420 → 300 收紧、5 → 30°/拍 加速（ph = 旧环在 b21.6 的角度 207 + 5·4.2 = 228，刚体、不倒转）
  AGD.key(21.6, 'ring', { cx: 960, cy: 540, R: 300, ph: 228, spin: 30, r: 34, dur: .8, stag: 0, polar: PC });
  // 2.3 / H7：随标志立起，点缩小、落到标志外的倾斜轨道（rx 1.6R、ry .3R、cy = 520 + .14R；远半圈在标志后面）
  AGD.key(23.8, 'orbit', { cx: 960, cy: 552, rx: 368, ry: 69, ph: 294, spin: 25.4, r: 18, dur: 1.2, stag: 0, polar: PC });
  // 2.5 / H9：轨道椭圆张开成罗盘外圈。交接汇总规定 b26.4 的新 key 由接手方 30-persona 写；为了两边谁都不漏、
  // 也不重复（同拍两个 key 会叠成双重缓动），在第一帧检查：没有 b26.4 的 compass key 时才补这一条。
  let compassChecked = false;
  const ensureCompass = () => {
    if (compassChecked) return; compassChecked = true;
    if (!AGD_KEYS.some((k) => k.form === 'compass' && Math.abs(k.b - 26.4) < .05)) AGD.key(26.4, 'compass', { dur: 1.4, stag: .06, polar: PC });
  };

  /* ---------- 标志（K3 M1–M5） ---------- */
  const ICON = { t0: 0, t: 1, yaw: MARK.ICON.yaw, pitch: MARK.ICON.pitch, R: 230, cx: 960, cy: 520 };
  const TOP = { t0: 0, t: 1, yaw: -160.4, pitch: 90, R: 328, cx: 960, cy: 540 };
  markAt(0, 88, () => { ensureCompass(); return null; });   // one-time check on whatever frame renders first
  // M1 grow（b22.4–23.8）：俯视螺旋从尾部（R 300 圆上方位 199.6°，(859, 823)）顺时针往里长出 1.6 圈
  markAt(22.4, 23.8, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: E.inOut(lp(b, 22.4, 1.4)), a: E.out(lp(b, 22.4, .3)) }));
  // M2 rise（b23.8–25.0）：TOP → ICON，和 v16 收尾同法（一个缓动因子，lift 1 − e 让尾端起步时贴在圆上）
  markAt(23.8, 25.0, (p, b) => {
    const e = E.inOut(lp(b, 23.8, 1.2));
    return markRing({ cx: 960, cy: lerp(540, 520, e), R: lerp(300, 230, e), yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e });
  });
  // M3（b25.0–26.4）：ICON 停住，不加偏航摆动（M4 要从 yaw 20 精确出发）
  markAt(25.0, 26.4, () => ICON);
  // M4 flip（b26.4–27.4）：翻成俯视、放大到描边光半径 381 × .86 = 328，同时顺时针转半圈（尾端方位 179.6° → 360°）
  markAt(26.4, 27.4, (p, b) => MARK.mix(ICON, TOP, E.inOut(lp(b, 26.4, 1))));
  // M5（b27.4–28.2）：描边光从尾端出发（30-persona 画），标志随之淡出
  markAt(27.4, 28.2, (p, b) => Object.assign({}, TOP, { a: 1 - E.inOut(lp(b, 27.4, .8)) }));
});
