/* ============ A4 tools ============
 * 明细表：真实日序列迷你线（会话当天工具数 × 该工具份额，7 天滑动平均）、错误率微型条、p50 / p95 两段耗时条、展开行可跳到会话；
 * 调用链：HTML grid + accent 单色序列 + 行 n + 对角线描边 + 悬停高亮整行整列；失败原因带绝对次数与「相关会话」；
 * 审批直方图每柱标值 + 累计读数；子代理并行度改 1 / 2 / 3 / 4+ 桶，柱内「完成 / 中途停止」两色堆叠（评审 §3.4）。 */
S.tools = S.tools || {}; S.tools.sort = S.tools.sort || 'n';
// 某工具在时间范围内的日序列：每天的工具调用 × 该工具份额；范围超过 7 天时做 7 天滑动平均，让迷你线读得出趋势而不是噪声（评审 A4-V02）
function toolDaily(L, share, range) {
  const w = win(range); const by = {}; L.forEach((s) => { by[s.d] = (by[s.d] || 0) + s.tools * share; });
  const raw = []; for (let d = w[0]; d <= w[1]; d++) raw.push(by[d] || 0);
  if (raw.length <= 7) return raw.map((v) => Math.round(v));
  return raw.map((v, i) => { const a = Math.max(0, i - 6); let t = 0; for (let k = a; k <= i; k++) t += raw[k]; return Math.round(t / (i - a + 1) * 10) / 10; });
}
const TOOL_SHARE = {}; TOOLS.forEach((t) => { TOOL_SHARE[t[0]] = t[1] / 9860; });
// F24: MCP 服务卡（Demo 与 live 共用）：服务名完整显示（可换行，不截断），有调用的服务可展开看其下每个工具的次数与失败率。
// servers: [{ server, calls, err (null = 不计算), errWhy, extra, tag, tagHtml, removed, tools: [{ name, n, err, errWhy }] }]
function ttMcpList(servers) {
  const T = S.tools; const pct = (v) => v == null ? '—' : f1(v * 100) + '%';
  return servers.map((x) => {
    const k = 'mcp·' + x.server; const can = !x.removed && x.calls > 0 && x.tools && x.tools.length; const open = can && T.mcpOpen === x.server;
    const rate = x.calls ? ' · 失败 ' + (x.err == null ? '<span data-tip="' + esc(x.errWhy || '状态未知，不计算错误率') + '">—</span>' : pct(x.err)) : '';
    const name = '<span class="mono tt-mcp-n' + (x.removed ? ' off' : '') + '">' + esc(k) + '</span>';
    const stats = '<span class="tt-mcp-v">' + (x.removed ? '已移除 · 可在资源库重装' : fmt(x.calls || 0) + ' 次' + rate + (x.extra || '')) + '</span>';
    const head = can ? '<button type="button" class="tt-mcp-h" data-act="toggleMcp" data-k="' + esc(x.server) + '" aria-expanded="' + open + '">' + ic(open ? 'chev' : 'chevr', 12, 'flex:none;color:var(--ink-3)') + name + stats + '</button>'
      : '<div class="tt-mcp-h">' + '<span class="tt-mcp-sp" aria-hidden="true"></span>' + name + stats + '</div>';
    let h = '<div class="tt-mcp-s" data-mcp="' + esc(x.server) + '">' + head + (x.tagHtml || (x.tag ? '<span class="tag">' + x.tag + '</span>' : '')) + '</div>';
    if (open) {
      const mx = Math.max(1, ...x.tools.map((t) => t.n || 0));
      h += '<div class="tt-mcp-tools" data-lv="mcp-tools">' + x.tools.map((t) => '<div class="tt-mcp-t"><span class="mono tt-mcp-tn">' + esc(t.name) + '</span><span class="tt-fail-bar"><i style="width:' + ((t.n || 0) / mx * 100).toFixed(1) + '%"></i></span><span class="mono tt-mcp-tv">' + fmt(t.n || 0) + ' 次 · 失败 ' + (t.err == null ? '<span data-tip="' + esc(t.errWhy || '状态未知，不计算错误率') + '">—</span>' : pct(t.err)) + '</span></div>').join('') + '</div>';
    }
    return h;
  }).join('');
}
// Demo：mcp·browser 下各工具的份额与失败率（示例数据）；总数随筛选跟着明细表那一行走
const MCP_DEMO_TOOLS = { browser: [['screenshot', 0.5, 0.06], ['navigate', 0.34, 0.09], ['click', 0.16, 0.1]] };
function ttDemoMcpTools(server, n) {
  const spec = MCP_DEMO_TOOLS[server] || []; let left = n;
  return spec.map((t, i) => { const c = i === spec.length - 1 ? left : Math.round(n * t[1]); left -= c; const f = Math.round(c * t[2]); return { name: t[0], n: c, fails: f, err: c ? f / c : null }; }).filter((t) => t.n > 0);
}
PAGES.tools = () => {
  if (LV.live) return lvToolsPage();   // live: same cards from /v1/uiview/tools (93-live-tools-projects.js)
  const L = sel(); const st = stats(L);
  const pw = prevWin(S.range); const P = pw ? stats(sel({ win: pw })) : null;
  const T = S.tools; S.tools.figma = !S.installed.has('remove-figma');   // 问本地 Agent 的回答与页头一致（BUG-21）
  const all = toolRows(L); let rows = all.slice();
  if (T.failOnly) rows = rows.filter((r) => r.fails > 0);
  const key = T.failOnly && T.sort === 'n' ? 'fails' : T.sort;
  const num = (r) => key === 'avg' ? parseFloat(r.avg) : r[key];
  rows.sort((a, b) => (key === 'name' ? a.name.localeCompare(b.name) : num(a) - num(b)) * T.dir);   // 名称按字符串排（BUG-20）
  const mxn = Math.max(1, ...rows.map((r) => T.failOnly ? r.fails : r.n));
  const p95 = (r) => parseFloat(r.avg) * (2.2 + (hash(r.name) & 7) / 10), p50 = (r) => parseFloat(r.avg) * 0.72;
  const mxDur = Math.max(1, ...all.map(p95));
  const approvalsOf = (rs) => Math.round(sum(rs, (r) => r.n * r.ap));
  const approvals = approvalsOf(all), approvalsPrev = P ? approvalsOf(toolRows(sel({ win: pw }))) : null;
  const task = all.find((r) => r.name === 'Task'), taskPrev = P ? toolRows(sel({ win: pw })).find((r) => r.name === 'Task') : null;
  const endDay = win(S.range)[1]; const rangeN = win(S.range)[1] - win(S.range)[0] + 1;
  const trendLbl = '近 12 周';
  const recent = L.slice().sort((a, b) => (b.d - a.d) || (b.h - a.h)).filter((s) => s.tools > 0);
  const th = (k, lbl, align) => '<th' + (align ? ' style="text-align:' + align + '"' : '') + '><button type="button" data-act="sortTools" data-k="' + k + '" aria-sort="' + (T.sort === k ? (T.dir < 0 ? 'descending' : 'ascending') : 'none') + '">' + lbl + (T.sort === k ? (T.dir < 0 ? ' ↓' : ' ↑') : '') + '</button></th>';
  const tbody = rows.map((r) => {
    const open = T.open === r.name; const rr = rng(hash(r.name + st.n));
    const sp = toolDaily(L, TOOL_SHARE[r.name], S.range);
    const v = T.failOnly ? r.fails : r.n;
    let h = '<tr class="click' + (open ? ' sel' : '') + '" data-act="toggleTool" data-t="' + r.name + '" aria-expanded="' + open + '"><td class="mono tt-name">' + ic(open ? 'chev' : 'chevr', 12, 'display:inline;vertical-align:-2px;color:var(--ink-3)') + ' ' + r.name + '</td>' +
      '<td class="tt-n"><span class="row" style="gap:8px"><span class="tt-bar"><i style="width:' + (v / mxn * 100).toFixed(1) + '%"></i></span><span class="mono tt-num">' + fmt(v) + '</span></span></td>' +
      '<td class="tt-err"><span class="row" style="gap:6px;justify-content:flex-end"><span class="tt-ebar" aria-hidden="true"><i style="width:' + Math.min(100, r.err / 0.15 * 100).toFixed(0) + '%;background:' + (r.err > 0.1 ? 'var(--vz-err)' : r.err > 0.03 ? 'var(--ink-3)' : 'var(--ink-4)') + '"></i></span><span class="mono" style="min-width:44px;text-align:right;color:' + (r.err > 0.1 ? 'var(--crit)' : 'var(--ink-2)') + ';font-weight:' + (r.err > 0.1 ? 600 : 400) + '">' + f1(r.err * 100) + '%</span></span></td>' +
      '<td class="tt-dur"><span class="row" style="gap:6px;justify-content:flex-end"><span class="tt-dbar" data-tip="p50 ' + f1(p50(r)) + ' s · p95 ' + f1(p95(r)) + ' s" aria-hidden="true"><i class="p95" style="width:' + (Math.sqrt(p95(r) / mxDur) * 100).toFixed(1) + '%"></i><i class="p50" style="width:' + (Math.sqrt(p50(r) / mxDur) * 100).toFixed(1) + '%"></i></span><span class="mono" style="min-width:40px;text-align:right">' + r.avg + '</span></span></td>' +
      '<td class="mono tt-ap" style="text-align:right">' + (r.ap ? Math.round(r.ap * 100) + '%' : '—') + '</td><td class="tt-sp">' + VZ.spark(sp, { w: 80, h: 22, label: r.name + '：' + rangeLabel() + '每日调用' }) + '</td></tr>';
    if (open) h += '<tr class="tt-open"><td colspan="6"><div class="col" style="gap:3px;padding:4px 0 6px">' + Array.from({ length: 5 }, (_, i) => { const s = recent[Math.floor(rr() * Math.min(recent.length, 12))] || recent[0]; const fail = rr() < r.err * 2.2; const dur = fail ? p95(r) * (0.6 + rr() * 0.8) : p50(r) * (0.5 + rr() * 1.4); return '<div class="row mono tt-call"><span style="color:var(--ink-3)">' + (s ? md(s.d) + ' ' + hm(s.h, Math.min(59, s.mi + i * 7)) : md(119 - i)) + '</span><span class="tt-cmd">' + esc(r.cmds[Math.floor(rr() * r.cmds.length)]) + '</span><span style="color:' + (fail ? 'var(--crit)' : 'var(--good)') + ';min-width:38px">' + (fail ? 'exit ' + (1 + Math.floor(rr() * 2)) : 'ok') + '</span><span style="color:var(--ink-3);min-width:46px;text-align:right">' + (dur < 10 ? f1(dur) : Math.round(dur)) + ' s</span>' + (s ? '<button type="button" class="lnk" data-act="openSession" data-id="' + s.id + '" style="font-family:var(--font-sans)">在轨迹中查看 →</button>' : '') + '</div>'; }).join('') + '</div></td></tr>';
    return h;
  }).join('');
  // 调用链矩阵：行 = 上一步、列 = 下一步；行 n 取自明细表（Web = WebFetch + WebSearch）
  const byName = {}; all.forEach((r) => { byName[r.name] = r.n; });
  const rowN = TRANS_NAMES.map((n) => n === 'Web' ? (byName.WebFetch || 0) + (byName.WebSearch || 0) : byName[n] || 0);
  const pmx = Math.max(...TRANS.flat()); const lvl = (p) => clamp(Math.floor(p / pmx * 5.999), 0, 5);
  const matrix = '<div class="tm" id="tm" style="grid-template-columns:auto repeat(' + TRANS_NAMES.length + ',minmax(36px,44px)) auto" role="table" aria-label="工具调用转移概率矩阵：行是上一步，列是下一步"><span class="tm-h tm-corner" title="行 = 上一步 · 列 = 下一步">上一步 ↓</span>' + TRANS_NAMES.map((n, j) => '<span class="tm-h mono" data-c="' + j + '">' + n + '</span>').join('') + '<span class="tm-h mono" style="text-align:right">n</span>' +
    TRANS.map((row, i) => '<span class="tm-rh mono" data-r="' + i + '">' + TRANS_NAMES[i] + '</span>' + row.map((p, j) => { const l = lvl(p); return '<button type="button" class="tm-c mono' + (i === j ? ' diag' : '') + (i === 1 && j === 0 ? ' peak' : '') + '" data-r="' + i + '" data-c="' + j + '" data-tf="trans|' + i + '|' + j + '" style="background:' + VZ.rampFill(l, 'accent') + ';color:' + (l >= 4 ? 'var(--accent-ink)' : 'var(--ink-1)') + '">' + Math.round(p * 100) + '</button>'; }).join('') + '<span class="tm-n mono" data-r="' + i + '">' + VZ.fmt(rowN[i], 'k') + '</span>').join('') + '</div>' +
    '<div class="vz-scale" aria-label="色阶：条件概率 0% 到 ' + Math.round(pmx * 100) + '%"><span class="cap">0%</span>' + [0, 1, 2, 3, 4, 5].map((l) => '<i style="background:' + VZ.rampFill(l, 'accent') + '"></i>').join('') + '<span class="cap">' + Math.round(pmx * 100) + '%</span><span class="cap vz-scale-note" title="对角线 = 同一工具连用 · 行尾 n = 该工具调用数">描边 = 同一工具连用</span></div>';
  // 审批等待：对数分桶；累计到 50% 的桶给出「一半的审批在 X 内」
  const wTot = sum(WAITS, (w) => w[1]); let cum = 0, half = WAITS[WAITS.length - 1][0];
  for (const w of WAITS) { cum += w[1]; if (cum >= wTot / 2) { half = w[0]; break; } }
  const halfTxt = ({ '<5s': '5 s', '5–15s': '15 s', '15–30s': '30 s', '30–60s': '1 分钟', '1–2m': '2 分钟', '2–5m': '5 分钟', '>5m': '5 分钟以上' })[half] || half;
  const fails = FAILS.map((f) => [f[0], f[1], Math.round(st.errors * f[1] / 100), f[2]]); const fmx = Math.max(1, ...fails.map((f) => f[1]));
  const mcpN = S.installed.has('remove-figma') ? 1 : 2;
  const br = all.find((r) => r.name === 'mcp·browser'); const brTools = br ? ttDemoMcpTools('browser', br.n) : []; const brFails = sum(brTools, (t) => t.fails);
  const mcpDemo = [{ server: 'browser', calls: br ? br.n : 0, err: br && br.n ? brFails / br.n : null, tools: brTools, tag: '在用' },
    S.installed.has('remove-figma') ? { server: 'figma', removed: true } : { server: 'figma', calls: 0, extra: ' · 常驻 ≈ 2.1k tokens', tools: [], tagHtml: '<button type="button" class="btn sm" data-act="install" data-id="remove-figma">移除</button>' }];
  const retries = RETRIES.map((r) => [r[0], Math.max(1, Math.round(r[1] * st.errors / 614)), r[2]]);
  const kpis = [
    VZ.kpi({ label: T.failOnly ? '失败次数' : '工具调用', value: fmt(T.failOnly ? st.errors : st.tools), delta: { cur: T.failOnly ? st.errors : st.tools, prev: P ? (T.failOnly ? P.errors : P.tools) : null, goodDown: T.failOnly ? true : null, fmt: 'int' }, trend: weekly((x) => sum(x, (s) => T.failOnly ? s.errors : s.tools), endDay, 12), trendLabel: trendLbl, tip: '每会话 ' + Math.round(st.tools / Math.max(1, st.n)) + ' 次' }),
    VZ.kpi({ label: '错误率', value: f1(st.err), unit: '%', delta: { cur: Math.round(st.err * 10) / 10, prev: P ? Math.round(P.err * 10) / 10 : null, unit: 'pt', goodDown: true, fmt: (v) => f1(v) + '%' }, trend: weekly((x) => stats(x).err, endDay, 12), trendLabel: trendLbl, tip: fmt(st.errors) + ' 次失败 · 命令占 77%（示例）' }),
    VZ.kpi({ label: '需要你审批', value: fmt(approvals), delta: { cur: approvals, prev: approvalsPrev, goodDown: true, fmt: 'int' }, trend: weekly((x) => approvalsOf(toolRows(x)), endDay, 12), trendLabel: trendLbl, tip: '平均等待 38 s · 约 ' + Math.round(approvals * 38 / 3600) + ' 小时被打断（示例）' }),
    VZ.kpi({ label: '子代理派发', value: fmt(task ? task.n : 0), delta: { cur: task ? task.n : 0, prev: taskPrev ? taskPrev.n : null, fmt: 'int' }, trend: weekly((x) => { const t = toolRows(x).find((r) => r.name === 'Task'); return t ? t.n : 0; }, endDay, 12), trendLabel: trendLbl, tip: '平均 96 s · 最多并行 9（示例）' })
  ].join('');
  return tbar('工具调用', fmt(st.tools) + ' 次调用 · ' + TOOLS.length + ' 种工具 · ' + mcpN + ' 个 MCP 服务', '<button type="button" class="btn ai" data-act="ask" data-ctx="tools">' + ic('spark', 14) + '找出可自动化的操作</button>') +
    '<div class="content" id="content">' + filterRow('<button type="button" class="chip' + (T.failOnly ? ' on' : '') + '" data-act="failOnly" aria-pressed="' + T.failOnly + '">' + ic('alert', 13) + '仅看失败</button>') +
    '<div class="stack"><div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))">' + kpis + '</div>' +
    '<div class="tt-grid"><div class="card pad tt-matrix"><div class="hd"><div class="grow"><span class="ct">调用链 · 下一步是什么</span><span class="cap" title="P(下一步 | 上一步)：行 = 上一步，列 = 下一步；悬停看整行整列">格内 = 下一步的概率 %</span></div></div>' + matrix + '<div class="col tt-ins"><span><b style="color:var(--ink-1)">最常见三步链</b> Grep → Read → Edit（58% → 41%）</span><span><b style="color:var(--ink-1)">命令之后仍是命令 ' + Math.round(TRANS[3][3] * 100) + '%</b>，其中一半是失败后的原样重试 → <button type="button" class="lnk" data-act="openRec" data-id="retry-breaker">重复失败熔断</button></span></div>' +
    '<div class="hd tt-sub"><div class="grow"><span class="ct">失败后原样重试 · Top 5</span><span class="cap" title="同一命令失败后未改参数直接重跑 · 次数与最长连跑">未改参数直接重跑</span></div></div><div class="col" style="gap:4px">' + retries.map((r) => '<div class="tt-retry"><span class="mono tt-cmd" title="' + esc(r[0]) + '">' + esc(r[0]) + '</span><span class="tt-fail-bar"><i style="width:' + (r[1] / retries[0][1] * 100).toFixed(1) + '%"></i></span><span class="mono tt-fail-v" title="重试 ' + r[1] + ' 次 · 最长连跑 ' + r[2] + ' 次">×' + r[1] + ' · 连跑 ' + r[2] + '</span></div>').join('') + '</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">失败原因</span><span class="cap">' + fmt(st.errors) + ' 次失败 · 按输出聚类</span></div></div><div class="col" style="gap:5px">' + fails.map((f) => '<button type="button" class="tt-fail' + (T.openFail === f[0] ? ' on' : '') + '" data-act="openFail" data-k="' + esc(f[0]) + '" aria-expanded="' + (T.openFail === f[0]) + '"><span class="tt-fail-n">' + f[0] + '</span><span class="tt-fail-bar"><i style="width:' + (f[1] / fmx * 100).toFixed(1) + '%"></i></span><span class="mono tt-fail-v">' + f[1] + '% · ' + fmt(f[2]) + ' 次</span></button>' + (T.openFail === f[0] ? '<div class="tt-fail-x"><span class="mono" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">典型：' + esc(f[3]) + '</span><button type="button" class="btn sm" data-act="failSessions">相关会话 →</button></div>' : '')).join('') + '</div></div>' +
    '<div class="card pad col" style="gap:0"><div class="hd" style="margin-bottom:4px"><div class="grow"><span class="ct">审批负担</span><span class="cap">等你点「允许」的时间 · 对数分桶</span></div></div><div class="vz" data-vz="waits"></div><div class="cap tt-wait-note">一半的审批在 <b style="color:var(--ink-1)">' + halfTxt + '</b> 内等到了你 · 共 ' + fmt(wTot) + ' 次（示例）</div><div class="row tt-cta"><span class="tt-cta-t"><b>212 次</b> 只读命令可自动放行</span>' + (S.installed.has('ro-allow') ? '<span class="tag">已安装</span>' : '<button type="button" class="btn sm p" data-act="install" data-id="ro-allow">生成白名单 Hook</button>') + '</div></div>' +
    '<div class="card pad tt-mcp"><div class="col" style="gap:8px"><div class="hd" style="margin:0"><div class="grow"><span class="ct">MCP 服务</span><span class="cap">' + mcpN + ' 个已连接</span></div></div>' + ttMcpList(mcpDemo) + '<div class="cap tt-mcp-note">工具描述每会话常驻上下文，没被调用的服务只消耗 tokens</div></div><div class="col" style="gap:6px"><div class="hd" style="margin:0"><div class="grow"><span class="ct">子代理派发 · 按并行度</span><span class="cap">共 ' + fmt(task ? task.n : 0) + ' 次 · 最多并行 9 个</span></div></div><div class="vz" data-vz="par"></div><div class="row tt-par-note">' + ic('alert', 13, 'margin-top:1px;color:var(--vz-corr)') + '并行 ≥ 4 的派发有 <b style="color:var(--ink-1)">40%</b> 被你中途停止</div></div></div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">工具明细</span><span class="cap" title="点列头排序 · 点行展开最近调用 · 迷你线为' + rangeLabel() + '每日调用' + (rangeN > 7 ? '（7 天滑动平均）' : '') + '">点行展开最近调用 · 列头可排序</span></div></div><div class="scroll-x"><table class="tbl tt"><thead><tr>' + th('name', '工具') + th('n', T.failOnly ? '失败次数' : '调用次数') + th('err', '错误率', 'right') + th('avg', '耗时 p50 / p95', 'right') + th('ap', '需审批', 'right') + '<th title="每日调用' + (rangeN > 7 ? '，7 天滑动平均' : '') + '">' + rangeLabel() + '</th></tr></thead><tbody>' + (tbody || '<tr><td colspan="6" class="cap">没有失败的调用</td></tr>') + '</tbody></table></div></div>' + '</div></div>';
};
// 失败后原样重试的命令（示例数据）：[命令, 次数（按 614 次失败的基准缩放）, 最长连跑]
const RETRIES = [['wrangler deploy --env production', 37, 4], ['npm run build', 21, 3], ['pytest -q tests/', 14, 3], ['gh pr merge --merge', 9, 2], ['latexmk -pdf main.tex', 7, 2]];
// 并行度分桶（示例数据）：[派发次数, 中途停止比例]
const PAR = [['1', 210, 0.08], ['2', 28, 0.14], ['3', 16, 0.25], ['4+', 12, 0.4]];
PAGES.tools.after = () => {
  VZ.mount('waits', { type: 'bar', title: '审批等待时间分布', height: 190, x: { values: WAITS.map((w) => w[0]) }, series: [{ name: '次数', values: WAITS.map((w) => w[1]) }], labels: true, y: { format: 'int', ticks: 3 }, legend: false, desc: '对数分桶，每柱标注次数' });
  VZ.mount('par', { type: 'bar', title: '子代理派发 · 按并行度', height: 130, stacked: true, labels: true, x: { values: PAR.map((p) => p[0] + (p[0] === '1' ? ' 个' : '')) }, series: [{ name: '完成', color: 'var(--ink-3)', values: PAR.map((p) => Math.round(p[1] * (1 - p[2]))) }, { name: '中途停止', color: VZ.sem.corr, values: PAR.map((p) => Math.round(p[1] * p[2])) }], y: { format: 'int', ticks: 3 }, legend: 'bottom' });
  const tm = $('#tm'); if (!tm) return;
  const hl = (r, c) => { tm.querySelectorAll('.hl').forEach((n) => n.classList.remove('hl')); tm.classList.toggle('has-hl', r != null); if (r == null) return; tm.querySelectorAll('[data-r="' + r + '"],[data-c="' + c + '"]').forEach((n) => n.classList.add('hl')); };
  tm.addEventListener('pointerover', (e) => { const c = e.target.closest('.tm-c'); if (c) hl(c.dataset.r, c.dataset.c); });
  tm.addEventListener('focusin', (e) => { const c = e.target.closest('.tm-c'); if (c) hl(c.dataset.r, c.dataset.c); });
  tm.addEventListener('pointerleave', () => hl(null));
  tm.addEventListener('focusout', () => hl(null));
};
TIPS.trans = (i, j) => '<b>' + TRANS_NAMES[+i] + ' → ' + TRANS_NAMES[+j] + '</b>\n条件概率 ' + Math.round(TRANS[+i][+j] * 100) + '%' + (+i === +j ? '（同一工具连用）' : '') + '\n约 ' + Math.round(TRANS[+i][+j] * 1400) + ' 次转移';
Object.assign(ACT, {
  sortTools: (el) => { const k = el.dataset.k; if (S.tools.sort === k) S.tools.dir *= -1; else { S.tools.sort = k; S.tools.dir = k === 'name' ? 1 : -1; } render(); },
  toggleTool: (el) => { S.tools.open = S.tools.open === el.dataset.t ? null : el.dataset.t; render(); },
  failOnly: () => { S.tools.failOnly = !S.tools.failOnly; store.set('toolsFailOnly', S.tools.failOnly); render(); },
  toggleMcp: (el) => { S.tools.mcpOpen = S.tools.mcpOpen === el.dataset.k ? null : el.dataset.k; render(); },
  openFail: (el) => { S.tools.openFail = S.tools.openFail === el.dataset.k ? null : el.dataset.k; render(); },
  failSessions: () => { S.fric = '工具 / 环境失败'; go('sessions'); toast('已筛选出现「工具 / 环境失败」的会话'); }
});
