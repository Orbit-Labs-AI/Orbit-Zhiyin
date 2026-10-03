/* 30-persona 3（b26.4–45.4；v17.3 / v17.4 读字共加长 5.0 拍，见下方 XL） — STORYBOARD.md v17「3」与「转场关键帧」H9–H11.
   罗盘在翻平的标志下成形（刻度 → 描边光从标志尾端出发 → 轨道层随扫描展开 → 花苞边转边减速落在你的类型并绽开）
   → 标题「引入协作人格分析」→ 罗盘左移 → 右侧竖向滚动列（R1–R7），条目经过中心线 y 540 时罗盘做对应反应
   → 揭晓块减速到中心线后慢漂（不停住）→ 徽章按行依次从公转的外圈剥离、滑成左侧竖列，表盘同时朝点列收缩淡出、揭晓块上漂淡出。
   本场景拥有 deck 2（b26.4 直接设定相机，drawCompass 每帧调用，pl: 0）与 b26.4 的 AGD compass key；标志归 20-orbit
   （到 b28.2），CO − .9 起的剥离（column key）归 40-recs（点从 cpBadge 的实时位置出发，所以 drawCompass
   一直调到 b41.5 + XL，deck 2 自 CO + .8 起已透明）。 */
scene('30-persona', () => {
  css(`
.k .ln.pe-or>span{color:var(--a1)}
.ln.pe72{font-size:72px}
.ln.pe44{font-size:44px}
.pe-col{position:absolute;left:1080px;top:0;width:740px;height:1080px;pointer-events:none;
  -webkit-mask-image:linear-gradient(180deg,transparent 0,#000 160px,#000 920px,transparent 1080px);mask-image:linear-gradient(180deg,transparent 0,#000 160px,#000 920px,transparent 1080px)}
.pe-it{position:absolute;left:20px;top:0;width:700px;display:flex;align-items:center;white-space:nowrap;will-change:transform,opacity,filter}
.pe-tx{display:flex;flex-direction:column;gap:8px}
.pe-it .eb{font-size:24px;color:rgba(255,255,255,.62)}
.pe-s{font-size:36px;color:rgba(255,255,255,.72)}
.pe-q{font-size:32px;color:rgba(255,255,255,.7)}
.pe-pl{font-size:54px;font-weight:600;letter-spacing:.02em;display:flex;align-items:center;gap:.36em;line-height:1.2}
.pe-pl .ar{font-size:.62em;font-weight:400;color:rgba(255,255,255,.34)}
.pe-fc{margin-left:auto;flex:none;width:96px;height:112px;border-radius:14px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);overflow:hidden;position:relative}
.pe-fc::after{content:'';position:absolute;left:0;right:0;top:50%;height:2px;margin-top:-1px;background:rgba(0,0,0,.55)}
.pe-fs{position:absolute;left:0;top:0;width:100%;will-change:transform}
.pe-fs i{display:block;height:112px;line-height:112px;text-align:center;font:700 76px var(--type);font-style:normal;color:var(--a1)}
.pe-code{font:700 130px/1 var(--type);letter-spacing:.04em;color:#fff}
.pe-code .ch{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.pe-nm{font-size:54px;font-weight:600}
.pe-nm i{font-family:var(--display);font-weight:500;color:var(--orbit);margin-left:.3em}
.pe-ln{font-size:34px;color:rgba(255,255,255,.72)}
.pe-r7{font-size:34px;color:rgba(255,255,255,.78);display:flex;align-items:center;gap:14px}
.pe-r7 .ic{font-size:30px;width:40px;text-align:center}
.pe-r7 .m{font-family:var(--mono);font-size:22px;letter-spacing:.24em;color:rgba(255,255,255,.5)}
`);
  const D0 = compassData(), ME = D0.me, AX = D0.AXES, W0 = decks[0].W;
  const ME_IDX = CODES.indexOf(ME.code);
  const typeDeg = (code) => (CODES.indexOf(code) + .5) * 22.5;
  const PC = [960, 540];

  /* ---------- Agent 点：轨道椭圆张开成罗盘外圈（H9；交接汇总：compass key 由接手方写） ---------- */
  // 点领着标志翻平：排速后 20-orbit 的翻平从 b25.9 起（sine 1.5 拍），原来 b26.4 的 key 让点在标志已翻开一半时
  // 还停在扁轨道上。key 改到 HB = b25.7（比翻平早 .2 拍，点先动、标志跟上）、sine，dur 2.0（峰速 1450 → ≈ 900 px/拍；
  // 最后一个点 b27.94 落定：徽章沿外圈滑过类型码时类型码还没淡入（b27.7 起），落定后接花苞绽开、b29.5 慢推）。0.0.4 徽章方位不均匀
  // （cc 43 / cx 62 / gm 288 / ds 118 / cp 221°），gm 必须越过 ds、cp：它顺时针从外侧绕过（径向外推 96px 的
  // cos² 鼓包，e .1–1，落定时归零），离 ds / cp 最近约 52 / 59px，不再在底部和它们相撞。
  const HB = 25.7, HD = 2.0, HS = .06;
  AGD.key(HB, 'compass', { dur: HD, ease: E.sine, stag: HS, polar: PC });
  AGD.follow(HB, HB + HS * 2 + HD, (i, b, q) => {
    if (i !== 2) return null;
    const e = E.sine(clamp((b - HB - HS * 2) / HD)), x = (e - .55) / .45;
    if (Math.abs(x) >= 1) return null;
    const cy = lerp(552, 540, e), dx = q.x - 960, dy = q.y - cy, d = Math.hypot(dx, dy) || 1, o = 96 * Math.cos(x * Math.PI / 2) ** 2;
    return { x: q.x + dx / d * o, y: q.y + dy / d * o };
  }, { blend: .01 });

  /* ---------- deck 2 相机（H9 / H10 / H11） ---------- */
  // 节奏（v17 放慢）：罗盘 MV–MV + 1.4 左移（v17.3 起 b31.4–32.8），之后的时间给右侧滚动列；
  // 标题期间与滚动列期间都慢推，不定格
  // v17.3 读字（每行完整可读 ≥ max(1.4, .9 + .12 / 汉字) 拍）：本场景加长 XL = 1.8 拍，起点 b26.4 不变——
  // ① 左移从 b30.9 推到 b31.4（+.5），标题 / 强调行读到 b31.8 才退场；② R1 先以慢漂进场、再 1.2 拍加速到匀速（+.3）；
  // ③ 揭晓块到中心线后多漂 1.0 拍再退场（含优势 / 盲点两行的进场）。旧 b39.2 及以后的退场与交接全部晚 XL
  // （40-recs 的 column key 由集成方用 SHIFT 推后同样的拍数）。
  // v17.4 读字（每行 ≥ max(2.0, 1.2 + .18 / 汉字 + .09 / 拉丁字母) 拍，标题 ×1.3）再加长 3.2 拍（XL 1.8 → 5.0）：
  // ① 罗盘成形后标题 / 强调行停留：左移 b31.4 → 32.8（+1.4，标题 b29.45 起到左移约 3.35 拍，期间慢推 + 外圈慢转）；
  // ② R1 先慢漂 .9 拍（+.4）；③ 匀速 V 150 → 130、清晰带加宽到中心线下 170 / 上 310px（R2–R5 过线间隔 1.05 → 1.21 拍）；
  // ④ 揭晓块到中心线后读到 EX = T6 + 3.0（原 + 2.2）。
  // v17.5：花随分析一瓣瓣更换（见下方 CH），揭晓前多给 1 拍让最后一次更换落在 DIMV 后再显影：XL 5.0 → 6.0
  const XL = 6.0, EX = 39.2 + XL, CO = 39.4 + XL;          // EX：滚动列退场；CO：罗盘退场 = 交给 40-recs 的拍
  const MV = 32.8, MVD = 1.4;
  // 罗盘中心 (400, 400) → 舞台 (960, 540)，s .86：描边光半径 381 × .86 = 328 = 俯视标志外圈 R；描边光与标志 b28.4 前收完，b29.5 起才慢推
  // 相机几何在 HB 先就位（仍透明），compass key 从 HB 起读 cpBadge 就是最终的舞台坐标；b26.4 才显示 deck 2
  tween(2, HB, 0, { x: 400, y: 400, s: .86, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0 });
  tween(2, 26.4, 0, { x: 400, y: 400, s: .86, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, 29.5, MV - 29.5, { s: .88 }, E.sine);
  tween(2, MV, MVD, { ax: 600, ay: 560, s: .78 }, E.inOut);
  tween(2, MV + MVD, CO - MV - MVD, { s: .81 }, E.sine);
  // T10（r176b）：40-recs 在 CO − .9 让第一枚徽章离开外圈；表盘同拍起用 2.0 拍长缓动朝点列（x 330）收缩（s .81 → .5，
  // 中心 → (400, 545)），还没剥离的徽章随外圈一起向点列聚拢，五个点始终是一组；透明度晚 .5 拍起 1.2 拍淡完（CO + .8），
  // 与揭晓块的退场、引言卡的写入重叠，中间没有空黑帧；review：原 CO − .1 起 1.3 拍（三次方缓动）到 CO + .4 外圈仍有 .77，
  // 前两行点写引言的连线（CO + .15 起）正好横穿半透明的表盘，现在连线画出时外圈只剩 ≈ .6 → .15、表盘与花已暗到 ≈ .2 → 0
  tween(2, CO - .9, 2.0, { s: .5, ax: 400, ay: 545 }, E.inOut);
  tween(2, CO - .4, 1.2, { o: 0 }, E.inOut);

  /* ---------- 花苞：随扫描转（梯形速度），b28.4 起减速，b29.6 落在起始类型 X0 ---------- */
  // v17.5：分析前还不知道你的类型——花先落在与你四个字母里三个相反的 X0（DIMV → SIFT），分析列每定一个字母，
  // 花就一瓣瓣换成与已定字母一致的类型（SIFT → DIFT → DIMT → DIMV，每次只翻一个字母），揭晓前落在你的类型
  const FLIP = { D: 'S', S: 'D', I: 'P', P: 'I', M: 'F', F: 'M', V: 'T', T: 'V' };
  const flip = (c, ks) => c.split('').map((x, k) => (ks.includes(k) ? FLIP[x] : x)).join('');
  const X0 = flip(ME.code, [0, 2, 3]);
  const DEG1 = typeDeg(X0), B0 = 27.2, BT = 2.4, ACC = .3, DEC = 1.2;
  const VMAX = DEG1 / (BT - ACC / 2 - DEC / 2);
  const degAt = (b) => {
    const t = b - B0;
    if (t <= 0) return 0;
    if (t >= BT) return DEG1;
    if (t < ACC) return VMAX * t * t / (2 * ACC);
    if (t < BT - DEC) return VMAX * (t - ACC / 2);
    const s = BT - t; return DEG1 - VMAX * s * s / (2 * DEC);
  };

  /* ---------- 滚动列的时间（R1–R6 过中心线的拍）与罗盘反应 ---------- */
  // v17.3：列 C0 淡入时 R1 在中心线下 25px 以慢漂 VR 进场，TR0 过线后 RU 拍内按余弦加速到匀速 V，
  // 匀速滚过 R2–R5（相距 GAP，每条 1.05 拍），SLOW 起平滑减速到慢漂 VR，T6 揭晓块到中心线后继续慢漂，不停住
  const V = 130, VR = 50, GAP = 157.5;                     // px / beat；条目间距 px
  const C0 = MV + .8, TR0 = C0 + .9, RU = 1.2, YR = RU * (V + VR) / 2;
  const TR = [0, 1, 2, 3, 4].map((k) => (k ? TR0 + RU + (GAP * k - YR) / V : TR0));   // b34.5 / 36.08 / 37.29 / 38.5 / 39.72
  const SLOW = TR[4] + .7, T6 = SLOW + 1.8;                // b40.42 / 42.22（v17.5：减速段 .8 → 1.8 拍，R5 多留在中心附近，揭晓块晚 1 拍）
  // 4 个维度依次排除不符的一半扇区（16 → 8 → 4 → 2 → 1）
  const axQ = (k, b) => E.inOut(lp(b, TR[k + 1] - .1, .6));
  const keepAt = (b) => CODES.map((c) => { let v = 1; for (let k = 0; k < 4; k++) if (c[k] !== ME.code[k]) v *= 1 - axQ(k, b); return v; });

  /* ---------- v17.5：花一瓣瓣更换（CH）、花匀速慢转、外圈曲线与徽章公转 ---------- */
  // 三次更换紧接着排（每次 2.0–2.1 拍，中间不停）：旧花的瓣从 12 点起顺时针一瓣瓣收进花心、新花的瓣紧跟着一瓣瓣开，
  // 花心在中途交叉淡换（drawCompass relay）；三角与强调码在 u .2–.8 滑到新类型。① 字母牌 D 落定前 .3 拍开始
  // （三角 .42 拍后才动，晚于落定）；② 紧接其后，三角在 M 落定（TR[3] − .2）前后滑到 DIMT；③ 在 V 落定后开始，
  // b41.68 落在 DIMV（类型码 T6 − .8 起显影）
  const ci = (c) => CODES.indexOf(c);
  const CH = [];
  [[TR[1] - .5, 2.1, [0]], [null, 2.0, [2]], [null, 2.0, [3]]].reduce((a, [s0, L, ks]) => {
    const b = flip(a, ks), s = s0 ?? CH[CH.length - 1].s + CH[CH.length - 1].L;
    CH.push({ s, L, a, b, ai: ci(a), bi: ci(b), dl: cpDelta(typeDeg(a), typeDeg(b)) });
    return b;
  }, X0);
  const triAt = (b) => (b < B0 + BT ? degAt(b) : DEG1 + CH.reduce((v, c) => v + c.dl * E.inOut(clamp(((b - c.s) / c.L - .2) / .6)), 0));
  // 花本身匀速慢转（约 7°/拍，顺时针）：花苞落定后 1 拍内起步，T6 + .8 前 1.5 拍内收住，收住时一瓣正对你的类型
  const TA = B0 + BT, TE = T6 + .8, NME = D0.fl[ME_IDX].n || 5;
  const TURN = (() => { const st = 360 / NME, base = ((typeDeg(ME.code) - DEG1) % st + st) % st, want = 7 * (TE - TA - 1.25); return base + st * Math.max(0, Math.round((want - base) / st)); })();
  const turnAt = (b) => {
    const t = b - TA, T = TE - TA, v = TURN / (T - 1.25);
    if (t <= 0) return 0;
    if (t >= T) return TURN;
    if (t < 1) return v * t * t / 2;
    if (t < T - 1.5) return v * (t - .5);
    return TURN - v * (T - t) * (T - t) / 3;
  };
  const faAt = (b) => degAt(b) + turnAt(b);
  // 公转：每个 Agent 的曲线和徽章各以匀速绕表盘转，内圈（曲线平均半径小）快：9 / 6.5 / 4.5 / 3 / 1.8°/拍（b26.4 起 1 拍内起步）；
  // 每次换花再同步多转一段。多转的量让每个 Agent 到 CO 恰好转满 360°——徽章回到数据方位，40-recs 按方位排好的
  // 竖列（ORD）照常接手，不交叉；交入时（b25.7–26.4）公转为 0，20-orbit 交来的编队形状不变。
  // 三次换花首尾相接，多转按整段换花匀速加上（首尾各 .8 拍缓起缓收，每次换花各得约 EXT）：不再每次 sine 一冲一停
  // （外圈原先 1.8 ↔ 87°/拍 一冲一停，现在换花期间匀速约 60°/拍）
  const RB = 26.4, RV = [9, 6.5, 4.5, 3, 1.8];
  const lyM = D0.sets.base.ly.map((y) => (y ? y.reduce((a, v) => a + v, 0) / y.length : -1));
  const SPD = []; [0, 1, 2, 3, 4].sort((p, q) => lyM[p] - lyM[q]).forEach((i, r) => { SPD[i] = RV[r]; });
  const baseRev = (i, b) => { const t = b - RB; return t <= 0 ? 0 : t < 1 ? SPD[i] * t * t / 2 : SPD[i] * (t - .5); };
  const EXT = SPD.map((v, i) => { let e = (360 - baseRev(i, CO)) / CH.length; while (e < 20) e += 360 / CH.length; return e; });
  const XS = CH[0].s, XT = CH[CH.length - 1].s + CH[CH.length - 1].L - XS, XR = .8, XV = 1 / (XT - XR);
  const xw = (b) => { const t = b - XS; return t <= 0 ? 0 : t >= XT ? 1 : t < XR ? XV * t * t / (2 * XR) : t > XT - XR ? 1 - XV * (XT - t) * (XT - t) / (2 * XR) : XV * (t - XR / 2); };
  const revAt = (b) => { const w = xw(b) * CH.length; return SPD.map((v, i) => baseRev(i, b) + EXT[i] * w); };

  /* ---------- v17.7 Agent 点形态（STORYBOARD「v17.7」F3 (3)） ---------- */
  // 花瓣形态一律 aim 表盘中心（cpStage(400, 400) 实时读相机，左移 / 收缩时仍指向花心；编队几何中心因方位不均会偏）
  const HEART = () => cpStage(400, 400);
  const bearing = (i, b) => { const d = D0.sets.base.pl[i]; return d == null ? null : ((d + revAt(b)[i]) % 360 + 360) % 360; };
  // ① 花苞边转边落定（b28.4–29.6 长大）：五点同时朝花心收成花瓣（像五片外瓣合拢），花绽开时回圆徽章
  AGD.morph(28.6, 'all', 'petal', { dur: .5, stag: 0, aim: HEART, hold: .2, back: .6 });
  // ② 三次逐瓣换花：旧花的瓣从 12 点起顺时针在 u = .55·φ/360 收起、新瓣在 u ≈ .14 + .55·φ/360 打开（drawCompass relay）。
  // 每个点在扫动到达它当时的方位（公转中，取不动点）前 .1 拍变花瓣，新瓣打开时回圆——与花瓣同向同速顺时针传过去
  // review：公转方位跨过 12 点时原来的不动点迭代在 0° / 360° 间来回跳，换花开头就让 12 点前（≈ 290–330°）的点变花瓣，
  // 扫动其实约 1 拍后才到——改为在展开的角度上二分求「扫动角 = 点的角」；扫动追不上（点在扫动收尾前已回到 12 点）时取最接近的扫动收尾
  CH.forEach((c) => {
    const SW = c.L * .55;
    for (let i = 0; i < 5; i++) {
      const d = D0.sets.base.pl[i];
      if (d == null) continue;
      const off = d + revAt(c.s)[i] - bearing(i, c.s), f = (t) => 360 * (t - c.s) / SW - (d + revAt(t)[i] - off);
      let t = c.s + SW;
      if (f(c.s + SW) >= 0) { let lo = c.s, hi = c.s + SW; for (let n = 0; n < 30; n++) { const m = (lo + hi) / 2; if (f(m) < 0) lo = m; else hi = m; } t = hi; }
      AGD.morph(t - .1, i, 'petal', { dur: .3, aim: HEART, hold: .25, back: .45 });
    }
  });
  // ③ 揭晓（类型码 T6 − .8 显影）：描边加粗 + 柔光从内圈到外圈（按曲线平均半径）扫过一次，然后一直是圆徽章进入剥离
  const INOUT = [0, 1, 2, 3, 4].filter((i) => lyM[i] >= 0).sort((p, q) => lyM[p] - lyM[q]);
  INOUT.forEach((i, n) => AGD.morph(T6 - .8 + .1 * n, i, 'dot', { ring: 1.5, glow: .35, dur: .3, hold: .2, back: .5 }));

  /* ---------- v17.1 T9：引导线把视线从罗盘带到右列 ---------- */
  // 从罗盘上 x 最大的徽章（相机只平移缩放、rz 0，所以按方位 sin 最大取下标，左移全程不变）连到右列中心线左端
  // (1100, 540)：白 30%（连线自带 stroke-opacity .7，.43 × .7），1.5px，长出 .5 拍，pulse 1，收回 .4 拍。
  // 拍号跟 R1：V2 写的 b32.2–33.6 对应排速前 R1 在 b33.0 过线；排速后 R1 在 TR[0]（b32.3）过线，
  // 所以照同样的相对关系写成线在 R1 过线前 .2 拍长满、过线后 .2 拍开始收回（v17.4：R1 b34.5 过线 → b33.8 → 34.3 长满 → 34.7–35.1 收回）。
  // v17.5：徽章在公转，按 R1 过线时（TR[0]）的方位取最右的那个
  const R9 = revAt(TR[0]), T9D = D0.sets.base.pl.map((d, i) => (d == null ? null : d + R9[i]));
  const T9I = T9D.reduce((m, d, i) => (d != null && (m < 0 || Math.sin(d * Math.PI / 180) > Math.sin(T9D[m] * Math.PI / 180)) ? i : m), -1);
  if (T9I >= 0) AGD.link(TR[0] - .7, TR[0] + .6, T9I, [1100, 540], { color: 'rgba(255,255,255,.43)', width: 1.5, draw: .5, out: .4, pulse: 1 });
  // 表圈上 16 个扇区的亮弧（罗盘坐标，跟着相机走）：R1 依次闪亮一遍；之后仍可能的扇区微亮，最后你的扇区留橙色
  let HL = null;
  const hlInit = () => {
    if (HL) return HL;
    const svg = buildCompass(), g = document.createElementNS(SVGNS, 'g');
    g.setAttribute('class', 'pe-hl');
    g.innerHTML = CODES.map((c, t) => '<path d="' + cpSector(366, 394, t * 22.5 + .9, (t + 1) * 22.5 - .9) + '" fill="' + (t === ME_IDX ? 'var(--a1)' : '#fff') + '" opacity="0"/>').join('');
    svg.insertBefore(g, svg.querySelector('.cp-trace'));
    HL = [...g.children];
    return HL;
  };
  const bump = (x, w) => (x <= 0 || x >= w ? 0 : Math.sin(Math.PI * x / w));
  const hlDraw = (b, keep, dial) => {
    hlInit().forEach((p, t) => {
      const flash = .5 * bump(b - (TR[0] - .2 + t * .06), .5);
      const cand = .16 * keep[t] * E.out(lp(b, TR[1] - .25, .5));
      const mine = t === ME_IDX ? .62 * E.inOut(lp(b, TR[4] - .1, .6)) : 0;
      const v = Math.max(flash, t === ME_IDX ? Math.max(cand, mine) : cand) * dial;
      p.setAttribute('opacity', v.toFixed(3));
    });
  };

  /* ---------- 罗盘：每帧一次（b26.4–41.5 + XL；deck 2 自 CO + .8 透明，之前一直为 40-recs 剥离中的点提供出发位置） ---------- */
  drive(2, 26.4, 41.5 + XL, (p, b) => {
    const out = 1 - E.inOut(lp(b, CO - .6, 1.3)), keep = keepAt(b);   // 表盘、花随剥离慢慢退暗（与 deck 2 的淡出相乘）
    const dial = E.out(lp(b, 26.5, .8)) * out;
    const ck = CH.find((c) => b >= c.s && b < c.s + c.L);
    drawCompass({
      pl: 0, deg: faAt(b), tri: triAt(b), fi: b < CH[0].s ? ci(X0) : ME_IDX, rev: revAt(b),
      relay: ck ? { a: ck.ai, b: ck.bi, u: (b - ck.s) / ck.L, a0: faAt(ck.s) } : null, grow: E.inOut(lp(b, 28.4, 1.2)), mine: E.inOut(lp(b, T6 - .3, 1.4)),
      spin: (b - 26.4) * .6, keep,
      ticks: E.inOut(lp(b, 26.6, 1.2)),
      trace: b < 29 ? lp(b, 27.4, 1.0) : null, traceA: 1 - E.out(lp(b, 28.4, .5)),
      sweep: lp(b, 27.4, 1.2), sweepFrom: 0,
      dial, core: E.out(lp(b, 27.0, .8)) * out, needle: E.out(lp(b, 27.8, .5)),
      codes: E.out(lp(b, 27.7, .5))   // H9：外框类型码等右侧的点穿过、翻平的标志淡到一半（b27.7）再淡入，b28.2 与标志淡完同时到齐
    });
    hlDraw(b, keep, dial);
  });

  /* ---------- 3.3 / 3.4 文字 ---------- */
  // 眉题：居中出现，MV 起随罗盘移到左上 x 160（左对齐），CO 退场
  txt(28.8, 40.0 + XL, [['eb', '01 · 协作人格']], { x: 160, y: 100 }, {
    anim: K.all(mask(.18, 1.0, .6), (el, tl, life, t) => {
      const b = t / BEAT, e = E.inOut(lp(b, MV, MVD)), dx = (960 - el.offsetWidth / 2 - 160) * (1 - e);
      // 居中时比标题（y 150，72px）上沿高出 18px，不贴字，并跟标题一起慢慢上漂 12px（漂到左移开始）；移到左上时回到 y 100
      el.style.transform = 'translate(' + dx.toFixed(1) + 'px,calc(-50% - ' + ((18 + 12 * clamp((b - 29.0) / (MV - 28.9))) * (1 - e)).toFixed(1) + 'px))';
    })
  });
  // 标题与强调行：在场时各自慢慢离开罗盘（标题连同眉题上漂 12px、强调行下漂 10px，配合罗盘慢推），左移开始 .4 拍后
  // （MV + .4 = b33.2，罗盘才移出 10%）退场：标题 b29.45–33.2 完整可读 3.75 拍，强调行 b29.1 起解码（步长 .04），b29.85–33.2 约 3.35 拍
  const drift = (px) => (el, tl, life) => { el.style.transform = 'translate(-50%,calc(-50% + ' + (px * clamp(tl / life)).toFixed(1) + 'px))'; };
  txt(29.0, MV + 1.0, [['hv sv pe72', '引入协作人格分析']], { x: 960, y: 150, align: 'c' }, { anim: K.all(mask(.18, 1.0, .6, true), drift(-12)) });
  txt(29.1, MV + 1.0, [['lt pe44 pe-or', '精准识别你的交互特征']], { x: 960, y: 975, align: 'c' }, { anim: K.all(K.decode({ step: .04, dur: .5, out: .6, spread: true }), drift(10)) });

  /* ---------- 3.5–3.7 右侧竖向滚动列 ---------- */
  // Y(b)：已滚动的 px。R1 以 VR 慢漂、b32.7 过中心线，之后 RU 拍按余弦加速到 V；SLOW–T6 速度按余弦平滑降到 VR，
  // T6 揭晓条目到中心线，之后以 VR 慢漂（不停住）；EX 起整列加速上移淡出
  const scrollY = (b) => {
    let y;
    if (b <= TR0) y = VR * (b - TR0);
    else if (b <= TR0 + RU) { const u = b - TR0; y = VR * u + (V - VR) * (u / 2 - RU / (2 * Math.PI) * Math.sin(Math.PI * u / RU)); }
    else if (b <= SLOW) y = YR + V * (b - TR0 - RU);
    else {
      const d = T6 - SLOW, u = Math.min(b - SLOW, d);
      y = YR + V * (SLOW - TR0 - RU) + VR * u + (V - VR) * (u / 2 + d / (2 * Math.PI) * Math.sin(Math.PI * u / d));
      if (b > T6) y += VR * (b - T6);
    }
    return y + 150 * E.inOut(lp(b, EX, 1.4));               // 退场：长缓动上漂 150px（不再 E.in 猛拉）
  };
  const P6 = scrollY(T6);                                  // 揭晓块锚点（R5 下方 185px）
  const FLAP = 'DSIPMFVT', DRUM = FLAP + FLAP[0];
  const pole = (k) => (ME.code[k] === AX[k].L ? 'L' : 'R');
  // 优势与盲点：App 人格卡的第一条（示例数据：委托 ≥ 50 → 整段委托 …；盲点 = 会话里最常见的摩擦类型），不带数字
  const STRONG = ME.v.D >= 50 ? '整段委托' : ME.v.V >= 50 ? '验收严格' : '节奏稳定';
  let BLIND = '';
  try { BLIND = (Object.entries(W0.eval('countBy')(D0.L, 'fric')).filter(([k]) => k && k !== 'undefined' && k !== 'null').sort((a, b) => b[1] - a[1])[0] || [''])[0]; } catch (e) { BLIND = ''; }
  // 条目：{ y: 锚点（列坐标）, html, k: 维度下标 | undefined, fy: 用于焦点的锚点（揭晓块整体用 P6） }
  const ITEMS = [
    { y: 0, html: '<div class="pe-tx"><span class="eb">16 种协作人格 · 4 个维度</span><span class="pe-s">每个会话，落到它的方位</span></div>' },
    ...[0, 1, 2, 3].map((k) => ({
      y: GAP * (k + 1), k,
      html: '<div class="pe-tx"><span class="pe-q">' + AX[k].q + '</span><span class="pe-pl"><span class="pL">' + AX[k].Ln + '</span><span class="ar">⟷</span><span class="pR">' + AX[k].Rn + '</span></span></div>' +
        '<span class="pe-fc"><span class="pe-fs">' + DRUM.split('').map((x) => '<i>' + x + '</i>').join('') + '</span></span>'
    })),
    { y: P6 - 92, fy: P6, html: '<span class="eb">你的协作人格</span>' },
    { y: P6, fy: P6, code: true, html: '<span class="pe-code">' + ME.code + '</span>' },
    { y: P6 + 112, fy: P6, name: true, html: '<span class="pe-nm">' + ME.zh + '<i>' + ME.en + '</i></span>' },
    { y: P6 + 180, fy: P6, line: true, html: '<span class="pe-ln">' + ME.line.split('，')[0] + '</span>' },
    { y: P6 + 262, fy: P6, r7: 0, html: '<span class="pe-r7"><span class="ic" style="color:var(--a3)">✓</span><span class="m">优势</span>' + STRONG + '</span>' },
    ...(BLIND ? [{ y: P6 + 314, fy: P6, r7: 1, html: '<span class="pe-r7"><span class="ic" style="color:#f3b25c">⚠</span><span class="m">盲点</span>' + BLIND + '</span>' }] : [])
  ];
  // 揭晓块的进场（相对 T6）：类型码 T6 − .8（居中向外显影），中文名 T6 − .55，一句话 T6 − .4（解码），
  // 优势 / 盲点 T6 + .05 / + .25 依次上浮淡入（原来只是糊着滚进来，读不到）；都读到 EX = T6 + 3.0
  const codeIn = K.centerOut({ step: .15, dur: .55, out: 0 }), lineIn = K.decode({ step: .04, dur: .45, out: 0, from: .3 });
  txt(C0, EX + 1.4, [['', '']], { x: 0, y: 0 }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT;
      if (!el._pe) {
        el._pe = true; el.style.transform = 'none'; el.style.left = '0'; el.style.top = '0';
        el.innerHTML = '<div class="pe-col">' + ITEMS.map((it) => '<div class="pe-it">' + it.html + '</div>').join('') + '</div>';
        el._it = [...el.querySelectorAll('.pe-it')];
      }
      // 退场（EX 起 1.1 拍）：揭晓块边上漂边淡、轻微失焦（≤ 5px），在引言卡标题写到 x 1100 前（≈ EX + 1.1）淡完，不残留
      const Y = scrollY(b), xo = E.inOut(lp(b, EX, 1.1)), colA = E.out(lp(b, C0, .8)) * (1 - xo), col = el.querySelector('.pe-col');
      col.style.opacity = colA.toFixed(3);
      col.style.filter = xo > .01 ? 'blur(' + (5 * xo).toFixed(2) + 'px)' : 'none';
      ITEMS.forEach((it, n) => {
        const node = el._it[n], s = (it.fy ?? it.y) - Y;
        let y = 540 + it.y - Y;
        if (y < -200 || y > 1280) { node.style.visibility = 'hidden'; return; }
        node.style.visibility = '';
        // v17.4 清晰带：中心线下 170px（将到）到上 310px（刚读过）之间不模糊，只按距离微暗（中心 1 → 带边 .7）；
        // 带外才变糊变暗。匀速 V 130 时每条完整可读约 3.7 拍，中心那条仍最亮
        const dd = s > 0 ? Math.max(0, s - 170) : Math.max(0, -s - 310), bl = 6 * dd / 300;
        let a = clamp(1 - .3 * Math.min(Math.abs(s), 200) / 200 - .45 * dd / 300);
        if (it.fy == null) a *= 1 - .6 * E.inOut(lp(b, T6, 1.0));           // 揭晓时前面的条目退暗，让出视线（R5 的字母牌先读满 2 拍）
        if (it.r7 != null) { const q = E.out(lp(b, T6 + .05 + .2 * it.r7, .5)); a *= q; y += (1 - q) * 18; }
        node.style.transform = 'translateY(' + (y - 1).toFixed(1) + 'px) translateY(-50%)';
        node.style.opacity = a.toFixed(3);
        node.style.filter = bl > .05 ? 'blur(' + bl.toFixed(2) + 'px)' : 'none';
        if (it.k != null) {                                // 维度：选中的一极亮、另一极 30%；字母牌滚到这一位字母
          const k = it.k, tk = TR[k + 1] - .2, q = E.inOut(lp(b, tk - .15, .5)), on = pole(k);   // 字母牌在过线前 .2 拍落定
          node.querySelector('.pL').style.color = 'rgba(255,255,255,' + lerp(.72, on === 'L' ? 1 : .3, q).toFixed(3) + ')';
          node.querySelector('.pR').style.color = 'rgba(255,255,255,' + lerp(.72, on === 'R' ? 1 : .3, q).toFixed(3) + ')';
          const tgt = FLAP.indexOf(ME.code[k]), u = clamp((tk - b) / 1.5), pos = (((tgt - 8 * u * u) % 8) + 8) % 8;
          node.querySelector('.pe-fs').style.transform = 'translateY(' + (-pos * 112).toFixed(1) + 'px)';
          // v17.7：字母牌从左侧（罗盘方向）擦出——在它开始翻滚前（tk − 1.95，条目还在中心线下方的糊带里）.5 拍从左向右显出、左移 14px 归位，
          // 「左边点 / 花在动、右边落字」读成因果；之前原地一直在
          const fc = node.querySelector('.pe-fc'), w = E.inOut(lp(b, tk - 1.95, .5));
          fc.style.clipPath = w >= 1 ? '' : 'inset(-2px ' + (100 * (1 - w)).toFixed(1) + '% -2px -2px round 14px)';
          fc.style.transform = w >= 1 ? '' : 'translateX(' + (-14 * (1 - w)).toFixed(1) + 'px)';
        }
        if (it.code) codeIn(node.firstChild, (b - (T6 - .8)) * BEAT, 99, t);
        if (it.name) { const q = E.out(lp(b, T6 - .55, .65)), f = node.firstChild; f.style.display = 'inline-block'; f.style.opacity = Math.min(1, q * 1.4).toFixed(3); f.style.transform = 'translateY(' + ((1 - q) * 26).toFixed(1) + 'px)'; }
        if (it.line) lineIn(node.firstChild, (b - (T6 - .4)) * BEAT, 99, t);
      });
    }
  });
});
