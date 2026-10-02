/* ============ Lite edition pages (l-home / l-persona / l-sessions / l-recs) ============
 * Lite = genius-FXC 的 Benchmark 精简成四页、每页一个主结论。视觉不另起一套：只用 Advance 已有组件拼装
 * （.card / .pad / .hd .ct .cap .eb、VZ.kpi 指标卡、.seg、.chip、.btn / .btn.p、.aib、.rcard 建议卡、.srow 会话行、
 * .persona-hero + .letters + .fp-wrap + fp2SVG、.ax + .track 维度条、.evo 月份码），冲击力只来自 39-lite.css 里
 * .lite 作用域下的尺寸变体（更大的字、更少的区块、更多留白）。
 * - 没有 Advance 的筛选行：只保留时间范围 seg（data-act="range"）；若带着 Advance 的 Agent / 项目 / 主题 / 结果等筛选，
 *   标题栏右侧给一个「已应用 Advance 筛选 · 清除」chip。
 * - 每页给「在 Advance 中查看明细 →」（edOpen，见 26-edition.js）。
 * - 动效标记：人格码 data-hero="code"、指纹 data-hero="fp"、大数字 data-count / data-dec（count-up 与进入编排由 37-motion.js 统一处理）。 */
const liteFiltered = () => S.agents.size < AG.length || !!S.project || !!S.topic || !!S.outcome || !!S.fric || S.hour != null;
function liteRight() {
  const seg = '<div class="seg" role="group" aria-label="时间范围">' + [[7, '7 天'], [30, '30 天'], [90, '90 天'], [0, '全部']].map((x) => '<button type="button" data-act="range" data-v="' + x[0] + '" class="' + (S.range === x[0] ? 'on' : '') + '" aria-pressed="' + (S.range === x[0]) + '">' + x[1] + '</button>').join('') + '</div>';
  const chip = liteFiltered() ? '<button type="button" class="chip on l-fchip" data-act="liteClear" data-tip="Lite 不显示筛选行；这些筛选来自 Advance，点击清除">已应用 Advance 筛选 · 清除' + ic('x', 12) + '</button>' : '';
  return chip + seg;
}
const liteBar = (title, meta) => tbar(title, meta, liteRight());
// 去 Advance 明细的链接：同一个 .lnk 样式，箭头在文字后
const liteAdv = (route, label) => '<button type="button" class="lnk l-adv" data-act="edOpen" data-r="' + route + '">' + (label || '在 Advance 中查看明细') + ' →</button>';
const liteFoot = (links) => '<div class="l-foot">' + links.map((x) => liteAdv(x[0], x[1])).join('<span class="l-sep" aria-hidden="true">·</span>') + '</div>';
// 大数字的 count-up 标记：data-count 为纯数字（可带小数），data-dec 为小数位
const liteCount = (html, v, dec) => html.replace('<span class="v">', '<span class="v" data-count="' + (dec ? (+v).toFixed(dec) : Math.round(v)) + '"' + (dec ? ' data-dec="' + dec + '"' : '') + '>');
// 建议主按钮：复用 A1 的 recPrimaryBtn；Lite 里教程 / 交给工坊 / 已安装追踪都在 Advance 页，改成先切过去再打开
function liteRecBtn(r) {
  return recPrimaryBtn(r).replace(/data-act="(tutorial|recToStudio|openRec)"/, 'data-act="liteRecAdv"').replace('class="btn', 'class="btn l-big');
}
const liteOrder = () => visibleRecs().slice().sort((a, b) => recX(b.id).save - recX(a.id).save);
const liteSaveH = (id) => recX(id).save;

