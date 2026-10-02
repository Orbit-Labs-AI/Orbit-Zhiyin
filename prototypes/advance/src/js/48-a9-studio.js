/* ============ A9 studio ============ */
// Built-in deterministic workflow: pack context (token stack + per-item preview with redaction) → analyse → draft (streamed)
// → self-check (spec / safety) → replay dry-run + judge → review → install (diff). A template (TPLS) only picks the step
// order; step ids are fixed, so logs, durations and check rows are looked up by id and a skipped step reads「已跳过」.
const CTX = [['sum', '相关会话摘要 · 46 个', '只含结构化统计与 AI 摘要，不含原文', 6100], ['fric', '摩擦与纠偏统计', '方向错误 17 · review 循环 11 轮 …', 1200], ['rules', '现有规则文件 · 3 份', 'AGENTS.md（全局、Hackathon、team-hub）', 3400], ['raw', '原始对话片段', '默认关闭；开启后逐条确认', 18600], ['redact', '脱敏：用户名、邮箱、密钥模式', '命中处替换为占位符', 0]];
const CTX_LIMIT = 24000;   // one generation's input budget; the stack bar turns critical above it
const CTX_HITS = { sum: 14, fric: 0, rules: 9, raw: 8 };   // redaction hits per item
// Sample lines shown in the per-item preview. {{u}} user name · {{m}} e-mail · {{k}} key · {{ip}} host — replaced by placeholders when redaction is on.
const CTX_SAMPLE = {
  sum: ['sess-0921-1412 · Confluo · 「部署到 Cloudflare Pages」 · 42 min · 纠偏 3', '  fric: 方向错误 → 「我说的是 Pages，不是 Workers」', 'sess-0918-2203 · latentskill · 「论文第 4 节重写」 · 1 h 08 · 纠偏 2', '  cwd: /Users/{{u}}/Projects/latentskill', '… 共 46 条，只含统计与摘要'],
  fric: ['方向错误 17 · 改动过度 9 · review 循环 11 轮（最长 4 轮）', '「直接合并」出现 6 次，其中 5 次 Agent 仍发起了新一轮 review', 'P2 意见占 review 评论的 71%'],
  rules: ['~/.agents/AGENTS.md · 38 行 · 维护者 {{u}}', 'Hackathon/AGENTS.md · 「合并前须通过 Codex review」', 'team-hub/AGENTS.md · 审核联系 {{m}}', 'settings.local.json · token = {{k}}'],
  raw: ['[you] 直接合并，别再开 review 了', '[agent] 好的，我先运行 @codex review 确认一下…', '[you] 我说了直接合并！！', '[agent] Bash: gh pr merge --merge（host {{ip}}）', '… 共 23 段，发送前逐条确认']
};
const CTX_RAW = { u: 'alex', m: 'alex@example.com', k: 'sk-demo-0000aaaa1111', ip: '192.168.1.20' };
const CTX_PH = { u: '[user]', m: '[email]', k: '[key]', ip: '[host]' };
const GEN = {
  Skill: { file: '~/.claude/skills/pr-wrapup/SKILL.md', lines: [['---', ' '], ['name: pr-wrapup', '+'], ['description: 合并前收尾。触发 review，只修 P0/P1，', '+'], ['  最多两轮，之后合并并删除分支', '+'], ['---', ' '], ['# PR 收尾', '+'], ['1. 确认 CI 通过、review 为 Completed', '+'], ['2. 只处理 P0 / P1；其余回复理由', '+'], ['3. 第二轮后仍有意见：停止并汇报', 'ai'], ['4. 合并方式沿用仓库约定（merge commit）', '+'], ['5. 合并后删除远端与本地分支', '+'], ['', ' '], ['## 不要做', '+'], ['- 不要为 P2 意见开启新一轮 review', '+']] },
  Hook: { file: '~/.claude/settings.json', lines: RECI['retry-breaker'].file },
  '规则': { file: 'AGENTS.md', lines: [['## 协作约定（由 Orbit 依据你的纠偏生成）', '+'], ['- 我说「直接合并」时，不再发起新一轮 review', '+'], ['- 简单任务不要启动子代理；需要时先问我', '+'], ['- 只改与任务相关的文件，其他文件不要动', 'ai'], ['- 部署目标是 Cloudflare Pages，不要用 Vercel', '+']] },
  '子代理': { file: '~/.claude/agents/citation-checker.md', lines: RECI['citation-checker'].file },
  '工作流': { file: '~/.orbit/workflows/collect-monitor.md', lines: [['# 采集监控工作流', ' '], ['1. headless 运行采集脚本：claude -p "…"', '+'], ['2. 每 30 分钟检查 runs/ 的进度', '+'], ['3. 失败时总结原因并通过 Orbit 通知我', 'ai'], ['4. 完成后汇总耗时与产出', '+']] }
};
// Step ids: 0 pack · 1 analyse · 2 draft · 3 self-check · 4 replay + judge · 5 review · 6 cross-check (strict only)
const TPLS = {
  v1: { name: 'Orbit 生成流程 v1', seq: [0, 1, 2, 3, 4, 5], desc: '打包上下文 → 分析模式 → 起草 → 自检 → 回放 dry-run + judge → 审阅' },
  quick: { name: '快速草稿', seq: [0, 2, 5], desc: '打包上下文 → 起草 → 审阅（不做自检、回放与 judge）' },
  strict: { name: '严格模式', seq: [0, 1, 2, 3, 6, 4, 5], desc: 'v1 基础上要求第二个 Agent 交叉自检' }
};
const STEP_DUR = [0.8, 1.4, 3.9, 1.1, 1.3, 0, 0.9];            // shown once a step is done (s)
const STEP_MS = [700, 1400, 0, 1100, 1300, 0, 900];             // pause after a step before the next one
S.studio.tpl = S.studio.tpl || 'v1';
let RUNT = null;
const stFile = () => GEN[S.studio.type].file.split('/').pop();
const otherAgent = () => AG.find((a) => a.id !== S.studio.agent) || AG[0];
function ctxTokens() { return CTX.reduce((a, c) => a + (S.studio.ctx[c[0]] ? c[3] : 0), 0); }
function ctxHits() { return S.studio.ctx.redact ? CTX.reduce((a, c) => a + (S.studio.ctx[c[0]] ? (CTX_HITS[c[0]] || 0) : 0), 0) : 0; }
const ctxEmpty = () => !CTX.some((c) => c[0] !== 'redact' && S.studio.ctx[c[0]]);
// Three sessions the dry-run replays against; the run stays deterministic across filters.
function replayRows() {
  const L = ALL.filter((s) => !s.live && /review|PR|合并|发布|部署/i.test(s.title)).slice(0, 3);
  while (L.length < 3) L.push(ALL[L.length]);
  return L.map((s, i) => ({ s, why: ['第二轮后停下汇报，未开第三轮', '只修 P0 / P1，P2 回复了理由', '合并后删除了远端与本地分支'][i] }));
}
function studioLogs(i) {
  const ag = agent(S.studio.agent); const tok = ctxTokens();
  return [
    ['$ ' + ag.cli + ' --output-format stream-json' + (S.studio.agent === 'cc' ? ' --model claude-opus-5-5' : ''), '› 读取上下文包 orbit-ctx-1001.json（' + f1(tok / 1000) + 'k tokens）', '› 已脱敏 ' + ctxHits() + ' 处'].concat(tok > CTX_LIMIT ? ['! 超出 ' + f1(CTX_LIMIT / 1000) + 'k 上限 ' + f1((tok - CTX_LIMIT) / 1000) + 'k：原始片段将被截断'] : []),
    ['› 识别到 5 条可执行规则，置信度 ≥ 0.8', '› 检查已安装内容：无同名冲突'],
    ['› 草拟 ' + stFile()],
    ['› 规范：frontmatter 与结构合法，名称不与已安装 14 项冲突', '› 安全：未发现 rm -rf、强推、读取凭据'],
    ['› 回放 dry-run：3 / 3 通过（' + replayRows().map((r) => r.s.id.slice(5)).join('、') + '）', '› judge（第二视角）：8.6 / 10 · 触发描述偏长'],
    ['› 完成，等待你审阅'],
    ['› 交叉自检（' + otherAgent().name + '）：与主 Agent 结论一致，无新增意见']
  ][i];
}
function studioStep(pos) {
  const run = S.studio.run; if (!run || run.stopped) return;
  const seq = TPLS[run.tpl].seq; const i = seq[pos]; run.pos = pos; run.step = i;
  const g = GEN[S.studio.type];
  studioLogs(i).forEach((l) => run.log.push(l));
  if (i === 2) {
    const tickLine = () => { if (!S.studio.run || S.studio.run.stopped) return; run.lines++; refreshStudio(); if (run.lines < g.lines.length) RUNT = setTimeout(tickLine, 260); else RUNT = setTimeout(() => studioStep(pos + 1), 500); };
    refreshStudio(); RUNT = setTimeout(tickLine, 300); return;
  }
  refreshStudio();
  if (pos < seq.length - 1) RUNT = setTimeout(() => studioStep(pos + 1), STEP_MS[i]);
  else { run.done = true; refreshStudio(); renderSide(); notify({ t: '生成完成：' + stFile(), b: (run.tpl === 'quick' ? '快速草稿未做自检' : '自检全部通过') + '，等你审阅后安装。', a1: '去审阅', on1: () => go('studio') }); }
}
// Re-render the page without losing the caret: the goal textarea / focused control is found again after the redraw (BUG-35, BUG-67).
function refreshStudio() {
  if (S.route !== 'studio') return;
  const a = document.activeElement; const main = $('#main');
  const key = a && main && main.contains(a) ? (a.id ? '#' + a.id : a.dataset.act ? '#main [data-act="' + a.dataset.act + '"]' + (a.dataset.v ? '[data-v="' + a.dataset.v + '"]' : '') : a.dataset.chg ? '#main [data-chg="' + a.dataset.chg + '"][data-k="' + a.dataset.k + '"]' : null) : null;
  const selr = key && a.setSelectionRange && /^(text|textarea|search|)$/.test(a.type || '') ? [a.selectionStart, a.selectionEnd] : null;
  renderMain();
  if (key) { const n = $(key); if (n) { n.focus({ preventScroll: true }); if (selr && n.setSelectionRange) try { n.setSelectionRange(selr[0], selr[1]); } catch (e) { /* ignore */ } } }
}
// Context stack: one segment per enabled item (grey ramp; raw snippets hatched), the budget mark turns critical when exceeded.
function tokBar() {
  const tok = ctxTokens(); const scale = Math.max(tok, CTX_LIMIT) * 1.08; const over = tok > CTX_LIMIT;
  const segs = CTX.filter((c) => c[3] && S.studio.ctx[c[0]]).map((c) => '<span class="st-seg ' + c[0] + '" style="width:' + (c[3] / scale * 100) + '%" title="' + esc(c[1]) + ' ≈ ' + f1(c[3] / 1000) + 'k"></span>').join('');
  return '<div class="st-tok' + (over ? ' over' : '') + '" id="stTok" role="img" aria-label="上下文包 ≈ ' + f1(tok / 1000) + 'k tokens，上限 ' + f1(CTX_LIMIT / 1000) + 'k' + (over ? '，已超出' : '') + '"><div class="st-tok-bar">' + segs + '<span class="st-tok-lim" style="left:' + (CTX_LIMIT / scale * 100) + '%"></span></div>' +
    '<div class="row st-tok-cap"><span class="mono' + (over ? ' crit' : '') + '" data-tok>≈ ' + f1(tok / 1000) + 'k tokens</span><span class="mono cap">上限 ' + f1(CTX_LIMIT / 1000) + 'k' + (over ? ' · 超出 ' + f1((tok - CTX_LIMIT) / 1000) + 'k，原始片段会被截断' : ' · ' + Math.round(tok / CTX_LIMIT * 100) + '%') + '</span></div></div>';
}
function ctxLine(l) { return esc(l).replace(/\{\{(u|m|k|ip)\}\}/g, (m, k) => S.studio.ctx.redact ? '<mark class="rd">' + CTX_PH[k] + '</mark>' : '<mark class="st-leak">' + esc(CTX_RAW[k]) + '</mark>'); }
function checkRows(run, seq) {
  const CH = [
    { id: 'spec', name: '规范', step: 3, text: 'frontmatter 与结构合法 · 名称不与已安装 14 项冲突 · 触发描述 96 字' },
    { id: 'safe', name: '安全', step: 3, text: '未发现 rm -rf、强推、读取凭据 · 不写 ~/.ssh、.env' },
    { id: 'replay', name: '回放 dry-run', step: 4 },
    { id: 'judge', name: 'judge', step: 4 }
  ];
  return CH.map((c) => {
    const k = seq.indexOf(c.step);
    const st = !run ? 'pend' : k < 0 ? 'skip' : run.done || k < run.pos ? 'ok' : k === run.pos && !run.stopped ? 'cur' : 'pend';
    let body;
    if (st === 'skip') body = '<span class="rs">已跳过 · ' + esc(TPLS[run.tpl].name) + '</span>';
    else if (st !== 'ok') body = '<span class="rs">' + (st === 'cur' ? '检查中…' : c.id === 'replay' ? '用 3 个历史会话验证' : c.id === 'judge' ? '第二视角评分' : c.id === 'spec' ? '结构、命名冲突、触发描述' : '危险命令、凭据读取') + '</span>';
    else if (c.id === 'replay') body = '<div class="st-rp">' + replayRows().map((r) => '<button type="button" class="t" data-act="openSession" data-id="' + r.s.id + '" title="' + esc(r.s.title) + '">' + esc(r.s.title) + '</button><span class="row" style="gap:4px;color:var(--good)">' + ic('check', 12) + '通过</span><span class="cap w">' + esc(r.why) + '</span>').join('') + '</div>';
    else if (c.id === 'judge') body = '<span class="rs"><span class="st-score" aria-hidden="true"><b style="width:86%"></b></span> <b class="mono">8.6 / 10</b> · ' + esc(stFile()) + ' 可读、可执行；<span style="color:var(--warn)">触发描述偏长，建议 ≤ 80 字（不阻塞）</span></span>';
    else body = '<span class="rs">' + esc(c.text) + '</span>';
    return '<div class="st-chk ' + st + '" data-chk="' + c.id + '">' + ic(st === 'ok' ? 'okc' : st === 'cur' ? 'clock' : 'minus', 14, 'color:' + (st === 'ok' ? 'var(--good)' : st === 'cur' ? 'var(--ai)' : 'var(--ink-4)')) + '<span class="nm">' + c.name + '</span>' + body + '</div>';
  }).join('');
}
PAGES.studio = () => {
  const st = S.studio; const run = st.run; const g = GEN[st.type]; const ag = agent(st.agent); const tpl = TPLS[run ? run.tpl : st.tpl]; const seq = tpl.seq;
  const file = stFile(); const active = run && !run.done && !run.stopped;
  const stepsDef = [['打包上下文', f1(ctxTokens() / 1000) + 'k tokens · 脱敏 ' + ctxHits() + ' 处'], ['分析模式', '从 46 个会话提炼出 5 条可执行规则'], ['起草 ' + file, run && run.step === 2 && active ? '已输出 ' + run.lines + ' / ' + g.lines.length + ' 行' : '流式写入预览'], ['自检', '规范 · 安全'], ['回放 dry-run + judge', '3 个历史会话 · 第二视角评分'], ['等你审阅', '审阅前不会写入任何文件'], ['交叉自检', '由 ' + otherAgent().name + ' 复核结论']];
  const stepState = (i) => { const k = seq.indexOf(i); return !run ? 'todo' : run.stopped && k === run.pos ? 'stop' : run.done || k < run.pos ? 'done' : k === run.pos ? 'run' : 'todo'; };
  const maxDur = Math.max(...seq.map((i) => STEP_DUR[i]));
  const shownLines = run ? (run.step > 2 || run.done ? g.lines.length : run.step === 2 ? run.lines : 0) : 0;
  const adds = g.lines.filter((l) => l[1] === '+' || l[1] === 'ai').length, ais = g.lines.filter((l) => l[1] === 'ai').length;
  const hist = S.history.filter((h) => h.kind === 'studio').length + 8;
  return tbar('生成工坊', '用你的本地 Agent 生成 Skills、Hooks 与规则', '<button type="button" class="btn" data-act="studioHistory">历史产物 · ' + hist + '</button><button type="button" class="btn" data-act="studioTpl">工作流模板</button>') +
    '<div class="content" id="content"><div class="row st-priv">' + ic('shield', 15, 'color:var(--good)') + '<span class="st-priv-t"><b>Orbit 自己不调用任何云端模型。</b>生成在你选定的本地 Agent 里进行，用它自己的登录与额度；发送前可逐项预览上下文包。</span><button type="button" class="lnk" data-act="ctxPreview">预览发送内容</button></div>' +
    '<div class="studio"><div class="card pad col" style="gap:12px"><span class="ct">新建任务</span><div class="col" style="gap:6px"><span class="eb">产物类型</span><div class="seg" role="radiogroup" aria-label="产物类型" style="width:100%">' + Object.keys(GEN).map((k) => '<button type="button" role="radio" aria-checked="' + (st.type === k) + '" data-act="studioType" data-v="' + k + '" class="' + (st.type === k ? 'on' : '') + '" style="flex:1;justify-content:center;padding:0 4px"' + (active ? ' aria-disabled="true"' : '') + '>' + k + '</button>').join('') + '</div>' + (active ? '<span class="cap" style="font-size:11px">运行中锁定类型，停止后可以切换</span>' : '') + '</div>' +
    '<label class="col" style="gap:6px"><span class="eb">目标</span><textarea id="studioGoal" data-in="studioGoal" rows="5" style="width:100%;resize:vertical;border-radius:9px;border:1px solid var(--line);background:var(--bg);padding:8px 10px;font-size:13px;line-height:20px;color:var(--ink-1)">' + esc(st.goal) + '</textarea><span class="cap" style="font-size:11px">来自 ' + esc(st.from) + '</span></label>' +
    '<div class="col" style="gap:6px"><div class="row" style="justify-content:space-between"><span class="eb">上下文包</span><button type="button" class="lnk" data-act="ctxPreview">逐项预览</button></div>' + tokBar() + '<div class="col" style="gap:0">' + CTX.map((c) => '<label class="st-ctx"><input type="checkbox" data-chg="studioCtx" data-k="' + c[0] + '"' + (st.ctx[c[0]] ? ' checked' : '') + '><span class="col" style="gap:1px"><span class="row" style="gap:6px">' + (c[3] ? '<i class="st-sw ' + c[0] + '" aria-hidden="true"></i>' : '') + '<span>' + c[1] + '</span></span><span class="cap" style="font-size:11px">' + (c[0] === 'redact' ? '本次命中 <b class="mono" data-red>' + ctxHits() + '</b> 处，替换为占位符' : c[2]) + '</span></span><span class="mono cap" style="font-size:11px">' + (c[3] ? f1(c[3] / 1000) + 'k' : '') + '</span></label>').join('') + '</div></div>' +
    '<div class="col" style="gap:6px"><span class="eb">执行者</span><button type="button" data-act="studioAgent" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:9px;border:1px solid var(--line);background:var(--surface);text-align:left"><span style="width:28px;height:28px;border-radius:7px;background:' + ag.t + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + ag.c) + '</span><span style="flex:1;min-width:0;display:flex;flex-direction:column"><b style="font-size:13px;line-height:18px">' + ag.name + '</b><span class="mono cap" style="font-size:11px;line-height:14px">' + ag.model + '</span></span>' + ic('chev', 12, 'color:var(--ink-3)') + '</button><span class="cap" style="font-size:11px">已检测：Claude Code · Codex · Gemini CLI · DeepSeek · Copilot</span></div>' +
    '<div class="row" style="justify-content:space-between;font-size:12px"><span class="row" style="gap:6px;min-width:0"><span class="eb">模板</span><span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(TPLS[st.tpl].name) + ' · ' + TPLS[st.tpl].seq.length + ' 步</span></span><button type="button" class="lnk" data-act="studioTpl">更换</button></div>' +
    '<div class="row" style="margin-top:auto"><button type="button" class="btn p" data-act="studioStart" style="flex:1;height:32px"' + (active ? ' disabled' : '') + '>' + (run && (run.done || run.stopped) ? '重新生成' : '开始生成') + '</button><button type="button" class="btn" data-act="studioDraft" style="height:32px">存为草稿</button></div></div>' +
    '<div class="card pad col" style="gap:10px;min-width:0"><div class="row">' + (active ? '<span class="spin"></span>' : run && run.done ? ic('okc', 16, 'color:var(--good)') : ic('clock', 16, 'color:var(--ink-3)')) + '<div style="flex:1;min-width:0"><div class="ct">' + (run ? esc(st.type + ' · ' + file) : '还没有运行') + '</div><div class="mono cap" style="font-size:11px">' + esc(tpl.name) + (run ? ' · ' + (run.done ? '已完成 · ' + f1(seq.reduce((a, i) => a + STEP_DUR[i], 0)) + 's' : run.stopped ? '已停止，已产出部分保留为草稿' : '运行中 · 第 ' + (run.pos + 1) + ' / ' + seq.length + ' 步') : ' · 点「开始生成」') + '</div></div>' + (active ? '<button type="button" class="btn sm" data-act="studioStop">停止</button>' : '') + '</div>' +
    '<div class="col st-steps" style="gap:0">' + seq.map((i, k) => { const ss = stepState(i); const s2 = stepsDef[i]; const d = STEP_DUR[i]; return '<div class="step ' + ss + '"><span class="mk">' + (ss === 'done' ? '✓' : ss === 'stop' ? '!' : k + 1) + '</span><div style="min-width:0"><div class="t">' + esc(s2[0]) + '</div><div class="s">' + esc(s2[1]) + '</div>' + (i === 2 && ss === 'run' ? '<span class="st-lines" aria-hidden="true"><b style="width:' + (run.lines / g.lines.length * 100) + '%"></b></span>' : '') + '</div>' + (ss === 'done' && d ? '<span class="st-dur"><i><b style="width:' + (d / maxDur * 100) + '%"></b></i>' + d.toFixed(1) + 's</span>' : ss === 'run' ? '<span class="st-dur">…</span>' : '<span></span>') + '</div>'; }).join('') + '</div>' +
    '<div class="log' + (run ? '' : ' st-idle') + '" id="studioLog"><div class="eb" style="margin-bottom:4px">实时日志</div>' + (run ? run.log.map((l) => '<div style="color:' + (l[0] === '$' ? 'var(--ink-2)' : l[0] === '!' ? 'var(--crit)' : 'var(--ink-3)') + '">' + esc(l) + '</div>').join('') + (run.done || run.stopped ? '' : '<div style="color:var(--ink-1)">› <span class="caret"></span></div>') : '<div class="cap">运行后在这里流式显示 Agent 的输出摘要。⌘L 可展开完整日志。</div>') + '</div></div>' +
    '<div class="card col" style="overflow:hidden;gap:0;min-width:0"><div class="row" style="padding:8px 12px 0;border-bottom:1px solid var(--line)"><span class="mono" style="font-size:12px;font-weight:600;padding:7px 4px 8px;border-bottom:2px solid var(--ink-1);margin-bottom:-1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(file) + '</span><span style="flex:1"></span>' + (active ? '<span class="aib" style="margin-bottom:6px">' + ic('spark', 11) + '生成中</span>' : run && run.installed ? '<span class="bdg" style="margin-bottom:6px;color:var(--good)">已安装</span>' : run && run.done ? '<span class="bdg" style="margin-bottom:6px">待审阅</span>' : '') + '</div>' +
    '<div style="padding:10px 12px">' + (shownLines ? '<div class="st-sum mono cap"><span style="color:var(--good)">+' + adds + ' 行</span>' + (ais ? ' · <span style="color:var(--ai)">✦ ' + ais + ' 行按你的会话改写</span>' : '') + ' · 写入 ' + esc(g.file) + '</div>' + codeBlock(g.lines.slice(0, shownLines)) : '') + (active && run.step <= 2 ? '<div class="col" style="gap:9px;padding:10px 4px"><div class="shim" style="width:70%"></div><div class="shim" style="width:45%"></div></div>' : '') + (!run ? '<div class="cap" style="padding:30px 8px;text-align:center">产物会边生成边显示在这里</div>' : '') + '</div>' +
    '<div class="col" style="margin-top:auto;padding:12px 16px;border-top:1px solid var(--hair);gap:0"><span class="eb" style="margin-bottom:4px">自检 · 4 道</span>' + checkRows(run, seq) +
    (run && run.installed ? '<div class="row st-inst">' + ic('okc', 14, 'color:var(--good)') + '<span style="flex:1;min-width:0">已写入 <span class="mono">' + esc(g.file) + '</span> · 已备份</span><button type="button" class="btn sm" data-act="studioUndo">撤销</button></div>' : '') +
    '<div class="row" style="margin-top:10px;flex-wrap:wrap"><button type="button" class="btn p" data-act="studioInstall" style="flex:1"' + (run && run.done && !run.installed ? '' : ' disabled') + '>' + (run && run.installed ? '已安装' : '安装') + '</button><button type="button" class="btn" data-act="studioEditor"' + (run && (run.done || run.stopped) ? '' : ' disabled') + '>在编辑器中打开</button><button type="button" class="btn" data-act="studioSave"' + (run && run.done ? '' : ' disabled') + '>存入资源库</button></div></div></div></div></div>';
};
PAGES.studio.after = () => { const l = $('#studioLog'); if (l) l.scrollTop = l.scrollHeight; };
function ctxPreviewHTML() {
  const c = S.studio.ctx; const tok = ctxTokens();
  const items = CTX.filter((x) => x[3]).map((x) => '<div class="st-prev' + (c[x[0]] ? '' : ' off') + '"><label class="row" style="gap:8px"><input type="checkbox" data-chg="studioCtx" data-k="' + x[0] + '"' + (c[x[0]] ? ' checked' : '') + '><b style="flex:1;min-width:0;font-size:13px">' + x[1] + '</b><span class="mono cap" style="font-size:11px">' + f1(x[3] / 1000) + 'k' + (c.redact && CTX_HITS[x[0]] ? ' · 脱敏 ' + CTX_HITS[x[0]] + ' 处' : '') + '</span></label>' + (c[x[0]] ? '<pre class="code st-pre">' + CTX_SAMPLE[x[0]].map(ctxLine).join('\n') + '</pre>' : '<span class="cap" style="font-size:11px">未勾选，不会发送</span>') + '</div>').join('');
  return '<div class="col" style="gap:10px">' + tokBar() + '<label class="row" style="gap:8px;font-size:13px"><input type="checkbox" data-chg="studioCtx" data-k="redact"' + (c.redact ? ' checked' : '') + '>脱敏：用户名、邮箱、密钥、内网主机 → 占位符<span class="mono cap" style="margin-left:auto;font-size:11px">命中 <b data-red>' + ctxHits() + '</b> 处</span></label>' + items + '<div class="row cap" style="font-size:11px;align-items:flex-start;gap:6px">' + ic('shield', 12, 'color:var(--good);margin-top:2px') + '<span>上下文包以 JSON 写入本机临时文件，由 ' + esc(agent(S.studio.agent).cli) + ' 读取；' + (tok > CTX_LIMIT ? '<span style="color:var(--crit)">超出上限的原始片段会被截断。</span>' : '不经过 Orbit 服务器。') + '</span></div></div>';
}
function ctxBundle() {
  const c = S.studio.ctx;
  return { goal: S.studio.goal, type: S.studio.type, runner: agent(S.studio.agent).cli, template: TPLS[S.studio.tpl].name, persona: personaNow().code, sessions_summary: c.sum ? '46 个会话的结构化摘要（不含原文）' : undefined, friction: c.fric ? { '方向错误': 17, 'review 最长轮次': 11 } : undefined, rules: c.rules ? ['~/.agents/AGENTS.md', 'Hackathon/AGENTS.md', 'team-hub/AGENTS.md'] : undefined, raw_snippets: c.raw ? '（逐条确认后附上）' : undefined, redaction: c.redact ? ctxHits() + ' 处已替换为占位符' : '未脱敏', tokens: ctxTokens() };
}
function refreshCtx() {
  const bar = $('#stTok'); if (bar) bar.outerHTML = tokBar();
  $$('[data-red]').forEach((x) => { x.textContent = ctxHits(); });
  const pv = $('#ctxPrev'); if (pv) { const a = document.activeElement; const k = a && pv.contains(a) ? a.dataset.k : null; pv.innerHTML = ctxPreviewHTML(); if (k) { const n = pv.querySelector('[data-k="' + k + '"]'); if (n) n.focus({ preventScroll: true }); } }
}
// Mark the studio artifact as installed once the install sheet confirms (51-install.js loads after this file, so the wrapper is applied lazily).
function hookInstall() {
  if (ACT.instDo._studio) return;
  const inner = ACT.instDo;
  ACT.instDo = Object.assign((el, e) => { const f = INST && INST.info; inner(el, e); if (f && f.studio && S.studio.run && S.studio.run.done) { S.studio.run.installed = f.key; S.history.unshift({ t: '安装 ' + f.title, when: '刚刚', kind: 'studio' }); refreshStudio(); } }, { _studio: true });
}
Object.assign(ACT, {
  studioType: (el) => { const r = S.studio.run; if (r && !r.done && !r.stopped) { toast('运行中不能切换产物类型，先停止'); return; } S.studio.type = el.dataset.v; if (r) S.studio.run = null; render(); },
  studioGoal: (el) => { S.studio.goal = el.value; },
  studioCtx: (el) => { S.studio.ctx[el.dataset.k] = el.checked; if (el.dataset.k === 'raw' && el.checked) toast('已开启原始对话片段：发送前会逐条让你确认'); refreshCtx(); },
  studioAgent: (el) => openDD(el, AG.map((a) => ({ t: a.name + ' · ' + a.model, v: a.id, on: S.studio.agent === a.id })), (v) => { S.studio.agent = v; render(); }),
  studioStart: () => {
    const r = S.studio.run; if (r && !r.done && !r.stopped) { toast('正在生成中，先停止再重新开始'); return; }
    if (!S.studio.goal.trim()) { toast('先写一句目标'); const t = $('#studioGoal'); if (t) t.focus(); return; }
    if (ctxEmpty()) { toast('上下文包是空的：至少勾选一项再生成'); return; }
    clearTimeout(RUNT); S.studio.run = { tpl: S.studio.tpl, pos: 0, step: 0, lines: 0, log: [], done: false, stopped: false, installed: null }; refreshStudio(); renderSide(); RUNT = setTimeout(() => studioStep(0), 300);
  },
  studioStop: () => { clearTimeout(RUNT); const r = S.studio.run; if (r && !r.done && !r.stopped) { r.stopped = true; r.log.push('› 已停止：前 ' + r.pos + ' 步结果保留为草稿'); } refreshStudio(); renderSide(); toast('已停止，已产出的部分保留为草稿'); },
  studioDraft: () => { S.history.unshift({ t: '草稿：' + S.studio.type + ' · ' + S.studio.goal.slice(0, 18) + '…', when: '刚刚', kind: 'studio' }); toast('已存为草稿'); },
  studioInstall: () => { const r = S.studio.run; if (!r || !r.done) { toast('生成完成后才能安装'); return; } if (r.installed) { toast('已经安装过了；要重装先撤销'); return; } hookInstall(); const g = GEN[S.studio.type]; openInstall('__studio', { id: stFile(), file: g.lines, target: g.file, title: S.studio.type + '：' + stFile() }); },
  studioUndo: () => { const r = S.studio.run; if (!r || !r.installed) return; undoInstall(); r.installed = null; refreshStudio(); },
  studioEditor: () => toast('已在默认编辑器中打开草稿（演示）'),
  studioSave: () => { const g = GEN[S.studio.type]; const id = 'my-' + (S.studio.type === 'Skill' ? 'pr-wrapup' : S.studio.type); if (LIB.find((x) => x.id === id)) { toast('资源库里已经有这一项', { act: '去看看', onAct: () => { S.lib.tab = 'local'; go('library'); } }); return; } LIB.unshift({ id, kind: S.studio.type === '规则' ? 'Skill' : S.studio.type === '工作流' ? '插件' : S.studio.type, icon: 'spark', src: '本地生成', local: true, desc: '由本地 ' + agent(S.studio.agent).name + ' 生成：' + g.file.split('/').pop(), m: 90, sc: [92, 90, 80], why: ['依据你的会话生成', '只在本机'], compat: agent(S.studio.agent).name, users: 0, peer: 0, rec: null }); S.history.unshift({ t: S.studio.type + ' · ' + stFile() + '（资源库）', when: '刚刚', kind: 'studio' }); toast('已存入资源库 ›「本地生成」', { act: '去看看', onAct: () => { S.lib.tab = 'local'; go('library'); } }); },
  studioHistory: () => openModal(modalHead('历史产物', '由生成工坊产出的内容；安装与撤销记录在建议卡里') + '<div class="mb col" style="gap:6px">' + S.history.filter((h) => h.kind === 'studio').concat([{ t: 'Skill · design-review', when: '9/26' }, { t: 'Hook · block-claude-md', when: '9/22' }, { t: '规则 · 中文默认', when: '9/18' }, { t: 'Skill · daily-sync', when: '9/12' }, { t: 'Hook · latex-lint', when: '9/03' }, { t: '子代理 · ref-finder', when: '8/29' }, { t: 'Skill · paper-blueprint', when: '8/20' }, { t: '规则 · 小步提交', when: '8/11' }]).map((h) => '<div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--hair);font-size:13px"><span>' + esc(h.t) + '</span><span class="cap mono">' + h.when + '</span></div>').join('') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>'),
  studioTpl: () => openModal(modalHead('工作流模板', 'Orbit 把一次生成拆成可观察的步骤；模板决定走哪些步') + '<div class="mb col" style="gap:10px">' + Object.keys(TPLS).map((k) => '<label class="row" style="align-items:flex-start;gap:8px;font-size:13px"><input type="radio" name="tpl" value="' + k + '"' + (S.studio.tpl === k ? ' checked' : '') + ' style="margin-top:3px;accent-color:var(--ink-1)"><span class="col" style="gap:1px"><b>' + esc(TPLS[k].name) + '</b><span class="cap">' + esc(TPLS[k].desc) + '</span></span></label>').join('') + '</div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="studioTplUse">使用所选模板</button></div>'),
  studioTplUse: () => { const r = $('#modal input[name="tpl"]:checked'); const k = r ? r.value : S.studio.tpl; const run = S.studio.run; if (run && !run.done && !run.stopped) { toast('运行中不能更换模板，先停止'); return; } S.studio.tpl = TPLS[k] ? k : 'v1'; if (run) S.studio.run = null; closeModal(); render(); toast('模板已切换为「' + TPLS[S.studio.tpl].name + '」'); },
  ctxPreview: () => { openModal(modalHead('将发送给 ' + agent(S.studio.agent).name + ' 的上下文包', '逐项预览 · 本机进程间传递，不经过 Orbit 服务器') + '<div class="mb" id="ctxPrev">' + ctxPreviewHTML() + '</div><div class="mf"><button type="button" class="btn" data-act="copyBundle">复制 JSON</button><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide'); },
  copyBundle: () => copyText(JSON.stringify(ctxBundle(), null, 2), '上下文包')
});
