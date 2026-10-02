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
    sp('read', 0.5, 6, 26, ['Read package.json', 'Read wrangler.toml', 'Grep "deploy"', 'Read docs/deploy.md']); sp('read', 9, 14, 10, ['Read src/main.ts', 'Glob src/**/*.ts']); sp('read', 17.5, 19.5, 5, ['Read wrangler.toml']); sp('read', 31.4, 32.4, 3, ['Read ~/.wrangler/config']);
    sp('edit', 9.2, 23.4, 22, ['Edit src/deck.ts', 'Edit index.html', 'Edit vite.config.ts']); sp('edit', 32.2, 34.4, 4, ['Edit wrangler.toml']);
    sp('bash', 1, 5.2, 6, ['git status', 'npm ci']); sp('bash', 13, 16.4, 8, ['npm run build', 'npx vercel --prod']); sp('bash', 19.2, 23.2, 5, ['npm run build']); sp('bash', 24.2, 25.8, 4, ['npx wrangler pages project list']); sp('bash', 32.4, 36, 6, ['npx wrangler login', 'npx wrangler pages deploy ./dist']); sp('bash', 36.4, 41.2, 5, ['curl -I https://confluo.fhxgs.cc']);
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
    const nT = Math.min(s.tools, 160);
    const P = PJI[s.p]; const toolCmds = TOOLS.find((x) => x[0] === 'Bash')[5];
    const laneOf = () => { const x = r(); return x < 0.3 ? 'read' : x < 0.52 ? 'edit' : x < 0.92 ? 'bash' : 'web'; };
    const pickT = (lane) => { const ph = lane === 'read' ? (r() < 0.6 ? 0 : 2) : lane === 'edit' ? (r() < 0.75 ? 2 : 3) : lane === 'web' ? 4 : 2 + Math.floor(r() * 3); const a = phases[ph][0], b = phases[ph][1]; return a + (b - a) * r(); };
    for (let i = 0; i < nT; i++) { const lane = laneOf(); add(lane, pickT(lane), 0, { cmd: lane === 'bash' ? toolCmds[Math.floor(r() * toolCmds.length)] : lane === 'read' ? 'Read ' + P.name + '/…' : lane === 'edit' ? 'Edit ' + P.name + '/…' : 'WebFetch …' }); }
    const nE = Math.min(s.errors, 24); const streakAt = phases[3][0] + (phases[3][1] - phases[3][0]) * r() * 0.6;
    for (let i = 0; i < nE; i++) { const inStreak = i < Math.min(4, nE) && nE >= 3; const t = inStreak ? streakAt + i * 0.9 : T * r(); add(inStreak ? 'bash' : laneOf(), Math.min(T - 0.1, t), 0, { err: true, cmd: inStreak ? toolCmds[1] : '…', res: ['exit 1 · 命令不存在', 'exit 128 · 权限被拒', '超时 120 s', '401 未授权'][Math.floor(r() * 4)] }); }
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
  return ALL.filter((s) => (s.d === 120 || (s.d >= w[0] && s.d <= w[1])) && sessOk(s) && (!q || s.title.toLowerCase().includes(q) || PJI[s.p].name.toLowerCase().includes(q) || agent(s.a).name.toLowerCase().includes(q))).sort((a, b) => (b.d - a.d) || (b.h - a.h) || (b.mi - a.mi));
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
function tlExtent(s) { const T = traj(s).T; return [0, s.live ? T * 1.1 : T]; }   // 运行中：右端留 10% 空白
function tlView(s) { return S.sess.view || tlExtent(s); }
// 工具泳道：显式 open / closed，否则按视窗内每个事件可分到的像素自动（≥ 4px 展开为四条）
function tlExpanded(s, pw) { if (S.sess.tools) return S.sess.tools === 'open'; const rg = tlView(s); const n = traj(s).ev.filter((e) => TOOL.includes(e.lane) && e.t >= rg[0] && e.t <= rg[1]).length; return n > 0 && pw / n >= 4; }
function tlLanes(s, expanded, compact) {
  const tr = traj(s); const nT = tr.ev.filter((e) => TOOL.includes(e.lane)).length;
  const L = [{ id: 'user', label: '你', h: compact ? 16 : 22 }, { id: 'agent', label: 'Agent', h: compact ? 12 : 16, color: 'var(--ink-4)' }];
  if (!compact && tr.ev.some((e) => e.lane === 'sub')) L.push({ id: 'sub', label: '子代理', h: 14, color: 'var(--ink-3)' });
  if (expanded) TOOL.forEach((k) => L.push({ id: k, label: TOOL_LBL[k], h: 16, color: 'var(--ink-3)' }));
  else L.push({ id: 'tool', label: '工具 ×' + nT, h: compact ? 22 : 28, mode: 'density', color: 'var(--ink-4)' });
  if (!compact) L.push({ id: 'ctx', label: '上下文', h: 30 });
  return L;
}
function tlEvents(s, expanded, compact) {
  const hi = S.sess.hi;
  const dim = (e) => !hi ? false : hi === 'err' ? !e.err : hi === 'corr' ? !(e.lane === 'user' && e.corr) : hi === 'user' ? e.lane !== 'user' : hi === 'tools' ? !TOOL.includes(e.lane) : false;
  return traj(s).ev.map((e) => {
    let o = null;
    if (e.lane === 'user') o = { lane: 'user', t: e.t, kind: e.corr ? 'ring' : 'dot', r: compact ? 4 : 5, color: e.corr ? VZ.sem.corr : moodColor(e.mood), label: e.txt, sub: '情绪 ' + sgn1(e.mood), detail: e.corr ? '纠偏' : '' };
    else if (e.lane === 'reply') o = { lane: 'agent', t: e.t, t2: e.t + e.w, kind: 'span', label: compact ? '' : e.txt };
    else if (e.lane === 'sub') { if (compact) return null; o = { lane: 'sub', t: e.t, t2: e.t + e.w, kind: 'span', label: e.txt }; }
    else if (TOOL.includes(e.lane)) o = { lane: expanded ? e.lane : 'tool', t: e.t, kind: 'tick', err: !!e.err, label: e.cmd, detail: e.res };
    if (!o) return null; o.id = e.id; o.dim = dim(e); return o;
  }).filter(Boolean);
}
function tlSpec(s, pw) {
  const tr = traj(s); const expanded = tlExpanded(s, pw); const ext = tlExtent(s);
  return {
    type: 'timeline', title: s.title + ' · 轨迹', tlExpanded: expanded,
    lanes: tlLanes(s, expanded, false), events: tlEvents(s, expanded, false),
    spans: tr.phases.map((p) => ({ t: p[0], t2: p[1], label: p[2], inferred: !s.featured })),
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
function ovSpec(s) {
  const tr = traj(s);
  return { type: 'minimap', title: '总览 · ' + s.title, range: tlExtent(s), unit: 'min', start: s.h * 60 + s.mi, axis: false, events: tr.ev.filter((e) => e.lane !== 'reply' && e.lane !== 'sub').map((e) => ({ t: e.t, err: !!e.err, user: e.lane === 'user' })), window: S.sess.view, onView: (rg, meta) => tlSetView(rg, 'minimap', meta) };
}
// 对比模式：A / B 两条紧凑时间线共用同一横轴尺度（B 带刻度），各自独立的 VZ 实例（评审 BUG-13：tooltip 不再串）
function cmpSpec(s, T, axis) {
  const tr = traj(s);
  return { type: 'timeline', title: s.title, lanes: tlLanes(s, false, true), events: tlEvents(s, false, true), spans: tr.phases.map((p) => ({ t: p[0], t2: p[1], label: p[2], inferred: !s.featured })), markers: tr.moments.map((m, i) => ({ t: m[0], n: i + 1, label: m[1], alert: m[3] })), range: [0, T], unit: 'min', start: s.h * 60 + s.mi, axis, zoom: false, top: 4 };
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
  let h = '<span class="mono tl-now">' + absT(s, ph) + '</span><span class="cap">' + (S.sess.playing ? '回放中 · ' : '') + '已发生 ' + done.length + ' / ' + tr.ev.length + ' 个事件 · 失败 ' + done.filter((e) => e.err).length + '</span>';
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
    body = '<div class="tl-ihd"><span class="mono tl-it">' + absT(s, bucket.t0) + (bucket.t1 > bucket.t0 ? ' – ' + absT(s, bucket.t1) : '') + '</span><span class="cap">工具密度桶</span></div>' + row('调用', bucket.n + ' 次') + row('失败', bucket.err ? bucket.err + ' 次' : '0') +
      '<ul class="tl-blist">' + bucket.events.slice(0, 8).map((x) => '<li class="mono' + (x.err ? ' err' : '') + '">' + esc(x.label || '') + (x.err && x.detail ? ' <span class="cap">· ' + esc(x.detail) + '</span>' : '') + '</li>').join('') + (bucket.events.length > 8 ? '<li class="cap">… 还有 ' + (bucket.events.length - 8) + ' 条</li>' : '') + '</ul>' +
      '<div class="row tl-ibtn"><button type="button" class="btn sm" data-act="tlZoomTo" data-a="' + bucket.t0 + '" data-b="' + bucket.t1 + '">放大到这一段</button><button type="button" class="btn sm gh" data-act="tlClear">清除选中</button></div>';
  } else if (!e) body = '<div class="cap" style="padding:8px 0">把播放头拖到任意位置，或点一个事件</div>';
  else {
    const res = e.err ? '<b style="color:var(--crit)">失败</b>' + (e.res ? ' · ' + esc(e.res) : '') : e.lane === 'user' ? (e.corr ? '<b style="color:var(--vz-corr)">纠偏</b>' : '正常') : (e.w ? '完成' : '成功');
    body = '<div class="tl-ihd"><span class="mono tl-it">' + absT(s, e.t) + '</span><span class="cap">' + (picked ? '选中' : '播放头处') + ' · ' + LANE_LBL[e.lane] + '</span></div>' +
      row(e.lane === 'user' ? '原文' : e.cmd ? '调用' : '内容', esc(e.cmd || e.txt || ''), e.cmd ? 'mono' : '') + row('结果', res) + (e.w ? row('耗时', Math.round(e.w * 60) + ' 秒') : '') + (e.lane === 'user' ? row('情绪', '<span class="mono">' + sgn1(e.mood) + '</span>' + (e.mood < -0.2 ? ' · 偏负面' : e.mood > 0.2 ? ' · 偏正面' : ' · 中性')) : '') +
      '<div class="row tl-ibtn"><div class="seg" role="group" aria-label="逐事件"><button type="button" data-act="tlStep" data-v="-1" aria-label="上一个事件">' + ic('chev', 12, 'transform:rotate(90deg)') + '</button><button type="button" data-act="tlStep" data-v="1" aria-label="下一个事件">' + ic('chevr', 12) + '</button></div><button type="button" class="btn sm gh" data-act="tlOpenLog">在原始日志中打开</button>' + (picked ? '<button type="button" class="btn sm gh" data-act="tlClear">清除</button>' : '') + '</div>';
  }
  el.innerHTML = '<div class="eb">事件检视</div>' + body;
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
    if (x.d !== lastDay) { lastDay = x.d; h += '<div class="dayh">' + (x.d === 120 ? '今天 · 10 月 1 日 周四' : x.d === 119 ? '昨天 · 9 月 30 日 周三' : mdz(x.d) + ' 周' + WD[wd(x.d)]) + '</div>'; }
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
/* ---------- 页面 ---------- */
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
  if (!s) return tbar('会话与轨迹', '', right) + '<div class="content" id="content">' + filterRow() + empty('没有会话') + '</div>';
  const tr = traj(s); const o = OUT[s.out] || OUT.ok; const ag = agent(s.a);
  const errN = tr.ev.filter((e) => e.err).length; const corrN = tr.users.filter((u) => u[2]).length;
  const peakCtx = Math.round(Math.max(...tr.ctx.map((c) => c[1])));
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
      const phasePct = (x) => { const t = traj(x); return t.phases.map((p) => '<span class="tl-ph-i">' + p[2] + ' <span class="mono">' + Math.round((p[1] - p[0]) / t.T * 100) + '%</span></span>').join(''); };
      detail = '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">对比</span><span class="cap" title="A、B 横轴对齐到同一时间尺度；B 结束于 ' + absT(b, traj(b).T) + '">同一时间尺度 · ' + Math.round(T) + ' 分钟</span></div><button type="button" class="btn sm" data-act="swapCmp">交换 A / B</button></div>' +
        [['a', s], ['b', b]].map((p) => '<div class="tl-cmp-row"><div class="row tl-cmp-hd"><span class="bdg">' + p[0].toUpperCase() + '</span><span class="dot" style="background:' + agent(p[1].a).c + '"></span><b class="tl-cmp-t" title="' + esc(p[1].title) + '">' + esc(p[1].title) + '</b><span class="cap tl-cmp-m">' + dur(p[1].dur) + ' · ' + p[1].tools + ' 工具 · ' + p[1].errors + ' 失败</span></div><div class="tl-cmp" data-cmp="' + p[0] + '" data-id="' + p[1].id + '"></div></div>').join('') +
        '<div class="scroll-x" style="margin-top:10px"><table class="tbl tl-cmp-tbl"><thead><tr><th>指标</th><th style="text-align:right">A</th><th style="text-align:right">B</th><th style="text-align:right">Δ（B − A）</th></tr></thead><tbody>' + rowc('时长', dur(s.dur), dur(b.dur), delta(s.dur, b.dur, true, (v) => dur(v))) + rowc('你的消息', s.msgs, b.msgs, delta(s.msgs, b.msgs, null, String)) + rowc('工具调用', s.tools, b.tools, delta(s.tools, b.tools, null, String)) + rowc('错误', s.errors, b.errors, delta(s.errors, b.errors, true, String)) + rowc('纠偏', s.corr, b.corr, delta(s.corr, b.corr, true, String)) + rowc('自主比', f1(sa.auto) + '×', f1(sb.auto) + '×', delta(sa.auto, sb.auto, false, (v) => f1(v) + '×')) + '<tr class="tl-ph-row"><td>阶段耗时占比</td><td colspan="3"><div class="tl-ph"><span class="bdg">A</span>' + phasePct(s) + '</div><div class="tl-ph"><span class="bdg">B</span>' + phasePct(b) + '</div></td></tr>' + '</tbody></table></div></div>';
    }
  } else {
    const summary = [Math.round(tr.T) + ' 分钟', s.msgs + ' 条消息', s.tools + ' 次工具', corrN ? corrN + ' 次纠偏' : null, errN ? errN + ' 次失败' : null, tr.comps.length ? tr.comps.length + ' 次压缩' : null, s.live ? '运行中' : o[2]].filter(Boolean).join(' · ');
    const sw = (st) => '<span class="tl-sw" style="' + st + '"></span>'; const li = (h) => '<span class="tl-li">' + h + '</span>';
    detail = '<div class="card" style="overflow:hidden"><div class="band" style="background:' + ag.t + ';border-top-color:' + ag.c + '"><div class="mono row sb-meta"><span class="dot" style="background:' + ag.c + '"></span><b style="font-family:var(--sans);color:var(--ink-2)">' + ag.name + '</b><span>·</span><span>' + (s.a === 'cc' ? 'claude-opus-5-5 · thinking high' : ag.model) + '</span><span>·</span><span class="sb-path" title="' + esc(PJI[s.p].path) + '">' + esc(PJI[s.p].path) + '</span></div><div class="row" style="margin-top:4px;flex-wrap:wrap"><h2 class="serif sb-title">' + esc(s.title) + '</h2><button type="button" class="btn" data-act="resume">' + ic('term', 14) + '在 ' + ag.short + ' 中继续</button><button type="button" class="ib" data-act="sessMore" aria-label="更多操作" style="background:var(--surface);border:1px solid var(--line)">' + ic('more', 16, 'stroke-width:2.6') + '</button></div><div class="row sb-sub"><span class="mono">' + mdz(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + (s.live ? '运行中 ' + liveElapsed() : dur(s.dur)) + '</span><span class="row" style="gap:4px;color:' + o[1] + ';font-weight:600">' + ic(o[0], 14) + o[2] + '</span>' + (corrN ? '<span class="row" style="gap:4px;color:var(--crit);font-weight:600">' + ic('alert', 14) + corrN + ' 次纠偏</span>' : '') + (S.excluded.has(s.id) ? '<span class="tag">不计入分析</span>' : '') + '</div></div>' +
      '<div class="stats7">' + statBtn('user', '你的消息', s.msgs) + statBtn('', 'Agent 步数', Math.round(s.tools * 1.54)) + statBtn('tools', '工具调用', s.tools) + statBtn('err', '错误', s.errors, s.errors ? 'var(--crit)' : '') + statBtn('corr', '纠偏', s.corr, s.corr ? 'var(--crit)' : '') + statBtn('', '上下文峰值', peakCtx + '%') + statBtn('', 'Tokens', f1(s.tok / 1e6) + 'M') + '</div></div>' +
      '<div class="card pad tl-card"><div class="hd" style="margin-bottom:6px"><div class="grow"><span class="ct">轨迹</span></div><div class="seg" role="group" aria-label="横轴"><button type="button" data-act="axis" data-v="time" class="' + (S.sess.axis === 'steps' ? '' : 'on') + '">时间</button><button type="button" data-act="axis" data-v="steps" class="' + (S.sess.axis === 'steps' ? 'on' : '') + '">步数</button></div><div class="seg" role="group" aria-label="缩放"><button type="button" data-act="zoom" data-v="-1" aria-label="缩小">−</button><button type="button" data-act="zoom" data-v="1" aria-label="放大">+</button><button type="button" data-act="zoom" data-v="0" class="' + (S.sess.view ? '' : 'on') + '">适应</button></div><span class="cap mono tl-zl" id="tlZoom">' + (S.sess.view ? f1(S.sess.zoom) + '×' : '全程') + '</span><button type="button" class="btn sm gh" data-act="tlTools" aria-pressed="false">' + ic('grid', 13) + '展开工具泳道</button></div>' +
      '<div class="cap tl-sum">' + summary + '</div><div class="tl-grid"><div class="tl-main"><div class="tl-ov" id="tlOv" aria-label="总览条"></div><div class="tl-box" id="tlBox"></div><div class="row tl-read" id="tlRead">' + readout(s) + '</div>' +
      '<div class="tl-legend">' + li('<span class="tl-sw2">' + sw('background:var(--vz-mood-pos)') + sw('background:var(--vz-mood-neg)') + '</span>你的消息 · 情绪正 / 负') + li(sw('border-radius:50%;box-shadow:inset 0 0 0 2px var(--vz-corr)') + '纠偏') + li(sw('background:var(--ink-4);width:14px;height:7px;border-radius:2px') + 'Agent 回复 / 工具密度') + li(sw('background:var(--vz-err);width:3px;height:11px;border-radius:1px') + '失败') + li(sw('background:var(--ink-1);border-radius:50%') + '关键时刻') + li(sw('background:color-mix(in srgb,var(--accent) 14%,transparent);border-top:1.5px solid var(--accent);width:14px;height:8px;border-radius:0') + '上下文（虚线 80%）') + '<span class="tl-hint" data-tip="拖总览条的视窗或 ⌘ 滚轮缩放 · 点击移动播放头 · 拖选统计选段 · Space 回放">' + ic('info', 12) + '<span class="tl-hint-t">⌘ 滚轮缩放 · 拖选统计 · Space 回放</span></span></div></div>' +
      '<aside class="tl-insp" id="tlInsp"></aside></div></div>' +
      '<div class="two tl-two"><div class="card pad"><div class="hd" style="margin-bottom:6px"><div class="grow"><span class="ct">关键时刻</span><span class="cap" title="悬停联动图上徽章 · 点击把播放头跳到这一刻">' + (s.featured ? '语义检测' : '规则检测') + ' · 点击跳转</span></div></div><div class="col" style="gap:2px">' + tr.moments.map((m, i) => '<button type="button" class="tl-mom" data-act="moment" data-t="' + m[0] + '" data-mk="' + i + '"><span class="n' + (m[3] ? ' alert' : '') + '">' + (i + 1) + '</span><span class="mono tl-mt">' + absT(s, m[0]) + '</span><span class="tl-mx"><b>' + esc(m[1]) + '</b> ' + esc(m[2]) + '</span></button>').join('') + '</div></div>' +
      '<div class="card pad col"><div class="row"><span class="ct">这次会话的启示</span><span class="aib">' + ic('spark', 11) + 'AI</span></div><p class="tl-ai">' + (s.featured ? '若 AGENTS.md 写明「部署目标：Cloudflare Pages」，可避免第 ② 步的偏离，约省 6 分钟。同一命令连续失败 2 次时，应先检查认证再重试。' : corrN || errN >= 3 ? (corrN ? '本次有 ' + corrN + ' 次纠偏，' : '') + (errN >= 3 ? '出现 ' + errN + ' 次失败，' : '') + '把相关约定写进规则，下次可以少说一次。' : '这次协作很顺：目标清楚、失败少。可以把开场方式记成模板。') + '</p><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:auto"><button type="button" class="btn sm p" data-act="install" data-id="' + (s.featured || s.fric === '方向错误' ? 'deploy-target' : 'acceptance') + '">生成规则</button><button type="button" class="btn sm" data-act="install" data-id="retry-breaker">加 Hook：重复失败提醒</button><button type="button" class="btn sm gh" data-act="inaccurate">不准确</button></div></div></div>';
  }
  return tbar('会话与轨迹', meta, right) + '<div class="content" id="content">' + filterRow() + '<div class="sess">' + listCard + '<div class="stack" style="min-width:0">' + detail + '</div></div></div>';
};
PAGES.sessions.after = () => {
  const q = $('#sessQ');
  if (q) { q.addEventListener('compositionstart', () => { q.dataset.ime = '1'; }); q.addEventListener('compositionend', () => { delete q.dataset.ime; ACT.sessQ(q, { isComposing: false }); }); }
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
    render();
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
  resume: () => { const s = BYID[S.sess.sel]; const ag = agent(s.a); const cmd = ag.resume + ' ' + s.id.replace('sess-', ''); openModal(modalHead('在 ' + ag.name + ' 中继续这个会话', '会在终端中打开；Demo 不会执行任何命令') + '<div class="mb col"><div class="row" style="padding:10px 12px;border-radius:9px;background:var(--sunken);border:1px solid var(--line)"><span class="mono" style="flex:1;font-size:12.5px;word-break:break-all">cd ' + esc(PJI[s.p].path) + ' &amp;&amp; ' + esc(cmd) + '</span><button type="button" class="btn sm" data-act="copyCmd" data-v="' + esc('cd "' + PJI[s.p].path.replace('~', '$HOME') + '" && ' + cmd) + '">复制</button></div><p class="cap" style="margin:0">Tandem 只负责打开终端并填入命令，确认前不会运行。</p></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="resumeGo">在终端中打开</button></div>'); },
  resumeGo: () => { closeModal(); toast('已在终端中打开（演示）'); },
  copyCmd: (el) => copyText(el.dataset.v, '命令'),
  sessMore: (el) => { const s = BYID[S.sess.sel]; openDD(el, [{ t: '复制会话 ID', v: () => copyText(s.id, '会话 ID') }, { t: '在 Finder 中显示日志', v: () => toast('已在 Finder 中显示（演示）：' + agent(s.a).path) }, { sep: 1 }, { t: S.excluded.has(s.id) ? '重新计入分析' : '标记为不计入分析', v: () => { if (S.excluded.has(s.id)) S.excluded.delete(s.id); else S.excluded.add(s.id); render(); toast(S.excluded.has(s.id) ? '已从统计中排除这个会话，所有页面已重算；它仍留在列表里，可随时恢复' : '已重新计入分析'); } }], (v) => v()); },
  inaccurate: () => toast('已记录：这条启示不准确。分类器下次会参考')
});