/* ---------- 1 概览：AI 一句话 + 人格码 → 四个大数字 + 活跃条带 → 本周最值得做的一件事 ---------- */
PAGES['l-home'] = () => {
  const L = sel(); const st = stats(L);
  const pw = prevWin(S.range); const P = pw ? stats(sel({ win: pw })) : null;
  const pers = personaNow();
  const lede = pers.ok ? '你像一位' + pers.zh + '：' + pers.line : '样本不足：所选范围只有 ' + pers.n + ' 个会话，至少需要 30 个才给出协作画像。';
  const ev = st.n ? Math.round(st.verify) + '% 的会话要求验证 · ' + fmt(st.corr) + ' 条纠偏消息 · 完成率 ' + Math.round(st.ok) + '%' : '这段时间没有会话';
  const hero = '<div class="card pad l-hero"><div class="col l-lede"><div class="row" style="flex-wrap:wrap"><span class="aib">' + ic('spark', 11) + 'AI 解读</span><span class="cap">本地 Claude Code 生成 · 9/30 23:10</span></div>' +
    '<p class="serif l-say">' + esc(lede) + '</p><span class="cap mono l-ev">' + ev + '</span></div>' +
    (pers.ok ? '<button type="button" class="ov-code l-code" data-act="go" data-r="l-persona" aria-label="查看协作画像：' + pers.code + ' ' + pers.zh + '"><span class="eb">协作画像 · ' + rangeLabel() + '</span><span class="serif ov-code-l" data-hero="code">' + pers.code + '</span><span class="row" style="align-items:baseline;flex-wrap:wrap;gap:8px"><span class="serif l-zh">' + pers.zh + '</span><span class="serif l-en">' + pers.en + '</span></span><span class="cap">查看协作画像 →</span></button>'
      : '<div class="ov-code l-code"><span class="eb">协作画像</span><span class="serif ov-code-l" data-hero="code">????</span><span class="cap">再积累 ' + Math.max(0, 30 - pers.n) + ' 个会话后揭晓</span></div>') + '</div>';
  const d = (cur, prev, o) => P ? Object.assign({ cur, prev }, o) : { text: S.range ? '无可比上期' : '全部历史 · 不比较', cls: '' };
  const tiles = [
    liteCount(VZ.kpi({ label: '会话', value: fmt(st.n), delta: d(st.n, P && P.n, { unit: 'pct', goodDown: false, fmt: 'int' }), act: 'go', attrs: ' data-r="l-sessions"' }), st.n),
    liteCount(VZ.kpi({ label: '协作时长', value: st.hours >= 100 ? fmt(st.hours) : f1(st.hours), unit: 'h', delta: d(st.hours, P && P.hours, { unit: 'pct', goodDown: false, fmt: (v) => f1(v) + 'h' }) }), st.hours, st.hours >= 100 ? 0 : 1),
    liteCount(VZ.kpi({ label: '摩擦率', value: f1(st.fric), unit: '%', delta: d(st.fric, P && P.fric, { unit: 'pt', goodDown: true, fmt: (v) => f1(v) + '%' }) }), st.fric, 1),
    liteCount(VZ.kpi({ label: '完成率', value: String(Math.round(st.ok)), unit: '%', delta: d(st.ok, P && P.ok, { unit: 'pt', goodDown: false, fmt: (v) => Math.round(v) + '%' }) }), st.ok)
  ].join('');
  // 活跃条带：至少 30 天，当前范围内的日子用实色，范围外的用浅色
  const w = win(S.range); const span = Math.max(30, w[1] - w[0] + 1); const a0 = w[1] - span + 1;
  const LL = sel({ win: [Math.max(0, a0), w[1]] }); const per = {}; LL.forEach((s) => { per[s.d] = (per[s.d] || 0) + 1; });
  const days = Array.from({ length: span }, (_, i) => a0 + i).filter((x) => x >= 0); const mx = Math.max(1, ...days.map((x) => per[x] || 0));
  const strip = '<div class="l-strip" role="img" aria-label="每日会话数 · ' + md(days[0]) + ' — ' + md(w[1]) + '">' + days.map((x) => '<i class="' + (x >= w[0] ? 'in' : '') + '" style="height:' + Math.max(4, (per[x] || 0) / mx * 100).toFixed(1) + '%" data-tip="' + md(x) + ' 周' + WD[wd(x)] + ' · ' + (per[x] || 0) + ' 个会话"></i>').join('') + '</div>' +
    '<div class="row cap l-strip-l"><span class="mono">' + md(days[0]) + '</span><span style="flex:1;text-align:center">每日会话 · 深色为' + rangeLabel() + '</span><span class="mono">' + md(w[1]) + '</span></div>';
  const open = liteOrder().filter((r) => !S.installed.has(r.id)); const r = open[0];
  const one = r ? '<div class="card rcard l-one"><div class="rc-top"><span class="eb" style="color:var(--ink-1)">本周最值得做的一件事</span><span class="row" style="gap:5px">' + ic(r.icon, 14, 'color:var(--ink-1)') + '<b class="mono">' + r.type + '</b></span><span class="row" style="gap:5px">' + lvlIcon(r.lvl) + LEVELS[r.lvl] + '</span></div>' +
    '<div class="rc-title serif">' + esc(r.title) + '</div><div class="rc-why">' + esc(r.why) + '</div>' +
    '<div class="rc-foot"><span class="l-gain"><span class="v mono" data-count="' + liteSaveH(r.id).toFixed(1) + '" data-dec="1">' + f1(liteSaveH(r.id)) + '</span><span class="u">h / 月 · 估计节省</span><span class="mono l-g2">' + esc(r.gain) + '</span></span><span style="flex:1"></span>' +
    (open.length > 1 ? '<button type="button" class="btn gh l-big" data-act="go" data-r="l-recs">还有 ' + (open.length - 1) + ' 条 →</button>' : '') + liteRecBtn(r) + '</div></div>'
    : '<div class="card pad l-one l-done"><span class="eb">本周最值得做的一件事</span><p class="serif l-say" style="margin:0">建议都已处理。7 天后在「优化建议」里看效果。</p><button type="button" class="btn l-big" data-act="go" data-r="l-recs" style="align-self:flex-start">查看已应用的建议 →</button></div>';
  return liteBar('概览', winLabel() + ' · ' + st.n + ' 个会话') +
    '<div class="content" id="content"><div class="lite l-home">' + hero +
    '<section class="l-sec"><div class="tiles l-tiles">' + tiles + '</div>' + strip + '</section>' + one +
    liteFoot([['overview', '完整概览'], ['tools', '工具调用'], ['projects', '项目习惯']]) + '</div></div>';
};

