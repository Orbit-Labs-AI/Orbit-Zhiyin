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
   LET0 起点行从左到右轻提 4 px · 标语行 r 16 / gap 56，逐词 glow .2 · b87.2 起 bullet + ✓ 依次扫过 · b93.0 合成 orb（r 30）与字标一起淡到全黑。
   v18.1（片长 −.8 拍：TURN0 81.8 → 81.0、END 94.8 → 94.0，成片 END 130.9 = 59.50 s）：b69.2 orb 先就地散开（compass 键 .35、
   cc 不带 logo 缩到 .3R，b69.4 起才挪到小徽章处，去掉 b106.4 的重影）；拆开后 .3 拍内各点长到 r ≥ 15，head 保持圆徽章大小只加尾巴；
   停留 b80.2–81.0 标志整体匀速放大 1 → 1.015（只缩放）、点行一道 ±3 px 的波从左到右走过；标语改为
   「Redesigning Agent workflow for everyone & every agent」（8 个 token，K.words 时序不变）。
   v18.7（D1–D3，片长不变，替代上面 v17.7 的 head / petal / bullet）：b69.2 AGD.open（.6 拍，sine）打开 17 系列合并徽章——cc 留在
   中心不缩小、b69.5 起再走螺旋，其余四段弧滑出成圆 logo 徽章，b69.7–69.9 依次闪；b71.95 五点一起闪（原 petal）；b74.3 圆环上
   bead 保留，b75.3 起骑笔全程圆徽章、gm b75.55 闪一下（笔头柔光领头，无 head）；标语下 ✓ 画在圆徽章旁并闪（无 bullet）；
   b92.2 merge + b92.45 AGD.seal（.6 拍）合回 cc 徽章 + 五色弧（b93.04 起 'orb'），与字标一起淡出。 */
