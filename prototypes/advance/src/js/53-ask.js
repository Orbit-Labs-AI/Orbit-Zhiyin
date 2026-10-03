/* ============ ask the local agent (canned, data-driven answers) ============ */
const ASKQ = {
  overview: ['和上一个周期比，最大的变化是什么？', '我现在最该先做哪一件事？', '摩擦率为什么是这个数？'],
  persona: ['为什么判定我是这个类型？', '换一种协作方式会更好吗？', '我的盲点该怎么补？'],
  recs: ['按投入产出比给这些建议排个序', '哪些建议可以一起装？', '还有没有我没想到的方向？'],
  session: ['这个会话卡在哪里？', '下次同类任务该怎么开场？', '帮我写一条规则避免重复'],
  tools: ['哪个工具最值得优化？', '审批太多怎么办？', '哪个 MCP 可以删掉？']
};
const ASKN = { overview: '概览', persona: '协作人格', recs: '优化建议', session: '当前会话', tools: '工具调用' };
const FRIC_RULE = { '方向错误': '开始改动前，先用三句话复述目标和完成条件，等我确认再动手。', '改动过度': '只改与任务直接相关的文件；超出范围的改动先列出来问我。', '工具 / 环境失败': '同一命令失败 2 次后停止重试，先检查认证与环境，再告诉我原因。', '流程过重（子代理）': '简单任务不要启动子代理；确实需要时先问我。', '误解需求': '需求有歧义时先提问，不要猜。', '并行会话冲突': '并行会话各自使用独立的 worktree，不要改同一个工作目录。', '额度 / 用量中断': '长任务分段完成，每段结束时写一段进度摘要。' };
let ASK = null;
function askAnswer(ctx, i) {
  const L = sel(); const st = stats(L); const p = personaNow();
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]);
  const recs = visibleRecs().filter((r) => !S.installed.has(r.id));
  const pct = (a, b) => (a >= b ? '+' : '−') + Math.round(Math.abs(a - b) / Math.max(1, b) * 100) + '%';
  if (ctx === 'overview') {
    if (i === 0) {
      const pw = prevWin(S.range); if (!pw) return '当前看的是全部历史，没有可比的上一个周期。切到 7、30 或 90 天再问我。';
      const PL = sel({ win: pw }); const P = stats(PL); const ra = projRows(L), rb = projRows(PL);
      const dl = ra.map((r, k) => [r.p.name, r.st.hours - rb[k].st.hours]).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
      return '和上一个同样长度的周期相比：\n\n· 会话 ' + P.n + ' → ' + st.n + '（' + pct(st.n, P.n) + '）\n· 协作时长 ' + f1(P.hours) + 'h → ' + f1(st.hours) + 'h\n· 摩擦率 ' + f1(P.fric) + '% → ' + f1(st.fric) + '%\n\n变化最大的是「' + dl[0] + '」：协作时长' + (dl[1] >= 0 ? '多了 ' : '少了 ') + f1(Math.abs(dl[1])) + ' 小时。' + (st.fric > P.fric ? '摩擦率在上升，主要来自「' + (fr[0] ? fr[0][0] : '—') + '」。' : '摩擦率在下降，最近加的规则可能起了作用。');
    }
    if (i === 1) { const r = recs[0]; return r ? '先做「' + r.title + '」。\n\n理由：' + r.why + '它属于' + LEVELS[r.lvl] + '，预计 ' + r.gain + '。\n\n做完之后再看「' + (recs[1] ? recs[1].title : '—') + '」。两条加起来不到 10 分钟。' : '当前可见的建议都已经处理了。7 天后到「效果追踪」看结果。'; }
    return '摩擦率 = 纠偏与不满消息 ÷ 你的消息 = ' + fmt(st.corr) + ' ÷ ' + fmt(st.msgs) + ' = ' + f1(st.fric) + '%。\n\n' + (fr.length ? '最常见的是「' + fr[0][0] + '」（' + fr[0][1] + ' 个会话）' + (fr[1] ? '和「' + fr[1][0] + '」（' + fr[1][1] + ' 个）' : '') + '。这两类都能用规则前置：写进 AGENTS.md 后，Agent 会先遵守，而不是等你提醒。' : '这段时间没有记录到摩擦。');
  }
  if (ctx === 'persona') {
    if (!p.ok) return '样本不足（少于 30 个会话），暂时不判断类型。';
    const ax = AXES.map((a, k) => axisView(p, k)).sort((a, b) => b.strong - a.strong);
    if (i === 0) return '依据 ' + p.n + ' 个会话：\n\n' + AXES.map((a, k) => { const v = axisView(p, k); return '· ' + a.dim + '：' + v.letter + ' ' + v.name + ' ' + v.strong + '（信号：' + a.sig + '）'; }).join('\n') + '\n\n最鲜明的是「' + ax[0].name + '」（' + ax[0].strong + '），最接近中间的是「' + ax[3].name + '」（' + ax[3].strong + '）。';
    if (i === 1) { const c = { D: '委托多：吞吐高，但方向一错代价也大', S: '掌舵多：方向稳，但你的时间被大量小指令占用', I: '即兴多：启动快，但更容易中途改向', P: '规划多：返工少，但前期投入大', M: '多线并行：产出多，但并行会话互相冲突的风险更高', F: '专注单线：质量稳，但等待 Agent 的时间更长', V: '验收严：结果可靠，但会花更多时间检查', T: '信任多：节奏快，但问题更晚才暴露' }; return '类型没有好坏，只有取舍。' + p.code + ' ' + p.zh + ' 的取舍是：\n\n' + p.code.split('').filter((x) => c[x]).map((x) => '· ' + c[x]).join('\n') + '\n\n不必换类型，把代价最高的环节前置成规则就行。可以从「' + (recs[0] ? recs[0].title : '—') + '」开始。'; }
    return '你的盲点主要在「' + (fr[0] ? fr[0][0] : '—') + '」' + (fr[1] ? '和「' + fr[1][0] + '」' : '') + '。\n\n建议：\n· ' + (fr[0] && FRIC_RULE[fr[0][0]] ? FRIC_RULE[fr[0][0]] : '在首条消息里写清完成条件') + '\n· ' + recs.slice(0, 2).map((r) => r.title).join('\n· ');
  }
  if (ctx === 'recs') {
    if (i === 0) return '按「预计收益 ÷ 投入」排序：\n\n' + recs.slice().sort((a, b) => a.lvl - b.lvl).slice(0, 5).map((r, k) => (k + 1) + '. ' + r.title + '（' + LEVELS[r.lvl] + ' · ' + r.gain + '）').join('\n') + '\n\nL1、L2 的几条加起来不到 15 分钟，先做这些。';
    if (i === 1) return '可以一起装：\n· 只读命令自动放行 + 重复失败熔断：都写在 settings.json，但字段不同，互不影响\n· PR 收尾 + 验收清单：都是 Skill，触发条件不同\n\n不建议同时启用：\n· 降低思考等级 + 无人值守任务：无人值守时更需要高思考等级';
    return '还可以考虑（这些不在你的数据里，属于推测）：\n· 为 latentskill 建一个「投稿前检查」工作流：页数、匿名化、引用格式一次查完\n· 把每天的 team-hub 审核做成定时的无人值守任务\n· 给 Surge 规则的发布加一步 dry-run，先看差异再上传';
  }
  if (ctx === 'session') {
    const s = BYID[S.sess.sel]; if (!s) return '先在左侧选一个会话。';
    if (i === 0) return '「' + s.title + '」：' + dur(s.dur) + '，' + s.tools + ' 次工具调用，' + s.errors + ' 次错误，' + s.corr + ' 次纠偏。\n\n' + (s.fric ? '主要卡在「' + s.fric + '」。' + (FRIC_RULE[s.fric] ? '下次可以提前约定：' + FRIC_RULE[s.fric] : '') : '整体顺利，没有明显卡点。') + (s.errors > 3 ? '\n错误集中在 Bash，多数是环境或权限问题，不是代码本身。' : '');
    if (i === 1) return '下次同类任务，第一条消息可以这样写：\n\n目标：' + s.title + '\n完成条件：（写清可以验证的结果，比如「线上返回 200」或「编译通过且 ≤ 9 页」）\n不要做：' + (s.fric && FRIC_RULE[s.fric] ? FRIC_RULE[s.fric] : '不要改与任务无关的文件') + '\n验证方式：完成后贴出命令输出\n\n你过去这样开场时，纠偏少了约 30%。';
    return '## ' + PJI[s.p].name + ' 协作约定\n\n- ' + (s.fric && FRIC_RULE[s.fric] ? FRIC_RULE[s.fric] : '只改与任务直接相关的文件。') + '\n- 完成后先自查，再向我汇报验证结果。\n\n可以复制到项目的 AGENTS.md，或交给生成工坊做成 Hook。';
  }
  const rows = toolRows(L).sort((a, b) => b.fails - a.fails);
  if (i === 0) return rows[0].name + ' 失败最多：' + fmt(rows[0].fails) + ' 次（错误率 ' + f1(rows[0].err * 100) + '%）。其中最多的是「' + FAILS[0][0] + '」，占 ' + FAILS[0][1] + '%。\n\n装「重复失败熔断」后，同一命令失败 2 次会先停下诊断，不再原样重试。';
  if (i === 1) { const b = toolRows(L).find((r) => r.name === 'Bash'); return 'Bash 有 ' + Math.round(b.ap * 100) + '% 的调用需要你审批，其中大部分是 git status、ls、gh pr view 这类只读命令。\n\n把只读命令放进允许列表，每月大约能少 212 次审批；含写操作的命令仍然需要你确认。'; }
  return !S.installed.has('remove-figma') ? 'figma 这个 MCP 近 30 天没有被调用过，但每个会话都会加载它的工具描述（约 2.1k tokens）。可以先移除，需要时再装回来。' : 'figma 已经移除了。剩下的 browser MCP 失败率 7.8%，主要是页面加载超时，可以把等待时间调长一点。';
}
function openAsk(ctx) {
  if (S.engine === 'stats') { toast('仅统计模式下无法使用 Agent 问答，请在设置中切换分析引擎'); return; }
  clearInterval(ASKT); ASK = { ctx: ASKQ[ctx] ? ctx : 'overview', q: '', text: '' };
  const c = ASK.ctx;
  openModal(modalHead('问本地 Agent', '本地 ' + agent(S.studio.agent).name + ' · ' + ASKN[c] + ' · ' + rangeLabel() + (typeof LV !== 'undefined' && LV.live ? '' : ' · Demo 为预置回答')) +
    '<div class="mb col" style="gap:10px"><div class="row" style="flex-wrap:wrap;gap:6px">' + ASKQ[c].map((q, i) => '<button type="button" class="chip sm" data-act="askPick" data-i="' + i + '">' + esc(q) + '</button>').join('') + '</div>' +
    '<div class="ask-a" id="askA" aria-live="polite"><span class="cap ask-empty">选一个问题，或在下方输入你自己的问题</span></div>' +
    '<div class="row"><label class="vh" for="askIn">你的问题</label><input id="askIn" placeholder="输入问题，回车发送" autocomplete="off" style="' + FIELD + ';height:32px"><button type="button" class="btn p" data-act="askSend" style="height:32px">发送</button></div></div>' +
    '<div class="mf"><span class="row cap" style="margin-right:auto;font-size:11px">' + ic('shield', 13, 'color:var(--good)') + '上下文只在本机进程间传递</span><button type="button" class="btn" data-act="askCopy">复制回答</button><button type="button" class="btn ai" data-act="askStudio">' + ic('spark', 13) + '交给生成工坊</button><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide');
  MODAL_KEY = 'ask';
}
function askStream(q, txt) {
  if (S.engine === 'stats') { clearInterval(ASKT); toast('仅统计模式下无法使用 Agent 问答'); return; }
  clearInterval(ASKT); ASK.q = q; ASK.text = txt;
  const a = $('#askA'); if (!a) return;
  a.innerHTML = '<div class="mono cap" style="font-size:11px;margin-bottom:6px">问：' + esc(q) + '</div><span id="askT"></span><span class="caret"></span>';
  let i = 0;
  ASKT = setInterval(() => { const t = $('#askT'); if (!t) { clearInterval(ASKT); return; } i += 3; t.textContent = txt.slice(0, i); if (i >= txt.length) { clearInterval(ASKT); const cr = $('#askA .caret'); if (cr) cr.remove(); } }, 22);
}
Object.assign(ACT, {
  ask: (el) => openAsk(el.dataset.ctx || 'overview'),
  askPick: (el) => { const i = +el.dataset.i; askStream(ASKQ[ASK.ctx][i], askAnswer(ASK.ctx, i)); },
  askSend: () => {
    const inp = $('#askIn'); const q = inp ? inp.value.trim() : ''; if (!q) { if (inp) inp.focus(); return; }
    const L = sel(); const st = stats(L); const p = personaNow();
    const hit = ASKQ[ASK.ctx].findIndex((x) => x.slice(0, 4) === q.slice(0, 4));
    askStream(q, hit >= 0 ? askAnswer(ASK.ctx, hit) : '（Demo 没有接入真实模型，下面是依据当前筛选整理的示例回答。）\n\n' + rangeLabel() + '共 ' + st.n + ' 个会话、' + f1(st.hours) + ' 小时，摩擦率 ' + f1(st.fric) + '%，人格 ' + (p.ok ? p.code + ' ' + p.zh : '样本不足') + '。\n\n在真实 App 里，你的问题会和上下文包一起交给本地 ' + agent(S.studio.agent).name + '，回答会引用具体会话，点引用可以跳到对应轨迹。');
    if (inp) inp.value = '';
  },
  askCopy: () => { if (!ASK || !ASK.text) { toast('还没有回答'); return; } copyText(ASK.text, '回答'); },
  askStudio: () => { const r = S.studio.run; if (r && !r.done && !r.stopped) { toast('生成工坊正在运行，先停止或等它完成再交给它', { act: '去看看', onAct: () => go('studio') }); return; } S.studio.goal = '依据这次问答继续：' + (ASK && ASK.q ? ASK.q : '把问答结论做成规则') + '\n\n' + (ASK && ASK.text ? ASK.text.slice(0, 160) : ''); S.studio.type = '规则'; S.studio.from = '问本地 Agent · ' + ASKN[ASK ? ASK.ctx : 'overview']; S.studio.run = null; clearInterval(ASKT); closeModal(); go('studio'); }
});
