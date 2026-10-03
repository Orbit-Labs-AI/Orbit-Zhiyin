/* 60-close 6–7（b68.9–88） — STORYBOARD.md v17「6」「7」与「转场关键帧」H13–H17、M6–M9.
   合并点散开，收拢罗盘（= R 300 圆环）在它们身后从左侧画出 → 展开成罗盘（你的类型的花）→ 再收回圆环 →
   圆环平着长出螺旋（与 2.2 同一个镜头）→ 立起成 45° Orbit 标志 → 标志上移缩小、点沿圆环两侧滑到底部排成一行 →
   「Orbit」+「An Assistant Redesign for everyone & every agent」→ 一起淡出到全黑。
   本场景拥有：deck 2（b68.9 起）、标志 markAt M6–M9、AGD 的 b68.9 / 77.0 / 86.2 三个 key、片尾文字。 */
scene('60-close', () => {
  END = 88;
  const PC = [960, 540];
  // 片尾慢推：b78.6–88 由 1 匀速推到 1.07，前 20 % 二次缓起（M8 上移收尾时接上，不会停一下再动）
  const push = (b) => { const p = lp(b, 78.6, 9.4), a = .2; return 1 + .07 * (p < a ? p * p / (2 * a) : p - a / 2) / (1 - a / 2); };

  /* ---------- deck 2：收拢罗盘 = 圆环 → 罗盘 → 圆环（H13–H15） ---------- */
  // b68.9 直接设定（H13 提前 0.5 拍：工坊卡还在缩小淡出时合并点就开始散开，b69.2–69.7 不再只剩一个静止的点）：罗盘中心 (400, 400) → 舞台 (960, 540)，s 1，不倾斜（6.3：orbitSVG 是正交投影，倾倒会对不上）
  tween(2, 68.9, 0, { x: 400, y: 400, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, 74.8, 1.0, { o: 0 }, E.inOut);                     // 6.4：螺旋长出时罗盘环淡出（drawCompass 继续到 b79）
  let degMe = null;
  // drawCompass 每帧调用到 b79（AGD 的 compass 编队要读点位，直到 row 在 b78.84 落定）；一切都是 b 的纯函数
  drive(2, 68.9, 79.0, (p, b) => {
    if (degMe == null) { const D = compassData(); degMe = D.mineIdx >= 0 ? D.mineIdx * 22.5 + 11.25 : 11.25; }
    const open = E.inOut(lp(b, 71.2, 1.6)), fold = E.inOut(lp(b, 73.2, 1.2));
    const on = E.inOut(lp(b, 71.6, 1.2)) * (1 - fold);        // dial / core：b71.6–72.8 出现，b73.2–74.4 淡出
    drawCompass({
      collapse: 1 - open + fold, dial: on, core: on, pl: 0,
      spin: (b - 72) * .5,                                     // K0：6 段独立取，b72 全开时 5 个点均匀分布
      sweep: E.inOut(lp(b, 69.3, 1.8)), sweepFrom: 270,        // 圆环从点飞来的左侧开始画出
      mine: 1, deg: degMe, grow: lerp(.34, 1, E.out(lp(b, 71.6, 1.2))), needle: 1
    });
  });

  /* ---------- Agent 点（H13 / H16 / H17） ---------- */
  // H13：合并点从 (220, 540) 散开，直线放射（arc 50，不用 polar）落到 R 300 圆环上，b71.12 落定（圆环 b71.1 画完，b71.2 起展开，不多停），之后骑在罗盘外圈
  AGD.key(68.9, 'compass', { dur: 1.9, stag: .08, arc: 50 });
  // H16 / 7.1：沿圆环两侧慢慢滑到底部、收成一行（cc 在右），b79.32 落定（「Orbit」b79.0 起淡入时还在收尾）
  AGD.key(77.0, 'row', { cx: 960, y: 780, gap: 72, r: 20, order: [4, 3, 2, 1, 0], dur: 2.0, stag: .08, polar: PC });
  // 7.4：片尾不定格——标志、字、点一起以 (960, 540) 为中心匀速慢推 1 → 1.07（b78.6–88，开头 0.2 段缓起），点另有 2px 漂移；
  // follow 到 b89 才淡出（b1 处的 0.6 拍混回不落在片内）
  AGD.follow(79.0, 89, (i, b, q) => {
    const s = push(b);
    return { x: 960 + (q.x - 960) * s + 2 * Math.sin(2 * Math.PI * (b / (9 + 3 * hash01(i, 8)) + hash01(i, 9))), y: 540 + (q.y - 540) * s + 2 * Math.sin(2 * Math.PI * (b / (11 + 3 * hash01(i, 10)) + hash01(i, 11))), r: q.r * s };
  }, { blend: .6 });
  // 7.3：「agent」落下（b81.62）时 5 个点从左到右依次亮起，间隔 .16 拍、各亮 .5 拍（.3 拍渐起渐落），像一道光扫过这一行
  for (let k = 0; k < 5; k++) AGD.glow(4 - k, 81.62 + .16 * k, 82.12 + .16 * k, .9);
  // H17：原地缩小淡出
  AGD.key(86.2, 'off', { dur: 1.6, stag: 0 });

  /* ---------- 标志（K3 M6–M9） ---------- */
  // M6 grow（b74.4–76.0）：俯视螺旋从圆环尾部（方位 199.6°，(859, 823)）顺时针往里长出，同 M1
  markAt(74.4, 76.0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: E.inOut(lp(b, 74.4, 1.6)), a: E.out(lp(b, 74.4, .3)) }));
  // M7 rise（b76.0–77.4）：TOP → ICON（R 300 → 215，cy 540 → 470），markRing 的 lift（两端为 0）；
  // M8 上移缩小（b77.2–79.2，cy 470 → 300，R 215 → 150，外框 y 188–392）与立起的收尾重叠，中间不再停 0.8 拍；
  // 之后随片尾慢推（push，以 (960, 540) 为中心等比放大，姿态不变）→ M9 淡出（b86.2–88）
  markAt(76.0, 88, (p, b) => {
    const e = E.inOut(lp(b, 76.0, 1.4)), u = E.inOut(lp(b, 77.2, 2.0)), s = push(b);
    const cy = lerp(lerp(540, 470, e), 300, u), R = lerp(lerp(300, 215, e), 150, u);
    return markRing({ cx: 960, cy: 540 + (cy - 540) * s, R: R * s, yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e, a: 1 - E.inOut(lp(b, 86.2, 1.8)) });
  });

  /* ---------- 片尾文字（7.3，b86.2–88 与标志、点一起淡出） ---------- */
  css(`
.cl-orbit{font-size:128px;font-weight:700;letter-spacing:-.015em;line-height:1;color:#fff}
.cl-orbit .ch{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.cl-tag{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.01em}
.cl-tag b{color:var(--acc);font-weight:600}
`);
  // 银色渐变放在每个字符上（K.blurIn 逐字淡入；放在行上会被父级的 background-clip 整块先画出来）
  // 字随片尾慢推一起放大：锚点 y 相对 540 外移 × push，字号 × push（tick 在 anim 之后覆盖 transform）
  const pushT = (y) => (el, tl, life, ts) => { const s = push(ts / BEAT); el.style.transform = 'translate(-50%,-50%) translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')'; };
  // 「Orbit」b79.0–80.4 逐字从模糊里浮出（spread .8 + dur .6）；标语 b79.9 起逐词出现，间隔约 .24 拍，「agent」b81.62
  txt(79.0, 88, [['cl-orbit', 'Orbit']], { x: 960, y: 560, align: 'c' }, { anim: K.blurIn({ spread: .8, dur: .6, out: 1.8 }), tick: pushT(560) });
  const W = ['An ', 'Assistant ', 'Redesign ', 'for ', 'everyone ', '&amp; ', '<b>every </b>', '<b>agent</b>'];
  txt(79.9, 88, [['cl-tag', W.map((w) => '<span class="w">' + w + '</span>').join('')]], { x: 960, y: 660, align: 'c' },
    { anim: K.words({ at: [0, .24, .48, .74, .98, 1.22, 1.46, 1.72], out: 1.8 }), tick: pushT(660) });
});
