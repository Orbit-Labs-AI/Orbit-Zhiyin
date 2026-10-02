/* ============ A6 sentiment ============
 * 情绪：VZ 派生类型 moodcorr —— 上图为每桶情绪分布带（P25–P75 阴影 + 中位线，y 域按数据且含 0），下图为纠偏柱（≥ 个人 P75 着琥珀），
 *       两图共用 x 轴与一条游标；标注规则改为事件型（情绪 < 0 的桶用情绪负色，纠偏 ≥ P90 的桶用琥珀），文字写事件而非引语（评审 A6-V01…V05）。
 * 摩擦分类 + Δ 上期 + 每类平均情绪，hover 列典型会话；语义主题标尺改发散条（BUG-72：主题筛选不再吞掉其他主题）；
 * 高频反馈语按次数降序 + 微型条 + 类别色点，出处按短语稳定取样（BUG-73）；情绪前因加 n 与 95% CI。AI 抽取的内容用紫色 .aib 标识。 */
S.sent = S.sent || {};
// 某桶内按会话情绪得到的分布统计；会话 < 2 时没有带，只有中位数
function moodDist(xs) { const st = VZ.stats(xs.map((s) => s.mood)); if (!st) return null; return { n: st.n, p25: st.n >= 2 ? st.p25 : null, p50: st.p50, p75: st.n >= 2 ? st.p75 : null }; }
VZ.types.moodcorr = {
  name: '情绪分布与纠偏',
  isEmpty: (spec) => !(spec.buckets || []).some((b) => b.n > 0),
  render(spec, w, h) {
    const B = spec.buckets || []; const n = B.length; const D = B.map((b) => moodDist(b.xs));
    const hB = 60, gap = 16, hT = h - hB - gap; const left = 36, right = 10;
    // y 域：按数据 ±0.1 并始终含 0（评审 A6-V01）
    let lo = 0, hi = 0; D.forEach((d) => { if (!d) return; lo = Math.min(lo, d.p25 != null ? d.p25 : d.p50); hi = Math.max(hi, d.p75 != null ? d.p75 : d.p50); });
    const [y0, y1] = VZ.nice(Math.min(lo - 0.1, -0.1), Math.max(hi + 0.1, 0.1), 4);
    const fm = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);
    const F = VZ.frame(spec, w, hT, { domain: [y0, y1], fmtY: (v) => (v > 0 ? '+' : '') + VZ.fmt(v, '1f'), left, right, top: 14, bottom: 4, noX: true });
    const sx = VZ.scale.band(n, F.x0, F.x1); const xs = Array.from({ length: n }, (_, i) => sx(i)); const step = sx.step;
    let g = VZ.grid(F);
    // 分布带：连续有带的桶连成多边形，中间断开处分段
    let segs = [], cur = [];
    D.forEach((d, i) => { if (d && d.p25 != null) cur.push([xs[i], F.y(d.p75), F.y(d.p25)]); else if (cur.length) { segs.push(cur); cur = []; } }); if (cur.length) segs.push(cur);
    segs.forEach((sg) => { if (sg.length < 2) return; let up = '', dn = ''; sg.forEach((p) => { up += (up ? 'L' : 'M') + VZ.r1(p[0]) + ' ' + VZ.r1(p[1]); dn = 'L' + VZ.r1(p[0]) + ' ' + VZ.r1(p[2]) + dn; }); g += '<path class="vz-cband sn-band" d="' + up + dn + 'Z" style="--c:var(--ink-3)"/>'; });
    const pts = D.map((d, i) => d ? [xs[i], F.y(d.p50)] : null);
    g += '<path class="vz-line" pathLength="1" d="' + VZ.linePath(pts) + '" style="--c:var(--ink-1)"/>';
    // 纠偏柱：共用 x；≥ 个人 P75 着琥珀（评审 A6-V03）
    const corr = B.map((b) => b.corr); const cmax = Math.max(1, ...corr); const cst = VZ.stats(corr.filter((c) => c > 0)); const p75 = cst ? cst.p75 : Infinity, p90 = cst ? cst.p90 : Infinity;
    const yB2 = h - 22, yT2 = hT + gap; const sy2 = VZ.scale.linear(0, cmax, yB2, yT2); const bw = Math.min(14, step * 0.6);
    g += '<line class="vz-base" x1="' + F.x0 + '" x2="' + F.x1 + '" y1="' + yB2 + '" y2="' + yB2 + '"/>' + VZ.txt(F.x0 - 6, yB2 + 3.5, '0', { class: 'vz-ax', 'text-anchor': 'end' }) + VZ.txt(F.x0 - 6, yT2 + 4, String(cmax), { class: 'vz-ax', 'text-anchor': 'end' }) + VZ.txt(F.x0 - 6, (yT2 + yB2) / 2 + 4, '纠偏', { class: 'vz-axl', 'text-anchor': 'end' });
    B.forEach((b, i) => { if (!b.corr) return; const hh = Math.max(1, yB2 - sy2(b.corr)); g += '<rect class="vz-bar" data-i="' + i + '" x="' + VZ.r1(xs[i] - bw / 2) + '" y="' + VZ.r1(yB2 - hh) + '" width="' + VZ.r1(bw) + '" height="' + VZ.r1(hh) + '" rx="1.5" style="--c:' + (b.corr >= p75 && b.corr >= 2 ? VZ.sem.corr : 'var(--ink-4)') + '"/>'; });
    // 事件标注：情绪 < 0 的桶（情绪负色）或纠偏 ≥ P90 的桶（琥珀），最多 3 个；靠右的标注改为左对齐（评审 A6-V02 / V05）
    const ev = B.map((b, i) => { const d = D[i]; if (!d) return null; const neg = d.p50 < 0, hot = cst && b.corr >= p90 && b.corr >= 2; if (!neg && !hot) return null; const fr = Object.entries(countBy(b.xs, 'fric')).sort((p, q) => q[1] - p[1])[0]; return { i, neg, hot, score: (neg ? 2 - d.p50 : 0) + (hot ? b.corr / cmax : 0), text: (neg ? '情绪 ' + fm(d.p50) : b.corr + ' 次纠偏') + (fr ? ' · ' + fr[0] + ' ×' + fr[1] : '') }; }).filter(Boolean).sort((p, q) => q.score - p.score).slice(0, 3);
    // 标注选位：上 / 下 × 右 / 左 / 居中候选，按「压到中位线的长度 + 与已放标注重叠」打分，避免文字横穿折线
    const used = []; const lineY = (x) => { let a = null; for (let k = 0; k < pts.length; k++) { const q = pts[k]; if (!q) continue; if (q[0] >= x) { if (!a) return q[1]; return a[1] + (q[1] - a[1]) * (x - a[0]) / Math.max(1e-6, q[0] - a[0]); } a = q; } return a ? a[1] : null; };
    ev.forEach((e) => { const x = xs[e.i], y = F.y(D[e.i].p50); const c = e.neg ? VZ.sem.neg : VZ.sem.corr; g += '<circle class="vz-pt sn-ev" data-i="' + e.i + '" cx="' + VZ.r1(x) + '" cy="' + VZ.r1(y) + '" r="4.5" style="--c:' + c + '"/>'; const tw = VZ.tw(e.text, 11);
      let best = null;
      [-12, 20, -26, 34].forEach((dy, di) => [['start', x + 8], ['end', x - 8], ['middle', x]].forEach(([an, lx], ai) => {
        const ly = y + dy; const bx0 = an === 'start' ? lx : an === 'end' ? lx - tw : lx - tw / 2; const b = [bx0, ly - 11, bx0 + tw, ly + 3];
        if (b[0] < F.x0 || b[2] > F.x1 || b[1] < F.yT - 4 || b[3] > F.yB) return;
        let sc = di * 3 + ai; for (let xx = b[0]; xx <= b[2]; xx += 3) { const yy = lineY(xx); if (yy != null && yy > b[1] - 3 && yy < b[3] + 3) sc += 4; }
        used.forEach((u) => { if (b[0] < u[2] + 6 && b[2] > u[0] - 6 && b[1] < u[3] + 2 && b[3] > u[1] - 2) sc += 1000; });
        if (!best || sc < best.sc) best = { sc, lx, ly, an, b };
      }));
      if (!best) return; used.push(best.b); g += VZ.txt(best.lx, best.ly, e.text, { class: 'vz-lbl', 'text-anchor': best.an }); });
    // 共用 x 轴刻度与游标
    const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(F.pw / 64))));
    g += VZ.axisX({ yB: yB2, x0: F.x0, x1: F.x1 }, xs.map((x, i) => ({ x, label: B[i].lbl, major: i % every === 0 })), { keepMajor: true });
    g += '<line class="vz-xline" x1="0" x2="0" y1="' + F.yT + '" y2="' + yB2 + '" hidden/><g class="vz-xdots"></g>';
    const FF = { yT: F.yT, yB: yB2, x0: F.x0, x1: F.x1 };
    return { body: g, model: { kind: 'x', n, F: FF, xs, has: (i) => !!D[i], tip: (i) => { const b = B[i], d = D[i]; const fr = Object.entries(countBy(b.xs, 'fric')).sort((p, q) => q[1] - p[1]).slice(0, 2); return VZ.tipHead(spec.label ? spec.label(b) : b.lbl, b.n + ' 个会话') + VZ.tipRow('var(--ink-1)', '情绪中位数', fm(d.p50), { kind: 'line' }) + (d.p25 != null ? VZ.tipRow('var(--ink-3)', 'P25 – P75', fm(d.p25) + ' – ' + fm(d.p75), { kind: 'rect' }) : '') + VZ.tipRow(b.corr >= p75 && b.corr >= 2 ? VZ.sem.corr : 'var(--ink-4)', '纠偏' + (b.corr >= p75 && b.corr >= 2 ? '（≥ 你的 P75）' : ''), b.corr + ' 次', { kind: 'rect' }) + (fr.length ? '<div class="vz-tr"><span class="vz-tk" style="--c:transparent"></span><span class="vz-tn">主要摩擦：' + fr.map((f) => esc(f[0]) + ' ×' + f[1]).join('、') + '</span></div>' : ''); }, at: (i) => [xs[i], D[i] ? F.y(D[i].p50) : F.yB], datum: (i) => ({ i, bucket: B[i], dist: D[i] }), dots: (i) => D[i] ? '<circle class="vz-pt" cx="' + VZ.r1(xs[i]) + '" cy="' + VZ.r1(F.y(D[i].p50)) + '" r="4" style="--c:var(--ink-1)"/>' : '' } };
  },
  table: (spec) => ({ cols: ['时间', '会话', '中位数', 'P25', 'P75', '纠偏'], rows: (spec.buckets || []).map((b) => { const d = moodDist(b.xs); const f = (v) => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2); return [b.lbl, String(b.n), d ? f(d.p50) : '—', d ? f(d.p25) : '—', d ? f(d.p75) : '—', String(b.corr)]; }) })
};
// 某条反馈语的出处：按类别选会话池，再用短语哈希稳定取样 3 条（BUG-73：不同短语不再给出同一组会话）
function phraseSources(k, cat) {
  const L = sel(); const pool = (cat === '纠偏' ? L.filter((s) => s.corr > 0) : cat === '验证' ? L.filter((s) => s.verify) : cat === '规划' ? L.filter((s) => s.msgs >= 6) : L).slice().sort((a, b) => (b.d - a.d) || (b.h - a.h));
  const r = rng(hash('ph:' + k)); const out = []; const idx = pool.map((_, i) => i).sort(() => r() - 0.5);
  for (const i of idx) { if (out.length >= 3) break; out.push(pool[i]); }
  return out.sort((a, b) => (b.d - a.d) || (b.h - a.h));
}
const AIB = (t) => '<span class="aib" data-tip="由本地 Agent 从你的消息中抽取 · 原文不离开本机">' + ic('spark', 11) + (t || 'AI 抽取') + '</span>';
PAGES.sentiment = () => {
  const head = tbar('情绪与语义', '你的消息 · 中文 62% · 英文 31% · 混合 7%', '<button type="button" class="btn gh" data-act="moodHow">' + ic('info', 14) + '情绪如何计算</button><button type="button" class="btn ai" data-act="phrasesToRule">' + ic('spark', 14) + '把高频纠偏写成规则</button>');
  if (S.engine === 'stats') return head + '<div class="content" id="content">' + empty('语义分析已关闭：分析引擎设为「仅统计」。<br><br><button type="button" class="btn p" data-act="openSettings" data-tab="analysis">去设置开启</button>') + '</div>';
  const L = sel(); const ms = moodSeries(L, S.range); CUR.mood = ms;
  const weeklyB = (win(S.range)[1] - win(S.range)[0] + 1) > 31;   // 按周聚合（BUG-69）
  const pw = prevWin(S.range); const LP = pw ? sel({ win: pw }) : null;
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]); const frMax = Math.max(1, ...fr.map((x) => x[1])); const frTot = Math.max(1, sum(fr, (x) => x[1]));
  const frPrev = LP ? countBy(LP, 'fric') : null;
  // 主题：忽略主题筛选本身，只套用其它筛选（BUG-72）
  const LT = sel({ noExtra: true }).filter((s) => (!S.outcome || s.out === S.outcome) && (!S.fric || s.fric === S.fric) && (S.hour == null || s.h === S.hour));
  const tp = Object.keys(TOPICS).map((k) => { const xs = LT.filter((s) => s.topic === k); return { k, n: xs.length, mood: xs.length ? sum(xs, (s) => s.mood) / xs.length : 0 }; }).filter((t) => t.n).sort((a, b) => b.n - a.n);
  const scale = L.length / 186;
  const phrases = PHRASES.map((p) => [p[0], Math.max(1, Math.round(p[1] * scale)), p[2]]).sort((a, b) => b[1] - a[1]); const phMax = phrases[0][1];
  const dn = L.length;
  const drivers = DRIVERS.map((d, i) => { const n = Math.max(3, Math.round(dn * [0.18, 0.12, 0.41, 0.33][i])); return { name: d[0], v: d[1], n, ci: Math.min(0.3, 0.9 / Math.sqrt(n)) }; });
  const divBar = (v, ci) => { const W = 100, mid = 50; const px = (x) => mid + x / 0.5 * 50; const a = clamp(px(v - (ci || 0)), 0, W), b = clamp(px(v + (ci || 0)), 0, W); return '<span class="sn-div" aria-hidden="true"><i class="mid"></i><i class="bar" style="left:' + Math.min(mid, px(v)) + '%;width:' + Math.abs(px(v) - mid) + '%;background:' + (v < 0 ? VZ.sem.neg : VZ.sem.pos) + '"></i>' + (ci ? '<i class="ci" style="left:' + a + '%;width:' + (b - a) + '%"></i>' : '') + '</span>'; };
  return head + '<div class="content" id="content">' + filterRow('<span class="row cap">' + ic('shield', 13, 'color:var(--good)') + '语义分析由本地 Agent 完成，原文不离开本机</span>') +
    '<div class="stack"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">情绪分布与纠偏</span>' + AIB('AI 打分') + '<span class="cap sn-mood-cap">' + (weeklyB ? '每周' : '每日') + '桶 · 会话情绪 −1 沮丧 … +1 满意</span></div><button type="button" class="btn sm gh" data-act="moodView" aria-pressed="' + (S.sent.view === 'table') + '">' + (S.sent.view === 'table' ? '看图表' : '看表格') + '</button></div>' +
      (S.sent.view === 'table' ? '' : '<div class="row sn-leg"><span class="row"><i class="ln"></i>中位数</span><span class="row"><i class="bd"></i>P25–P75</span><span class="row"><i class="br" style="background:' + VZ.sem.corr + '"></i>纠偏 ≥ 你的 P75</span><span class="row" data-tip="情绪为负（情绪负色）或纠偏 ≥ 你的 P90（琥珀）的' + (weeklyB ? '周' : '日') + '"><i class="pt" style="background:' + VZ.sem.corr + '"></i>标注 = 异常' + (weeklyB ? '周' : '日') + '</span></div>') + '<div class="vz" data-vz="mood"></div></div>' +
    '<div class="two sn-two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">摩擦分类</span>' + AIB() + '<span class="cap" data-tip="Δ 为较上期 · 悬停看典型会话">出现该摩擦的会话数 · 点击回看</span></div></div><div class="col" style="gap:2px">' + (fr.length ? '<div class="sn-fric sn-fric-h" aria-hidden="true"><span class="cap">类别</span><span></span><span class="cap">会话</span><span class="cap">Δ 上期</span><span class="cap">均值情绪</span></div>' + fr.map((f, i) => { const xs = L.filter((s) => s.fric === f[0]); const mood = sum(xs, (s) => s.mood) / Math.max(1, xs.length); const prev = frPrev ? (frPrev[f[0]] || 0) : null; const dlt = prev == null ? '' : prev === f[1] ? '± 0' : (f[1] > prev ? '▲ ' : '▼ ') + Math.abs(f[1] - prev); return '<button type="button" class="sn-fric" data-act="fricGo" data-k="' + esc(f[0]) + '" data-tf="fricx|' + esc(f[0]) + '"><span class="sn-fric-n">' + f[0] + '</span><span class="sn-fric-bar"><i style="width:' + (f[1] / frMax * 100) + '%;background:' + (i < 2 ? 'var(--ink-1)' : 'var(--ink-4)') + '"></i></span><span class="mono sn-fric-v">' + f[1] + '</span><span class="mono sn-fric-d ' + (prev == null ? 'na' : f[1] > prev ? 'vz-bad' : f[1] < prev ? 'vz-good' : 'flat') + '">' + (prev == null ? '—' : dlt) + '</span><span class="mono sn-fric-m" style="color:' + (mood < 0 ? VZ.sem.neg : 'var(--ink-3)') + '">' + (mood > 0 ? '+' : '') + f1(mood) + '</span></button>'; }).join('') : '<span class="cap">没有摩擦记录</span>') + '</div><div class="cap sn-foot">前两类占全部摩擦的 ' + (fr.length ? Math.round((fr[0][1] + (fr[1] ? fr[1][1] : 0)) / frTot * 100) : 0) + '%，都可以用规则前置</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">语义主题</span>' + AIB('AI 聚类') + '<span class="cap" data-tip="按会话意图聚类 · 标尺为平均情绪 −1 … +1">点击设为全局筛选</span></div></div><div class="sn-topics">' + tp.map((t, i) => '<button type="button" class="sn-topic' + (S.topic === t.k ? ' on' : '') + (i === 0 ? ' top' : '') + '" data-act="topicSet" data-k="' + t.k + '" aria-pressed="' + (S.topic === t.k) + '"><b title="' + TOPICS[t.k] + '">' + TOPICS[t.k] + '</b><span class="row" style="gap:8px"><span class="mono cap sn-tn">' + t.n + ' 个会话</span>' + divBar(t.mood) + '<span class="mono" style="font-size:11px;color:' + (t.mood < 0 ? VZ.sem.neg : 'var(--ink-2)') + '">' + (t.mood > 0 ? '+' : '') + f1(t.mood) + '</span></span></button>').join('') + '</div></div></div>' +
    '<div class="two" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">你的高频反馈语</span>' + AIB() + '<span class="cap">已脱敏 · 点击查看出处</span></div></div><div class="col" style="gap:4px">' + phrases.map((p) => '<button type="button" class="sn-ph" data-act="phrase" data-k="' + esc(p[0]) + '" data-c="' + esc(p[2]) + '"><span class="sn-ph-t">「' + esc(p[0]) + '」</span><span class="sn-ph-bar"><i style="width:' + (p[1] / phMax * 100).toFixed(0) + '%"></i></span><span class="mono sn-ph-n">×' + p[1] + '</span><span class="sn-ph-c"><i style="background:' + (p[2] === '纠偏' ? VZ.sem.corr : 'var(--ink-4)') + '"></i>' + p[2] + '</span></button>').join('') + '</div><div class="row sn-act"><span class="sn-note" data-tip="让 Agent 先遵守，而不是等你提醒">' + phrases.filter((p) => p[2] === '纠偏').length + ' 条纠偏语可以直接写成规则</span><button type="button" class="btn sm" data-act="phrasesToRule">生成规则草稿</button></div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">情绪的前因</span><span class="cap" data-tip="相关不等于因果">与会话特征的关联 · 须线 = 95% CI</span></div></div><div class="col" style="gap:12px">' + drivers.map((d) => '<div class="sn-drv"><span class="sn-drv-n">' + d.name + '</span>' + divBar(d.v, d.ci) + '<span class="mono sn-drv-v" style="color:' + (d.v < 0 ? VZ.sem.neg : VZ.sem.pos) + '">' + (d.v > 0 ? '+' : '−') + Math.abs(d.v).toFixed(2) + '</span><span class="mono cap sn-drv-k">n=' + d.n + '</span></div>').join('') + '</div><div class="sn-drv sn-drv-ax cap" aria-hidden="true"><span></span><span class="row mono" style="justify-content:space-between;font-size:11px"><span>−0.5</span><span>0</span><span>+0.5</span></span><span></span><span></span></div><div class="cap sn-foot" data-tip="数值为该特征会话与其它会话的情绪均值差（示例）">左 = 情绪更差 · 右 = 更好</div></div></div></div></div>';
};
PAGES.sentiment.after = () => {
  const ms = CUR.mood; if (!ms || S.engine === 'stats') return;
  const weeklyB = (win(S.range)[1] - win(S.range)[0] + 1) > 31;
  VZ.mount('mood', { type: 'moodcorr', title: '情绪分布与纠偏次数', height: 236, buckets: ms, view: S.sent.view || 'chart', label: (b) => b.a === b.b ? mdz(b.a) + ' 周' + WD[wd(b.a)] : md(b.a) + ' – ' + md(b.b) + (weeklyB ? '（周）' : ''), empty: '所选范围内没有会话' });
};
TIPS.fricx = (k) => { const xs = sel().filter((s) => s.fric === k).sort((a, b) => (b.d - a.d) || (b.h - a.h)).slice(0, 3); if (!xs.length) return ''; return '<b>「' + esc(k) + '」典型会话</b>\n' + xs.map((s) => md(s.d) + ' · ' + esc(s.title) + ' · ' + s.corr + ' 次纠偏').join('\n') + '\n<span style="opacity:.7">点击筛选全部相关会话</span>'; };
Object.assign(ACT, {
  fricGo: (el) => { S.fric = el.dataset.k; go('sessions'); toast('已筛选出现「' + el.dataset.k + '」的会话'); },
  topicSet: (el) => { S.topic = S.topic === el.dataset.k ? null : el.dataset.k; render(); },
  moodView: () => { S.sent.view = S.sent.view === 'table' ? 'chart' : 'table'; render(); },
  phrase: (el) => { const xs = phraseSources(el.dataset.k, el.dataset.c); openDD(el, [{ h: '「' + el.dataset.k + '」的出处（' + xs.length + ' 次 · 已脱敏）' }].concat(xs.length ? xs.map((s) => ({ t: md(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + s.title, v: s.id })) : [{ t: '当前筛选下没有出处', v: null, dis: true }]), (v) => { if (!v) return; S.sess.sel = v; S.sess.mode = 'single'; go('sessions'); }); },
  phrasesToRule: () => { S.studio.type = '规则'; S.studio.goal = '把我的高频纠偏写成 AGENTS.md 规则：「直接合并」「别用子代理」「不要改别的文件」「用 Cloudflare 不是 Vercel」。'; S.studio.from = 'A6 高频反馈语'; S.studio.run = null; go('studio'); },
  moodHow: () => openModal(modalHead('情绪如何计算') + '<div class="mb col" style="gap:10px;font-size:13px;line-height:1.6;color:var(--ink-2)"><p style="margin:0">只看你发出的消息，不评判 Agent 的回复。每条消息由本地 Agent 打一个 −1 到 +1 的分，置信度低于 0.6 的不计入。</p><p style="margin:0">每个会话取其消息分数的加权平均；图中每天（或每周）画的是当期会话情绪的 P25–P75 分布带与中位数。纠偏是被判定为「方向修正」或「不满」的消息。</p><p style="margin:0">关闭语义分析后，这一页只保留计数统计。</p></div><div class="mf"><button type="button" class="btn" data-act="openSettings" data-tab="analysis">分析设置</button><button type="button" class="btn p" data-act="closeModal">知道了</button></div>')
});
