/* ============ live A4 tools + A5 projects (slice 3) ============
   Live mode only: the polished A4 / A5 pages render the same cards, classes and animations as the prototype, with every
   number taken from the local service instead of 05-data:
   - A4 ← GET /v1/uiview/tools (header, kpis, table, matrix, retries, failures, approval, mcp, parallel, automation).
     TRANS_NAMES / TRANS / FAILS / WAITS / RETRIES / PAR are refilled in place in their existing shapes; toolRows() returns
     the server rows (TOOLS itself stays untouched because A3 still reads its Bash commands). A row's recent calls come from
     GET /v1/analytics/tool_calls (LRU, one request per tool and filter).
   - A5 ← GET /v1/uiview/projects (rows, scatter, folders), GET /v1/uiview/projects/{id} (vs, agents, workflows, coverage,
     rule files, top recommendation, persona) and GET /v1/features/linked (configured item names in the coverage tips).
     The project objects in PJ get their flow / cover / tags / git / tip / rec filled from the detail.
   The backend ignores the UI-only filters (topic / outcome / friction / hour, gap G3): both pages say so in a scope note.
   Missing routes or errors render an honest empty state; personal data never falls back to demo rows. */
const LVTP = { tools: null, projects: null, det: null, calls: null, linked: null };
const LVTP_NODE = { read: 'Read', search: 'Search', edit: 'Edit', shell: 'Shell', subagent: 'Task', web: 'Web', other: 'Other' };
const LVTP_COV = { rule: '规则文件', hook: 'Hooks', skill: 'Skills', mcp: 'MCP', subagent: '子代理' };
const LVTP_HALF = { '<5s': '5 s', '5–15s': '15 s', '15–30s': '30 s', '30–60s': '1 分钟', '1–2m': '2 分钟', '2–5m': '5 分钟', '>5m': '5 分钟以上' };
// start of the first day of the range window, as local-midnight epoch ms (null = all time)
function lvtpFrom(range) {
  if (!range) return null;
  const x = new Date(DAY0 + win(range)[0] * 86400000);
  return new Date(x.getUTCFullYear(), x.getUTCMonth(), x.getUTCDate()).getTime();
}
// G3: the page endpoints only take range / agent / project; say which active filters are not applied
function lvtpScopeNote() {
  const x = [];
  if (S.topic) x.push('主题'); if (S.outcome) x.push('结果'); if (S.fric) x.push('摩擦'); if (S.hour != null) x.push('时段');
  return x.length ? '<div class="cap" data-lv="scope-note" style="margin:-4px 0 10px">' + ic('alert', 12, 'vertical-align:-2px;color:var(--ink-3)') + ' 本页按时间与 Agent 统计，' + x.join(' / ') + '筛选暂不计入</div>' : '';
}
const lvtpMs = (ms) => ms == null ? '—' : ms < 10000 ? f1(ms / 1000) + ' s' : ms < 600000 ? Math.round(ms / 1000) + ' s' : f1(ms / 60000) + ' m';
const lvtpPct = (v) => v == null ? '—' : f1(v * 100) + '%';
const lvtpTrend = (k, mul) => (k && k.trend ? k.trend.map((t) => t.value == null ? null : t.value * (mul || 1)) : null);
const lvtpHours = (h) => h == null ? 0 : typeof h === 'object' ? (h.value || 0) : h;
const lvtpAgent = (bid) => AGI[LV.agentOf(bid).id] || null;
// B11: each agent names the same tool differently (Bash / bash / exec_command / terminal / Shell); the server rows carry the
// unified kind from the tool-name map (/v1/app/tool_map), so the table shows one row per kind like the prototype.
// MCP tools merge per server (mcp·<server>); a kind outside the map keeps its raw name.
const LVTP_KIND = { shell: 'Bash', 'file.read': 'Read', 'file.edit': 'Edit', 'file.write': 'Write', search: 'Grep', 'web.search': 'WebSearch', 'web.fetch': 'WebFetch', subagent: 'Task', skill: 'Skill', plan: 'TodoWrite', ask_user: 'AskUser' };
function lvtpUnified(t) {
  if (t.kind === 'mcp' && t.mcp_server) return { name: 'mcp·' + t.mcp_server, q: { mcp_server: t.mcp_server } };
  if (LVTP_KIND[t.kind]) return { name: LVTP_KIND[t.kind], q: { kind: t.kind } };
  return { name: t.name, q: { name: t.name } };
}
// B12: workflow steps arrive as raw tool names + command heads; chips show a human label (bold) over the unified tool or
// command (mono), like the prototype's 「只读审查 / Read ×24」. Kind comes from the tools feed when loaded, else the static
// alias list below (mirrors /v1/app/tool_map 1.2.x).
const LVTP_ALIAS = {};
[['shell', 'bash exec_command terminal shell commandexecution exec pwsh'], ['file.read', 'read read_file view_image'], ['file.edit', 'edit apply_patch multiedit str_replace_editor filechange'],
  ['file.write', 'write write_file'], ['search', 'grep glob find search'], ['web.search', 'websearch web_search web.search'], ['web.fetch', 'webfetch web_fetch web.fetch'],
  ['subagent', 'task agent subagent spawn_agent delegate_task'], ['skill', 'skill'], ['plan', 'todowrite todo_write update_plan'], ['ask_user', 'askuserquestion ask_user_question request_user_input']
].forEach(([k, names]) => names.split(' ').forEach((n) => { LVTP_ALIAS[n] = k; }));
const LVTP_STEP = { 'file.read': '读取文件', 'file.edit': '修改文件', 'file.write': '写入文件', search: '搜索代码', 'web.search': '网页搜索', 'web.fetch': '抓取网页', subagent: '派发子代理', skill: '调用技能', plan: '更新计划', ask_user: '向你提问', mcp: 'MCP 工具', shell: '运行命令' };
const LVTP_HEAD = [[/^(cat|head|tail|less|more|sed|bat|wc)\b/, '查看文件'], [/^(ls|tree|find|fd|pwd)\b/, '浏览目录'], [/^(rg|grep|ag|ack)\b/, '搜索代码'],
  [/^(pytest|jest|vitest|mocha|tox)\b|^(npm|pnpm|yarn|bun) (run )?test\b|^(go|cargo) test\b/, '运行测试'], [/^git (diff|status|log|show)\b/, '查看改动'], [/^git\b|^gh\b/, 'Git 操作'],
  [/^(npm|pnpm|yarn|bun|make|cargo|go|tsc|latexmk)\b/, '构建'], [/^(python3?|node|deno|ruby|bash|sh|uv)\b/, '运行脚本'], [/^(curl|wget|http)\b/, '请求接口'], [/^(mkdir|cp|mv|rm|touch|chmod|ln)\b/, '整理文件']];
