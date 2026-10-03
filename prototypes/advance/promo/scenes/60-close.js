/* 60-close 6–7（b69.2–94） — STORYBOARD.md v17.1 T13（5 → 6 交接 b69.2）与 v17「6」「7」、「转场关键帧」H14–H17、M6–M9.
   合并点在画面中心 (960, 540) 螺旋放出，各自身后画出一段圆弧，5 段合成收拢罗盘（= R 300 圆环）→ 展开成罗盘（你的类型的花）→
   再收回圆环 → 圆环平着长出螺旋（与 2.2 同一个镜头）→ 立起成 45° Orbit 标志，在画面正中停留约 1.2 s（慢慢呼吸）、点沿圆环两侧
   滑到它下方排成一行 → v17.4：标志按 logo kit 的 reveal（scenes/03-wordmark.js）继续绕轴转身成 O、向左展开成居中的「Orbit·知音」
   → 字标下方「An Assistant Redesign for everyone & every agent」、点收成标语下的一小行 → 可读停留 ≥ 2.5 s → 一起淡出到全黑。
   v17.4 时序（场景拍）：ICON 到位 b78.4、停留到 b81.0、转身 b81.0–84.3、字母 b83.475–85.85、标语 b85.0–86.4、淡出 b92.2–94（END 89 → 94）。
   v17.6（用户：「先出现曲线再曲线动画成 orbit」）：圆环收回后不再从环尾长出俯视螺旋，而是先「画」曲线——orbitSVG 从内端 t 0 一笔画到
   外端 t 1（kit 的近粗远细、两端渐细，头部一团柔光），5 个点从圆环飞到笔头、排成一串紧跟在笔头后面骑着这条线走，圆环在外圈画到时
   淡掉；画完后整条曲线连同骑在上面的点一起转身、倾倒成正中的 45° App 图标（黑夜版白线），点落到下方一行，短暂停留，再按 kit reveal
   展开成字标，转身时颜色由白线过渡到字标的香槟黄（brand.md：深色底字标 #d6c7a1，不用纯白）。
   v17.6 时序（场景拍）：笔画 b75.6–78.6、转身倒成图标 b78.6–80.2、停留到 b81.8、转身 b81.8–85.1、标语 b85.8、淡出 b93.0–94.8（END 94 → 94.8）。
   本场景拥有：deck 2（b69.2 起）、标志 markAt M6–M7 与片尾字标层、AGD 的 b69.2 / 78.0 / 85.2 / 92.2 四个 key 与 b69.2–71.4 的螺旋 follow、片尾标语。
   v17.3 看清文字：罗盘展开后多停 1 拍（插在 b73.2，之后一切 +1，END 88 → 89）——展开提前到 b71.04（圆环合成整圈即开，不再空等 .16 拍），
   类型码 b72.64 全亮、b74.2 才开始收回，完整可读 1.56 拍（DIMV 加粗那一个约 1.9 拍）；停留时不定格：花继续慢慢开、慢转 ±10°，
   deck 2 慢推 1 → 1.025（收回圆环时同一段 E.inOut 退回 1，b75.4 圆环仍是 R 300，接 M6）。
   v17.7 点形态（AGD.morph，场景拍，片长不变）：b69.2 回 dot（合并 orb 拆开）· b69.5–70.9 各点 head 拖出圆弧 · b71.95 petal 合拢
   （hold .3）· b72.64 glow 顺时针扫过 · b74.3 bead 沿圆环切线 · b75.3 bead 飞向笔头（按像素间距排串，gm 领头 b75.55 变 head，
   gm / cp 在这里淡入）· 圆环 b75.8–77.6 从笔头方位向两侧退开 · b78.6 head 回 bead · b79.1 落行 dot r 22、b80.45 慢呼吸 ·
   LET0 起点行从左到右轻提 4 px · 标语行 r 16 / gap 56，逐词 glow .2 · b87.2 起 bullet + ✓ 依次扫过 · b93.0 合成 orb（r 30）与字标一起淡到全黑。 */