/* ---------- 2 协作画像：超大四字母 + 指纹 → 四个维度 → 月度演变 ---------- */
PAGES['l-persona'] = () => {
  const L = personaScope(); const p = persona(L);
  if (!p.ok) {
    return liteBar('协作画像', rangeLabel() + ' · ' + p.n + ' 个会话') + '<div class="content" id="content"><div class="lite l-persona"><div class="card pe-low l-low"><div class="ov-code"><span class="serif ov-code-l" data-hero="code">????</span></div><div class="col" style="gap:10px;flex:1;min-width:240px"><span class="eb">样本不足</span><p class="serif l-say" style="margin:0">所选范围只有 ' + p.n + ' 个会话，至少需要 30 个才给出协作画像。</p><div class="row" style="flex-wrap:wrap"><button type="button" class="btn p l-big" data-act="range" data-v="30">看近 30 天</button><button type="button" class="btn l-big" data-act="range" data-v="0">看全部历史</button></div></div></div>' + liteFoot([['persona', '在 Advance 中查看明细']]) + '</div></div>';
  }
  const tags = [0, 1, 2, 3].map((i) => axisView(p, i)).map((a) => '<span class="tag">' + a.name + ' ' + a.strong + '</span>').join('');
  const hero = '<div class="card persona-hero l-phero"><div class="col" style="gap:0;min-width:0"><div class="row" style="flex-wrap:wrap"><span class="eb">协作画像 · ' + rangeLabel() + '</span><span class="bdg">置信度 ' + p.conf + ' · n=' + p.n + '</span></div>' +
    '<div class="letters" data-hero="code" aria-label="' + p.code + ' ' + p.zh + '">' + p.code.split('').map((ch) => '<span class="L serif">' + ch + '</span>').join('') + '</div>' +
    '<div class="row" style="align-items:baseline;gap:12px;flex-wrap:wrap"><span class="serif l-zh">' + p.zh + '</span><span class="serif l-en">' + p.en + '</span></div>' +
    '<p class="serif l-line">' + esc(p.line) + '</p><div class="row" style="flex-wrap:wrap;gap:6px"><span class="aib">' + ic('spark', 11) + 'AI 撰写</span>' + tags + '</div>' +
    '<div class="row l-acts"><button type="button" class="btn p l-big" data-act="reveal">' + ic('play', 13) + '播放揭晓</button><button type="button" class="btn l-big" data-act="share">' + ic('share', 14) + '导出分享卡</button></div></div>' +
    '<div class="fp-wrap l-fp" data-hero="fp">' + fp2SVG(L, p, 300, { labels: true }) + '</div></div>';
  const axes = '<div class="card pad l-axes"><div class="hd"><div class="grow"><span class="ct">四个维度</span><span class="cap">点的位置 = 你偏向哪一极 · 中线 50</span></div></div>' + [0, 1, 2, 3].map((i) => {
    const a = axisView(p, i); const lw = a.leftWins;
    return '<div class="ax l-ax"><span class="l-pole' + (lw ? ' on' : '') + '"><b class="mono">' + a.ax.L + '</b>' + a.ax.Ln + '</span><span class="track"><span class="mid"></span><span class="fill" style="left:' + Math.min(a.pos, 50) + '%;width:' + Math.abs(a.pos - 50) + '%"></span><span class="knob" style="left:' + a.pos + '%"></span></span><span class="l-pole r' + (lw ? '' : ' on') + '">' + a.ax.Rn + '<b class="mono">' + a.ax.R + '</b></span><span class="mono l-axv" data-count="' + a.strong + '">' + a.strong + '</span></div>';
  }).join('') + '</div>';
  const months = ['jun', 'jul', 'aug', 'sep'].map((k) => ({ k, m: ({ jun: 6, jul: 7, aug: 8, sep: 9 })[k], p: persona(personaScope([PERIODS[k][0], PERIODS[k][1]])) }));
  const evo = '<div class="card pad l-evo"><div class="hd"><div class="grow"><span class="ct">演变</span><span class="cap">按月重算 · 点击在 Advance 中查看那个月</span></div>' + liteAdv('persona') + '</div><div class="evo">' +
    months.map((m, i) => '<button type="button" data-act="litePeriod" data-v="' + m.k + '" class="' + (m.k === 'sep' ? 'on' : '') + '"' + (m.k === 'sep' ? ' aria-current="true"' : '') + '><span class="mono l-mm">' + m.m + ' 月' + (m.k === 'sep' ? ' · 本月' : '') + '</span><span class="serif l-mc">' + (m.p.ok ? m.p.code : '—') + '</span><span class="l-mz">' + (m.p.ok ? m.p.zh : '样本不足') + '</span></button>' + (i < 3 ? ic('arrow', 14, 'color:var(--ink-4)') : '')).join('') + '</div></div>';
  return liteBar('协作画像', 'n=' + p.n + ' · ' + new Set(L.map((s) => s.a)).size + ' 个 Agent · ' + rangeLabel()) +
    '<div class="content" id="content"><div class="lite l-persona">' + hero + axes + evo + '</div></div>';
};

