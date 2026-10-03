/* ============ A7 recommendations ============ */
// A7-only derived numbers (the rec data in 05-data.js is shared with A1 / widgets / exports). The saving is a share of the
// real trajectory, never hours: pct.st / pct.sk = the share the rec's operations (failed calls, approval waits, rework
// turns, resident context …) take of all active time / all tokens, pct.p = the remedy's effectiveness (prior), so the
// expected saving is t = st × p of the time and k = sk × p of the tokens (null = not measured, e.g. the time cost of
// resident context). tokp = the rec's own resident context as a share of all tokens (negative = frees it); n = the before /
// after session counts the 7-day tracking is based on. Live rows carry the same fields from ui.save (97-live-recs.js).
const demoPct = (key, st, sk, p) => ({ st, sk, p, t: st == null ? null : st * p, k: sk == null ? null : sk * p, key });
const REC_X = {
  'ro-allow': { pct: demoPct('approval', 1.7, 0, .9), tok: 0, n: [41, 38] }, 'pr-wrapup': { pct: demoPct('review', 7.2, 6.4, .6), tok: 0.4, n: [12, 11] },
  'deploy-target': { pct: demoPct('deploy', 1.1, .9, .6), tok: 0.1, n: [6, 5] }, 'think-medium': { pct: null, tok: 0, n: [22, 19] },   // like the backend (narrate._save kind model): reasoning tokens are not logged apart → 未估算
  'retry-breaker': { pct: demoPct('retry', 2.4, 2, .8), tok: 0, n: [17, 15] }, worktree: { pct: demoPct('parallel', 1.6, 1.2, .67), tok: 0, n: [9, 10] },
  'citation-checker': { pct: demoPct('citation', 1.4, 1.1, .6), tok: 0.3, n: [9, 7] }, 'remove-figma': { pct: demoPct('figma', null, 1.6, .86), tok: -2.1, n: [186, 171] },
  acceptance: { pct: demoPct('correction', 1.9, 1.7, .6), tok: 0.1, n: [43, 40] }, 'latex-hook': { pct: demoPct('latex', .84, .6, .67), tok: 0, n: [5, 3] },
  'summary-compact': { pct: demoPct('compaction', 1.3, 1.9, .6), tok: 0.1, n: [9, 8] }, 'paper-audit': { pct: demoPct('paper', 2.8, 2.5, .6), tok: 0.5, n: [19, 16] },
  headless: { pct: demoPct('polling', 5.6, .8, .5), tok: 0, n: [8, 7] }
};
Object.values(REC_X).forEach((x) => { x.tokp = Math.round(x.tok * 76) / 100; });   // demo: 1k resident tokens ≈ 0.76 % of all tokens
const REC_UP = /一致率|比例|完成率|并行会话数/;   // metrics where higher is better; everything else is good when it goes down
const recX = (id) => REC_X[id] || { pct: null, tok: 0, tokp: 0, n: [10, 10] };
const recPct = (id) => recX(id).pct || null;
// 0.04 →「<0.1%」, 3.21 →「3.2%」, 12.6 →「13%」(the same rounding as recommend/narrate.py pct_text)
const fmtPct = (v) => v == null ? '—' : v <= 0 ? '0%' : v < 0.1 ? '<0.1%' : v < 10 ? f1(v) + '%' : Math.round(v) + '%';
// count-up attributes for a percentage (none below 0.1 %, where the text is「<0.1%」)
const pctCount = (v, ck) => v == null || v < 0.1 ? '' : ' data-count="' + (v >= 10 ? Math.round(v) : (+v).toFixed(1)) + '"' + (v >= 10 ? '' : ' data-dec="1"') + (ck ? ' data-ck="' + ck + '"' : '');
// sort key = the main number the cards show: the time share, the token share where time is not measured (resident
// context); recs without a share sort last
const recRank = (id) => { const p = recPct(id); return !p ? -1 : p.t != null ? p.t : p.k != null ? p.k : -1; };
const pctLabel = (p) => [p.t != null ? '省时 ' + fmtPct(p.t) : '', p.k != null ? '省 token ' + fmtPct(p.k) : ''].filter(Boolean).join(' · ');
// the one-line saving every surface prints (A1 本周建议, menubar, widgets, palette, exports, Lite); without a share the
// row's own gain (live: the backend's evidence line) or 未估算
const recGain = (r) => { const p = recPct(r.id); return p ? pctLabel(p) : r.live && r.gain && r.gain !== '—' ? r.gain : '未估算'; };
// 对应操作占比: what the rec's operations take of the real trajectory before the effectiveness
const recShare = (r) => { const p = recPct(r.id); if (!p || (p.st == null && p.sk == null)) return r.gain; return '对应操作占' + [p.st != null ? '时间 ' + fmtPct(p.st) : '', p.sk != null ? 'token ' + fmtPct(p.sk) : ''].filter(Boolean).join(' · '); };
const recBasis = (r) => { const p = recPct(r.id); return p && p.basis ? p.basis : p ? recShare(r) + ' × 生效率 ' + p.p : r.saveBasis || (r.dim === 'model' ? '降低思考档位只影响推理 token，轨迹里没有可靠地分开记录推理 token，暂不折算' : '没有可折算的问题证据'); };
// The combined saving of several recs (Lite 开屏合计 …), never above what the operations really take — the same total as
// recommend/narrate.py total_saving: alternatives on one problem (key) count once (the best); problems on one operation
// pool (g: tool calls, approval waits, rework turns, resident context) share at most the pool's share of the trajectory
// (cap), so overlapping shares are scaled down in proportion; all pools together never exceed the whole trajectory;
// each rec keeps its own effectiveness. (The old Σ clamped at 100 printed「100%」once a few large shares added up, F10.)
function recTotal(rows) {
  const best = {};
  rows.forEach((r) => {
    const p = recPct(r.id); if (!p) return; const key = p.key || r.id;
    [['t', 'st'], ['k', 'sk']].forEach(([f, sf]) => {
      if (p[f] == null) return;
      const share = p[sf] != null ? p[sf] : p[f];
      const cap = p.cap && p.cap[f] != null ? Math.max(p.cap[f], share) : 100; // a pool holds at least the share it priced
      const e = { pct: p[f], share, g: p.g || key, cap };
      const id = key + '\u0000' + f; if (!best[id] || e.pct > best[id].pct) best[id] = Object.assign(e, { f });
    });
  });
  const es = Object.values(best); if (!es.length) return null;
  const sum = (f) => {
    const xs = es.filter((e) => e.f === f); if (!xs.length) return null;
    const pools = {}; xs.forEach((e) => { const q = pools[e.g] || (pools[e.g] = { used: 0, cap: 100 }); q.used += e.share; q.cap = Math.min(q.cap, e.cap); });
    const sc = (e) => { const q = pools[e.g]; return q.used > 0 ? Math.min(1, q.cap / q.used) : 1; };
    const whole = xs.reduce((a, e) => a + e.share * sc(e), 0); const all = whole > 0 ? Math.min(1, 100 / whole) : 1;
    return xs.reduce((a, e) => a + e.pct * sc(e) * all, 0);
  };
  return { t: sum('t'), k: sum('k') };
}
const recTok = (id) => { const t = recX(id).tokp; return t == null ? '—' : t > 0 ? '+' + fmtPct(t) : t < 0 ? '−' + fmtPct(-t) : '0'; };
// Which agents a rec applies to, parsed from its compat string (identity colours only).
function recAgents(r) {
  if (r.live && r.agents) { const on = r.agents.filter((i) => AGI[i]); return on.length ? on : r.agents; }   // live: the rec's verified target agents only (未核实 never reads as 适用)
  if (/所有/.test(r.compat)) return AG.map((a) => a.id);
  const ids = []; if (/Claude/.test(r.compat)) ids.push('cc'); if (/Codex/.test(r.compat)) ids.push('cx'); if (/Kimi/.test(r.compat)) ids.push('km'); if (/DeepSeek/.test(r.compat)) ids.push('ds'); if (/OpenCode/.test(r.compat)) ids.push('oc');
  return ids.length ? ids : ['cc'];
}
// live: which target agents get a converted equivalent instead of the native format
// (only adaptation_required converts; manual is said as such; unknown support is 未核实, never compatible)
const recShorts = (ids) => ids.map((i) => agent(i).short).join(' / ');
function recConvNote(r) {
  const shown = recAgents(r); const pick = (a) => (a || []).filter((i) => shown.indexOf(i) >= 0);
  const conv = r.conv ? pick(r.conv) : shown.filter((i) => (r.native || []).indexOf(i) < 0), man = pick(r.manual), unv = r.unverified || [];
  const out = []; if (conv.length) out.push(recShorts(conv) + ' 转为等价配置'); if (man.length) out.push(recShorts(man) + ' 需手动配置'); if (unv.length) out.push(recShorts(unv) + ' 未核实');
  return out.length ? out.join('；') : shown.length ? '全部原生支持' : '没有已核实的 Agent';
}
function agentDots(r, names) { const ids = recAgents(r); const unv = r.live ? r.unverified || [] : []; return '<span class="rc-ag" data-tip="适用：' + esc(ids.length ? ids.map((i) => agent(i).name).join('、') : '暂无已核实的 Agent') + (r.live ? (r.conv && r.conv.length ? '（' + recShorts(r.conv) + ' 为转换后的等价配置）' : '') + (unv.length ? '；未核实：' + unv.map((i) => agent(i).name).join('、') : '') : /转换/.test(r.compat) ? '（Codex 为转换后的等价配置）' : '') + '">' + ids.map((i) => '<span class="dot" style="background:' + agent(i).c + '"></span>').join('') + (names ? '<span>' + (ids.length === AG.length ? '所有 Agent' : ids.length ? ids.map((i) => agent(i).short).join(' · ') : 'Agent 未核实') + '</span>' : '') + '</span>'; }
// Install scope (BUG-22): recs that write under ~/.claude can also be installed into one project; the path follows.
const recScoped = (r) => /^~\/\.claude\/(skills|agents|settings)/.test(r.target);
const scopeProj = () => S.project || S.proj.sel || 'confluo';
const scopeProjName = () => (PJI[scopeProj()] || { name: '—' }).name;   // live spine may have no project yet
function recTarget(r) { return S.recs.scope === 'proj' && recScoped(r) ? scopeProjName() + '/' + r.target.replace(/^~\//, '') : r.target; }
// File verdict (BUG-23): a diff whose context lines are only front-matter / blanks / comments creates a new file.
function fileKind(r) { if (r.file.some((l) => l[1] === '-')) return '删除项'; const ctx = r.file.filter((l) => l[1] === ' ' && l[0].trim() && !/^(---|#)/.test(l[0].trim())); return ctx.length ? '修改' : '新建'; }
const recNoEv = (r) => !!(r && r.live && !r.evN);   // live catalog/profile match with no session behind it
const r0live = () => RECS.some((x) => x.live);
const AUD_D = ['刚开始用 Agent', '会改配置、会用 Git', '会写脚本与定时任务'];
const lvlIcon = (n) => '<span class="lvl" aria-hidden="true">' + [1, 2, 3, 4].map((k) => '<i class="' + (k <= n ? 'f' : '') + '"></i>').join('') + '</span>';
let TRK_SPECS = [];
PAGES.recs = () => {
  const R = S.recs; let vis = visibleRecs();
  const peek = R.peek && RECI[R.peek] && !R.gone.has(R.peek) ? RECI[R.peek] : null;   // opened from elsewhere: shown without changing the filters (BUG-80)
  if (peek && !vis.includes(peek)) vis = vis.concat([peek]);
  const inLv = vis.filter((r) => R.lv.has(r.lvl) || r === peek);
  const list = inLv.filter((r) => R.dim === 'all' || r.dim === R.dim || r === peek).sort((a, b) => recRank(b.id) - recRank(a.id));
  const cnt = (d) => inLv.filter((r) => d === 'all' || r.dim === d).length;
  const sel0 = RECI[R.sel] && list.includes(RECI[R.sel]) ? RECI[R.sel] : list[0];
  if (sel0) R.sel = sel0.id;
  const card = (r) => { const inst = S.installed.get(r.id); const x = recX(r.id); return '<div class="card rcard' + (r.id === R.sel ? ' sel' : '') + (inst ? ' inst' : '') + '" data-act="selRec" data-id="' + r.id + '" role="button" tabindex="0" aria-pressed="' + (r.id === R.sel) + '" aria-label="' + esc(r.title) + '"><div class="rc-top"><span class="row" style="gap:5px">' + ic(r.icon, 14, 'color:var(--ink-1)') + '<b class="mono">' + r.type + '</b></span><span class="row" style="gap:5px" data-tip="难度 ' + LEVELS[r.lvl] + '">' + lvlIcon(r.lvl) + LEVELS[r.lvl] + '</span>' + (r === peek && !visibleRecs().includes(r) ? '<span class="tag">高于当前水平筛选</span>' : '') + (!x.pct ? '<span class="rc-save"' + (r.live ? ' data-tl="rec-nosave"' : '') + ' data-tip="' + esc(recBasis(r)) + '"><span class="u">未估算</span></span>' : '<span class="rc-save" data-tip="预计节省：占全部协作时长 / 全部 token 的比例（对应操作占比 × 生效率）">' + (x.pct.t != null ? '<span class="u">省时</span><b' + pctCount(x.pct.t, 'rc:' + r.id) + '>' + fmtPct(x.pct.t) + '</b>' : '') + (x.pct.k != null ? '<span class="u">' + (x.pct.t != null ? '· ' : '省 ') + 'token</span><b' + pctCount(x.pct.k, 'rk:' + r.id) + '>' + fmtPct(x.pct.k) + '</b>' : '') + '</span>') + '</div><div class="rc-title">' + esc(r.title) + '</div><div class="rc-why"' + (r.live ? ' data-tl="rec-why" style="display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden"' : '') + '>' + esc(r.why) + ' ' + (recNoEv(r) ? '<span class="cap" data-tl="rec-match">' + esc(r.ev) + '</span>' : '<button type="button" class="lnk" data-act="recEvidence" data-id="' + r.id + '">依据 · ' + r.ev + ' →</button>') + '</div><div class="rc-meta">' + agentDots(r, true) + '<span class="rc-tok' + (x.tokp < 0 ? ' good' : '') + '" data-tip="常驻 token 占比：每次请求都带上的上下文占全部 token 的比例（负数为释放）">' + ic('db', 11) + (x.tokp ? '常驻 ' + recTok(r.id) : x.tokp === 0 ? '不占常驻' : '常驻 —') + '</span></div><div class="rc-foot"><span class="mono rc-gain" data-tip="对应操作在全部轨迹里的占比（实测），乘以生效率即预计节省">' + esc(recShare(r)) + '</span>' + (inst ? '<span class="tag">' + (inst.days >= 7 ? '已安装 · ' + VERDICT[trackStats(r).verdict][0] : '已安装 · 追踪中 ' + inst.days + ' / 7 天') + (inst.scope === 'proj' ? ' · 仅 ' + esc((inst.target || '').split('/')[0]) : '') + '</span>' : '<button type="button" class="btn sm gh" data-act="dismissRec" data-id="' + r.id + '">不适用</button>' + recPrimaryBtn(r, true)) + '</div></div>'; };
  // g0 (live): profile matches without session evidence; g3 (live): 资料库推荐 (catalog-only), always last
  const g3 = list.filter((r) => r.lib), ev = list.filter((r) => !r.lib);
  const g0 = ev.filter(recNoEv), g1 = ev.filter((r) => r.lvl <= 2 && !recNoEv(r)), g2 = ev.filter((r) => r.lvl >= 3 && !recNoEv(r));
  const libN = g3.length && R.dim === 'all' && LVR.applied && LVR.applied.counts && LVR.applied.counts.library != null && R.lv.size === 4 ? LVR.applied.counts.library : g3.length;
  let detail = empty('没有符合筛选的建议');
  TRK_SPECS = [];
  if (sel0) {
    const r = sel0; const inst = S.installed.get(r.id); const x = recX(r.id);
    const tabs = [['why', '说明与依据'], ['preview', '预览'], ['tut', r.live && !r.steps.length ? '教程' : '教程 · ' + r.steps.length + ' 步'], ['track', '效果追踪']];
    let body = '';
    if (R.tab === 'why') body = '<div class="col" style="gap:12px;font-size:13px;line-height:1.6;color:var(--ink-2)"><p style="margin:0">' + esc(r.why) + '</p><div class="row" style="flex-wrap:wrap"><span class="tag">' + esc(r.compat) + '</span></div>' +
      '<div class="rc-ev"><div class="row" style="justify-content:space-between;flex-wrap:wrap"><span class="eb">依据 · 可回看</span>' + (recNoEv(r) ? '<span class="cap">' + esc(r.ev) + ' · 还没有直接相关的会话</span>' : '<button type="button" class="btn sm" data-act="recEvidence" data-id="' + r.id + '">' + ic('sessions', 13) + '在会话里回看 ' + r.ev + '</button>') + '</div><div class="rc-base">' + r.track.map((t) => '<span><span class="cap">' + t[0] + '</span><b class="mono">' + (t[1] == null ? '—' : t[1]) + '</b><span class="cap">' + t[3] + '</span></span>').join('') + '</div><span class="cap">安装前 7 天基准 · 效果追踪的对照组 · ' + x.n[0] + ' 个会话</span></div>' +
      '<p style="margin:0" class="cap" data-tip="不原生支持的 Agent 会自动转换成等价形式（例如 Skill → AGENTS.md 片段）">节省比例 = 对应操作在全部轨迹里的时间 / token 占比 × 生效率（先验）</p></div>';
    else if (R.tab === 'preview' && r.live && !r.target && !r.file.length) body = '<div class="col" data-tl="rec-pv-plan" style="gap:10px;align-items:flex-start;font-size:13px;line-height:1.6;color:var(--ink-2)"><span class="eb">将写入</span><p style="margin:0">具体文件由安装预览生成：Orbit 先读取来源，按你的 Agent 逐个生成差异，确认后才写入，写入前自动备份。</p><span class="eb">其他 Agent</span><span style="font-size:12px">' + esc(recConvNote(r)) + '</span>' + recPrimaryBtn(r) + '</div>';
    else if (R.tab === 'preview') body = '<div class="rc-pv"><div class="rc-pv-f"><div class="col" style="gap:4px;font-size:12px;min-width:0"><span class="eb">将写入</span><span class="mono rc-path">' + esc(recTarget(r)).replace(/\//g, '/<wbr>') + '</span><span class="row" style="margin-top:4px;padding:4px 8px;border-radius:6px;background:var(--sunken)">' + ic('file', 13) + '<span class="mono" style="font-size:12px;font-weight:600">' + esc(r.target.split('/').pop()) + '</span><span class="mono" style="margin-left:auto;font-size:11px;color:' + (fileKind(r) === '删除项' ? 'var(--crit)' : 'var(--good)') + '">' + fileKind(r) + '</span></span></div><div class="col" style="gap:4px;font-size:12px;min-width:0"><span class="eb rc-eb">安装到' + (recScoped(r) && !S.project ? '<span class="rc-i" data-tip="项目取自侧栏筛选；未筛选时用「项目习惯」里选中的项目" aria-label="说明">' + ic('info', 12) + '</span>' : '') + '</span>' +
      (recScoped(r) ? '<label class="row" style="font-size:12px"><input type="radio" name="scope" ' + (R.scope === 'global' ? 'checked ' : '') + 'data-chg="recScope" value="global" style="accent-color:var(--ink-1)">全局（所有项目）</label><label class="row" style="font-size:12px"><input type="radio" name="scope" ' + (R.scope === 'proj' ? 'checked ' : '') + 'data-chg="recScope" value="proj" style="accent-color:var(--ink-1)">仅 ' + esc(scopeProjName()) + '</label>' : /教程|剪贴板/.test(r.target) ? '<span class="cap">不写入文件</span>' : '<span class="cap">已限定项目 · ' + esc(r.target.split('/')[0]) + '</span>') +
      '<span class="eb" style="margin-top:8px">其他 Agent</span><span style="font-size:12px;line-height:16px;color:var(--ink-2)">' + (r.live ? recConvNote(r) : /Codex|所有/.test(r.compat) ? '同时生成 Codex 等价配置' : 'Codex / Kimi 转为 AGENTS.md 片段') + '</span></div></div><div style="min-width:0"><div class="row" style="justify-content:space-between;margin-bottom:6px"><span class="mono" style="font-size:12px;font-weight:600">' + esc(r.target.split('/').pop()) + '</span>' + (r.live && !r.file.length ? '' : '<button type="button" class="btn sm gh" data-act="copyRec" data-id="' + r.id + '">' + ic('copy', 13) + '复制</button>') + '</div>' + (r.live && !r.file.length ? '<div class="col" data-tl="rec-pv-nofile" style="gap:10px;align-items:flex-start;padding:12px 14px;border-radius:9px;background:var(--sunken);font-size:12.5px;line-height:1.6;color:var(--ink-2)"><span>这条建议没有附带文件正文。具体内容由安装预览按你的 Agent 逐个生成差异，确认后才写入，写入前自动备份。</span>' + recPrimaryBtn(r) + '</div>' : codeBlock(r.file)) + '</div></div>';
    else if (R.tab === 'tut' && r.live && !r.steps.length) body = LV.na('这条建议没有分步教程，可在「预览」里看将写入的内容。');
    else if (R.tab === 'tut') body = '<ol style="margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px">' + r.steps.map((s2, i) => '<li class="row" style="align-items:flex-start;gap:10px"><span class="mono" style="width:22px;height:22px;flex:none;border-radius:50%;background:var(--ink-1);color:var(--surface);font-size:11px;font-weight:700;line-height:22px;text-align:center">' + (i + 1) + '</span><span style="font-size:13px;line-height:1.55;padding-top:1px">' + esc(s2) + '</span></li>').join('') + '</ol><div class="cap" style="margin-top:12px">外部链接会在默认浏览器中打开；命令都可以复制。</div>';
    else body = inst ? trackView(r, inst) : '<div class="col" style="gap:10px;align-items:flex-start"><span style="font-size:13px;line-height:18px;color:var(--ink-2)" data-tip="安装后 7 天逐项对比，给出 95% 区间与结论">安装后开始追踪，对比安装前后各 7 天</span><span class="eb">基准 · 安装前 7 天 · ' + x.n[0] + ' 个会话</span><div class="rc-base">' + r.track.map((t) => '<span><span class="cap">' + t[0] + '</span><b class="mono">' + (t[1] == null ? '—' : t[1]) + '</b><span class="cap">' + t[3] + '</span></span>').join('') + '</div>' + recPrimaryBtn(r) + '</div>';
    detail = '<div class="card" style="overflow:hidden"><div style="padding:14px 18px 0" class="col"><div class="row" style="flex-wrap:wrap;font-size:12px;color:var(--ink-2)">' + ic(r.icon, 14, 'color:var(--ink-1)') + '<b class="mono">' + r.type + '</b>' + lvlIcon(r.lvl) + LEVELS[r.lvl] + '<span style="flex:1"></span><span class="tag">适合：' + AUD[r.aud] + '</span></div><h2 class="serif rc-h">' + esc(r.title) + '</h2>' +
      '<div class="rc-kpis"><div class="rc-kpi rc-kpi-save"><span class="eb">预计节省 · 占全部轨迹</span>' + (!x.pct ? '<span class="v"' + (r.live ? ' data-tl="rec-kpi-nosave"' : '') + '>未估算</span><span class="cap" title="' + esc(recBasis(r)) + '">' + esc(recBasis(r)) + '</span>' : '<span class="v">' + (x.pct.t != null ? fmtPct(x.pct.t) + '<small>时间</small>' : '') + (x.pct.k != null ? (x.pct.t != null ? ' ' : '') + fmtPct(x.pct.k) + '<small>token</small>' : '') + '</span><span class="cap" title="' + esc(recBasis(r)) + '">' + esc(recShare(r) + ' × 生效率 ' + (x.pct.p != null ? +(+x.pct.p).toFixed(2) : '—')) + '</span>') + '</div><div class="rc-kpi"><span class="eb">常驻 token · 占比</span><span class="v' + (x.tokp < 0 ? ' good' : '') + '">' + recTok(r.id) + (x.tokp ? '<small>token</small>' : '') + '</span><span class="cap">' + (x.tokp > 0 ? '每次请求额外带上' : x.tokp < 0 ? '从每次请求中释放' : x.tokp === 0 ? '不占常驻上下文' : '没有可折算的轨迹') + '</span></div><div class="rc-kpi"><span class="eb">适用 Agent</span><span class="row" style="gap:6px;min-height:24px">' + agentDots(r, true) + '</span><span class="cap">' + (r.live ? recConvNote(r) : /转换/.test(r.compat) ? 'Codex 用等价配置' : /所有/.test(r.compat) ? 'AGENTS.md 片段通用' : '其余转为 AGENTS.md') + '</span></div></div></div>' +
      '<div role="tablist" style="display:flex;gap:2px;padding:10px 14px 0;border-bottom:1px solid var(--line);flex-wrap:wrap">' + tabs.map((t) => '<button type="button" role="tab" data-act="recTab" data-v="' + t[0] + '" aria-selected="' + (R.tab === t[0]) + '" style="border:0;background:none;padding:8px 10px;font-size:13px;color:' + (R.tab === t[0] ? 'var(--ink-1)' : 'var(--ink-3)') + ';font-weight:' + (R.tab === t[0] ? 600 : 400) + ';border-bottom:2px solid ' + (R.tab === t[0] ? 'var(--ink-1)' : 'transparent') + ';margin-bottom:-1px">' + t[1] + '</button>').join('') + '</div><div style="padding:14px 18px">' + body + '</div><div class="row rc-dfoot"><span class="row cap rc-dfoot-n">' + ic('grad', 13) + (r.live ? esc(r.origin === 'catalog' ? '资源目录' : 'Orbit 知识库') + ' · ' + esc(r.license || '许可未知') + (r.url ? ' · ' + liLink(r.url, '来源') : '') : 'Orbit 模板库 · MIT') + '</span><button type="button" class="btn" data-act="copyRec" data-id="' + r.id + '">复制内容</button><button type="button" class="btn ai" data-act="recToStudio" data-id="' + r.id + '">' + ic('spark', 13) + '交给 Agent 定制</button>' + (inst ? '<button type="button" class="btn" data-act="uninstall" data-id="' + r.id + '">撤销安装…</button>' : recPrimaryBtn(r)) + '</div></div>';
  }
  // live: the header leads with the same total as the sidebar badge (open recs at the current level) and then says how many the
  // difficulty / dimension filters show, so the badge and「N 条」never disagree (R4-15)
  const lvHid = r0live() ? vis.length - list.length : 0, lvInst = r0live() ? vis.filter((r) => S.installed.has(r.id)).length : 0;
  const lvHead = r0live() ? '共 ' + (vis.length - lvInst) + ' 条' + (lvInst ? ' · ' + lvInst + ' 条已安装' : '') + (lvHid > 0 ? ' · 显示 ' + list.length + ' 条（' + lvHid + ' 条被筛选隐藏）' : '') : vis.length + ' 条';
  return tbar('优化建议', lvHead + ' · 按节省比例排序 · ' + (RECS.some((x) => x.live) ? lvRecUpdated() : '9 月 30 日 23:10 更新'), '<button type="button" class="btn" data-act="recalc">' + ic('sync', 14) + '重新计算</button><button type="button" class="btn ai" data-act="ask" data-ctx="recs">' + ic('spark', 14) + '让本地 Agent 深度诊断</button>') +
    '<div class="content" id="content"><div class="frow"><div class="seg" role="tablist" aria-label="优化维度">' + DIMS.map((d) => '<button type="button" role="tab" data-act="recDim" data-v="' + d[0] + '" class="' + (R.dim === d[0] ? 'on' : '') + '" aria-selected="' + (R.dim === d[0]) + '">' + d[1] + '<span class="mono" style="font-size:11px;color:var(--ink-3);font-weight:500">' + cnt(d[0]) + '</span></button>').join('') + '</div></div>' +
    '<div class="frow"><span class="cap" data-tip="难度：L1 一键应用 · L2 复制粘贴 · L3 需要配置 · L4 架构调整">难度</span>' + [1, 2, 3, 4].map((k) => '<button type="button" class="chip sm' + (R.lv.has(k) ? '' : ' dash') + '" data-act="recLv" data-v="' + k + '" aria-pressed="' + R.lv.has(k) + '">' + lvlIcon(k) + LEVELS[k] + '</button>').join('') + '<span style="width:1px;height:18px;background:var(--line);margin:0 6px"></span><span class="cap">按我的水平</span><button type="button" class="chip sm" data-act="recAud" data-tip="' + AUD_D[R.aud] + '">' + AUD[R.aud] + ic('chev', 12) + '</button><span style="flex:1"></span><span class="cap">已应用 ' + S.installed.size + ' · 不适用 ' + R.gone.size + (R.gone.size ? ' <button type="button" class="lnk" data-act="restoreRecs" style="font-size:12px">恢复</button>' : '') + '</span></div>' +
    '<div class="recs"><div class="stack">' + (g1.length ? '<div class="eb" style="display:flex;justify-content:space-between"><span>高收益 · 低成本</span><span>' + g1.length + '</span></div>' + g1.map(card).join('') : '') + (g2.length ? '<div class="eb" style="display:flex;justify-content:space-between;margin-top:4px"><span>值得投入 · 需要配置</span><span>' + g2.length + '</span></div>' + g2.map(card).join('') : '') + (g0.length ? '<div class="eb" style="display:flex;justify-content:space-between;margin-top:4px" data-tl="rec-g0"><span>按画像匹配 · 待验证</span><span>' + g0.length + '</span></div>' + g0.map(card).join('') : '') + (g3.length ? '<div class="eb" style="display:flex;justify-content:space-between;margin-top:4px" data-tl="rec-lib"><span>资料库推荐 · 按画像匹配</span><span>' + libN + '</span></div>' + g3.map(card).join('') : '') + (list.length ? '' : empty('没有符合筛选的建议。试试放宽难度或水平。')) + '</div><div style="position:sticky;top:0">' + detail + '</div></div></div>';
};
PAGES.recs.after = () => { TRK_SPECS.forEach((sp, i) => { const el = $('#content [data-vz="trk-' + i + '"]'); if (el) VZ.mount(el, sp); }); };
function codeBlock(lines) { return '<div class="code">' + lines.map((l, i) => '<div class="' + (l[1] === '+' ? 'add' : l[1] === 'ai' ? 'ai' : '') + '"' + (l[1] === '-' ? ' style="background:var(--crit-bg)"' : '') + '><span class="n">' + (l[1] === '+' ? '+' : l[1] === '-' ? '−' : i + 1) + '</span><span class="t" style="' + (l[1] === '-' ? 'text-decoration:line-through;color:var(--crit)' : '') + '">' + (esc(l[0]) || ' ') + '</span></div>').join('') + '</div>'; }
// 7-day comparison per metric: relative change with a (deterministic, demo) 95% bootstrap interval from the sample sizes;
// verdict in four states — 有效 / 无显著变化 / 变差 / 样本不足 (n < 5 on either side, or the two windows differ by > 30%).
function trackStats(r) {
  const x = recX(r.id); const [n0, n1] = x.n; const low = Math.min(n0, n1) < 5 || Math.abs(n0 - n1) / Math.max(n0, n1) > 0.3;
  const rows = r.track.map((t) => { const a = t[1], b = t[2]; const up = REC_UP.test(t[0]); const rel = a ? (b - a) / a : 0; const se = Math.abs(rel) * 0.35 / Math.sqrt(Math.min(n0, n1)) + 0.03; const lo = rel - 1.96 * se, hi = rel + 1.96 * se; const better = up ? b > a : b < a; const sig = lo > 0 || hi < 0; return { name: t[0], unit: t[3], a, b, up, rel, lo, hi, better, sig }; });
  const good = rows.filter((m) => m.sig && m.better).length, bad = rows.filter((m) => m.sig && !m.better).length;
  const verdict = low ? 'low' : good >= 2 ? 'good' : bad && !good ? 'bad' : 'flat';
  return { n0, n1, low, rows, verdict };
}
const VERDICT = { good: ['有效', 'okc', 'good'], flat: ['无显著变化', 'minus', 'flat'], bad: ['变差', 'xc', 'bad'], low: ['样本不足', 'alert', 'low'] };
const pctTxt = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.round(Math.abs(v) * 100) + '%';
function trackView(r, inst) {
  const done = inst.days >= 7; const st = trackStats(r); const V = VERDICT[st.verdict];
  const days = '<div class="rc-days" role="img" aria-label="安装前 7 天基准，安装后第 ' + inst.days + ' 天">' + [1, 2, 3, 4, 5, 6, 7].map(() => '<i class="base"></i>').join('') + '<i class="mark" aria-hidden="true">▲</i>' + [1, 2, 3, 4, 5, 6, 7].map((k) => '<i class="' + (k <= inst.days ? 'on' : '') + '"></i>').join('') + '</div><div class="rc-dlbl"><span><i class="k base"></i>安装前 7 天 · ' + st.n0 + ' 个会话</span><span class="mono" style="color:var(--ink-1)">安装日</span><span><i class="k on"></i>安装后 ' + (done ? '7 天 · ' + st.n1 + ' 个会话' : '第 ' + inst.days + ' / 7 天') + '</span></div>';
  const head = '<div class="row" style="flex-wrap:wrap"><span style="font-size:13px;font-weight:600;flex:1">' + (done ? '7 天对比结果' : '追踪中 · 第 ' + inst.days + ' / 7 天') + (inst.scope === 'proj' ? ' <span class="cap">· 仅 ' + esc((inst.target || '').split('/')[0]) + '</span>' : '') + '</span>' + (done ? '<span class="rc-verdict ' + V[2] + '" data-tip="口径：安装前后各 7 天、同一批项目；区间为自助法 95% 置信区间">' + ic(V[1], 14) + V[0] + '</span>' : inst.live ? '<span class="cap mono">满 7 天后出结论</span>' : '<button type="button" class="btn sm" data-act="ff7" data-id="' + r.id + '">快进 7 天（演示）</button>') + '</div>';
  if (!done) return '<div class="col" style="gap:12px">' + head + days + '<span class="eb">基准 · 安装前 7 天</span><div class="rc-base">' + st.rows.map((m) => '<span><span class="cap">' + m.name + '</span><b class="mono">' + (m.a == null ? '—' : m.a) + '</b><span class="cap">' + m.unit + '</span></span>').join('') + '</div><span class="cap" data-tip="前后会话数相差超过 30% 时标为「样本不足」">满 7 天后逐项给出 95% 区间与结论</span></div>';
  const metrics = st.rows.map((m, i) => {
    TRK_SPECS.push({ type: 'dumbbell', title: m.name + '：安装前后对比', rows: [{ name: '', a: m.a, b: m.b }], labels: ['安装前 7 天', '安装后 7 天'], colors: ['var(--h3)', 'var(--accent)'], goodDown: !m.up, legend: false, rowH: 26, height: 46, animate: false, format: (v) => VZ.fmt(v, Math.abs(v) < 10 && v % 1 ? '1f' : 'int') + (m.unit ? ' ' + m.unit : '') });
    return '<div class="rc-metric"><div class="row rc-mh"><b>' + m.name + '</b><span class="mono" style="color:var(--ink-2)">' + m.a + ' → ' + m.b + ' ' + m.unit + '</span><span class="mono rc-d ' + (m.sig ? (m.better ? 'good' : 'bad') : '') + '">' + pctTxt(m.rel) + '</span><span style="flex:1"></span><span class="cap mono rc-ci">95% CI ' + pctTxt(m.lo) + ' … ' + pctTxt(m.hi) + ' · 前后 ' + st.n0 + ' / ' + st.n1 + ' 个会话</span></div><div class="vz" data-vz="trk-' + i + '"></div></div>';
  }).join('');
  const why = st.verdict === 'good' ? '三项中至少两项的 95% 区间不含 0 且方向正确。' : st.verdict === 'low' ? '前后会话数 ' + st.n0 + ' / ' + st.n1 + '：样本太少或相差超过 30%，结论不可靠；可以继续观察 7 天。' : st.verdict === 'bad' ? '有指标显著变差，建议撤销后在生成工坊里定制。' : '区间都跨过 0，看不出稳定的变化；多观察 7 天或与同类建议组合。';
  return '<div class="col" style="gap:12px">' + head + days + '<div>' + metrics + '</div><div class="cap" style="line-height:16px">' + why + '</div><div class="row" style="justify-content:flex-end;gap:6px"><button type="button" class="btn" data-act="uninstall" data-id="' + r.id + '">撤销…</button><button type="button" class="btn p" data-act="keepRec" data-id="' + r.id + '">保留</button></div></div>';
}
let DISMISS_T = 0;
document.addEventListener('keydown', (e) => { if (e.key !== 'Enter' && e.key !== ' ') return; const el = e.target.closest && e.target.closest('.rcard[data-act="selRec"]'); if (!el || e.target !== el) return; e.preventDefault(); ACT.selRec(el, e); const n = $('#content .rcard[data-id="' + el.dataset.id + '"]'); if (n) n.focus({ preventScroll: true }); });
Object.assign(ACT, {
  recDim: (el) => { S.recs.dim = el.dataset.v; S.recs.peek = null; render(); },
  recLv: (el) => { const k = +el.dataset.v; if (S.recs.lv.has(k)) { if (S.recs.lv.size > 1) S.recs.lv.delete(k); } else S.recs.lv.add(k); S.recs.peek = null; render(); },
  recAud: (el) => openDD(el, AUD.map((a, i) => ({ t: a + ' · ' + AUD_D[i], v: i, on: S.recs.aud === i })), (v) => { S.recs.aud = v; if (v === 2) S.recs.lv.add(4); S.recs.peek = null; render(); toast('已按「' + AUD[v] + '」调整可见建议与说明深度'); }),
  selRec: (el, e) => { if (e.target.closest('button')) return; S.recs.sel = el.dataset.id; render(); },
  recTab: (el) => { S.recs.tab = el.dataset.v; render(); },
  recScope: (el) => { S.recs.scope = el.value; renderMain(); },
  // Opening a rec from elsewhere (palette, overview, widgets) shows it without touching the level / difficulty filters (BUG-80).
  openRec: (el) => { const id = el.dataset.id; if (!RECI[id]) return; S.recs.sel = id; S.recs.tab = el.dataset.tab || 'preview'; S.recs.peek = id; S.recs.gone.delete(id); go('recs'); },
  dismissRec: (el) => {
    if (Date.now() - DISMISS_T < 450) return; DISMISS_T = Date.now();   // a double click must not strike the next card (BUG-65)
    const id = el.dataset.id; const prevSel = S.recs.sel; S.recs.gone.add(id); render();
    toast('已标记「不适用」，同类建议会降权', { act: '撤销', sec: 8, onAct: () => { S.recs.gone.delete(id); S.recs.sel = prevSel; render(); } });
  },
  restoreRecs: () => { S.recs.gone.clear(); render(); },
  // Evidence = the rec's own session set: start from a clean filter set so A3 shows just that query (BUG-27).
  recEvidence: (el) => { const r = RECI[el.dataset.id]; const q = r.evq || {}; S.topic = null; S.outcome = null; S.hour = null; S.fric = q.fric || null; S.topic = q.topic || null; S.project = q.project || null; S.sess.mode = 'single'; go('sessions'); toast('依据：' + r.ev + (q.fric ? ' · 摩擦「' + q.fric + '」' : q.topic ? ' · 主题「' + TOPICS[q.topic] + '」' : q.project ? ' · 项目 ' + PJI[q.project].name : q.tool ? ' · 含 ' + q.tool + ' 审批的会话' : ' · 近 30 天全部会话')); },
  copyRec: (el) => { const r = RECI[el.dataset.id]; copyText(r.file.filter((l) => l[1] !== '-').map((l) => l[0]).join('\n'), r.title.split('：')[0]); },
  tutorial: (el) => { S.recs.sel = el.dataset.id; S.recs.tab = 'tut'; S.recs.peek = el.dataset.id; go('recs'); },
  recToStudio: (el) => { const r = RECI[el.dataset.id]; if (S.studio.run && !S.studio.run.done && !S.studio.run.stopped) { toast('生成工坊正在运行，先停止或等它完成再定制', { act: '去看看', onAct: () => go('studio') }); return; } S.studio.type = r.dim === 'hook' ? 'Hook' : r.dim === 'agent' ? '子代理' : r.dim === 'rule' ? '规则' : r.dim === 'flow' ? '工作流' : 'Skill'; S.studio.goal = '依据我的会话定制：' + r.title + '。' + r.why; S.studio.from = 'A7 建议「' + r.title.split('：')[0] + '」'; S.studio.run = null; go('studio'); },
  install: (el) => openInstall(el.dataset.id),
  uninstall: (el) => { const id = el.dataset.id; const inst = S.installed.get(id); openModal(modalHead('撤销「' + esc(RECI[id].title.split('：')[0]) + '」？', '会从备份恢复写入前的文件') + '<div class="mb"><div class="mono" style="font-size:12px;padding:10px 12px;border-radius:8px;background:var(--sunken)">' + esc(inst && inst.target ? inst.target : RECI[id].target) + '</div></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="doUninstall" data-id="' + id + '">撤销安装</button></div>'); },
  doUninstall: (el) => { const id = el.dataset.id; closeModal(); uninstallRec(id); render(); toast('已撤销，文件已从备份恢复'); },
  ff7: (el) => { const i = S.installed.get(el.dataset.id); if (i) i.days = 7; render(); },
  keepRec: () => toast('已保留。同类建议的权重会提高'),
  recalc: () => { const c = $('#content'); if (c) c.classList.add('stale'); setTimeout(() => { if (S.route !== 'recs') return; renderMain(); toast('建议已按最新数据重算'); }, 900); }   // never lands on another page (BUG-67)
});