scene('60-close', () => {
  const PC = [960, 540];
  // v17.6 片尾：画曲线（D0–D1）→ 转身倒成 45° 图标（D1–M1）→ 正中停留 → 转身向左展开成字标 → 标语 → 点一行 → 可读停留 → 淡出（场景拍）
  const D0 = 75.6, D1 = 78.6, M1 = 80.2;
  const TURN0 = 81.8, LET0 = TURN0 + .75 * WORDMARK.T, TAG0 = TURN0 + 4.0, TAG_AG = TAG0 + 1.4, FADE0 = TURN0 + 11.2;
  END = TURN0 + 13.0;
  // 片尾慢推：字标转身起（TURN0）到 END 由 1 匀速推到 1.06，前 20 % 二次缓起
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
  // v17.7 交接：orb 里的 5 个小徽章（02-agents micro：logo 点外 .5R、半径 .3R、方位 6·b + 72i − 90，R = r·k 1.15）就是拆开后的 5 个点——
  // 点 i 从自己那枚小徽章的位置与大小起步（点 0 带着 orb 在拆开的前 .5 拍缩到 cc 小徽章处），不再 5 个都以 orb 的 r 40 叠在中心、
  // 先闪成一颗 cc 大点
  const spMini = (i, b) => {
    const s = s0(0), R = s.r * 1.15, a = (6 * (HB + (SHIFT['60-close'] || 0)) + 72 * i - 90) * Math.PI / 180;
    const u = i ? 1 : E.inOut(clamp((b - HB) / .5));
    return { x: s.x + .5 * R * Math.cos(a) * u, y: s.y + .5 * R * Math.sin(a) * u, r: lerp(s.r, .3 * R, u) };
  };

  /* ---------- deck 2：收拢罗盘 = 圆环 → 罗盘 → 圆环（H13–H15） ---------- */
  // b69.2 直接设定：罗盘中心 (400, 400) → 舞台 (960, 540)，不倾斜（6.3：orbitSVG 是正交投影，倾倒会对不上）；s 从 .001
  // 随点的半径长到 1（b70.92，罗盘 b71.04 展开前已是 1）；这时圆环的裁剪全是空的（5 段长度都是 0），画面上只有中心的合并点
  tween(2, HB, 0, { x: 400, y: 400, s: SP_S0, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, HB, SP_RD, { s: 1 }, spRing);
  // 读类型码时慢推 1 → 1.025（b72.2–74.2，sine），收回圆环时同一段退回 1（b74.2–75.4，与 fold 同曲线），M6 起圆环仍是 R 300
  tween(2, 72.2, 2.0, { s: 1.025 }, E.sine);
  tween(2, 74.2, 1.2, { s: 1 }, E.inOut);
  tween(2, 75.8, 1.8, { o: 0 }, E.inOut);                     // v17.6：曲线画起来时圆环淡出，外圈画到时已看不见（drawCompass 继续到 b80.8）
  let degMe = null;
  // drawCompass 每帧调用到 b80.8（AGD 的 compass 编队要读点位，直到 row 在 b80.56 落定）；一切都是 b 的纯函数
  drive(2, HB, 80.8, (p, b) => {
    if (degMe == null) { const D = compassData(); degMe = D.mineIdx >= 0 ? D.mineIdx * 22.5 + 11.25 : 11.25; }
    const open = E.inOut(lp(b, SP_END, 1.6)), fold = E.inOut(lp(b, 74.2, 1.2));
    const on = E.inOut(lp(b, 71.44, 1.2)) * (1 - fold);       // dial / core：b71.44–72.64 出现（与 open 同时到 1），b74.2–75.4 淡出
    // T13：圆环由点画出——第 i 段从上一个徽章的方位起、长 G_i·e_i，紧跟在点 i 身后（起点往回多 .6° 盖住相邻两段接缝的抗锯齿，
    // 这 .6° 也随 e_i 长出，开头不会先冒出一小截）；b71.04 合成整圈后不再裁剪
    // v17.7：曲线画起后圆环从笔头的方位向两侧退开（缺口以笔头方位为中心、b75.8–77.6 张到整圈），与 deck 2 的淡出同段，视线留在笔头
    const g = 360 * E.inOut(lp(b, 75.8, 1.8)), pen = g > .01 ? penBearing(b) : 0;
    const segs = b < SP_END ? spG().map(([d, G], i) => [d - G - .6, (G + .6) * spE(i, b)]) : g > .01 ? [[pen + g / 2, Math.max(0, 360 - g)]] : undefined;
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
  AGD.key(HB, 'compass', { dur: .7, stag: 0 });            // v17.7：.4 → .7，orb 拆开与 head 冒出同段（不先闪成一颗 cc 大点）
  AGD.follow(69.0, 71.4, (i, b) => {
    if (b < HB) return null;
    // R = 徽章到中心的实际距离 = 圆环当帧半径（deck 2 的 s 已随点放大，不再乘 e_i）；徽章大小按 s 1 的 19 取
    const e = spE(i, b), G = spG()[i][1], c = cpBadge(i), C = cpStage(400, 400), s = spMini(i, b);
    const dc = Math.atan2(c.x - C[0], -(c.y - C[1])) / (Math.PI / 180), R = Math.hypot(c.x - C[0], c.y - C[1]), th = (dc - G * (1 - e)) * Math.PI / 180;
    return { x: C[0] + R * Math.sin(th) + (s.x - C[0]) * (1 - e), y: C[1] - R * Math.cos(th) + (s.y - C[1]) * (1 - e), r: lerp(s.r, c.r / decks[2].C.s, e) };
  }, { blend: .2 });
  /* v17.7 F3「6」形态（场景拍）：
     · b69.2 先显式回 dot（50-tools 交来的合并 orb 随 compass 键 .4 拍拆开）；b69.5 + .06i 起每个点变 head（rot 'vel'，尾尖朝着
       身后刚画出的圆弧，弧就是彗星尾迹），e_i 到 .7 左右（b70.35 + .06i）回 dot，合成整圈时已是圆徽章骑在罗盘外圈上
     · 花开到位（b71.95）五点一起朝花心收成 petal（hold .3，同 3 的合拢），类型码全亮 b72.64 起 glow 顺时针扫过（cc cx ds cp gm）
     · 收回圆环（b74.3–74.9）dot → bead，rot 取圆环切线（同 1e 穿在 R 300 圆环上的样子） */
  const DEG = 180 / Math.PI, CW = [0, 1, 3, 4, 2];
  AGD.morph(HB, 0, 'dot', { dur: .4 });
  // 点 1–4 拆开时就是普通圆徽章（'bead' 参数写成与 dot 完全相同）：'dot' 在 merged > 0 时会混入 orb，各点自带 5 枚小徽章与色弧、
  // 叠在 orb 上成一团重影；用不触发 orb 混合的同形写法，它们从 orb 里的小徽章原样长出
  AGD.morph(HB, [1, 2, 3, 4], 'bead', { w: 2, h: 2, rad: 1, rot: 0, ls: 1, dur: .01, stag: 0 });
  for (let i = 0; i < 5; i++) {
    AGD.morph(HB + .3 + .06 * i, i, 'head', { dur: .4, glow: .35 });
    AGD.morph(HB + 1.15 + .06 * i, i, 'dot', { dur: .45 });
  }
  AGD.morph(71.95, 'all', 'petal', { dur: .45, stag: 0, aim: PC, ls: .95, hold: .3, back: .55 });
  CW.forEach((i, k) => AGD.glow(i, 72.64 + .12 * k, 73.24 + .12 * k, .55));
  const tanRot = (b, i) => { const p = AGD.pos(i, b); return Math.atan2(p.y - PC[1], p.x - PC[0]) * DEG + 90; };
  AGD.morph(74.3, 'all', 'bead', { dur: .6, stag: 0, rot: tanRot });
  /* v17.6 画曲线 → 转身成图标 → 落成一行（H16 / 7.1）：
     曲线 pose(b)：D0–D1 俯视附近（R 300 = 圆环、pitch 90 → 80、yaw −100 → −70 慢慢转），笔头 t = sine 从 0 画到 1；
     D1–M1 整条线转身、倾倒到 ICON（yaw −70 → 20、pitch 80 → 45、R 300 → 230、cy 540 → 520，E.inOut）；之后正中停留、R 慢慢 × 1.03。
     5 个点在 b75.3 起 1 拍内从圆环飞到笔头，排成一串跟在笔头后面骑着线走（第 k 位在 t − .045 − .05k，起笔时都挤在内端，像在给笔头
     「喂墨」）；画完后停在外圈上随曲线一起转身，D1 + .5 起 1.3 拍落到图标下方的一行（row 键的位置，r 20）。
     一行从左到右按罗盘上的方位排（gm 288° · cp 221° · ds 118° · cx 62° · cc 43°）；串里也按这个顺序（gm 领头）。 */
  const ROW = [4, 3, 0, 2, 1], LTR = [2, 4, 3, 1, 0];          // ROW[i] = 点 i 的位次；LTR[k] = 第 k 位（从左数）的点
  const strokeT = (b) => E.sine(lp(b, D0, D1 - D0));
  const pose = (b) => {
    const d = lp(b, D0, D1 - D0), e = E.inOut(lp(b, D1, M1 - D1)), s = 1 + .03 * E.sine(lp(b, M1, TURN0 - M1));
    return { cx: 960, cy: lerp(540, 520, e), R: lerp(300, 230, e) * s, yaw: lerp(lerp(-100, -70, E.sine(d)), 20, e), pitch: lerp(lerp(90, 80, d), 45, e) };
  };
  let PTS = null;                                              // orbitPts 按姿态缓存（同一帧 5 个点共用）
  const curveAt = (P, t) => {
    const key = P.yaw.toFixed(4) + '/' + P.pitch.toFixed(4);
    if (!PTS || PTS.key !== key) PTS = { key, q: orbitPts(P.yaw, P.pitch) };
    const q = PTS.q[Math.round(clamp(t) * ORB.N)];
    return [P.cx + q[0] * P.R, P.cy + q[1] * P.R];
  };
  // 曲线上从 t 往回走 dpx 像素（屏幕弧长）的参数——笔串按像素排，不按 t（内圈外圈间距一样，珠子不互相叠）
  const backT = (P, t, dpx) => {
    curveAt(P, t);
    const q = PTS.q; let n = Math.round(clamp(t) * ORB.N), acc = 0;
    while (n > 0 && acc < dpx) { acc += Math.hypot(q[n][0] - q[n - 1][0], q[n][1] - q[n - 1][1]) * P.R; n--; }
    return n / ORB.N;
  };
  // 串里第 k 位的屏幕位置：曲线还不够长（起笔时）就沿内端切线往回延长剩下的像素——珠子在内端排成一小列「排队喂墨」，不叠在一起
  const backXY = (P, t, dpx) => {
    const u = backT(P, t, dpx), [x, y] = curveAt(P, u);
    if (u > 0) return [x, y];
    const q = PTS.q; let n = Math.round(clamp(t) * ORB.N), acc = 0;
    for (let j = n; j > 0; j--) acc += Math.hypot(q[j][0] - q[j - 1][0], q[j][1] - q[j - 1][1]) * P.R;
    const m = Math.min(4, ORB.N), dx = q[0][0] - q[m][0], dy = q[0][1] - q[m][1], L = Math.hypot(dx, dy) || 1, rest = Math.max(0, dpx - acc);
    return [x + dx / L * rest, y + dy / L * rest];
  };
  const penBearing = (b) => { const [x, y] = curveAt(pose(b), strokeT(b)); return Math.atan2(x - PC[0], -(y - PC[1])) * DEG; };
  // v17.7 笔串：第 k 位（0 = 串头 gm）到笔头的像素距离与半径。串头是 head（尖朝后），圆头离笔头柔光外缘约 8 px，不盖住它；
  // 其余是 bead（rot 'vel'，ls 1.05：r 15–17 时 logo ≈ 20 px）。尺寸串尾到串头 × 1 / .96 / .92 / .88 / .84（基数 r 17）
  const STR_R = [.84, .88, .92, .96, 1].map((k) => 17 * k), STR_D = [56, 118, 166, 214, 262];
  const ROW0 = { cx: 960, y: 780, gap: 72, r: 22, order: ROW };
  AGD.key(78.8, 'row', Object.assign({ dur: 1.6, ease: E.sine, stag: .04, polar: PC }, ROW0));
  // 落位直接奔向一行的最终格位（静态），不追 row 键还在极坐标过渡中的位置——否则点会穿过图标中间、互相叠住、到位前排不齐
  const ROWP = AGD.pts('row', ROW0);
  AGD.follow(75.3, 81.2, (i, b) => {
    const P = pose(b), k = ROW[i], [x, y] = backXY(P, strokeT(b), STR_D[k]), e = E.inOut(lp(b, D1 + .5, 1.3));
    // a 1：罗盘上没有数据的 Agent（徽章 a 0）在飞向笔头时淡入，五个点一起推笔
    return { x: lerp(x, ROWP[i][0], e), y: lerp(y, ROWP[i][1], e), r: lerp(STR_R[k], ROW0.r, e), a: 1 };
  }, { blend: 1.0 });
  /* v17.7 F3「6」笔串与落行（场景拍）：b75.3 起飞向笔头时 bead 改 rot 'vel'；串头 gm b75.5 变 head（glow .4、ls .7），五个 Agent
     一起「推着笔」；画完（D1）head 回 bead，b79.1 起落行时 bead → dot（r 22），停在图标下方时慢呼吸 */
  const LEAD = LTR[0];
  AGD.morph(75.3, 'all', 'bead', { dur: .5, stag: .03, rot: 'vel', ls: 1.05 });
  AGD.morph(75.55, LEAD, 'head', { dur: .5, glow: .4, ls: .7 });
  AGD.morph(D1, LEAD, 'bead', { dur: .5, rot: 'vel', ls: 1.05 });
  AGD.morph(D1 + .5, LTR, 'dot', { dur: .9, stag: .05 });
  LTR.forEach((i, k) => AGD.pulse(i, 80.45 + .1 * k, 1.05, 1.3));
  // v17.4：标语出现时（TAG0）点收成标语下方的一小行，b86.9 落定
  // v17.7：标语下一行 r 13 → 16（logo ≈ 21 px），间距 50 → 56
  AGD.key(TAG0 + .2, 'row', { cx: 960, y: 736, gap: 56, r: 16, order: ROW, dur: 1.4, ease: E.sine, stag: .06 });
  // v17.7 7.1：字母「rbit·知音」从左到右升起（LET0 起，kit 110 ms 错开）时，点行跟着从左到右轻提 4 px，像一道波
  const lift = (i, b) => 4 * Math.sin(Math.PI * clamp((b - LET0 - .2 * ROW[i]) / .7));
  // 7.4：片尾不定格——字标、字、点一起以 (960, 540) 为中心慢推（push），点另有 2px 漂移；follow 到 END + 1 才淡出（混回不落在片内）
  AGD.follow(TURN0 - .6, END + 1, (i, b, q) => {
    const s = push(b);
    return { x: 960 + (q.x - 960) * s + 2 * Math.sin(2 * Math.PI * (b / (9 + 3 * hash01(i, 8)) + hash01(i, 9))), y: 540 + (q.y - 540) * s - lift(i, b) + 2 * Math.sin(2 * Math.PI * (b / (11 + 3 * hash01(i, 10)) + hash01(i, 11))), r: q.r * s };
  }, { blend: .6 });
  // v17.7 7.3：标语逐词出现时，词下方的点 glow .2（Redesign 下两点 · for 下中间一点 · everyone 下两点），像被点逐个点亮
  [.4, .4, .6, .8, .8].forEach((w, k) => AGD.glow(LTR[k], TAG0 + w, TAG0 + w + .7, .2));
  // 「agent」落定（TAG_AG）时 5 个点从左到右依次变 bullet 并画出 ✓（间隔 .16 拍，各 .5 拍），读作「every agent ✓」，再回 dot
  LTR.forEach((i, k) => {
    AGD.morph(TAG_AG + .16 * k, i, 'bullet', { tick: 1, dur: .25, hold: .25, back: .35 });
    AGD.glow(i, TAG_AG + .16 * k, TAG_AG + .5 + .16 * k, .5);
  });
  // v17.7 H17：不再原地缩小——五点在约 1 拍内向行中心合成 orb（r 30，与开场 b0.2 的 orb 同大），再与字标、标语一起淡到全黑
  AGD.key(FADE0, 'merge', { x: 960, y: 736, r: (b) => lerp(16, 30, E.inOut(lp(b, FADE0 + .45, .55))), a: (b) => 1 - E.inOut(lp(b, FADE0, 1.8)), dur: .85, stag: .04, spin: 6 });

  /* ---------- 标志：画曲线 → 45° 图标 → 正中停留 → 字标（logo kit reveal，scenes/03-wordmark.js） ---------- */
  // 白线 = App 图标黑夜版（#fff）；字标 = 深色底的香槟黄 #d6c7a1（brand.md），转身 v 0 → 1 时由白过渡到香槟黄
  const NIGHT_WORD = [214, 199, 161];
  const inkAt = (v) => 'rgb(' + NIGHT_WORD.map((c) => Math.round(lerp(255, c, v))).join(',') + ')';
  const icon = (b) => pose(b);
  markAt(D0, TURN0, (p, b) => {
    const t = strokeT(b);
    return Object.assign(pose(b), { t: Math.max(.002, t), a: E.out(lp(b, D0, .25)), head: E.out(lp(b, D0, .3)) * clamp((1 - t) / .04), color: '#ffffff' });
  });
  // 字标段（b81.8–END）：kit 的帧原样——标志绕自身轴再转一圈成为字标的 O、向左滑到 O 的位置，「rbit·知音」在它右边逐字升起
  // （kit 时序：转 T = 3.3 拍、字母自 .75T 起 110 ms 错开、各 420 ms）；第 0 帧由 WORDMARK.place 与 b81.8 的 ICON 姿态精确重合，
  // 摆放从那里移到读字位置（字标整体居中 (960, 470)、k .5 ≈ 1160 px 宽），之后随 push 慢推；FADE0–END 与标语、点一起淡出
  let P0 = null;
  const readAt = (b) => { const s = push(b); return { cx: 960, cy: 540 + (470 - 540) * s, k: .5 * s }; };
  markAt(TURN0, END, (p, b) => {
    if (!WORDMARK.F) return Object.assign(icon(TURN0), { a: 1 - E.inOut(lp(b, FADE0, 1.8)), color: '#ffffff' });   // frames missing: keep the icon
    P0 = P0 || WORDMARK.place(icon(TURN0));
    const v = E.inOut(lp(b, TURN0, WORDMARK.T)), r = readAt(b);
    WORDMARK.add(WORDMARK.svg({ a: 1 - E.inOut(lp(b, FADE0, 1.8)), cx: lerp(P0.cx, r.cx, v), cy: lerp(P0.cy, r.cy, v), k: lerp(P0.k, r.k, v), v, b, on: LET0, color: inkAt(v) }));
    return null;
  });

  /* ---------- 片尾标语（7.3，FADE0–END 与字标、点一起淡出） ---------- */
  css(`
.cl-tag{font-size:48px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.01em}
.cl-tag b{color:var(--acc);font-weight:600}
`);
  // 字随片尾慢推一起放大：锚点 y 相对 540 外移 × push，字号 × push（tick 在 anim 之后覆盖 transform）
  const pushT = (y) => (el, tl, life, ts) => { const s = push(ts / BEAT); el.style.transform = 'translate(-50%,-50%) translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')'; };
  // 标语在最后两个字升起时（TAG0 b85.8）居中出现在字标下方，逐词间隔 .2 拍，「agent」b87.2；之后完整可读到 FADE0 b93.0（5.8 拍 ≈ 2.6 s）
  const W = ['An ', 'Assistant ', 'Redesign ', 'for ', 'everyone ', '&amp; ', '<b>every </b>', '<b>agent</b>'];
  txt(TAG0, END, [['cl-tag', W.map((w) => '<span class="w">' + w + '</span>').join('')]], { x: 960, y: 648, align: 'c' },
    { anim: K.words({ at: [0, .2, .4, .6, .8, 1.0, 1.2, 1.4], out: 1.8 }), tick: pushT(648) });
});