scene('60-close', () => {
  const PC = [960, 540];
  // v17.6 片尾：画曲线（D0–D1）→ 转身倒成 45° 图标（D1–M1）→ 正中停留 → 转身向左展开成字标 → 标语 → 点一行 → 可读停留 → 淡出（场景拍）
  const D0 = 75.6, D1 = 78.6, M1 = 80.2;
  // v18.5：TURN0 81.0 → 80.4（标语多 .6 拍可读），END / FADE0 写死字面量，片长与淡出点不变；转身自 W0 = TURN0 − .3 起（M1 前 .1 拍，
  // 倾倒已 99.9 % 到位），v 跨 T + .3 拍；QA：v 用 E.sine（E.inOut 在 b118.3 只有 .01，b118.8 才看得出），成片 b118.3 起就看得出在转
  const TURN0 = 80.4, W0 = TURN0 - .3, LET0 = TURN0 + .75 * WORDMARK.T, TAG0 = TURN0 + 4.0, TAG_AG = TAG0 + 1.4, FADE0 = 92.2;
  END = 94.0;
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
  const spEase = (p) => Math.max(spRing(p), SP_R0 / 300 * E.out(clamp(p * SP_RD / SP_POP))), spS = (b) => lerp(SP_S0, 1, spEase(clamp((b - HB) / SP_RD)));
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
  // v18.2：分裂第一帧起 5 个点（含 cc）就是 orb 里的 5 枚小徽章（位置、大小原样，r .3R ≈ 14），随即沿各自方向弹出到
  // 半径约 70 的一圈（SP_POP 拍，E.out）——整团从 orb 的约 100 px 直接长大，不再先缩成一小团；圆环同步撑到 70，点一落圈就骑在环上。
  // 方位用极坐标：从小徽章方位 β_i 随 e_i 滑到螺旋方位（差值取近的一边；随 e 走，圆还小时相邻点不挤在 cc 43° / cx 62° 这种近方位上），
  // 途中分道：gm 要越过 ds / cp，走外道（+72 px），ds / cp 让到内道（−26）；cc 紧跟 cx，cc 走内道 −30、cx 外道 +34，彗星尾不压 logo
  const SP_POP = .5, SP_R0 = 70, SP_LANE = [-30, 34, 72, -26, -26];
  // v18.6 R1：合并态是一个圆（02-agents orb：深色圆盘 + 贴边五色 72° 弧，无小徽章）——点 i 从圆的边缘、自己那段颜色弧的正中
  // 冒出（起点在边内 .85R、半径 .2R 的小圆徽章），随即照原 SP_POP 弹到 SP_R0 一圈；不再读 micro 小徽章的位置
  const spSpin = () => { const fb = HB + (SHIFT['60-close'] || 0), mK = AGD_KEYS.filter((k) => k.form === 'merge' && k.b <= fb).pop(); return mK ? agV(mK.o, 'spin', 6, fb, 0, mK.sh) * (fb - mK.b) : 6 * fb; };
  let SPO = null;
  const spOrb = () => SPO || (SPO = ((s) => { const R = s.r * 1.15; return { x: s.x, y: s.y, R, m: .85 * R, r: .2 * R, sp: spSpin() }; })(s0(0)));
  const spBeta = (i) => spOrb().sp + 72 * i + 36;                                // 颜色弧 i 的正中方位（罗盘角，顺时针，0 = 上）

  /* ---------- deck 2：收拢罗盘 = 圆环 → 罗盘 → 圆环（H13–H15） ---------- */
  // b69.2 直接设定：罗盘中心 (400, 400) → 舞台 (960, 540)，不倾斜（6.3：orbitSVG 是正交投影，倾倒会对不上）；s 从 .001
  // 随点的半径长到 1（b70.92，罗盘 b71.04 展开前已是 1）；这时圆环的裁剪全是空的（5 段长度都是 0），画面上只有中心的合并点
  tween(2, HB, 0, { x: 400, y: 400, s: SP_S0, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  // v18.2：前 SP_POP 拍圆环至少撑到 SP_R0（点弹出的那一圈），之后照常按 spRing 长到 1
  tween(2, HB, SP_RD, { s: 1 }, spEase);
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
    const segs = b < SP_END ? spG().map(([d, G], i) => { const a = d - G - .6; let L = spWrap(spPolar(i, b).th - SP_HS(i, b) - a); if (L > 300) L = 0; return [a, Math.min(L, G + .6)]; }) : g > .01 ? [[pen + g / 2, Math.max(0, 360 - g)]] : undefined;
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
  AGD.key(HB, 'compass', { dur: .01, stag: 0 });         // v18.2：.35 → .01——merged 必须一帧内归零：02-agents 在 merged > .6 时隐藏点 1–4，.1 拍时 b106.91 一帧只剩 cc 和空圆盘（QA）
  // v18.2 orb 外壳：分裂那一刻 5 枚小徽章原样成为 5 个点，orb 的深色圆盘与五色细弧画在点的下层（AGD.back），随点一起
  // 张开到约 SP_R0 + 10 并在 .45 拍内淡掉——五色弧张到点落圈的半径，交给随后画出的圆环；不再在点上面盖一个缩小的 orb
  // v18.7 D2：合并态是 17 系列的合并徽章（cc 的 logo 徽章 + 五色 72° 弧，50-tools 交来），由 AGD.open 用自己的弧打开：
  // cc 留在中心，其余四段弧沿 cc 边滑出、缩成点，各 Agent 的圆形 logo 徽章从弧里长出（不再画 v18.6 的暗盘外壳）
  const SP_OPEN = .6;
  AGD.open(HB, SP_OPEN, { ease: E.sine });
  // cc 在打开期间留在中心、保持合并时的大小，HB + .3 起再沿螺旋走出去（gc：0 = 中心）
  const spCC = (b) => E.inOut(lp(b, HB + .3, .8));
  // 点 i 在 b 的极坐标：中心 (cx, cy)、方位 th（度，罗盘角）、半径 rad；R 是圆环当帧半径（舞台 px），ring = [d0, G]
  const spPolar = (i, b) => {
    // R = 徽章到中心的实际距离 = 圆环当帧半径（deck 2 的 s 已随点放大，不再乘 e_i）；徽章大小按 s 1 的 19 取
    const e = spE(i, b), [d0, G] = spG()[i], c = cpBadge(i), C = cpStage(400, 400), O = spOrb();
    // v18.7：R 按 deck 2 在 b 时的 s（解析式 spS）换算，不用相机当帧的 s——AGD.open 会在窗口开头预读 b + dur 的点位，
    // 用当帧（s ≈ .001）的相机会把点算到 cc 里面，弧段就钻到 cc 徽章下面看不见
    const dc = Math.atan2(c.x - C[0], -(c.y - C[1])) / (Math.PI / 180), R = Math.hypot(c.x - C[0], c.y - C[1]) * spS(b) / decks[2].C.s;
    let D = spWrap(spBeta(i) - (d0 - G)); if (D > 180) D -= 360;               // 小徽章方位 − 螺旋起点方位（近的一边）
    const pop = E.out(lp(b, HB, SP_POP)), wA = e, gc = i ? 1 : spCC(b);
    return { e, d0, G, c, C, O, R, th: dc - G * (1 - e) + D * (1 - wA), rad: (lerp(O.m, R, pop) + SP_LANE[i] * Math.sin(Math.PI * wA)) * gc, cx: lerp(O.x, C[0], pop), cy: lerp(O.y, C[1], pop) };
  };
  AGD.follow(69.0, 71.4, (i, b) => {
    if (b <= HB) return null;                                  // b69.2 这一帧仍是完整的 orb（50-tools 交来的 r 40）
    const P = spPolar(i, b), th = P.th * Math.PI / 180;
    if (!i) { const g = spCC(b), r1 = Math.max(lerp(P.O.r, P.c.r / decks[2].C.s, P.e), 16); return { x: P.cx + P.rad * Math.sin(th), y: P.cy - P.rad * Math.cos(th), r: lerp(s0(0).r, r1, g) }; }   // D2：cc 是中心徽章，打开时不缩小
    // 第一帧 r = 小徽章的 .3R（≈ 14），.35 拍内长到 16（logo ≈ 27 px），之后再随 e 长到罗盘徽章的 19
    return { x: P.cx + P.rad * Math.sin(th), y: P.cy - P.rad * Math.cos(th), r: Math.max(lerp(P.O.r, P.c.r / decks[2].C.s, P.e), lerp(P.O.r, 16, E.out(lp(b, HB, .35)))) * lerp(.25, 1, E.out(lp(b, HB, .22))) };   // QA：从弧上一颗小点长出，不在交接帧一下冒出 5 枚满 logo 徽章
  }, { blend: .2 });
  /* v18.4 圆弧头接到点上：点在螺旋途中走分道（SP_LANE）、方位还带着小徽章起点的偏差，罗盘画的圆弧却在圆环半径上——b107.5–107.7
     弧头离点头几十 px。现在罗盘的第 i 段只画到弧头前 SP_HS 度，最后这一截由这里在点的下层画：从圆环上平滑弯到点心
     （同圆环的白 .6 / 2.4·s 描边），点到位（e = 1）时分道与偏差都归零、这一截与圆环重合，SP_END 起交回整圈 */
  const SP_HS = (i, b) => Math.min(36, spG()[i][1] * spE(i, b));
  AGD.back(HB, SP_END, (b) => {
    const C = cpStage(400, 400), Rr = Math.hypot(...((q) => [q[0] - C[0], q[1] - C[1]])(cpStage(400, 100))), w = 2.4 * decks[2].C.s;
    let s = '';
    for (let i = 0; i < 5; i++) {
      const P = spPolar(i, b), hs = SP_HS(i, b); if (hs < .3) continue;
      // 这一截从点身后 hs 度的圆环上起，向前弯到点心（只向前，不回钩）；罗盘那段画到同一方位为止
      let d = '';
      for (let n = 0; n <= 24; n++) {
        const u = n / 24, m = u * u * (3 - 2 * u), th = (P.th - hs * (1 - u)) * Math.PI / 180, r = lerp(Rr, P.rad, m);
        const x = lerp(C[0], P.cx, m) + r * Math.sin(th), y = lerp(C[1], P.cy, m) - r * Math.cos(th);
        d += (n ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
      }
      s += '<path d="' + d + '" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="' + w.toFixed(2) + '"/>';
    }
    return s;
  });
  /* v17.7 F3「6」形态（场景拍）：
     · b69.2 先显式回 dot（50-tools 交来的合并 orb 随 compass 键 .4 拍拆开）；b69.5 + .06i 起每个点变 head（rot 'vel'，尾尖朝着
       身后刚画出的圆弧，弧就是彗星尾迹），e_i 到 .7 左右（b70.35 + .06i）回 dot，合成整圈时已是圆徽章骑在罗盘外圈上
     · 花开到位（b71.95）五点一起朝花心收成 petal（hold .3，同 3 的合拢），类型码全亮 b72.64 起 glow 顺时针扫过（cc cx ds cp gm）
     · 收回圆环（b74.3–74.9）dot → bead，rot 取圆环切线（同 1e 穿在 R 300 圆环上的样子） */
  const DEG = 180 / Math.PI, CW = [0, 1, 3, 4, 2];
  AGD.noStretch(HB, HB + 2.2);                                // v18.6：螺旋途中不做速度拉伸，点始终是圆徽章
  AGD.morph(HB, 0, 'bead', { w: 2, h: 2, rad: 1, rot: 0, ls: 1, dur: .01 });  // v18.2：cc 第一帧就在自己的小徽章处、同大小；orb 的外壳交给下面的 AGD.back 张开淡掉   // QA：不走 'dot'（会混入 orb，b106.3 缩小的 orb 里 5 枚小徽章与点 1–4 叠成重影），cc logo 随 orb 缩到 .3R 淡入，不再留一颗无 logo 的空圆盖住点 1–4
  // 点 1–4 拆开时就是普通圆徽章（'bead' 参数写成与 dot 完全相同）：'dot' 在 merged > 0 时会混入 orb，各点自带 5 枚小徽章与色弧、
  // 叠在 orb 上成一团重影；用不触发 orb 混合的同形写法，它们从 orb 里的小徽章原样长出
  AGD.morph(HB, [1, 2, 3, 4], 'bead', { w: 2, h: 2, rad: 1, rot: 0, ls: 1, dur: .01, stag: 0 });
  for (let i = 0; i < 5; i++) {
    // v18.1：彗星头保持圆徽章的大小（h 2、圆头 rad 1、logo ls 1 在圆头中心），只在身后多出尾巴
    // v18.6：不再变 head 拖尾（b107.4 三颗药丸叠成一团）——保持圆徽章，冒出后依次闪一下（圆形 + 闪烁），身后的圆弧就是轨迹
    AGD.blink(i, HB + .5 + .05 * i, { dur: .3, k: 1.08 });   // v18.7：打开（AGD.open HB–HB + .6）收尾时依次闪
    AGD.morph(HB + 1.15 + .06 * i, i, 'dot', { dur: .45 });
  }
  // v18.7 D1 / D3：花开到位时五个圆 logo 徽章一起闪一下（原 petal 合拢），之后 glow 顺时针扫过
  AGD.blink('all', 71.95, { dur: .4, k: 1.08 });
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
  // v18.1 停留（M1–TURN0，.8 拍）：整枚标志只做匀速放大 1 → 1.015（前 20 % 二次缓起，接上倾倒的减速；只缩放，不重画、不改线宽），
  // 不再定格；TURN0 起 WORDMARK.place 取这一刻的姿态，之后交给 push
  // v18.4：停顿（成片 b116.3–119.3 = 场景 D1 → D1 + 3）改为整体慢推 1 → 1.04（E.inOut）：标志、落行的点、之后的字标 / 标语 / 点
  // 都乘这一层（hold），之后再叠 push；标志本身只等比缩放，不重画、不改线宽
  const holdPush = (b) => 1 + .04 * E.inOut(lp(b, D1, 3.0));
  const S = (b) => holdPush(b) * push(b);
  const pose = (b) => {
    const d = lp(b, D0, D1 - D0), e = E.inOut(lp(b, D1, M1 - D1)), s = holdPush(b);
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
  // v18.7 D3：骑笔的五个点全程是圆 logo 徽章（不再 bead 'vel' / gm 彗星 head），笔画自己的笔头柔光领头；
  // 圆环上的 bead（b74.3）在飞向笔头时收回圆形，串头 gm 搭上笔头时闪一下
  AGD.morph(75.3, 'all', 'dot', { dur: .5, stag: .03 });
  AGD.blink(LEAD, 75.55, { dur: .4, k: 1.08 });
  LTR.forEach((i, k) => AGD.pulse(i, 80.45 + .1 * k, 1.05, 1.3));
  // v17.4：标语出现时（TAG0）点收成标语下方的一小行，b86.9 落定
  // v17.7：标语下一行 r 13 → 16（logo ≈ 21 px），间距 50 → 56；v18.4 标语加大下移后 y 736 → 752
  // v18.5：gap 56 → 68——bullet 的 ✓ 画在点右侧 1.3–2.25 r（r 16 时到 +36 px），56 时离下一枚徽章左缘只剩 4 px，68 时留 16 px
  AGD.key(TAG0 + .2, 'row', { cx: 960, y: 752, gap: 68, r: 16, order: ROW, dur: 1.4, ease: E.sine, stag: .06 });
  // v17.7 7.1：字母「rbit·知音」从左到右升起（LET0 起，kit 110 ms 错开）时，点行跟着从左到右轻提 4 px，像一道波
  const lift = (i, b) => 4 * Math.sin(Math.PI * clamp((b - LET0 - .2 * ROW[i]) / .7));
  // 7.4：片尾不定格——字标、字、点一起以 (960, 540) 为中心慢推（push），点另有 2px 漂移；follow 到 END + 1 才淡出（混回不落在片内）
  // v18.1 停留时点行不定格：落定（b80.4）后一道 ±3 px 的波从左到右走过这一行（周期 1.6 拍，相邻点相差 .9 rad），
  // 字母升起前（LET0 − .3 起 .5 拍）让给 lift
  // v18.4：±3 → ±6 px，相邻点相位错开 .5 拍（周期 1.6 拍），读得出是一道从左到右的波
  const wave = (i, b) => 6 * Math.sin(2 * Math.PI * (b - M1 - .5 * ROW[i]) / 1.6) * E.inOut(lp(b, M1 + .15, .45)) * (1 - E.inOut(lp(b, LET0 - .3, .5)));
  // v18.4：从 D1 起挂上（那时 S = 1，无跳变），落行途中就随 holdPush 一起慢推
  AGD.follow(D1, END + 1, (i, b, q) => {
    const s = S(b);
    return { x: 960 + (q.x - 960) * s + 2 * Math.sin(2 * Math.PI * (b / (9 + 3 * hash01(i, 8)) + hash01(i, 9))), y: 540 + (q.y - 540) * s - lift(i, b) - wave(i, b) + 2 * Math.sin(2 * Math.PI * (b / (11 + 3 * hash01(i, 10)) + hash01(i, 11))), r: q.r * s };
  }, { blend: .5 });
  // v17.7 7.3：标语逐词出现时，词下方的点 glow .2（Redesign 下两点 · for 下中间一点 · everyone 下两点），像被点逐个点亮
  [.4, .4, .6, .8, .8].forEach((w, k) => AGD.glow(LTR[k], TAG0 + w, TAG0 + w + .7, .2));
  // 「agent」落定（TAG_AG）时 5 个点从左到右依次变 bullet 并画出 ✓（间隔 .16 拍，各 .5 拍），读作「every agent ✓」，再回 dot
  LTR.forEach((i, k) => {
    // v18.7 D3：徽章保持圆形（不再 bullet），✓ 画在圆徽章右侧，同时闪一下
    AGD.morph(TAG_AG + .16 * k, i, { tick: 1 }, { dur: .25, hold: .25, back: .35 });
    AGD.blink(i, TAG_AG + .16 * k, { dur: .5, k: 1.06 });
  });
  // v17.7 H17：不再原地缩小——五点在约 1 拍内向行中心合成 orb（r 30，与开场 b0.2 的 orb 同大），再与字标、标语一起淡到全黑
  // v18.7 D2：合成的是 17 系列的合并徽章（cc logo 徽章 + 五色弧）——AGD.seal：各点飞向行中心时变回自己的弧、贴到 cc 徽章边上
  // QA：原 .6 拍 inOut seal + .85 拍 inOut 合拢叠在一起，四枚徽章在约 1 帧内（b92.6–92.7）同时消失 = 跳变；改为 merge 先快后缓（E.out）、
  // seal 1 拍正弦，徽章与弧在约 .6 拍内可见地收拢；淡出改为 b93.1 起 .9 拍（仍止于 b94.0），合并徽章完整可见约 .2 拍
  AGD.key(FADE0, 'merge', { x: 960, y: 752, r: (b) => lerp(16, 30, E.inOut(lp(b, FADE0 + .5, .8))), a: (b) => 1 - E.inOut(lp(b, FADE0 + .9, .9)), dur: 1.0, stag: .04, ease: E.out, spin: 6 });
  AGD.seal(FADE0 + .25, 1.0, { ease: E.sine });
  AGD.morph(FADE0 + 1.24, 0, 'orb', { dur: .01 });

  /* ---------- 标志：画曲线 → 45° 图标 → 正中停留 → 字标（logo kit reveal，scenes/03-wordmark.js） ---------- */
  // 白线 = App 图标黑夜版（#fff）；字标 = 深色底的香槟黄 #d6c7a1（brand.md），转身 v 0 → 1 时由白过渡到香槟黄
  const NIGHT_WORD = [214, 199, 161];
  const inkAt = (v) => 'rgb(' + NIGHT_WORD.map((c) => Math.round(lerp(255, c, v))).join(',') + ')';
  const icon = (b) => pose(b);
  markAt(D0, W0, (p, b) => {
    const t = strokeT(b);
    return Object.assign(pose(b), { t: Math.max(.002, t), a: E.out(lp(b, D0, .25)), head: E.out(lp(b, D0, .3)) * clamp((1 - t) / .04), color: '#ffffff' });
  });
  // 字标段（b81.8–END）：kit 的帧原样——标志绕自身轴再转一圈成为字标的 O、向左滑到 O 的位置，「rbit·知音」在它右边逐字升起
  // （kit 时序：转 T = 3.3 拍、字母自 .75T 起 110 ms 错开、各 420 ms）；第 0 帧由 WORDMARK.place 与 b81.8 的 ICON 姿态精确重合，
  // 摆放从那里移到读字位置（字标整体居中 (960, 470)、k .5 ≈ 1160 px 宽），之后随 push 慢推；FADE0–END 与标语、点一起淡出
  let P0 = null;
  const readAt = (b) => { const s = S(b); return { cx: 960, cy: 540 + (470 - 540) * s, k: .5 * s }; };
  markAt(W0, END, (p, b) => {
    if (!WORDMARK.F) return Object.assign(icon(W0), { a: 1 - E.inOut(lp(b, FADE0, 1.8)), color: '#ffffff' });   // frames missing: keep the icon
    P0 = P0 || WORDMARK.place(icon(W0));
    const v = E.sine(lp(b, W0, WORDMARK.T + .3)), r = readAt(b);
    WORDMARK.add(WORDMARK.svg({ a: 1 - E.inOut(lp(b, FADE0, 1.8)), cx: lerp(P0.cx, r.cx, v), cy: lerp(P0.cy, r.cy, v), k: lerp(P0.k, r.k, v), v, b, on: LET0, color: inkAt(v) }));
    return null;
  });

  /* ---------- 片尾标语（7.3，FADE0–END 与字标、点一起淡出） ---------- */
  css(`
.cl-tag{font-size:54px;font-weight:500;color:rgba(255,255,255,.88);letter-spacing:.005em}
.cl-tag b{color:#d6c7a1;font-weight:600}
`);
  // 字随片尾慢推一起放大：锚点 y 相对 540 外移 × push，字号 × push（tick 在 anim 之后覆盖 transform）
  const pushT = (y) => (el, tl, life, ts) => { const s = S(ts / BEAT); el.style.transform = 'translate(-50%,-50%) translateY(' + ((y - 540) * (s - 1)).toFixed(2) + 'px) scale(' + s.toFixed(4) + ')'; };
  // 标语在最后两个字升起时（TAG0 b85.8）居中出现在字标下方，逐词间隔 .2 拍，「agent」b87.2；之后完整可读到 FADE0 b93.0（5.8 拍 ≈ 2.6 s）
  // v18.4：强调色只留字标的香槟色 #d6c7a1（不再混入钢蓝 --acc），字号 48 → 54（60 时宽 1550 px、超出字标太多），下移 16 px 与字标拉开，
  // 大小写与 1e 的「Agent Workflow」一致
  const W = ['Redesigning ', 'Agent ', 'Workflow ', 'for ', 'everyone ', '&amp; ', '<b>every </b>', '<b>agent</b>'];
  txt(TAG0, END, [['cl-tag', W.map((w) => '<span class="w">' + w + '</span>').join('')]], { x: 960, y: 664, align: 'c' },
    { anim: K.words({ at: [0, .2, .4, .6, .8, 1.0, 1.2, 1.4], out: 1.8 }), tick: pushT(664) });
});
