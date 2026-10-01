/* ============ A1 overview ============ */
PAGES.overview = () => {
  const L = sel(); const st = stats(L);
  const pw = prevWin(S.range); const P = pw ? stats(sel({ win: pw })) : null;
  const pers = persona(L);
  const d = (cur, prev, unit, goodDown) => {
    if (!S.compare) return ['', 'var(--ink-3)'];
    if (!P || !prev) return ['无可比上期', 'var(--ink-3)'];
    const diff = unit === 'pt' ? cur - prev : (cur - prev) / prev * 100;
    const txt = (diff >= 0 ? '↑ ' : '↓ ') + (unit === 'pt' ? f1(Math.abs(diff)) + ' pt' : unit === 'x' ? f1(Math.abs(cur - prev)) + '×' : Math.round(Math.abs(diff)) + '%');
    const col = goodDown == null ? 'var(--ink-2)' : ((diff < 0) === goodDown ? 'var(--good)' : 'var(--crit)');
    return [txt, col];
  };
  const endDay = win(S.range)[1];
  const tiles = [
    ['n', '会话', fmt(st.n), '', d(st.n, P && P.n), weekly((x) => x.length, endDay, 12), 'sessions'],
    ['h', '协作时长', f1(st.hours).replace('.0', ''), 'h', d(st.hours, P && P.hours), weekly((x) => sum(x, (s) => s.dur), endDay, 12), 'sessions'],
    ['m', '你发出的消息', fmt(st.msgs), '', [f1(st.per) + ' 条 / 会话', 'var(--ink-2)'], weekly((x) => sum(x, (s) => s.msgs), endDay, 12), 'sentiment'],
    ['a', '自主比', f1(st.auto), '×', d(st.auto, P && P.auto, 'x'), weekly((x) => stats(x).auto, endDay, 12), 'persona'],
    ['f', '摩擦率', f1(st.fric), '%', d(st.fric, P && P.fric, 'pt', true), weekly((x) => stats(x).fric, endDay, 12), 'sentiment']
  ];
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]);
  const topF = fr[0];
  const projC = {}; L.forEach((s) => { if (s.corr) projC[s.p] = (projC[s.p] || 0) + s.corr; });
  const topP = Object.entries(projC).sort((a, b) => b[1] - a[1]).slice(0, 2).map((x) => PJI[x[0]].name);
  const topR = visibleRecs().filter((r) => !S.installed.has(r.id)).slice(0, 3);
  const ai = [
    ['做得好', 'okc', 'var(--good)', Math.round(st.verify) + '% 的会话要求测试或线上验证，完成率 ' + Math.round(st.ok) + '%。', '证据 · ' + L.filter((s) => s.verify).length + ' 个会话', 'evGood'],
    ['卡在哪', 'alert', 'var(--crit)', topF ? topF[1] + ' 个会话出现「' + topF[0] + '」' + (topP.length ? '，集中在 ' + topP.join('、') : '') + '。' : '这段时间没有明显的摩擦。', topF ? '证据 · ' + topF[1] + ' 个会话' : '', 'evBad'],
    ['立刻可做', 'bolt', 'var(--ai)', topR.length ? topR.slice(0, 2).map((r) => r.title.split('：')[0]).join('；') + '。' : '建议都已处理。', '查看 ' + topR.length + ' 条建议', 'evRec']
  ];
  const ser = series(L, S.range, S.metric); CUR.trend = ser;
  const vis = AG.map((a) => S.agents.has(a.id));
  const tot = ser.map((b) => b.v.reduce((x, v, j) => x + (vis[j] ? v : 0), 0));
  const mx = Math.max(1, ...tot);
  const step = mx <= 4 ? 1 : mx <= 8 ? 2 : mx <= 16 ? 4 : mx <= 40 ? 10 : mx <= 80 ? 20 : Math.ceil(mx / 4 / 10) * 10;
  const top = Math.ceil(mx / step) * step;
  const W = 720, H = 170, x0 = 30, pw2 = W - x0 - 4, slot = pw2 / ser.length, bw = Math.min(16, slot * 0.62);
  let bars = '';
  ser.forEach((b, i) => {
    let y = H; const last = (() => { let l = -1; b.v.forEach((v, j) => { if (vis[j] && v > 0) l = j; }); return l; })();
    b.v.forEach((v, j) => {
      if (!vis[j] || v <= 0) return;
      const h = v / top * H; const yy = y - h;
      const x = x0 + i * slot + (slot - bw) / 2;
      bars += j === last ? '<path d="M' + x.toFixed(1) + ' ' + (y - 1).toFixed(1) + 'V' + (yy + 3).toFixed(1) + 'q0 -3 3 -3h' + (bw - 6).toFixed(1) + 'q3 0 3 3V' + (y - 1).toFixed(1) + 'Z" fill="' + AG[j].c + '"/>' : '<rect x="' + x.toFixed(1) + '" y="' + yy.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(0.5, h - 2).toFixed(1) + '" fill="' + AG[j].c + '"/>';
      y = yy;
    });
    bars += '<rect x="' + (x0 + i * slot).toFixed(1) + '" y="0" width="' + slot.toFixed(1) + '" height="' + H + '" fill="transparent" class="hov" data-tf="trend|' + i + '"/>';
  });
  let grid = ''; for (let v = 0; v <= top; v += step) { const y = H - v / top * H; grid += '<line x1="' + x0 + '" x2="' + W + '" y1="' + y.toFixed(1) + '" y2="' + y.toFixed(1) + '" stroke="var(--hair)"/><text x="' + (x0 - 6) + '" y="' + (y + 3.5).toFixed(1) + '" text-anchor="end">' + (S.metric === 'tok' ? v + 'M' : v) + '</text>'; }
  const every = Math.ceil(ser.length / 6);
  const xl = ser.map((b, i) => i % every === 0 ? '<text x="' + (x0 + i * slot + slot / 2).toFixed(1) + '" y="' + (H + 16) + '" text-anchor="middle">' + b.lbl + '</text>' : '').join('');
  const unitName = S.metric === 'h' ? '小时' : S.metric === 'tok' ? '百万 tokens' : '会话';
  const table = '<div class="scroll-x"><table class="tbl"><thead><tr><th>' + (ser.length > 31 ? '周起始' : '日期') + '</th>' + AG.filter((a, j) => vis[j]).map((a) => '<th style="text-align:right">' + a.short + '</th>').join('') + '<th style="text-align:right">合计</th></tr></thead><tbody>' + ser.map((b, i) => '<tr><td class="mono">' + b.lbl + '</td>' + b.v.map((v, j) => vis[j] ? '<td class="mono" style="text-align:right">' + (S.metric === 'n' ? v : f1(v)) + '</td>' : '').join('') + '<td class="mono" style="text-align:right;font-weight:600">' + (S.metric === 'n' ? tot[i] : f1(tot[i])) + '</td></tr>').join('') + '</tbody></table></div>';
  const hmap = heat(L); CUR.heat = hmap;
  const hmx = Math.max(1, ...hmap.H.flat());
  let peak = [0, 0]; hmap.H.forEach((r, di) => r.forEach((v, h) => { if (v > hmap.H[peak[0]][peak[1]]) peak = [di, h]; }));
  const night = stats(L.filter((s) => s.h < 3)), day = stats(L.filter((s) => s.h >= 9 && s.h < 18));
  const ratio = day.fric ? night.fric / day.fric : 0;
  const cells = hmap.H.map((r, di) => r.map((v, h) => '<rect x="' + (18 + h * 13) + '" y="' + (di * 13) + '" width="11" height="11" rx="2" fill="var(--h' + Math.min(5, Math.floor(v / hmx * 5.999)) + ')" data-tf="heat|' + di + '|' + h + '" data-act="heatCell" data-h="' + h + '" style="cursor:pointer"/>').join('')).join('');
  const trows = toolRows(L).slice(0, 6); const tmx = Math.max(1, trows[0].n);
  return tbar('概览', winLabel() + ' · ' + st.n + ' 个会话 · ' + AG.filter((a) => S.agents.has(a.id)).length + ' 个 Agent',
    '<button type="button" class="btn gh" data-act="reindex" data-tip="重新索引（⌘R）">' + ic('sync', 13) + '<span data-sync>2 分钟前已同步</span></button><button type="button" class="btn" data-act="report">' + ic('share', 14) + '分享报告</button><button type="button" class="btn ai" data-act="ask" data-ctx="overview">' + ic('spark', 14) + '问本地 Agent</button><button type="button" class="ib" data-act="ovMore" aria-label="更多操作">' + ic('more', 16, 'stroke-width:2.6') + '</button>') +
    '<div class="content" id="content">' + filterRow('<label class="row cap" style="font-size:12.5px;color:var(--ink-2)">对比上一周期<button type="button" class="sw' + (S.compare ? ' on' : '') + '" data-act="compare" aria-pressed="' + S.compare + '" aria-label="对比上一周期"></button></label>') +
    '<div class="stack">' +
    '<div class="card pad ov-ai" id="aiCard"><div class="col" style="gap:8px"><div class="row" style="flex-wrap:wrap"><span class="aib">' + ic('spark', 11) + 'AI 解读</span><span class="cap" style="font-size:11.5px" data-aigen>本地 Claude Code 生成 · 9/30 23:10</span><button type="button" class="btn sm gh" data-act="regen" style="margin-left:auto">重新生成</button></div><p class="serif" id="aiLead" style="margin:0;font-size:17px;line-height:1.5;font-weight:500;text-wrap:pretty">' + (pers.ok ? '你像一位' + pers.zh + '：' + pers.line : '样本不足：所选范围只有 ' + st.n + ' 个会话，至少需要 30 个才给出协作画像。') + '</p></div>' +
    ai.map((g) => '<div class="col" style="gap:6px"><div class="row" style="font-size:12px;font-weight:600">' + ic(g[1], 14, 'color:' + g[2]) + g[0] + '</div><p style="margin:0;font-size:12.5px;line-height:1.55;color:var(--ink-2)">' + esc(g[3]) + '</p>' + (g[4] ? '<button type="button" class="lnk" data-act="' + g[5] + '" style="align-self:flex-start;margin-top:auto">' + esc(g[4]) + '</button>' : '') + '</div>').join('') + '</div>' +
    '<div class="tiles">' + tiles.map((t) => '<button type="button" class="card tile" data-act="go" data-r="' + t[6] + '" data-tf="def|' + t[0] + '"><span class="row" style="justify-content:space-between;width:100%"><span style="font-size:12px;color:var(--ink-2)">' + t[1] + '</span>' + spark(t[5]) + '</span><span class="row" style="align-items:baseline;gap:3px"><span class="v">' + t[2] + '</span><span style="font-size:13px;color:var(--ink-3)">' + t[3] + '</span></span><span style="font-size:11.5px;color:' + t[4][1] + ';font-weight:600;white-space:nowrap">' + (t[4][0] || '&nbsp;') + '</span></button>').join('') + '</div>' +
    '<div class="two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">Agent 使用趋势</span><span class="cap">' + (ser.length > 31 ? '每周' : '每日') + unitName + ' · 按 Agent 堆叠</span></div><div class="seg" role="group" aria-label="度量">' + [['n', '会话'], ['h', '时长'], ['tok', 'Tokens']].map((m) => '<button type="button" data-act="metric" data-v="' + m[0] + '" class="' + (S.metric === m[0] ? 'on' : '') + '">' + m[1] + '</button>').join('') + '</div><div class="seg" role="group" aria-label="视图"><button type="button" data-act="view" data-v="chart" class="' + (S.view === 'chart' ? 'on' : '') + '" aria-label="图表视图" style="padding:0 6px">' + ic('chart', 14) + '</button><button type="button" data-act="view" data-v="table" class="' + (S.view === 'table' ? 'on' : '') + '" aria-label="表格视图" style="padding:0 6px">' + ic('grid', 14) + '</button></div></div>' +
    '<div class="legend" style="margin-bottom:8px">' + AG.map((a, j) => '<button type="button" class="' + (vis[j] ? '' : 'off') + '" data-act="agentToggle" data-a="' + a.id + '" data-tip="点击只看该 Agent；⌥ 点击多选"><span class="sq" style="background:' + a.c + '"></span>' + a.name + '<b class="mono" style="color:var(--ink-1)">' + (S.metric === 'n' ? L.filter((s) => s.a === a.id).length : f1(sum(ser, (b) => b.v[j]))) + '</b></button>').join('') + '</div>' +
    (S.view === 'chart' ? '<svg class="chart" viewBox="0 0 ' + W + ' ' + (H + 22) + '" role="img" aria-label="每日各 Agent 会话数堆叠柱状图">' + grid + bars + '<line x1="' + x0 + '" x2="' + W + '" y1="' + H + '" y2="' + H + '" stroke="var(--line)"/>' + xl + '</svg>' : table) + '</div>' +
    '<button type="button" class="card pad" data-act="go" data-r="persona" style="text-align:left;display:flex;flex-direction:column;gap:10px"><span class="row" style="justify-content:space-between;width:100%"><span class="eb">协作人格 · ' + rangeLabel() + '</span><span class="bdg">置信度 ' + (pers.ok ? pers.conf : '低') + ' · n=' + st.n + '</span></span>' +
    (pers.ok ? '<span class="serif" style="font-size:40px;line-height:44px;font-weight:600;letter-spacing:.04em">' + pers.code + '</span><span class="row" style="align-items:baseline"><span class="serif" style="font-size:20px;font-weight:600">' + pers.zh + '</span><span class="serif" style="font-size:15px;font-style:italic;color:var(--ink-3)">' + pers.en + '</span></span>' + [0, 1, 2, 3].map((i) => { const a = axisView(pers, i); return '<span style="display:grid;grid-template-columns:50px minmax(0,1fr) 50px 24px;align-items:center;gap:8px;font-size:12px;width:100%"><span style="color:' + (a.leftWins ? 'var(--ink-1)' : 'var(--ink-3)') + ';font-weight:' + (a.leftWins ? 700 : 400) + '"><span class="mono">' + a.ax.L + '</span> ' + a.ax.Ln + '</span><span class="track" style="height:6px"><span class="mid"></span><span class="fill" style="height:6px;left:' + Math.min(a.pos, 50) + '%;width:' + Math.abs(a.pos - 50) + '%"></span><span class="knob" style="width:12px;height:12px;margin-left:-6px;top:-3px;left:' + a.pos + '%"></span></span><span style="text-align:right;color:' + (!a.leftWins ? 'var(--ink-1)' : 'var(--ink-3)') + ';font-weight:' + (!a.leftWins ? 700 : 400) + '">' + a.ax.Rn + ' <span class="mono">' + a.ax.R + '</span></span><span class="mono" style="text-align:right;font-weight:600">' + a.strong + '</span></span>'; }).join('') : '<span class="cap">再积累 ' + (30 - st.n) + ' 个会话后揭晓</span>') +
    '<span class="row" style="margin-top:auto;justify-content:space-between;width:100%"><span class="cap">点击查看完整画像</span>' + ic('arrow', 14) + '</span></button></div>' +
    '<div class="three">' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">活跃节律</span><span class="cap">消息数 · 周 × 小时</span></div></div><svg viewBox="0 0 332 106" style="width:100%;height:auto" role="img" aria-label="一周七天乘二十四小时的活跃热力图">' + WD.map((w, i) => '<text x="0" y="' + (i * 13 + 9) + '" font-size="10" fill="var(--ink-3)">' + w + '</text>').join('') + cells + '<rect x="' + (18 + peak[1] * 13 - 2) + '" y="' + (peak[0] * 13 - 2) + '" width="15" height="15" rx="4" fill="none" stroke="var(--ink-1)" stroke-width="1.5"/>' + [0, 6, 12, 18, 23].map((h) => '<text x="' + (18 + h * 13 + 5.5) + '" y="104" font-size="10" text-anchor="middle" font-family="var(--mono)" fill="var(--ink-3)">' + h + '</text>').join('') + '</svg><div class="row" style="justify-content:space-between;margin-top:8px;flex-wrap:wrap;gap:8px"><span style="font-size:12px;color:var(--ink-2)"><b style="color:var(--ink-1)">高峰 周' + WD[peak[0]] + ' ' + peak[1] + '–' + (peak[1] + 1) + ' 时</b>' + (ratio ? ' · 深夜纠偏率为白天 ' + f1(ratio) + '×' : '') + '</span><span class="row" style="gap:2px" aria-label="颜色图例：少到多"><span class="cap" style="font-size:10.5px;margin-right:3px">少</span>' + [1, 2, 3, 4, 5].map((k) => '<span style="width:9px;height:9px;border-radius:2px;background:var(--h' + k + ')"></span>').join('') + '<span class="cap" style="font-size:10.5px;margin-left:3px">多</span></span></div><div class="cap" style="font-size:11px;margin-top:6px">点击格子：查看该时段的会话</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">工具调用 Top 6</span></div><button type="button" class="lnk" data-act="go" data-r="tools">全部 11 种</button></div><div class="col" style="gap:6px">' + trows.map((t) => '<button type="button" data-act="openTool" data-t="' + t.name + '" style="display:grid;grid-template-columns:66px minmax(0,1fr) 44px 62px;align-items:center;gap:8px;height:22px;border:0;background:none;padding:0;text-align:left"><span class="mono" style="font-size:12px">' + t.name + '</span><span style="height:10px"><span style="display:block;height:10px;width:' + (t.n / tmx * 100).toFixed(1) + '%;min-width:2px;border-radius:0 4px 4px 0;background:var(--ink-2)"></span></span><span class="mono" style="font-size:11.5px;text-align:right">' + fmt(t.n) + '</span><span class="row" style="justify-content:flex-end;gap:3px;font-size:11px;color:' + (t.err > 0.1 ? 'var(--crit)' : 'var(--ink-3)') + ';font-weight:' + (t.err > 0.1 ? 600 : 400) + '">' + (t.err > 0.1 ? ic('alert', 12) : '') + '<span class="mono">' + f1(t.err * 100) + '%</span></span></button>').join('') + '</div><div class="cap" style="font-size:11px;margin-top:8px">右列为错误率 · 超过 10% 以图标标出</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">本周建议</span></div><button type="button" class="lnk" data-act="go" data-r="recs">全部 ' + visibleRecs().length + ' 条</button></div><div class="col" style="gap:8px">' + (topR.length ? topR.map((r) => '<div class="row" style="min-height:48px;gap:10px"><span style="width:32px;height:32px;border-radius:8px;flex:none;display:grid;place-items:center;background:var(--sunken)">' + ic(r.icon) + '</span><button type="button" data-act="openRec" data-id="' + r.id + '" style="flex:1;min-width:0;border:0;background:none;padding:0;text-align:left"><span style="display:block;font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(r.title) + '</span><span style="display:block;font-size:11.5px;color:var(--ink-3)"><span class="mono" style="color:var(--ink-2)">' + r.type + '</span> · ' + r.gain + ' · L' + r.lvl + '</span></button>' + recPrimaryBtn(r, true) + '</div>').join('') : '<div class="cap">建议都已处理，下周再看看。</div>') + '</div></div>' +
    '</div></div></div>';
};
TIPS.trend = (i) => { const b = CUR.trend && CUR.trend[+i]; if (!b) return ''; const vis = AG.map((a) => S.agents.has(a.id)); const t = b.v.reduce((x, v, j) => x + (vis[j] ? v : 0), 0); const fmtv = (v) => S.metric === 'n' ? v : f1(v); return '<div style="display:flex;justify-content:space-between;gap:14px;margin-bottom:6px"><b>' + (b.a === b.b ? mdz(b.a) + ' 周' + WD[wd(b.a)] : md(b.a) + ' – ' + md(b.b)) + '</b><span class="mono" style="opacity:.75">' + fmtv(t) + (S.metric === 'n' ? ' 个会话' : S.metric === 'h' ? ' h' : 'M') + '</span></div>' + b.v.map((v, j) => vis[j] && v ? '<div style="display:flex;align-items:center;gap:8px"><span style="width:10px;height:2px;background:' + AG[j].c + '"></span><b class="mono">' + fmtv(v) + '</b><span style="opacity:.8">' + AG[j].name + '</span></div>' : '').join(''); };
TIPS.heat = (di, h) => { const v = CUR.heat.H[di][h], c = CUR.heat.C[di][h]; return '<b>周' + WD[di] + ' ' + h + ':00–' + (+h + 1) + ':00</b>\n' + v + ' 条消息 · 纠偏 ' + c + ' 次' + (v ? '（' + f1(c / v * 100) + '%）' : ''); };
function recPrimaryBtn(r, small) {
  const inst = S.installed.has(r.id);
  if (inst) return '<button type="button" class="btn' + (small ? ' sm' : '') + '" data-act="openRec" data-id="' + r.id + '" data-tab="track">已安装 · 追踪中</button>';
  const p = r.primary;
  const act = /复制/.test(p) ? 'copyRec' : /教程/.test(p) ? 'tutorial' : /交给/.test(p) ? 'recToStudio' : 'install';
  return '<button type="button" class="btn' + (small ? ' sm' : '') + (act === 'install' ? ' p' : act === 'recToStudio' ? ' ai' : '') + '" data-act="' + act + '" data-id="' + r.id + '">' + p + '</button>';
}
Object.assign(ACT, {
  compare: () => { S.compare = !S.compare; render(); },
  metric: (el) => { S.metric = el.dataset.v; render(); },
  view: (el) => { S.view = el.dataset.v; render(); },
  heatCell: (el) => { S.hour = +el.dataset.h; go('sessions'); toast('已筛选 ' + el.dataset.h + ':00–' + (+el.dataset.h + 1) + ':00 开始的会话'); },
  openTool: (el) => { S.tools.open = el.dataset.t; go('tools'); },
  evGood: () => { S.outcome = 'ok'; go('sessions'); },
  evBad: () => { const fr = Object.entries(countBy(sel(), 'fric')).sort((a, b) => b[1] - a[1]); if (fr[0]) S.fric = fr[0][0]; go('sessions'); },
  evRec: () => go('recs'),
  regen: () => {
    const p = personaNow(); const el = $('#aiLead'); if (!el) return;
    const variants = p.ok ? ['你像一位' + p.zh + '：' + p.line, '一句话：你把大块目标交给 Agent，并且很在意结果是否真的可用。', '你的协作重心在「交出去」和「收回来」两端：委托得多，验收也严。'] : ['样本不足，暂不下结论。'];
    const txt = variants[Math.floor(Math.random() * variants.length)];
    el.textContent = ''; $('[data-aigen]').innerHTML = '<span class="spin" style="width:10px;height:10px;vertical-align:-1px"></span> 本地 Claude Code 生成中…';
    let i = 0; const t = setInterval(() => { i += 2; el.textContent = txt.slice(0, i); if (i >= txt.length) { clearInterval(t); const g = $('[data-aigen]'); if (g) g.textContent = '本地 Claude Code 生成 · 刚刚'; } }, 30);
  },
  reindex: () => reindex(),
  report: () => openReport(),
  ovMore: (el) => openDD(el, [{ t: '重新索引', k: '⌘R', v: () => reindex() }, { t: '导出工具明细 CSV…', v: () => openCSV() }, { t: '键盘快捷键', k: '?', v: () => openKeys() }], (v) => v())
});
function reindex() {
  const s = $('[data-sync]'); if (s) s.innerHTML = '<span class="spin" style="width:11px;height:11px;vertical-align:-1px"></span> 正在索引…';
  const c = $('#content'); if (c) c.classList.add('stale');
  setTimeout(() => { if (c) c.classList.remove('stale'); const s2 = $('[data-sync]'); if (s2) s2.textContent = '刚刚已同步'; toast('索引完成：新增 0 个会话，2,416 个会话均已是最新'); }, 1200);
}

