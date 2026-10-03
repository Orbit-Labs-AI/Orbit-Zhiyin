/* ============ onboarding & reveal (overlay) ============
 * 首次启动：0 欢迎 → 1 选择来源 → 2/3 Genesis；菜单「播放人格揭晓」与画像页「重播揭晓」复用 Genesis 的 2–5 段（openReveal）。
 * Genesis 是同一个盒子里的一段连贯序列，步骤之间不整体替换 innerHTML：
 *   01 导入  Orbit 母题：表盘先以倾斜轨道的视角出现（Orbit 标志的倾斜椭圆，CSS rotateX 64° + 转角 + 缩小），放大并翻正成罗盘外框；
 *            标志的内弧收拢成领瓣，合拢的花苞随后自由快转（寻找方向）。选中来源行的 Agent 色点化作会话粒子，沿倾斜的椭圆轨道螺旋汇入中央；
 *            来源列表收拢淡出，计数器累加；粒子汇入时花苞逐渐减速，转满整圈停在 00 接上 02
 *   02 归位  花苞（领瓣在前）匀速扫一圈（身后拖一道淡扇形），粒子在领瓣扫过处按开始时间落到表盘对应角度（半径 = 时长），再汇入轨道环带；
 *            环带在扫过处长出（.fp-sweep 遮罩），Agent 行星随扫描依次出现、跟着领瓣公转，扫完走最短弧滑到各自的协作重心（fp2SVG 的几何，FPG）
 *   03 开花  花苞开成该类型的花（前排先开、身后一轮稍晚，带回弹）；字母位在两极之间翻牌时花左右寻向，
 *            最后一个字母锁定时领瓣摆向协作重心，阻尼振荡后停住
 *   04 匹配  最接近的 6 种类型卡绕表盘出现、按相似度排序（花轻颤），其余淡出，胜出的一张飞入四字母（花定住），给出匹配度
 *   05 落地  「查看完整画像」：大人格码与指纹（含花）FLIP 到画像页 [data-hero="code"] / [data-hero="fp"]，overlay 同时淡出
 * 粒子画在 overlay 的 canvas 上（devicePixelRatio、颜色取计算样式），翻正、内弧、环带扫描与行星在 rAF 里逐帧写，其余是 CSS keyframes + WAAPI，节点只建一次。
 * 跳过 / Esc / 在后台继续随时可用；closeOverlay() 取消全部计时器、动画帧与动画；prefers-reduced-motion 直接给最终态。 */
let OB = null, REV = null, GNS = null;
function closeOverlay() {
  genStop();
  const o = $('#overlay'); o.hidden = true; o.innerHTML = '';
  if (OB) OB.timers.forEach(clearTimeout);
  if (REV) REV.timers.forEach(clearTimeout);
  OVL = null;
}
// First launch looks at every session of the sources ticked in step 2 (90 days when「只分析最近 90 天」is on), not at the
// main window's project / Agent filters (BUG-84).
function obSel() { return ALL.filter((s) => !s.live && OB && OB.src.has(s.a) && (!OB.recent || s.d >= LASTDAY - 89)); }
function obPersona() { return persona(obSel()); }
function genFacts(L) {
  const st = stats(L);
  const hc = new Array(24).fill(0); L.forEach((s) => { hc[s.h] += s.msgs; });
  let bh = 0; hc.forEach((v, h) => { if (v > hc[bh]) bh = h; });
  const byA = AG.map((a) => [a, sum(L.filter((s) => s.a === a.id), (s) => s.dur)]).sort((x, y) => y[1] - x[1]);
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]);
  return [
    ['统计', fmt(L.length) + ' 个会话 · ' + fmt(st.tools) + ' 次工具调用', '最常在 ' + bh + ':00–' + (bh + 1) + ':00 协作'],
    ['轨迹', '还原每个会话的时间线', (byA[0] ? byA[0][0].name : '—') + ' 占协作时长 ' + Math.round((byA[0] ? byA[0][1] : 0) / Math.max(1, st.hours * 60) * 100) + '%'],
    ['语义', '本地 Agent 正在归类你的消息', '摩擦最多的是「' + (fr[0] ? fr[0][0] : '—') + '」'],
    ['人格', '四个维度', Math.round(st.verify) + '% 的会话要求验证结果']
  ];
}
function obFacts() { return genFacts(obSel()); }
function openOnboarding(step) {
  closeModal(); closeDD(); closeOverlay();
  OB = { step: step || 0, src: new Set(AG.map((a) => a.id).filter((id) => !S.srcOff.has(id))), recent: true, prog: -1, timers: [] };
  OVL = 'ob'; $('#overlay').hidden = false; drawOB();
}
// The live source list scrolls inside its card; its max-height is a viewport budget, so snap it down to whole rows
// (R4-10: the last visible row — often the 添加文件夹 row — was cut in half at the card's bottom edge).
function obSnapRows(sc) {
  sc.style.removeProperty('height');
  const cap = sc.clientHeight, rows = Array.from(sc.children);
  if (!rows.length || sc.scrollHeight <= cap + 1) return;
  const pad = parseFloat(getComputedStyle(sc).paddingTop) || 0, top = sc.getBoundingClientRect().top + sc.clientTop;
  let fit = 0;
  rows.forEach((r) => { const b = r.getBoundingClientRect().bottom - top; if (b <= cap - pad + 0.5) fit = Math.max(fit, b); });
  const bb = getComputedStyle(sc).boxSizing === 'border-box' ? sc.offsetHeight - sc.clientHeight : 0;
  // end exactly at the last whole row (fractional px): the bottom padding would otherwise show a sliver of the next row
  if (fit > 0) sc.style.height = (fit + bb).toFixed(2) + 'px';
}
function drawOB() {
  const s = OB.step;
  // 2 / 3 步是 Genesis：直接打开（3 = 最终态）；从第 1 步点「开始分析」时走 obStart，带上来源行位置做粒子起点
  if (s >= 2) { genOpen('ob', { L: obSel(), final: s === 3 }); return; }
  const dots = '<div class="ob-dots" aria-hidden="true">' + [0, 1, 2, 3].map((i) => '<i class="' + (i <= s ? 'on' : '') + '"></i>').join('') + '</div>';
  const top = '<div class="row">' + dots + '<span class="mono cap" style="font-size:11px">' + (s + 1) + ' / 4</span><span style="flex:1"></span>' + (s < 3 ? '<button type="button" class="btn sm gh" data-act="obClose">跳过</button>' : '') + '</div>';
  let b = '';
  if (s === 0) {
    b = '<span class="appicon ob-mark" style="width:56px;height:56px">' + appIcon(56) + '</span><div><div class="eb">Orbit</div><h2 class="serif" style="margin:4px 0 0;font-size:26px;line-height:1.25">看见你和 Agent 怎么协作</h2></div><p style="margin:0;font-size:13px;line-height:1.6;color:var(--ink-2)">没有注册，也没有账号。Orbit 读取本机各个 Agent 的会话日志，告诉你协作习惯、卡点和下一步该装什么。四步里只有一次需要你做决定：分析哪些数据。</p>' +
      [['eye', '只读本地日志', '不碰凭据文件，也不需要「完全磁盘访问」'], ['shield', '数据不出本机', '0 B 上传；匿名贡献默认关闭'], ['bot', '不调用云端模型', '语义分析交给你自己的本地 Agent']].map((x) => '<div class="row" style="align-items:flex-start;gap:10px">' + ic(x[0], 18, 'margin-top:1px') + '<span class="col" style="gap:1px"><b style="font-size:13px">' + x[1] + '</b><span class="cap">' + x[2] + '</span></span></div>').join('') +
      '<div class="row" style="justify-content:space-between;margin-top:6px"><button type="button" class="lnk" data-act="obPrivacy">完整隐私说明</button><button type="button" class="btn p" data-act="obNext" style="height:32px;padding:0 18px">开始</button></div>';
  } else if (s === 1 && OB.live) {
    b = obLiveStep();
  } else if (s === 1) {
    const tot = AG.filter((a) => OB.src.has(a.id)).reduce((x, a) => x + a.all, 0);
    b = '<div><h2 class="serif" style="margin:0;font-size:26px;line-height:1.25">找到了这些 Agent 的会话</h2><p class="cap" style="margin:6px 0 0">只读取会话日志。取消勾选的来源不会被索引。</p></div><div class="card" style="padding:2px 0">' +
      AG.map((a) => '<label class="srcrow"><span style="width:30px;height:30px;border-radius:8px;background:' + a.t + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + a.c) + '</span><span style="min-width:0"><b style="font-size:13px">' + a.name + '</b><span class="mono cap" style="display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + a.path + '</span></span><span class="mono cap" style="font-size:11px">' + fmt(a.all) + '</span><input type="checkbox" data-chg="obSrc" data-a="' + a.id + '"' + (OB.src.has(a.id) ? ' checked' : '') + ' aria-label="分析 ' + a.name + '" style="width:16px;height:16px;accent-color:var(--ink-1)"></label>').join('') +
      '<div class="srcrow" style="opacity:.6"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('minus', 15) + '</span><span><b style="font-size:13px">Cursor</b><span class="cap" style="display:block;font-size:11px">未检测到 · 可稍后在设置中手动指定</span></span><span></span><span></span></div></div>' +
      '<div class="row" style="align-items:flex-start;gap:10px">' + swBtn(OB.recent, 'obRecent', '', '只分析最近 90 天') + '<span class="col" style="gap:2px"><b style="font-size:13px">只分析最近 90 天</b><span class="cap" style="font-size:11px">首次约 40 秒；之后可以在设置中扩展到全部历史</span></span></div><div class="mono cap" style="font-size:11px">共 ' + fmt(tot) + ' 个会话 · 最早 2025-11-03</div>' +
      '<div class="row" style="justify-content:space-between"><button type="button" class="btn gh" data-act="obBack">返回</button><button type="button" class="btn p" data-act="obStart" style="height:32px;padding:0 18px"' + (OB.src.size ? '' : ' disabled') + '>开始分析</button></div>';
  }
  // Keep the keyboard where it was across redraws (a ticked checkbox, the 90-day switch, the progress page's 950 ms ticks);
  // only a step change moves focus to the default button (BUG-54).
  const o = $('#overlay'); const a = document.activeElement; const key = a && o.contains(a) ? (a.dataset.a ? '[data-a="' + a.dataset.a + '"]' : a.dataset.act ? '[data-act="' + a.dataset.act + '"]' : null) : null;
  const sc0 = o.querySelector('[data-ob="sources"]'); const top0 = sc0 ? sc0.scrollTop : 0;
  o.innerHTML = '<div class="obox" role="dialog" aria-modal="true" aria-label="首次启动">' + top + b + '</div>';
  const sc = o.querySelector('[data-ob="sources"]'); if (sc) { obSnapRows(sc); sc.scrollTop = top0; }
  const keep = key && OB.drawn === s ? o.querySelector(key) : null;
  if (keep) keep.focus({ preventScroll: true }); else if (OB.drawn !== s) { const f = $('#overlay button.p'); if (f && !f.disabled) f.focus(); }
  OB.drawn = s;
}

