/* 20-orbit 2（b21.6–34.6） — STORYBOARD.md v17「2」与「转场关键帧」H5–H9、M1–M5.
   v17.4 产品介绍收紧（本场景 −2.4 拍，起点不变）：长出 1.3 拍（b22.2 起）、立起 1.3 拍（b23.3 起，与长出重叠 .2），字标转身 b24.6；
   字标下加一行「你的 AI 协作复盘助手」（b27.5 起，可读 ≈ 2.6 拍），b30.3 收字（kit 收回 ×1.5 速）、O 转回 b30.8–32.5（1.7 拍），
   翻平 1.3 拍 b32.5–33.8（= TOP，描边光交接），淡完 b34.6；compass key b32.1（原 b34.5 − 2.4）。下面旧拍号的说明按此平移。
   v17.7 去掉「于是，我们做了……」（本场景 −.8 拍，起点与交入 / 交出的形状不变）：45° 标志立稳即按 kit reveal 转身，转身 ×1.5 速
   （2.2 拍，与收回同速），字母 b26.25 起、b28.6 齐，副标题 b26.7 起（可读 3 拍），b29.5 收字、O 转回 b30.0–31.7，
   翻平 b31.7–33.0，淡完 b33.8；compass key b31.3；点 b24.8 离开轨道、向下兜一小弧排成一行（避开左移的 O）。
   圆环收紧加速 → 环自己长成俯视螺旋（尾端落在虚线圆上）→ 立起成 45° Orbit 标志（ICON），点落到标志外的倾斜轨道
   → 字标段（v17.3，v17.7 起不再有引导句）：标志按 logo kit 的 reveal 绕自身轴转一圈
     成为字标的 O，「rbit·知音」逐字升起，齐全可读 1.55 拍（加上最后两字升起约 1.9 拍）（字标一直慢推、点在字标下方排成一行缓缓舒展，不静止），
     然后字母倒序收回、O 转回标志（回到 ICON 姿态，慢推续上）
   → 翻平、放大、顺时针转半圈，尾端停在罗盘描边光起点 (960, 212) → 光离开时淡出。
   放慢节奏（v17 pace）：长出 1.6 拍、立起 1.5 拍（与长出尾段重叠）、翻平 1.5 拍，三段都用 sine。
   v17.3 字标段：本场景加长 ADD = 8.8 拍，插在 b25.3（标志立起完成）与翻平之间；b25.3 之后的事件（翻平、落定、淡出、
   回到轨道的点、compass key）全部后移 ADD，起点与交出的形状不变：翻平 b34.7 起、compass key b34.5、落定 TOP b36.2、淡完 b37.0。
   字标时序（场景拍，kit 原样：转 1500 ms = 3.3 拍、字母 110 ms 错开 / 各 420 ms）：转身 b25.3–28.6，字母 b27.775 起、b30.15 齐，
   b31.7 起倒序收回（b34.08 收完），O 转回 b32.5–34.7（2.2 拍，与收字重叠，kit 的 1.08 s 等待省掉）。
   本场景只拥有标志（markAt M1–M5）、字标层（scenes/03-wordmark.js）与 AGD 的 b21.6 / b23.8 / b26.6 / b32.8 四个 key；
   不碰 deck 2（归 30-persona）、不画虚线圆（归 15-redesign）。compass key 按交接表由接手方 30-persona 写；它没写时这里补上（见下）。 */
