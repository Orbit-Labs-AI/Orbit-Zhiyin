/* 60-close 6–7（b69.2–94） — STORYBOARD.md v17.1 T13（5 → 6 交接 b69.2）与 v17「6」「7」、「转场关键帧」H14–H17、M6–M9.
   合并点在画面中心 (960, 540) 螺旋放出，各自身后画出一段圆弧，5 段合成收拢罗盘（= R 300 圆环）→ 展开成罗盘（你的类型的花）→
   再收回圆环 → 圆环平着长出螺旋（与 2.2 同一个镜头）→ 立起成 45° Orbit 标志，在画面正中停留约 1.2 s（慢慢呼吸）、点沿圆环两侧
   滑到它下方排成一行 → v17.4：标志按 logo kit 的 reveal（scenes/03-wordmark.js）继续绕轴转身成 O、向左展开成居中的「Orbit·知音」
   → 字标下方「An Assistant Redesign for everyone & every agent」、点收成标语下的一小行 → 可读停留 ≥ 2.5 s → 一起淡出到全黑。
   v17.4 时序（场景拍）：ICON 到位 b78.4、停留到 b81.0、转身 b81.0–84.3、字母 b83.475–85.85、标语 b85.0–86.4、淡出 b92.2–94（END 89 → 94）。
   本场景拥有：deck 2（b69.2 起）、标志 markAt M6–M7 与片尾字标层、AGD 的 b69.2 / 78.0 / 85.2 / 92.2 四个 key 与 b69.2–71.4 的螺旋 follow、片尾标语。
   v17.3 看清文字：罗盘展开后多停 1 拍（插在 b73.2，之后一切 +1，END 88 → 89）——展开提前到 b71.04（圆环合成整圈即开，不再空等 .16 拍），
   类型码 b72.64 全亮、b74.2 才开始收回，完整可读 1.56 拍（DIMV 加粗那一个约 1.9 拍）；停留时不定格：花继续慢慢开、慢转 ±10°，
   deck 2 慢推 1 → 1.025（收回圆环时同一段 E.inOut 退回 1，b75.4 圆环仍是 R 300，接 M6）。 */