// Import stage names and notes in one place (the live first run, the sidebar entry and notifications read them from here),
// so the wording can be replaced once the backend's import phases are settled. stages: [id, label] in display order;
// a gateway-provided label (/v1/shell/onboarding progress.stages) still wins over these.
const OB_TEXT = {
  stages: [['backfill', '导入历史会话'], ['stats', '统计分析'], ['semantic', '语义分析'], ['persona', '协作画像']],
  semanticOff: '仅统计模式：不调用模型',
  preparing: '准备来源', queued: '排队中', failed: '导入失败', skipped: '跳过',
  partial: '已导入；少量记录未能解析或暂时保留了上一版本',
  // job frame progress → the note under 导入历史会话: the gateway's stage name and detail (which source / batch, whether it
  // rebuilds the affected sessions or the whole source, a retry after a source changed mid-import); older gateways only
  // send progress.stage, named by the shared adapter. count: 「N / M 个文件」; ratio: the whole job (never moves back).
  stageNote: (pr) => TandemLive.ui.stageNote(pr),
  count: (x) => (x.total ? fmt(x.done || 0) + ' / ' + fmt(x.total) + (TandemLive.ui.unitName(x.unit) ? ' ' + TandemLive.ui.unitName(x.unit) : '') : x.status === 'skipped' ? OB_TEXT.skipped : ''),
  ratio: (pr) => TandemLive.ui.stageRatio(pr),
  headRun: '正在导入你的会话', headDone: '导入已完成',
  bgHint: '可以关闭窗口，完成后通知你',
  side: { run: '导入中', analyze: '分析中', fail: '导入未完成', done: '重新打开引导', start: '开始导入', view: '查看', retry: '重试' }
};
// Live step 1 (OB.live, filled by 95-live-native.js): the sources come from /v1/shell/onboarding (estimates) and
// /v1/app/discovery, 添加文件夹 goes through LVN.addSource() (native chooseFolder, or the path field in a browser), and once
// 开始分析 has posted the import job the button row becomes the four onboarding stages driven by job frames.
// 来源路径与 mock 一样显示成 ~/…（macOS / Linux 的用户主目录）
const obTilde = (p) => String(p || '—').replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, '~');
function obLiveStep() {
  const L = OB.live, rows = L.sources, host = window.ORBIT && ORBIT.native.hasHost();
  const ag = (x) => lvAgentOf(x.agent);
  const col = (m, k) => m.slot ? 'var(--a' + m.slot + k + ')' : 'var(--a0' + k + ')';
  const busy = !!(L.job || L.starting);
  const cnt = (x) => x.status === 'permission_denied' ? '无权限' : x.est ? fmt(x.est) : x.status === 'empty' ? '空' : '—';
  const list = L.state === 'loading' && !rows.length ? '<div class="srcrow"><span class="spin" style="width:14px;height:14px;margin:8px"></span><span class="cap">正在查找本机的 Agent 会话…</span><span></span><span></span></div>'
    : rows.length ? rows.map((x) => { const m = ag(x); const dis = busy || x.status === 'permission_denied'; return '<label class="srcrow" data-src="' + esc(x.id) + '"><span style="width:30px;height:30px;border-radius:8px;background:' + col(m, 't') + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + col(m, '')) + '</span><span style="min-width:0"><b style="font-size:13px">' + esc(m.name) + '</b><span class="mono cap" style="display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + esc(x.root || '') + '">' + esc(obTilde(x.root)) + '</span></span><span class="mono cap" style="font-size:11px">' + cnt(x) + '</span><input type="checkbox" data-chg="obSrcL" data-s="' + esc(x.id) + '" data-a="' + esc(m.id) + '"' + (L.sel.has(x.id) ? ' checked' : '') + (dis ? ' disabled' : '') + ' aria-label="分析 ' + esc(m.name) + '" style="width:16px;height:16px;accent-color:var(--ink-1)"></label>'; }).join('')
    : '<div class="srcrow" style="opacity:.75"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('minus', 15) + '</span><span><b style="font-size:13px">' + (L.state === 'error' ? '读取来源失败' : '没有找到 Agent 会话目录') + '</b><span class="cap" style="display:block;font-size:11px">' + (L.state === 'error' ? esc(L.loadErr || '本机服务没有响应') : '可以在下面手动添加文件夹') + '</span></span><span></span><span></span></div>';
  const opts = '<option value="auto">自动识别</option>' + Object.keys(LV.AGENTS).filter((k) => LV.AGENTS[k].key === k).map((k) => '<option value="' + k + '"' + (L.manual.agent === k ? ' selected' : '') + '>' + esc(LV.AGENTS[k].name) + '</option>').join('');
  const add = '<div class="srcrow ob-add"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('plus', 15) + '</span><span class="row" style="gap:6px;min-width:0"><select class="ob-agent" data-chg="obAgent" aria-label="来源的 Agent"' + (busy ? ' disabled' : '') + ' style="height:26px;max-width:132px">' + opts + '</select>' +
    (host ? '<span class="cap" style="font-size:11px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">选择一个会话日志目录</span>' : '<input class="mono ob-path code-t" id="obPath" data-in="obPath" placeholder="~/.claude" value="' + esc(L.manual.path || '') + '" aria-label="文件夹路径"' + (busy ? ' disabled' : '') + ' style="height:26px;min-width:0;flex:1;font-size:11px">') + '</span><span></span>' +
    '<button type="button" class="btn sm" data-act="obAddFolder"' + (busy || L.adding ? ' disabled' : '') + '>' + (L.adding ? '添加中…' : host ? '添加文件夹…' : '添加') + '</button></div>';
  const chosen = rows.filter((x) => L.sel.has(x.id));
  const tot = chosen.reduce((a, x) => a + (x.est || 0), 0);
  const first = chosen.reduce((a, x) => (x.earliest && (!a || x.earliest < a) ? x.earliest : a), null);
  const day = (ms) => { try { return new Date(ms).toISOString().slice(0, 10); } catch (e) { return '—'; } };
  const head = '<div><h2 class="serif" style="margin:0;font-size:26px;line-height:1.25">' + (L.done ? OB_TEXT.headDone : L.job ? OB_TEXT.headRun : rows.length ? '找到了这些 Agent 的会话' : '先告诉 Orbit 会话在哪里') + '</h2><p class="cap" style="margin:6px 0 0">只读取会话日志。取消勾选的来源不会被索引。</p></div>';
  let foot;
  if (L.job || L.starting) {
    const st = L.stages || [];
    const pr = L.job && L.job.progress || {}; const ratio = OB_TEXT.ratio(pr);
    foot = '<div class="st-steps ob-stages" data-ob="stages">' + st.map((x, i) => { const k = x.status === 'done' ? 'done' : x.status === 'running' ? 'run' : x.status === 'failed' ? 'stop' : 'todo';
      return '<div class="step ' + k + '" data-stage="' + esc(x.id) + '" data-st="' + esc(x.status) + '"><span class="mk">' + (k === 'done' ? '✓' : k === 'stop' ? '!' : i + 1) + '</span><span class="col" style="gap:1px;min-width:0"><span class="t">' + esc(x.label) + '</span>' + (x.note ? '<span class="s">' + esc(x.note) + '</span>' : '') + '</span><span class="mono cap" style="font-size:11px;text-align:right">' + OB_TEXT.count(x) + '</span></div>'; }).join('') + '</div>' +
      '<div class="g-bar"><i data-ob="bar" style="width:' + (ratio == null ? 4 : Math.round(ratio * 100)) + '%"></i></div>' +
      (L.err ? '<div class="cap" data-ob="err" style="color:var(--crit)">' + esc(L.err) + '</div>' : '') +
      '<div class="row" style="justify-content:space-between"><span class="cap">' + (L.done ? '协作画像已生成' : OB_TEXT.bgHint) + '</span>' + (L.err ? '<button type="button" class="btn p" data-act="obStart" style="height:32px;padding:0 18px">重试</button>' : L.done ? '<button type="button" class="btn p" data-act="obPlay" style="height:32px;padding:0 18px">查看揭晓</button>' : '<button type="button" class="btn" data-act="obBgImport">在后台继续</button>') + '</div>';
  } else {
    foot = (L.err ? '<div class="cap" data-ob="err" style="color:var(--crit)">' + esc(L.err) + '</div>' : '') +
      '<div class="row" style="justify-content:space-between"><button type="button" class="btn gh" data-act="obBack">返回</button><button type="button" class="btn p" data-act="obStart" style="height:32px;padding:0 18px"' + (chosen.length ? '' : ' disabled') + '>开始分析</button></div>';
  }
  // the sheet has to fit a 900 px App window: the source list scrolls inside its card (shorter while the four stages show),
  // and once the import runs the 添加 row and the 90-day switch give their room to the stages and the footer
  const cap = busy ? 'max-height:min(204px,24vh)' : 'max-height:max(160px,calc(100vh - 470px))';
  return head + '<div class="card ob-srcs" data-ob="sources" style="padding:2px 0;flex:none;overflow:auto;' + cap + '">' + list + (busy ? '' : add) + '</div>' +
    (L.added ? '<div class="row cap" data-ob="added" style="gap:4px;font-size:11px;color:var(--good);min-width:0">' + ic('check', 12, 'flex:none') + '<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">已添加来源 ' + esc(obTilde(L.added)) + '</span></div>' : '') +
    (busy ? '' : '<div class="row" style="align-items:flex-start;gap:10px">' + swBtn(OB.recent, 'obRecent', '', '只分析最近 90 天') + '<span class="col" style="gap:2px"><b style="font-size:13px">只分析最近 90 天</b><span class="cap" style="font-size:11px">只导入 90 天内改动过的日志；之后可以在设置中扩展到全部历史</span></span></div>') +
    '<div class="mono cap" data-ob="total" style="font-size:11px">' + (chosen.length ? '约 ' + fmt(tot) + ' 个会话（估计）' + (first ? ' · 最早 ' + day(first) : '') : '还没有选择来源') + '</div>' + foot;
}

/* ---- Genesis ---- */
const G_EASE = 'cubic-bezier(.2,.8,.2,1)', G_SPRING = 'cubic-bezier(.34,1.45,.64,1)';
const G_PAIRS = [['D', 'S'], ['I', 'P'], ['M', 'F'], ['V', 'T']];
// reduceMotion() comes from 37-motion.js (shared by every motion layer)
const genIO = (u) => { u = clamp(u, 0, 1); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };
const genBack = (u) => { u = clamp(u, 0, 1); const c = 1.25; return 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2); };
// 各段起点（ms）。首次启动从「开始分析」算起约 6.7 s；揭晓没有来源列表，01 段只把会话点汇集到中央，约 4.9 s。
function genTimes(mode) { return mode === 'ob' ? { place: 1700, grow: 3000, match: 4500, end: 6700 } : { place: 700, grow: 1800, match: 3100, end: 4900 }; }
// 16 种类型的原型点取每轴 25 / 75；匹配度 = 100 − 0.9 × 四维欧氏距离（每轴落在同侧的类型一定最近，所以第一名就是 p.code）
function genCands(p) {
  const K = ['D', 'I', 'M', 'V'];
  return Object.keys(TYPES).map((c) => { const d = Math.sqrt(K.reduce((a, k, i) => a + Math.pow(p.v[k] - (c[i] === k ? 75 : 25), 2), 0)); return { c, zh: TYPES[c][0], en: TYPES[c][1], sim: clamp(Math.round(100 - d * 0.9), 3, 99) }; }).sort((a, b) => b.sim - a.sim);
}
// 来源行的图标中心（overlay 坐标）：导入段的粒子从这里出发
function obSources() {
  const o = $('#overlay').getBoundingClientRect(); const m = {};
  $$('#overlay .srcrow').forEach((row) => { const cb = row.querySelector('input[data-a]'); if (!cb || !cb.checked) return; const r = row.firstElementChild.getBoundingClientRect(); m[cb.dataset.a] = [r.left - o.left + r.width / 2, r.top - o.top + r.height / 2, r.width]; });
  return m;
}
// 结构只建一次：指纹沿用画像页的 fp2SVG（.fp-wrap 纸面），人格码沿用 .letters / .L，类型小卡是 .card，按钮是 .btn / .btn.p
function genHTML(g) {
  const ob = g.mode === 'ob', p = g.p, F = g.F;
  const pv = p.ok ? p : { v: { D: 50, I: 50, M: 50, V: 50 } };
  const hr = S.persona.fpHour, cur = CUR.fp; S.persona.fpHour = null;
  const fp = fp2SVG(g.L, pv, 300, { labels: p.ok });
  S.persona.fpHour = hr; CUR.fp = cur;
  // 叠层：罗盘外框画线（与 fp2SVG 外框同半径）、24 个整点刻度、花身后的扫掠扇形（花本身是 fp2SVG 里的 .fp-bloom）、首次启动的 Orbit 内弧
  let tk = ''; for (let h = 0; h < 24; h++) { const a = h / 24 * Math.PI * 2; const q1 = pt(200, h % 6 ? 187.5 : 184, a), q2 = pt(200, 194.5, a); tk += 'M' + q1[0].toFixed(1) + ' ' + q1[1].toFixed(1) + 'L' + q2[0].toFixed(1) + ' ' + q2[1].toFixed(1); }
  const RW = FPG.R0 + FPG.RH + 2, w0 = pt(200, RW, -0.45);
  const over = '<svg class="g-over" viewBox="0 0 400 400" aria-hidden="true"><circle class="g-ring0" cx="200" cy="200" r="198" pathLength="1"/><path class="g-ticks" d="' + tk + '"/><g class="g-hand"><path class="g-wedge" d="M200 200L' + w0[0].toFixed(1) + ' ' + w0[1].toFixed(1) + 'A' + RW + ' ' + RW + ' 0 0 1 200 ' + (200 - RW) + 'Z"/></g>' + (g.mode === 'ob' ? '<path class="g-arc"/>' : '') + '</svg>';
  const slots = [0, 1, 2, 3].map((i) => { const a = p.ok ? axisView(p, i) : null; const ch = p.ok ? p.code[i] : '—'; return '<span class="g-slot"><span class="L">' + ch + '</span><span class="g-ax">' + (a ? a.name + ' <span class="mono">' + a.strong + '</span>' : '&nbsp;') + '</span></span>'; }).join('');
  const m = p.ok && p.classified ? g.cands.find((x) => x.c === p.code) : null;
  const match = m ? '<span class="bdg">匹配度 ' + m.sim + '%</span><span class="cap">16 种类型里最接近 · 置信度 ' + p.conf + ' · n=' + p.n + '</span>' : '<span class="bdg">' + (p.ok ? '置信度 ' + p.conf : '还没有会话') + '</span><span class="cap">' + (p.ok ? (p.hint || 'n=' + p.n) : '已选来源还没有会话') + '</span>';
  const nm = '<div class="serif g-zh">' + (p.ok ? p.zh + ' <i>' + p.en + '</i>' : '还没有会话') + '</div><p class="g-line">' + esc(p.ok ? p.line : '已选来源还没有会话，先用一段时间再来看。') + '</p>';
  const facts = F.map((f, i) => '<div class="step g-fact" data-i="' + i + '"><span class="mk">' + (i + 1) + '</span><div class="g-ft"><b>' + f[0] + '</b><span class="g-sw"><span class="cap g-sub">' + esc(f[1]) + '</span><span class="g-fx"><span>' + esc(f[2]) + '</span></span></span></div><span></span></div>').join('');
  const top = '<div class="row g-top">' + (ob ? '<div class="ob-dots" aria-hidden="true">' + [0, 1, 2, 3].map((i) => '<i class="' + (i <= 2 ? 'on' : '') + '"></i>').join('') + '</div><span class="mono cap" data-g="n" style="font-size:11px">3 / 4</span>' : '') +
    '<span class="mono cap g-stage"' + (ob ? '' : ' id="revStage"') + ' data-g="stage"></span><span style="flex:1"></span><button type="button" class="btn sm gh" data-act="' + (ob ? 'genSkip' : 'revSkip') + '">跳过</button></div>';
  const head = ob ? '<div class="g-head" data-g="head"><h2 class="serif">正在建立你的协作画像</h2><p class="cap">每完成一步就先给你看结果，不用等到最后。</p></div><div class="g-bar"><i data-g="bar"></i></div>' : '';
  const done = ob ? '<div class="g-next">' + [['看看优化建议', genRecLine()], ['打开悬浮组件', kb('⌥⌘P') + ' · 会话运行时陪着你'], ['去生成工坊', '按你的会话写 Skill 与规则']].map((x, i) => '<div class="row" style="align-items:flex-start;gap:8px;min-width:0"><span class="mono g-n">' + (i + 1) + '</span><span class="col" style="gap:1px;min-width:0"><b class="g-nt">' + x[0] + '</b><span class="cap g-nc">' + x[1] + '</span></span></div>').join('') + '</div>' +
      '<div class="g-foot"><button type="button" class="lnk" data-act="obReveal">播放揭晓动画</button><span class="row" style="gap:8px"><button type="button" class="btn" data-act="obShare">导出分享卡</button><button type="button" class="btn p" data-act="obDone" style="height:32px;padding:0 18px">查看完整画像</button></span></div>'
    : '<div class="g-foot"><span></span><span class="row" style="gap:8px"><button type="button" class="btn" data-act="revShare">导出分享卡</button><button type="button" class="btn p" data-act="revGo" style="height:32px;padding:0 18px">查看完整画像</button></span></div>';
  return top + head +
    '<div class="g-body"><div class="fp-wrap g-dial" data-g="dial"><div class="g-fp">' + fp + '</div>' + over + '<div class="g-cards" data-g="cards"></div></div>' +
    '<div class="g-side"><div class="mono cap g-count" data-g="count"></div><div class="g-res"><span class="eb">你的协作人格</span><div class="letters code g-code" data-g="code" role="img" aria-label="' + (p.ok ? p.code : '样本不足') + '">' + slots + '</div><div class="row g-match" data-g="match">' + match + '</div><div class="nm" data-g="nm">' + nm + '</div></div>' +
    '<div class="g-facts"><span class="eb">已经知道的</span>' + facts + '</div></div></div>' +
    '<div class="g-tail">' + (ob ? '<div class="g-foot" data-g="run"><span class="cap">可以关闭窗口，完成后通知你</span><button type="button" class="btn" data-act="obBg">在后台继续</button></div>' : '') +
    '<div class="g-done" data-g="done">' + done.replace(/<button /g, '<button disabled ') + '</div></div>';
}
// 取 fp2SVG 的各层（罗盘外框 .fp-base / 方位数字 .fp-hours / 节律带 .fp-band / 内盘 .fp-core / 花 .fp-flower（旋转层 .fp-bloom、
// 开花层 .fp-front / .fp-back）/ 轨道环带的扫描遮罩 .fp-sweep / 行星 .fp-pl）与翻正用的两层（.g-fp、.g-over）
function genMark(g) {
  const svg = g.box.querySelector('.g-fp svg'); g.svg = svg; g.pls = []; g.tiltEls = []; if (!svg) return;
  g.front = svg.querySelector('.fp-front'); g.back = svg.querySelector('.fp-back');
  g.nd = svg.querySelector('.fp-bloom'); g.hd = g.nd ? +g.nd.dataset.hd : 0;
  g.sweepEl = svg.querySelector('.fp-sweep');
  g.pls = Array.from(svg.querySelectorAll('.fp-pl')).map((el) => ({ el, deg: +el.dataset.pa }));
  g.tiltEls = [g.box.querySelector('.g-fp'), g.box.querySelector('.g-over')].filter(Boolean); g.arc = g.box.querySelector('.g-arc');
  g.slotL = Array.from(g.box.querySelectorAll('.g-slot .L'));
}
// 开花：x = 0 是花苞（FPG.BUD 倍），1 是全开；前排用 genBack 回弹，身后一轮晚 18%。x ≥ 1 交回 CSS（清掉内联 transform）；
// 样本不足时一直是花苞
function genBloom(g, x) {
  const set = (el, v) => { if (el) el.style.transform = v >= 1 && x >= 1 ? '' : 'scale(' + (FPG.BUD + (1 - FPG.BUD) * v).toFixed(4) + ')'; };
  const k = g.p.ok ? x : 0;
  set(g.front, k <= 0 ? 0 : genBack(k)); set(g.back, k <= 0.18 ? 0 : genBack((k - 0.18) / 0.82));
}
// 花（领瓣）的角度（度，顺时针，0 = 00:00）：01 三次 Hermite 从快转减速，转满整圈落在 00 并接上扫描的速度；02 匀速扫一圈；
// 03 滑停后左右寻向（中心缓慢偏向重心），最后一个字母锁定时从当前位置摆向协作重心，阻尼振荡；04 候选卡竞争时轻颤，匹配卡并入后定住
// 首次启动：Orbit 内弧先在 00 收拢成领瓣（G_HOLD 之前花苞停在 00），再从静止起转，快转两圈后减速落到 00
const G_HOLD = 960;
function genNeedle(g, t) {
  const T = g.T, P = T.place, sw = g.sweep, ws = 360 / sw, ob = g.mode === 'ob', t0 = ob ? G_HOLD : 0, w0 = ob ? 0 : 1.25;
  if (t < t0) return 0;
  if (t < P) {
    const D = P - t0, N = ob ? 2 : Math.max(1, Math.round((w0 + ws) / 2 * D / 360)), u = (t - t0) / D;
    return (u * u * u - 2 * u * u + u) * w0 * D + (3 * u * u - 2 * u * u * u) * N * 360 + (u * u * u - u * u) * ws * D;
  }
  if (t < P + sw) return (t - P) / sw * 360;
  const cd = 300, ts = P + sw + cd, A0 = 360 + ws * cd / 2;
  if (t < ts) { const tc = t - P - sw; return 360 + ws * tc - ws * tc * tc / (2 * cd); }
  const H = A0 + ((g.hd - A0) % 360 + 540) % 360 - 180;
  const search = (x) => { const v = clamp((x - ts) / 900, 0, 1); return A0 + (H - A0) * 0.35 * v * v * (3 - 2 * v) + 30 * Math.sin((x - ts) / 520 * Math.PI * 2) * Math.min(1, (x - ts) / 250); };
  if (t < g.lockAt) return search(t);
  const tt = t - g.lockAt; let a = H + (search(g.lockAt) - H) * Math.exp(-tt / 240) * Math.cos(tt / 430 * Math.PI * 2);
  const tm = T.match, te = T.match + (T.end - T.match) * 0.62 + 520;
  if (t > tm && t < te) a += 1.8 * Math.sin((t - tm) / 46) * Math.sin(Math.PI * (t - tm) / (te - tm));
  return a;
}
function genAnim(g, el, kf, o) {
  if (!el || !el.animate) return null;
  const a = el.animate(kf, Object.assign({ fill: 'both', easing: G_EASE }, o)); g.anims.push(a); return a;
}
// 01 的 Orbit 母题：表盘从倾斜轨道视角翻正（rotateX 64° → 0°、转角 8° → 0°、0.62 → 1 倍），0.2–1.5 s；粒子与内弧用同一投影
const G_TILT = 1500;
function genTiltAt(t) { const u = genIO((t - 200) / (G_TILT - 200)); return { a: 64 * (1 - u), z: 8 * (1 - u), s: 0.62 + 0.38 * u }; }
function genProj(q, k) {
  const ca = Math.cos(k.a * Math.PI / 180), cz = Math.cos(k.z * Math.PI / 180), sz = Math.sin(k.z * Math.PI / 180);
  const dx = (q[0] - 200) * k.s, dy = (q[1] - 200) * ca * k.s;
  return [200 + dx * cz - dy * sz, 200 + dx * sz + dy * cz];
}
function genTilt(g, t) {
  const k = genTiltAt(t), done = t >= G_TILT;
  g.tiltEls.forEach((el) => { el.style.transform = done ? '' : 'rotate(' + k.z.toFixed(2) + 'deg) scale(' + k.s.toFixed(4) + ') rotateX(' + k.a.toFixed(2) + 'deg)'; });
  // 内弧（标志里半径 9/16 的那一段，左下 → 上 → 右）收拢成 00 方向的领瓣：每个采样点从弧上滑到指针上对应的位置
  if (g.arc) {
    const u = genIO((t - 420) / 540), n = 28, f = (q) => q[0].toFixed(1) + ' ' + q[1].toFixed(1); let d = '';
    for (let i = 0; i <= n; i++) { const A = pt(200, 112, (235 + i / n * 225) * Math.PI / 180), B = [200, 200 - FPG.NL * i / n]; d += (i ? 'L' : 'M') + f([A[0] + (B[0] - A[0]) * u, A[1] + (B[1] - A[1]) * u]); }
    g.arc.setAttribute('d', d); g.arc.style.opacity = String(clamp(1 - (t - 960) / 160, 0, 1));
  }
}
function genStage(g, t) { const s = g.box.querySelector('[data-g="stage"]'); if (!s) return; s.textContent = t; if (!g.done) s.animate([{ opacity: 0, transform: 'translateY(3px)' }, { opacity: 1, transform: 'none' }], { duration: 260, easing: G_EASE }); }
function genCount(g) {
  const el = g.box.querySelector('[data-g="count"]'); if (!el) return;
  const all = !g.N || g.arrived >= g.N; const f = all ? 1 : g.arrived / g.N;
  const t = '已读取 ' + fmt(Math.round(g.L.length * f)) + ' 个会话 · ' + fmt(Math.round(g.st.tools * f)) + ' 次工具调用';
  if (el.textContent !== t) el.textContent = t;
}
// 「看看优化建议」的条数：与侧栏角标同源（visibleRecs，live 下是 GET /v1/recommendations 的 A7 列表）；定型时再读一次
function genRecLine() { const vr = visibleRecs(); return vr.length + ' 条，其中 ' + vr.filter((r) => r.lvl === 1).length + ' 条可以一键应用'; }
function genOpen(mode, opt) {
  genStop();
  // live: opt.p / opt.cands carry the server persona (/v1/uiview/persona/reveal, mapped in 95-live-native.js)
  const L = opt.L, p = opt.p || persona(L), ob = mode === 'ob';
  const g = { mode, L, p, st: stats(L), F: genFacts(L), cands: opt.cands && opt.cands.length ? opt.cands : p.ok ? genCands(p) : [], T: genTimes(mode), timers: [], anims: [], raf: 0, done: false, arrived: 0, N: 0, flips: [-1, -1, -1, -1], locked: [false, false, false, false], t0: performance.now() };
  g.lockAt = g.T.grow + (g.T.match - g.T.grow) * 0.77;   // 第四个字母锁定的时刻（genPlay 里 0.32 + 3 × 0.15）
  GNS = g;
  const o = $('#overlay'); const old = ob ? o.querySelector('.obox') : null;
  const r0 = old && opt.from ? old.getBoundingClientRect() : null; const kids = r0 ? Array.from(old.childNodes) : null;
  let box = old;
  if (!box) { o.innerHTML = '<div class="obox"></div>'; box = o.firstChild; }
  box.id = ob ? 'genBox' : 'revBox'; box.className = 'obox gen' + (ob ? '' : ' reveal') + ' run'; box.tabIndex = -1;
  box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true');
  box.setAttribute('aria-label', ob ? '首次启动' : '人格揭晓：' + (p.ok ? p.code + ' ' + p.zh : '样本不足'));
  box.style.setProperty('--g-grow', g.T.grow + 'ms');
  box.innerHTML = genHTML(g); g.box = box; genMark(g);
  if (opt.final || reduceMotion()) { genFinal('init'); return; }
  genBloom(g, 0);
  if (g.sweepEl) g.sweepEl.style.strokeDashoffset = '1';
  g.pls.forEach((x) => { x.el.style.opacity = '0'; });
  if (ob) genTilt(g, 0);
  if (kids) {
    // 来源列表：留在原位收拢、模糊、淡出；盒子用 clip-path 从旧尺寸展开到新尺寸，新内容随后上浮淡入
    const gh = document.createElement('div'); gh.className = 'g-ghost'; gh.setAttribute('aria-hidden', 'true'); gh.inert = true;
    kids.forEach((n) => gh.appendChild(n)); box.prepend(gh);
    const r1 = box.getBoundingClientRect();
    Object.assign(gh.style, { width: r0.width + 'px', left: (r0.left - r1.left) + 'px', top: (r0.top - r1.top) + 'px' });
    const ins = 'inset(' + Math.max(0, r0.top - r1.top) + 'px ' + Math.max(0, r1.right - r0.right) + 'px ' + Math.max(0, r1.bottom - r0.bottom) + 'px ' + Math.max(0, r0.left - r1.left) + 'px round 14px)';
    box.classList.add('g-morph');
    genAnim(g, box, [{ clipPath: ins }, { clipPath: 'inset(0px 0px 0px 0px round 14px)' }], { duration: 620, fill: 'none' });
    genAnim(g, gh, [{ opacity: 1, transform: 'none', filter: 'blur(0px)' }, { opacity: 0, transform: 'scale(.965) translateY(-6px)', filter: 'blur(5px)' }], { duration: 460, fill: 'forwards' });
    g.timers.push(setTimeout(() => { gh.remove(); box.classList.remove('g-morph'); }, 640));
    Array.from(box.children).forEach((el, i) => { if (el !== gh) genAnim(g, el, [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 520, delay: 120 + i * 60 }); });
  } else genAnim(g, box, [{ opacity: 0, transform: 'scale(.98)' }, { opacity: 1, transform: 'none' }], { duration: 320 });
  genParticles(g, opt.from); genCount(g);
  genPlay(g);
  g.raf = requestAnimationFrame(() => genTick(g));
}
function genParticles(g, from) {
  const o = $('#overlay'), cs = getComputedStyle(g.box), T = g.T, ob = g.mode === 'ob', ow = o.getBoundingClientRect().width;
  const col = (c) => { const m = /^var\((--[\w-]+)\)$/.exec(c); return m ? cs.getPropertyValue(m[1]).trim() || '#888' : c; };
  const L = g.L.slice().sort((a, b) => (a.h * 60 + a.mi) - (b.h * 60 + b.mi));
  const N = Math.min(240, L.length), R = rng(hash('genesis' + L.length)), parts = [];
  const byH = new Array(24).fill(0); g.L.forEach((s) => { byH[s.h]++; }); const mxH = Math.max(1, ...byH);
  g.sweep = (T.grow - T.place) * 0.8;
  for (let i = 0; i < N; i++) {
    const s = L[Math.floor(i * L.length / N)];
    const a = (s.h + s.mi / 60) / 24 * Math.PI * 2;
    const src = from && from[s.a];
    const q = { c: col(agent(s.a).c), r: 2.3 + Math.min(s.msgs, 20) / 20 * 2, fin: pt(200, FPG.R0 + 4 + Math.min(s.dur, 126) / 126 * (FPG.RH - 6), a), pour: pt(200, FPG.R0 + byH[s.h] / mxH * FPG.RH * 0.55, a), ca: R() * Math.PI * 2, cr: 16 + R() * 70, bend: (R() < 0.5 ? -1 : 1) * (0.25 + R() * 0.55) };
    if (ob) { q.e = R() * 1050; q.fl = 760 + R() * 300; q.turns = 0.55 + R() * 0.6; if (src) { q.sx = src[0] + (R() - 0.5) * src[2] * 0.6; q.sy = src[1] + (R() - 0.5) * src[2] * 0.6; } else { q.sx = R() * ow; q.sy = -12; } }
    else { q.e = R() * 260; q.fl = 380 + R() * 220; q.gs = pt(200, 250 + R() * 90, R() * Math.PI * 2); }
    q.dep = Math.max(T.place + a / (Math.PI * 2) * g.sweep, q.e + q.fl + 60); q.land = q.dep + 380; q.pourAt = q.land + 240;
    parts.push(q);
  }
  g.parts = parts; g.N = N; g.surf = cs.getPropertyValue('--surface').trim();
  const cv = document.createElement('canvas'); cv.className = 'g-cv'; cv.setAttribute('aria-hidden', 'true'); o.appendChild(cv); g.cv = cv; g.ctx = cv.getContext('2d');
}
function genDraw(g, t, orc, sr) {
  const cv = g.cv, dpr = window.devicePixelRatio || 1, W = orc.width, H = orc.height;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const x = g.ctx; x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
  const k = sr.width / 400, ox = sr.left - orc.left, oy = sr.top - orc.top, tl = g.mode === 'ob' && t < G_TILT ? genTiltAt(t) : null;
  const U = (q) => { if (tl) q = genProj(q, tl); return [ox + q[0] * k, oy + q[1] * k]; };
  const cloud = (p, tt) => U(pt(200, p.cr, p.ca + tt * 0.0011));
  const lerp = (a, b, u) => [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
  let arrived = 0, live = 0;
  x.lineWidth = 1.2 * k; x.strokeStyle = g.surf;
  for (const p of g.parts) {
    if (t < p.e) { live++; continue; }
    let pos, r = p.r * k, al = 1;
    if (t < p.e + p.fl && p.turns) {
      // 导入（首次启动）：从来源图标被拉进倾斜的椭圆轨道，沿轨道顺时针螺旋收进中央的会话云；轨道随表盘一起翻正
      const u = (t - p.e) / p.fl, v = genIO(u), th = p.ca + (p.e + p.fl) * 0.0011 - (1 - v) * p.turns * Math.PI * 2;
      const sp = U(pt(200, p.cr + (196 - p.cr) * (1 - v) * (1 - v), th)), j = genIO(u / 0.38);
      pos = [p.sx + (sp[0] - p.sx) * j, p.sy + (sp[1] - p.sy) * j];
      al = Math.min(1, (t - p.e) / 160); r *= 0.65 + 0.35 * v;
    } else if (t < p.e + p.fl) {
      // 汇集（揭晓）：二次贝塞尔，从表盘外一圈弯向中央的会话云
      const u = genIO((t - p.e) / p.fl), st = p.gs ? U(p.gs) : [p.sx, p.sy], en = cloud(p, t);
      const cx = (st[0] + en[0]) / 2 - (en[1] - st[1]) * p.bend, cy = (st[1] + en[1]) / 2 + (en[0] - st[0]) * p.bend, v = 1 - u;
      pos = [v * v * st[0] + 2 * v * u * cx + u * u * en[0], v * v * st[1] + 2 * v * u * cy + u * u * en[1]];
      al = Math.min(1, (t - p.e) / 160); r *= 0.65 + 0.35 * u;
    } else if (t < p.dep) { arrived++; pos = cloud(p, t); }
    else if (t < p.land) { arrived++; pos = lerp(cloud(p, p.dep), U(p.fin), genIO((t - p.dep) / (p.land - p.dep))); }
    else if (t < p.pourAt) { arrived++; pos = U(p.fin); }
    else if (t < p.pourAt + 360) { arrived++; const u = genIO((t - p.pourAt) / 360); pos = lerp(U(p.fin), U(p.pour), u); r *= 1 - u * 0.9; al = 1 - u * 0.7; }
    else { arrived++; continue; }
    live++;
    x.globalAlpha = al; x.beginPath(); x.arc(pos[0], pos[1], Math.max(0.2, r), 0, Math.PI * 2); x.fillStyle = p.c; x.fill(); if (r > 1.6) x.stroke();
  }
  x.globalAlpha = 1; g.arrived = arrived;
  if (!live) { cv.remove(); g.cv = null; }
}
function genTick(g) {
  if (GNS !== g || g.done) return;
  const t = performance.now() - g.t0, T = g.T;
  // 先读布局（overlay 与指纹的位置），再写 canvas / 文本 / 属性
  // 指纹的未变换位置：.g-dial 的内框（.fp-wrap 留 8px 纸边）；翻正期间 .g-fp 带 3D 变换，不能直接量 svg
  const orc = $('#overlay').getBoundingClientRect(), dl = g.svg ? g.box.querySelector('[data-g="dial"]') : null, dr = dl ? dl.getBoundingClientRect() : null;
  const sr = dr ? { left: dr.left + 8, top: dr.top + 8, width: dr.width - 16 } : null;
  if (g.cv && sr) genDraw(g, t, orc, sr);
  if (!g.counted) { genCount(g); if (g.arrived >= g.N) g.counted = true; }
  if (t >= T.grow && !g.roseDone) { const u = (t - T.grow) / ((T.match - T.grow) * 0.7); genBloom(g, Math.min(u, 1)); if (u >= 1) g.roseDone = true; }
  if (g.nd) g.nd.style.transform = 'rotate(' + genNeedle(g, t).toFixed(2) + 'deg)';
  if (g.mode === 'ob' && !g.flat) { genTilt(g, t); if (t >= G_TILT + 200) g.flat = true; }
  // 02：环带在指针扫过处长出（比指针晚 450 ms，等粒子落位）；行星依次出现、跟在指针后公转，扫完走最短弧滑到各自的协作重心
  const P = T.place, sw = g.sweep;
  if (g.sweepEl && !g.swept) { const v = clamp((t - P - 450) / sw, 0, 1); g.sweepEl.style.strokeDashoffset = (1 - v).toFixed(4); if (v >= 1) { g.sweepEl.style.strokeDashoffset = ''; g.swept = true; } }
  if (g.pls.length && !g.settled) {
    let all = true;
    g.pls.forEach((x, i) => {
      const ride = (tt) => clamp((tt - P) / sw, 0, 1) * 360 - 16 - 9 * i, t1 = P + sw, ra = ride(t1), d = ((x.deg - ra) % 360 + 540) % 360 - 180;
      const u = clamp((t - t1 - i * 60) / 800, 0, 1), a = t < t1 ? ride(t) : ra + d * genIO(u);
      x.el.style.opacity = String(clamp((t - P - 120 - i * 110) / 220, 0, 1)); x.el.style.transform = 'rotate(' + a.toFixed(2) + 'deg)';
      if (u < 1) all = false;
    });
    if (all) { g.pls.forEach((x) => { x.el.style.opacity = ''; x.el.style.transform = ''; }); g.settled = true; }
  }
  if (t >= T.grow + 60) g.slotL.forEach((el, i) => {
    if (g.locked[i]) return;
    const f = Math.floor((t - T.grow) / 85); if (f === g.flips[i]) return; g.flips[i] = f;
    el.textContent = G_PAIRS[i][(f + i) % 2];
    el.animate([{ transform: 'translateY(-34%) scaleY(.55)', opacity: 0.25 }, { transform: 'none', opacity: 1 }], { duration: 80, easing: 'ease-out' });
  });
  if (g.cards) g.cards.forEach((c, j) => { const u = clamp((t - g.cardT - j * 70) / 600, 0, 1); const v = Math.round(c.sim * (1 - Math.pow(1 - u, 3))) + '%'; if (c.pc.textContent !== v) c.pc.textContent = v; });
  if (t < T.end + 60) g.raf = requestAnimationFrame(() => genTick(g));
}
function genLock(g, i) {
  g.locked[i] = true; const el = g.slotL[i]; if (!el) return;
  el.textContent = g.p.ok ? g.p.code[i] : '—'; el.parentNode.classList.add('lock');
  genAnim(g, el, [{ transform: 'scale(1.3)', opacity: 0.4 }, { transform: 'scale(.93)', opacity: 1, offset: 0.55 }, { transform: 'none', opacity: 1 }], { duration: 520, easing: 'ease-out', fill: 'none' });
  genAnim(g, el.parentNode.querySelector('.g-ax'), [{ opacity: 0, transform: 'translateY(-4px)' }, { opacity: 1, transform: 'none' }], { duration: 320 });
}
function genFactRun(g, i) { const r = g.box.querySelectorAll('.g-fact')[i]; if (!r) return; r.classList.add('run'); r.querySelector('.mk').innerHTML = '<span class="spin" style="width:12px;height:12px"></span>'; }
function genFact(g, i) {
  const rows = g.box.querySelectorAll('.g-fact'); const r = rows[i]; if (!r) return;
  r.classList.remove('run'); r.classList.add('done'); r.querySelector('.mk').textContent = '✓';
  genAnim(g, r.querySelector('.g-sub'), [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(-6px)' }], { duration: 260, fill: 'forwards' });
  genAnim(g, r.querySelector('.g-fx'), [{ opacity: 0, transform: 'translateX(-10px)' }, { opacity: 1, transform: 'none' }], { duration: 420, delay: 120 });
  if (rows[i + 1]) genFactRun(g, i + 1);
  if (g.mode === 'ob' && OB) OB.prog = i;
  const bar = g.box.querySelector('[data-g="bar"]'); if (bar) bar.style.width = ((i + 1) / 4 * 100) + '%';
}
// 候选类型卡：绕表盘出现（打乱的位置）→ 按相似度移到名次位 → 其余淡出 → 第一名飞进四字母
function genCards(g) {
  const box = g.box, wrap = box.querySelector('[data-g="cards"]'), dial = box.querySelector('[data-g="dial"]'); if (!wrap || !dial) return;
  const T = g.T, ml = T.end - T.match, top = g.cands.slice(0, 6), win = g.p.classified;
  const at = (ms, fn) => g.timers.push(setTimeout(() => { if (GNS === g && !g.done) fn(); }, ms));
  const D = dial.clientWidth, H = dial.clientHeight, ANG = [0, 60, 300, 120, 240, 180], perm = [3, 0, 5, 1, 4, 2];
  const slot = (j) => { const a = ANG[j] * Math.PI / 180; return [D / 2 + Math.sin(a) * (D / 2 - 26), H / 2 - Math.cos(a) * (H / 2 - 14)]; };
  wrap.innerHTML = top.map((c) => '<div class="card g-card"><span class="mono c">' + c.c + '</span><span class="mono pc">0%</span><span class="z">' + c.zh + '</span></div>').join('');
  const els = Array.from(wrap.children); g.cardT = performance.now() - g.t0;
  g.cards = els.map((el, j) => ({ sim: top[j].sim, pc: el.querySelector('.pc') }));
  els.forEach((el, j) => { const s = slot(perm[j]); el.style.left = s[0] + 'px'; el.style.top = s[1] + 'px'; genAnim(g, el, [{ opacity: 0, transform: 'translate(' + ((D / 2 - s[0]) * 0.55).toFixed(1) + 'px,' + ((H / 2 - s[1]) * 0.55).toFixed(1) + 'px) scale(.6)' }, { opacity: 1, transform: 'none' }], { duration: 440, delay: j * 70, easing: G_SPRING }); });
  at(ml * 0.3, () => els.forEach((el, j) => {
    const a = slot(perm[j]), b = slot(j); el.style.left = b[0] + 'px'; el.style.top = b[1] + 'px';
    genAnim(g, el, [{ transform: 'translate(' + (a[0] - b[0]).toFixed(1) + 'px,' + (a[1] - b[1]).toFixed(1) + 'px)' }, { transform: 'none' }], { duration: 540, easing: G_SPRING, fill: 'none' });
    if (j === 0 && win) el.classList.add('win');
  }));
  at(ml * 0.55, () => els.forEach((el, j) => { if (j === 0 && win) return; genAnim(g, el, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.86)' }], { duration: 280, delay: (5 - j) * 50, fill: 'forwards' }); }));
  if (win) at(ml * 0.62, () => {
    const el = els[0], code = box.querySelector('[data-g="code"]'); const cr = el.getBoundingClientRect(), tr = code.getBoundingClientRect();
    const dx = tr.left + tr.width / 2 - (cr.left + cr.width / 2), dy = tr.top + tr.height / 2 - (cr.top + cr.height / 2);
    genAnim(g, el, [{ transform: 'none', opacity: 1 }, { transform: 'translate(' + (dx * 0.8).toFixed(1) + 'px,' + (dy * 0.8).toFixed(1) + 'px) scale(.8)', opacity: 1, offset: 0.7 }, { transform: 'translate(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px) scale(.55)', opacity: 0 }], { duration: 560, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'forwards' });
    at(500, () => genAnim(g, code, [{ transform: 'none' }, { transform: 'scale(1.06)', offset: 0.4 }, { transform: 'none' }], { duration: 480, fill: 'none' }));
  });
}
function genPlay(g) {
  const T = g.T, box = g.box, ob = g.mode === 'ob', q = (s) => box.querySelector(s), qa = (s) => Array.from(box.querySelectorAll(s));
  const at = (ms, fn) => g.timers.push(setTimeout(() => { if (GNS === g && !g.done) fn(); }, ms));
  const A = (el, kf, o) => genAnim(g, el, kf, o), fade = { opacity: [0, 1] };
  const gl = T.match - T.grow, ml = T.end - T.match, n = fmt(g.L.length), sw = g.sweep;
  const lab = [[0, (ob ? '01 / 导入 · 读取 ' : '01 / 汇集 · 读取 ') + n + ' 个会话'], [T.place, '02 / 归位 · 花苞扫过 24 小时，会话按开始时间落位'], [T.grow, '03 / 开花 · 长成你的协作人格之花'], [T.match, ob ? '04 / 匹配 · 16 种类型里找最接近的' : '04 / 定型 · ' + (g.p.ok ? g.p.code : '—')]];
  genStage(g, lab[0][1]); lab.slice(1).forEach((x) => at(x[0], () => genStage(g, x[1])));
  // 01：罗盘外框画出 → 外框刻度淡入；中心的内盘与花苞随即出现（花的角度在 genTick 里逐帧写）。
  // 首次启动时外框先是 Orbit 标志的倾斜椭圆（石板灰、留一道缺口），随翻正补全并换成外框的墨色
  if (ob) A(q('.g-ring0'), [{ strokeDashoffset: 0.17, stroke: 'var(--orbit)', strokeWidth: 4.5 }, { strokeDashoffset: 0.12, stroke: 'var(--orbit)', strokeWidth: 4.5, offset: 0.4 }, { strokeDashoffset: 0, stroke: 'var(--ink-2)', strokeWidth: 1.2 }], { duration: G_TILT, easing: 'ease-in-out' });
  else A(q('.g-ring0'), [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: 600 });
  A(q('.g-ticks'), fade, { duration: 500, delay: ob ? 500 : 200 });
  qa('.g-fp .fp-base').forEach((el) => A(el, fade, { duration: 600, delay: ob ? 700 : 250 }));
  A(q('.g-fp .fp-core'), [{ opacity: 0, transform: 'scale(.82)' }, { opacity: 1, transform: 'none' }], { duration: 520, delay: ob ? 700 : 80 });
  A(q('.g-fp .fp-flower'), [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'none' }], { duration: 480, delay: ob ? 860 : 120, easing: G_SPRING });
  // 02：扫掠扇形跟着花苞转一圈，会话点在领瓣扫过处落位；节律带与方位数字淡入（轨道环带与行星在 genTick 里跟着扫描写）
  A(q('.g-hand'), [{ transform: 'rotate(0deg)', opacity: 0 }, { transform: 'rotate(21.6deg)', opacity: 1, offset: 0.06 }, { transform: 'rotate(338.4deg)', opacity: 1, offset: 0.94 }, { transform: 'rotate(360deg)', opacity: 0 }], { duration: sw, delay: T.place, easing: 'linear' });
  qa('.g-fp .fp-band, .g-fp .fp-hours').forEach((el) => A(el, fade, { duration: 700, delay: T.place }));
  A(q('.g-over'), [{ opacity: 1 }, { opacity: 0 }], { duration: 500, delay: T.grow + 200 });
  // 03：花苞在 rAF 里开成该类型的花；字母位翻牌（花寻向），按顺序锁定
  [0, 1, 2, 3].forEach((i) => at(T.grow + gl * 0.32 + i * gl * 0.15, () => genLock(g, i)));
  // 已经知道的：每完成一段给一条
  genFactRun(g, 0);
  [T.place - 200, T.grow - 100, T.grow + gl * 0.6, T.match + ml * 0.4].forEach((ms, i) => at(ms, () => genFact(g, i)));
  // 04：候选卡 → 匹配度、名字与一句话
  if (g.p.ok) at(T.match, () => genCards(g));
  at(T.match + ml * 0.8, () => A(q('[data-g="match"]'), [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 420 }));
  at(T.match + ml * 0.86, () => A(q('[data-g="nm"]'), [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 520 }));
  at(T.end, () => genFinal('end'));
}
// 最终态：跳过、自然结束、减少动态效果与第 3 步直开都走这里
function genFinal(how) {
  const g = GNS; if (!g || g.done) return;
  g.done = true; g.timers.forEach(clearTimeout); g.timers = []; cancelAnimationFrame(g.raf);
  g.anims.forEach((a) => { try { a.cancel(); } catch (e) { /* detached */ } }); g.anims = [];
  if (g.cv) { g.cv.remove(); g.cv = null; }
  const box = g.box, ob = g.mode === 'ob', p = g.p, q = (s) => box.querySelector(s);
  box.querySelectorAll('.g-ghost').forEach((el) => el.remove()); box.classList.remove('run', 'g-morph'); box.classList.add('skip');
  genBloom(g, 1); if (g.nd) g.nd.style.transform = '';
  if (g.sweepEl) g.sweepEl.style.strokeDashoffset = '';
  g.pls.forEach((x) => { x.el.style.opacity = ''; x.el.style.transform = ''; });
  g.tiltEls.forEach((el) => { el.style.transform = ''; });
  g.slotL.forEach((el, i) => { el.textContent = p.ok ? p.code[i] : '—'; el.parentNode.classList.add('lock'); });
  const cw = q('[data-g="cards"]'); if (cw) cw.innerHTML = ''; g.cards = null;
  g.arrived = g.N; genCount(g);
  box.querySelectorAll('.g-fact').forEach((r) => { r.classList.remove('run'); r.classList.add('done'); r.querySelector('.mk').textContent = '✓'; });
  const bar = q('[data-g="bar"]'); if (bar) bar.style.width = '100%';
  const run = q('[data-g="run"]'); if (run) run.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  const sk = q('[data-act="genSkip"], [data-act="revSkip"]'); if (sk) sk.hidden = true;
  const dn = q('[data-g="done"]'); if (dn) { dn.querySelectorAll('button').forEach((b) => { b.disabled = false; }); if (how !== 'init') dn.animate([{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 420, easing: G_EASE }); }
  if (ob) {
    genStage(g, '05 / 定型 · ' + (p.ok ? p.code : '样本不足'));
    const nn = q('[data-g="n"]'); if (nn) nn.textContent = '4 / 4'; box.querySelectorAll('.ob-dots i').forEach((i) => i.classList.add('on'));
    const hd = q('[data-g="head"]'); if (hd) { hd.querySelector('h2').textContent = p.ok ? '你的协作画像已经生成' : '样本还不够'; hd.querySelector('p').textContent = '基于 ' + fmt(g.L.length) + ' 个会话' + (p.partial ? ' · 部分结果，分析仍在更新，以画像页为准' : p.ok ? ' · 之后可以在画像页「重播揭晓」' : ' · 先用一段时间再来看'); }
    const rl = box.querySelector('.g-next .g-nc'); if (rl) rl.textContent = genRecLine();
    if (OB) { OB.prog = 3; OB.step = 3; OB.drawn = 3; }
    const f = q('[data-act="obDone"]'); if (f) f.focus({ preventScroll: true });
    render();
  } else {
    genStage(g, '05 / 定型 · ' + (p.ok ? p.code : '样本不足'));
    if (REV) { REV.done = true; REV.timers.forEach(clearTimeout); }
    if (how !== 'init') { const f = q('[data-act="revGo"]'); if (f) f.focus(); }
  }
}
function genStop() {
  const g = GNS; if (!g) return; GNS = null;
  g.done = true; g.timers.forEach(clearTimeout); cancelAnimationFrame(g.raf);
  g.anims.forEach((a) => { try { a.cancel(); } catch (e) { /* detached */ } });
  if (g.cv) g.cv.remove();
  if (g.land) g.land();
}
// The landing page shows the scope first launch just analysed (90 days when「只分析最近 90 天」is on, else all history):
// Lite reads S.range, Advance's persona page its own period, so both are aligned and the numbers do not jump on arrival.
function obScope() { if (!OB) return; S.range = OB.recent ? 90 : 0; S.persona.period = OB.recent ? '90' : 'all'; }
// 05 落地：大人格码逐字母、指纹整体从 overlay FLIP 到画像页 [data-hero]；overlay 同时淡出，目标页内容随后淡入。
// Lite 的 l-persona 或目标不在可视区时退化为原地缩小淡出。
function genLand() {
  const g = GNS, box = g && g.box;
  if (!g || !box || reduceMotion() || g.land) { closeOverlay(); go('persona'); return; }
  const o = $('#overlay');
  const fromL = g.slotL.map((el) => [el, el.getBoundingClientRect()]);
  const fromF = g.svg ? [g.svg, g.svg.getBoundingClientRect()] : null;
  const fly = [], hid = [], an = [];
  const clone = (el, r) => {
    const c = el.cloneNode(true); const cs = getComputedStyle(el); c.removeAttribute('id'); c.classList.add('g-fly');
    Object.assign(c.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px', font: cs.font, letterSpacing: cs.letterSpacing, color: cs.color, lineHeight: r.height + 'px' });
    document.body.appendChild(c); fly.push(c); return c;
  };
  const cL = fromL.map((x) => clone(x[0], x[1])); const cF = fromF ? clone(fromF[0], fromF[1]) : null;
  g.land = () => { g.land = null; an.forEach((a) => { try { a.cancel(); } catch (e) { /* detached */ } }); fly.forEach((c) => c.remove()); hid.forEach((el) => { el.style.visibility = ''; }); o.style.pointerEvents = ''; };
  o.style.pointerEvents = 'none';
  an.push(o.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 380, easing: 'ease-out', fill: 'forwards' }));
  go('persona');
  const main = $('#main'), cont = $('#content'), cr = cont ? cont.getBoundingClientRect() : null;
  const seen = (r) => !!cr && r.width > 4 && r.bottom > cr.top + 24 && r.top < cr.bottom - 24;
  const tL = main ? Array.from(main.querySelectorAll('[data-hero="code"] .L')) : [];
  const tH = main ? main.querySelector('[data-hero="fp"]') : null; const tF = tH ? (tH.querySelector('svg') || tH) : null;
  if (cont) an.push(cont.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], { duration: 480, delay: 160, easing: G_EASE, fill: 'backwards' }));
  const flyTo = (c, r0, el, i, byW) => {
    const r1 = el ? el.getBoundingClientRect() : null;
    if (!r1 || !seen(r1) || !r0.width || !r0.height) { an.push(c.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.9)' }], { duration: 360, delay: i * 30, easing: G_EASE, fill: 'forwards' })); return; }
    const s = byW ? r1.width / r0.width : r1.height / r0.height;
    const dx = r1.left + r1.width / 2 - (r0.left + r0.width / 2), dy = r1.top + r1.height / 2 - (r0.top + r0.height / 2);
    hid.push(el); el.style.visibility = 'hidden';
    an.push(c.animate([{ transform: 'none' }, { transform: 'translate(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px) scale(' + s.toFixed(3) + ')' }], { duration: byW ? 700 : 640, delay: i * 45, easing: byW ? G_EASE : 'cubic-bezier(.3,1.25,.5,1)', fill: 'forwards' }));
  };
  cL.forEach((c, i) => flyTo(c, fromL[i][1], tL.length === 4 ? tL[i] : null, i, false));
  if (cF) flyTo(cF, fromF[1], tF, 0, true);
  g.timers.push(setTimeout(() => {
    if (GNS !== g) return;
    // 字母落在同一位置、同一字形：直接换成目标，不做交叉淡化（否则会叠出灰影）；指纹数据口径不同，交叉淡化
    hid.forEach((el) => { el.style.visibility = ''; if (el === tF) an.push(el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 240, easing: 'ease-out' })); });
    cL.forEach((c) => { c.style.visibility = 'hidden'; });
    if (cF) an.push(cF.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 240, easing: 'ease-out', fill: 'forwards' }));
  }, 760));
  g.timers.push(setTimeout(() => { if (GNS === g) closeOverlay(); }, 980));
}
function openReveal(opt) {
  closeModal(); closeDD(); closeOverlay();
  const per = PERIODS[S.persona.period]; const L = opt && opt.L ? opt.L : S.route === 'persona' ? sel({ win: [per[0], per[1]] }) : sel({ noExtra: true }); const p = opt && opt.p || persona(L);
  if (!p.ok) { toast('当前范围还没有会话，暂时不能揭晓'); return; }
  if (!p.classified) { toast('协作画像正在更新，稍后再揭晓'); return; }   // 旧版快照（带「?」）才会走到这里
  REV = { done: false, timers: [] }; OVL = 'reveal';
  const o = $('#overlay'); o.hidden = false; o.innerHTML = '';
  genOpen('rev', { L, p, cands: opt && opt.cands });
  const bx = $('#revBox'); if (bx) bx.focus({ preventScroll: true });
}
function revealSkip() {
  if (!REV || REV.done) return;
  if (GNS && GNS.mode === 'rev') genFinal('skip'); else REV.done = true;
}
$('#overlay').addEventListener('click', (e) => {
  if (OVL !== 'reveal' || !REV) return;
  if (!REV.done && !e.target.closest('button')) { revealSkip(); return; }
  if (REV.done && e.target.id === 'overlay') closeOverlay();
});
Object.assign(ACT, {
  obNext: () => { OB.step = 1; drawOB(); },
  obBack: () => { OB.step = 0; drawOB(); },
  obClose: () => { closeOverlay(); render(); },
  obPrivacy: () => { closeOverlay(); openSettings('privacy'); },
  obSrc: (el) => { const id = el.dataset.a; if (el.checked) OB.src.add(id); else OB.src.delete(id); drawOB(); },
  obRecent: () => { OB.recent = !OB.recent; drawOB(); },
  obStart: () => { AG.forEach((a) => { if (OB.src.has(a.id)) S.srcOff.delete(a.id); else S.srcOff.add(a.id); }); OB.step = 2; OB.prog = -1; const from = obSources(); genOpen('ob', { L: obSel(), from }); },
  genSkip: () => genFinal('skip'),
  obBg: () => { const p = obPersona(); closeOverlay(); render(); setTimeout(() => { notify({ t: '协作画像已生成', b: p.ok ? '你是 ' + p.code + '「' + p.zh + '」。点开看看四个维度和协作指纹。' : '已选来源还没有会话，暂时无法给出类型。', a1: '查看', on1: () => { obScope(); go('persona'); }, force: true }); }, 2600); },
  obDone: () => { obScope(); genLand(); },
  obShare: () => { closeOverlay(); render(); openShare(); },
  obReveal: () => { const L = obSel(); closeOverlay(); render(); openReveal({ L }); },
  revSkip: () => revealSkip(),
  revGo: () => genLand(),
  revShare: () => { closeOverlay(); openShare(); }
});
// Tab stays inside the open overlay box (first launch or reveal); without this it walks on to the menu bar behind the scrim (BUG-55).
$('#overlay').addEventListener('keydown', (e) => {
  if (e.key !== 'Tab') return;
  const f = $$('#overlay button:not([disabled]):not([hidden]), #overlay input:not([disabled]), #overlay [tabindex="0"]').filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1], a = document.activeElement;
  if (e.shiftKey && (a === first || !$('#overlay').contains(a) || a === $('#revBox'))) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (a === last || !$('#overlay').contains(a) || a === $('#revBox'))) { e.preventDefault(); first.focus(); }
});