/* ---------- 3 会话轨迹：最近 8 个会话 → 选中会话的大标题 + 四个数字 + 关键步骤时间线 + AI 洞察 ---------- */
function liteSessList() {
  const w = win(S.range);
  const all = ALL.filter((s) => (s.d === 120 || (s.d >= w[0] && s.d <= w[1])) && sessOk(s)).sort((a, b) => (b.d - a.d) || (b.h - a.h) || (b.mi - a.mi));
  const top = all.slice(0, 8);
  const cur = BYID[S.sess.sel];
  // 从别处 openSession 进来：选中的会话不在最近 8 个里时也放进列表（替换最后一个）
  if (cur && !top.includes(cur) && all.includes(cur)) top.splice(7, 1, cur);
  return top;
}
function liteInsight(s, tr) {
  const streak = tr.moments.find((m) => m[1] === '连续失败');
  if (s.live) return '会话进行中：已运行 ' + liveMin() + ' 分钟、调用工具 ' + s.tools + ' 次，暂时没有卡住的迹象。';
  if (streak) return '同一命令连续失败才停下——下次失败两次就先检查认证与环境，再继续。' + (s.corr ? '这次你还纠偏了 ' + s.corr + ' 次。' : '');
  if (s.corr >= 2) return '你纠偏了 ' + s.corr + ' 次，方向在中途才说清——把完成条件写进第一条消息，能省掉大部分来回。';
  if (s.out === 'ok' && s.verify) return '一次到位：目标清楚、过程中' + (s.corr ? '只纠偏 1 次' : '没有返工') + '，最后做了验证。可以把这次的开场白存成模板。';
  if (s.out === 'ok') return '顺利完成，但没有要求验证——加一步测试或线上检查，结果会更稳。';
  if (s.out === 'fail') return '这次放弃了。' + (s.errors ? '出现 ' + s.errors + ' 次工具错误，' : '') + '换个更小的切入点，或先让 Agent 只读调查。';
  return '部分完成：' + (s.errors ? s.errors + ' 次工具错误拖慢了进度，' : '') + '建议把剩余部分拆成单独的会话。';
}
PAGES['l-sessions'] = () => {
  const list = liteSessList();
  let s = BYID[S.sess.sel];
  if (!s || !list.includes(s)) s = list[0];
  if (!s) return liteBar('会话轨迹', rangeLabel()) + '<div class="content" id="content"><div class="lite l-sessions">' + empty('没有匹配的会话。试试放宽时间范围' + (liteFiltered() ? '，或清除 Advance 筛选' : '') + '。') + '</div></div>';
  const tr = traj(s); const T = tr.T; const o = OUT[s.out] || OUT.ok;
  const rows = list.map((x) => { const ox = OUT[x.out] || OUT.ok; return '<button type="button" class="srow' + (x === s ? ' sel' : '') + '" data-act="liteSess" data-id="' + x.id + '" aria-pressed="' + (x === s) + '"><span class="row" style="width:100%"><span class="dot' + (x.live ? ' live' : '') + '" style="background:' + agent(x.a).c + '"></span><span class="t">' + esc(x.title) + '</span>' + ic(ox[0], 14, 'color:' + ox[1]) + '</span><span class="m">' + (x.d === 120 ? '今天' : md(x.d)) + ' ' + hm(x.h, x.mi) + ' · ' + (x.live ? '运行中 ' + liveMin() + 'm' : dur(x.dur)) + '</span></button>'; }).join('');
  const nums = [
    liteCount(VZ.kpi({ label: '你的消息', value: String(s.msgs), unit: '轮' }), s.msgs),
    liteCount(VZ.kpi({ label: '工具调用', value: String(s.tools), unit: '次' }), s.tools),
    liteCount(VZ.kpi({ label: '工具错误', value: String(s.errors), unit: '次', sub: '纠偏 ' + s.corr + ' 次', cls: s.errors >= 3 ? 'l-warn' : '' }), s.errors),
    liteCount(VZ.kpi({ label: '时长', value: s.live ? String(liveMin()) : String(Math.round(s.dur)), unit: 'min', sub: s.live ? '运行中' : s.dur >= 60 ? dur(s.dur) : '' }), s.live ? liveMin() : s.dur)
  ].join('');
  // 时间线：阶段带（宽度够才写名字）+ 关键时刻节点（编号，纠偏 / 失败用 crit）+ 节点列表
  const pc = (t) => clamp(t / T * 100, 0, 100).toFixed(2);
  const phases = tr.phases.map((ph) => { const wpc = (ph[1] - ph[0]) / T * 100; return '<span class="l-ph" style="left:' + pc(ph[0]) + '%;width:' + wpc.toFixed(2) + '%">' + (wpc >= 11 ? '<span>' + esc(ph[2]) + '</span>' : '') + '</span>'; }).join('');
  // 节点至少相隔 8%（约 40px，留出 3px 描边），太近的顺次后推（只为可读，顺序不变）
  const xs = []; tr.moments.forEach((m, i) => { xs.push(Math.max(+pc(m[0]), i ? xs[i - 1] + 8 : 0)); });
  for (let i = xs.length - 1; i >= 0; i--) xs[i] = Math.min(xs[i], i === xs.length - 1 ? 100 : xs[i + 1] - 8);
  const nodes = tr.moments.map((m, i) => '<span class="l-node' + (m[3] ? ' bad' : '') + '" style="left:' + xs[i].toFixed(2) + '%" data-tip="' + esc(relT(Math.round(m[0] * 10) / 10) + ' · ' + m[1]) + '">' + (i + 1) + '</span>').join('');
  const steps = tr.moments.map((m, i) => '<li class="' + (m[3] ? 'bad' : '') + '"><span class="l-sn mono">' + (i + 1) + '</span><span class="mono l-st">' + relT(Math.round(m[0] * 10) / 10) + '</span><b>' + esc(m[1]) + '</b><span class="l-sd">' + esc(m[2]) + '</span></li>').join('');
  const head = '<div class="card pad l-shead"><div class="row" style="flex-wrap:wrap;gap:8px"><span class="dot" style="background:' + agent(s.a).c + '"></span><span class="eb">' + agent(s.a).name + ' · ' + PJI[s.p].name + ' · ' + (s.d === 120 ? '今天' : mdz(s.d)) + ' ' + hm(s.h, s.mi) + '</span><span class="row" style="gap:4px;margin-left:auto;font-size:12px;color:var(--ink-2)">' + ic(o[0], 14, 'color:' + o[1]) + o[2] + '</span></div>' +
    '<h2 class="serif l-stitle">' + esc(s.title) + '</h2><div class="row l-ins"><span class="aib">' + ic('spark', 11) + 'AI 洞察</span><p class="serif">' + esc(liteInsight(s, tr)) + '</p></div></div>';
  const tl = '<div class="card pad l-tlc"><div class="hd"><div class="grow"><span class="ct">关键步骤</span><span class="cap">' + tr.moments.length + ' 个关键时刻 · 全程 ' + (s.live ? liveMin() + 'm' : dur(T)) + '</span></div>' + liteAdv('sessions', '在 Advance 中回放') + '</div>' +
    '<div class="l-tl" role="img" aria-label="会话时间线：' + esc(tr.moments.map((m) => m[1]).join('、')) + '"><span class="l-rail"></span>' + nodes + '<div class="l-phs">' + phases + '</div></div><ol class="l-steps">' + steps + '</ol></div>';
  return liteBar('会话轨迹', rangeLabel() + ' · 最近 ' + list.length + ' 个会话') +
    '<div class="content" id="content"><div class="lite l-sessions"><div class="sess l-sess"><div class="card l-slist-c"><div class="hd l-slh"><div class="grow"><span class="ct">最近的会话</span></div></div><div class="slist">' + rows + '</div></div>' +
    '<div class="stack">' + head + '<div class="tiles l-tiles l-snums">' + nums + '</div>' + tl + '</div></div></div></div>';
};