scene('60-close', () => {
  END = 94;
  const PC = [960, 540];
  // v17.4 片尾：45° 标志正中停留 → 转身向左展开成字标 → 标语 → 点一行 → 可读停留 → 淡出（场景拍）
  const TURN0 = 81.0, LET0 = TURN0 + .75 * WORDMARK.T, TAG0 = 85.0, TAG_AG = TAG0 + 1.4, FADE0 = 92.2;
  // 片尾慢推：字标转身起（b81.0）到 END 由 1 匀速推到 1.06，前 20 % 二次缓起
  const push = (b) => { const p = lp(b, TURN0, END - TURN0), a = .2; return 1 + .06 * (p < a ? p * p / (2 * a) : p - a / 2) / (1 - a / 2); };

  /* ---------- T13 螺旋放出（b69.2–71.04） ----------
     50-tools 的合并点 b69.2 停在 (960, 540)、r 40；从这里 5 个点各按 e_i = E.io((b − 69.2 − .06i) / 1.6) 向外放出（ρ = 圆环当帧半径，
     随中间那个点的 e 长到收拢罗盘上徽章到中心的距离 300，见 spRing），同时顺时针转到自己的徽章方位 d_i：θ_i = d_i − G_i·(1 − e_i)。0.0.4 的徽章停在各 Agent
     的平均方向（不均匀：cc 43 / cx 62 / ds 118 / cp 221 / gm 288°），所以 G_i 取 d_i 到逆时针方向上一个徽章的间隔（cc 115 / cx 19 /
     ds 56 / cp 103 / gm 67°，合计 360）而不是一律 72°：每个点起转于上一个点的终点方位，角度区间首尾相接、互不交叉，身后的圆弧
     [d_i − G_i, d_i − G_i + G_i·e_i] 头部始终在点的方位上，b71.04 五段正好合成整圈（无缺口、无重叠）。 */
  const HB = 69.2, spE = (i, b) => E.inOut(clamp((b - HB - .06 * i) / 1.6)), SP_END = HB + .06 * 4 + 1.6;
  // 圆环跟着点一起放大：deck 2 的 s 从 .001 按中间那个点（i = 2）的 e 长到 1（b70.92），5 个点的半径就取圆环当帧的半径
  // （300·s），只有转角按各自的 e_i 错开——身后的圆弧因此就在点所在的圆上、头部贴着点，而不是在 R 300 处凭空出现、点还在里面
  const SP_S0 = .001, SP_RD = 1.6 + .12, spRing = (p) => E.inOut(clamp((p * SP_RD - .12) / 1.6));
  const spWrap = (d) => ((d % 360) + 360) % 360;
  let SPG = null;                                             // [d_i, G_i]：徽章方位与它到上一个徽章的顺时针间隔（数据决定，算一次）
  const spG = () => SPG || (SPG = (() => {
    const d = compassData().sets.base.pl.map((x, i) => x ?? i * 72 + 18);
    return d.map((di, i) => { const g = d.map((dj, j) => (j === i ? 0 : spWrap(di - dj))).filter((x) => x > .01); return [di, g.length ? Math.min(...g) : 72]; });
  })());
  const S0 = [];                                              // 交接拍 b69.2 时 50-tools 交来的点（AGD.pos 读实际位置，像素级接上）
  const s0 = (i) => S0[i] || (S0[i] = AGD.pos(i, HB - 1e-6));

  /* ---------- deck 2：收拢罗盘 = 圆环 → 罗盘 → 圆环（H13–H15） ---------- */
  // b69.2 直接设定：罗盘中心 (400, 400) → 舞台 (960, 540)，不倾斜（6.3：orbitSVG 是正交投影，倾倒会对不上）；s 从 .001
  // 随点的半径长到 1（b70.92，罗盘 b71.04 展开前已是 1）；这时圆环的裁剪全是空的（5 段长度都是 0），画面上只有中心的合并点
  tween(2, HB, 0, { x: 400, y: 400, s: SP_S0, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, HB, SP_RD, { s: 1 }, spRing);
  // 读类型码时慢推 1 → 1.025（b72.2–74.2，sine），收回圆环时同一段退回 1（b74.2–75.4，与 fold 同曲线），M6 起圆环仍是 R 300
  tween(2, 72.2, 2.0, { s: 1.025 }, E.sine);
  tween(2, 74.2, 1.2, { s: 1 }, E.inOut);
  tween(2, 75.8, 1.0, { o: 0 }, E.inOut);                     // 6.4：螺旋长出时罗盘环淡出（drawCompass 继续到 b80）
  let degMe = null;
  // drawCompass 每帧调用到 b80（AGD 的 compass 编队要读点位，直到 row 在 b80.32 落定）；一切都是 b 的纯函数
  drive(2, HB, 80.0, (p, b) => {
    if (degMe == null) { const D = compassData(); degMe = D.mineIdx >= 0 ? D.mineIdx * 22.5 + 11.25 : 11.25; }
    const open = E.inOut(lp(b, SP_END, 1.6)), fold = E.inOut(lp(b, 74.2, 1.2));
    const on = E.inOut(lp(b, 71.44, 1.2)) * (1 - fold);       // dial / core：b71.44–72.64 出现（与 open 同时到 1），b74.2–75.4 淡出
    // T13：圆环由点画出——第 i 段从上一个徽章的方位起、长 G_i·e_i，紧跟在点 i 身后（起点往回多 .6° 盖住相邻两段接缝的抗锯齿，
    // 这 .6° 也随 e_i 长出，开头不会先冒出一小截）；b71.04 合成整圈后不再裁剪
    const segs = b < SP_END ? spG().map(([d, G], i) => [d - G - .6, (G + .6) * spE(i, b)]) : undefined;
    drawCompass({
      collapse: 1 - open + fold, dial: on, core: on, pl: 0,     // pl 0：徽章只由 AGD 画（compass 编队骑在同一位置）
      sweepSegs: segs,
      // 花：b71.44 起开到 .88（1.3 拍），余下 .12 在 b72.2–74.4 慢慢开完；同时慢转 −10° → +12°（b71.44–75.4，b73.2 前后正对类型）
      mine: 1, deg: degMe, grow: lerp(.34, 1, .88 * E.out(lp(b, 71.44, 1.3)) + .12 * E.sine(lp(b, 72.2, 2.2))), twist: lerp(-10, 12, lp(b, 71.44, 3.96)), needle: 1
    });
  });

  /* ---------- Agent 点（T13 / H16 / H17） ---------- */
  // T13：b69.2 起底下是罗盘编队（.4 拍内把合并点的五色细环淡掉；x / y / r 由下面的螺旋 follow 全权接管），
  // follow 从 b69.0 挂上（b69.2 前返回 null，不影响 50-tools），b69.2 时权重已是 1，起点就是交来的合并点；
  // e_i = 1 之后 follow 的结果与罗盘编队完全重合，b71.2–71.4 的退出混合看不出来，点继续骑在展开的罗盘外圈上
  AGD.key(HB, 'compass', { dur: .4, stag: 0 });
  AGD.follow(69.0, 71.4, (i, b) => {
    if (b < HB) return null;
    // R = 徽章到中心的实际距离 = 圆环当帧半径（deck 2 的 s 已随点放大，不再乘 e_i）；徽章大小按 s 1 的 19 取
    const e = spE(i, b), G = spG()[i][1], c = cpBadge(i), C = cpStage(400, 400), s = s0(i);
    const dc = Math.atan2(c.x - C[0], -(c.y - C[1])) / (Math.PI / 180), R = Math.hypot(c.x - C[0], c.y - C[1]), th = (dc - G * (1 - e)) * Math.PI / 180;
    return { x: C[0] + R * Math.sin(th) + (s.x - C[0]) * (1 - e), y: C[1] - R * Math.cos(th) + (s.y - C[1]) * (1 - e), r: lerp(s.r, c.r / decks[2].C.s, e) };
  }, { blend: .2 });
  // H16 / 7.1：沿圆环两侧慢慢滑到底部、收成一行（cc 在右），b80.32 落定（标志在正中立成 45° 并停留时，点在它下方）
  AGD.key(78.0, 'row', { cx: 960, y: 780, gap: 72, r: 20, order: [4, 3, 2, 1, 0], dur: 2.0, stag: .08, polar: PC });
  // v17.4：标语出现时（b85.0）点收成标语下方的一小行，b86.9 落定
  AGD.key(TAG0 + .2, 'row', { cx: 960, y: 736, gap: 50, r: 13, order: [4, 3, 2, 1, 0], dur: 1.4, ease: E.sine, stag: .06 });
  // 7.4：片尾不定格——字标、字、点一起以 (960, 540) 为中心慢推（push），点另有 2px 漂移；follow 到 END + 1 才淡出（混回不落在片内）
  AGD.follow(TURN0 - .6, END + 1, (i, b, q) => {
    const s = push(b);
    return { x: 960 + (q.x - 960) * s + 2 * Math.sin(2 * Math.PI * (b / (9 + 3 * hash01(i, 8)) + hash01(i, 9))), y: 540 + (q.y - 540) * s + 2 * Math.sin(2 * Math.PI * (b / (11 + 3 * hash01(i, 10)) + hash01(i, 11))), r: q.r * s };
  }, { blend: .6 });
  // 7.3：「agent」出现时 5 个点从左到右依次亮起，间隔 .16 拍、各亮 .5 拍（.3 拍渐起渐落），像一道光扫过这一行
  for (let k = 0; k < 5; k++) AGD.glow(4 - k, TAG_AG + .16 * k, TAG_AG + .5 + .16 * k, .9);
  // H17：原地缩小淡出
  AGD.key(FADE0, 'off', { dur: 1.6, stag: 0 });

  /* ---------- 标志（K3 M6–M7）→ 45° 正中停留 → 字标（logo kit reveal，scenes/03-wordmark.js） ---------- */
  // M6 grow（b75.4–77.0）：俯视螺旋从圆环尾部（方位 199.6°，(859, 823)）顺时针往里长出，同 M1
  markAt(75.4, 77.0, (p, b) => markRing({ cx: 960, cy: 540, R: 300, grow: E.inOut(lp(b, 75.4, 1.6)), a: E.out(lp(b, 75.4, .3)) }));
  // M7 rise（b77.0–78.4）：TOP → ICON（R 300 → 230，cy 540 → 520，yaw 0 → 20、pitch 90 → 45），markRing 的 lift（两端为 0）；
  // 之后在画面正中停留到 b81.0（约 1.2 s），停留时慢慢「呼吸」：R × 1 → 1.04（b78.0–81.0，sine），不定格
  const icon = (b) => {
    const e = E.inOut(lp(b, 77.0, 1.4)), s = 1 + .04 * E.sine(lp(b, 78.0, TURN0 - 78.0));
    return markRing({ cx: 960, cy: lerp(540, 520, e), R: lerp(300, 230, e) * s, yaw: lerp(0, 20, e), pitch: lerp(90, 45, e), lift: 1 - e });
  };
  markAt(77.0, TURN0, (p, b) => icon(b));
  // 字标段（b81.0–END）：kit 的帧原样——标志绕自身轴再转一圈成为字标的 O、向左滑到 O 的位置，「rbit·知音」在它右边逐字升起
  // （kit 时序：转 T = 3.3 拍、字母自 .75T 起 110 ms 错开、各 420 ms）；第 0 帧由 WORDMARK.place 与 b81.0 的 ICON 姿态精确重合，
  // 摆放从那里移到读字位置（字标整体居中 (960, 470)、k .5 ≈ 1160 px 宽），之后随 push 慢推；b92.2–94 与标语、点一起淡出
  let P0 = null;
  const readAt = (b) => { const s = push(b); return { cx: 960, cy: 540 + (470 - 540) * s, k: .5 * s }; };
  markAt(TURN0, END, (p, b) => {
    if (!WORDMARK.F) return Object.assign(icon(b), { a: 1 - E.inOut(lp(b, FADE0, 1.8)) });   // frames missing: keep the icon
    P0 = P0 || WORDMARK.place(icon(TURN0));
    const v = E.inOut(lp(b, TURN0, WORDMARK.T)), r = readAt(b);
    WORDMARK.add(WORDMARK.svg({ a: 1 - E.inOut(lp(b, FADE0, 1.8)), cx: lerp(P0.cx, r.cx, v), cy: lerp(P0.cy, r.cy, v), k: lerp(P0.k, r.k, v), v, b, on: LET0 }));
    return null;
  });

  /* ---------- 片尾标语（7.3，b92.2–94 与字标、点一起淡出） ---------- */
  css(`
.cl-tag{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.01em}
.cl-tag b{color:var(--acc);font-weight:600}
`);
  // 字随片尾慢推一起放大：锚点 y 相对 540 外移 × push，字号 × push（tick 在 anim 之后覆盖 transform）
  const pushT = (y) => (el, tl, life, ts) => { const s = push(ts / BEAT); el.style.transform = 'translate(-50%,-50%) translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')'; };
  // 标语在最后两个字升起时（b85.0）居中出现在字标下方，逐词间隔 .2 拍，「agent」b86.4；之后完整可读到 b92.2（5.8 拍 ≈ 2.6 s）
  const W = ['An ', 'Assistant ', 'Redesign ', 'for ', 'everyone ', '&amp; ', '<b>every </b>', '<b>agent</b>'];
  txt(TAG0, END, [['cl-tag', W.map((w) => '<span class="w">' + w + '</span>').join('')]], { x: 960, y: 648, align: 'c' },
    { anim: K.words({ at: [0, .2, .4, .6, .8, 1.0, 1.2, 1.4], out: 1.8 }), tick: pushT(648) });
});
