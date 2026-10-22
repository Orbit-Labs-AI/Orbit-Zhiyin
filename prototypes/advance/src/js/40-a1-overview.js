/* ============ A1 overview ============
 * 结构：先下结论（AI 解读 + 三栏微型证据）→ 五张指标卡（环比三件套 + 极性着色 + 带周期的迷你线）→ 会话结果构成
 * → Agent 趋势（VZ 堆叠柱：周末底纹 / 均值线 / 本图图例 / 堆叠·分组·100% / 刷选重算指标卡）+ 人格卡（双向条）
 * → 活跃节律（VZ 热力图：消息数 / 纠偏率）+ 工具 Top 6（浅条 + 错误率微型条）+ 本周建议。
 * 页面状态放在 S.ov；图表在 PAGES.overview.after 里用 VZ.mount 挂载。 */
S.ov = S.ov || { stack: 'stacked', heat: 'msgs', hidden: [], lede: null, synced: '2 分钟前已同步', brush: null };
let OV_T = null;   // 「重新生成」的打字定时器：连点只保留最后一次（BUG-66）
function ovDaily(fn, endDay, n) { const out = []; for (let k = n - 1; k >= 0; k--) { const d = endDay - k; out.push(fn(ALL.filter((s) => s.d === d && pass(s, { noExtra: true })))); } return out; }
function ovTrend(fn, endDay) { return S.range === 7 ? ovDaily(fn, endDay, 7) : weekly(fn, endDay, 12); }
// 指标卡：delta 为 VZ.delta2 的输入（▲▼ + 变化量 + 上期值，按极性着色）；brushed 时不比上期，只说明范围
function ovTiles(L, P, brushed) {
  const st = stats(L); const endDay = win(S.range)[1]; const tl = S.range === 7 ? '近 7 天' : '近 12 周';
  const cmp = S.compare && !brushed && P;
  const dl = (cur, prev, o) => cmp ? Object.assign({ cur, prev }, o) : null;
  const sub = brushed ? '刷选范围' : S.compare && !P ? '缩短时期以比较' : '';
  const autoD = cmp && P.msgs && P.auto ? { text: (st.auto - P.auto >= 0 ? '▲ +' : '▼ −') + f1(Math.abs(st.auto - P.auto)) + ' · 上期 ' + f1(P.auto) + '×', cls: '' } : null;
  const tiles = [
    { k: 'n', label: '会话', value: fmt(st.n), delta: dl(st.n, P && P.n, { unit: 'pct', fmt: 'int' }), trend: ovTrend((x) => x.length, endDay), r: 'sessions' },
    { k: 'h', label: '协作时长', value: f1(st.hours).replace('.0', ''), unit: 'h', delta: dl(st.hours, P && P.hours, { unit: 'pct', fmt: (v) => f1(v) + 'h' }), trend: ovTrend((x) => sum(x, (s) => s.dur), endDay), r: 'sessions' },
    { k: 'f', label: '摩擦率', value: st.msgs ? f1(st.fric) : '—', unit: st.msgs ? '%' : '', delta: st.msgs && P && P.msgs ? dl(st.fric, P.fric, { unit: 'pt', goodDown: true, fmt: (v) => f1(v) + '%' }) : null, trend: ovTrend((x) => stats(x).fric, endDay), r: 'sentiment' }
  ];
  // F08: while the data is still being imported / analysed nothing has been measured yet — no 0, no delta, no trend
  const busy = dataBusy();
  if (busy) return tiles.map((t) => VZ.kpi({ label: t.label, value: '—', sub: busyShort(busy), act: 'go', attrs: ' data-r="' + t.r + '" data-k="' + t.k + '" data-busy', tf: 'def|' + t.k })).join('');
  return tiles.map((t) => VZ.kpi({ label: t.label, value: t.value, unit: t.unit, delta: t.delta, sub: t.sub && !t.delta ? t.sub : sub, trend: t.trend, trendLabel: tl, sparkOpt: { w: 40, h: 20 }, act: 'go', attrs: ' data-r="' + t.r + '" data-k="' + t.k + '"', tf: 'def|' + t.k })).join('');
}
// AI 解读三栏的 24px 微型证据：完成率环 / 摩擦类型条 / 建议数
function ovMini(kind, a, b) {
  if (kind === 'ring') { const r = 9, c = 2 * Math.PI * r; return '<svg class="ov-mini" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="' + r + '" fill="none" stroke="var(--line)" stroke-width="3"/>' + (a == null ? '' : '<circle cx="12" cy="12" r="' + r + '" fill="none" stroke="var(--good)" stroke-width="3" stroke-linecap="round" stroke-dasharray="' + (c * a / 100).toFixed(1) + ' ' + c.toFixed(1) + '" transform="rotate(-90 12 12)"/>') + '</svg>'; }
  if (kind === 'bars') { const mx = Math.max(1, ...a); return '<svg class="ov-mini" width="36" height="24" viewBox="0 0 36 24" aria-hidden="true">' + a.slice(0, 3).map((v, i) => '<rect x="0" y="' + (i * 8) + '" width="' + Math.max(2, v / mx * 36).toFixed(1) + '" height="6" rx="1.5" fill="' + (i === 0 ? 'var(--crit)' : 'var(--h2)') + '"/>').join('') + '</svg>'; }
  return '<svg class="ov-mini" width="' + (Math.max(1, a + b) * 9) + '" height="24" viewBox="0 0 ' + (Math.max(1, a + b) * 9) + ' 24" aria-hidden="true">' + Array.from({ length: a + b }, (_, i) => '<rect x="' + (i * 9) + '" y="8" width="7" height="7" rx="1.5" fill="' + (i < a ? 'var(--ai)' : 'none') + '" stroke="var(--ai)" stroke-width="1.2"/>').join('') + '</svg>';
}
// projection_pending（首次导入还没发布）是正常的进行中状态，不当成「取不到」（F08）；与 OrbitLive.ui.pending 同一判定
function persPending(e) { return !!e && (e.code === 'projection_pending' || e.reason === 'projection_pending'); }
// 人格未揭晓：保留卡片的结构（占位码 + 进度 + 四轴空轨），不留大块空白，也不编造数值（R4-14）
function ovPersEmpty(pers) {
  const n = pers.n || 0; const need = 0;   // 1 个会话即可出结论：这里只剩「没有会话 / 取不到 / 暂不计算」三种空态，不再有进度条
  const busy = dataBusy();   // 导入 / 整理 / 分析还在进行：说明进度，不写「还没有会话」，也不给导入入口（F08）
  const pend = persPending(pers.error) || !!busy;   // 首次导入还没发布：正在整理，不是取不到也不是没有会话（F08）
  const why = busy ? (busy.n ? '已导入 ' + fmt(busy.n) + ' 个会话 · ' : '') + (busy.err ? busyThen(busy) : '分析完成后自动显示') + '画像' : pend ? '导入的会话发布后会自动显示画像' : pers.error ? '画像暂时取不到，稍后会自动重试' : !n ? '还没有会话 · 有 1 个会话即可揭晓' : '当前筛选下暂不计算画像';
  // 没有画像时不放占位码（F21）：虚线花形轮廓 + 一句说明；没有会话时给导入入口
  return '<div class="ov-code-r" data-lv="pers-empty">' + emptyBloomSVG(56) + '<span class="col" style="gap:4px;min-width:0"><span class="serif" style="font-size:18px;font-weight:600;color:var(--ink-2)">' + (busy ? busy.t : pend ? '正在整理数据…' : pers.error ? '画像暂时取不到' : '还没有长出来') + '</span>' + (!n && !pers.error && !pend ? emptyActs(false) : '') + '</span></div>' +
    '<div class="col" style="gap:5px"><div class="row" style="justify-content:space-between;gap:8px"><span class="cap">' + why + '</span>' + (need ? '<span class="mono cap">' + n + '</span>' : '') + '</div>' +
    (need ? '<div style="height:4px;border-radius:2px;background:var(--sunken);overflow:hidden"><i style="display:block;height:100%;width:0%;background:var(--ink-3);border-radius:2px"></i></div>' : '') + '</div>' +
    '<div class="col" style="gap:12px;margin:auto 0" aria-label="四个维度尚无数值">' + AXES.map((ax) => '<div style="display:grid;grid-template-columns:64px minmax(0,1fr) 64px;align-items:center;gap:8px;font-size:11.5px;color:var(--ink-3)"><span class="mono">' + ax.L + ' ' + ax.Ln + '</span><span style="height:10px;border-radius:5px;border:1px dashed var(--line)"></span><span class="mono" style="text-align:right">' + ax.Rn + ' ' + ax.R + '</span></div>').join('') + '</div>';
}
// 「AI 解读」徽标只给模型写成的解读：live 下以 insight.basis 为准（ai_narrative），规则模板写成的标中性的「规则解读」，
// 不用 AI 紫；demo 是预置的 Claude Code 示例，保持原样
let OV_BADGE = null;
function ovInsAI(ins) { return !LV.live || !!(ins && ins.basis === 'ai_narrative'); }
function ovInsBadge(ins) { return ovInsAI(ins) ? '<span class="aib">' + ic('spark', 11) + 'AI 解读</span>' : '<span class="tag" data-lv="ins-basis">规则解读</span>'; }
// live 的来源行：模型写成的写明执行者与完成时间，否则是规则模板
function ovInsWhen(ins) {
  if (!ins) return '规则模板 · 本地生成';
  if (ins.basis !== 'ai_narrative') return ins.when || '规则模板 · 本地生成';
  const src = ins.source || {}; const nm = src.engine ? (typeof tlsEngName === 'function' ? tlsEngName(src.engine) : src.engine) : null;
  const t = src.finished_at ? new Date(src.finished_at) : null;
  return (ins.when || 'AI 撰写') + (nm ? ' · ' + nm : '') + (t ? ' · ' + (t.getMonth() + 1) + '/' + t.getDate() + ' ' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0') : '');
}
PAGES.overview = () => {
  const L = sel(); const st = stats(L);
  const pw = prevWin(S.range); const P = pw ? stats(sel({ win: pw })) : null;
  const pers = personaNow();   // 与侧栏、报告同一口径（BUG-06）
  const note = personaScopeNote();
  S.ov.brush = null;
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]);
  const topF = fr[0];
  const projC = {}; L.forEach((s) => { if (s.corr) projC[s.p] = (projC[s.p] || 0) + s.corr; });
  const topP = Object.entries(projC).sort((a, b) => b[1] - a[1]).slice(0, 2).map((x) => PJI[x[0]].name);
  const topR = recTop('A1').slice(0, 3); const rNone = recNone(); const busy = dataBusy();
  const okN = L.filter((s) => s.out === 'ok').length;
  // live: the insight texts come from /v1/uiview/overview (L0 template, same scope); the micro evidence stays spine-derived
  const OVL = LV.live ? (LV.ready('overview') && LV.ov ? LV.ov : null) : undefined; const ins = OVL && OVL.insight;
  const pendTxt = LV.live && !OVL && LV.feedState('overview') !== 'error';   // 404 / 501: the spine-derived texts stay, tools say 暂无数据
  const ai = [
    ['卡在哪', 'alert', 'var(--crit)', ins && ins.stuck ? ins.stuck.text : topF ? topF[1] + ' 个会话出现「' + topF[0] + '」' + (topP.length ? '，集中在 ' + topP.join('、') : '') + '。' : st.msgs ? '这段时间没有明显的摩擦。' : '会话里没有你发出的消息，暂时判断不了卡在哪。', topF ? '证据 · ' + topF[1] + ' 个会话' : '', 'evBad', ovMini('bars', fr.map((x) => x[1]))],
    ['立刻可做', 'bolt', 'var(--ai)', topR.length ? topR.slice(0, 2).map((r) => r.title.split('：')[0]).join('；') + '。' : ins && ins.next && ins.next.text && !rNone.k.match(/busy|none/) ? ins.next.text : rNone.t, topR.length ? '查看 ' + topR.length + ' 条建议' : rNone.k === 'done' ? '查看已处理的建议' : '', 'evRec', ovMini('dots', topR.length, Math.min(4, Array.from(S.installed.keys()).length))]
  ];
  // 0 sessions in range: no praise / friction verdict (the backend's 「这段时间还没有会话」 next to 「查看 3 条建议」 read as
  // contradictory); the range note under the filter row offers the wider range instead
  if (!st.n) { ai[0][3] = '—'; ai[0][4] = ''; ai[1][3] = '—'; ai[1][4] = ''; }
  const ledeKey = S.range + '|' + (pers.ok ? pers.code : '-') + '|' + Array.from(S.agents).join(',');
  const lede = S.ov.lede && S.ov.lede.key === ledeKey ? S.ov.lede.txt : ins && ins.lede ? ins.lede : (pers.ok ? '你像一位' + pers.zh + '：' + pers.line + (pers.hint ? '（' + pers.hint + '）' : '') : busy ? busy.t.replace(/…$/, '') + '，' + (busy.err ? busyThen(busy) : '完成后在这里给出') + '协作画像。' : '所选范围还没有会话，暂时无法给出协作画像。');
  const ledeWhen = S.ov.lede && S.ov.lede.key === ledeKey ? '本地 Claude Code 生成 · 刚刚' : LV.live ? ovInsWhen(ins) : '本地 Claude Code 生成 · 9/30 23:10';
  const caveat = LV.live && ins && ins.basis === 'ai_narrative' && (ins.caveats || []).length ? ins.caveats.join('；') : '';
  // live「重新生成」提交 narrate.overview：Agent 子集、项目与「全部」都有各自的 ai_scope；主题 / 结果 / 摩擦 / 时段筛选与刷选没有，按钮如实不可用
  // 不可用时用 aria-disabled 而非 disabled：按钮仍可悬停 / 聚焦看到原因，点击由 ACT.regen 提示
  const regenOff = LV.live && !(ins && ins.ai_scope);
  // 生成中（LV.ovRegen，91-live-persona）：重绘后仍显示进度，按钮变为「停止」可取消作业
  const regenRun = LV.live && LV.ovRegen;
  const regenTip = regenOff ? (ins ? '按主题、结果、摩擦、时段筛选或刷选时间段的视图暂不生成 AI 解读：清除这些筛选后再生成（Agent 与项目筛选可以保留）' : '数据载入后可生成') : LV.live ? '交给本地 Agent 依据当前数据重写（会调用其模型服务，计入今日 AI 花费）' : '';
  // 无会话且没有洞察 lede 时，那句话是固定说明而不是 AI 输出：不挂解读标记与生成来源（与 Lite 首页 said 同一规则）
  const said = (S.ov.lede && S.ov.lede.key === ledeKey) || (ins && ins.lede) || pers.ok || pendTxt || regenRun;
  OV_BADGE = said ? (ovInsAI(ins) ? 'AI 解读' : '规则解读') : null;   // the page guide names this badge (37-motion GUIDE)
  const ledeP = pendTxt && !(S.ov.lede && S.ov.lede.key === ledeKey) ? LV.pend(48) : '<p class="serif" id="aiLead" style="margin:0;font-size:17px;line-height:1.5;font-weight:500;text-wrap:pretty">' + esc(lede) + '</p>';
  const ser = series(L, S.range, S.metric); CUR.trend = ser;
  const unitName = S.metric === 'h' ? '小时' : S.metric === 'tok' ? 'tokens · 估算' : '会话';
  const vis = AG.map((a) => !S.ov.hidden.includes(a.name));
  const tot = ser.map((b) => b.v.reduce((x, v, j) => x + (vis[j] ? v : 0), 0));
  const hmap = heat(L); CUR.heat = hmap;
  let peak = [0, 0]; hmap.H.forEach((r, di) => r.forEach((v, h) => { if (v > hmap.H[peak[0]][peak[1]]) peak = [di, h]; }));
  const night = stats(L.filter((s) => s.h < 3)), day = stats(L.filter((s) => s.h >= 9 && s.h < 18));
  const ratio = day.fric ? night.fric / day.fric : 0;
  const peakV = hmap.H[peak[0]][peak[1]];
  const heatLine = busy ? busy.t : S.ov.heat === 'msgs' ? !peakV ? '这段时间没有你发出的消息' : '高峰 周' + WD[peak[0]] + ' ' + peak[1] + '–' + (peak[1] + 1) + ' 时 · ' + peakV + ' 条消息' : (ratio ? '深夜（0–3 时）纠偏率为白天的 ' + f1(ratio) + '×' : '深夜样本不足，暂不比较') + ' · 整体 ' + fricTxt(st);
  // live: tool top 6 from /v1/uiview/overview.tools (real tool names, err over known statuses only; null → —)
  const trows = LV.live ? (OVL ? (OVL.tools && OVL.tools.top || []).map((t) => { const why = typeof lvtpRateWhy === 'function' ? lvtpRateWhy(t) : null; return { name: t.name, n: t.n, err: why ? null : t.err, why: why || (t.err == null ? '状态未知，不计算错误率' : null) }; }) : []) : toolRows(L).slice(0, 6);
  const tmx = Math.max(1, trows[0] ? trows[0].n : 1); const tkinds = LV.live ? (OVL && OVL.tools ? OVL.tools.kinds_total : 0) : 11;
  const terr = (t) => t.err == null ? '<span class="mono e"' + (t.why ? ' data-tip="' + esc(t.why) + '"' : '') + '>—</span><span class="eb-bar"><span style="width:0%"></span></span>' : '<span class="mono e' + (t.err > 0.1 ? ' hi' : '') + '">' + f1(t.err * 100) + '%</span><span class="eb-bar' + (t.err > 0.1 ? ' hi' : '') + '"><span style="width:' + Math.min(100, t.err / 0.2 * 100).toFixed(1) + '%"></span></span>';
  const outc = [['ok', '完成'], ['part', '部分完成'], ['fail', '放弃']].map((o) => ({ id: o[0], name: o[1], value: L.filter((s) => s.out === o[0]).length, color: OUT[o[0]][1] }));
  const outKnown = outc.reduce((a, o) => a + o.value, 0);   // sessions with an outcome signal; the rest are 结果未知
  const outLine = outc.map((o) => o.name + ' ' + pctKnown(o.value / Math.max(1, outKnown) * 100, outKnown)).join(' · ') + (outKnown < st.n ? ' · 结果未知 ' + (st.n - outKnown) + ' 个会话' : '');
  return tbar('概览', winLabel() + ' · ' + (busy ? busyMeta(busy) : st.n + ' 个会话 · ' + (ALL.length ? new Set(L.map((s) => s.a)).size + ' 个 Agent' : '还没有会话')),
    '<button type="button" class="btn gh" data-act="reindex" data-tip="重新索引（⌘R）">' + ic('sync', 13) + '<span data-sync>' + esc(S.ov.synced) + '</span></button><button type="button" class="ib" data-act="ovMore" aria-label="更多操作">' + ic('more', 16, 'stroke-width:2.6') + '</button>') +
    '<div class="content" id="content">' + filterRow('<label class="row cap" style="font-size:12px;color:var(--ink-2)">对比上一周期<button type="button" class="sw' + (S.compare ? ' on' : '') + '" data-act="compare" aria-pressed="' + S.compare + '" aria-label="对比上一周期"></button></label>') +
    '<div class="stack">' +
    // 先下结论：AI 解读一句话 + 三栏（每栏一个微型证据图 + 证据链接）
    '<div class="card pad ov-ai" id="aiCard"><div class="col ov-aic ov-ail"><div class="row ov-aih">' + (said ? ovInsBadge(ins) + (regenRun ? '<button type="button" class="btn sm gh" data-act="regenStop" data-tip="取消这次生成，卡片保持现有内容">' + ic('x', 12) + '停止</button>' : '<button type="button" class="btn sm gh" data-act="regen"' + (regenOff ? ' aria-disabled="true"' : '') + (regenTip ? ' data-tip="' + esc(regenTip) + '"' : '') + '>' + ic('sync', 12) + (LV.live && !ovInsAI(ins) ? 'AI 生成' : '重新生成') + '</button>') : '<span class="eb">协作画像</span>') + '</div>' + ledeP + (note ? '<span class="cap" style="font-size:11px">' + esc(note) + '</span>' : '') + '</div>' +
    ai.map((g) => '<div class="col ov-aic"><div class="row ov-aih"><span class="row ov-aik">' + ic(g[1], 14, 'color:' + g[2]) + g[0] + '</span>' + g[6] + '</div>' + (pendTxt && g[5] !== 'evRec' ? LV.pend(36) : '<p class="ov-aip">' + esc(g[3]) + '</p>') + (g[4] ? '<button type="button" class="lnk ov-aiev" data-act="' + g[5] + '">' + esc(g[4]) + '</button>' : '') + '</div>').join('') + '</div>' +
    '<div class="tiles" id="ovTiles">' + ovTiles(L, P) + '</div>' +
    '<div class="two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">Agent 使用趋势</span><span class="cap">' + (ser.length > 31 ? '每周' : '每日') + unitName + (S.metric === 'tok' ? ' <span class="bdg">示例</span>' : '') + ' · ' + ({ stacked: '按 Agent 堆叠', grouped: '按 Agent 分组', pct: '各 Agent 占比' })[S.ov.stack] + '<span data-ovavg></span></span></div></div><div class="row ov-ctl"><div class="seg" role="group" aria-label="度量">' + [['n', '会话'], ['h', '时长'], ['tok', 'Tokens']].map((m) => '<button type="button" data-act="metric" data-v="' + m[0] + '" class="' + (S.metric === m[0] ? 'on' : '') + '">' + m[1] + '</button>').join('') + '</div><div class="seg" role="group" aria-label="堆叠方式">' + [['stacked', '堆叠'], ['grouped', '分组'], ['pct', '100%']].map((m) => '<button type="button" data-act="stackMode" data-v="' + m[0] + '" class="' + (S.ov.stack === m[0] ? 'on' : '') + '">' + m[1] + '</button>').join('') + '</div><div class="seg" role="group" aria-label="视图"><button type="button" data-act="view" data-v="chart" class="' + (S.view === 'chart' ? 'on' : '') + '" aria-label="图表视图" style="padding:0 6px">' + ic('chart', 14) + '</button><button type="button" data-act="view" data-v="table" class="' + (S.view === 'table' ? 'on' : '') + '" aria-label="表格视图" style="padding:0 6px">' + ic('grid', 14) + '</button></div></div>' +
    '<div class="vz" data-vz="ov-trend"></div><div class="row ov-brush" id="ovBrush" hidden><span class="cap" id="ovBrushTxt"></span><button type="button" class="lnk" data-act="ovBrushClear">清除刷选</button></div><div class="cap ov-foot" title="图例只影响本图：点击隐藏，⌥ 点击只看；在图上拖选一段时间，上方指标卡按该范围重算">点击图例隐藏 · 拖选时段重算指标卡</div></div>' +
    // 活跃节律：固定格宽、消息数 / 纠偏率切换、数值图例（评审 A1-V11）
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">活跃节律</span><span class="cap">周 × 小时</span></div><div class="seg" role="group" aria-label="热力图度量"><button type="button" data-act="heatMode" data-v="msgs" class="' + (S.ov.heat === 'msgs' ? 'on' : '') + '">消息数</button><button type="button" data-act="heatMode" data-v="corr" class="' + (S.ov.heat === 'corr' ? 'on' : '') + '">纠偏率</button></div></div>' +
    '<div class="ov-heat-line"><b>' + heatLine + '</b>' + (S.ov.heat === 'msgs' ? '<button type="button" class="lnk" data-act="heatCell" data-h="' + peak[1] + '" data-d="' + peak[0] + '">证据 →</button>' : '') + '</div>' +
    '<div class="scroll-x"><div class="vz ov-heat" data-vz="ov-heat"></div></div><div class="cap ov-foot" title="筛选只按小时，不分星期">点击格子查看该小时开始的会话</div></div>' +
    // 工具 Top 6：浅灰 6px 条 + 错误率微型条（评审 A1-V13）
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">工具调用 Top 6</span>' + (busy ? '<span class="cap">' + busyShort(busy) + '</span>' : '<span class="cap">' + fmt(st.tools) + ' 次</span>') + '</div>' + (busy ? '' : '<button type="button" class="lnk" data-act="go" data-r="tools">全部 ' + tkinds + ' 种</button>') + '</div><div class="ov-tools">' + (pendTxt ? LV.pend(180) : LV.live && !OVL ? LV.na() : LV.live && !trows.length ? LV.na('这段时间没有工具调用') : '') + trows.map((t) => '<button type="button" class="ov-tool" data-act="openTool" data-t="' + t.name + '"><span class="mono nm">' + t.name + '</span><span class="bar"><span style="width:' + (t.n / tmx * 100).toFixed(1) + '%"></span></span><span class="mono n">' + fmt(t.n) + '</span><span class="ov-err">' + terr(t) + '</span></button>').join('') + '</div><div class="cap ov-foot" title="错误率条的刻度为 0–20%">右列为错误率 · 超过 10% 标红</div></div>' +
    ovRecsCard(topR) +
    '</div></div></div>';
};
// 图表挂载：趋势（堆叠 / 分组 / 100%）、结果构成、人格双向条、节律热力图
PAGES.overview.after = () => {
  const L = sel(); const ser = CUR.trend || []; const pers = personaNow();
  const last = ser.length - 1; const weeklyB = ser.length > 31;
  const days = last >= 0 ? ser[last].b - ser[last].a + 1 : 0; const partial = weeklyB && days < 7;
  const pct = S.ov.stack === 'pct';
  const totals = ser.map((b) => b.v.reduce((x, v) => x + v, 0));
  const unit = S.metric === 'n' ? ' 个会话' : S.metric === 'h' ? ' h' : 'M';
  const fmtV = (v) => S.metric === 'n' ? fmt(v) : f1(v);
  const series0 = AG.map((a, j) => ({ name: a.name, color: a.c, values: ser.map((b, i) => pct ? (totals[i] ? b.v[j] / totals[i] * 100 : null) : b.v[j]), total: fmtV(sum(ser, (b) => b.v[j])) + (S.metric === 'n' ? '' : unit) }));
  // 周末底纹：相邻的周六 / 周日合并成一段（只有日桶时）
  const bands = []; if (!weeklyB) ser.forEach((b, i) => { if (wd(b.a) >= 5) { const prev = bands[bands.length - 1]; if (prev && prev.to === i - 1 && wd(b.a) === 6) prev.to = i; else bands.push({ from: i, to: i, label: bands.length ? '' : '周末' }); } });
  const vis = AG.map((a) => !S.ov.hidden.includes(a.name));
  const full = ser.slice(0, partial ? last : ser.length).map((b) => b.v.reduce((x, v, j) => x + (vis[j] ? v : 0), 0));
  const avg = full.length ? full.reduce((a, b) => a + b, 0) / full.length : 0;
  const avgEl = $('[data-ovavg]'); if (avgEl) avgEl.textContent = pct || !avg ? '' : ' · 虚线 ' + (weeklyB ? '周均 ' : '日均 ') + fmtV(avg);
  VZ.mount('ov-trend', {
    type: 'bar', title: 'Agent 使用趋势', height: 190, stacked: !(S.ov.stack === 'grouped'), view: S.view, hidden: S.ov.hidden, animate: false,
    x: { values: ser.map((b) => b.lbl) }, series: series0,
    y: { format: pct ? (v) => Math.round(v) + '%' : S.metric === 'tok' ? (v) => (v ? v + 'M' : '0') : S.metric === 'h' ? '1f' : 'int', max: pct ? 100 : undefined, label: pct ? '占比' : S.metric === 'h' ? '小时' : S.metric === 'tok' ? '百万 tokens' : '会话' },
    bands, refs: pct || !avg ? [] : [{ y: avg }],
    hatch: partial ? [last] : [], notes: partial ? [{ i: last, text: '本周进行中（' + days + '/7 天）' }] : [],
    brush: true,
    onLegend: (name, on, o) => { S.ov.hidden = o.hidden; },
    onBrush: (r) => ACT.ovBrushed(r),
    onSelect: (i) => { const b = ser[i]; if (!b) return; toast((b.a === b.b ? md(b.a) : md(b.a) + ' – ' + md(b.b)) + ' · ' + fmtV(b.v.reduce((x, v, j) => x + (vis[j] ? v : 0), 0)) + unit); }
  });
  const st = stats(L);
  const H = CUR.heat; if (!H) return;
  const corr = S.ov.heat === 'corr';
  const values = corr ? H.H.map((r, i) => r.map((v, h) => (v ? H.C[i][h] / v * 100 : null))) : H.H;
  const mx = Math.max(1, ...values.flat().filter((v) => v != null));
  VZ.mount('ov-heat', {
    type: 'heatmap', title: '活跃节律 · ' + (corr ? '纠偏率' : '消息数'), rows: WD, cols: Array.from({ length: 24 }, (_, h) => h % 6 ? '' : String(h)), values, ramp: corr ? 'corr' : 'accent', cellMax: 13, gap: 2, peak: !corr, min: 0, animate: false,
    format: corr ? 'pct' : 'int', unit: corr ? '纠偏率' : '条消息', scaleLabels: ['0', (corr ? f1(mx) + '%' : fmt(mx) + ' 条')], scaleNote: corr ? '灰格：该时段没有消息' : null,
    tipHead: (r, c) => '周' + WD[r] + ' ' + c + ':00–' + (c + 1) + ':00', tipExtra: (r, c) => { const v = H.H[r][c], k = H.C[r][c]; return corr ? VZ.tipRow('var(--ink-4)', '消息', fmt(v) + ' 条 · 纠偏 ' + k + ' 次', { kind: 'rect' }) : VZ.tipRow(VZ.sem.corr, '纠偏', k + ' 次' + (v ? '（' + f1(k / v * 100) + '%）' : ''), { kind: 'rect' }); },
    onSelect: (i, d) => ACT.heatCell({ dataset: { h: String(d.c), d: String(d.r) } })
  });
};
TIPS.heat = (di, h) => { const v = CUR.heat.H[di][h], c = CUR.heat.C[di][h]; return '<b>周' + WD[di] + ' ' + h + ':00–' + (+h + 1) + ':00</b>\n' + v + ' 条消息 · 纠偏 ' + c + ' 次' + (v ? '（' + f1(c / v * 100) + '%）' : ''); };
// 「本周建议」card (also appended to the live overview by 97-live-recs.js)
function ovRecsCard(topR) {
  return '<div class="card pad ov-recs"><div class="hd"><div class="grow"><span class="ct">本周建议</span></div>' + (dataBusy() ? '' : '<button type="button" class="lnk" data-act="go" data-r="recs">全部 ' + visibleRecs().length + ' 条</button>') + '</div><div class="ov-recl">' + (topR.length ? topR.map((r) => '<div class="ov-rec"><span class="ov-reci">' + ic(r.icon) + '</span><div class="ov-rect"><button type="button" class="ov-recb" data-act="openRec" data-id="' + r.id + '"><span class="ov-recn" title="' + esc(r.title) + '">' + esc(r.title) + '</span><span class="ov-recm"><span class="mono">' + r.type + '</span> · ' + esc(recGain(r)) + ' · L' + r.lvl + '</span></button>' + recPrimaryBtn(r, true) + '</div></div>').join('') : '<div class="cap" data-rec-none="' + recNone().k + '">' + esc(recNone().k === 'done' ? '建议都已处理，下周再看看。' : recNone().t) + '</div>') + '</div></div>';
}
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
  stackMode: (el) => { S.ov.stack = el.dataset.v; render(); },
  heatMode: (el) => { S.ov.heat = el.dataset.v; render(); },
  // 刷选：指标卡按刷选的桶范围重算（不整页重绘，保留刷选框）；清除后恢复整段
  ovBrushed: (r) => {
    const ser = CUR.trend || []; const box = $('#ovBrush'); const tiles = $('#ovTiles'); if (!tiles) return;
    if (!r || !ser.length) { S.ov.brush = null; if (box) box.hidden = true; const pw = prevWin(S.range); tiles.innerHTML = ovTiles(sel(), pw ? stats(sel({ win: pw })) : null); return; }
    const a = Math.min(r[0], r[1]), b = Math.max(r[0], r[1]); S.ov.brush = [a, b];
    const sub = sel({ win: [ser[a].a, ser[b].b] });
    tiles.innerHTML = ovTiles(sub, null, true);
    if (box) { box.hidden = false; $('#ovBrushTxt').textContent = '已刷选 ' + md(ser[a].a) + ' – ' + md(ser[b].b) + ' · ' + sub.length + ' 个会话，指标卡已按该范围重算'; }
  },
  ovBrushClear: () => { const el = $('[data-vz="ov-trend"]'); const inst = el && VZ._inst.get(el); if (inst) { inst.brushRange = null; const r = el.querySelector('.vz-brush'); if (r) r.setAttribute('hidden', ''); } ACT.ovBrushed(null); },
  heatCell: (el) => { const h = +el.dataset.h; const d = el.dataset.d; S.hour = h; go('sessions'); toast('已筛选 ' + h + ':00–' + (h + 1) + ':00 开始的会话' + (d != null ? '（按小时，不分星期：周' + WD[+d] + '的格子只决定小时）' : '')); },
  openTool: (el) => { S.tools.open = el.dataset.t; go('tools'); },
  evGood: () => { S.outcome = 'ok'; go('sessions'); },
  evBad: () => { const fr = Object.entries(countBy(sel(), 'fric')).sort((a, b) => b[1] - a[1]); if (fr[0]) S.fric = fr[0][0]; go('sessions'); },
  evRec: () => go('recs'),
  regen: () => {
    const p = personaNow(); const el = $('#aiLead'); if (!el) return;
    const lv = LV.live && LV.ov && LV.ov.insight && LV.ov.insight.lede;
    const variants = lv ? [lv] : p.ok ? ['你像一位' + p.zh + '：' + p.line, '一句话：你把大块目标交给 Agent，并且很在意结果是否真的可用。', '你的协作重心在「交出去」和「收回来」两端：委托得多，验收也严。'] : ['所选范围还没有会话，暂时无法给出协作画像。'];
    const txt = variants[Math.floor(Math.random() * variants.length)];
    if (OV_T) clearInterval(OV_T);   // 连点只保留最后一次（BUG-66）
    el.textContent = ''; const g0 = $('[data-aigen]'); if (g0) g0.innerHTML = '<span class="spin" style="width:10px;height:10px;vertical-align:-1px"></span> ' + (LV.live ? '本地生成中…' : '本地 Claude Code 生成中…');
    const key = S.range + '|' + (p.ok ? p.code : '-') + '|' + Array.from(S.agents).join(',');
    let i = 0; OV_T = setInterval(() => { i += 2; el.textContent = txt.slice(0, i); if (i >= txt.length) { clearInterval(OV_T); OV_T = null; S.ov.lede = { key, txt }; const g = $('[data-aigen]'); if (g) g.textContent = LV.live ? '规则模板 · 本地生成 · 刚刚' : '本地 Claude Code 生成 · 刚刚'; } }, 30);
  },
  reindex: () => reindex(),
  report: () => openReport(),
  ovMore: (el) => openDD(el, [{ t: '分享报告', v: () => openReport() }, { t: '问本地 Agent', v: () => openAsk('overview') }, { sep: 1 }, { t: '重新索引', k: '⌘R', v: () => reindex() }, { t: '键盘快捷键', k: '?', v: () => openKeys() }], (v) => v())
});
let OV_IDX = null;
function reindex() {
  if (OV_IDX) return;   // 正在索引时不重复启动
  const s = $('[data-sync]'); if (s) s.innerHTML = '<span class="spin" style="width:11px;height:11px;vertical-align:-1px"></span> 正在索引…';
  const c = $('#content'); if (c) c.classList.add('stale');
  if (LV.live) {   // live: reload the spine (ETag → 304 when nothing changed) and report the real count
    OV_IDX = true;
    Promise.resolve(LV.loadSpine()).then(() => { OV_IDX = null; S.ov.synced = '刚刚已同步'; const c2 = $('#content'); if (c2) c2.classList.remove('stale'); const s2 = $('[data-sync]'); if (s2) s2.textContent = S.ov.synced; toast(LV.state === 'error' ? '刷新失败，稍后重试' : '索引完成：' + fmt(ALL.length) + ' 个会话均已是最新'); });
    return;
  }
  OV_IDX = setTimeout(() => { OV_IDX = null; S.ov.synced = '刚刚已同步'; const c2 = $('#content'); if (c2) c2.classList.remove('stale'); const s2 = $('[data-sync]'); if (s2) s2.textContent = S.ov.synced; toast('索引完成：新增 0 个会话，2,416 个会话均已是最新'); }, 1200);
}
