/* ============ A3 sessions & trajectory ============
 * 轨迹时间线建在 VZ（36-vizkit.js）的 timeline / minimap / playhead 原语上：总览条（刷子视窗）+ 主时间线（关键时刻徽章、阶段带、
 * 「你」泳道、Agent 中性块、工具密度带 ↔ 四条展开泳道、上下文面积 + 80% 阈值线、顶部相对时间轴 + 底部绝对时刻轴）+ 右侧事件检视。
 * 保持的接口：S.sess.{ph, playing, zoom, axis}、startPlay() / stopPlay() / updTimeline()、#tlBox（effects 测试依赖）。
 * 新增状态：S.sess.view（当前视窗 [a, b] 分钟，null = 全程）、tools（工具泳道 'open' | 'closed' | null = 按像素密度自动）、
 * ev / evd（检视面板选中的事件 id / 数据）、brush（刷选区间）、limit（会话列表已渲染行数）、turn（对比模式下一次点选是 A 还是 B）。 */
S.excluded = new Set();
const _base = base;
// eslint-disable-next-line no-func-assign
base = function (s) { return _base(s) && !S.excluded.has(s.id); };
['view', 'tools', 'ev', 'evd', 'brush', 'turn'].forEach((k) => { if (!(k in S.sess)) S.sess[k] = null; });
S.sess.limit = S.sess.limit || 120;
S.sess.last = S.sess.sel;   // 初始播放头（30.8）是刻意停在失败串上的演示状态，首次渲染不重置
const TOOL = ['read', 'edit', 'bash', 'web'];
const TOOL_LBL = { read: '读取 / 搜索', edit: '编辑', bash: '命令', web: '网络' };
const LANE_LBL = { user: '你的消息', reply: 'Agent 回复', read: '读取 / 搜索', edit: '编辑', bash: '命令', web: '网络', sub: '子代理' };
/* 数据钩子：默认值即演示口径；live 模式（92-live-sessions.js）用会话详情 / 搜索 / 对比端点的真实数据覆盖，组件与布局不变 */
const A3H = {
  todayD: () => 120,
  dayLabel: (d) => d === 120 ? '今天 · 10 月 1 日 周四' : d === 119 ? '昨天 · 9 月 30 日 周三' : mdz(d) + ' 周' + WD[wd(d)],
  qMatch: (s, q) => s.title.toLowerCase().includes(q) || PJI[s.p].name.toLowerCase().includes(q) || agent(s.a).name.toLowerCase().includes(q),
  model: (s, ag) => s.a === 'cc' ? 'claude-opus-5-5 · thinking high' : ag.model,
  path: (s) => PJI[s.p].path,
  steps: (s) => Math.round(s.tools * 1.54),
  ctxPeak: (s, tr) => Math.round(Math.max(...tr.ctx.map((c) => c[1]))) + '%',
  tok: (s) => f1(s.tok / 1e6) + 'M',
  mood: (m) => '<span class="mono">' + sgn1(m) + '</span>' + (m < -0.2 ? ' · 偏负面' : m > 0.2 ? ' · 偏正面' : ' · 中性'),
  summary: (s, tr, def) => def,
  inspExtra: () => '',
  insight: null,   // (s, corrN, errN) → { text, actions: [{ label, id, act? }] }；null = 演示文案
  phasePct: null   // (x, side) → [[label, pct]]；null = 按 traj 阶段计算
};
function spreadTimes(r, a, b, n) { const o = []; for (let i = 0; i < n; i++) o.push(a + (b - a) * ((i + r() * 0.8) / n)); return o; }
function traj(s) {
  if (s._traj) return s._traj;
  const r = rng(hash(s.id)); const T = Math.max(4, s.dur);
  const ev = [];
  const add = (lane, t, w, info) => ev.push(Object.assign({ lane, t, w: w || 0 }, info));
  let phases, users, ctx, moments;
  if (s.featured) {
    phases = [[0, 6, '探索'], [6, 9, '规划'], [9, 24, '实施'], [24, 36, '部署'], [36, 42, '验证']];
    users = [[0.1, 0.3, false, '部署到自定义域名，配 HTTPS，并验证'], [3.2, 0.1, false, '先看看现在的构建配置'], [17.1, -0.6, true, '不要用 Vercel，用 Cloudflare'], [24.4, 0.2, false, '好，继续'], [31.0, -0.4, true, '别重复试了，先检查认证'], [37.9, 0.3, false, '验证一下 https 和 www 跳转'], [41.6, 0.7, false, '可以，提交吧']];
    [[0.3, 0.6], [2.0, 0.8], [3.5, 0.5], [5.6, 1.4], [8.2, 0.9], [12.5, 0.6], [15.4, 1.0], [17.4, 0.8], [23.6, 0.7], [27.0, 0.5], [31.2, 1.0], [35.5, 0.6], [38.1, 0.8], [41.0, 0.6]].forEach((x) => add('reply', x[0], x[1], { txt: 'Agent 回复 · ' + Math.round(x[1] * 60) + ' 秒' }));
    const sp = (lane, a, b, n, cmd) => spreadTimes(r, a, b, n).forEach((t) => add(lane, t, 0, { cmd: cmd[Math.floor(r() * cmd.length)] }));
    sp('read', 0.5, 6, 26, ['Read package.json', 'Read wrangler.toml', 'Grep "deploy"', 'Read docs/deploy.md']); sp('read', 9, 14, 10, ['Read src/main.ts', 'Glob src/**/*.ts']); sp('read', 17.5, 19.5, 5, ['Read wrangler.toml']); sp('read', 31.4, 32.4, 3, ['Read ~/.wrangler/config']); sp('read', 9.5, 23, 21, ['Read src/deck.ts', 'Grep "slide"']);
    sp('edit', 9.2, 23.4, 22, ['Edit src/deck.ts', 'Edit index.html', 'Edit vite.config.ts']); sp('edit', 32.2, 34.4, 4, ['Edit wrangler.toml']);
    sp('bash', 1, 5.2, 6, ['git status', 'npm ci']); sp('bash', 13, 16.4, 8, ['npm run build', 'npx vercel --prod']); sp('bash', 19.2, 23.2, 5, ['npm run build']); sp('bash', 24.2, 25.8, 4, ['npx wrangler pages project list']); sp('bash', 32.6, 36, 5, ['npx wrangler pages deploy ./dist']); add('bash', 31.9, 0.1, { cmd: 'npx wrangler login', approval: 'approved', wait: 1.6 }); sp('bash', 36.4, 41.2, 5, ['curl -I https://confluo.fhxgs.cc']);
    sp('web', 4.0, 4.8, 2, ['WebFetch Cloudflare Pages 文档']); sp('web', 36.5, 40.6, 6, ['WebFetch https://confluo.fhxgs.cc']);
    [[26.1, 'bash', 'npx wrangler pages deploy ./dist', 'exit 1 · 未登录 Cloudflare'], [27.4, 'bash', 'npx wrangler pages deploy ./dist', 'exit 1 · 未登录 Cloudflare'], [28.7, 'bash', 'npx wrangler pages deploy ./dist', 'exit 1 · 未登录 Cloudflare'], [30.8, 'bash', 'npx wrangler pages deploy ./dist', 'exit 1 · 未登录 Cloudflare（连续第 4 次）'], [14.9, 'bash', 'npm run build', 'exit 2 · 类型错误'], [34.1, 'bash', 'npx wrangler pages deploy ./dist', 'exit 1 · 项目名不存在'], [12.2, 'edit', 'Edit src/deck.ts', 'old_string 未找到'], [4.9, 'read', 'Read docs/deploy.md', '文件不存在'], [37.2, 'web', 'WebFetch https://www.confluo…', '超时 30 s']].forEach((e) => add(e[1], e[0], 0, { err: true, cmd: e[2], res: e[3] }));
    add('sub', 1.2, 4.6, { txt: 'Explore ×3 并行 · 4.6 分钟' });
    ctx = [[0, 6], [3, 14], [6, 24], [9, 30], [14, 41], [18, 47], [23, 58], [28, 66], [33, 78], [33.6, 31], [37, 38], [42, 44]];
    moments = [[0.1, '你给出目标', '「部署到自定义域名，配 HTTPS，并验证」', false], [15.6, 'Agent 偏离', '选择 Vercel 部署，与项目约定不符', true], [17.1, '你纠偏', '「不要用 Vercel，用 Cloudflare」', true], [26.1, '连续失败', 'wrangler 未登录，同一命令失败 4 次', true], [38.4, '验证通过', '线上 200 · HTTPS 与 www 跳转正常', false]];
  } else {
    const names = s.topic === 'paper' ? ['阅读', '列问题', '修改', '编译', '核对'] : s.topic === 'git' ? ['同步', '审查', '修复', '合并', '清理'] : ['探索', '规划', '实施', '调试', '验证'];
    let pr = [0.14, 0.08, 0.38, 0.26, 0.14].map((x) => x * (0.7 + r() * 0.6)); const ps = pr.reduce((a, b) => a + b, 0); pr = pr.map((x) => x / ps);
    let acc = 0; phases = pr.map((x, i) => { const a = acc; acc += x * T; return [a, acc, names[i]]; });
    const ut = [0.1].concat(spreadTimes(r, T * 0.04, T * 0.98, Math.max(0, s.msgs - 1))).sort((a, b) => a - b);
    const corrIdx = new Set(); for (let k = 0; k < s.corr && k < ut.length - 1; k++) corrIdx.add(1 + Math.floor(r() * (ut.length - 1)));
    const sayings = { ok: ['继续', '好的，下一步', '先看看现在的进度', '可以'], bad: QUOTES.neg };
    users = ut.map((t, i) => { const c = corrIdx.has(i); const m = clamp(s.mood + (c ? -0.55 : 0.1) + (r() - 0.5) * 0.3, -1, 1); return [t, m, c, i === 0 ? s.title : c ? sayings.bad[Math.floor(r() * sayings.bad.length)].replace(/[「」]/g, '') : sayings.ok[Math.floor(r() * sayings.ok.length)]]; });
    ut.forEach((t) => add('reply', Math.min(T - 0.3, t + 0.2), 0.3 + r() * 0.9, { txt: 'Agent 回复' }));
    const nE = Math.min(s.errors, 300); const nW = s.tools >= 40 ? 1 + (Math.abs(hash(s.id)) % 2) : 0; const nT = Math.max(0, Math.min(s.tools, 1500) - nE - nW);
    const P = PJI[s.p]; const toolCmds = TOOLS.find((x) => x[0] === 'Bash')[5];
    const laneOf = () => { const x = r(); return x < 0.3 ? 'read' : x < 0.52 ? 'edit' : x < 0.92 ? 'bash' : 'web'; };
    const pickT = (lane) => { const ph = lane === 'read' ? (r() < 0.6 ? 0 : 2) : lane === 'edit' ? (r() < 0.75 ? 2 : 3) : lane === 'web' ? 4 : 2 + Math.floor(r() * 3); const a = phases[ph][0], b = phases[ph][1]; return a + (b - a) * r(); };
    for (let i = 0; i < nT; i++) { const lane = laneOf(); add(lane, pickT(lane), 0, { cmd: lane === 'bash' ? toolCmds[Math.floor(r() * toolCmds.length)] : lane === 'read' ? 'Read ' + P.name + '/…' : lane === 'edit' ? 'Edit ' + P.name + '/…' : 'WebFetch …' }); }
    const streakAt = phases[3][0] + (phases[3][1] - phases[3][0]) * r() * 0.6;
    for (let i = 0; i < nE; i++) { const inStreak = i < Math.min(4, nE) && nE >= 3; const t = inStreak ? streakAt + i * 0.9 : T * r(); add(inStreak ? 'bash' : laneOf(), Math.min(T - 0.1, t), 0, { err: true, cmd: inStreak ? toolCmds[1] : '…', res: ['exit 1 · 命令不存在', 'exit 128 · 权限被拒', '超时 120 s', '401 未授权'][Math.floor(r() * 4)] }); }
    for (let i = 0; i < nW; i++) { const t = phases[2][0] + (phases[2][1] - phases[2][0]) * r(); add('bash', t, 0.05, { cmd: toolCmds[Math.floor(r() * toolCmds.length)], approval: 'approved', wait: 0.3 + r() * 2 }); }
    const nSub = Math.round(s.tools * 0.05 / 12); for (let i = 0; i < nSub && i < 3; i++) { const t = T * (0.05 + r() * 0.6); add('sub', t, Math.max(0.6, T * 0.08), { txt: 'Task 子代理 · ' + (1 + Math.floor(r() * 3)) + ' 个并行' }); }
    const peak = clamp(18 + T * 1.1 + s.tools * 0.18, 20, 96);
    ctx = [[0, 5], [T * 0.3, peak * 0.45], [T * 0.6, peak * 0.75]];
    if (peak > 76) ctx.push([T * 0.78, 78], [T * 0.79, 31], [T, 31 + (peak - 78) * 0.6]); else ctx.push([T, peak]);
    moments = [[0.1, '你给出目标', '「' + s.title + '」', false]];
    users.forEach((u) => { if (u[2]) moments.push([u[0], '你纠偏', '「' + u[3] + '」', true]); });
    if (nE >= 3) moments.push([streakAt, '连续失败', '同一命令失败 ' + Math.min(4, nE) + ' 次', true]);
    moments.push([T - 0.3, s.out === 'ok' ? (s.verify ? '验证通过' : '完成') : s.out === 'fail' ? '放弃' : s.out === 'live' ? '进行中' : '部分完成', s.out === 'ok' ? '会话结束' : '会话未完全达成目标', s.out !== 'ok' && s.out !== 'live']);
    moments.sort((a, b) => a[0] - b[0]); moments = moments.slice(0, 6);
  }
  users.forEach((u, i) => add('user', u[0], 0, { mood: u[1], corr: u[2], txt: u[3], idx: i }));
  ev.sort((a, b) => a.t - b.t);
  ev.forEach((e, i) => { e.id = 'e' + i; });   // 稳定 id：检视面板选中、VZ selected 描边都按它找
  // 上下文自动压缩：相邻采样下降 > 20 个百分点
  const comps = ctx.map((c, i) => i > 0 && c[1] < ctx[i - 1][1] - 20 ? i : -1).filter((i) => i > 0);
  s._traj = { T: s.featured ? 42 : T, ev, phases, ctx, moments, users, comps };
  return s._traj;
}
// 会话列表口径（评审 BUG-02 / 48）：所有会话（含今天与运行中）都过 Agent / 来源 / 项目 / 附加筛选；被「不计入分析」的会话仍可浏览并单独恢复（BUG-19）
function sessOk(s) { return sourceEnabled(s) && S.agents.has(s.a) && (!S.project || s.p === S.project) && (!S.topic || s.topic === S.topic) && (!S.outcome || s.out === S.outcome) && (!S.fric || s.fric === S.fric) && (S.hour == null || s.h === S.hour); }
function sessList() {
  const q = S.sess.q.trim().toLowerCase();
  const w = win(S.range);
  return ALL.filter((s) => (s.d === A3H.todayD() || (s.d >= w[0] && s.d <= w[1])) && sessOk(s) && (!q || A3H.qMatch(s, q))).sort((a, b) => (b.d - a.d) || (b.h - a.h) || (b.mi - a.mi));
}
function barcode(s, w) {
  const r = rng(hash(s.id + 'b')); const n = Math.min(s.tools, 90); const f = s.live ? 0.62 : 1;
  let d = '', e = '';
  for (let i = 0; i < n; i++) d += 'M' + (r() * w * f).toFixed(1) + ' 1V7';
  for (let i = 0; i < Math.min(s.errors, 12); i++) e += 'M' + (r() * w * f).toFixed(1) + ' 0V8';
  return '<svg width="100%" height="8" viewBox="0 0 ' + w + ' 8" preserveAspectRatio="none" aria-hidden="true" style="display:block"><path d="' + (d || 'M0 0') + '" stroke="var(--ink-4)" stroke-width="1.4"/><path d="' + (e || 'M0 0') + '" stroke="var(--vz-err)" stroke-width="2"/></svg>';
}
/* ---------- 时间线 spec ---------- */
const liveMin = () => Math.floor((Date.now() - S.live.t0) / 60000);
const absT = (s, t) => { const a = s.h * 60 + s.mi + t; return hm(Math.floor(a / 60) % 24, Math.floor(a % 60)); };
const sgn1 = (v) => (v > 0 ? '+' : '') + f1(v);
const moodColor = (m) => m < -0.2 ? VZ.sem.neg : m > 0.2 ? VZ.sem.pos : 'var(--ink-3)';
const relT = (m) => '+' + (m >= 60 ? Math.floor(m / 60) + 'h' + (Math.round(m % 60) ? String(Math.round(m % 60)).padStart(2, '0') : '') : (Number.isInteger(m) ? m : f1(m)) + 'm');
/* ---------- 「这次会话发生了什么」：只按轨迹里的真实事件统计（规则，不是 AI）。demo 与 live 共用：live 的 traj 由 92 号文件从会话详情映射 ---------- */
// 时长：秒 / 分钟 / 小时，供摘要、检视与悬停说明共用
const spanTxt = (m) => m < 1 ? Math.max(1, Math.round(m * 60)) + ' 秒' : m < 60 ? Math.round(m) + ' 分钟' : Math.floor(m / 60) + ' 小时' + (Math.round(m % 60) ? ' ' + Math.round(m % 60) + ' 分' : '');
// 关键时刻「为什么重要」：按规则名（标签）给出一句人话；未知标签不编造
const MOMENT_WHY = {
  '你给出目标': '会话从这里开始，后面的工作都围绕它',
  '你纠偏': 'Agent 的做法和你的预期不一致；反复出现就值得写进项目规则',
  '连续失败': '同一命令反复失败，时间和 token 花在了重试上',
  '验证通过': '有测试 / 构建成功，可作为完成的证据',
  '上下文压缩': '早先的细节可能被丢掉，之后容易重复或偏离',
  'Agent 偏离': '做法偏离了项目约定，后面通常要你出面纠正',
  '完成': '会话在这里结束', '进行中': '会话还在运行', '放弃': '目标没有达成就结束了', '部分完成': '目标只完成了一部分'
};
function phaseAt(tr, t) { const P = tr.phases; for (let i = 0; i < P.length; i++) if (t >= P[i][0] - 1e-9 && (t < P[i][1] || i === P.length - 1)) return P[i]; return null; }
// 连续失败：同一命令（cmd）按时间相邻地失败 ≥ 3 次，中间夹着别的调用就断开（与后端 moments.failure_streaks 同口径）
function failStreaks(tools) {
  const out = []; let run = [];
  const close = () => { if (run.length >= 3) out.push({ t: run[0].t, t2: run[run.length - 1].t, n: run.length, cmd: run[0].cmd || '', id: run[2].id }); };
  tools.forEach((e) => { if (e.err && run.length && run[run.length - 1].cmd === e.cmd) { run.push(e); return; } close(); run = e.err ? [e] : []; });
  close(); return out;
}
function sessDigest(s, tr) {
  if (tr._dg) return tr._dg;
  const tools = tr.ev.filter((e) => TOOL.includes(e.lane));
  const rows = new Map();
  tr.phases.forEach((p) => { const k = p[2] || '—'; const o = rows.get(k) || { label: k, dur: 0, ranges: [], tools: 0, err: 0, msgs: 0, corr: 0, waitN: 0, wait: 0, cats: {} }; o.dur += p[1] - p[0]; o.ranges.push([p[0], p[1]]); rows.set(k, o); });
  tr.ev.forEach((e) => {
    const p = phaseAt(tr, e.t); const o = p && rows.get(p[2] || '—'); if (!o) return;
    if (TOOL.includes(e.lane)) { o.tools++; o.cats[e.lane] = (o.cats[e.lane] || 0) + 1; if (e.err) o.err++; if (e.wait) { o.waitN++; o.wait += e.wait; } }
    else if (e.lane === 'user') { o.msgs++; if (e.corr) o.corr++; }
  });
  const blk = [];
  failStreaks(tools).forEach((x) => blk.push({ t: x.t, kind: 'err', label: '连续失败', detail: (x.cmd ? x.cmd + ' ' : '') + '连续失败 ' + x.n + ' 次' }));
  tr.ev.forEach((e) => { if (e.lane === 'user' && e.corr) blk.push({ t: e.t, kind: 'corr', label: '你纠偏', detail: e.txt ? '「' + e.txt.slice(0, 40) + (e.txt.length > 40 ? '…' : '') + '」' : '' }); });
  const comps = (tr.marks && tr.marks.length ? tr.marks.map((m) => m.t) : tr.comps.map((i) => tr.ctx[i][0]));
  comps.forEach((t) => blk.push({ t, kind: 'comp', label: '上下文压缩', detail: '早先细节可能丢失' }));
  const waits = tools.filter((e) => e.wait > 0);
  waits.forEach((e) => blk.push({ t: e.t, kind: 'wait', label: '等你批准', detail: (e.cmd ? e.cmd + ' · ' : '') + '等了 ' + spanTxt(e.wait), w: e.wait }));
  tools.filter(refused).forEach((e) => blk.push({ t: e.t, kind: 'deny', label: apprTxt(e.approval), detail: e.cmd || '' }));
  blk.sort((a, b) => a.t - b.t);
  const users = tr.ev.filter((e) => e.lane === 'user');
  const verify = tr.moments.filter((m) => m[1] === '验证通过').pop();
  tr._dg = {
    goal: users.length ? users[0].txt || '' : '', phases: Array.from(rows.values()), blk,
    tools: tools.length, err: tools.filter((e) => e.err).length, msgs: users.length, corr: users.filter((e) => e.corr).length,
    waitN: waits.length, wait: waits.reduce((a, e) => a + e.wait, 0), verify: verify ? verify[2] : ''
  };
  return tr._dg;
}
const BLK_IC = { err: ['alert', 'var(--crit)'], corr: ['undo', 'var(--vz-corr)'], wait: ['clock', 'var(--warn)'], comp: ['collapse', 'var(--ink-2)'], deny: ['xc', 'var(--crit)'] };
function sessDigestCard(s, tr) {
  const o = OUT[s.out] || OUT.ok; const dg = sessDigest(s, tr);
  if (tr.state === 'pending') return '<div class="card pad sd-card" data-lv="pending" aria-busy="true"><div class="hd"><div class="grow"><span class="ct">这次会话发生了什么</span></div></div><div class="cap">正在载入事件…</div></div>';
  if (tr.state === 'error') return '';
  const T = tr.T || 1;
  const rangeTxt = (r) => r.length === 1 ? absT(s, r[0][0]) + '–' + absT(s, r[0][1]) : r.length + ' 段 · ' + absT(s, r[0][0]) + ' 起';
  const cats = (c) => TOOL.filter((k) => c[k]).map((k) => TOOL_LBL[k] + ' ' + c[k]).join(' · ');
  const cell = (v, cls) => '<td class="num' + (v && cls ? ' ' + cls : '') + '">' + (v ? fmt(v) : '<span class="sd-z">0</span>') + '</td>';
  const tbl = dg.phases.length ? '<div class="scroll-x"><table class="tbl sd-tbl"><thead><tr><th>阶段</th><th>时间</th><th class="num">时长</th><th class="num">工具</th><th class="num">失败</th><th class="num">你的消息</th><th class="num" title="Agent 停下来等你批准的次数与时长">审批等待</th></tr></thead><tbody>' +
    dg.phases.map((r) => '<tr><td><b>' + esc(r.label) + '</b><span class="mono sd-rg-n">' + rangeTxt(r.ranges) + '</span></td><td class="mono sd-rg" title="' + esc(r.ranges.map((x) => absT(s, x[0]) + '–' + absT(s, x[1])).join('、')) + '">' + rangeTxt(r.ranges) + '</td><td class="num">' + spanTxt(r.dur) + ' <span class="cap">' + Math.round(r.dur / T * 100) + '%</span></td><td class="num" title="' + esc(cats(r.cats)) + '">' + (r.tools ? fmt(r.tools) : '<span class="sd-z">0</span>') + '</td>' + cell(r.err, 'sd-err') + '<td class="num">' + (r.msgs ? r.msgs + (r.corr ? ' <span class="sd-corr">· ' + r.corr + ' 纠偏</span>' : '') : '<span class="sd-z">0</span>') + '</td><td class="num">' + (r.waitN ? r.waitN + ' 次 <span class="cap">' + spanTxt(r.wait) + '</span>' : '<span class="sd-z">0</span>') + '</td></tr>').join('') + '</tbody></table></div>' : '<div class="cap">这次会话没有可划分的阶段</div>';
  const MAXB = 8;
  const chips = dg.blk.length ? dg.blk.slice(0, MAXB).map((b) => '<button type="button" class="sd-chip" data-act="moment" data-t="' + b.t + '" title="跳到 ' + absT(s, b.t) + '"><span class="sd-ci" style="color:' + BLK_IC[b.kind][1] + '">' + ic(BLK_IC[b.kind][0], 13) + '</span><span class="mono sd-ct">' + absT(s, b.t) + '</span><b>' + b.label + '</b><span class="sd-cd">' + esc(b.detail) + '</span></button>').join('') + (dg.blk.length > MAXB ? '<span class="cap sd-more">还有 ' + (dg.blk.length - MAXB) + ' 处，见下方轨迹</span>' : '') : '<span class="cap">没有连续失败、纠偏、上下文压缩、审批等待或被你拒绝的调用</span>';
  const outTxt = s.live ? '运行中' : o[2];
  const diff = [['工具', dg.tools, s.tools], ['消息', dg.msgs, s.msgs], ['失败', dg.err, s.errors]].filter((x) => x[2] != null && x[1] !== x[2]).map((x) => x[0]);
  const sub = diff.length ? '<span class="cap sd-basis" title="摘要只统计这条轨迹里载入的事件；页头数字来自整段会话（含子代理内部调用、未载入轨迹的记录与另一套错误口径），两者可能不同">按轨迹事件统计 · ' + diff.join('、') + '数与页头口径不同</span>' : '<span class="cap">按事件规则统计</span>';
  return '<div class="card pad sd-card"><div class="hd"><div class="grow"><span class="ct">这次会话发生了什么</span>' + sub + '</div></div>' +
    '<div class="sd-kv"><span class="k">目标</span><span class="v sd-goal" title="' + esc(dg.goal) + '">' + (dg.goal ? '「' + esc(dg.goal.length > 120 ? dg.goal.slice(0, 120) + '…' : dg.goal) + '」' : '<span class="cap">没有记录到你的第一条消息</span>') + '</span></div>' +
    '<div class="sd-kv"><span class="k">过程</span><span class="v">' + spanTxt(T) + ' · 你发了 ' + dg.msgs + ' 条消息' + (dg.corr ? '（' + dg.corr + ' 次纠偏）' : '') + ' · 工具 ' + fmt(dg.tools) + ' 次' + (dg.err ? ' · <span class="sd-err">失败 ' + fmt(dg.err) + ' 次</span>' : ' · 没有失败') + (dg.waitN ? ' · 等你批准 ' + dg.waitN + ' 次，共 ' + spanTxt(dg.wait) : '') + '</span></div>' +
    (dg.phases.length ? '<div class="sd-kv"><span class="k">阶段</span><span class="v sd-phs">' + dg.phases.map((r) => '<span class="sd-ph"><b>' + esc(r.label) + '</b> <span class="num">' + Math.round(r.dur / T * 100) + '%</span>' + (r.err ? ' <span class="sd-err">失败 ' + r.err + '</span>' : '') + (r.waitN ? ' <span class="sd-wt">等你 ' + r.waitN + '</span>' : '') + '</span>').join('<span class="sd-sep" aria-hidden="true">→</span>') + '</span></div>' : '') +
    '<details class="sd-more-ph"' + (S.sess.dgOpen ? ' open' : '') + '><summary class="cap">各阶段明细（时间、工具、失败、你的消息、审批等待）</summary>' + tbl + '</details>' +
    '<div class="sd-kv sd-blk"><span class="k">卡点</span><span class="v sd-chips">' + chips + '</span></div>' +
    '<div class="sd-kv"><span class="k">结果</span><span class="v"><span class="row" style="display:inline-flex;gap:4px;color:' + o[1] + ';font-weight:600">' + ic(o[0], 14) + outTxt + '</span>' + (dg.verify ? ' <span class="cap">· 最后一次验证：' + esc(dg.verify) + '</span>' : '') + '</span></div></div>';
}
function tlExtent(s) { const T = traj(s).T; return [0, s.live ? T * 1.1 : T]; }   // 运行中：右端留 10% 空白
function tlView(s) { return S.sess.view || tlExtent(s); }
// 工具泳道：显式 open / closed，否则按视窗内每个事件可分到的像素自动（≥ 4px 展开为四条）
function tlExpanded(s, pw) { if (S.sess.tools) return S.sess.tools === 'open'; const rg = tlView(s); const n = traj(s).ev.filter((e) => TOOL.includes(e.lane) && e.t >= rg[0] && e.t <= rg[1]).length; return n > 0 && pw / n >= 4; }
function tlLanes(s, expanded, compact) {
  const tr = traj(s); const nT = tr.ev.filter((e) => TOOL.includes(e.lane)).length;
  const L = [{ id: 'user', label: compact ? '你' : '你的消息', h: compact ? 16 : 22 }, { id: 'agent', label: compact ? 'Agent' : 'Agent 回复', h: compact ? 12 : 16, color: 'var(--ink-4)' }];
  if (!compact && tr.ev.some((e) => e.lane === 'sub')) L.push({ id: 'sub', label: '子代理', h: 14, color: 'var(--ink-3)' });
  if (expanded) TOOL.forEach((k) => L.push({ id: k, label: TOOL_LBL[k], h: 16, color: 'var(--ink-3)' }));
  else L.push({ id: 'tool', label: compact ? '工具 ×' + nT : '工具调用 ' + fmt(nT), unit: '次调用', h: compact ? 22 : 28, mode: 'density', color: 'var(--ink-4)' });
  if (!compact) L.push({ id: 'ctx', label: '上下文占用', h: 30 });
  return L;
}
function tlEvents(s, expanded, compact) {
  const hi = S.sess.hi;
  const dim = (e) => !hi ? false : hi === 'err' ? !e.err : hi === 'corr' ? !(e.lane === 'user' && e.corr) : hi === 'user' ? e.lane !== 'user' : hi === 'tools' ? !TOOL.includes(e.lane) : false;
  return traj(s).ev.map((e) => {
    let o = null;
    if (e.lane === 'user') o = { lane: 'user', t: e.t, kind: e.corr ? 'ring' : 'dot', r: compact ? 4 : 5, color: e.corr ? VZ.sem.corr : moodColor(e.mood), label: e.txt, sub: e.mood == null ? '' : '情绪 ' + sgn1(e.mood), detail: e.corr ? '纠偏：你在让 Agent 改方向' : '' };
    else if (e.lane === 'reply') o = { lane: 'agent', t: e.t, t2: e.t + e.w, kind: 'span', label: compact ? '' : e.txt };
    else if (e.lane === 'sub') { if (compact) return null; o = { lane: 'sub', t: e.t, t2: e.t + e.w, kind: 'span', label: e.txt }; }
    else if (TOOL.includes(e.lane)) o = { lane: expanded ? e.lane : 'tool', t: e.t, kind: 'tick', err: !!e.err, label: e.cmd, sub: TOOL_LBL[e.lane], cat: TOOL_LBL[e.lane], detail: e.err ? '失败' + (e.res ? ' · ' + e.res : '') : e.res };
    if (!o) return null; o.id = e.id; o.dim = dim(e); return o;
  }).filter(Boolean).concat(compact ? [] : traj(s).ev.filter((e) => e.wait > 0).map((e) => ({ lane: 'user', t: e.t, t2: e.t + e.wait, kind: 'span', color: 'var(--warn-m)', label: '', sub: '等你批准', id: e.id, detail: '等你批准 ' + spanTxt(e.wait) + (e.cmd ? ' · ' + e.cmd : ''), dim: !!hi })));
}
function tlSpec(s, pw) {
  const tr = traj(s); const expanded = tlExpanded(s, pw); const ext = tlExtent(s);
  return {
    type: 'timeline', title: s.title + ' · 轨迹', tlExpanded: expanded,
    lanes: tlLanes(s, expanded, false), events: tlEvents(s, expanded, false),
    spans: tr.phases.map((p) => ({ t: p[0], t2: p[1], label: p[2] + ' ' + absT(s, p[0]) + '–' + absT(s, p[1]), short: p[2], tip: phaseTip(s, tr, p), inferred: p.inferred != null ? p.inferred : !s.featured })),
    markers: tr.moments.map((m, i) => ({ t: m[0], n: i + 1, label: m[1], alert: m[3] })),
    range: tlView(s), extent: ext, unit: 'min', start: s.h * 60 + s.mi, top: 18, now: s.live ? tr.T : undefined,
    axisMode: S.sess.axis === 'steps' ? 'steps' : 'time', playhead: clamp(S.sess.ph, 0, ext[1]), selected: S.sess.ev, brush: true,
    onPlayhead: (t) => { if (S.sess.playing) stopPlay(); S.sess.ph = t; tlReadout(s); tlInspect(s); },
    onView: (rg) => tlSetView(rg, 'timeline'),
    onSelect: (i, d) => tlPick(s, d),
    onHover: (i, d) => tlHotMoments(d && d.marker ? d.markers : null),
    onBrush: (r) => { S.sess.brush = r; tlReadout(s); }
  };
}
// 阶段带悬停：名称、时间范围、时长与这段里的工具 / 失败 / 消息（按事件计数，规则推断的阶段注明「推断」）
function phaseTip(s, tr, p) {
  const ev = tr.ev.filter((e) => e.t >= p[0] && e.t < p[1] + (p[1] >= tr.T ? 1e-9 : 0)); const tl = ev.filter((e) => TOOL.includes(e.lane));
  return p[2] + '阶段' + (p.inferred !== false && !s.featured ? '（按事件推断）' : '') + '\n' + absT(s, p[0]) + '–' + absT(s, p[1]) + ' · ' + spanTxt(p[1] - p[0]) + '\n工具 ' + tl.length + ' 次 · 失败 ' + tl.filter((e) => e.err).length + ' 次 · 你的消息 ' + ev.filter((e) => e.lane === 'user').length + ' 条';
}
function ovSpec(s) {
  const tr = traj(s);
  return { type: 'minimap', title: '总览 · ' + s.title, range: tlExtent(s), unit: 'min', start: s.h * 60 + s.mi, axis: false, events: tr.ev.filter((e) => e.lane !== 'reply' && e.lane !== 'sub').map((e) => ({ t: e.t, err: !!e.err, user: e.lane === 'user' })), window: S.sess.view, onView: (rg, meta) => tlSetView(rg, 'minimap', meta) };
}
// 对比模式：A / B 两条紧凑时间线共用同一横轴尺度（B 带刻度），各自独立的 VZ 实例（评审 BUG-13：tooltip 不再串）
function cmpSpec(s, T, axis) {
  const tr = traj(s);
  return { type: 'timeline', title: s.title, lanes: tlLanes(s, false, true), events: tlEvents(s, false, true), spans: tr.phases.map((p) => ({ t: p[0], t2: p[1], label: p[2], inferred: p.inferred != null ? p.inferred : !s.featured })), markers: tr.moments.map((m, i) => ({ t: m[0], n: i + 1, label: m[1], alert: m[3] })), range: [0, T], unit: 'min', start: s.h * 60 + s.mi, axis, zoom: false, top: 4 };
}
/* ---------- 装饰：VZ 不画的两层 —— 上下文面积（10% 强调色 + 1.5px 线 + 80% 阈值虚线 + 压缩标记）与顶部相对时间轴。
   VZ.draw 每次重绘都重置 innerHTML，所以用 MutationObserver 在每次重绘后补画（tlObserve） ---------- */