/* ---------- 4 优化建议：一句总收益 → 前三条大卡（应用 / 已应用 · 撤销）→ 全部与资源库 ---------- */
PAGES['l-recs'] = () => {
  const all = liteOrder(); const top = all.slice(0, 3);
  const open = top.filter((r) => !S.installed.has(r.id));
  const save = sum(open, (r) => liteSaveH(r.id));
  const hero = '<div class="card pad l-rhero"><span class="eb">优化建议 · 按每月节省时间排序</span>' +
    (open.length ? '<p class="serif l-say">做完这 ' + open.length + ' 件事，每月大约省下</p><div class="row l-big-n"><span class="v mono" data-count="' + save.toFixed(1) + '" data-dec="1">' + f1(save) + '</span><span class="u">小时</span></div>'
      : '<p class="serif l-say">前三条都已应用。7 天后看效果追踪，或在 Advance 里挑下一条。</p>') + '</div>';
  const card = (r, i) => {
    const inst = S.installed.get(r.id);
    const state = inst ? '<span class="tag">' + ic('okc', 12, 'color:var(--good)') + (inst.days >= 7 ? '已应用 · ' + VERDICT[trackStats(r).verdict][0] : '已应用 · 追踪中 ' + inst.days + ' / 7 天') + '</span><button type="button" class="btn gh l-big" data-act="liteRecAdv" data-id="' + r.id + '">查看追踪</button><button type="button" class="btn l-big" data-act="uninstall" data-id="' + r.id + '">' + ic('undo', 13) + '撤销</button>' : liteRecBtn(r);
    return '<div class="card rcard l-rc' + (inst ? ' inst' : '') + '" data-id="' + r.id + '"><span class="l-rn mono" aria-hidden="true">0' + (i + 1) + '</span><div class="col l-rb"><div class="rc-top"><span class="row" style="gap:5px">' + ic(r.icon, 14, 'color:var(--ink-1)') + '<b class="mono">' + r.type + '</b></span><span class="row" style="gap:5px">' + lvlIcon(r.lvl) + LEVELS[r.lvl] + '</span>' + agentDots(r, true) + '</div>' +
      '<div class="rc-title serif">' + esc(r.title) + '</div><div class="rc-why">' + esc(r.why) + '</div>' +
      '<div class="rc-foot"><span class="l-gain"><span class="v mono" data-count="' + liteSaveH(r.id).toFixed(1) + '" data-dec="1">' + f1(liteSaveH(r.id)) + '</span><span class="u">h / 月</span><span class="mono l-g2">' + esc(r.gain) + '</span></span><span style="flex:1"></span>' + state + '</div></div></div>';
  };
  return liteBar('优化建议', all.length + ' 条 · 这里只看最值得做的 3 条') +
    '<div class="content" id="content"><div class="lite l-recs">' + hero + '<div class="stack">' + (top.length ? top.map(card).join('') : empty('没有可见的建议')) + '</div>' +
    liteFoot([['recs', '查看全部 ' + all.length + ' 条建议'], ['library', '资源库']]) + '</div></div>';
};

