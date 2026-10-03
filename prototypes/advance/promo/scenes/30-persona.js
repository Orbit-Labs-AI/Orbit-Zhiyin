/* 30-persona 3（b26.4–40.4） — STORYBOARD.md v17「3」与「转场关键帧」H9–H11.
   罗盘在翻平的标志下成形（刻度 → 描边光从标志尾端出发 → 轨道层随扫描展开 → 花苞边转边减速落在你的类型并绽开）
   → 标题「引入协作人格分析」→ 罗盘左移 → 右侧竖向滚动列（R1–R7），条目经过中心线 y 540 时罗盘做对应反应
   → 揭晓块减速到中心线后慢漂（不停住）→ 列上移淡出、罗盘缩小淡出。
   本场景拥有 deck 2（b26.4 直接设定相机，drawCompass 每帧调用，pl: 0）与 b26.4 的 AGD compass key；标志归 20-orbit
   （到 b28.2），b39.4 的 column key 归 40-recs（点从 cpBadge 的实时位置出发，所以 drawCompass 一直调到 b41.5，
   deck 2 自 b40.4 起已透明）。 */
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

  /* ---------- Agent 点：轨道椭圆张开成罗盘外圈（H9；交接汇总：b26.4 的 key 由接手方写） ---------- */
  AGD.key(26.4, 'compass', { dur: 1.4, stag: .06, polar: PC });

  /* ---------- deck 2 相机（H9 / H10 / H11） ---------- */
  // 节奏（v17 放慢）：罗盘 b30.9–32.3 左移（比原来早 .5 拍），省下的时间和原来揭晓的定格一起给右侧滚动列；
  // 标题期间与滚动列期间都慢推，不定格
  const MV = 30.9, MVD = 1.4;
  // 罗盘中心 (400, 400) → 舞台 (960, 540)，s .86：描边光半径 381 × .86 = 328 = 俯视标志外圈 R；描边光与标志 b28.4 前收完，b29.5 起才慢推
  tween(2, 26.4, 0, { x: 400, y: 400, s: .86, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0, mx: 0, my: 0 });
  tween(2, 29.5, MV - 29.5, { s: .875 }, E.sine);
  tween(2, MV, MVD, { ax: 600, ay: 560, s: .78 }, E.inOut);
  tween(2, MV + MVD, 39.4 - MV - MVD, { s: .81 }, E.sine);
  tween(2, 39.4, .85, { s: .6, o: 0 }, E.inOut);              // E.inOut：表盘底盘与轨道层不在点飞走后残留（b40.25 已透明）

  /* ---------- 花苞：随扫描转（梯形速度），b28.4 起减速，b29.6 落在你的类型（+1 圈） ---------- */
  const DEG1 = typeDeg(ME.code) + 360, B0 = 27.2, BT = 2.4, ACC = .3, DEC = 1.2;
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
  // 匀速 V 滚过 R1–R5（每条 1.05 拍、相距 157px），b37.2 起平滑减速到慢漂 VR，b38.0 揭晓块到中心线后继续慢漂，不停住
  const V = 150, VR = 50;                                  // px / beat
  const TR = [32.3, 33.35, 34.4, 35.45, 36.5], T6 = 38.0, SLOW = 37.2;
  // 4 个维度依次排除不符的一半扇区（16 → 8 → 4 → 2 → 1）
  const axQ = (k, b) => E.inOut(lp(b, TR[k + 1] - .1, .6));
  const keepAt = (b) => CODES.map((c) => { let v = 1; for (let k = 0; k < 4; k++) if (c[k] !== ME.code[k]) v *= 1 - axQ(k, b); return v; });
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

  /* ---------- 罗盘：每帧一次（b26.4–41.5；deck 2 自 b40.4 透明，之后只为 40-recs 的点提供出发位置） ---------- */
  drive(2, 26.4, 41.5, (p, b) => {
    const out = 1 - E.inOut(lp(b, 39.4, .8)), keep = keepAt(b);
    const dial = E.out(lp(b, 26.5, .8)) * out;
    drawCompass({
      pl: 0, deg: degAt(b), fi: ME_IDX, grow: E.inOut(lp(b, 28.4, 1.2)), mine: E.inOut(lp(b, T6 - .3, 1.4)),
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
  // 眉题：居中出现，b30.9–32.3 随罗盘移到左上 x 160（左对齐），b39.4 退场
  txt(28.8, 40.0, [['eb', '01 · 协作人格']], { x: 160, y: 100 }, {
    anim: K.all(mask(.18, 1.0, .6), (el, tl, life, t) => {
      const b = t / BEAT, e = E.inOut(lp(b, MV, MVD)), dx = (960 - el.offsetWidth / 2 - 160) * (1 - e);
      // 居中时比标题（y 150，72px）上沿高出 18px，不贴字，并跟标题一起慢慢上漂 12px；移到左上时回到 y 100
      el.style.transform = 'translate(' + dx.toFixed(1) + 'px,calc(-50% - ' + ((18 + 12 * clamp((b - 29.0) / 2.5)) * (1 - e)).toFixed(1) + 'px))';
    })
  });
  // 标题与强调行：在场时各自慢慢离开罗盘（标题连同眉题上漂 12px、强调行下漂 10px，配合罗盘慢推），b30.9–31.5 随左移退场
  const drift = (px) => (el, tl, life) => { el.style.transform = 'translate(-50%,calc(-50% + ' + (px * clamp(tl / life)).toFixed(1) + 'px))'; };
  txt(29.0, 31.5, [['hv sv pe72', '引入协作人格分析']], { x: 960, y: 150, align: 'c' }, { anim: K.all(mask(.18, 1.0, .6, true), drift(-12)) });
  txt(29.35, 31.5, [['lt pe44 pe-or', '精准识别你的交互特征']], { x: 960, y: 975, align: 'c' }, { anim: K.all(K.decode({ step: .055, dur: .5, out: .6, spread: true }), drift(10)) });

  /* ---------- 3.5–3.7 右侧竖向滚动列 ---------- */
  // Y(b)：已滚动的 px。R1 在 b32.3 过中心线；匀速 V；b37.2–38.0 速度按余弦平滑降到 VR，b38.0 揭晓条目到中心线，
  // 之后以 VR 慢漂（不停住）；b39.2 起整列加速上移淡出
  const scrollY = (b) => {
    let y;
    if (b <= SLOW) y = V * (b - TR[0]);
    else {
      const d = T6 - SLOW, u = Math.min(b - SLOW, d);
      y = V * (SLOW - TR[0]) + VR * u + (V - VR) * (u / 2 + d / (2 * Math.PI) * Math.sin(Math.PI * u / d));
      if (b > T6) y += VR * (b - T6);
    }
    return y + 330 * E.in(lp(b, 39.2, 1.0));
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
      y: V * (TR[k + 1] - TR[0]), k,
      html: '<div class="pe-tx"><span class="pe-q">' + AX[k].q + '</span><span class="pe-pl"><span class="pL">' + AX[k].Ln + '</span><span class="ar">⟷</span><span class="pR">' + AX[k].Rn + '</span></span></div>' +
        '<span class="pe-fc"><span class="pe-fs">' + DRUM.split('').map((x) => '<i>' + x + '</i>').join('') + '</span></span>'
    })),
    { y: P6 - 92, fy: P6, html: '<span class="eb">你的协作人格</span>' },
    { y: P6, fy: P6, code: true, html: '<span class="pe-code">' + ME.code + '</span>' },
    { y: P6 + 112, fy: P6, name: true, html: '<span class="pe-nm">' + ME.zh + '<i>' + ME.en + '</i></span>' },
    { y: P6 + 180, fy: P6, line: true, html: '<span class="pe-ln">' + ME.line.split('，')[0] + '</span>' },
    { y: P6 + 262, html: '<span class="pe-r7"><span class="ic" style="color:var(--a3)">✓</span><span class="m">优势</span>' + STRONG + '</span>' },
    ...(BLIND ? [{ y: P6 + 314, html: '<span class="pe-r7"><span class="ic" style="color:#f3b25c">⚠</span><span class="m">盲点</span>' + BLIND + '</span>' }] : [])
  ];
  const codeIn = K.centerOut({ step: .15, dur: .55, out: 0 }), lineIn = K.decode({ step: .04, dur: .45, out: 0, from: .3 });
  txt(31.7, 40.3, [['', '']], { x: 0, y: 0 }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT;
      if (!el._pe) {
        el._pe = true; el.style.transform = 'none'; el.style.left = '0'; el.style.top = '0';
        el.innerHTML = '<div class="pe-col">' + ITEMS.map((it) => '<div class="pe-it">' + it.html + '</div>').join('') + '</div>';
        el._it = [...el.querySelectorAll('.pe-it')];
      }
      const Y = scrollY(b), colA = E.out(lp(b, 31.7, .8)) * (1 - E.inOut(lp(b, 39.2, 1.0)));
      el.querySelector('.pe-col').style.opacity = colA.toFixed(3);
      ITEMS.forEach((it, n) => {
        const node = el._it[n], y = 540 + it.y - Y, dy = Math.abs((it.fy ?? it.y) - Y);
        if (y < -200 || y > 1280) { node.style.visibility = 'hidden'; return; }
        node.style.visibility = '';
        const bl = 6 * dy / 400, a = clamp(1 - .65 * dy / 400);
        node.style.transform = 'translateY(' + (y - 1).toFixed(1) + 'px) translateY(-50%)';
        node.style.opacity = a.toFixed(3);
        node.style.filter = bl > .05 ? 'blur(' + bl.toFixed(2) + 'px)' : 'none';
        if (it.k != null) {                                // 维度：选中的一极亮、另一极 30%；字母牌滚到这一位字母
          const k = it.k, tk = TR[k + 1], q = E.inOut(lp(b, tk - .2, .5)), on = pole(k);
          node.querySelector('.pL').style.color = 'rgba(255,255,255,' + lerp(.72, on === 'L' ? 1 : .3, q).toFixed(3) + ')';
          node.querySelector('.pR').style.color = 'rgba(255,255,255,' + lerp(.72, on === 'R' ? 1 : .3, q).toFixed(3) + ')';
          const tgt = FLAP.indexOf(ME.code[k]), u = clamp((tk - b) / 1.5), pos = (((tgt - 8 * u * u) % 8) + 8) % 8;
          node.querySelector('.pe-fs').style.transform = 'translateY(' + (-pos * 112).toFixed(1) + 'px)';
        }
        if (it.code) codeIn(node.firstChild, (b - 37.4) * BEAT, 99, t);
        if (it.name) { const q = E.out(lp(b, 37.65, .65)), f = node.firstChild; f.style.display = 'inline-block'; f.style.opacity = Math.min(1, q * 1.4).toFixed(3); f.style.transform = 'translateY(' + ((1 - q) * 26).toFixed(1) + 'px)'; }
        if (it.line) lineIn(node.firstChild, (b - 37.85) * BEAT, 99, t);
      });
    }
  });
});
