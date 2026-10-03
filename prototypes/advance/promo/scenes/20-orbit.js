/* 20-orbit 2（b21.6–37.0） — STORYBOARD.md v17「2」与「转场关键帧」H5–H9、M1–M5.
   圆环收紧加速 → 环自己长成俯视螺旋（尾端落在虚线圆上）→ 立起成 45° Orbit 标志（ICON），点落到标志外的倾斜轨道
   → 字标段（v17.3）：「于是，我们做了……」（银色，省略号的点逐个出现）随标志出现；标志按 logo kit 的 reveal 绕自身轴转一圈
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
.k .wm-l{font-size:60px;font-weight:400;letter-spacing:.02em}
.k .wm-l .ln{display:inline-block}
.k .wm-l .ln>span{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.k .wm-l .ln+.ln>span{width:.34em;text-align:center}
`);
scene('20-orbit', () => {
  const PC = [960, 540], MYSH = SH;
  // 字标段（场景拍）
  const WS = 25.3, T = WORDMARK.T, ON = WS + .75 * T, OFF = 31.7, BACK0 = 32.5, BACKD = 2.2, BACK1 = BACK0 + BACKD;
  const ADD = BACK1 - 25.9;                                  // 8.8：原来 b25.3–25.9 的 .6 拍慢推换成字标段

  /* ---------- Agent 点（K1 相位链：228 → 294 → compass key 时 Φ 与原来相同，只晚 ADD 拍） ---------- */
  // 2.1 / H5：圆环 R 420 → 300 收紧、5 → 30°/拍 加速（ph = 旧环在 b21.6 的角度 207 + 5·4.2 = 228，刚体、不倒转）
  AGD.key(21.6, 'ring', { cx: 960, cy: 540, R: 300, ph: 228, spin: 30, r: 34, dur: .8, stag: 0, polar: PC });
  // 2.3 / H7：随标志立起（1.5 拍），点缩小、落到标志外的倾斜轨道（rx 1.6R、ry .3R、cy = 520 + .14R；远半圈在标志后面）
  const OB = { cx: 960, cy: 552, rx: 368, ry: 69, spin: 25.4, r: 18 };
  AGD.key(23.8, 'orbit', { ...OB, ph: 294, dur: 1.5, ease: E.sine, stag: 0, polar: PC });
  // 字标段：标志转身时点离开轨道（按 x 排序，不交叉），在字标下方排成一小行；读字时这一行缓缓上移、点距慢慢舒展（不静止）
  const ROW = 26.6;
  AGD.key(ROW, 'row', { cx: 960, y: (b) => 744 - 3 * Math.max(0, b - ROW), gap: (b) => 60 + 1.4 * Math.max(0, b - ROW), r: 15, order: 'x', dur: 1.8, ease: E.sine, stag: .06 });
  // O 转回标志时点先回到轨道（polar 沿椭圆参数），相位 = 原轨道后移 ADD：b34.5 交给 compass 时每个点的位置与原来 b25.7 完全一样
  const RET = 32.8;
  AGD.key(RET, 'orbit', { ...OB, ph: 294 + OB.spin * (RET - ADD - 23.8), dur: 1.6, ease: E.sine, stag: .04, polar: PC });
  // 2.5 / H9：轨道椭圆张开成罗盘外圈，点比翻平早 .2 拍起步（b34.5，sine），领着标志翻开。交接汇总规定这条 compass key 由接手方 30-persona 写；
  // 为了两边谁都不漏、也不重复，在第一帧检查（按本场景拍比较）：b34.2–35.3 没有 compass key 时才补这一条
  const CK = 25.7 + ADD;
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
  const GROW0 = 22.4, GROW = 1.6, RISE0 = 23.8, RISE = 1.5, FLIP0 = 25.9 + ADD, FLIP1 = 27.4 + ADD, FADE1 = 28.2 + ADD;
  const grow = (b) => E.sine(lp(b, GROW0, GROW));
  // ICON 上的慢推：R × 1 → 1.056（b24.8 起 1.6 拍）；字标段之后按原来的时间续上（b − ADD）
  const push = (b) => 1 + .056 * lp(b >= BACK1 ? b - ADD : Math.min(b, WS), 24.8, 1.6);
  const icon = (b) => Object.assign({}, ICON, { R: ICON.R * push(b) });
  markAt(0, 88, () => { ensureCompass(); return null; });   // one-time check on whatever frame renders first
  // M1 grow（b22.4–23.8，长出续到 b24.0）
  markAt(GROW0, RISE0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: grow(b), a: E.out(lp(b, GROW0, .4)) }));
  // M2 rise（b23.8–25.3）：TOP → ICON
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
    if (b < BACK0) { v = E.inOut(lp(b, WS, T)); at = mixP(P0, readAt(b), v); }
    else { const e = E.inOut(lp(b, BACK0, BACKD)); v = 1 - e; at = mixP(readAt(b), P1, e); }
    WORDMARK.add(WORDMARK.svg({ a: 1, cx: at.cx, cy: at.cy, k: at.k, v, b, on: ON, off: OFF }));
    return null;
  });
  // 「于是，我们做了……」：银色 60px，标志立稳前浮现（b24.9），省略号六个点从 b25.6 起每 .22 拍出现一个；整行每拍上移 4px，
  // 与字母一起在 b31.7 起离开（.8 拍，上移、模糊）
  const L0 = 24.9, L1 = OFF + .8, DOT0 = 25.6;
  txt(L0, L1, [['wm-l', ['于是，我们做了', '·', '·', '·', '·', '·', '·']]], { x: 960, y: 250, align: 'c' }, {
    anim: (el, tl, life, ts) => {
      const b = ts / BEAT, q = E.inOut(clamp((life - tl) / BB(.8)));
      el.style.transform = 'translate(-50%,-50%) translateY(' + (-4 * (b - L0)).toFixed(1) + 'px)';
      el.querySelectorAll('.ln>span').forEach((s, i) => {
        const p = i === 0 ? E.expo(clamp(tl / BB(1))) : E.out(clamp((b - DOT0 - (i - 1) * .22) / .3));
        s.style.transform = 'translateY(' + ((1 - p) * (i === 0 ? 130 : 40) - (1 - q) * 30).toFixed(2) + '%)';
        s.style.opacity = (Math.min(1, p * 1.4) * q).toFixed(3);
        s.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none';
      });
    }
  });

  // M4 flip（b34.7–36.2）：从仍在慢推的 ICON 翻成俯视、放大到描边光半径 381 × .86 = 328，同时顺时针转半圈
  // （尾端方位 179.6° → 360°）；b36.2 落定 = TOP，与描边光起点交接不变
  markAt(FLIP0, FLIP1, (p, b) => MARK.mix(icon(b), TOP, E.sine(lp(b, FLIP0, FLIP1 - FLIP0))));
  // M5（b36.2–37.0）：描边光从尾端出发（30-persona 画），标志随之淡出
  markAt(FLIP1, FADE1, (p, b) => Object.assign({}, TOP, { a: 1 - E.inOut(lp(b, FLIP1, .8)) }));
});
