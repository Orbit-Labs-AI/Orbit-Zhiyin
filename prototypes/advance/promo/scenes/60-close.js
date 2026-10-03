/* 60-close 6–7（b69.4–88） — STORYBOARD.md v17「6」「7」与「转场关键帧」H13–H17、M6–M9.
   合并点散开，收拢罗盘（= R 300 圆环）在它们身后从左侧画出 → 展开成罗盘（你的类型的花）→ 再收回圆环 →
   圆环平着长出螺旋（与 2.2 同一个镜头）→ 立起成 45° Orbit 标志 → 标志上移缩小、点沿圆环两侧滑到底部排成一行 →
   「Orbit」+「An Assistant Redesign for everyone & every agent」→ 一起淡出到全黑。
   本场景拥有：deck 2（b69.4 起）、标志 markAt M6–M9、AGD 的 b69.4 / 77.0 / 86.2 三个 key、片尾文字。 */
scene('60-close', () => {
  END = 88;
  const PC = [960, 540];

  /* ---------- deck 2：收拢罗盘 = 圆环 → 罗盘 → 圆环（H13–H15） ---------- */
  // b69.4 直接设定：罗盘中心 (400, 400) → 舞台 (960, 540)，s 1，不倾斜（6.3：orbitSVG 是正交投影，倾倒会对不上）
  tween(2, 69.4, 0, { x: 400, y: 400, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, 74.8, 1.0, { o: 0 }, E.inOut);                     // 6.4：螺旋长出时罗盘环淡出（drawCompass 继续到 b79）
  let degMe = null;
  // drawCompass 每帧调用到 b79（AGD 的 compass 编队要读点位，直到 row 在 b78.84 落定）；一切都是 b 的纯函数
  drive(2, 69.4, 79.0, (p, b) => {
    if (degMe == null) { const D = compassData(); degMe = D.mineIdx >= 0 ? D.mineIdx * 22.5 + 11.25 : 11.25; }
    const open = E.inOut(lp(b, 71.2, 1.6)), fold = E.inOut(lp(b, 73.2, 1.2));
    const on = E.inOut(lp(b, 71.6, 1.2)) * (1 - fold);        // dial / core：b71.6–72.8 出现，b73.2–74.4 淡出
    drawCompass({
      collapse: 1 - open + fold, dial: on, core: on, pl: 0,
      spin: (b - 72) * .5,                                     // K0：6 段独立取，b72 全开时 5 个点均匀分布
      sweep: E.inOut(lp(b, 69.8, 1.4)), sweepFrom: 270,        // 圆环从点飞来的左侧开始画出
      mine: 1, deg: degMe, grow: lerp(.34, 1, E.out(lp(b, 71.6, 1.2))), needle: 1
    });
  });

  /* ---------- Agent 点（H13 / H16 / H17） ---------- */
  // H13：合并点从 (220, 540) 散开，直线放射（arc 50，不用 polar）落到 R 300 圆环上，b71.32 落定，之后骑在罗盘外圈
  AGD.key(69.4, 'compass', { dur: 1.6, stag: .08, arc: 50 });
  // H16 / 7.1：沿圆环两侧滑到底部、收成一行（cc 在右），b78.84 落定，字出现前已就位
  AGD.key(77.0, 'row', { cx: 960, y: 780, gap: 72, r: 20, order: [4, 3, 2, 1, 0], dur: 1.6, stag: .06, polar: PC });
  // 7.4：定格时极小的漂移（2px，不随节拍）
  AGD.follow(78.84, 88, (i, b, q) => ({ x: q.x + 2 * Math.sin(2 * Math.PI * (b / (9 + 3 * hash01(i, 8)) + hash01(i, 9))), y: q.y + 2 * Math.sin(2 * Math.PI * (b / (11 + 3 * hash01(i, 10)) + hash01(i, 11))) }), { blend: .6 });
  // 7.3：「every agent」落下时 5 个点从左到右依次亮起，与配乐 b80.6 + .1k 的 5 个 blip 同步（blip 声像也是左 → 右）
  for (let k = 0; k < 5; k++) AGD.glow(4 - k, 80.6 + .1 * k, 80.7 + .1 * k, .9);
  // H17：原地缩小淡出
  AGD.key(86.2, 'off', { dur: 1.6, stag: 0 });

  /* ---------- 标志（K3 M6–M9） ---------- */
  // M6 grow（b74.4–76.0）：俯视螺旋从圆环尾部（方位 199.6°，(859, 823)）顺时针往里长出，同 M1
  markAt(74.4, 76.0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: E.inOut(lp(b, 74.4, 1.6)), a: E.out(lp(b, 74.4, .3)) }));
  // M7 rise（b76.0–77.0）：TOP → ICON（R 300 → 215，cy 540 → 470），markRing 的 lift（两端为 0）
  markAt(76.0, 77.0, (p, b) => {
    const e = E.inOut(lp(b, 76.0, 1.0));
    return markRing({ cx: 960, cy: lerp(540, 470, e), R: lerp(300, 215, e), yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e });
  });
  // 7.1 停住（b77.0–77.8）→ M8 上移缩小（b77.8–79.2，cy 470 → 300，R 215 → 150，外框 y 188–392）→ 定格 → M9 淡出（b86.2–88）
  markAt(77.0, 88, (p, b) => {
    const e = E.inOut(lp(b, 77.8, 1.4));
    return markRing({ cx: 960, cy: lerp(470, 300, e), R: lerp(215, 150, e), yaw: 20, pitch: 45, lift: 0, a: 1 - E.inOut(lp(b, 86.2, 1.8)) });
  });

  /* ---------- 片尾文字（7.3，b86.2–88 与标志、点一起淡出） ---------- */
  css(`
.cl-orbit{font-size:128px;font-weight:700;letter-spacing:-.015em;line-height:1;color:#fff}
.cl-orbit .ch{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.cl-tag{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.01em}
.cl-tag b{color:var(--acc);font-weight:600}
`);
  // 银色渐变放在每个字符上（K.blurIn 逐字淡入；放在行上会被父级的 background-clip 整块先画出来）
  txt(79.0, 88, [['cl-orbit', 'Orbit']], { x: 960, y: 560, align: 'c' }, { anim: K.blurIn({ spread: .45, dur: .35, out: 1.8 }) });
  const W = ['An ', 'Assistant ', 'Redesign ', 'for ', 'everyone ', '&amp; ', '<b>every </b>', '<b>agent</b>'];
  txt(79.6, 88, [['cl-tag', W.map((w) => '<span class="w">' + w + '</span>').join('')]], { x: 960, y: 660, align: 'c' },
    { anim: K.words({ at: [0, .14, .28, .44, .58, .72, .86, 1.0], out: 1.8 }) });
});
