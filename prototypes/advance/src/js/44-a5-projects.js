/* ============ A5 projects ============
 * 项目表：table-layout:fixed（路径列吃掉剩余宽度、人格列固定），新增与散点同口径的「摩擦率」列，Agent 构成 hover 列出全部分段；
 * 散点：VZ scatter 派生类型 pscatter —— 标签避让、回归线 + 95% 置信带、每点到回归线的残差竖线（高于线琥珀 / 低于线绿）、
 *       面积 = 时长的尺寸图例、对比模式 A 实心 / B 描边 + 字母；此项目 vs 基准：项目墨色 / 基准浅灰 + Δ ▲▼；
 * Agent 分工：会话 / 时长 / 完成率三行条；规则与配置覆盖：Agent × 配置类型方块矩阵（评审 §3.5）。 */
const FOLDERS = { confluo: ['Confluo', 'Confluo/docs/plan/v2/demo'], latentskill: ['~/Research/ppb', '~/Research/latentskill（软链接）'], teamhub: ['team-hub'], hackathon: ['Hackathon'], quant: ['Auto Finance & Quant', 'Auto Finance & Quant/packages/datahub'], fhgs: ['FHGS Website/apps/web', 'FHGS Website/apps/stats'], surge: ['~/.config/surge'], tweet: ['Tweet Card'], other: ['~/Research/General', '~/Downloads', '~/Projects/Coffee'] };
// 各类配置哪些 Agent 读取（示例口径）：AGENTS.md 全部；Hooks / 子代理只有 Claude Code；Skills 为 Claude Code 与 Codex；MCP 除 DeepSeek 外都支持
const COV_SUP = { 'AGENTS.md': ['cc', 'cx', 'gm', 'ds', 'cp'], Hooks: ['cc'], Skills: ['cc', 'cx'], MCP: ['cc', 'cx', 'gm', 'cp'], '子代理': ['cc'] };
// 散点派生类型：在 VZ.scatter 之上加残差竖线与 A / B 标记；其余（标签避让、拟合带、尺寸图例、表格视图）沿用
VZ.types.pscatter = Object.assign({}, VZ.types.scatter, {
  name: '项目散点',
  render(spec, w, h, ctx) {
    // 标签自行放置（基础 scatter 的避让不认识回归线与残差竖线，标签会压在虚线上）：先画点，再按 8 个候选位打分选位
    const out = VZ.types.scatter.render(Object.assign({}, spec, { labels: false }), w, h, ctx); const m = out.model; const fit = m && m.fit; let g = '';
    const P = spec.points || []; const F = m.F; const segs = [];
    // 残差竖线从气泡边缘起画（气泡半透明，线从圆心起会在气泡里透出一截）
    const rmx0 = Math.max(1e-9, ...P.map((p) => VZ.num(p.r) || 0)); const rad0 = (p) => 4 + Math.sqrt((VZ.num(p.r) || 0) / rmx0) * ((spec.rMax || 20) - 4);
    if (fit) P.forEach((p, i) => { if (!m.has(i)) return; const [x, y] = m.at(i); const yf = clamp(F.y(fit.pred(p.x)), F.yT, F.yB); const res = p.y - fit.pred(p.x); if (Math.abs(y - yf) < 2) return; const ys = Math.abs(y - yf) > rad0(p) + 2 ? y + Math.sign(yf - y) * rad0(p) : y; segs.push([x, y, x, yf]); g += '<line class="pj-res" x1="' + VZ.r1(x) + '" x2="' + VZ.r1(x) + '" y1="' + VZ.r1(ys) + '" y2="' + VZ.r1(yf) + '" style="--c:' + (res > 0 ? VZ.sem.corr : VZ.sem.good) + '"/>'; });
    let body = out.body; const k = body.indexOf('<circle class="vz-dot'); body = k >= 0 ? body.slice(0, k) + g + body.slice(k) : body + g;
    const ids = P.map((_, i) => i).filter((i) => m.has(i));
    if (fit && ids.length > 1) { const lo = ids.reduce((a, i) => P[i].x < P[a].x ? i : a), hi = ids.reduce((a, i) => P[i].x > P[a].x ? i : a); segs.push([m.at(lo)[0], F.y(fit.pred(P[lo].x)), m.at(hi)[0], F.y(fit.pred(P[hi].x))]); }
    if (spec.labels !== false && ids.length) {
      const rmx = Math.max(1e-9, ...ids.map((i) => VZ.num(P[i].r) || 0)); const rMax = spec.rMax || 20; const rad = (p) => 4 + Math.sqrt((VZ.num(p.r) || 0) / rmx) * (rMax - 4);
      const isSel = (i) => spec.selected != null && (spec.selected === i || spec.selected === P[i].id);
      const boxes = ids.map((i) => { const [x, y] = m.at(i); const r = rad(P[i]); return [x - r, y - r, x + r, y + r, i]; });
      // 轴标题占位：左上「↑ 摩擦率」、右下 x 轴标题
      if (spec.y && spec.y.label) boxes.push([F.x0, F.yT, F.x0 + 8 + VZ.tw(spec.y.label, 11), F.yT + 15, -1]);
      if (spec.x && spec.x.label) boxes.push([F.x1 - VZ.tw(spec.x.label, 11) - 6, F.yB - 18, F.x1, F.yB, -1]);
      const hitSeg = (b, sg) => { for (let t = 0; t <= 1.0001; t += 1 / 24) { const x = sg[0] + (sg[2] - sg[0]) * t, y = sg[1] + (sg[3] - sg[1]) * t; if (x > b[0] - 2 && x < b[2] + 2 && y > b[1] - 2 && y < b[3] + 2) return 1; } return 0; };
      let lb = '';
      ids.slice().sort((a, c) => (isSel(c) - isSel(a)) || (rad(P[c]) - rad(P[a]))).forEach((i) => {
        const p = P[i]; if (p.label == null || p.label === '') return; const [cx, cy] = m.at(i); const r = rad(p); const tw = VZ.tw(p.label, 11); const d = r * 0.71;
        const cands = [[cx + r + 5, cy + 4, 'start'], [cx - r - 5, cy + 4, 'end'], [cx + d + 4, cy - d - 2, 'start'], [cx - d - 4, cy - d - 2, 'end'], [cx, cy - r - 6, 'middle'], [cx + d + 4, cy + d + 10, 'start'], [cx - d - 4, cy + d + 10, 'end'], [cx, cy + r + 13, 'middle']];
        let best = null;
        cands.forEach(([lx, ly, an], ci) => {
          const bx0 = an === 'start' ? lx : an === 'end' ? lx - tw : lx - tw / 2; const b = [bx0, ly - 11, bx0 + tw, ly + 3];
          if (b[0] < F.x0 + 2 || b[2] > w - 2 || b[1] < F.yT - 2 || b[3] > F.yB + 2) return;
          let sc = ci * 0.5; boxes.forEach((o) => { if (o[4] !== i && b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]) sc += 1000; }); segs.forEach((sg) => { sc += hitSeg(b, sg) * 8; });
          if (!best || sc < best.sc) best = { sc, lx, ly, an, b };
        });
        if (!best || best.sc >= 1000) return;
        boxes.push(best.b.concat([-1])); lb += VZ.txt(best.lx, best.ly, p.label, { class: 'vz-lbl pj-lbl' + (isSel(i) ? ' vz-strong' : ''), 'text-anchor': best.an });
      });
      const kh = body.indexOf('<circle class="vz-hit'); body = kh >= 0 ? body.slice(0, kh) + lb + body.slice(kh) : body + lb;
    }
    // A / B：A 为选中项目（实心墨色），B 为对比项目（描边环 + 字母）；只在对比模式下标字母
    (spec.marks2 || []).forEach((mk) => { const i = P.findIndex((p) => p.id === mk.id); if (i < 0 || !m.has(i)) return; const [x, y] = m.at(i); body += (mk.ring ? '<circle class="pj-ring" cx="' + VZ.r1(x) + '" cy="' + VZ.r1(y) + '" r="' + VZ.r1(mk.r + 3) + '"/>' : '') + VZ.txt(x, y + 4, mk.letter, { class: 'pj-ab' + (mk.ring ? ' ring' : ''), 'text-anchor': 'middle' }); });
    return { body, model: m };
  }
});
PAGES.projects = () => {
  if (LV.live) return lvProjectsPage();   // live: same cards from /v1/uiview/projects* (93-live-tools-projects.js)
  const L = sel({ project: null });
  const rows = projRows(L).filter((r) => r.st.n > 0).sort((a, b) => b.st.hours - a.st.hours);
  // 全局项目筛选激活时，详情定位到该项目（BUG-07）；B 与 A 相同则清掉 B（BUG-71）
  if (S.project && rows.some((r) => r.p.id === S.project)) S.proj.sel = S.project;
  if (S.proj.cmp && S.proj.cmp === S.proj.sel) S.proj.cmp = null;
  const selRow = rows.find((r) => r.p.id === S.proj.sel) || rows[0];
  if (!selRow) return tbar('项目习惯', '') + '<div class="content" id="content">' + filterRow() + empty('所选范围内没有会话') + '</div>';
  S.proj.sel = selRow.p.id;
  const p = selRow.p; const xs = selRow.xs; const st = selRow.st;
  const cmpRow = S.proj.cmp ? rows.find((r) => r.p.id === S.proj.cmp) : null;
  const overall = stats(L);
  const days = (arr) => new Set(arr.map((s) => s.d)).size || 1;
  const pts = rows.filter((r) => r.st.n >= 3).map((r) => ({ x: r.st.auto, y: r.st.fric, r: r.st.hours, id: r.p.id, label: r.p.name, meta: r.st.n + ' 个会话', color: r.p.id === p.id ? 'var(--ink-1)' : (cmpRow && r.p.id === cmpRow.p.id) ? 'var(--surface)' : 'var(--h2)' }));
  CUR.pjPts = pts;
  const tableRows = S.proj.group === 'folder'
    ? rows.flatMap((r) => FOLDERS[r.p.id].map((f, i, arr) => { const share = arr.length === 1 ? 1 : i === 0 ? 0.72 : 0.28 / (arr.length - 1); return { r, f, n: Math.max(1, Math.round(r.st.n * share)), h: r.st.hours * share }; }))
    : rows.map((r) => ({ r, f: null, n: r.st.n, h: r.st.hours }));
  const fricMax = Math.max(1, ...rows.map((r) => r.st.fric));
  const cmpA = cmpRow ? cmpRow.st : overall; const cmpXs = cmpRow ? cmpRow.xs : L; const cmpName = cmpRow ? cmpRow.p.name : '整体';
  // [名称, 本项目, 基准, 格式, 单位（pt = 百分点差；pct = 相对差）, goodDown]
  const metrics = [['平均会话时长', st.hours * 60 / Math.max(1, st.n), cmpA.hours * 60 / Math.max(1, cmpA.n), (v) => Math.round(v) + 'm', 'pct', null], ['每会话消息', st.per, cmpA.per, (v) => f1(v), 'pct', null], ['自主比', st.auto, cmpA.auto, (v) => f1(v) + '×', 'x', null], ['要求验证', st.verify, cmpA.verify, (v) => Math.round(v) + '%', 'pt', false], ['摩擦率', st.fric, cmpA.fric, (v) => f1(v) + '%', 'pt', true], ['日均会话', st.n / days(xs), cmpA.n / days(cmpXs), (v) => f1(v), 'pct', null]];
  const split = selRow.split; const splitTot = split.reduce((a, b) => a + b, 0) || 1;
  const pp = selRow.pers;
  const agRows = AG.map((a, j) => { const ys = xs.filter((s) => s.a === a.id); if (!ys.length) return null; const h = sum(ys, (s) => s.dur) / 60; return { a, n: ys.length, h, ok: ys.filter((s) => s.out === 'ok').length / ys.length * 100 }; }).filter(Boolean);
  const agMaxN = Math.max(1, ...agRows.map((r) => r.n)), agMaxH = Math.max(0.1, ...agRows.map((r) => r.h));
  const agents = AG.filter((a, j) => split[j] > 0);
  const support = Math.max(1, Math.round(xs.length * 0.61));
  const covCell = (c, a) => { const sup = (COV_SUP[c[0]] || []).includes(a.id); const on = sup && c[3]; return '<span class="pj-cov-c' + (on ? ' on' : sup ? ' off' : ' na') + '" data-tip="' + esc(a.name + ' · ' + c[0] + '：' + (on ? '已配置（' + c[1] + '）' : sup ? '未配置 · ' + c[2] : '该 Agent 不读取此类配置')) + '" role="img" aria-label="' + esc(a.short + ' ' + c[0] + (on ? ' 已配置' : sup ? ' 未配置' : ' 不适用')) + '"></span>'; };
  return tbar('项目习惯', rows.length + ' 个项目 · ' + f1(overall.hours) + ' 小时 · 按协作时长排序', '<button type="button" class="btn' + (S.proj.cmpMode ? ' p' : '') + '" data-act="projCompare">' + (S.proj.cmpMode ? '退出对比' : '对比两个项目') + '</button><button type="button" class="btn ai" data-act="projRule">' + ic('spark', 14) + '为此项目起草规则</button>') +
    '<div class="content" id="content">' + filterRow('<span class="cap">聚合</span><div class="seg" role="group" aria-label="聚合方式"><button type="button" data-act="projGroup" data-v="project" class="' + (S.proj.group === 'project' ? 'on' : '') + '">按项目</button><button type="button" data-act="projGroup" data-v="folder" class="' + (S.proj.group === 'folder' ? 'on' : '') + '">按文件夹</button></div>') +
    '<div class="pj"><div class="stack"><div class="card pad"><table class="tbl pj-tbl"><colgroup><col><col class="pj-c-n"><col class="pj-c-h"><col class="pj-c-f"><col class="pj-c-s"><col class="pj-c-p"></colgroup><thead><tr><th>' + (S.proj.group === 'folder' ? '文件夹' : '项目') + '</th><th style="text-align:right">会话</th><th style="text-align:right">时长</th><th>摩擦率</th><th>Agent 构成</th><th style="text-align:right">此处人格</th></tr></thead><tbody>' +
    tableRows.map((t) => { const r = t.r; const on = r.p.id === p.id, on2 = cmpRow && r.p.id === cmpRow.p.id; const tot2 = r.split.reduce((a, b) => a + b, 0) || 1; const pc = r.pers.ok ? r.pers.code : '—'; return '<tr class="click' + (on || on2 ? ' sel' : '') + '" data-act="pickProject" data-p="' + r.p.id + '" aria-selected="' + !!on + '"><td class="pj-name"><div class="pj-title">' + esc(t.f || r.p.name) + ((S.proj.cmpMode && on) || on2 ? ' <span class="bdg">' + (on ? 'A' : 'B') + '</span>' : '') + '</div><div class="mono cap pj-path code-t">' + esc(t.f ? '归入 ' + r.p.name : r.p.path) + '</div></td><td class="mono" style="text-align:right" data-count="' + t.n + '" data-ck="pj-n:' + r.p.id + ':' + esc(t.f || '') + '">' + t.n + '</td><td class="mono" style="text-align:right" data-count="' + f1(t.h) + '" data-ck="pj-h:' + r.p.id + ':' + esc(t.f || '') + '">' + f1(t.h) + 'h</td><td><span class="row pj-fric"><span class="pj-bar"><i style="width:' + (r.st.fric / fricMax * 100).toFixed(1) + '%"></i></span><span class="mono">' + f1(r.st.fric) + '%</span></span></td><td><div class="pj-split" data-tf="split|' + r.p.id + '" tabindex="0">' + r.split.map((v, j) => v ? '<span style="width:' + (v / tot2 * 100) + '%;background:' + AG[j].c + '"></span>' : '').join('') + '</div></td><td class="mono pj-pers" style="font-weight:' + (r.pers.ok && r.pers.code !== 'DIMV' ? 700 : 500) + ';color:' + (r.pers.ok ? 'var(--ink-1)' : 'var(--ink-3)') + '"' + (pc.includes('?') ? ' data-tip="「?」= 该维度落在 45–55 之间，尚未定型"' : '') + '>' + pc + '</td></tr>'; }).join('') + '</tbody></table><div class="cap pj-foot" data-tip="按项目聚合时以 git 根目录归并子文件夹；摩擦率 = 纠偏消息 / 全部消息">' + (S.proj.group === 'folder' ? '子文件夹按会话归入所属项目 · ' : '') + '「—」样本 &lt; 8 个会话 · 「?」维度未定型</div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">跨项目对比</span><span class="cap">' + (S.proj.cmpMode ? '点另一个项目作为 B' : '面积 = 时长 · 竖线 = 到回归线的残差') + '</span></div><span class="row cap pj-rleg" data-tip="琥珀 = 摩擦率高于同等自主度的预期；绿 = 低于"><span class="row" style="gap:4px"><i style="background:' + VZ.sem.corr + '"></i>高于预期</span><span class="row" style="gap:4px"><i style="background:' + VZ.sem.good + '"></i>低于预期</span></span></div><div class="vz" data-vz="pj-scatter"></div><div class="cap pj-foot">' + (pts.length >= 3 ? '高于回归线的项目最值得先加护栏' : '项目太少，无法拟合') + '</div></div></div>' +
    '<div class="stack"><div class="card pad"><div class="row" style="gap:12px;flex-wrap:wrap"><span style="width:36px;height:36px;border-radius:9px;background:var(--sunken);display:grid;place-items:center">' + ic('projects', 18) + '</span><div style="flex:1;min-width:200px"><div class="row" style="align-items:baseline;gap:10px;flex-wrap:wrap"><h2 class="serif" style="margin:0;font-size:22px">' + esc(p.name) + '</h2><span class="mono cap code-t">' + esc(p.path) + ' · git: ' + esc(p.git) + '</span></div><div class="row" style="gap:6px;margin-top:4px;flex-wrap:wrap">' + p.tags.map((t) => '<span class="tag">' + t + '</span>').join('') + '</div></div><button type="button" class="btn" data-act="finder">在 Finder 中显示</button><button type="button" class="btn" data-act="openAgents">打开 AGENTS.md</button></div>' +
    '<div class="row pj-pline">' + ic('persona', 14) + '<span>' + (pp.ok ? '在这个项目里你是 <b class="mono" style="color:var(--ink-1);letter-spacing:.04em">' + pp.code + '</b> <b style="color:var(--ink-1)">' + pp.zh + '</b>' + (personaNow().ok && personaNow().code !== pp.code ? '，和整体（' + personaNow().code + ' ' + personaNow().zh + '）不同' : '，和整体一致') + '。' : '这个项目的会话少于 8 个，暂不判断人格。') + '</span></div></div>' +
    '<div class="pj-two"><div class="card pad"><div class="hd"><div class="grow"><span class="ct">此项目 vs ' + esc(cmpName) + '</span></div><span class="row cap" style="font-size:11px;gap:10px"><span class="row" style="gap:4px"><span class="pj-key" style="background:var(--ink-1)"></span>' + esc(p.name) + '</span><span class="row" style="gap:4px"><span class="pj-key" style="background:var(--ink-4)"></span>' + esc(cmpName) + '</span></span></div><div class="col" style="gap:8px">' + metrics.map((m) => { const mx = Math.max(m[1], m[2]) || 1; const d = VZ.delta2({ cur: m[1], prev: m[2], unit: m[4] === 'pct' ? undefined : m[4], goodDown: m[5], prevText: false }); const rel = m[2] ? Math.abs(m[1] - m[2]) / Math.abs(m[2]) : 0; return '<div class="pj-vs"><span class="pj-vs-n">' + m[0] + '</span><span class="col" style="gap:2px"><span class="pj-vs-b a" style="width:' + (m[1] / mx * 100) + '%"></span><span class="pj-vs-b" style="width:' + (m[2] / mx * 100) + '%"></span></span><span class="mono pj-vs-v"><b>' + m[3](m[1]) + '</b> / ' + m[3](m[2]) + '</span><span class="mono pj-vs-d ' + (rel < 0.1 ? 'flat' : d.cls) + '">' + (rel < 0.1 ? '≈' : d.text) + '</span></div>'; }).join('') + '</div>' + (S.proj.cmpMode && !cmpRow ? '<div class="cap pj-foot">在表格或散点图里点另一个项目作为 B</div>' : '<div class="cap pj-foot" data-tip="只有摩擦率与要求验证按好坏着色">Δ 相对 ' + esc(cmpName) + ' · 差异 &lt; 10% 记为 ≈</div>') + '</div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">Agent 分工</span><span class="cap">' + xs.length + ' 个会话 · 条宽 = 会话占比</span></div></div><div class="pj-share">' + split.map((v, j) => v ? '<span style="width:' + (v / splitTot * 100) + '%;background:' + AG[j].c + '" data-tip="' + AG[j].name + '：' + v + ' 个会话 · ' + Math.round(v / splitTot * 100) + '%"></span>' : '').join('') + '</div><div class="col" style="gap:8px;margin-top:10px">' + agRows.map((r) => '<div class="pj-ag"><span class="row" style="gap:6px;font-size:12px;min-width:0"><span class="pj-dot" style="background:' + r.a.c + '"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + r.a.short + '</span></span><span class="col" style="gap:3px"><span class="pj-ag-r"><span class="cap">会话</span><span class="pj-bar"><i style="width:' + (r.n / agMaxN * 100).toFixed(0) + '%;background:' + r.a.c + '"></i></span><span class="mono">' + r.n + '</span></span><span class="pj-ag-r"><span class="cap">时长</span><span class="pj-bar"><i style="width:' + (r.h / agMaxH * 100).toFixed(0) + '%;background:' + r.a.c + '"></i></span><span class="mono">' + f1(r.h) + 'h</span></span><span class="pj-ag-r"><span class="cap">完成</span><span class="pj-bar"><i style="width:' + r.ok.toFixed(0) + '%;background:var(--ink-3)"></i></span><span class="mono">' + Math.round(r.ok) + '%</span></span></span></div>').join('') + '</div></div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">识别到的工作流</span><span class="cap">出现在 ' + support + ' / ' + xs.length + ' 个会话 · 支持度 ' + Math.round(support / Math.max(1, xs.length) * 100) + '%</span></div></div><div class="row" style="flex-wrap:wrap;gap:8px">' + p.flow.map((f, i) => '<span class="col pj-step"><b>' + f[0] + '</b><span class="mono cap">' + esc(f[1]) + '</span></span>' + (i < p.flow.length - 1 ? ic('arrow', 14, 'color:var(--ink-4)') : '')).join('') + '</div><div class="row" style="margin-top:10px;flex-wrap:wrap"><span class="pj-note">固定成一个 Skill 后，每次可少说约 4 条指令。</span><button type="button" class="btn sm ai" data-act="flowToStudio">' + ic('spark', 12) + '封装为 Skill</button></div></div>' +
    '<div class="card pad"><div class="hd"><div class="grow"><span class="ct">规则与配置覆盖</span><span class="cap" data-tip="扫描 AGENTS.md、.claude、.codex、.gemini（示例）">列 = 此项目用到的 Agent</span></div></div><div class="pj-cov" style="grid-template-columns:auto repeat(' + agents.length + ',24px) minmax(0,1fr)" role="table" aria-label="规则与配置覆盖矩阵"><span></span>' + agents.map((a) => '<span class="pj-cov-h" title="' + a.name + '"><span class="pj-dot" style="background:' + a.c + '"></span></span>').join('') + '<span></span>' + p.cover.map((c) => '<span class="pj-cov-r">' + c[0] + '</span>' + agents.map((a) => covCell(c, a)).join('') + '<span class="pj-cov-v"><b class="mono">' + c[1] + '</b><span class="cap">' + c[2] + '</span></span>').join('') + '</div><div class="row cap pj-foot" style="gap:12px;flex-wrap:wrap"><span class="row" style="gap:4px"><span class="pj-cov-c on"></span>已配置</span><span class="row" style="gap:4px"><span class="pj-cov-c off"></span>未配置</span><span class="row" style="gap:4px"><span class="pj-cov-c na"></span>该 Agent 不读取</span></div><div class="row" style="margin-top:10px;padding:7px 10px;border-radius:8px;background:var(--sunken);flex-wrap:wrap">' + ic('bolt', 15, 'color:var(--ai)') + '<span class="pj-note">建议：' + esc(p.tip) + '</span><button type="button" class="btn sm" data-act="openRec" data-id="' + p.rec + '">查看建议</button></div></div></div></div></div>';
};
PAGES.projects.after = () => {
  const pts = CUR.pjPts || []; if (!pts.length) return;
  const cmpRow = S.proj.cmp; const selId = S.proj.sel;
  const marks2 = (S.proj.cmpMode ? [{ id: selId, letter: 'A', r: 0 }] : []).concat(cmpRow ? [{ id: cmpRow, letter: 'B', r: 0, ring: true }] : []);
  VZ.mount('pj-scatter', { type: 'pscatter', title: '各项目自主比与摩擦率', height: 260, points: pts, fit: true, labels: true, rMax: 18, rLabel: '时长', rFormat: (v) => f1(v) + ' h', selected: selId, marks2, x: { label: '自主比（工具调用 / 你的消息）→', format: (v) => v + '×' }, y: { label: '↑ 摩擦率', format: 'pct' }, legend: false, onSelect: (i, d) => { if (d && d.id) ACT.pickProject({ dataset: { p: d.id } }); } });
};
TIPS.split = (id) => { const r = projRows(sel({ project: null })).find((x) => x.p.id === id); if (!r) return ''; const tot = r.split.reduce((a, b) => a + b, 0) || 1; return '<b>' + esc(r.p.name) + ' · Agent 构成</b>\n' + r.split.map((v, j) => v ? '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + AG[j].c + ';margin-right:5px;vertical-align:-1px"></span>' + AG[j].name + ' <b class="mono">' + v + '</b> · ' + Math.round(v / tot * 100) + '%' : '').filter(Boolean).join('\n'); };
Object.assign(ACT, {
  pickProject: (el) => { const id = el.dataset.p; if (S.proj.cmpMode) { if (id !== S.proj.sel) S.proj.cmp = id; } else { S.proj.sel = id; if (S.proj.cmp === id) S.proj.cmp = null; } if (S.route !== 'projects') go('projects'); else render(); },
  projCompare: () => { if (S.proj.cmpMode) { S.proj.cmpMode = false; S.proj.cmp = null; } else { S.proj.cmpMode = true; S.proj.cmp = ''; toast('在左侧表格或散点图里点另一个项目作为 B'); } render(); },
  projGroup: (el) => { S.proj.group = el.dataset.v; render(); },
  finder: () => toast('已在 Finder 中显示（演示）：' + PJI[S.proj.sel].path),
  openAgents: () => toast('已用默认编辑器打开 AGENTS.md（演示，应用内不改写文件）'),
  flowToStudio: () => { const p = PJI[S.proj.sel]; S.studio.type = 'Skill'; S.studio.goal = '把 ' + p.name + ' 里反复出现的工作流做成一个 Skill：' + p.flow.map((f) => f[0]).join(' → ') + '。'; S.studio.from = 'A5 识别到的工作流 · ' + p.name; S.studio.run = null; go('studio'); },
  projRule: () => { const p = PJI[S.proj.sel]; S.studio.type = '规则'; S.studio.goal = '为 ' + p.name + ' 起草一段 AGENTS.md 规则，覆盖最常见的纠偏：' + Object.keys(p.fric).slice(0, 2).join('、') + '。'; S.studio.from = 'A5 项目习惯 · ' + p.name; S.studio.run = null; go('studio'); }
});