function lvtpKindOf(name) {
  const k = String(name || '').toLowerCase();
  const t = LVTP.tools && (LVTP.tools.tools || []).find((x) => String(x.name || '').toLowerCase() === k);
  if (t && t.kind) return t.kind;
  if (/^mcp__/.test(k)) return 'mcp';
  return LVTP_ALIAS[k] || null;
}
function lvtpStep(s) {
  const kind = lvtpKindOf(s.name); const head = s.head ? String(s.head) : '';
  const tool = kind === 'mcp' ? String(s.name).replace(/^mcp__([^_]+)__/, '$1.') : (LVTP_KIND[kind] || s.name);
  if (head) { const m = LVTP_HEAD.find((x) => x[0].test(head)); return [m ? m[1] : (LVTP_STEP[kind] || '运行命令'), head]; }
  return [LVTP_STEP[kind] || String(s.name), tool];
}
function lvtpMerge(list) {
  const by = {}; const out = [];
  (list || []).forEach((t) => {
    const u = lvtpUnified(t); let g = by[u.name];
    if (!g) { g = by[u.name] = { name: u.name, q: u.q, kind: t.kind, mcp: t.mcp_server, n: 0, failed: 0, known: 0, ap: 0, p50: [0, 0], p95: [0, 0], daily: [], aliases: [] }; out.push(g); }
    const n = t.n || 0;
    g.n += n; g.failed += t.failed || 0; g.known += t.known != null ? t.known : n; g.ap += (t.approval_rate || 0) * n;
    if (t.p50_ms != null) { g.p50[0] += t.p50_ms * n; g.p50[1] += n; }
    if (t.p95_ms != null) { g.p95[0] += t.p95_ms * n; g.p95[1] += n; }
    (t.daily || []).forEach((v, i) => { g.daily[i] = (g.daily[i] || 0) + (v || 0); });
    if (g.aliases.indexOf(t.name) < 0) g.aliases.push(t.name);
  });
  return out.map((g) => {
    const p50 = g.p50[1] ? g.p50[0] / g.p50[1] : null, p95 = g.p95[1] ? g.p95[0] / g.p95[1] : null;
    return { name: g.name, n: g.n, err: g.known ? g.failed / g.known : 0, fails: g.failed, avg: lvtpMs(p50), ap: g.n ? g.ap / g.n : 0, cmds: [],
      p50: p50 != null ? p50 / 1000 : 0, p95: p95 != null ? p95 / 1000 : 0, daily: g.daily, kind: g.kind, mcp: g.mcp, q: g.q, aliases: g.aliases };
  }).sort((a, c) => c.n - a.n);
}

