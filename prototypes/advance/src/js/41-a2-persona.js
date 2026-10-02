/* ============ A2 persona ============
 * 结构：hero（四字母 + 名称 + 「实验性」+ 演变：月份码 + 四轴折线）与协作指纹（内核 4 轴雷达 / 中环 1px 刻度 + 节律带 /
 * 外环 24 段按 Agent 堆叠的密度环，点击一段展开该小时的会话点）→ 四个维度（VZ 双向条：45–55 未定型带、对照刻度、
 * 数值跟随胜出极、每轴证据微型图）+ 优势与盲点 + 契合度（中性条、透明度随 n、95% 区间、Agent 色只在圆点）。
 * 人格口径统一走 personaScope（BUG-06）；样本不足时列出放宽哪个筛选能补到多少（A2-V08），全部来源停用时引导到设置（BUG-50）。 */
const PERIODS = { sep: [90, 119, '9 月'], '90': [30, 119, '近 90 天'], all: [0, 119, '全部'], jun: [0, 27, '6 月'], jul: [28, 58, '7 月'], aug: [59, 89, '8 月'] };
const POP = { D: 52, I: 54, M: 47, V: 58 };
if (S.persona.fpHour === undefined) S.persona.fpHour = null;
const peNum = (v) => String(Math.round(Math.abs(v) * 50 + 50));
function peAxisRows(p, prev) {
  return [0, 1, 2, 3].map((i) => {
    const a = axisView(p, i); const k = a.ax.k; const sgn = k === 'I' ? 1 : -1;
    const gv = S.persona.vs === 'pop' ? POP[k] : (prev && prev.ok ? prev.v[k] : null);
    return { name: '', left: a.ax.L + ' ' + a.ax.Ln, right: a.ax.Rn + ' ' + a.ax.R, value: +((50 - a.val) * sgn * -1 / 50).toFixed(2), ref: gv == null ? null : +((50 - gv) * sgn * -1 / 50).toFixed(2), hint: a.ax.q + ' · 强度 ' + a.strong, id: k };
  });
}
// 每轴证据微型图：D 每会话消息数分布、P/I 项目按结构度排序的时长、M 每日会话数分布、V 项目按求证度排序的时长
function peEvidence(L, st, p, i) {
  const hist = (vals, n, max) => { const out = new Array(n).fill(0); vals.forEach((v) => { out[Math.min(n - 1, Math.floor(v / max * n))]++; }); return out; };
  const byProj = (key) => PJ.slice().sort((a, b) => a[key] - b[key]).map((pj) => sum(L.filter((s) => s.p === pj.id), (s) => s.dur) / 60);
  if (i === 0) return { txt: '每会话 ' + f1(st.per) + ' 条消息 · 单轮平均 ' + f1(st.auto) + ' 步', vals: hist(L.map((s) => s.msgs), 10, 20), lbl: '消息数 0 → 20+ 的会话数' };
  if (i === 1) return { txt: '规划型项目占 ' + Math.round(sum(L.filter((s) => PJI[s.p].I < 50), (s) => s.dur) / (st.hours * 60 || 1) * 100) + '% 时长', vals: byProj('I'), lbl: '项目时长 · 规划型 → 即兴型' };
  if (i === 2) { const by = {}; L.forEach((s) => { by[s.d] = (by[s.d] || 0) + 1; }); return { txt: '日均 ' + f1(p.avgS) + ' 个会话 · 同日 ' + f1(p.avgA) + ' 个 Agent', vals: hist(Object.values(by), 8, 8), lbl: '每日会话数 1 → 8+ 的天数' }; }
  return { txt: Math.round(st.verify) + '% 会话要求验证 · 完成率 ' + Math.round(st.ok) + '%', vals: byProj('V'), lbl: '项目时长 · 信任型 → 求证型' };
}
// 样本不足时：放宽哪个筛选能补到多少（只看人格口径里的三个条件：Agent、项目、周期）
function peRelax(w) {
  const out = []; const n = (o) => ALL.filter((s) => s.d >= o.w[0] && s.d <= o.w[1] && !s.live && sourceEnabled(s) && (o.allAg || S.agents.has(s.a)) && (o.noProj || !S.project || s.p === S.project)).length;
  if (S.project) out.push({ k: 'project', t: '项目 · ' + PJI[S.project].name, n: n({ w, noProj: true }) });
  if (S.agents.size < AG.length) out.push({ k: 'agents', t: 'Agent · ' + AG.filter((a) => S.agents.has(a.id)).map((a) => a.short).join(' / '), n: n({ w, allAg: true }) });
  if (S.persona.period !== 'all') out.push({ k: 'period', t: '周期 · ' + PERIODS[S.persona.period][2], n: n({ w: [0, 119] }) });
  return out;
}
const AXR = { D: 0, I: 90, M: 180, V: 270 };
// 协作指纹（评审 A2-V01/02/03）：内核 4 轴雷达，中环 1px 刻度 + 节律带，外环 24 段按 Agent 堆叠的密度环；选中小时展开会话点
function fp2SVG(L, p, size, opt) {
  opt = opt || {}; const C = 200; const R0 = 140, RH = 44;
  const byH = Array.from({ length: 24 }, () => []); L.forEach((s) => byH[s.h].push(s));
  const mxH = Math.max(1, ...byH.map((x) => x.length));
  CUR.fp = { byH, mxH };
  const sector = (r0, r1, a0, a1) => { const p0 = pt(C, r0, a0), p1 = pt(C, r1, a0), p2 = pt(C, r1, a1), p3 = pt(C, r0, a1); const lg = a1 - a0 > Math.PI ? 1 : 0; return 'M' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1) + 'L' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + 'A' + r1 + ' ' + r1 + ' 0 ' + lg + ' 1 ' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1) + 'L' + p3[0].toFixed(1) + ' ' + p3[1].toFixed(1) + 'A' + r0 + ' ' + r0 + ' 0 ' + lg + ' 0 ' + p0[0].toFixed(1) + ' ' + p0[1].toFixed(1) + 'Z'; };
  const sel = S.persona.fpHour;
  let ring = '';
  byH.forEach((xs, h) => {
    const a0 = h / 24 * Math.PI * 2 + 0.02, a1 = (h + 1) / 24 * Math.PI * 2 - 0.02; const on = sel == null || sel === h;
    let r = R0 + 1;
    const total = xs.length; const hh = total / mxH * RH;
    ring += '<g class="fps' + (sel === h ? ' sel' : '') + (!on ? ' dim' : '') + '" data-h="' + h + '"' + (opt.interactive ? ' data-tf="fph|' + h + '" data-act="fpHour" tabindex="0" role="button" aria-label="' + h + ':00–' + (h + 1) + ':00 · ' + total + ' 个会话"' : '') + '><path d="' + sector(R0, R0 + RH + 2, a0, a1) + '" fill="transparent"/>';
    AG.forEach((a) => { const k = xs.filter((s) => s.a === a.id).length; if (!k) return; const seg = k / total * hh; ring += '<path d="' + sector(r, r + Math.max(1.5, seg - 1), a0, a1) + '" fill="' + a.c + '"/>'; r += seg; });
    ring += '</g>';
  });
  // 选中小时：展开该小时的会话点（角度 = 开始分钟，半径 = 时长），这时才能悬停到单个会话
  let dots = '';
  if (sel != null) dots = byH[sel].map((s) => { const a = (s.h + s.mi / 60) / 24 * Math.PI * 2; const q = pt(C, R0 + 4 + Math.min(s.dur, 126) / 126 * (RH - 6), a); return '<circle class="fpd" cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="4" fill="' + agent(s.a).c + '" stroke="var(--surface)" stroke-width="1.5"' + (opt.interactive ? ' data-tf="sess|' + s.id + '" data-act="openSession" data-id="' + s.id + '" style="cursor:pointer"' : '') + '/>'; }).join('');
  // 中环：24 个 1px 刻度 + 节律带（每半小时一个采样点，半径 102 → 128）
  const hc = new Array(24).fill(0); L.forEach((s) => { hc[s.h]++; });
  const hm2 = Math.max(1, ...hc);
  let ticks = ''; for (let h = 0; h < 24; h++) { const a = h / 24 * Math.PI * 2; const p1 = pt(C, 96, a), p2 = pt(C, h % 6 ? 100 : 103, a); ticks += 'M' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + 'L' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1); }
  let band = ''; for (let k = 0; k < 48; k++) { const h = Math.floor(k / 2); const v = (k % 2 === 0 ? hc[h] : (hc[h] + hc[(h + 1) % 24]) / 2) / hm2; const a = k / 48 * Math.PI * 2; const q = pt(C, 102 + v * 20, a); band += (k ? 'L' : 'M') + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }
  band += 'Z'; let inner = ''; for (let k = 0; k < 48; k++) { const a = k / 48 * Math.PI * 2; const q = pt(C, 102, a); inner += (k ? 'L' : 'M') + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }
  // 内核：4 轴雷达（0 在中心，100 在 r=64）；45–55 画成浅灰环
  const RR = 64; const rad = (v) => v / 100 * RR; const axes = ['D', 'I', 'M', 'V'];
  const poly = axes.map((k) => pt(C, rad(p.v[k]), AXR[k] * Math.PI / 180)).map((q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1)).join('L');
  const spokes = axes.map((k) => { const q = pt(C, RR, AXR[k] * Math.PI / 180); return 'M' + C + ' ' + C + 'L' + q[0].toFixed(1) + ' ' + q[1].toFixed(1); }).join('');
  const verts = axes.map((k) => { const q = pt(C, rad(p.v[k]), AXR[k] * Math.PI / 180); return '<circle cx="' + q[0].toFixed(1) + '" cy="' + q[1].toFixed(1) + '" r="3.5" fill="var(--ink-1)" stroke="var(--surface)" stroke-width="1.5"/>'; }).join('');
  const lbl = opt.labels ? axes.map((k, i) => { const a = axisView(p, i); const q = pt(C, RR + 14, AXR[k] * Math.PI / 180); return '<text x="' + q[0].toFixed(1) + '" y="' + (q[1] + 4).toFixed(1) + '" text-anchor="middle" font-size="11" font-family="var(--mono)" font-weight="700" fill="var(--ink-1)">' + a.letter + ' ' + a.strong + '</text>'; }).join('') +
    [['00', 0], ['06', 90], ['12', 180], ['18', 270]].map((h) => { const q = pt(C, 131, h[1] * Math.PI / 180); return '<text x="' + q[0].toFixed(1) + '" y="' + (q[1] + 3.5).toFixed(1) + '" text-anchor="middle" font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)" paint-order="stroke" stroke="var(--surface)" stroke-width="3">' + h[0] + '</text>'; }).join('') +
    '<text x="' + (C + R0 + RH + 4) + '" y="' + (C + 3.5) + '" font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)">' + mxH + '</text><text x="' + (C + R0 + 3) + '" y="' + (C - 3) + '" font-size="9.5" font-family="var(--mono)" fill="var(--ink-3)">0</text>' : '';
  return '<svg class="fp2" width="' + size + '" height="' + size + '" viewBox="0 0 400 400" role="img" aria-label="协作指纹：内核是四维度雷达，中环是 24 小时节律带，外环每段是该小时的会话数、按 Agent 堆叠" style="overflow:visible;max-width:100%;height:auto"><circle cx="200" cy="200" r="' + (R0 + RH + 2) + '" fill="var(--surface)" stroke="var(--line)"/><circle cx="200" cy="200" r="' + R0 + '" fill="none" stroke="var(--line)"/><circle cx="200" cy="200" r="' + (R0 + RH / 2) + '" fill="none" stroke="var(--hair)" stroke-dasharray="2 3"/><path d="' + band + inner + '" fill="var(--h2)" fill-opacity=".7" fill-rule="evenodd"/><path d="' + ticks + '" stroke="var(--ink-3)" stroke-width="1"/><circle cx="200" cy="200" r="96" fill="var(--bg)" stroke="var(--line)"/><circle cx="200" cy="200" r="' + ((rad(55) + rad(45)) / 2).toFixed(1) + '" fill="none" stroke="var(--sunken)" stroke-width="' + (rad(55) - rad(45)).toFixed(1) + '"/><circle cx="200" cy="200" r="' + rad(55) + '" fill="none" stroke="var(--hair)"/><circle cx="200" cy="200" r="' + rad(45) + '" fill="none" stroke="var(--hair)"/><path d="' + spokes + '" stroke="var(--line)" stroke-width="1"/><g class="radar"><path d="M' + poly + 'Z" fill="var(--ink-1)" fill-opacity=".14" stroke="var(--ink-1)" stroke-width="2" stroke-linejoin="round"/>' + verts + '</g><g class="ring">' + ring + '</g><g class="dots">' + dots + '</g>' + lbl + '</svg>';
}
TIPS.fph = (h) => { const F = CUR.fp; if (!F) return ''; const xs = F.byH[+h]; const by = AG.map((a) => [a, xs.filter((s) => s.a === a.id).length]).filter((x) => x[1]); return '<b>' + h + ':00–' + (+h + 1) + ':00 · ' + xs.length + ' 个会话</b>\n' + (by.length ? by.map((x) => '<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:' + x[0].c + ';vertical-align:-1px"></span> ' + x[0].short + ' ' + x[1]).join(' · ') : '这个小时没有会话') + '\n<span style="opacity:.75">' + (S.persona.fpHour === +h ? '再点一次收起' : '点击展开这个小时的会话点') + '</span>'; };
PAGES.persona = () => {
  const per = PERIODS[S.persona.period];
  const L = personaScope([per[0], per[1]]); const p = persona(L);
  const note = personaScopeNote();
  const months = ['jun', 'jul', 'aug', 'sep'].map((k) => ({ k, lbl: '2026-0' + ({ jun: 6, jul: 7, aug: 8, sep: 9 })[k], p: persona(personaScope([PERIODS[k][0], PERIODS[k][1]])) }));
  const prevKey = { sep: 'aug', aug: 'jul', jul: 'jun', jun: null, '90': null, all: null }[S.persona.period];
  const prev = prevKey ? persona(personaScope([PERIODS[prevKey][0], PERIODS[prevKey][1]])) : null;
  const filt = (S.project ? PJI[S.project].name + ' · ' : '') + (S.agents.size < 5 ? AG.filter((a) => S.agents.has(a.id)).map((a) => a.short).join(' / ') + ' · ' : '');
  const right = '<div class="seg" role="group" aria-label="统计周期">' + [['sep', '9 月'], ['90', '近 90 天'], ['all', '全部']].map((x) => '<button type="button" data-act="period" data-v="' + x[0] + '" class="' + (S.persona.period === x[0] ? 'on' : '') + '">' + x[1] + '</button>').join('') + '</div><button type="button" class="btn gh" data-act="method">' + ic('info', 14) + '算法说明</button><button type="button" class="btn" data-act="share">' + ic('share', 14) + '导出分享卡</button><button type="button" class="btn ai" data-act="ask" data-ctx="persona">' + ic('spark', 14) + '让 Agent 写一份自述</button>';
  const allOff = AG.every((a) => S.srcOff.has(a.id));
  if (!p.ok) {
    const frac = Math.min(1, L.length / 30); const a = frac * Math.PI * 2; const x = 56 + 46 * Math.sin(a), y = 56 - 46 * Math.cos(a);
    const relax = peRelax([per[0], per[1]]);
    return tbar('协作人格', filt + '基于 ' + L.length + ' 个会话 · ' + per[2], right) + '<div class="content" id="content"><div class="card pad pe-low"><svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true"><circle cx="56" cy="56" r="46" fill="none" stroke="var(--line)" stroke-width="10"/>' + (frac > 0 ? '<path d="M56 10 A46 46 0 ' + (frac > 0.5 ? 1 : 0) + ' 1 ' + x.toFixed(1) + ' ' + y.toFixed(1) + '" fill="none" stroke="var(--ink-1)" stroke-width="10" stroke-linecap="round"/>' : '') + '<text x="56" y="62" text-anchor="middle" font-size="18" font-weight="700" font-family="var(--mono)" fill="var(--ink-1)">' + L.length + '/30</text></svg><div class="col" style="flex:1;min-width:240px">' +
      (allOff ? '<h2 class="serif" style="margin:0;font-size:24px">所有数据源已停用</h2><p style="margin:0;color:var(--ink-2)">人格需要会话数据。到「设置 › 数据源」重新启用至少一个 Agent，分析会立即恢复。</p><div class="row"><button type="button" class="btn p" data-act="openSettings" data-tab="sources">打开设置 · 数据源</button></div>'
        : '<h2 class="serif" style="margin:0;font-size:24px">再积累 ' + (30 - L.length) + ' 个会话后揭晓</h2><p style="margin:0;color:var(--ink-2)">当前筛选下样本太少，人格需要足够的会话才可靠。' + (relax.length ? '放宽下面任一筛选可以补到：' : '可以放宽筛选，或换一个统计周期。') + '</p>' +
        (relax.length ? '<div class="pe-relax">' + relax.map((r) => '<button type="button" class="chip on" data-act="peRelax" data-k="' + r.k + '">' + esc(r.t) + ic('x', 12) + '<b class="mono" style="color:' + (r.n >= 30 ? 'var(--good)' : 'var(--ink-3)') + '">移除后 n≈' + r.n + '</b></button>').join('') + '</div>' : '') +
        '<div class="row" style="flex-wrap:wrap"><button type="button" class="btn p" data-act="clearAllFilters">清除筛选</button><button type="button" class="btn" data-act="period" data-v="all">看全部历史</button></div>') +
      '</div></div></div>';
  }
  CUR.persona = p;
  const traits = [];
  if (p.v.D >= 55) traits.push('高吞吐'); else if (p.v.D <= 45) traits.push('亲自掌舵');
  if (p.v.I >= 55) traits.push('边做边想'); else if (p.v.I <= 45) traits.push('先规划');
  if (p.v.M >= 55) traits.push('多线程'); else if (p.v.M <= 45) traits.push('单线专注');
  if (p.v.V >= 55) traits.push('验收严格'); else if (p.v.V <= 45) traits.push('信任结果');
  traits.push('中英混用');
  const st = p.st;
  const conts = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]).slice(0, 3);
  const recFor = { '方向错误': 'deploy-target', '工具 / 环境失败': 'retry-breaker', '改动过度': 'paper-audit', '误解需求': 'acceptance', '并行会话冲突': 'worktree', '流程过重（子代理）': 'pr-wrapup', '额度 / 用量中断': 'summary-compact' };
  const fitRows = AG.map((a) => { const xs = L.filter((s) => s.a === a.id); const st2 = stats(xs); const f = fitOf(xs); const okp = st2.ok / 100; const ci = f == null ? null : Math.round(1.96 * Math.sqrt(okp * (1 - okp) / xs.length) * 100); return { a, n: xs.length, f, st: st2, ci, off: S.srcOff.has(a.id) }; });
  CUR.peMonths = months;
  const evos = [0, 1, 2, 3].map((i) => peEvidence(L, st, p, i));
  return tbar('协作人格', filt + '基于 ' + L.length + ' 个会话 · ' + new Set(L.map((s) => s.a)).size + ' 个 Agent · ' + per[2] + (note ? ' · ' + note : ''), right) +
    '<div class="content" id="content"><div class="stack">' +
    '<div class="card persona-hero"><div class="col" style="gap:0;min-width:0"><div class="row" style="flex-wrap:wrap"><span class="eb">Your agent collaboration type · 你的协作人格</span><span class="tag" data-tip="维度信号与权重是初版设想，待真实数据校准">实验性</span><span class="bdg">置信度 ' + p.conf + ' · n=' + p.n + '</span></div>' +
    '<div class="letters" data-hero="code">' + p.code.split('').map((ch, i) => { const a = axisView(p, i); return '<button type="button" data-act="axisJump" data-tf="axis|' + i + '"><span class="L">' + ch + '</span><span style="font-size:12px;color:var(--ink-2);white-space:nowrap">' + (ch === '?' ? '未定型' : a.name) + ' <span class="mono" style="color:var(--ink-1);font-weight:600">' + a.strong + '</span></span></button>'; }).join('') + '</div>' +
    '<div class="row" style="align-items:baseline;gap:12px;margin-top:16px;flex-wrap:wrap"><span class="serif" style="font-size:36px;line-height:1.1;font-weight:600">' + p.zh + '</span><span class="serif" style="font-size:24px;font-style:italic;color:var(--ink-3)">' + p.en + '</span></div>' +
    '<p style="margin:12px 0 0;max-width:580px;font-size:14.5px;line-height:1.65;color:var(--ink-2);text-wrap:pretty">' + esc(p.line) + ' 这段时间你平均每个会话只发 ' + f1(st.per) + ' 条消息，Agent 每轮自主走 ' + f1(st.auto) + ' 步；' + Math.round(st.verify) + '% 的会话会要求验证结果。</p>' +
    '<div class="row" style="flex-wrap:wrap;gap:6px;margin-top:12px"><span class="aib">' + ic('spark', 11) + 'AI 撰写</span>' + traits.map((t) => '<span class="tag">' + t + '</span>').join('') + '<button type="button" class="btn sm gh" data-act="notMe">不像我？</button></div>' +
    (note ? '<div class="cap" style="margin-top:8px;font-size:11.5px">' + esc(note) + '：人格只按时间、Agent 与项目计算，和侧栏、报告一致</div>' : '') +
    // 演变：月份码 + 四轴折线（评审 A2-V06）
    '<div style="margin-top:22px"><div class="eb" style="margin-bottom:8px">演变 · 按月重算 · 点击切换</div><div class="evo">' + months.map((m, i) => '<button type="button" data-act="period" data-v="' + m.k + '" class="' + (S.persona.period === m.k ? 'on' : '') + '"><span class="mono" style="display:block;font-size:10px;color:var(--ink-3)">' + m.lbl + '</span><span class="mono" style="display:block;font-size:14px;font-weight:700;letter-spacing:.06em">' + (m.p.ok ? m.p.code : '—') + '</span><span style="display:block;font-size:11px;color:var(--ink-2)">' + (m.p.ok ? m.p.zh : '样本不足') + '</span></button>' + (i < 3 ? ic('arrow', 13, 'color:var(--ink-4)') : '')).join('') + '</div>' +
    '<div class="vz pe-evo" data-vz="pe-evo"></div><div class="cap" style="font-size:11px;margin-top:4px">四个维度逐月的值 · 中线 50，灰带 45–55 为未定型 · 跨过中线的月份字母会变</div></div></div>' +
    '<div class="fp-wrap" data-hero="fp"><button type="button" class="btn sm gh" data-act="reveal" style="position:absolute;right:8px;top:8px;z-index:2">重播揭晓</button>' + fp2SVG(L, p, 400, { interactive: true, labels: true }) +
    '<div class="pe-fp-legend"><span class="row" style="gap:5px"><span style="width:10px;height:10px;border-radius:2px;background:var(--ink-1);opacity:.7"></span>内核 · 四维度雷达（0 在中心）</span><span class="row" style="gap:5px"><span style="width:10px;height:5px;border-radius:2px;background:var(--h2)"></span>中环 · 24 小时节律</span><span class="row" style="gap:5px"><span class="dot" style="background:var(--a1)"></span>外环 · 每段是该小时的会话数，按 Agent 堆叠；点击展开' + (S.persona.fpHour != null ? ' · <button type="button" class="lnk" data-act="fpHour" data-h="' + S.persona.fpHour + '">收起 ' + S.persona.fpHour + ' 时</button>' : '') + '</span></div></div></div>' +
    '<div class="three" style="grid-template-columns:minmax(0,1.6fr) minmax(0,1fr) minmax(0,1fr)">' +
    '<div class="card pad" id="axesCard"><div class="hd"><div class="grow"><span class="ct">四个维度</span></div><div class="seg" role="group" aria-label="对照组"><button type="button" data-act="vs" data-v="past" class="' + (S.persona.vs === 'past' ? 'on' : '') + '">与过去的我</button><button type="button" data-act="vs" data-v="pop" class="' + (S.persona.vs === 'pop' ? 'on' : '') + '">与全体用户</button></div></div>' +
    '<div class="vz" data-vz="pe-axes"></div>' +
    '<div class="pe-ev">' + evos.map((e, i) => { const a = axisView(p, i); return '<div class="pe-evi"><span class="row" style="justify-content:space-between;gap:6px"><span class="mono pe-evl">' + a.ax.dim + ' · ' + a.letter + '</span>' + VZ.spark(e.vals, { bars: true, w: 72, h: 20, color: 'var(--h3)', last: 'var(--h3)', label: e.lbl }) + '</span><span class="cap" style="font-size:11px">' + esc(e.txt) + '</span><span class="cap" style="font-size:10.5px;color:var(--ink-4)">' + esc(e.lbl) + '</span></div>'; }).join('') + '</div>' +
    '<div class="cap" style="margin-top:10px;font-size:11.5px">细刻度：' + (S.persona.vs === 'pop' ? '全体用户均值（示例）' : prev && prev.ok ? '上个月的位置' : '无可比时段') + ' · 中线为 50；落在 45–55（灰带）记为未定型</div></div>' +
    '<div class="card pad"><div class="ct" style="margin-bottom:10px">优势与盲点</div><div class="col" style="gap:8px">' +
    [['整段委托', '单轮平均 ' + f1(st.auto) + ' 步自主执行。', p.v.D >= 55], ['验收严格', Math.round(st.verify) + '% 的会话要求验证。', p.v.V >= 55], ['节奏稳定', '日均 ' + f1(p.avgS) + ' 个会话。', true]].filter((x) => x[2]).map((x) => '<div class="row" style="align-items:flex-start;font-size:12.5px;line-height:1.45">' + ic('okc', 15, 'color:var(--good);margin-top:1px') + '<span style="color:var(--ink-2)"><b style="color:var(--ink-1)">' + x[0] + '</b> ' + x[1] + '</span></div>').join('') +
    '<div style="height:1px;background:var(--hair);margin:4px 0"></div>' +
    (conts.length ? conts.map((c) => '<div class="row" style="align-items:flex-start;font-size:12.5px;line-height:1.45">' + ic('alert', 15, 'color:var(--crit);margin-top:1px') + '<span style="color:var(--ink-2);flex:1"><b style="color:var(--ink-1)">' + c[0] + '</b> 出现在 ' + c[1] + ' 个会话。 <button type="button" class="lnk" data-act="openRec" data-id="' + recFor[c[0]] + '">→ 建议</button></span></div>').join('') : '<span class="cap">这段时间没有明显盲点。</span>') + '</div></div>' +
    // 契合度：中性条 + 透明度随 n + 95% 区间（评审 A2-V07）；来源停用的 Agent 不可点（BUG-49）
    '<div class="card pad"><div class="row" style="justify-content:space-between;margin-bottom:10px"><span class="ct">与 Agent 的契合度</span><span class="cap" style="font-size:11px">0–100 · 带 95% 区间</span></div><div class="col" style="gap:9px">' +
    fitRows.map((r) => '<' + (r.off || !r.n ? 'div' : 'button type="button" data-act="soloAgent" data-a="' + r.a.id + '"') + ' class="pe-fit' + (r.off ? ' off' : '') + '"><span class="row" style="font-size:12.5px;width:100%"><span class="dot" style="background:' + r.a.c + '"></span><span style="flex:1">' + r.a.name + '</span>' + (r.off ? '<span class="cap" style="font-size:11px">来源已停用</span>' : '<b class="mono">' + (r.f == null ? '—' : r.f) + '</b>') + '</span><span class="pe-fit-bar" style="opacity:' + (r.n < 20 ? 0.5 : 1) + '"><span class="fill" style="width:' + (r.f || 0) + '%"></span>' + (r.ci != null ? '<span class="ci" style="left:' + Math.max(0, r.f - r.ci) + '%;width:' + Math.min(100 - Math.max(0, r.f - r.ci), r.ci * 2) + '%"></span>' : '') + '</span><span style="font-size:11px;color:var(--ink-3)">' + (r.off ? '到设置里重新启用后参与计算' : r.n < 5 ? '样本少（' + r.n + ' 个会话），不计分' : 'n=' + r.n + (r.n < 20 ? '（样本少）' : '') + ' · ±' + r.ci + ' · 摩擦率 ' + f1(r.st.fric) + '% · 完成率 ' + Math.round(r.st.ok) + '%') + '</span></' + (r.off || !r.n ? 'div' : 'button') + '>').join('') +
    '</div><div class="cap" style="margin-top:10px;font-size:11px">综合完成率与摩擦率 · 条越淡样本越少 · 点击只看该 Agent 的人格</div></div>' +
    '</div></div></div>';
};
PAGES.persona.after = () => {
  const p = CUR.persona; if (!p || !$('[data-vz="pe-axes"]')) return;
  const prevKey = { sep: 'aug', aug: 'jul', jul: 'jun', jun: null, '90': null, all: null }[S.persona.period];
  const prev = prevKey ? persona(personaScope([PERIODS[prevKey][0], PERIODS[prevKey][1]])) : null;
  VZ.mount('pe-axes', { type: 'diverging', title: '协作人格 · 四个维度', rows: peAxisRows(p, prev), domain: [-1, 1], colors: ['var(--ink-2)', 'var(--ink-2)'], deadband: [-0.1, 0.1], format: peNum, refLabel: S.persona.vs === 'pop' ? '全体用户（示例）' : '上月', axis: false, rowH: 34, barH: 10, legend: false, animate: false, onSelect: () => ACT.axisJump() });
  const months = CUR.peMonths || [];
  VZ.mount('pe-evo', { type: 'line', title: '四个维度 · 逐月', height: 150, legend: 'top', animate: false, points: true, endLabels: false, x: { values: months.map((m) => m.lbl.slice(5) + ' 月') }, y: { min: 0, max: 100, format: 'int', ticks: 4 }, refs: [{ y: 55, color: 'var(--line)' }, { y: 50, label: '中线 50' }, { y: 45, color: 'var(--line)' }],
    series: [['D', '自主 D', 'var(--ink-1)', false], ['I', '结构 I', 'var(--ink-2)', true], ['M', '并发 M', 'var(--ink-3)', false], ['V', '求证 V', 'var(--h3)', true]].map((k) => ({ name: k[1], color: k[2], dash: k[3], values: months.map((m) => m.p.ok ? Math.round(m.p.v[k[0]]) : null) })) });
};
TIPS.axis = (i) => { const p = CUR.persona; if (!p) return ''; const a = axisView(p, +i); return '<b>' + a.ax.dim + '：' + a.ax.L + ' ' + a.ax.Ln + ' ↔ ' + a.ax.R + ' ' + a.ax.Rn + '</b>\n' + a.ax.q + '\n<span style="opacity:.8">信号：' + a.ax.sig + '</span>'; };
Object.assign(ACT, {
  period: (el) => { S.persona.period = el.dataset.v; S.persona.fpHour = null; render(); },
  vs: (el) => { S.persona.vs = el.dataset.v; render(); },
  fpHour: (el) => { const h = +el.dataset.h; S.persona.fpHour = S.persona.fpHour === h ? null : h; tipOff(); render(); },
  peRelax: (el) => { const k = el.dataset.k; if (k === 'project') S.project = null; else if (k === 'agents') AG.forEach((a) => S.agents.add(a.id)); else S.persona.period = 'all'; render(); },
  axisJump: () => { const c = $('#axesCard'); if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'center' }); c.animate([{ boxShadow: '0 0 0 3px var(--focus)' }, { boxShadow: '0 0 0 0 transparent' }], { duration: 900 }); } },
  notMe: (el) => openDD(el, [{ h: '哪里不像你？' }, { t: '描述太夸张了', v: 1 }, { t: '某个维度判断不对', v: 2 }, { t: '这段时间不代表我', v: 3 }, { t: '其他', v: 4 }], () => toast('已记录反馈，下次计算会降低相关信号的权重')),
  soloAgent: (el) => {
    const id = el.dataset.a;
    if (S.srcOff.has(id)) { toast(agent(id).name + ' 已在设置中停用，先到「设置 › 数据源」启用', { act: '打开设置', onAct: () => openSettings('sources') }); return; }
    S.agents.clear(); S.agents.add(id); render(); toast('已只看 ' + agent(id).name + '；点侧边栏同一个 Agent 可恢复全部');
  },
  clearAllFilters: () => {
    S.project = null; S.topic = null; S.outcome = null; S.fric = null; S.hour = null; AG.forEach((a) => S.agents.add(a.id)); render();
    if (AG.every((a) => S.srcOff.has(a.id))) toast('筛选已清除，但所有数据源都已停用', { act: '打开设置', onAct: () => openSettings('sources') });
  },
  method: () => openMethod(),
  share: () => openShare(),
  reveal: () => openReveal(),
  openSession: (el) => {
    const s = BYID[el.dataset.id];
    if (!s || !sourceEnabled(s) || S.excluded.has(s.id)) { toast('此会话的来源已停用或已从分析中排除'); return; }
    stopPlay();
    S.agents.add(s.a);
    for (const [key, value] of [['project', s.p], ['topic', s.topic], ['outcome', s.out], ['fric', s.fric], ['hour', s.h]]) {
      if (S[key] != null && S[key] !== value) S[key] = null;
    }
    const w = win(S.range);
    if (s.d !== 120 && (s.d < w[0] || s.d > w[1])) S.range = 0;
    S.sess.sel = s.id; S.sess.mode = 'single'; S.sess.cmp = null; S.sess.q = ''; S.sess.ph = traj(s).T;
    go('sessions');
  }
});
