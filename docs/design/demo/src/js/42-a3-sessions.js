/* ============ A3 sessions & trajectory ============ */
S.excluded = new Set();
const _base = base;
// eslint-disable-next-line no-func-assign
base = function (s) { return _base(s) && !S.excluded.has(s.id); };
const LANES = [['moment', '关键时刻', 0, 18], ['phase', '阶段', 24, 20], ['user', '你', 50, 22], ['reply', 'Agent 回复', 76, 14], ['read', '读取 / 搜索', 96, 14], ['edit', '编辑', 116, 14], ['bash', '命令', 136, 18], ['web', '网络', 160, 14], ['sub', '子代理', 182, 16], ['ctx', '上下文', 204, 40], ['mood', '情绪', 250, 30]];
const LANE = {}; LANES.forEach((l) => { LANE[l[0]] = { top: l[2], h: l[3] }; });
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
  s._traj = { T: s.featured ? 42 : T, ev, phases, ctx, moments, users };
  return s._traj;
}
function sessList() {
  const q = S.sess.q.trim().toLowerCase();
  const w = win(S.range);
  return ALL.filter((s) => (s.d === 120 || (s.d >= w[0] && s.d <= w[1])) && (s.d === 120 ? S.agents.has(s.a) && (!S.project || s.p === S.project) : pass(s, {})) && (!q || s.title.toLowerCase().includes(q) || PJI[s.p].name.toLowerCase().includes(q) || agent(s.a).name.toLowerCase().includes(q))).sort((a, b) => (b.d - a.d) || (b.h - a.h) || (b.mi - a.mi));
}
function barcode(s, w) {
  const r = rng(hash(s.id + 'b')); const n = Math.min(s.tools, 90); const f = s.live ? 0.62 : 1;
  let d = '', e = '';
  for (let i = 0; i < n; i++) d += 'M' + (r() * w * f).toFixed(1) + ' 1V7';
  for (let i = 0; i < Math.min(s.errors, 12); i++) e += 'M' + (r() * w * f).toFixed(1) + ' 0V8';
  return '<svg width="100%" height="8" viewBox="0 0 ' + w + ' 8" preserveAspectRatio="none" aria-hidden="true" style="display:block"><path d="' + (d || 'M0 0') + '" stroke="var(--ink-4)" stroke-width="1.4"/><path d="' + (e || 'M0 0') + '" stroke="var(--crit-m)" stroke-width="2"/></svg>';
}
function timelineSVG(s, opt) {
  opt = opt || {};
  const tr = traj(s); const T = opt.T || tr.T;
  const W = Math.round((opt.width || 686) * (opt.zoom || 1)); const compact = !!opt.compact;
  const times = tr.ev.map((e) => e.t);
  const X = S.sess.axis === 'steps' && !compact ? (t) => { if (!times.length) return 0; let i = 0; while (i < times.length && times[i] < t) i++; const frac = i / Math.max(1, times.length - 1); return Math.min(W, frac * W); } : (t) => t / T * W;
  const ph = opt.ph != null ? opt.ph : T;
  const dim = (e) => { if (S.sess.hi === 'err') return !e.err; if (S.sess.hi === 'corr') return !(e.lane === 'user' && e.corr); if (S.sess.hi === 'user') return e.lane !== 'user'; if (S.sess.hi === 'tools') return !['read', 'edit', 'bash', 'web'].includes(e.lane); return false; };
  const lanes = compact ? ['user', 'read', 'edit', 'bash', 'web'] : LANES.map((l) => l[0]);
  const yOf = {}; let yy = 0; lanes.forEach((k) => { if (compact) { yOf[k] = { top: yy, h: 12 }; yy += 16; } else yOf[k] = LANE[k]; });
  const H = compact ? yy : 300;
  let g = '';
  if (!compact) {
    LANES.forEach((l) => { g += '<line x1="0" x2="' + W + '" y1="' + (l[2] + l[3] + 2) + '" y2="' + (l[2] + l[3] + 2) + '" stroke="var(--hair)"/>'; });
    tr.phases.forEach((p) => { const x1 = X(p[0]), x2 = X(p[1]); g += '<rect x="' + (x1 + 1).toFixed(1) + '" y="24" width="' + Math.max(1, x2 - x1 - 2).toFixed(1) + '" height="20" rx="5" fill="var(--sunken)" stroke="var(--line)"/>' + (x2 - x1 > 34 ? '<text x="' + ((x1 + x2) / 2).toFixed(1) + '" y="38" text-anchor="middle" font-size="11" fill="var(--ink-2)" font-family="var(--sans)">' + p[2] + '</text>' : ''); });
    const cy = (v) => (244 - v / 100 * 40).toFixed(1);
    const line = 'M' + tr.ctx.map((c) => X(c[0]).toFixed(1) + ' ' + cy(c[1])).join(' L');
    g += '<path d="' + line + ' L' + X(tr.ctx[tr.ctx.length - 1][0]).toFixed(1) + ' 244 L0 244Z" fill="var(--ink-3)" fill-opacity=".1"/><path d="' + line + '" fill="none" stroke="var(--ink-2)" stroke-width="2" stroke-linejoin="round"/>';
    const comp = tr.ctx.findIndex((c, i) => i > 0 && c[1] < tr.ctx[i - 1][1] - 20);
    if (comp > 0) { const cx = X(tr.ctx[comp][0]); g += '<line x1="' + cx.toFixed(1) + '" x2="' + cx.toFixed(1) + '" y1="202" y2="244" stroke="var(--ink-1)"/><text x="' + (cx + 4).toFixed(1) + '" y="214" font-size="10" fill="var(--ink-1)" font-family="var(--mono)">自动压缩 ' + Math.round(tr.ctx[comp - 1][1]) + '% → ' + Math.round(tr.ctx[comp][1]) + '%</text>'; }
    g += '<line x1="0" x2="' + W + '" y1="265" y2="265" stroke="var(--line)"/>';
    const my = (m) => (265 - m * 13).toFixed(1);
    g += '<path d="M' + tr.users.map((u) => X(u[0]).toFixed(1) + ' ' + my(u[1])).join(' L') + '" fill="none" stroke="var(--ink-3)" stroke-width="1.5"/>';
    tr.users.forEach((u, i) => { g += '<circle cx="' + X(u[0]).toFixed(1) + '" cy="' + my(u[1]) + '" r="4.5" fill="' + (u[1] < 0 ? 'var(--crit-m)' : 'var(--ink-2)') + '" stroke="var(--surface)" stroke-width="2" data-tf="user|' + i + '"/>'; });
    tr.moments.forEach((m, i) => { const x = Math.max(9, X(m[0])); g += '<g data-act="moment" data-t="' + m[0] + '" style="cursor:pointer" data-tf="mom|' + i + '"><circle cx="' + x.toFixed(1) + '" cy="9" r="9" fill="' + (m[3] ? 'var(--surface)' : 'var(--ink-1)') + '" stroke="' + (m[3] ? 'var(--crit-m)' : 'none') + '" stroke-width="1.5"/><text x="' + x.toFixed(1) + '" y="12.5" text-anchor="middle" font-size="10" font-weight="700" font-family="var(--mono)" fill="' + (m[3] ? 'var(--crit)' : 'var(--surface)') + '">' + (i + 1) + '</text></g>'; });
  }
  CUR.ev = tr.ev;
  tr.ev.forEach((e, i) => {
    const L = yOf[e.lane]; if (!L) return;
    const past = e.t <= ph + 0.01; const op = (dim(e) ? 0.15 : 1) * (past ? 1 : 0.3);
    const x = X(e.t);
    if (e.lane === 'user') g += '<rect x="' + (x - 6).toFixed(1) + '" y="' + (L.top + (compact ? 0 : 5)) + '" width="12" height="12" rx="6" fill="' + (e.corr ? 'var(--surface)' : 'var(--ink-1)') + '" stroke="' + (e.corr ? 'var(--crit-m)' : 'none') + '" stroke-width="2.5" opacity="' + op + '" data-tf="ev|' + i + '"/>';
    else if (e.lane === 'reply') g += '<rect x="' + x.toFixed(1) + '" y="80" width="' + Math.max(4, X(e.t + e.w) - x).toFixed(1) + '" height="10" rx="3" fill="var(--a1)" opacity="' + (0.55 * op) + '" data-tf="ev|' + i + '"/>';
    else if (e.lane === 'sub') g += '<rect x="' + x.toFixed(1) + '" y="183" width="' + Math.max(8, X(e.t + e.w) - x).toFixed(1) + '" height="14" rx="4" fill="var(--a1t)" stroke="var(--a1)" opacity="' + op + '" data-tf="ev|' + i + '"/>';
    else g += '<rect x="' + (x - (e.err ? 1.5 : 1)).toFixed(1) + '" y="' + (e.err ? L.top - 2 : L.top) + '" width="' + (e.err ? 3 : 2) + '" height="' + (e.err ? L.h + 4 : L.h) + '" rx="1" fill="' + (e.err ? 'var(--crit-m)' : e.lane === 'read' || e.lane === 'web' ? 'var(--ink-3)' : e.lane === 'edit' ? 'var(--ink-2)' : 'var(--ink-1)') + '" opacity="' + op + '" data-tf="ev|' + i + '"/>';
  });
  if (!compact) {
    const px = X(Math.min(ph, T));
    g += '<line x1="' + px.toFixed(1) + '" x2="' + px.toFixed(1) + '" y1="20" y2="286" stroke="var(--ink-1)"/><rect x="' + (px - 5).toFixed(1) + '" y="281" width="10" height="10" transform="rotate(45 ' + px.toFixed(1) + ' 286)" fill="var(--ink-1)"/>';
    const ticks = []; const stepM = T > 90 ? 20 : T > 40 ? 10 : 5;
    for (let m = stepM; m < T; m += stepM) ticks.push(m);
    g += ticks.map((m) => { const t0 = s.h * 60 + s.mi + m; return '<text x="' + X(m).toFixed(1) + '" y="299" text-anchor="middle" font-size="10" font-family="var(--mono)" fill="var(--ink-3)">' + (S.sess.axis === 'steps' ? '' : hm(Math.floor(t0 / 60) % 24, t0 % 60)) + '</text>'; }).join('');
  }
  return '<svg class="tl" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" style="display:block;touch-action:none" data-T="' + T + '" data-w="' + W + '">' + g + '</svg>';
}
TIPS.ev = (i) => { const e = CUR.ev && CUR.ev[+i]; if (!e) return ''; const s = BYID[S.sess.sel]; const t0 = s ? s.h * 60 + s.mi + e.t : e.t; const time = s ? hm(Math.floor(t0 / 60) % 24, Math.floor(t0 % 60)) : f1(e.t) + ' 分钟'; const lane = { user: '你的消息', reply: 'Agent 回复', read: '读取 / 搜索', edit: '编辑', bash: '命令', web: '网络', sub: '子代理' }[e.lane]; return '<b class="mono">' + time + '</b> · ' + lane + (e.err ? ' · <b style="color:var(--crit-m)">失败</b>' : '') + (e.cmd ? '\n<span class="mono" style="font-size:11px">' + esc(e.cmd) + '</span>' : '') + (e.res ? '\n' + esc(e.res) : '') + (e.txt ? '\n' + esc(e.txt) : '') + (e.lane === 'user' ? '\n情绪 ' + (e.mood > 0 ? '+' : '') + f1(e.mood) + (e.corr ? ' · 纠偏' : '') : ''); };
TIPS.user = (i) => { const s = BYID[S.sess.sel]; const u = s && traj(s).users[+i]; return u ? '<b>情绪 ' + (u[1] > 0 ? '+' : '') + f1(u[1]) + '</b>\n「' + esc(u[3]) + '」' : ''; };
TIPS.mom = (i) => { const s = BYID[S.sess.sel]; const m = s && traj(s).moments[+i]; return m ? '<b>' + esc(m[1]) + '</b>\n' + esc(m[2]) + '\n<span style="opacity:.8">点击跳到这一刻</span>' : ''; };
let PLAY = null;
function stopPlay() { if (PLAY) cancelAnimationFrame(PLAY); PLAY = null; S.sess.playing = false; }
function startPlay() {
  const s = BYID[S.sess.sel]; if (!s) return; const T = traj(s).T;
  if (S.sess.ph >= T - 0.05) S.sess.ph = 0;
  S.sess.playing = true; const t0 = performance.now(); const ph0 = S.sess.ph; const dur = 8000 * (1 - ph0 / T);
  const tick = (now) => { const k = Math.min(1, (now - t0) / Math.max(1, dur)); S.sess.ph = ph0 + (T - ph0) * k; updTimeline(); if (k < 1 && S.sess.playing) PLAY = requestAnimationFrame(tick); else { S.sess.playing = false; PLAY = null; updTimeline(); } };
  PLAY = requestAnimationFrame(tick); updTimeline();
}
function updTimeline() {
  const box = $('#tlBox'); const s = BYID[S.sess.sel]; if (!box || !s) return;
  box.innerHTML = timelineSVG(s, { zoom: S.sess.zoom, ph: S.sess.ph });
  const r = $('#tlRead'); if (r) r.innerHTML = readout(s);
  const pb = $('[data-act="playToggle"]'); if (pb) pb.innerHTML = ic(S.sess.playing ? 'pause' : 'play', 13) + (S.sess.playing ? '暂停' : '回放');
}
function readout(s) {
  const tr = traj(s); const ph = S.sess.ph; let last = null;
  tr.ev.forEach((e) => { if (e.t <= ph) last = e; });
  const t0 = s.h * 60 + s.mi + ph;
  const done = tr.ev.filter((e) => e.t <= ph);
  return '<span class="mono" style="font-weight:700">' + hm(Math.floor(t0 / 60) % 24, Math.floor(t0 % 60)) + '</span><span class="cap">已发生 ' + done.length + ' / ' + tr.ev.length + ' 个事件 · 错误 ' + done.filter((e) => e.err).length + '</span>' + (last ? '<span style="font-size:12px;color:var(--ink-2);min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">最近：' + esc(last.cmd || last.txt || '') + (last.err ? ' · ' + esc(last.res || '失败') : '') + '</span>' : '');
}
PAGES.sessions = () => {
  const list = sessList();
  const s = BYID[S.sess.sel] || list[0] || ALL[ALL.length - 1];
  if (s && S.sess.sel !== s.id) S.sess.sel = s.id;
  const right = '<div class="seg" role="group" aria-label="视图模式"><button type="button" data-act="sessMode" data-v="single" class="' + (S.sess.mode === 'single' ? 'on' : '') + '">单个</button><button type="button" data-act="sessMode" data-v="cmp" class="' + (S.sess.mode === 'cmp' ? 'on' : '') + '">对比</button></div><button type="button" class="btn" data-act="playToggle">' + ic(S.sess.playing ? 'pause' : 'play', 13) + (S.sess.playing ? '暂停' : '回放') + '</button><button type="button" class="btn ai" data-act="ask" data-ctx="session">' + ic('spark', 14) + '让 Agent 复盘</button>';
  let lastDay = null;
  const rows = list.slice(0, 120).map((x) => {
    let h = '';
    if (x.d !== lastDay) { lastDay = x.d; h += '<div class="dayh">' + (x.d === 120 ? '今天 · 10 月 1 日 周四' : x.d === 119 ? '昨天 · 9 月 30 日 周三' : mdz(x.d) + ' 周' + WD[wd(x.d)]) + '</div>'; }
    const o = OUT[x.out] || OUT.ok;
    const isSel = x.id === S.sess.sel, isCmp = x.id === S.sess.cmp;
    return h + '<button type="button" class="srow' + (isSel || isCmp ? ' sel' : '') + '" data-act="pickSession" data-id="' + x.id + '" aria-pressed="' + (isSel || isCmp) + '"><span class="row" style="width:100%"><span class="dot' + (x.live ? ' live' : '') + '" style="background:' + agent(x.a).c + '"></span><span class="t">' + esc(x.title) + '</span>' + (S.sess.mode === 'cmp' && (isSel || isCmp) ? '<span class="bdg">' + (isSel ? 'A' : 'B') + '</span>' : '') + ic(o[0], 14, 'color:' + o[1]) + '</span><span class="m">' + PJI[x.p].name + ' · ' + hm(x.h, x.mi) + ' · ' + (x.live ? '运行中 ' + liveElapsed().slice(0, 2) + 'm' : dur(x.dur)) + ' · ' + x.tools + ' 次工具' + (x.corr ? ' · ' + x.corr + ' 次纠偏' : '') + '</span><span style="padding-left:16px;width:100%">' + barcode(x, 280) + '</span></button>';
  }).join('');
  const listCard = '<div class="card" style="overflow:hidden"><div style="padding:10px 10px 8px;border-bottom:1px solid var(--hair);display:flex;flex-direction:column;gap:8px"><label class="row" style="height:30px;padding:0 9px;border-radius:8px;background:var(--field);color:var(--ink-3)">' + ic('search', 14) + '<span class="vh">搜索会话</span><input id="sessQ" type="search" data-in="sessQ" placeholder="搜索标题、项目、Agent…" value="' + esc(S.sess.q) + '" style="flex:1;min-width:0;border:0;outline:none;background:transparent;font-size:13px;color:var(--ink-1)"></label><div class="row cap" style="font-size:11.5px;justify-content:space-between"><span>' + list.length + ' 个会话 · ' + rangeLabel() + '</span>' + (S.sess.mode === 'cmp' ? '<span>依次点选 A、B 两个会话</span>' : '<span>最新在前</span>') + '</div></div><div class="slist">' + (rows || '<div class="cap" style="padding:20px">没有匹配的会话。试试放宽筛选。</div>') + '</div></div>';
  if (!s) return tbar('会话与轨迹', '', right) + '<div class="content" id="content">' + filterRow() + empty('没有会话') + '</div>';
  const tr = traj(s); const o = OUT[s.out] || OUT.ok; const ag = agent(s.a);
  const errN = tr.ev.filter((e) => e.err).length; const corrN = tr.users.filter((u) => u[2]).length;
  const peakCtx = Math.round(Math.max(...tr.ctx.map((c) => c[1])));
  const statBtn = (k, label, v, col) => '<button type="button" data-act="hiStat" data-v="' + k + '" class="' + (S.sess.hi === k ? 'on' : '') + '"' + (k ? ' data-tip="点击在时间轴上高亮"' : '') + '><span style="font-size:11px;color:var(--ink-3)">' + label + '</span><span style="font-size:16px;font-weight:600;color:' + (col || 'var(--ink-1)') + '">' + v + '</span></button>';
  let detail;
  if (S.sess.mode === 'cmp') {
    const b = BYID[S.sess.cmp];
    if (!b) detail = empty('对比模式：在左侧列表再选一个会话作为 B（当前 A：' + esc(s.title) + '）');
    else {
      const T = Math.max(traj(s).T, traj(b).T); const sa = stats([s]), sb = stats([b]);
      const rowc = (lbl, va, vb, better) => '<tr><td>' + lbl + '</td><td class="mono" style="text-align:right">' + va + '</td><td class="mono" style="text-align:right">' + vb + '</td><td style="text-align:right;font-size:11.5px;color:var(--ink-3)">' + better + '</td></tr>';
      detail = '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">对比</span><span class="cap">横轴对齐到同一时间尺度（' + Math.round(T) + ' 分钟）</span></div><button type="button" class="btn sm" data-act="swapCmp">交换 A / B</button></div>' +
        [['A', s], ['B', b]].map((p) => '<div style="margin-bottom:12px"><div class="row" style="margin-bottom:6px"><span class="bdg">' + p[0] + '</span><span class="dot" style="background:' + agent(p[1].a).c + '"></span><b style="font-size:13px">' + esc(p[1].title) + '</b><span class="cap mono">' + dur(p[1].dur) + '</span></div><div class="lanes">' + timelineSVG(p[1], { compact: true, T, width: 686 }) + '</div></div>').join('') +
        '<div class="scroll-x"><table class="tbl"><thead><tr><th>指标</th><th style="text-align:right">A</th><th style="text-align:right">B</th><th style="text-align:right">差异</th></tr></thead><tbody>' + rowc('时长', dur(s.dur), dur(b.dur), s.dur < b.dur ? 'A 更快' : 'B 更快') + rowc('你的消息', s.msgs, b.msgs, '') + rowc('工具调用', s.tools, b.tools, '') + rowc('错误', s.errors, b.errors, s.errors < b.errors ? 'A 更稳' : s.errors > b.errors ? 'B 更稳' : '持平') + rowc('纠偏', s.corr, b.corr, '') + rowc('自主比', f1(sa.auto) + '×', f1(sb.auto) + '×', '') + '</tbody></table></div></div>';
    }
  } else {
    detail = '<div class="card" style="overflow:hidden"><div class="band" style="background:' + ag.t + ';border-top-color:' + ag.c + '"><div class="mono row" style="font-size:11.5px;color:var(--ink-3);flex-wrap:wrap;gap:6px"><span class="dot" style="background:' + ag.c + '"></span><b style="font-family:var(--sans);color:var(--ink-2)">' + ag.name + '</b><span>·</span><span>' + (s.a === 'cc' ? 'claude-opus-5-5 · thinking high' : ag.model) + '</span><span>·</span><span>' + esc(PJI[s.p].path) + '</span></div><div class="row" style="margin-top:4px;flex-wrap:wrap"><h2 class="serif" style="margin:0;flex:1;min-width:200px;font-size:22px;line-height:28px;font-weight:600">' + esc(s.title) + '</h2><button type="button" class="btn" data-act="resume">' + ic('term', 14) + '在 ' + ag.short + ' 中继续</button><button type="button" class="ib" data-act="sessMore" aria-label="更多操作" style="background:var(--surface);border:1px solid var(--line)">' + ic('more', 16, 'stroke-width:2.6') + '</button></div><div class="row" style="font-size:12.5px;color:var(--ink-2);margin-top:4px;flex-wrap:wrap;gap:10px"><span class="mono">' + mdz(s.d) + ' ' + hm(s.h, s.mi) + ' · ' + (s.live ? '运行中 ' + liveElapsed() : dur(s.dur)) + '</span><span class="row" style="gap:4px;color:' + o[1] + ';font-weight:600">' + ic(o[0], 14) + o[2] + '</span>' + (corrN ? '<span class="row" style="gap:4px;color:var(--crit);font-weight:600">' + ic('alert', 14) + corrN + ' 次纠偏</span>' : '') + (S.excluded.has(s.id) ? '<span class="tag">不计入分析</span>' : '') + '</div></div>' +
      '<div class="stats7">' + statBtn('user', '你的消息', s.msgs) + statBtn('', 'Agent 步数', Math.round(s.tools * 1.54)) + statBtn('tools', '工具调用', s.tools) + statBtn('err', '错误', s.errors, s.errors ? 'var(--crit)' : '') + statBtn('corr', '纠偏', s.corr, s.corr ? 'var(--crit)' : '') + statBtn('', '上下文峰值', peakCtx + '%') + statBtn('', 'Tokens', f1(s.tok / 1e6) + 'M') + '</div></div>' +
      '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">轨迹</span><span class="cap">泳道时间轴 · ' + s.tools + ' 次工具调用（显示 ' + tr.ev.filter((e) => ['read', 'edit', 'bash', 'web'].includes(e.lane)).length + '）· 拖动画面移动播放头</span></div><div class="seg" role="group" aria-label="横轴"><button type="button" data-act="axis" data-v="time" class="' + (S.sess.axis === 'time' ? 'on' : '') + '">时间</button><button type="button" data-act="axis" data-v="steps" class="' + (S.sess.axis === 'steps' ? 'on' : '') + '">步数</button></div><div class="seg" role="group" aria-label="缩放"><button type="button" data-act="zoom" data-v="-1" aria-label="缩小">−</button><button type="button" data-act="zoom" data-v="1" aria-label="放大">+</button><button type="button" data-act="zoom" data-v="0" class="' + (S.sess.zoom === 1 ? 'on' : '') + '">适应</button></div></div>' +
      '<div class="row" style="align-items:flex-start;gap:0"><div style="position:relative;width:88px;flex:none;height:300px">' + LANES.map((l) => '<div class="lane-lbl" style="top:' + l[2] + 'px;height:' + l[3] + 'px">' + l[1] + '</div>').join('') + '</div><div class="lanes" id="tlBox" style="flex:1;min-width:0">' + timelineSVG(s, { zoom: S.sess.zoom, ph: S.sess.ph }) + '</div></div>' +
      '<div class="row" id="tlRead" style="gap:12px;margin-top:8px;flex-wrap:wrap">' + readout(s) + '</div>' +
      '<div class="row cap" style="gap:14px;flex-wrap:wrap;margin-top:8px;font-size:11px"><span class="row" style="gap:5px"><span style="width:10px;height:10px;border-radius:50%;background:var(--ink-1)"></span>你的消息</span><span class="row" style="gap:5px"><span style="width:10px;height:10px;border-radius:50%;box-shadow:inset 0 0 0 2px var(--crit-m)"></span>纠偏</span><span class="row" style="gap:5px"><span style="width:3px;height:10px;background:var(--crit-m)"></span>失败的调用</span><span class="row" style="gap:5px"><span style="width:12px;height:6px;border-radius:2px;background:var(--a1);opacity:.55"></span>Agent 回复</span><span>Space 回放 · 点编号跳转</span></div></div>' +
      '<div class="two" style="grid-template-columns:minmax(0,1fr) 300px"><div class="card pad"><div class="ct" style="margin-bottom:8px">关键时刻</div><div class="col" style="gap:6px">' + tr.moments.map((m, i) => { const t0 = s.h * 60 + s.mi + m[0]; return '<button type="button" data-act="moment" data-t="' + m[0] + '" style="display:grid;grid-template-columns:18px 44px minmax(0,1fr);gap:8px;align-items:start;font-size:12.5px;line-height:18px;border:0;background:none;padding:2px 0;text-align:left;width:100%"><span style="width:18px;height:18px;border-radius:50%;background:' + (m[3] ? 'var(--surface)' : 'var(--ink-1)') + ';color:' + (m[3] ? 'var(--crit)' : 'var(--surface)') + ';box-shadow:' + (m[3] ? 'inset 0 0 0 1.5px var(--crit-m)' : 'none') + ';font:700 10px/18px var(--mono);text-align:center">' + (i + 1) + '</span><span class="mono" style="font-size:11.5px;color:var(--ink-3)">' + hm(Math.floor(t0 / 60) % 24, Math.floor(t0 % 60)) + '</span><span style="color:var(--ink-2)"><b style="color:var(--ink-1)">' + esc(m[1]) + '</b> ' + esc(m[2]) + '</span></button>'; }).join('') + '</div></div>' +
      '<div class="card pad col"><div class="row"><span class="ct">这次会话的启示</span><span class="aib">' + ic('spark', 11) + 'AI</span></div><p style="margin:0;font-size:12.5px;line-height:1.6;color:var(--ink-2)">' + (s.featured ? '若 AGENTS.md 写明「部署目标：Cloudflare Pages」，可避免第 ② 步的偏离，约省 6 分钟。同一命令连续失败 2 次时，应先检查认证再重试。' : corrN || errN >= 3 ? (corrN ? '本次有 ' + corrN + ' 次纠偏，' : '') + (errN >= 3 ? '出现 ' + errN + ' 次失败，' : '') + '把相关约定写进规则，下次可以少说一次。' : '这次协作很顺：目标清楚、失败少。可以把开场方式记成模板。') + '</p><div class="row" style="flex-wrap:wrap;gap:6px;margin-top:auto"><button type="button" class="btn sm p" data-act="install" data-id="' + (s.featured || s.fric === '方向错误' ? 'deploy-target' : 'acceptance') + '">生成规则</button><button type="button" class="btn sm" data-act="install" data-id="retry-breaker">加 Hook：重复失败提醒</button><button type="button" class="btn sm gh" data-act="inaccurate">不准确</button></div></div></div>';
  }
  return tbar('会话与轨迹', list.length + ' 个会话 · ' + rangeLabel() + ' · 1 个运行中', right) + '<div class="content" id="content">' + filterRow() + '<div class="sess">' + listCard + '<div class="stack" style="min-width:0">' + detail + '</div></div></div>';
};
PAGES.sessions.after = () => {
  const box = $('#tlBox'); if (!box) return;
  let drag = false;
  const setFrom = (e) => { const svg = box.querySelector('svg.tl'); if (!svg) return; const r = svg.getBoundingClientRect(); const T = +svg.dataset.t; const W = +svg.dataset.w; const x = clamp(e.clientX - r.left, 0, r.width) * (W / r.width); S.sess.ph = S.sess.axis === 'steps' ? (() => { const ev = CUR.ev || []; const i = Math.round(x / W * (ev.length - 1)); return ev[i] ? ev[i].t : 0; })() : x / W * T; stopPlay(); updTimeline(); };
  box.addEventListener('pointerdown', (e) => { if (e.target.closest('[data-act]')) return; drag = true; box.setPointerCapture(e.pointerId); setFrom(e); });
  box.addEventListener('pointermove', (e) => { if (drag) setFrom(e); });
  box.addEventListener('pointerup', () => { drag = false; });
  box.addEventListener('wheel', (e) => { if (!(e.metaKey || e.ctrlKey)) return; e.preventDefault(); S.sess.zoom = clamp(S.sess.zoom * (e.deltaY < 0 ? 1.25 : 0.8), 1, 6); updTimeline(); }, { passive: false });
};
Object.assign(ACT, {
  sessQ: (el) => { S.sess.q = el.value; const pos = el.selectionStart; renderMain(); const n = $('#sessQ'); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (e) { /* ignore */ } } },
  pickSession: (el) => {
    stopPlay();
    if (S.sess.mode === 'cmp') { if (el.dataset.id === S.sess.sel) return; S.sess.cmp = el.dataset.id; }
    else { S.sess.sel = el.dataset.id; const s = BYID[el.dataset.id]; S.sess.ph = s ? traj(s).T : 0; S.sess.hi = null; }
    render();
  },
  sessMode: (el) => { S.sess.mode = el.dataset.v; stopPlay(); if (S.sess.mode === 'cmp' && !S.sess.cmp) { const l = sessList().filter((x) => x.id !== S.sess.sel && x.p === BYID[S.sess.sel].p); S.sess.cmp = l[0] ? l[0].id : null; } render(); },
  swapCmp: () => { const a = S.sess.sel; S.sess.sel = S.sess.cmp; S.sess.cmp = a; render(); },
  playToggle: () => { if (S.route !== 'sessions') { go('sessions'); } if (S.sess.mode !== 'single') { S.sess.mode = 'single'; render(); } if (S.sess.playing) { stopPlay(); updTimeline(); } else startPlay(); },
  axis: (el) => { S.sess.axis = el.dataset.v; render(); },
  zoom: (el) => { const v = +el.dataset.v; S.sess.zoom = v === 0 ? 1 : clamp(S.sess.zoom * (v > 0 ? 1.5 : 1 / 1.5), 1, 6); render(); },
  hiStat: (el) => { const v = el.dataset.v; if (!v) return; S.sess.hi = S.sess.hi === v ? null : v; render(); },
  moment: (el) => { stopPlay(); S.sess.ph = +el.dataset.t; updTimeline(); },
  resume: () => { const s = BYID[S.sess.sel]; const ag = agent(s.a); const cmd = ag.resume + ' ' + s.id.replace('sess-', ''); openModal(modalHead('在 ' + ag.name + ' 中继续这个会话', '会在终端中打开；Demo 不会执行任何命令') + '<div class="mb col"><div class="row" style="padding:10px 12px;border-radius:9px;background:var(--sunken);border:1px solid var(--line)"><span class="mono" style="flex:1;font-size:12.5px;word-break:break-all">cd ' + esc(PJI[s.p].path) + ' &amp;&amp; ' + esc(cmd) + '</span><button type="button" class="btn sm" data-act="copyCmd" data-v="' + esc('cd "' + PJI[s.p].path.replace('~', '$HOME') + '" && ' + cmd) + '">复制</button></div><p class="cap" style="margin:0">Tandem 只负责打开终端并填入命令，确认前不会运行。</p></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="resumeGo">在终端中打开</button></div>'); },
  resumeGo: () => { closeModal(); toast('已在终端中打开（演示）'); },
  copyCmd: (el) => copyText(el.dataset.v, '命令'),
  sessMore: (el) => { const s = BYID[S.sess.sel]; openDD(el, [{ t: '复制会话 ID', v: () => copyText(s.id, '会话 ID') }, { t: '在 Finder 中显示日志', v: () => toast('已在 Finder 中显示（演示）：' + agent(s.a).path) }, { sep: 1 }, { t: S.excluded.has(s.id) ? '重新计入分析' : '标记为不计入分析', v: () => { if (S.excluded.has(s.id)) S.excluded.delete(s.id); else S.excluded.add(s.id); render(); toast(S.excluded.has(s.id) ? '已从统计中排除这个会话，所有页面已重算' : '已重新计入分析'); } }], (v) => v()); },
  inaccurate: () => toast('已记录：这条启示不准确。分类器下次会参考')
});