'use strict';
css(`
.k .ln.wm-s{font-size:44px;font-weight:300;color:rgba(255,255,255,.76);letter-spacing:.08em}
`);
scene('20-orbit', () => {
  const PC = [960, 540], MYSH = SH;
  // 字标段（场景拍）
  const GROW0 = 22.2, GROW = 1.3, RISE0 = 23.3, RISE = 1.3;
  // 转身 TT = kit 的 ×1.5 速（2.2 拍，与收回同速）；字母照 kit 在转身 75 % 处起、110 ms 错开 / 各 420 ms；收字 OFF 在字母起后 3.25 拍
  const WS = RISE0 + RISE, TT = WORDMARK.T / 1.5, ON = WS + .75 * TT, OFF = ON + 3.25, BACK0 = OFF + .5, BACKD = 1.7, BACK1 = BACK0 + BACKD;
  const ADD = BACK1 - (WS + .6);                             // 慢推：字标段之后按「没有字标段」的时间续上
  const FLIP0 = BACK1, FLIP1 = FLIP0 + 1.3, FADE1 = FLIP1 + .8, CK = FLIP1 - 1.7;   // CK b31.3：点比翻平早 .4 拍起步

  /* ---------- Agent 点（K1 相位链：228 → 294 → compass key 时 Φ 与原来相同，只晚 ADD 拍） ---------- */
  // 2.1 / H5：圆环 R 420 → 300 收紧、5 → 30°/拍 加速（ph = 旧环在 b21.6 的角度 207 + 5·4.2 = 228，刚体、不倒转）
  AGD.key(21.6, 'ring', { cx: 960, cy: 540, R: 300, ph: 228, spin: 30, r: 34, dur: .8, stag: 0, polar: PC });
  // 2.3 / H7：随标志立起（RISE 1.3 拍），点缩小、落到标志外的倾斜轨道（rx 1.6R、ry .3R、cy = 520 + .14R；远半圈在标志后面）
  const OB = { cx: 960, cy: 552, rx: 368, ry: 69, spin: 25.4, r: 18 };
  AGD.key(RISE0, 'orbit', { ...OB, ph: 228 + 30 * (RISE0 - 21.6), dur: RISE, ease: E.sine, stag: 0, polar: PC });
  // 字标段：标志转身时点离开轨道（按 x 排序，不交叉），在字标与副标题下方排成一小行；读字时这一行缓缓上移、点距慢慢舒展（不静止）
  // （b24.8 起 1.6 拍：副标题 b26.7 浮现前点已越过它的那一行）。转身时标志左移成 O，扫过轨道左端：点早 .4 拍起步、
  // 路径向下兜 90px（arc −90），最左的 cp 在标志左缘扫到前已落到它下方，不再从 O 上穿过
  const ROW = WS + .2;
  AGD.key(ROW, 'row', { cx: 960, y: (b) => 812 - 3 * Math.max(0, b - ROW), gap: (b) => 60 + 1.4 * Math.max(0, b - ROW), r: 15, order: 'x', dur: 1.6, ease: E.sine, stag: .06, arc: -90 });
  // 收字时点先回到轨道（polar 沿椭圆参数）；相位使 CK 交给 compass 时每个点的位置与原来（轨道 key 后 1.9 拍）完全一样。
  // 交接检查：原先 BACK0 − .3 起 1.6 拍，点在副标题淡出、「rb」还实着时就从字母间穿上去；改为 BACK0 + .25 起 1.1 拍
  // （到位拍不变），路径中段向下兜 40px（arc −40）：点升进字母带时副标题已无、「rb」只剩 ≲ 15 % 的残影
  const RET = BACK0 + .25;
  AGD.key(RET, 'orbit', { ...OB, ph: 294 + OB.spin * (RET - CK + 1.9), dur: 1.1, ease: E.sine, stag: .04, polar: PC, arc: -40 });
  // 2.5 / H9：轨道椭圆张开成罗盘外圈，点比翻平早 .2 拍起步（b34.5，sine），领着标志翻开。交接汇总规定这条 compass key 由接手方 30-persona 写；
  // 为了两边谁都不漏、也不重复，在第一帧检查（按本场景拍比较）：CK −.3 / +.8 内没有 compass key 时才补这一条
  let compassChecked = false;
  const ensureCompass = () => {
    if (compassChecked) return; compassChecked = true;
    if (AGD_KEYS.some((k) => k.form === 'compass' && k.b - MYSH > CK - .3 && k.b - MYSH < CK + .8)) return;
    const s0 = SH; SH = MYSH;
    try { AGD.key(CK, 'compass', { dur: 2.0, ease: E.sine, stag: .06, polar: PC }); } finally { SH = s0; }
  };

  /* ---------- 标志（K3 M1–M5） ---------- */
  const ICON = { t0: 0, t: 1, yaw: MARK.ICON.yaw, pitch: MARK.ICON.pitch, R: 230, cx: 960, cy: 520 };
  const TOP = { t0: 0, t: 1, yaw: -160.4, pitch: 90, R: 328, cx: 960, cy: 540 };
  const grow = (b) => E.sine(lp(b, GROW0, GROW));
  // ICON 上的慢推：R × 1 → 1.056（立起完成前 .5 拍起 1.6 拍）；字标段之后按原来的时间续上（b − ADD）
  const push = (b) => 1 + .056 * lp(b >= BACK1 ? b - ADD : Math.min(b, WS), WS - .5, 1.6);
  const icon = (b) => Object.assign({}, ICON, { R: ICON.R * push(b) });
  markAt(0, 88, () => { ensureCompass(); return null; });   // one-time check on whatever frame renders first
  // M1 grow（b22.2–23.3，长出续到 b23.5）
  markAt(GROW0, RISE0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: grow(b), a: E.out(lp(b, GROW0, .4)) }));
  // M2 rise（b23.3–24.6）：TOP → ICON
  markAt(RISE0, WS, (p, b) => {
    const e = E.sine(lp(b, RISE0, RISE));
    return markRing({ cx: 960, cy: lerp(540, 520, e), R: lerp(300, 230, e) * push(b), yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e, grow: grow(b) });
  });

  /* ---------- 字标段 W（b25.3–34.7）：logo kit 的 reveal ---------- */
  // 起点 / 终点的字标摆放 = 第 0 帧与 ICON 姿态重合（起点 R × push(b25.3)，终点 R × push(b25.9)，慢推连续）；
  // 读字时字标居中 (960, 520)，k .54（约 1250 px 宽）并一直慢推 +3 %
  let P0 = null, P1 = null;
  const readAt = (b) => ({ cx: 960, cy: 520, k: .54 * (1 + .03 * lp(b, WS, BACK1 - WS)) });
  const mixP = (a, c, e) => ({ cx: lerp(a.cx, c.cx, e), cy: lerp(a.cy, c.cy, e), k: lerp(a.k, c.k, e) });
  markAt(WS, BACK1, (p, b) => {
    if (!WORDMARK.F) return icon(b);                         // frames missing: keep the icon (no wordmark)
    P0 = P0 || WORDMARK.place(icon(WS)); P1 = P1 || WORDMARK.place(icon(BACK1));
    let v, at;
    if (b < BACK0) { v = E.inOut(lp(b, WS, TT)); at = mixP(P0, readAt(b), v); }
    else { const e = E.inOut(lp(b, BACK0, BACKD)); v = 1 - e; at = mixP(readAt(b), P1, e); }
    WORDMARK.add(WORDMARK.svg({ a: 1, cx: at.cx, cy: at.cy, k: at.k, v, b, on: ON, off: OFF, offRate: 1.5 }));
    return null;
  });
  // 副标题「你的 AI 协作复盘助手」（pitch deck）：字标字母升起后接着浮现（b26.7），在字标下方，每拍上移 3px 与点行同步；
  // 比收字晚 .2 拍离开（b29.7 起 .8 拍），可读 ≈ 3 拍 ≈ 1.4 s
  const S0 = ON + .45, S1 = OFF + 1.0, SUB = mask(.18, 1, .8);
  txt(S0, S1, [['wm-s', '你的 AI 协作复盘助手']], { x: 960, y: 706, align: 'c' }, {
    anim: (el, tl, life, ts) => { SUB(el, tl, life); el.style.transform = 'translate(-50%,-50%) translateY(' + (-3 * (ts / BEAT - S0)).toFixed(1) + 'px)'; }
  });

  // M4 flip（b32.5–33.8）：从仍在慢推的 ICON 翻成俯视、放大到描边光半径 381 × .86 = 328，同时顺时针转半圈
  // （尾端方位 179.6° → 360°）；FLIP1（b33.8）落定 = TOP，与描边光起点交接不变
  markAt(FLIP0, FLIP1, (p, b) => MARK.mix(icon(b), TOP, E.sine(lp(b, FLIP0, FLIP1 - FLIP0))));
  // M5（b33.8–34.6）：描边光从尾端出发（30-persona 画），标志随之淡出
  markAt(FLIP1, FADE1, (p, b) => Object.assign({}, TOP, { a: 1 - E.inOut(lp(b, FLIP1, .8)) }));
});