Object.assign(ACT, {
  liteClear: () => { S.project = null; S.topic = null; S.outcome = null; S.fric = null; S.hour = null; AG.forEach((a) => S.agents.add(a.id)); render(); },
  liteSess: (el) => { const s = BYID[el.dataset.id]; if (!s) return; stopPlay(); S.sess.sel = s.id; S.sess.mode = 'single'; S.sess.cmp = null; S.sess.ph = traj(s).T; renderMain(); },
  litePeriod: (el) => { S.persona.period = el.dataset.v; edOpen('persona'); },
  // 教程 / 交给工坊 / 已安装的追踪都在 Advance：先切版本，再走 A7 原有的入口
  liteRecAdv: (el) => {
    const id = el.dataset.id; const r = RECI[id]; if (!r) return;
    if (S.installed.has(id) || !/教程|交给/.test(r.primary)) { S.recs.sel = id; S.recs.tab = S.installed.has(id) ? 'track' : 'preview'; S.recs.peek = id; S.recs.gone.delete(id); edOpen('recs'); return; }
    if (/教程/.test(r.primary)) { S.recs.sel = id; S.recs.tab = 'tut'; S.recs.peek = id; edOpen('recs'); return; }
    edOpen('recs'); ACT.recToStudio(el);
  }
});
