/* 20-orbit 2（b21.6–28.2） — STORYBOARD.md v17「2」与「转场关键帧」H5–H9、M1–M5.
   圆环收紧加速 → 环自己长成俯视螺旋（尾端落在虚线圆上）→ 立起成 45° Orbit 标志（ICON），点落到标志外的倾斜轨道
   → 标志慢推不停住 → 翻平、放大、顺时针转半圈，尾端停在罗盘描边光起点 (960, 212) → 光离开时淡出。
   放慢节奏（v17 pace）：长出 1.6 拍、立起 1.5 拍（与长出尾段重叠）、翻平 1.5 拍，三段都用 sine（起步就看得见、匀速感）；
   原来 b25.0–26.4 的 1.4 拍静止改成 ICON 上的慢推（R 每拍 +3.5%），翻平提前到 b25.9 起步。
   交接拍不变：b21.6 ring key、b22.4 螺旋起长（虚线圆同时淡出）、b23.8 orbit key 相位、compass key（v17.1 交接检查后改到 b25.7，比翻平早 .2 拍）、
   b27.4 落定 TOP（尾端 = 描边光起点）、b28.2 淡完。
   本场景只拥有标志（markAt M1–M5，到 b28.2）与 AGD 的 b21.6 / b23.8 两个 key；不碰 deck 2（归 30-persona）、
   不画虚线圆（归 15-redesign）。compass key 按交接表由接手方 30-persona 写；它没写时这里补上（见下）。 */
scene('20-orbit', () => {
  const PC = [960, 540];

  /* ---------- Agent 点（K1 相位链：228 → 294 → b26.4 时 Φ ≡ 0） ---------- */
  // 2.1 / H5：圆环 R 420 → 300 收紧、5 → 30°/拍 加速（ph = 旧环在 b21.6 的角度 207 + 5·4.2 = 228，刚体、不倒转）
  AGD.key(21.6, 'ring', { cx: 960, cy: 540, R: 300, ph: 228, spin: 30, r: 34, dur: .8, stag: 0, polar: PC });
  // 2.3 / H7：随标志立起（1.5 拍），点缩小、落到标志外的倾斜轨道（rx 1.6R、ry .3R、cy = 520 + .14R；远半圈在标志后面）
  // 起拍与 ph / spin 不变（相位链只看起拍），只把混合时长拉到和立起一样的 1.5 拍、同一条 sine 缓动
  AGD.key(23.8, 'orbit', { cx: 960, cy: 552, rx: 368, ry: 69, ph: 294, spin: 25.4, r: 18, dur: 1.5, ease: E.sine, stag: 0, polar: PC });
  // 2.5 / H9：轨道椭圆张开成罗盘外圈，点比翻平早 .2 拍起步（b25.7，sine），领着标志翻开。交接汇总规定这条 compass key 由接手方 30-persona 写；
  // 为了两边谁都不漏、也不重复（两个 key 会叠成双重缓动），在第一帧检查：b25.4–26.5 没有 compass key 时才补这一条。
  let compassChecked = false;
  const ensureCompass = () => {
    if (compassChecked) return; compassChecked = true;
    if (!AGD_KEYS.some((k) => k.form === 'compass' && k.b > 25.4 && k.b < 26.5)) AGD.key(25.7, 'compass', { dur: 2.0, ease: E.sine, stag: .06, polar: PC });
  };

  /* ---------- 标志（K3 M1–M5） ---------- */
  const ICON = { t0: 0, t: 1, yaw: MARK.ICON.yaw, pitch: MARK.ICON.pitch, R: 230, cx: 960, cy: 520 };
  const TOP = { t0: 0, t: 1, yaw: -160.4, pitch: 90, R: 328, cx: 960, cy: 540 };
  const GROW0 = 22.4, GROW = 1.6, RISE0 = 23.8, RISE = 1.5, FLIP0 = 25.9, FLIP1 = 27.4;
  // 长出用 sine：b22.6 已有 4%、b22.8 有 15%（E.inOut 在 b22.85 前几乎看不见）；尾段 b23.8–24.0 与立起重叠，不停顿
  const grow = (b) => E.sine(lp(b, GROW0, GROW));
  // ICON 上的慢推：b24.8–26.4 R × 1 → 1.056 匀速（立起减速时接上，翻平起步时仍在动），代替原来的 1.4 拍静止
  const push = (b) => 1 + .056 * lp(b, 24.8, 1.6);
  const icon = (b) => Object.assign({}, ICON, { R: ICON.R * push(b) });
  markAt(0, 88, () => { ensureCompass(); return null; });   // one-time check on whatever frame renders first
  // M1 grow（b22.4–23.8，长出续到 b24.0）：俯视螺旋从尾部（R 300 圆上方位 199.6°，(859, 823)）顺时针往里长出 1.6 圈
  markAt(GROW0, RISE0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: grow(b), a: E.out(lp(b, GROW0, .4)) }));
  // M2 rise（b23.8–25.3）：TOP → ICON，和 v16 收尾同法（一个缓动因子，lift 1 − e 让尾端起步时贴在圆上）
  markAt(RISE0, RISE0 + RISE, (p, b) => {
    const e = E.sine(lp(b, RISE0, RISE));                    // sine：整段匀一些，不是只在中间 0.6 拍里猛转
    return markRing({ cx: 960, cy: lerp(540, 520, e), R: lerp(300, 230, e) * push(b), yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e, grow: grow(b) });
  });
  // M3（b25.3–25.9）：ICON 姿态（yaw 20 / pitch 45 不摆动），只做慢推
  markAt(RISE0 + RISE, FLIP0, (p, b) => icon(b));
  // M4 flip（b25.9–27.4）：从仍在慢推的 ICON 翻成俯视、放大到描边光半径 381 × .86 = 328，同时顺时针转半圈
  // （尾端方位 179.6° → 360°）；b27.4 落定 = TOP，与描边光起点交接不变
  markAt(FLIP0, FLIP1, (p, b) => MARK.mix(icon(b), TOP, E.sine(lp(b, FLIP0, FLIP1 - FLIP0))));
  // M5（b27.4–28.2）：描边光从尾端出发（30-persona 画），标志随之淡出
  markAt(FLIP1, 28.2, (p, b) => Object.assign({}, TOP, { a: 1 - E.inOut(lp(b, FLIP1, .8)) }));
});