if (LV.live) (function () {
  LVTP.det = LV.lru(30); LVTP.calls = LV.lru(30); LVTP.linked = LV.lru(30);

  /* ---------- A4 feed: the response refills the page constants in place ---------- */
  LV.feed('tools', (sc) => [{ name: 't', path: LV.withQuery('/v1/uiview/tools', { display_timezone: sc.tz, from_ts: lvtpFrom(sc.range), agent: sc.agents, project_ids: sc.project }) }], (d) => {
    const b = d.t || {};
    LVTP.tools = b;
    const m = b.matrix || { nodes: [], prob: [], counts: [], row_n: [] };
    TRANS_NAMES.length = 0; (m.nodes || []).forEach((n) => TRANS_NAMES.push(LVTP_NODE[n] || n));
    TRANS.length = 0; (m.prob || []).forEach((r) => TRANS.push(r.slice()));
    FAILS.length = 0; ((b.failures && b.failures.rows) || []).forEach((f) => FAILS.push([f.label || f.key, Math.round((f.share || 0) * 100), f.typical || '—', f.n || 0, f.session_uids || []]));
    WAITS.length = 0; ((b.approval && b.approval.histogram) || []).forEach((w) => WAITS.push([w.bucket, w.n || 0]));
    RETRIES.length = 0; (b.retries || []).forEach((r) => RETRIES.push([r.command, r.count || 0, r.max_run || 0, r.session_uids || []]));
    PAR.length = 0; ((b.parallel && b.parallel.buckets) || []).forEach((p) => PAR.push([p.degree, p.n || 0, p.n ? (p.stopped || 0) / p.n : 0]));
  });
  // server rows in the toolRows() shape (+ p50 / p95 seconds, the daily series and kind), merged by unified tool (B11)
  // until /v1/uiview/tools answered, keep the previous derivation (A1's tools card indexes trows[0]; slice 1 owns it)
  const toolRows0 = toolRows;
  toolRows = function (L) {
    const b = LVTP.tools; if (!b || !b.tools) return toolRows0(L);
    return lvtpMerge(b.tools);
  };
  TIPS.trans = (i, j) => { const m = (LVTP.tools && LVTP.tools.matrix) || {}; const c = m.counts && m.counts[+i] ? m.counts[+i][+j] : null; return '<b>' + esc(TRANS_NAMES[+i] + ' → ' + TRANS_NAMES[+j]) + '</b>\n条件概率 ' + Math.round((TRANS[+i] ? TRANS[+i][+j] : 0) * 100) + '%' + (+i === +j ? '（同一工具连用）' : '') + (c != null ? '\n' + fmt(c) + ' 次转移' : ''); };

  /* ---------- A5 feed ---------- */
  LV.feed('projects', (sc) => [{ name: 'p', path: LV.withQuery('/v1/uiview/projects', { agent: sc.agents, since: lvtpFrom(sc.range), group: S.proj.group === 'folder' ? 'folder' : null }) }], (d) => { LVTP.projects = d.p || {}; });
  TIPS.split = (id) => { const r = lvtpRows().find((x) => x.p.id === id); if (!r) return ''; const tot = r.split.reduce((a, b) => a + b, 0) || 1; return '<b>' + esc(r.p.name) + ' · Agent 构成</b>\n' + r.split.map((v, j) => v ? '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + AG[j].c + ';margin-right:5px;vertical-align:-1px"></span>' + esc(AG[j].name) + ' <b class="mono">' + v + '</b> · ' + Math.round(v / tot * 100) + '%' : '').filter(Boolean).join('\n'); };
  const reveal = (path, what) => { if (!path || path === '—') { toast('没有记录' + what + '路径'); return; } ORBIT.native.request('reveal', { path }).then((r) => { if (r && r.ok === false) toast('无法在 Finder 中显示：' + path); }, () => toast('无法在 Finder 中显示：' + path)); };
  Object.assign(ACT, {
    finder: () => { const p = PJI[S.proj.sel]; reveal(p && p.path, '项目'); },
    openAgents: () => { const p = PJI[S.proj.sel]; const f = p && p.ruleFiles && p.ruleFiles[0]; reveal(f && f.path, '规则文件'); },
    lvtpMore: () => { const t = S.tools.open; if (!t) return; S.tools.callsN = (S.tools.callsN || 6) + 10; render(); }
  });
})();

/* ---------- A4 page ---------- */
function lvtpCalls(name) {
  const n = S.tools.callsN || 6; const st = S.tools.failOnly ? 'failed' : 'all';
  const row = (LVTP.tools && LVTP.tools.tools ? toolRows() : []).find((r) => r.name === name); const q = (row && row.q) || { name };
  const path = LV.withQuery('/v1/analytics/tool_calls', Object.assign({}, q, { status: st, limit: n, display_timezone: TL_TZ, from_ts: lvtpFrom(S.range) }));
  return LV.detail(LVTP.calls, path, path);
}
function lvtpCallRows(name) {
  const e = lvtpCalls(name);
  if (e.state === 'pending') return LV.pend(64);
  if (e.state === 'error') return '<div class="cap" data-lv="na" style="padding:4px 0">本地服务暂不提供调用明细</div>';
  const items = (e.data && e.data.items) || [];
  if (!items.length) return '<div class="cap" data-lv="na" style="padding:4px 0">所选范围内没有' + (S.tools.failOnly ? '失败的' : '') + '调用</div>';
  const OK = { success: 1, completed: 1, ok: 1 }, BAD = { failed: 1, error: 1 };
  return items.map((c) => {
    const d = c.started_at != null ? new Date(c.started_at) : null; const fail = BAD[c.status]; const ok = OK[c.status];
    const cmd = c.command_head ? (c.args_summary && c.args_summary.indexOf(c.command_head) === 0 ? c.args_summary : c.command_head) : (c.args_summary || (c.files || []).join(' ') || c.name);
    return '<div class="row mono tt-call"><span style="color:var(--ink-3)">' + (d ? (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hm(d.getHours(), d.getMinutes()) : '—') + '</span><span class="tt-cmd">' + esc(cmd || '—') + '</span><span style="color:' + (fail ? 'var(--crit)' : ok ? 'var(--good)' : 'var(--ink-3)') + ';min-width:38px">' + (fail ? (c.exit_code != null ? 'exit ' + c.exit_code : '失败') : ok ? 'ok' : '未知') + '</span><span style="color:var(--ink-3);min-width:46px;text-align:right">' + (c.duration_ms == null ? '—' : c.duration_ms < 10000 ? f1(c.duration_ms / 1000) + ' s' : Math.round(c.duration_ms / 1000) + ' s') + '</span>' + (BYID[c.session_uid] ? '<button type="button" class="lnk" data-act="openSession" data-id="' + esc(c.session_uid) + '" style="font-family:var(--sans)">在轨迹中查看 →</button>' : '') + '</div>';
  }).join('') + (e.data && e.data.has_more ? '<div class="row" style="justify-content:flex-start"><button type="button" class="lnk" data-act="lvtpMore" style="font-family:var(--sans)">更多调用 →</button></div>' : '');
}
function lvToolsPage() {
  const T = S.tools; const fs = LV.feedState('tools'); const b = LVTP.tools;
  const actions = '<button type="button" class="btn" data-act="csv">' + ic('down', 14) + '导出 CSV</button><button type="button" class="btn ai" data-act="ask" data-ctx="tools">' + ic('spark', 14) + '找出可自动化的操作</button>';
  const chip = '<button type="button" class="chip' + (T.failOnly ? ' on' : '') + '" data-act="failOnly" aria-pressed="' + !!T.failOnly + '">' + ic('alert', 13) + '仅看失败</button>';
  const head = (meta) => tbar('工具调用', meta, actions) + '<div class="content" id="content">' + filterRow(chip) + lvtpScopeNote();
  if (fs === 'error' && !b) return head('—') + empty('本地服务暂不提供工具统计') + '</div>';
  if (!b) return head('正在读取…') + '<div class="stack" data-lv="pending"><div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))">' + [0, 1, 2, 3].map(() => '<div class="card tile">' + LV.pend(64) + '</div>').join('') + '</div><div class="card pad">' + LV.pend(260) + '</div></div></div>';
  const H = b.header || {}; const K = b.kpis || {};
  if (!H.calls) return head('0 次调用') + empty(b.meta && b.meta.freshness === 'none' ? '还没有导入会话，工具统计会在导入后出现' : '所选范围内没有工具调用') + '</div>';
  const all = toolRows(); let rows = all.slice();
  if (T.failOnly) rows = rows.filter((r) => r.fails > 0);
  const key = T.failOnly && T.sort === 'n' ? 'fails' : T.sort;
  const num = (r) => key === 'avg' ? r.p50 : r[key];
  rows.sort((a, c) => (key === 'name' ? a.name.localeCompare(c.name) : num(a) - num(c)) * T.dir);
  const mxn = Math.max(1, ...rows.map((r) => T.failOnly ? r.fails : r.n));
  const mxDur = Math.max(0.001, ...all.map((r) => r.p95));
  const rangeN = S.range || 0;
  const spark = (r) => { let raw = (r.daily || []).slice(); if (rangeN && raw.length > rangeN) raw = raw.slice(-rangeN); if (raw.length <= 7) return raw; return raw.map((v, i) => { const a = Math.max(0, i - 6); let t = 0; for (let k = a; k <= i; k++) t += raw[k]; return Math.round(t / (i - a + 1) * 10) / 10; }); };
  const th = (k, lbl, align) => '<th' + (align ? ' style="text-align:' + align + '"' : '') + '><button type="button" data-act="sortTools" data-k="' + k + '" aria-sort="' + (T.sort === k ? (T.dir < 0 ? 'descending' : 'ascending') : 'none') + '">' + lbl + (T.sort === k ? (T.dir < 0 ? ' ↓' : ' ↑') : '') + '</button></th>';
  const tbody = rows.map((r) => {
    const open = T.open === r.name; const v = T.failOnly ? r.fails : r.n;
    let h = '<tr class="click' + (open ? ' sel' : '') + '" data-act="toggleTool" data-t="' + esc(r.name) + '" aria-expanded="' + open + '"><td class="mono tt-name"' + (r.aliases && (r.aliases.length > 1 || r.aliases[0] !== r.name) ? ' data-tip="' + esc('各 Agent 的原始工具名：' + r.aliases.join(' · ')) + '"' : '') + '>' + ic(open ? 'chev' : 'chevr', 12, 'display:inline;vertical-align:-2px;color:var(--ink-3)') + ' ' + esc(r.name) + '</td>' +
      '<td class="tt-n"><span class="row" style="gap:8px"><span class="tt-bar"><i style="width:' + (v / mxn * 100).toFixed(1) + '%"></i></span><span class="mono tt-num">' + fmt(v) + '</span></span></td>' +
      '<td class="tt-err"><span class="row" style="gap:6px;justify-content:flex-end"><span class="tt-ebar" aria-hidden="true"><i style="width:' + Math.min(100, r.err / 0.15 * 100).toFixed(0) + '%;background:' + (r.err > 0.1 ? 'var(--vz-err)' : r.err > 0.03 ? 'var(--ink-3)' : 'var(--ink-4)') + '"></i></span><span class="mono" style="min-width:44px;text-align:right;color:' + (r.err > 0.1 ? 'var(--crit)' : 'var(--ink-2)') + ';font-weight:' + (r.err > 0.1 ? 600 : 400) + '">' + f1(r.err * 100) + '%</span></span></td>' +
      '<td class="tt-dur"><span class="row" style="gap:6px;justify-content:flex-end"><span class="tt-dbar" data-tip="p50 ' + f1(r.p50) + ' s · p95 ' + f1(r.p95) + ' s" aria-hidden="true"><i class="p95" style="width:' + (Math.sqrt(r.p95 / mxDur) * 100).toFixed(1) + '%"></i><i class="p50" style="width:' + (Math.sqrt(r.p50 / mxDur) * 100).toFixed(1) + '%"></i></span><span class="mono" style="min-width:40px;text-align:right">' + r.avg + '</span></span></td>' +
      '<td class="mono tt-ap" style="text-align:right">' + (r.ap ? Math.round(r.ap * 100) + '%' : '—') + '</td><td class="tt-sp">' + VZ.spark(spark(r), { w: 80, h: 22, label: r.name + '：' + rangeLabel() + '每日调用' }) + '</td></tr>';
    if (open) h += '<tr class="tt-open"><td colspan="6"><div class="col" style="gap:3px;padding:4px 0 6px" data-lv="tool-calls">' + lvtpCallRows(r.name) + '</div></td></tr>';
    return h;
  }).join('');
  // matrix (rows = previous step, cols = next step); row n from the server
  const M = b.matrix || {}; const nodes = TRANS_NAMES.length; const rowN = M.row_n || [];
  const pmx = Math.max(0.0001, ...TRANS.flat()); const lvl = (p) => clamp(Math.floor(p / pmx * 5.999), 0, 5);
  let peak = [-1, -1], pv = -1; TRANS.forEach((row, i) => row.forEach((p, j) => { if (i !== j && p > pv) { pv = p; peak = [i, j]; } }));
  const matrix = !M.pairs ? '<div class="cap" data-lv="na" style="padding:18px 0">调用链样本不足：至少需要一个会话里有两次连续的工具调用</div>' : '<div class="tm" id="tm" style="grid-template-columns:auto repeat(' + nodes + ',minmax(36px,44px)) auto" role="table" aria-label="工具调用转移概率矩阵：行是上一步，列是下一步"><span class="tm-h tm-corner" title="行 = 上一步 · 列 = 下一步">上一步 ↓</span>' + TRANS_NAMES.map((n, j) => '<span class="tm-h mono" data-c="' + j + '">' + esc(n) + '</span>').join('') + '<span class="tm-h mono" style="text-align:right">n</span>' +
    TRANS.map((row, i) => '<span class="tm-rh mono" data-r="' + i + '">' + esc(TRANS_NAMES[i]) + '</span>' + row.map((p, j) => { const l = lvl(p); return '<button type="button" class="tm-c mono' + (i === j ? ' diag' : '') + (i === peak[0] && j === peak[1] ? ' peak' : '') + '" data-r="' + i + '" data-c="' + j + '" data-tf="trans|' + i + '|' + j + '" style="background:' + VZ.rampFill(l, 'accent') + ';color:' + (l >= 4 ? 'var(--accent-ink)' : 'var(--ink-1)') + '">' + Math.round(p * 100) + '</button>'; }).join('') + '<span class="tm-n mono" data-r="' + i + '">' + VZ.fmt(rowN[i] || 0, 'k') + '</span>').join('') + '</div>' +
    '<div class="vz-scale" aria-label="色阶：条件概率 0% 到 ' + Math.round(pmx * 100) + '%"><span class="cap">0%</span>' + [0, 1, 2, 3, 4, 5].map((l) => '<i style="background:' + VZ.rampFill(l, 'accent') + '"></i>').join('') + '<span class="cap">' + Math.round(pmx * 100) + '%</span><span class="cap vz-scale-note" title="对角线 = 同一工具连用 · 行尾 n = 该工具调用数">描边 = 同一工具连用</span></div>';
  const tc = M.top_chain; const si = (M.nodes || []).indexOf('shell');
  const auto = (b.automation || []).find((a) => a.kind === 'hook') || (b.automation || [])[0];
  const ins = (tc && tc.steps && tc.steps.length ? '<span><b style="color:var(--ink-1)">最常见三步链</b> ' + tc.steps.map((s) => esc(LVTP_NODE[s] || s)).join(' → ') + '（' + (tc.probs || []).map((p) => Math.round(p * 100) + '%').join(' → ') + '）· ' + fmt(tc.support_sessions || 0) + ' 个会话</span>' : '') +
    (si >= 0 && TRANS[si] ? '<span><b style="color:var(--ink-1)">命令之后仍是命令 ' + Math.round(TRANS[si][si] * 100) + '%</b>' + (auto ? '，' + esc(auto.title) + '可覆盖 ' + fmt(auto.count || 0) + ' 次' + (auto.candidate_id ? ' → <button type="button" class="lnk" data-act="openRec" data-id="' + esc(auto.candidate_id) + '">查看建议</button>' : '') : '') + '</span>' : '');
  // approvals
  const AP = b.approval || {}; const wTot = sum(WAITS, (w) => w[1]); const halfTxt = LVTP_HALF[AP.half_bucket] || AP.half_bucket;
  const ro = AP.readonly_prompted || {};
  const cov = (b.meta && b.meta.coverage) || {}; const apWith = (cov.approval_agents_with || []).map((x) => LV.agentOf(x).short);
  const waitsBody = wTot ? '<div class="vz" data-vz="waits"></div><div class="cap tt-wait-note">' + (halfTxt ? '一半的审批在 <b style="color:var(--ink-1)">' + esc(halfTxt) + '</b> 内等到了你 · ' : '') + '共 ' + fmt(wTot) + ' 次</div>' : '<div class="cap" data-lv="na" style="padding:18px 0">' + (K.approvals && K.approvals.count ? fmt(K.approvals.count) + ' 次审批，但没有记录等待时长' : '所选范围内没有审批记录') + (apWith.length ? '（只有 ' + esc(apWith.join('、')) + ' 记录审批）' : '') + '</div>';
  const roCta = ro.n ? '<div class="row tt-cta"><span class="tt-cta-t"><b>' + fmt(ro.n) + ' 次</b> 只读命令可自动放行</span>' + (AP.candidate_id ? '<button type="button" class="btn sm p" data-act="openRec" data-id="' + esc(AP.candidate_id) + '">生成白名单 Hook</button>' : '') + '</div>' : '';
  // failures / retries / mcp / parallel
  const FT = b.failures || {}; const fmx = Math.max(1, ...FAILS.map((f) => f[1]));
  const rmx = Math.max(1, ...RETRIES.map((r) => r[1]));
  const mcp = b.mcp || []; const mcpN = H.mcp_servers || 0;
  const SA = K.subagent || {}; const pg4 = b.parallel && b.parallel.stopped_share_ge4;
  const kpis = [
    VZ.kpi({ label: T.failOnly ? '失败次数' : '工具调用', value: fmt(T.failOnly ? (K.error_rate && K.error_rate.failed) || 0 : (K.calls && K.calls.value) || 0), delta: T.failOnly ? null : { cur: (K.calls && K.calls.value) || 0, prev: K.calls ? K.calls.prev : null, fmt: 'int' }, trend: T.failOnly ? null : lvtpTrend(K.calls), trendLabel: '近 12 周', tip: K.calls && K.calls.per_session != null ? '每会话 ' + Math.round(K.calls.per_session) + ' 次 · ' + fmt(H.sessions || 0) + ' 个会话' : null }),
    VZ.kpi({ label: '错误率', value: K.error_rate && K.error_rate.value != null ? f1(K.error_rate.value * 100) : '—', unit: '%', delta: { cur: K.error_rate && K.error_rate.value != null ? Math.round(K.error_rate.value * 1000) / 10 : null, prev: K.error_rate && K.error_rate.prev != null ? Math.round(K.error_rate.prev * 1000) / 10 : null, unit: 'pt', goodDown: true, fmt: (v) => f1(v) + '%' }, trend: lvtpTrend(K.error_rate, 100), trendLabel: '近 12 周', tip: K.error_rate ? fmt(K.error_rate.failed || 0) + ' 次失败' + (K.error_rate.shell_share != null ? ' · 命令占 ' + Math.round(K.error_rate.shell_share * 100) + '%' : '') + (K.error_rate.unknown ? ' · ' + fmt(K.error_rate.unknown) + ' 次状态未知' : '') : null }),
    VZ.kpi({ label: '需要你审批', value: fmt((K.approvals && K.approvals.count) || 0), delta: { cur: (K.approvals && K.approvals.count) || 0, prev: K.approvals ? K.approvals.prev : null, goodDown: true, fmt: 'int' }, trend: lvtpTrend(K.approvals), trendLabel: '近 12 周', tip: K.approvals && K.approvals.median_wait_ms != null ? '等待中位数 ' + lvtpMs(K.approvals.median_wait_ms) : '没有记录等待时长' }),
    VZ.kpi({ label: '子代理派发', value: fmt(SA.dispatches || 0), delta: { cur: SA.dispatches || 0, prev: SA.prev != null ? SA.prev : null, fmt: 'int' }, tip: SA.dispatches ? '平均 ' + lvtpMs(SA.avg_duration_ms) + ' · 最多并行 ' + (SA.max_parallel || 0) : '所选范围内没有子代理派发' })
  ].join('');
  return head(fmt(H.calls) + ' 次调用 · ' + fmt(all.length || H.tool_kinds) + ' 种工具 · ' + mcpN + ' 个 MCP 服务' + (fs === 'pending' || fs === 'computing' ? ' · 更新中' : '')) +
    '<div class="stack"><div class="tiles" style="grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr))">' + kpis + '</div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">工具明细</span><span class="cap" title="点列头排序 · 点行展开最近调用 · 迷你线为' + rangeLabel() + '每日调用' + (rangeN > 7 || !rangeN ? '（7 天滑动平均）' : '') + '">点行展开最近调用 · 列头可排序</span></div></div><div class="scroll-x"><table class="tbl tt"><thead><tr>' + th('name', '工具') + th('n', T.failOnly ? '失败次数' : '调用次数') + th('err', '错误率', 'right') + th('avg', '耗时 p50 / p95', 'right') + th('ap', '需审批', 'right') + '<th>' + rangeLabel() + '</th></tr></thead><tbody>' + (tbody || '<tr><td colspan="6" class="cap">没有失败的调用</td></tr>') + '</tbody></table></div></div>' +
    '<div class="tt-grid"><div class="card pad tt-matrix"><div class="hd"><div class="grow"><span class="ct">调用链 · 下一步是什么</span><span class="cap" title="P(下一步 | 上一步)：行 = 上一步，列 = 下一步；悬停看整行整列">格内 = 下一步的概率 %</span></div></div>' + matrix + (ins ? '<div class="col tt-ins">' + ins + '</div>' : '') +
    '<div class="hd tt-sub"><div class="grow"><span class="ct">失败后原样重试 · Top ' + Math.min(5, RETRIES.length || 5) + '</span><span class="cap" title="同一命令失败后未改参数直接重跑 · 次数与最长连跑">未改参数直接重跑</span></div></div><div class="col" style="gap:4px">' + (RETRIES.length ? RETRIES.slice(0, 5).map((r) => '<div class="tt-retry"><span class="mono tt-cmd" title="' + esc(r[0]) + '">' + esc(r[0]) + '</span><span class="tt-fail-bar"><i style="width:' + (r[1] / rmx * 100).toFixed(1) + '%"></i></span><span class="mono tt-fail-v" title="重试 ' + r[1] + ' 次 · 最长连跑 ' + r[2] + ' 次">×' + r[1] + ' · 连跑 ' + r[2] + '</span></div>').join('') : '<span class="cap" data-lv="na">没有发现失败后原样重试的命令</span>') + '</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">失败原因</span><span class="cap">' + fmt(FT.total || 0) + ' 次失败 · 按输出聚类' + (FT.unknown_status ? ' · ' + fmt(FT.unknown_status) + ' 次状态未知' : '') + '</span></div></div><div class="col" style="gap:5px">' + (FAILS.length ? FAILS.map((f) => '<button type="button" class="tt-fail' + (T.openFail === f[0] ? ' on' : '') + '" data-act="openFail" data-k="' + esc(f[0]) + '" aria-expanded="' + (T.openFail === f[0]) + '"><span class="tt-fail-n">' + esc(f[0]) + '</span><span class="tt-fail-bar"><i style="width:' + (f[1] / fmx * 100).toFixed(1) + '%"></i></span><span class="mono tt-fail-v">' + f[1] + '% · ' + fmt(f[3]) + ' 次</span></button>' + (T.openFail === f[0] ? '<div class="tt-fail-x"><span class="mono" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis">典型：' + esc(f[2]) + '</span>' + (f[4] && f[4].some((u) => BYID[u]) ? '<button type="button" class="btn sm" data-act="openSession" data-id="' + esc(f[4].find((u) => BYID[u])) + '">相关会话 →</button>' : '') + '</div>' : '')).join('') : '<span class="cap" data-lv="na">所选范围内没有失败的调用</span>') + '</div></div>' +
    '<div class="card pad col" style="gap:0"><div class="hd" style="margin-bottom:4px"><div class="grow"><span class="ct">审批负担</span><span class="cap">等你点「允许」的时间 · 对数分桶</span></div></div>' + waitsBody + roCta + '</div>' +
    '<div class="card pad tt-mcp"><div class="col" style="gap:8px"><div class="hd" style="margin:0"><div class="grow"><span class="ct">MCP 服务</span><span class="cap">' + mcpN + ' 个' + (cov.inventory === 'available' ? '已连接' : '在用（配置未扫描）') + '</span></div></div>' + (mcp.length ? mcp.map((x) => '<div class="row" style="font-size:12px"><span class="mono" style="width:92px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(x.server) + '">mcp·' + esc(x.server) + '</span><span style="flex:1;color:var(--ink-2)">' + fmt(x.calls || 0) + ' 次 · 失败 ' + lvtpPct(x.err) + (x.resident_tokens ? ' · 常驻 ≈ ' + VZ.fmt(x.resident_tokens, 'k') + ' tokens' : '') + '</span>' + (x.calls ? '<span class="tag">在用</span>' : '<span class="tag">未调用</span>') + '</div>').join('') : '<span class="cap" data-lv="na">所选范围内没有 MCP 调用</span>') + '<div class="cap tt-mcp-note">工具描述每会话常驻上下文，没被调用的服务只消耗 tokens</div></div><div class="col" style="gap:6px"><div class="hd" style="margin:0"><div class="grow"><span class="ct">子代理派发 · 按并行度</span><span class="cap">共 ' + fmt(SA.dispatches || 0) + ' 次' + (b.parallel && b.parallel.max ? ' · 最多并行 ' + b.parallel.max + ' 个' : '') + '</span></div></div>' + (SA.dispatches ? '<div class="vz" data-vz="par"></div><div class="row tt-par-note">' + ic('alert', 13, 'margin-top:1px;color:var(--vz-corr)') + (pg4 && pg4.value != null ? '并行 ≥ 4 的派发有 <b style="color:var(--ink-1)">' + Math.round(pg4.value * 100) + '%</b> 被你中途停止（' + pg4.n + ' 次）' : '并行 ≥ 4 的派发样本不足') + '</div>' : '<span class="cap" data-lv="na">所选范围内没有子代理派发</span>') + '</div></div></div></div></div>';
}

/* ---------- A5 page ---------- */
// server project rows merged with the spine's session lists (xs, for the session ids of this scope)
function lvtpRows() {
  const P = LVTP.projects; if (!P || !P.projects) return [];
  return P.projects.filter((r) => (r.sessions || 0) > 0).map((r) => {
    const p = PJI[r.project_id] || { id: r.project_id, name: r.name, path: r.path || '—', tags: [], flow: [], cover: [], fric: {}, live: true };
    p.name = r.name || p.name; if (r.path) p.path = r.path; p.tags = r.tags || p.tags || []; if (r.git) p.git = r.git;
    const split = AG.map((a) => sum((r.agents || []).filter((x) => LV.agentOf(x.agent).id === a.id), (x) => x.sessions || 0));
    const per = r.persona || {}; const t = per.code && TYPES[per.code];
    const fr = r.friction || {};
    return { p, xs: ALL.filter((s) => s.p === r.project_id), raw: r, split,
      st: { n: r.sessions || 0, hours: lvtpHours(r.hours), fric: fr.value != null ? fr.value * 100 : 0, fricLo: fr.lo, fricHi: fr.hi, auto: r.tools_per_human_message || 0 },
      pers: per.code ? { ok: true, code: per.code, zh: t ? t[0] : '尚未定型', status: per.status } : { ok: false, code: null, status: per.status || 'insufficient', reason: per.reason } };
  }).sort((a, c) => c.st.hours - a.st.hours || c.st.n - a.st.n);
}
function lvtpDetail(id, cmp) {
  const sc = LV.scope();
  const path = LV.withQuery('/v1/uiview/projects/' + encodeURIComponent(id), { agent: sc.agents, since: lvtpFrom(sc.range), compare: cmp || null });
  return LV.detail(LVTP.det, path, path);
}
function lvtpLinked(id) { const path = LV.withQuery('/v1/features/linked', { project_id: id }); return LV.detail(LVTP.linked, path, path); }
const LVTP_VS = { avg_session_minutes: ['平均会话时长', (v) => Math.round(v) + 'm', 'pct', null], messages_per_session: ['每会话消息', (v) => f1(v), 'pct', null], autonomy: ['自主比', (v) => Math.round(v * 100) + '%', 'pt100', null], verify_rate: ['要求验证', (v) => Math.round(v * 100) + '%', 'pt100', false], friction_rate: ['摩擦率', (v) => f1(v * 100) + '%', 'pt100', true], daily_sessions: ['日均会话', (v) => f1(v), 'pct', null] };
function lvProjectsPage() {
  const fs = LV.feedState('projects'); const P = LVTP.projects;
  const actions = '<button type="button" class="btn' + (S.proj.cmpMode ? ' p' : '') + '" data-act="projCompare">' + (S.proj.cmpMode ? '退出对比' : '对比两个项目') + '</button><button type="button" class="btn ai" data-act="projRule">' + ic('spark', 14) + '为此项目起草规则</button>';
  const seg = '<span class="cap">聚合</span><div class="seg" role="group" aria-label="聚合方式"><button type="button" data-act="projGroup" data-v="project" class="' + (S.proj.group === 'project' ? 'on' : '') + '">按项目</button><button type="button" data-act="projGroup" data-v="folder" class="' + (S.proj.group === 'folder' ? 'on' : '') + '">按文件夹</button></div>';
  if (!P) {
    if (fs === 'error') return tbar('项目习惯', '') + '<div class="content" id="content">' + filterRow() + empty(ALL.length ? '本地服务暂不提供项目统计' : '还没有导入会话，项目会在导入后出现') + '</div>';
    return tbar('项目习惯', '正在读取…', actions) + '<div class="content" id="content">' + filterRow(seg) + '<div class="pj" data-lv="pending"><div class="stack"><div class="card pad">' + LV.pend(220) + '</div><div class="card pad">' + LV.pend(260) + '</div></div><div class="stack"><div class="card pad">' + LV.pend(90) + '</div><div class="card pad">' + LV.pend(200) + '</div></div></div></div>';
  }
  const rows = lvtpRows();
  if (S.project && rows.some((r) => r.p.id === S.project)) S.proj.sel = S.project;
  if (S.proj.cmp && S.proj.cmp === S.proj.sel) S.proj.cmp = null;
  const selRow = rows.find((r) => r.p.id === S.proj.sel) || rows[0];
  if (!selRow) return tbar('项目习惯', '') + '<div class="content" id="content">' + filterRow() + lvtpScopeNote() + empty('所选范围内没有会话') + '</div>';
  S.proj.sel = selRow.p.id;
  const p = selRow.p; const st = selRow.st;
  const cmpRow = S.proj.cmp ? rows.find((r) => r.p.id === S.proj.cmp) : null;
  const cmpName = cmpRow ? cmpRow.p.name : '整体';
  const hoursAll = sum(rows, (r) => r.st.hours);
  const pts = rows.filter((r) => r.st.n >= 3).map((r) => ({ x: Math.round(r.st.auto * 10) / 10, y: Math.round(r.st.fric * 10) / 10, r: r.st.hours, id: r.p.id, label: r.p.name, meta: r.st.n + ' 个会话', color: r.p.id === p.id ? 'var(--ink-1)' : (cmpRow && r.p.id === cmpRow.p.id) ? 'var(--surface)' : 'var(--h2)' }));
  CUR.pjPts = pts;
  const byId = {}; rows.forEach((r) => { byId[r.p.id] = r; });
  const tableRows = S.proj.group === 'folder'
    ? (P.folders || []).filter((f) => byId[f.belongs_to]).map((f) => ({ r: byId[f.belongs_to], f: f.cwd || '（未记录目录）', n: f.sessions || 0, h: lvtpHours(f.hours) }))
    : rows.map((r) => ({ r, f: null, n: r.st.n, h: r.st.hours }));
  const fricMax = Math.max(1, ...rows.map((r) => r.st.fric));
  // detail (vs / agents / workflows / coverage / rule files / top rec / persona)
  const D = lvtpDetail(p.id, cmpRow ? cmpRow.p.id : null); const d = D.state === 'ready' ? D.data || {} : null;
  const Lk = lvtpLinked(p.id); const linked = Lk.state === 'ready' && Lk.data ? Lk.data.items || [] : [];
  const hd = (d && d.header) || {};
  if (d) {
    const w0 = (d.workflows || [])[0];
    p.flow = w0 ? w0.steps.map(lvtpStep) : [];
    p.cover = (d.coverage || []).map((c) => [LVTP_COV[c.type] || c.type, c.configured == null ? '—' : String(c.project != null ? c.project : (c.configured ? 1 : 0)), c.detail || '', c.configured ? 1 : 0, c]);
    p.git = hd.git || '—'; p.tags = hd.tags || p.tags; p.ruleFiles = hd.rule_files || [];
    p.rec = d.top_recommendation ? d.top_recommendation.candidate_id : null; p.tip = d.top_recommendation ? d.top_recommendation.title : '';
  }
  const pp = hd.persona && hd.persona.code ? { ok: true, code: hd.persona.code, zh: (TYPES[hd.persona.code] || ['尚未定型'])[0] } : selRow.pers;
  const now = personaNow();
  const plineTxt = pp.ok ? '在这个项目里你是 <b class="mono" style="color:var(--ink-1);letter-spacing:.04em">' + esc(pp.code) + '</b> <b style="color:var(--ink-1)">' + esc(pp.zh) + '</b>' + (now && now.ok ? (now.code !== pp.code ? '，和整体（' + esc(now.code + ' ' + now.zh) + '）不同' : '，和整体一致') : '') + '。'
    : (pp.status === 'persona_pending' ? (fs === 'computing' || LV.state === 'computing' || LV.state === 'connecting' ? '这个项目的人格还在计算，导入完成后会出现。' : '本地服务还没有给出这个项目的人格，表格里先记为「—」。') : '这个项目的样本还不够，暂不判断人格。');
  const vsRows = d ? ((d.vs && d.vs.metrics) || []).map((m) => {
    const f = LVTP_VS[m.key] || [m.label || m.key, (v) => f1(v), 'pct', null];
    const a = m.a == null ? 0 : m.a, bb = m.b == null ? 0 : m.b; const mx = Math.max(a, bb) || 1;
    const dd = f[2] === 'pt100' ? VZ.delta2({ cur: a * 100, prev: bb * 100, unit: 'pt', goodDown: f[3], prevText: false }) : VZ.delta2({ cur: a, prev: bb, goodDown: f[3], prevText: false });
    const flat = m.flat != null ? m.flat : (bb ? Math.abs(a - bb) / Math.abs(bb) < 0.1 : true);
    return '<div class="pj-vs"><span class="pj-vs-n">' + esc(f[0]) + '</span><span class="col" style="gap:2px"><span class="pj-vs-b a" style="width:' + (a / mx * 100) + '%"></span><span class="pj-vs-b" style="width:' + (bb / mx * 100) + '%"></span></span><span class="mono pj-vs-v"><b>' + (m.a == null ? '—' : f[1](a)) + '</b> / ' + (m.b == null ? '—' : f[1](bb)) + '</span><span class="mono pj-vs-d ' + (flat ? 'flat' : dd.cls) + '"' + (m.lo != null ? ' data-tip="95% 区间 ' + esc(f1(m.lo) + ' ~ ' + f1(m.hi)) + (flat ? ' · 区间跨 0，记为 ≈' : '') + '"' : '') + '>' + (flat ? '≈' : dd.text) + '</span></div>';
  }).join('') : '';
  const agSrc = (d && d.agents) || selRow.raw.agents || [];
  const agRows = agSrc.map((x) => { const a = lvtpAgent(x.agent); return a ? { a, n: x.sessions || 0, h: x.hours || 0, ok: x.n ? (x.accepted || 0) / x.n * 100 : null, tn: x.n || 0 } : null; }).filter(Boolean);
  const agMaxN = Math.max(1, ...agRows.map((r) => r.n)), agMaxH = Math.max(0.1, ...agRows.map((r) => r.h));
  const split = selRow.split; const splitTot = split.reduce((a, b) => a + b, 0) || 1;
  const agents = AG.filter((a, j) => split[j] > 0);
  const w0 = d && (d.workflows || [])[0];
  const itemNames = (type) => linked.filter((i) => i.type === type && (!i.project_id || i.project_id === p.id)).map((i) => i.name || i.title || i.key || i.item_id).filter(Boolean).slice(0, 3);
  const covCell = (c, a) => { const x = c[4] || {}; const sup = (x.agents_read || []).some((k) => LV.agentOf(k).id === a.id); const on = sup && x.configured; const unk = x.configured == null; const names = itemNames(x.type); return '<span class="pj-cov-c' + (on ? ' on' : sup ? ' off' : ' na') + '" data-tip="' + esc(a.name + ' · ' + c[0] + '：' + (on ? '已配置（' + (names.length ? names.join('、') : c[2]) + '）' : sup ? (unk ? '未扫描' : '未配置 · ' + c[2]) : '该 Agent 不读取此类配置')) + '" role="img" aria-label="' + esc(a.short + ' ' + c[0] + (on ? ' 已配置' : sup ? (unk ? ' 未扫描' : ' 未配置') : ' 不适用')) + '"></span>'; };
  const ruleFiles = p.ruleFiles || [];
  const pend = (h) => LV.pend(h);
  return tbar('项目习惯', rows.length + ' 个项目 · ' + f1(hoursAll) + ' 小时 · 按协作时长排序' + (fs === 'pending' || fs === 'computing' ? ' · 更新中' : ''), actions) +
    '<div class="content" id="content">' + filterRow(seg) + lvtpScopeNote() +
    '<div class="pj"><div class="stack"><div class="card pad"><table class="tbl pj-tbl"><colgroup><col><col class="pj-c-n"><col class="pj-c-h"><col class="pj-c-f"><col class="pj-c-s"><col class="pj-c-p"></colgroup><thead><tr><th>' + (S.proj.group === 'folder' ? '文件夹' : '项目') + '</th><th style="text-align:right">会话</th><th style="text-align:right">时长</th><th>摩擦率</th><th>Agent 构成</th><th style="text-align:right">此处人格</th></tr></thead><tbody>' +
    (tableRows.length ? tableRows.map((t) => { const r = t.r; const on = r.p.id === p.id, on2 = cmpRow && r.p.id === cmpRow.p.id; const tot2 = r.split.reduce((a, b) => a + b, 0) || 1; const pc = r.pers.ok ? r.pers.code : '—'; return '<tr class="click' + (on || on2 ? ' sel' : '') + '" data-act="pickProject" data-p="' + esc(r.p.id) + '" aria-selected="' + !!on + '"><td class="pj-name"><div class="pj-title">' + esc(t.f || r.p.name) + ((S.proj.cmpMode && on) || on2 ? ' <span class="bdg">' + (on ? 'A' : 'B') + '</span>' : '') + '</div><div class="mono cap pj-path">' + esc(t.f ? '归入 ' + r.p.name : r.p.path) + '</div></td><td class="mono" style="text-align:right" data-count="' + t.n + '" data-ck="pj-n:' + esc(r.p.id) + ':' + esc(t.f || '') + '">' + t.n + '</td><td class="mono" style="text-align:right" data-count="' + f1(t.h) + '" data-ck="pj-h:' + esc(r.p.id) + ':' + esc(t.f || '') + '">' + f1(t.h) + 'h</td><td><span class="row pj-fric"' + (r.st.fricLo != null ? ' data-tip="95% 区间 ' + f1(r.st.fricLo * 100) + '% ~ ' + f1(r.st.fricHi * 100) + '%"' : '') + '><span class="pj-bar"><i style="width:' + (r.st.fric / fricMax * 100).toFixed(1) + '%"></i></span><span class="mono">' + f1(r.st.fric) + '%</span></span></td><td><div class="pj-split" data-tf="split|' + esc(r.p.id) + '" tabindex="0">' + r.split.map((v, j) => v ? '<span style="width:' + (v / tot2 * 100) + '%;background:' + AG[j].c + '"></span>' : '').join('') + '</div></td><td class="mono pj-pers" style="font-weight:' + (r.pers.ok ? 700 : 500) + ';color:' + (r.pers.ok ? 'var(--ink-1)' : 'var(--ink-3)') + '">' + pc + '</td></tr>'; }).join('') : '<tr><td colspan="6" class="cap" data-lv="na">' + (fs === 'pending' || fs === 'computing' ? LV.pend(60) : S.proj.group === 'folder' ? '本地服务没有返回文件夹明细' : '暂无数据') + '</td></tr>') +
    '</tbody></table><div class="cap pj-foot" data-tip="时长 = 会话时间段的并集（含空闲）；摩擦率 = 纠偏候选消息 / 你的消息">' + (S.proj.group === 'folder' ? '子文件夹按会话归入所属项目 · ' : '') + '「—」人格尚未计算或样本不足</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">跨项目对比</span><span class="cap">' + (S.proj.cmpMode ? '点另一个项目作为 B' : '面积 = 时长 · 竖线 = 到回归线的残差') + '</span></div><span class="row cap pj-rleg" data-tip="琥珀 = 摩擦率高于同等自主度的预期；绿 = 低于"><span class="row" style="gap:4px"><i style="background:' + VZ.sem.corr + '"></i>高于预期</span><span class="row" style="gap:4px"><i style="background:' + VZ.sem.good + '"></i>低于预期</span></span></div><div class="vz" data-vz="pj-scatter"></div><div class="cap pj-foot">' + (pts.length >= 3 ? '高于回归线的项目最值得先加护栏' : '项目太少，无法拟合') + '</div></div></div>' +
    '<div class="stack"><div class="card pad"><div class="row" style="gap:12px;flex-wrap:wrap"><span style="width:36px;height:36px;border-radius:9px;background:var(--sunken);display:grid;place-items:center">' + ic('projects', 18) + '</span><div style="flex:1;min-width:200px"><div class="row" style="align-items:baseline;gap:10px;flex-wrap:wrap"><h2 class="serif" style="margin:0;font-size:22px">' + esc(p.name) + '</h2><span class="mono cap">' + esc(p.path) + ' · git: ' + esc(p.git || '—') + '</span></div><div class="row" style="gap:6px;margin-top:4px;flex-wrap:wrap">' + (p.tags || []).map((t) => '<span class="tag">' + esc(t) + '</span>').join('') + '</div></div><button type="button" class="btn" data-act="finder">在 Finder 中显示</button>' + (ruleFiles.length ? '<button type="button" class="btn" data-act="openAgents" data-tip="' + esc(ruleFiles[0].path) + '">显示 ' + esc(String(ruleFiles[0].path).split('/').pop()) + '</button>' : '') + '</div>' +
    '<div class="row pj-pline">' + ic('persona', 14) + '<span>' + plineTxt + '</span></div></div>' +
    '<div class="pj-two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">此项目 vs ' + esc(cmpName) + '</span></div><span class="row cap" style="font-size:11px;gap:10px"><span class="row" style="gap:4px"><span class="pj-key" style="background:var(--ink-1)"></span>' + esc(p.name) + '</span><span class="row" style="gap:4px"><span class="pj-key" style="background:var(--ink-4)"></span>' + esc(cmpName) + '</span></span></div><div class="col" style="gap:8px">' + (d ? vsRows || LV.na() : D.state === 'error' ? LV.na('本地服务暂不提供项目对比') : pend(150)) + '</div>' + (S.proj.cmpMode && !cmpRow ? '<div class="cap pj-foot">在表格或散点图里点另一个项目作为 B</div>' : '<div class="cap pj-foot" data-tip="只有摩擦率与要求验证按好坏着色">Δ 相对 ' + esc(cmpName) + ' · 95% 区间跨 0 记为 ≈</div>') + '</div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">Agent 分工</span><span class="cap">' + st.n + ' 个会话 · 条宽 = 会话占比</span></div></div><div class="pj-share">' + split.map((v, j) => v ? '<span style="width:' + (v / splitTot * 100) + '%;background:' + AG[j].c + '" data-tip="' + esc(AG[j].name) + '：' + v + ' 个会话 · ' + Math.round(v / splitTot * 100) + '%"></span>' : '').join('') + '</div><div class="col" style="gap:8px;margin-top:10px">' + agRows.map((r) => '<div class="pj-ag"><span class="row" style="gap:6px;font-size:12px;min-width:0"><span class="pj-dot" style="background:' + r.a.c + '"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(r.a.short) + '</span></span><span class="col" style="gap:3px"><span class="pj-ag-r"><span class="cap">会话</span><span class="pj-bar"><i style="width:' + (r.n / agMaxN * 100).toFixed(0) + '%;background:' + r.a.c + '"></i></span><span class="mono">' + r.n + '</span></span><span class="pj-ag-r"><span class="cap">时长</span><span class="pj-bar"><i style="width:' + (r.h / agMaxH * 100).toFixed(0) + '%;background:' + r.a.c + '"></i></span><span class="mono">' + f1(r.h) + 'h</span></span><span class="pj-ag-r" data-tip="有结果的 ' + r.tn + ' 个任务里被你直接采纳的占比"><span class="cap">采纳</span><span class="pj-bar"><i style="width:' + (r.ok == null ? 0 : r.ok).toFixed(0) + '%;background:var(--ink-3)"></i></span><span class="mono">' + (r.ok == null ? '—' : Math.round(r.ok) + '%') + '</span></span></span></div>').join('') + '</div></div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">识别到的工作流</span><span class="cap">' + (w0 ? '出现在 ' + w0.support_sessions + ' / ' + w0.eligible_sessions + ' 个会话 · 支持度 ' + Math.round((w0.support_rate || 0) * 100) + '%' : '同一三步链在多个会话出现才算') + '</span></div></div>' + (d ? (p.flow.length ? '<div class="row" style="flex-wrap:wrap;gap:8px">' + p.flow.map((f, i) => '<span class="col pj-step"><b>' + esc(f[0]) + '</b><span class="mono cap">' + esc(f[1]) + '</span></span>' + (i < p.flow.length - 1 ? ic('arrow', 14, 'color:var(--ink-4)') : '')).join('') + '</div><div class="row" style="margin-top:10px;flex-wrap:wrap"><span class="pj-note">固定成一个 Skill 后，这段流程不必每次重新交代。</span><button type="button" class="btn sm ai" data-act="flowToStudio">' + ic('spark', 12) + '封装为 Skill</button></div>' : LV.na('还没有识别到重复出现的工作流')) : D.state === 'error' ? LV.na() : pend(60)) + '</div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">规则与配置覆盖</span><span class="cap" data-tip="来自本机配置扫描（规则文件、Hooks、Skills、MCP）">列 = 此项目用到的 Agent</span></div></div>' + (d ? '<div class="pj-cov" style="grid-template-columns:auto repeat(' + agents.length + ',24px) minmax(0,1fr)" role="table" aria-label="规则与配置覆盖矩阵"><span></span>' + agents.map((a) => '<span class="pj-cov-h" title="' + esc(a.name) + '"><span class="pj-dot" style="background:' + a.c + '"></span></span>').join('') + '<span></span>' + p.cover.map((c) => '<span class="pj-cov-r">' + esc(c[0]) + '</span>' + agents.map((a) => covCell(c, a)).join('') + '<span class="pj-cov-v"><b class="mono">' + esc(c[1]) + '</b><span class="cap">' + esc(c[2]) + '</span></span>').join('') + '</div><div class="row cap pj-foot" style="gap:12px;flex-wrap:wrap"><span class="row" style="gap:4px"><span class="pj-cov-c on"></span>已配置</span><span class="row" style="gap:4px"><span class="pj-cov-c off"></span>未配置 / 未扫描</span><span class="row" style="gap:4px"><span class="pj-cov-c na"></span>该 Agent 不读取</span></div>' +
      (ruleFiles.length ? '<div class="col" style="gap:3px;margin-top:8px" data-lv="rule-files">' + ruleFiles.map((f) => '<div class="row cap mono" style="font-size:11.5px;gap:8px"><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(f.path) + '">' + esc(f.path) + '</span><span>' + f1((f.bytes || 0) / 1024) + ' KB · ' + (f.lines || 0) + ' 行</span></div>').join('') + '</div>' : '') +
      '<div class="row" style="margin-top:10px;padding:7px 10px;border-radius:8px;background:var(--sunken);flex-wrap:wrap">' + ic('bolt', 15, 'color:var(--ai)') + (p.rec ? '<span class="pj-note">建议：' + esc(p.tip) + '</span><button type="button" class="btn sm" data-act="openRec" data-id="' + esc(p.rec) + '">查看建议</button>' : '<span class="pj-note">暂时没有针对这个项目的建议</span>') + '</div>'
      : D.state === 'error' ? LV.na() : pend(140)) + '</div></div></div></div>';
}