function tlDecorate(el, s) {
  const inst = VZ._inst.get(el); const svg = el.querySelector('svg.vz-svg'); if (!inst || !inst.model || !inst.model.F || !svg || svg.querySelector('.tl-deco')) return;
  const F = inst.model.F; const tr = traj(s); const L = VZ.laneOf(F.L, 'ctx'); const X = (t) => F.sx(F.pos(t)); let g = '';
  if (L) {
    const y = (v) => VZ.r1(L.y1 - 2 - v / 100 * (L.h - 8));
    const pts = tr.ctx.map((c) => [VZ.r1(X(c[0])), y(c[1])]); const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0] + ' ' + p[1]).join('');
    const id = 'tlc' + (VZ._uid++);
    g += '<clipPath id="' + id + '"><rect x="' + F.x0 + '" y="' + L.y0 + '" width="' + VZ.r1(F.pw) + '" height="' + L.h + '"/></clipPath><g clip-path="url(#' + id + ')">';
    g += '<path class="tl-ctx-area" d="' + path + 'L' + pts[pts.length - 1][0] + ' ' + (L.y1 - 2) + 'L' + pts[0][0] + ' ' + (L.y1 - 2) + 'Z"/><path class="tl-ctx-line" d="' + path + '"/>';
    g += '<line class="tl-ctx-th" x1="' + F.x0 + '" x2="' + VZ.r1(F.x1) + '" y1="' + y(80) + '" y2="' + y(80) + '"/>';
    tr.comps.forEach((i) => { const x = VZ.r1(X(tr.ctx[i][0])); const lbl = '压缩 ' + Math.round(tr.ctx[i - 1][1]) + '% → ' + Math.round(tr.ctx[i][1]) + '%'; const left = x + 6 + VZ.twm(lbl, 10) > F.x1; g += '<g class="tl-ctx-comp"><line x1="' + x + '" x2="' + x + '" y1="' + L.y0 + '" y2="' + (L.y1 - 2) + '"/>' + VZ.txt(left ? x - 4 : x + 4, L.y0 + 9, lbl, { class: 'vz-lbl tl-ctx-lbl', 'text-anchor': left ? 'end' : 'start' }) + '</g>'; });
    g += '</g>' + VZ.txt(F.x0 + 3, y(80) - 3, '80%', { class: 'tl-ctx-tick' });
  }
  if (!F.steps) {   // 顶部相对时间轴：+0、+5m、+10m…（步数模式下底轴已是步号，不再画）
    const [a, b] = F.range; const st = VZ.tickStep(a, b, Math.max(2, Math.floor(F.pw / 90))); let ticks = '';
    for (let m = Math.ceil(a / st) * st; m <= b + 1e-9; m += st) { const x = VZ.r1(X(m)); if (x < F.x0 - 1 || x > F.x1 + 1) continue; ticks += '<line class="tl-rel-tick" x1="' + x + '" x2="' + x + '" y1="13" y2="17"/>' + VZ.txt(clamp(x, F.x0 + 10, F.x1 - 12), 10, relT(+m.toFixed(6)), { class: 'tl-rel', 'text-anchor': 'middle' }); }
    g += '<line class="tl-rel-base" x1="' + F.x0 + '" x2="' + VZ.r1(F.x1) + '" y1="17" y2="17"/>' + ticks;
  }
  svg.insertAdjacentHTML('beforeend', '<g class="tl-deco" pointer-events="none">' + g + '</g>');
}
function tlObserve(el) {
  const inst = VZ._inst.get(el); if (!inst || inst.tlMO) return;
  inst.tlMO = new MutationObserver(() => { const s = BYID[S.sess.sel]; if (s && el.isConnected && el.dataset.deco !== '0') tlDecorate(el, s); });
  inst.tlMO.observe(el, { childList: true });
}
/* ---------- 视窗、缩放、播放头、检视 ---------- */
let OV_RAF = null;
function tlSetView(rg, from, meta) {
  const s = BYID[S.sess.sel]; if (!s) return; const ext = tlExtent(s); const full = ext[1] - ext[0];
  S.sess.view = rg && rg[1] - rg[0] < full - 1e-6 ? [Math.max(ext[0], rg[0]), Math.min(ext[1], rg[1])] : null;
  S.sess.zoom = S.sess.view ? full / (S.sess.view[1] - S.sess.view[0]) : 1;
  const box = $('#tlBox'); const inst = box && VZ._inst.get(box);
  if (inst) {
    const pw = Math.max(200, box.clientWidth - 90); const spec = tlSpec(s, pw);
    if (from !== 'timeline' || spec.tlExpanded !== inst.spec.tlExpanded) {   // ⌘ 滚轮已由 VZ 重绘；只有展开状态变化时才重建
      if (meta && meta.done === false) { if (OV_RAF) cancelAnimationFrame(OV_RAF); OV_RAF = requestAnimationFrame(() => { OV_RAF = null; VZ.mount(box, spec); tlDecorate(box, s); }); } else { VZ.mount(box, spec); tlDecorate(box, s); }
    }
  }
  if (from !== 'minimap') { const ov = $('#tlOv'); const oi = ov && VZ._inst.get(ov); if (oi) { oi.spec.window = S.sess.view; VZ.draw(ov); } }
  tlCtl(); tlReadout(s);
}
function tlSeek(t) {
  const s = BYID[S.sess.sel]; if (!s) return; stopPlay(); S.sess.ph = clamp(t, 0, tlExtent(s)[1]);
  const box = $('#tlBox'); if (box && VZ._inst.get(box) && VZ._inst.get(box).model) VZ.playhead(box, S.sess.ph); else updTimeline();
  tlReadout(s); tlInspect(s); tlMomentsOn(s);
}
function tlPick(s, d) {
  if (!d) return;
  if (d.marker) { S.sess.evd = null; S.sess.ev = null; tlSeek(d.t); return; }
  S.sess.evd = d.bucket ? d : { id: d.id }; S.sess.ev = d.id || null;
  const box = $('#tlBox'); const inst = box && VZ._inst.get(box);
  if (inst) { inst.spec.selected = S.sess.ev; box.querySelectorAll('.vz-sel').forEach((n) => n.classList.remove('vz-sel')); if (S.sess.ev) box.querySelectorAll('.vz-ev[data-i]').forEach((n) => { const it = inst.model.items[+n.dataset.i]; const dd = it && it.datum(); if (dd && dd.id === S.sess.ev) n.classList.add('vz-sel'); }); }
  tlInspect(s);
}
function tlHotMoments(mks) { const ts = mks ? mks.map((m) => m.t) : []; $$('.tl-mom').forEach((b) => b.classList.toggle('hot', ts.includes(+b.dataset.t))); }
function tlMomentsOn(s) { const tr = traj(s); let on = -1; tr.moments.forEach((m, i) => { if (m[0] <= S.sess.ph + 0.01) on = i; }); $$('.tl-mom').forEach((b) => b.classList.toggle('on', +b.dataset.mk === on)); }
function tlCtl() {
  const s = BYID[S.sess.sel]; const box = $('#tlBox'); const inst = box && VZ._inst.get(box);
  const fit = $('[data-act="zoom"][data-v="0"]'); if (fit) fit.classList.toggle('on', !S.sess.view);
  const zl = $('#tlZoom'); if (zl) zl.textContent = S.sess.view ? f1(S.sess.zoom) + '×' : '全程';
  const tb = $('[data-act="tlTools"]'); if (tb && inst) { const x = !!inst.spec.tlExpanded; tb.innerHTML = ic(x ? 'collapse' : 'grid', 13) + (x ? '折叠工具泳道' : '展开工具泳道'); tb.setAttribute('aria-pressed', x); }
  if (s) tlMomentsOn(s);
}
function tlPlayBtn() { const pb = $('[data-act="playToggle"]'); if (pb) pb.innerHTML = ic(S.sess.playing ? 'pause' : 'play', 13) + (S.sess.playing ? '暂停' : '回放'); }
function tlReadout(s) { const r = $('#tlRead'); if (r) r.innerHTML = readout(s); }
function readout(s) {
  const tr = traj(s); const ph = S.sess.ph; const done = tr.ev.filter((e) => e.t <= ph);
  let h = '<span class="mono tl-now">' + absT(s, ph) + '</span><span class="cap">' + (S.sess.playing ? '回放中 · ' : '') + '已发生 ' + done.length + ' / ' + tr.ev.length + ' 个事件 · 失败 ' + done.filter((e) => e.err).length + (phaseAt(tr, ph) ? ' · 处于「' + esc(phaseAt(tr, ph)[2]) + '」阶段' : '') + '</span>';
  if (S.sess.brush) { const [a, b] = S.sess.brush; const x = tr.ev.filter((e) => e.t >= a && e.t <= b); h += '<span class="tag tl-brush">选段 <span class="mono">' + absT(s, a) + '–' + absT(s, b) + '</span> · ' + Math.max(1, Math.round(b - a)) + ' 分钟 · ' + x.filter((e) => TOOL.includes(e.lane)).length + ' 次工具 · ' + x.filter((e) => e.err).length + ' 次失败 · ' + x.filter((e) => e.lane === 'user').length + ' 条消息<button type="button" class="ib" data-act="tlBrushClear" aria-label="清除选段" style="width:16px;height:16px">' + ic('x', 11) + '</button></span>'; }
  if (S.sess.view) h += '<span class="cap">视窗 <span class="mono">' + absT(s, S.sess.view[0]) + '–' + absT(s, S.sess.view[1]) + '</span></span>';
  return h;
}
// 事件检视：选中的事件 / 密度桶，否则播放头处最近一个事件（回放时随播放头走）
function tlInspect(s) {
  const el = $('#tlInsp'); if (!el) return;
  const tr = traj(s); const d = S.sess.evd; let e = null, bucket = null, picked = false;
  if (d && d.bucket) { bucket = d; picked = true; } else if (d && d.id) { e = tr.ev.find((x) => x.id === d.id) || null; picked = !!e; }
  if (!e && !bucket) tr.ev.forEach((x) => { if (x.t <= S.sess.ph + 1e-9) e = x; });
  const key = bucket ? 'b' + bucket.t0 + ':' + bucket.lane : e ? e.id : 'none'; if (el.dataset.key === key && el.dataset.picked === String(picked)) return; el.dataset.key = key; el.dataset.picked = String(picked);
  const row = (k, v, cls) => v == null || v === '' ? '' : '<div class="tl-kv"><span class="k">' + k + '</span><span class="v' + (cls ? ' ' + cls : '') + '">' + v + '</span></div>';
  let body;
  if (bucket) {
    const cats = {}; bucket.events.forEach((x) => { if (x.cat) cats[x.cat] = (cats[x.cat] || 0) + 1; }); const ph0 = phaseAt(tr, bucket.t0);
    body = '<div class="tl-ihd"><span class="mono tl-it">' + absT(s, bucket.t0) + (bucket.t1 > bucket.t0 ? ' – ' + absT(s, bucket.t1) : '') + '</span><span class="cap">这一小段的工具调用</span></div>' + row('阶段', ph0 ? esc(ph0[2]) : '') + row('调用', bucket.n + ' 次') + row('类别', Object.keys(cats).sort((a, b) => cats[b] - cats[a]).map((k) => k + ' ' + cats[k]).join(' · ')) + row('失败', bucket.err ? '<b style="color:var(--crit)">' + bucket.err + ' 次</b>' : '0') +
      '<ul class="tl-blist">' + bucket.events.slice(0, 8).map((x) => '<li class="mono' + (x.err ? ' err' : '') + '">' + esc(x.label || '') + (x.err && x.detail ? ' <span class="cap">· ' + esc(x.detail) + '</span>' : '') + '</li>').join('') + (bucket.events.length > 8 ? '<li class="cap">… 还有 ' + (bucket.events.length - 8) + ' 条</li>' : '') + '</ul>' +
      '<div class="row tl-ibtn"><button type="button" class="btn sm" data-act="tlZoomTo" data-a="' + bucket.t0 + '" data-b="' + bucket.t1 + '">放大到这一段</button><button type="button" class="btn sm gh" data-act="tlClear">清除选中</button></div>';
  } else if (!e) body = '<div class="cap" style="padding:8px 0">把播放头拖到任意位置，或点一个事件</div>';
  else {
    const res = e.err ? '<b style="color:var(--crit)">失败</b>' + (e.res ? ' · ' + esc(e.res) : '') : e.lane === 'user' ? (e.corr ? '<b style="color:var(--vz-corr)">纠偏</b>' : '正常') : (e.w ? '完成' : '成功');
    const ph0 = phaseAt(tr, e.t); const idx = tr.ev.indexOf(e);
    body = '<div class="tl-ihd"><span class="mono tl-it">' + absT(s, e.t) + '</span><span class="cap">' + (picked ? '选中' : '播放头停在这里') + ' · ' + LANE_LBL[e.lane] + '</span></div>' +
      row(e.lane === 'user' ? '原文' : e.cmd ? '调用' : '内容', esc(e.cmd || e.txt || ''), e.cmd ? 'mono' : '') + row('结果', res) + (e.w ? row('耗时', spanTxt(e.w)) : '') + (e.wait ? row('审批', '<b style="color:var(--warn)">等你批准 ' + spanTxt(e.wait) + '</b>' + (e.approval ? ' · ' + esc(apprTxt(e.approval)) : '')) : e.approval ? row('审批', refused(e) ? '<b style="color:var(--crit)">' + esc(apprTxt(e.approval)) + '</b>' : esc(apprTxt(e.approval))) : '') + (e.lane === 'user' ? row('情绪', e.mood == null ? '<span class="mono">—</span>' : A3H.mood(e.mood)) : '') +
      row('为什么', evWhy(tr, e)) + row('位置', (ph0 ? esc(ph0[2]) + '阶段 · ' : '') + '开始后 ' + relT(Math.round(e.t)).slice(1) + ' · 第 ' + fmt(idx + 1) + ' / ' + fmt(tr.ev.length) + ' 个事件') +
      '<div class="row tl-ibtn"><div class="seg" role="group" aria-label="逐事件"><button type="button" data-act="tlStep" data-v="-1" aria-label="上一个事件">' + ic('chev', 12, 'transform:rotate(90deg)') + '</button><button type="button" data-act="tlStep" data-v="1" aria-label="下一个事件">' + ic('chevr', 12) + '</button></div>' + A3H.inspExtra(s, e) + '<button type="button" class="btn sm gh" data-act="tlOpenLog">在原始日志中打开</button>' + (picked ? '<button type="button" class="btn sm gh" data-act="tlClear">清除</button>' : '') + '</div>';
  }
  el.innerHTML = '<div class="eb">事件检视</div>' + body;
}
// 审批决定：拒绝一侧与后端 orbit_data.reduce._REFUSED 同口径；连接器原样透传的 approved_for_session 等也要译成人话
const APPROVAL = { approved: '你批准了', approve: '你批准了', allow: '你批准了', allowed: '你批准了', accepted: '你批准了', approved_for_session: '你批准了（本会话内不再询问）', denied: '你拒绝了', deny: '你拒绝了', rejected: '你拒绝了', reject: '你拒绝了', declined: '你拒绝了', abort: '你中止了', cancelled: '你取消了' };
const APPROVAL_REFUSED = new Set(['denied', 'deny', 'rejected', 'reject', 'abort', 'cancelled', 'declined']);
const refused = (e) => !!e.approval && APPROVAL_REFUSED.has(String(e.approval).toLowerCase());
const apprTxt = (a) => APPROVAL[String(a).toLowerCase()] || a;
// 事件检视「为什么」：只说这一条事件在规则上意味着什么（失败串、纠偏、审批等待），普通事件不写
function evWhy(tr, e) {
  if (e.err && TOOL.includes(e.lane)) {
    const tools = tr.ev.filter((x) => TOOL.includes(x.lane)); let k = tools.indexOf(e); let n = 0; while (k >= 0 && tools[k].err && tools[k].cmd === e.cmd) { n++; k--; }
    return n >= 2 ? '同一命令连续第 ' + n + ' 次失败' + (n >= 3 ? '，已算作卡点' : '') : '这次调用没成功，Agent 通常会重试或换个做法';
  }
  if (e.lane === 'user' && e.corr) return '你在纠正 Agent 的方向；同类纠偏反复出现时值得写进规则';
  if (e.lane === 'user' && e.idx === 0) return '你给出的目标，会话从这里开始';
  if (e.wait) return 'Agent 停下来等你批准，这段时间没有进展';
  return '';
}
/* ---------- 回放：8 秒走完全程（从当前播放头续播则按剩余比例缩短）；每帧只移动播放头（VZ.playhead），不重绘 ---------- */
let PLAY = null;
function tlFrame(playing) {
  const box = $('#tlBox'); const s = BYID[S.sess.sel]; if (!box || !s) return;
  const inst = VZ._inst.get(box); if (inst && inst.model) VZ.playhead(box, S.sess.ph, { playing }); else updTimeline();
  tlReadout(s); tlInspect(s); tlMomentsOn(s);
}
function stopPlay() { if (PLAY) cancelAnimationFrame(PLAY); PLAY = null; const was = S.sess.playing; S.sess.playing = false; if (was) { tlFrame(false); tlPlayBtn(); } }
function startPlay() {
  const s = BYID[S.sess.sel]; if (!s) return; const T = traj(s).T;
  if (S.sess.ph >= T - 0.05) S.sess.ph = 0;
  S.sess.playing = true; const t0 = performance.now(); const ph0 = S.sess.ph; const dur = 8000 * (1 - ph0 / T);
  const tick = (now) => {
    if (S.route !== 'sessions' || !$('#tlBox')) { stopPlay(); return; }   // 离开页面或切换视图时结束回放（评审 BUG-16）
    const k = Math.min(1, (now - t0) / Math.max(1, dur)); S.sess.ph = ph0 + (T - ph0) * k;
    if (k < 1 && S.sess.playing) { tlFrame(true); PLAY = requestAnimationFrame(tick); } else { S.sess.playing = false; PLAY = null; updTimeline(); }
  };
  PLAY = requestAnimationFrame(tick); tlFrame(true); tlPlayBtn();
}
function updTimeline() {
  const box = $('#tlBox'); const s = BYID[S.sess.sel]; if (!box || !s) return;
  const ext = tlExtent(s); if (S.sess.view && (S.sess.view[1] > ext[1] + 1e-6 || S.sess.view[0] < 0)) { S.sess.view = null; S.sess.zoom = 1; }
  const pw = Math.max(200, box.clientWidth - 90); const spec = tlSpec(s, pw);
  VZ.mount(box, spec); tlObserve(box); tlDecorate(box, s);
  const ov = $('#tlOv'); if (ov) { const labW = Math.min(120, Math.ceil(Math.max(...spec.lanes.map((l) => VZ.tw(l.label || '', 11))) + 12)); ov.style.marginLeft = (labW - 2) + 'px'; ov.style.marginRight = '2px'; VZ.mount(ov, ovSpec(s)); }
  tlReadout(s); tlInspect(s); tlPlayBtn(); tlCtl();
}
/* ---------- 列表 ---------- */
function sessRows(list) {
  let lastDay = null;
  const rows = list.slice(0, S.sess.limit).map((x) => {
    let h = '';
    if (x.d !== lastDay) { lastDay = x.d; h += '<div class="dayh">' + A3H.dayLabel(x.d) + '</div>'; }
    const o = OUT[x.out] || OUT.ok;
    const isSel = x.id === S.sess.sel, isCmp = x.id === S.sess.cmp;
    return h + '<button type="button" class="srow' + (isSel || isCmp ? ' sel' : '') + '" data-act="pickSession" data-id="' + x.id + '" aria-pressed="' + (isSel || isCmp) + '"><span class="row" style="width:100%"><span class="dot' + (x.live ? ' live' : '') + '" style="background:' + agent(x.a).c + '"></span><span class="t">' + esc(x.title) + '</span>' + (S.sess.mode === 'cmp' && (isSel || isCmp) ? '<span class="bdg">' + (isSel ? 'A' : 'B') + '</span>' : '') + (S.excluded.has(x.id) ? '<span class="tag" style="height:16px;font-size:10px">不计入</span>' : '') + ic(o[0], 14, 'color:' + o[1]) + '</span><span class="m">' + PJI[x.p].name + ' · ' + hm(x.h, x.mi) + ' · ' + (x.live ? '运行中 ' + liveMin() + 'm' : dur(x.dur)) + ' · ' + x.tools + ' 工具' + (x.corr ? ' · ' + x.corr + ' 纠偏' : '') + '</span><span style="padding-left:16px;width:100%">' + barcode(x, 280) + '</span></button>';
  }).join('');
  // 截断提示（评审 BUG-05）：声明了多少、渲染了多少，一键加载更多
  const more = list.length > S.sess.limit ? '<button type="button" class="tl-more" data-act="sessLoadMore">已显示前 ' + S.sess.limit + ' 个 · 还有 ' + (list.length - S.sess.limit) + ' 个<b>加载更多</b></button>' : list.length > 120 ? '<div class="cap tl-more-end">已显示全部 ' + list.length + ' 个会话</div>' : '';
  return (rows || '<div class="cap" style="padding:20px">没有匹配的会话。试试放宽筛选。</div>') + more;
}
// 列表头只给计数（完整口径在页头 meta 与 title 提示里），避免与页头重复一整句
function sessCountShort(list) { const w = win(S.range); const inWin = list.filter((s) => s.d >= w[0] && s.d <= w[1]).length; const excl = list.filter((s) => S.excluded.has(s.id)).length; return inWin + ' 个会话' + (list.length > inWin ? ' · 今天 +' + (list.length - inWin) : '') + (excl ? ' · ' + excl + ' 个不计入' : ''); }
function sessCount(list) {
  const w = win(S.range); const inWin = list.filter((s) => s.d >= w[0] && s.d <= w[1]).length; const today = list.length - inWin; const live = list.filter((s) => s.live).length; const excl = list.filter((s) => S.excluded.has(s.id)).length;
  return inWin + ' 个会话 · ' + rangeLabel() + (today ? ' · 今天 ' + today + ' 个' : '') + (live ? '（' + live + ' 个运行中）' : '') + (excl ? ' · ' + excl + ' 个不计入分析' : '');
}
// 搜索 / 加载更多只重绘列表与计数，不重建输入框（评审 BUG-12：不打断输入法组字）；选中项被筛掉时才整页重绘
function updSessList() {
  const list = sessList(); const sl = $('#slist'); const sc = $('#sessCount');
  const selOk = S.sess.sel && list.some((x) => x.id === S.sess.sel);
  if (!sl || (list.length && !selOk) || (!list.length && S.sess.sel)) { const n0 = $('#sessQ'); const pos = n0 ? n0.selectionStart : null; renderMain(); const n = $('#sessQ'); if (n && n0) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } } return; }
  sl.innerHTML = sessRows(list); if (sc) { sc.textContent = sessCountShort(list); sc.title = sessCount(list); }
}
// 单个模式下点选会话：只换右侧详情并切换列表行的 .sel，不重建整页（上千行的列表不必重新解析）。页面 HTML 仍由
// PAGES.sessions()（含 live 包装）生成，取出末尾的详情栏；结构对不上或处于对比模式时返回 false，由调用方整页渲染。
const SESS_DET_OPEN = '<div class="stack" style="min-width:0">', SESS_DET_CLOSE = '</div></div></div>';
function sessPickPartial() {
  if (S.route !== 'sessions' || S.sess.mode === 'cmp') return false;
  const m = $('#main'); const host = m && m.querySelector('.sess > .stack'); const sl = $('#slist');
  if (!host || !sl) return false;
  const html = PAGES.sessions(); const i = html.lastIndexOf(SESS_DET_OPEN);
  if (i < 0 || html.slice(-SESS_DET_CLOSE.length) !== SESS_DET_CLOSE || !sl.querySelector('[data-act="pickSession"][data-id="' + S.sess.sel + '"]')) return false;
  host.innerHTML = html.slice(i + SESS_DET_OPEN.length, html.length - SESS_DET_CLOSE.length);
  sl.querySelectorAll('.srow').forEach((b) => { const on = b.dataset.id === S.sess.sel || b.dataset.id === S.sess.cmp; b.classList.toggle('sel', on); b.setAttribute('aria-pressed', String(on)); });
  if (PAGES.sessions.after) PAGES.sessions.after();
  RENDER_HOOKS.forEach((fn) => { try { fn(m, false); } catch (e) { console.error(e); } });
  paneSync();   // the new session's detail starts at the top of its pane (88-panes.js)
  if (window.__lvRendered) window.__lvRendered();
  return true;
}
/* ---------- 页面 ---------- */
// 启示卡（live）：服务端文案 + 动作按钮，沿用演示的 tl-ai 段落与按钮行
function sessInsightLive(x) {
  const acts = (x && x.actions) || [];
  return '<p class="tl-ai">' + esc((x && x.text) || '暂无启示') + '</p><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:auto">' + acts.map((a, i) => '<button type="button" class="btn sm' + (i ? '' : ' p') + '" data-act="' + (a.act || 'install') + '" data-id="' + esc(a.id || '') + '">' + esc(a.label) + '</button>').join('') + '<button type="button" class="btn sm gh" data-act="inaccurate">不准确</button></div>';
}
PAGES.sessions = () => {
  const list = sessList();
  const s = list.find((x) => x.id === S.sess.sel) || list[0];
  S.sess.sel = s ? s.id : null;
  if (S.sess.limit < 120) S.sess.limit = 120;
  if (!list.some((x) => x.id === S.sess.cmp) || S.sess.cmp === S.sess.sel) S.sess.cmp = null;
  // 从其他入口（命令面板、A2 指纹、菜单栏面板）切到另一个会话：播放头回到末尾、视窗复位、停止回放（评审 BUG-15 / 16）
  if (S.sess.sel !== S.sess.last) { stopPlay(); S.sess.last = S.sess.sel; if (s) { S.sess.ph = traj(s).T; S.sess.view = null; S.sess.zoom = 1; S.sess.ev = null; S.sess.evd = null; S.sess.brush = null; S.sess.hi = null; } }
  const right = '<div class="seg" role="group" aria-label="视图模式"><button type="button" data-act="sessMode" data-v="single" class="' + (S.sess.mode === 'single' ? 'on' : '') + '">单个</button><button type="button" data-act="sessMode" data-v="cmp" class="' + (S.sess.mode === 'cmp' ? 'on' : '') + '">对比</button></div><button type="button" class="btn" data-act="playToggle">' + ic(S.sess.playing ? 'pause' : 'play', 13) + (S.sess.playing ? '暂停' : '回放') + '</button><button type="button" class="btn ai" data-act="ask" data-ctx="session">' + ic('spark', 14) + '让 Agent 复盘</button>';
  const listCard = '<div class="card" style="overflow:hidden"><div class="sl-top"><label class="row sl-q">' + ic('search', 14) + '<span class="vh">搜索会话</span><input id="sessQ" type="search" data-in="sessQ" placeholder="搜索标题、项目、Agent…" value="' + esc(S.sess.q) + '" ></label><div class="row cap sl-hd"><span id="sessCount" title="' + esc(sessCount(list)) + '">' + sessCountShort(list) + '</span>' + (S.sess.mode === 'cmp' ? '<span title="依次点选 A、B">下一次点选作为 <b>' + (S.sess.turn === 'B' ? 'B' : 'A') + '</b></span>' : '<span>最新在前</span>') + '</div></div><div class="slist" id="slist">' + sessRows(list) + '</div></div>';
  const meta = sessCount(list);
  if (!s) return tbar('会话轨迹', '', right) + '<div class="content" id="content">' + filterRow() + empty('没有会话') + '</div>';
  const tr = traj(s); const o = OUT[s.out] || OUT.ok; const ag = agent(s.a);
  const errN = tr.ev.filter((e) => e.err).length; const corrN = tr.users.filter((u) => u[2]).length;
  const statBtn = (k, label, v, col) => '<button type="button" data-act="hiStat" data-v="' + k + '" class="' + (S.sess.hi === k ? 'on' : '') + '"' + (k ? ' data-tip="点击在时间轴上高亮"' : '') + '><span class="st-k">' + label + '</span><span class="st-v"' + (col ? ' style="color:' + col + '"' : '') + '>' + v + '</span></button>';
  let detail;
  if (S.sess.mode === 'cmp') {
    const b = list.find((x) => x.id === S.sess.cmp);
    if (!b) detail = empty('对比模式：在左侧列表再选一个会话作为 B（当前 A：' + esc(s.title) + '）');
    else {
      const T = Math.max(traj(s).T, traj(b).T); const sa = stats([s]), sb = stats([b]);
      // 差异列：Δ(B − A) + 百分比 + 方向色（goodDown：越小越好）
      const delta = (va, vb, goodDown, fmt) => { const d = vb - va; if (!d) return '<span class="cap">持平</span>'; const pct = va ? Math.round(d / va * 100) : null; const good = goodDown == null ? null : (d < 0) === goodDown; return '<span class="mono' + (good == null ? '' : good ? ' vz-good' : ' vz-bad') + '">' + (d > 0 ? '+' : '−') + fmt(Math.abs(d)) + (pct != null ? ' · ' + (d > 0 ? '+' : '−') + Math.abs(pct) + '%' : '') + '</span>' + (good == null ? '' : '<span class="cap"> · ' + (good ? 'B 更好' : 'A 更好') + '</span>'); };
      const rowc = (lbl, va, vb, dl) => '<tr><td>' + lbl + '</td><td class="mono" style="text-align:right">' + va + '</td><td class="mono" style="text-align:right">' + vb + '</td><td style="text-align:right;font-size:11px">' + dl + '</td></tr>';
      const phasePct = (x, side) => { const t = traj(x); return (A3H.phasePct ? A3H.phasePct(x, side) : t.phases.map((p) => [p[2], Math.round((p[1] - p[0]) / t.T * 100)])).map((p) => '<span class="tl-ph-i">' + p[0] + ' <span class="mono">' + p[1] + '%</span></span>').join(''); };
      detail = '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">对比</span><span class="cap" title="A、B 横轴对齐到同一时间尺度；B 结束于 ' + absT(b, traj(b).T) + '">同一时间尺度 · ' + Math.round(T) + ' 分钟</span></div><button type="button" class="btn sm" data-act="swapCmp">交换 A / B</button></div>' +
        [['a', s], ['b', b]].map((p) => '<div class="tl-cmp-row"><div class="row tl-cmp-hd"><span class="bdg">' + p[0].toUpperCase() + '</span><span class="dot" style="background:' + agent(p[1].a).c + '"></span><b class="tl-cmp-t" title="' + esc(p[1].title) + '">' + esc(p[1].title) + '</b><span class="cap tl-cmp-m">' + dur(p[1].dur) + ' · ' + p[1].tools + ' 工具 · ' + p[1].errors + ' 失败</span></div><div class="tl-cmp" data-cmp="' + p[0] + '" data-id="' + p[1].id + '"></div></div>').join('') +
        '<div class="scroll-x" style="margin-top:10px"><table class="tbl tl-cmp-tbl"><thead><tr><th>指标</th><th style="text-align:right">A</th><th style="text-align:right">B</th><th style="text-align:right">Δ（B − A）</th></tr></thead><tbody>' + rowc('时长', dur(s.dur), dur(b.dur), delta(s.dur, b.dur, true, (v) => dur(v))) + rowc('你的消息', s.msgs, b.msgs, delta(s.msgs, b.msgs, null, String)) + rowc('工具调用', s.tools, b.tools, delta(s.tools, b.tools, null, String)) + rowc('错误', s.errors, b.errors, delta(s.errors, b.errors, true, String)) + rowc('纠偏', s.corr, b.corr, delta(s.corr, b.corr, true, String)) + rowc('自主比', f1(sa.auto) + '×', f1(sb.auto) + '×', delta(sa.auto, sb.auto, false, (v) => f1(v) + '×')) + '<tr class="tl-ph-row"><td>阶段耗时占比</td><td colspan="3"><div class="tl-ph"><span class="bdg">A</span>' + phasePct(s, 'a') + '</div><div class="tl-ph"><span class="bdg">B</span>' + phasePct(b, 'b') + '</div></td></tr>' + '</tbody></table></div></div>';
    }
  } else {
    const summary = A3H.summary(s, tr, [Math.round(tr.T) + ' 分钟', s.msgs + ' 条消息', s.tools + ' 次工具', corrN ? corrN + ' 次纠偏' : null, errN ? errN + ' 次失败' : null, tr.comps.length ? tr.comps.length + ' 次压缩' : null, s.live ? '运行中' : o[2]].filter(Boolean).join(' · '));
    const ins = A3H.insight ? A3H.insight(s, corrN, errN) : null;   // live：服务端启示；basis 不是模型时标「规则」
    const sw = (st) => '<span class="tl-sw" style="' + st + '"></span>'; const li = (h) => '<span class="tl-li">' + h + '</span>';
    detail = '<div class="card" style="overflow:hidden"><div class="band" style="background:' + ag.t + ';border-top-color:' + ag.c + '"><div class="mono row sb-meta"><span class="dot" style="background:' + ag.c + '"></span><b style="font-family:var(--font-sans);color:var(--ink-2)">' + ag.name + '</b><span>·</span><span>' + A3H.model(s, ag) + '</span><span>·</span><span class="sb-path" title="' + esc(A3H.path(s)) + '">' + esc(A3H.path(s)) + '</span></div><div class="row" style="margin-top:4px;flex-wrap:wrap"><h2 class="serif sb-title">' + esc(s.title) + '</h2><button type="button" class="btn" data-act="resume">' + ic('term', 14) + '在 ' + ag.short + ' 中继续</button><button type="button" class="ib" data-act="sessMore" aria-label="更多操作" style="background:var(--surface);border:1px solid var(--line)">' + ic('more', 16, 'stroke-width:2.6') + '</button></div><div class="row sb-sub"><span class="mono">' + mdz(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + (s.live ? '运行中 ' + liveElapsed() : dur(s.dur)) + '</span><span class="row" style="gap:4px;color:' + o[1] + ';font-weight:600">' + ic(o[0], 14) + o[2] + '</span>' + (corrN ? '<span class="row" style="gap:4px;color:var(--crit);font-weight:600">' + ic('alert', 14) + corrN + ' 次纠偏</span>' : '') + (S.excluded.has(s.id) ? '<span class="tag">不计入分析</span>' : '') + '</div></div>' +
      '<div class="stats7">' + statBtn('user', '你的消息', s.msgs) + statBtn('', 'Agent 步数', A3H.steps(s)) + statBtn('tools', '工具调用', s.tools) + statBtn('err', '错误', s.errors, s.errors ? 'var(--crit)' : '') + statBtn('corr', '纠偏', s.corr, s.corr ? 'var(--crit)' : '') + statBtn('', '上下文峰值', A3H.ctxPeak(s, tr)) + statBtn('', 'Tokens', A3H.tok(s)) + '</div></div>' +
      sessDigestCard(s, tr) + '<div class="card pad tl-card"><div class="hd" style="margin-bottom:6px"><div class="grow"><span class="ct">轨迹</span></div><div class="seg" role="group" aria-label="横轴"><button type="button" data-act="axis" data-v="time" class="' + (S.sess.axis === 'steps' ? '' : 'on') + '">时间</button><button type="button" data-act="axis" data-v="steps" class="' + (S.sess.axis === 'steps' ? 'on' : '') + '">步数</button></div><div class="seg" role="group" aria-label="缩放"><button type="button" data-act="zoom" data-v="-1" aria-label="缩小">−</button><button type="button" data-act="zoom" data-v="1" aria-label="放大">+</button><button type="button" data-act="zoom" data-v="0" class="' + (S.sess.view ? '' : 'on') + '">适应</button></div><span class="cap mono tl-zl" id="tlZoom">' + (S.sess.view ? f1(S.sess.zoom) + '×' : '全程') + '</span><button type="button" class="btn sm gh" data-act="tlTools" aria-pressed="false">' + ic('grid', 13) + '展开工具泳道</button></div>' +
      '<div class="cap tl-sum">' + summary + '</div><div class="tl-grid"><div class="tl-main"><div class="tl-ov" id="tlOv" aria-label="总览条"></div><div class="tl-box" id="tlBox"></div><div class="row tl-read" id="tlRead">' + readout(s) + '</div>' +
      '<div class="tl-legend">' + li('<span class="tl-sw2">' + sw('background:var(--vz-mood-pos)') + sw('background:var(--vz-mood-neg)') + '</span>你的消息（颜色是语气：正面 / 负面）') + li(sw('border-radius:50%;box-shadow:inset 0 0 0 2px var(--vz-corr)') + '你纠偏，让 Agent 改方向') + li(sw('background:var(--warn-m);width:14px;height:8px;border-radius:2px') + '等你批准') + li(sw('background:var(--ink-4);width:14px;height:7px;border-radius:2px') + 'Agent 回复；工具柱越高调用越密') + li(sw('background:var(--vz-err);width:3px;height:11px;border-radius:1px') + '调用失败') + li(sw('background:var(--ink-1);border-radius:50%') + '关键时刻（编号见下方列表）') + li(sw('background:color-mix(in srgb,var(--accent) 14%,transparent);border-top:1.5px solid var(--accent);width:14px;height:8px;border-radius:0') + '上下文占用（虚线 80%，满了会被压缩）') + li(sw('background:var(--sunken);border:1px dashed var(--line);width:14px;height:8px;border-radius:0') + (tr.phases.some((p) => (p.inferred != null ? p.inferred : !s.featured)) ? '阶段（按事件推断，悬停看统计）' : '阶段（悬停看统计）')) + '<span class="tl-hint" data-tip="拖总览条的视窗或 ⌘ 滚轮缩放 · 点击移动播放头 · 拖选统计选段 · Space 回放">' + ic('info', 12) + '<span class="tl-hint-t">⌘ 滚轮缩放 · 拖选统计 · Space 回放</span></span></div></div>' +
      '<aside class="tl-insp" id="tlInsp"></aside></div></div>' +
      '<div class="two tl-two"><div class="card pad"><div class="hd" style="margin-bottom:6px"><div class="grow"><span class="ct">关键时刻</span><span class="cap" title="悬停联动图上徽章 · 点击把播放头跳到这一刻">' + (s.featured ? '语义检测' : '规则检测') + ' · 点击跳转</span></div></div><div class="col" style="gap:2px">' + (tr.moments.length ? tr.moments.map((m, i) => '<button type="button" class="tl-mom" data-act="moment" data-t="' + m[0] + '" data-mk="' + i + '"><span class="n' + (m[3] ? ' alert' : '') + '">' + (i + 1) + '</span><span class="tl-mt"><span class="mono">' + absT(s, m[0]) + '</span><span class="tl-mrel">' + relT(Math.round(m[0])) + '</span></span><span class="tl-mx"><b>' + esc(m[1]) + '</b> ' + esc(m[2]) + (MOMENT_WHY[m[1]] ? '<span class="tl-mw">' + MOMENT_WHY[m[1]] + '</span>' : '') + '</span></button>').join('') : '<div class="cap" style="padding:6px 0">这次会话没有触发关键时刻规则</div>') + '</div></div>' +
      '<div class="card pad col"><div class="row"><span class="ct">这次会话的启示</span>' + (ins && !ins.ai ? '<span class="tag" title="由规则模板按这次会话的事件生成，不是 AI">规则</span>' : '<span class="aib">' + ic('spark', 11) + 'AI</span>') + '</div>' + (ins ? sessInsightLive(ins) : '<p class="tl-ai">' + (s.featured ? '若 AGENTS.md 写明「部署目标：Cloudflare Pages」，可避免第 ② 步的偏离，约省 6 分钟。同一命令连续失败 2 次时，应先检查认证再重试。' : corrN || errN >= 3 ? (corrN ? '本次有 ' + corrN + ' 次纠偏，' : '') + (errN >= 3 ? '出现 ' + errN + ' 次失败，' : '') + '把相关约定写进规则，下次可以少说一次。' : '这次协作很顺：目标清楚、失败少。可以把开场方式记成模板。') + '</p><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:auto"><button type="button" class="btn sm p" data-act="install" data-id="' + (s.featured || s.fric === '方向错误' ? 'deploy-target' : 'acceptance') + '">生成规则</button><button type="button" class="btn sm" data-act="install" data-id="retry-breaker">加 Hook：重复失败提醒</button><button type="button" class="btn sm gh" data-act="inaccurate">不准确</button></div>') + '</div></div>';
  }
  return tbar('会话轨迹', meta, right) + '<div class="content" id="content">' + filterRow() + '<div class="sess">' + listCard + '<div class="stack" style="min-width:0">' + detail + '</div></div></div>';
};
PAGES.sessions.after = () => {
  const q = $('#sessQ');
  if (q && !q.dataset.bound) { q.dataset.bound = '1'; q.addEventListener('compositionstart', () => { q.dataset.ime = '1'; }); q.addEventListener('compositionend', () => { delete q.dataset.ime; ACT.sessQ(q, { isComposing: false }); }); }
  const dgd = $('.sd-more-ph'); if (dgd) dgd.addEventListener('toggle', () => { S.sess.dgOpen = dgd.open; });   // 阶段明细默认折叠，展开状态跨重绘保留
  if (S.sess.mode === 'cmp') { const T = Math.max(...$$('.tl-cmp').map((el) => traj(BYID[el.dataset.id]).T)); $$('.tl-cmp').forEach((el) => { el.dataset.deco = '0'; VZ.mount(el, cmpSpec(BYID[el.dataset.id], T, el.dataset.cmp === 'b')); }); return; }
  const box = $('#tlBox'); if (!box) return;
  updTimeline();
  // 点击空白处移动播放头（拖动是 VZ 的刷选，位移 < 4px 才算点击）；事件 / 徽章 / 手柄的点击由 VZ 的 onSelect 与播放头拖动处理
  let down = null;
  box.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
  box.addEventListener('click', (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    if (e.target.closest('[data-i],.vz-playhead,.vz-marker,.vz-legend')) return;
    const inst = VZ._inst.get(box); const plot = box.querySelector('.vz-plot'); if (!inst || !inst.model || !plot) return;
    const F = inst.model.F; const x = e.clientX - plot.getBoundingClientRect().left; if (x < F.x0 || x > F.x1) return;
    tlSeek(F.inv(x));
  });
  // 关键时刻列表 ⇄ 图上徽章联动
  $$('.tl-mom').forEach((b) => {
    b.addEventListener('mouseenter', () => { const k = b.dataset.mk; $$('#tlBox .vz-marker').forEach((m) => m.classList.toggle('vz-hot', m.dataset.mk.split(',').includes(k))); });
    b.addEventListener('mouseleave', () => $$('#tlBox .vz-marker.vz-hot').forEach((m) => m.classList.remove('vz-hot')));
  });
};
Object.assign(ACT, {
  sessQ: (el, e) => { if ((e && e.isComposing) || el.dataset.ime) return; if (el.value === S.sess.q) return; S.sess.q = el.value; S.sess.limit = 120; updSessList(); },
  sessLoadMore: () => { S.sess.limit += 120; updSessList(); },
  pickSession: (el) => {
    stopPlay(); const id = el.dataset.id;
    if (S.sess.mode === 'cmp') {   // 依次点选 A、B（评审 BUG-14）：第一次替换 A，第二次替换 B，再轮回
      if (id === S.sess.sel || id === S.sess.cmp) return;
      if (S.sess.turn === 'B' || !S.sess.cmp) { S.sess.cmp = id; S.sess.turn = 'A'; } else { S.sess.sel = id; S.sess.turn = 'B'; }
    } else { S.sess.sel = id; const s = BYID[id]; S.sess.ph = s ? traj(s).T : 0; S.sess.hi = null; S.sess.view = null; S.sess.zoom = 1; S.sess.ev = null; S.sess.evd = null; S.sess.brush = null; }
    if (!sessPickPartial()) render();
  },
  sessMode: (el) => { S.sess.mode = el.dataset.v; stopPlay(); S.sess.turn = 'A'; if (S.sess.mode === 'cmp' && !S.sess.cmp) { const l = sessList().filter((x) => x.id !== S.sess.sel && x.p === BYID[S.sess.sel].p); S.sess.cmp = l[0] ? l[0].id : null; } render(); },
  swapCmp: () => { const a = S.sess.sel; S.sess.sel = S.sess.cmp; S.sess.cmp = a; S.sess.last = S.sess.sel; render(); },
  playToggle: () => { if (S.route !== 'sessions') { go('sessions'); } if (S.sess.mode !== 'single') { S.sess.mode = 'single'; render(); } if (S.sess.playing) { stopPlay(); updTimeline(); } else startPlay(); },
  axis: (el) => { S.sess.axis = el.dataset.v; render(); },
  // −/+ 以播放头为锚缩放（1 – 12×）；「适应」回到全程
  zoom: (el) => {
    const v = +el.dataset.v; const s = BYID[S.sess.sel]; if (!s) return;
    if (v === 0) { tlSetView(null, 'ctl'); return; }
    const ext = tlExtent(s); const full = ext[1] - ext[0]; const z = clamp(S.sess.zoom * (v > 0 ? 1.5 : 1 / 1.5), 1, 12); const span = full / z;
    const a = clamp(clamp(S.sess.ph, ext[0], ext[1]) - span / 2, ext[0], ext[1] - span);
    tlSetView(z <= 1.0001 ? null : [a, a + span], 'ctl');
  },
  tlZoomTo: (el) => { const s = BYID[S.sess.sel]; if (!s) return; const ext = tlExtent(s); const a = +el.dataset.a, b = +el.dataset.b; const pad = Math.max(0.5, (b - a) * 0.5, (ext[1] - ext[0]) / 24); tlSetView([Math.max(ext[0], a - pad), Math.min(ext[1], b + pad)], 'ctl'); },
  tlTools: () => { const box = $('#tlBox'); const inst = box && VZ._inst.get(box); const x = inst ? !!inst.spec.tlExpanded : false; S.sess.tools = x ? 'closed' : 'open'; updTimeline(); },
  tlBrushClear: () => { S.sess.brush = null; const box = $('#tlBox'); const inst = box && VZ._inst.get(box); if (inst) { inst.brushRange = null; const r = box.querySelector('.vz-brush'); if (r) r.setAttribute('hidden', ''); } const s = BYID[S.sess.sel]; if (s) tlReadout(s); },
  tlClear: () => { const s = BYID[S.sess.sel]; if (!s) return; S.sess.evd = null; S.sess.ev = null; const box = $('#tlBox'); const inst = box && VZ._inst.get(box); if (inst) { inst.spec.selected = null; box.querySelectorAll('.vz-sel').forEach((n) => n.classList.remove('vz-sel')); } tlInspect(s); },
  tlStep: (el) => {
    const s = BYID[S.sess.sel]; if (!s) return; const tr = traj(s); const dir = +el.dataset.v;
    let i = S.sess.ev ? tr.ev.findIndex((x) => x.id === S.sess.ev) : -1;
    if (i < 0) { tr.ev.forEach((x, k) => { if (x.t <= S.sess.ph + 1e-9) i = k; }); }
    const n = clamp(i + dir, 0, tr.ev.length - 1); const e = tr.ev[n]; if (!e) return;
    tlPick(s, { id: e.id }); tlSeek(e.t);
  },
  tlOpenLog: () => { const s = BYID[S.sess.sel]; if (s) toast('已在原始日志中打开（演示）：' + agent(s.a).path); },
  hiStat: (el) => { const v = el.dataset.v; if (!v) return; S.sess.hi = S.sess.hi === v ? null : v; render(); },
  moment: (el) => { S.sess.evd = null; S.sess.ev = null; tlSeek(+el.dataset.t); },
  resume: () => { const s = BYID[S.sess.sel]; const ag = agent(s.a); const cmd = ag.resume + ' ' + s.id.replace('sess-', ''); openModal(modalHead('在 ' + ag.name + ' 中继续这个会话', '会在终端中打开；Demo 不会执行任何命令') + '<div class="mb col"><div class="row" style="padding:10px 12px;border-radius:9px;background:var(--sunken);border:1px solid var(--line)"><span class="mono code-t" style="flex:1;font-size:12.5px;word-break:break-all">cd ' + esc(PJI[s.p].path) + ' &amp;&amp; ' + esc(cmd) + '</span><button type="button" class="btn sm" data-act="copyCmd" data-v="' + esc('cd "' + PJI[s.p].path.replace('~', '$HOME') + '" && ' + cmd) + '">复制</button></div><p class="cap" style="margin:0">Orbit 只负责打开终端并填入命令，确认前不会运行。</p></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="resumeGo">在终端中打开</button></div>'); },
  resumeGo: () => { closeModal(); toast('已在终端中打开（演示）'); },
  copyCmd: (el) => copyText(el.dataset.v, '命令'),
  sessMore: (el) => { const s = BYID[S.sess.sel]; openDD(el, [{ t: '复制会话 ID', v: () => copyText(s.id, '会话 ID') }, { t: '在 Finder 中显示日志', v: () => toast('已在 Finder 中显示（演示）：' + agent(s.a).path) }, { sep: 1 }, { t: S.excluded.has(s.id) ? '重新计入分析' : '标记为不计入分析', v: () => { if (S.excluded.has(s.id)) S.excluded.delete(s.id); else S.excluded.add(s.id); render(); toast(S.excluded.has(s.id) ? '已从统计中排除这个会话，所有页面已重算；它仍留在列表里，可随时恢复' : '已重新计入分析'); } }], (v) => v()); },
  inaccurate: () => toast('已记录：这条启示不准确。分类器下次会参考')
});
