/* ============ settings window (its own .panel: 720×560, centred near the top, draggable, becomes the key window) ============ */
const SET_TABS = [['general', '通用', 'settings'], ['sources', '数据源', 'db'], ['privacy', '隐私', 'shield'], ['analysis', '分析', 'chart'], ['notify', '通知', 'bell'], ['about', '关于', 'info']];
const SRC_ST = { cc: ['正常', 'okc', 'var(--good)', '2 分钟前'], cx: ['正常', 'okc', 'var(--good)', '2 分钟前'], gm: ['部分字段缺失', 'alert', 'var(--warn)', '5 分钟前'], ds: ['正常', 'okc', 'var(--good)', '12 分钟前'], cp: ['正常', 'okc', 'var(--good)', '1 小时前'] };
const RULE_RE = {
  '路径中的用户名': [/\/Users\/[A-Za-z0-9._-]+/g, '/Users/‹USER›'],
  '邮箱': [/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, '‹EMAIL›'],
  'API Key / Token': [/\b(?:sk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{8,}/g, '‹KEY›'],
  '内网 IP 与主机名': [/\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b|\b[\w-]+\.local\b/g, '‹HOST›'],
  '手机号': [/(^|\D)1[3-9]\d{9}(?!\d)/g, '$1‹PHONE›'],
  '自定义正则 2 条': [/内部代号-[A-Z0-9]+|工号\s*\d{5,}/g, '‹CODE›']
};
const ENGINE_TXT = { stats: '只做计数与时序统计。语义主题、情绪曲线、AI 解读与生成工坊都不可用。', agent: '语义分析交给你本机的 Agent（默认 Claude Code），用它自己的登录与额度；Orbit 只传结构化摘要。', ollama: '用本机模型（如 qwen3:8b）做语义分析，完全离线但较慢；生成工坊仍然需要本地 Agent。' };
const NEV = [['waiting', '有会话等你确认'], ['done', '会话完成（超过 10 分钟的）'], ['stuck', '同一命令连续失败 / 长时间无进展'], ['ctx', '上下文即将压缩'], ['weekly', '每周报告已生成']];
const NEV_COL = [['横幅', '右上角滑入，7 秒后自动收起'], ['悬浮组件', '胶囊切换为该事件的状态'], ['菜单栏角标', '图标角标变色 / 变形']];
// what leaves the machine when the analysis engine is a local Agent or model (settings › 分析 › AI 通道)
S.aiCh = S.aiCh || { sum: true, snip: true, raw: false };
const AI_CH = [['sum', '结构化摘要', '计数、时序、工具名、结果；不含任何原文'], ['snip', '脱敏后的片段', '关键时刻前后各 2 条消息，先过脱敏规则'], ['raw', '完整原文', '仅本机模型（Ollama）可选；本地 Agent 通道始终关闭']];
// the default time range survives a reload (BUG-51)
{ const r = store.get('range', null); if (typeof r === 'number') S.range = r; }
function redact(text) {
  let n = 0; let t = text;
  Object.keys(RULE_RE).forEach((k) => { if (!S.rules[k]) return; const rr = RULE_RE[k]; t = t.replace(rr[0], (...m) => { n++; const pre = rr[1].startsWith('$1') ? m[1] : ''; return pre + '\u0001' + rr[1].replace('$1', '') + '\u0002'; }); });
  return { n, html: esc(t).replace(/\u0001/g, '<mark class="rd">').replace(/\u0002/g, '</mark>') };
}
// settings › 数据源 / 隐私 rows; live mode (97-live-studio-settings.js) swaps these for the gateway's sources and rules
let srcRows = () => AG.map((a) => ({ name: a.name, ver: a.ver, path: a.path, n: fmt(a.all), st: SRC_ST[a.id] || ['—', 'minus', 'var(--ink-3)', '—'], on: !S.srcOff.has(a.id), t: a.t, c: a.c, attrs: ' data-a="' + a.id + '"' }));
let srcMissing = () => (S.extraSrc.some((x) => /cursor/i.test(x.name)) ? [] : [{ name: 'Cursor', v: 'Cursor', hint: '未检测到 · 可以手动指定数据库位置' }]);
let srcIndexed = () => fmt(2416 + S.extraSrc.length * 37);
let ruleRows = () => Object.keys(S.rules).map((k) => ({ k, label: k, ph: RULE_RE[k] ? RULE_RE[k][1].replace('$1', '') : '', on: S.rules[k], locked: false }));
// A sheet left open by the previous tab (工具名映射表, 协作人格如何计算 …) or by the main window would cover the settings window and
// swallow every pointer event, so opening settings or switching tabs closes it first (palette excluded: it has no host).
function setDropSheet() { if (!$('#modal').hidden && MODAL_HOST) closeModal(); tipOff(); }
function openSettings(tab) { if (tab) S.setTab = tab; S.pop = false; closeDD(); setDropSheet(); S.keyWin = 'set'; $('#set').hidden = false; render(); setPlace(); keyWinApply(); }
function closeSettings() { if (MODAL_HOST === $('#set')) closeModal(); $('#set').hidden = true; S.keyWin = 'main'; keyWinApply(); }
/* centred horizontally, 60px under the menu bar (or wherever it was dragged to), always fully inside the stage */
function setPlace() {
  const el = $('#set'); if (el.hidden) return;
  const st = stageSize(); const w = el.offsetWidth, h = el.offsetHeight;
  let x, y;
  if (S.setPos) { x = clamp(S.setPos.x, 0, Math.max(0, st.w - w)); y = clamp(S.setPos.y, MB_H, Math.max(MB_H, st.h - h)); }
  else { x = Math.round((st.w - w) / 2); y = Math.max(MB_H, Math.min(MB_H + 60, st.h - h - 16)); }
  el.style.left = x + 'px'; el.style.top = y + 'px';
}
function renderSet() {
  const el = $('#set'); if (el.hidden) return;
  const t = S.setTab; const curTab = SET_TABS.find((x) => x[0] === t) || SET_TABS[0];
  const row = (l, ctrl, hint) => '<span class="l">' + l + '</span><div class="col" style="gap:4px;align-items:flex-start">' + ctrl + (hint ? '<span class="cap" style="font-size:11px">' + hint + '</span>' : '') + '</div>';
  const seg = (act, cur, opts, label) => '<div class="seg" role="radiogroup" aria-label="' + (label || '') + '">' + opts.map((o) => '<button type="button" role="radio" aria-checked="' + (cur === o[0]) + '" data-act="' + act + '" data-v="' + o[0] + '" class="' + (cur === o[0] ? 'on' : '') + '">' + o[1] + '</button>').join('') + '</div>';
  const card = (title, sub, inner, right) => '<div class="card"><div class="row set-ch"><div style="flex:1;min-width:200px"><div class="ct">' + title + '</div>' + (sub ? '<div class="cap set-cs">' + sub + '</div>' : '') + '</div>' + (right || '') + '</div><div class="set-cb">' + inner + '</div></div>';
  let body = '';
  if (t === 'general') {
    body = card('外观与组件', '', '<div class="form">' + row('外观', seg('setTheme', S.theme, [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']], '外观')) + row('悬浮组件', swBtn(S.hud.show, 'setHud', '', '悬浮组件'), kb('⌥⌘P') + ' 显示或隐藏 · 拖动吸附到 6 个位置，按住 ⌥ 自由放置') + row('桌面小组件', swBtn(S.widgets, 'setWidgets', '', '桌面小组件'), '<span data-tip="屏幕宽度不小于 1500 时主窗口默认让出左侧一列；更窄时小组件在主窗口之下，移动或缩小主窗口可以看到">显示在桌面层，主窗口之下 · 宽屏时主窗口让出左侧一列</span>') + row('小组件尺寸', seg('wgSize', S.wgSize || 'm', WG_SIZES, '小组件尺寸'), '小：人格、今日 · 中：+ 本周、建议 · 大：+ 运行中、7 天趋势') + row('小组件只显示数字', swBtn(S.numOnly, 'setNumOnly', '', '小组件只显示数字'), '隐藏项目名与会话标题，适合录屏与演示') + row('登录时启动', swBtn(S.login, 'setLogin', '', '登录时启动'), '只在菜单栏常驻，不打开主窗口') + '</div>') +
      card('统计', '', '<div class="form">' + row('默认时间范围', seg('setRange', String(S.range), [['7', '7 天'], ['30', '30 天'], ['90', '90 天'], ['0', '全部']], '默认时间范围')) + row('键盘快捷键', '<button type="button" class="btn sm" data-act="openKeys">查看全部</button>') + '</div>');
  } else if (t === 'sources') {
    body = card('已检测到的 Agent', '自动扫描默认目录 · 只读会话日志，不读凭据文件', srcRows().map((r) => '<div class="srcrow" style="opacity:' + (r.on ? 1 : 0.55) + '"><span style="width:30px;height:30px;border-radius:8px;background:' + r.t + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + r.c) + '</span><div style="min-width:0"><div class="row" style="gap:6px;flex-wrap:wrap"><b style="font-size:13px">' + r.name + '</b><span class="mono cap" style="font-size:11px">' + r.ver + '</span><span class="row" style="gap:3px;font-size:11px;color:' + r.st[2] + '">' + ic(r.st[1], 12) + r.st[0] + '</span></div><div class="mono cap" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + r.path + ' · ' + r.n + ' 个会话</div></div><span class="mono cap when" style="font-size:11px">' + r.st[3] + '</span>' + swBtn(r.on, 'setSrc', r.attrs, '启用 ' + r.name) + '</div>').join('') +
      S.extraSrc.map((x, i) => '<div class="srcrow"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('db', 15) + '</span><div style="min-width:0"><div class="row" style="gap:6px"><b style="font-size:13px">' + esc(x.name) + '</b><span class="bdg">' + ({ jsonl: 'JSONL', sqlite: 'SQLite', md: 'Markdown' })[x.fmt] + '</span><span class="row" style="gap:3px;font-size:11px;color:var(--good)">' + ic('okc', 12) + '正常</span></div><div class="mono cap" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(x.path) + ' · ' + x.n + ' 个会话</div></div><span class="mono cap when" style="font-size:11px">刚刚</span><button type="button" class="btn sm gh" data-act="setRmSrc" data-i="' + i + '">移除</button></div>').join('') +
      srcMissing().map((m) => '<div class="srcrow" style="opacity:.75"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('minus', 15) + '</span><div><b style="font-size:13px">' + esc(m.name) + '</b><div class="cap" style="font-size:11px">' + m.hint + '</div></div><span class="when"></span><button type="button" class="btn sm" data-act="setAddSrc" data-v="' + esc(m.v) + '">指定…</button></div>').join('') +
      (S.addSrc ? '<div class="col" style="gap:10px;margin-top:10px;padding:12px;border-radius:10px;background:var(--sunken)"><div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:8px 12px"><label class="l" for="srcName">名称</label><input id="srcName" value="' + esc(S.addSrc === 'Cursor' ? 'Cursor' : '导出的聊天记录') + '" style="' + FIELD + '"><label class="l" for="srcPath">位置</label><input id="srcPath" value="' + esc(S.addSrc === 'Cursor' ? '~/Library/Application Support/Cursor/User/workspaceStorage' : '~/Documents/chat-export') + '" style="' + FIELD + ';font-family:var(--font-mono)"><span class="l">格式</span>' + seg('setParser', S.addSrcFmt, [['jsonl', 'JSONL'], ['sqlite', 'SQLite'], ['md', 'Markdown 导出']], '格式') + '</div><div class="row" style="justify-content:flex-end"><button type="button" class="btn sm" data-act="setAddCancel">取消</button><button type="button" class="btn sm p" data-act="setAddDo">添加并索引</button></div></div>' : ''),
      '<button type="button" class="btn sm" data-act="setMap">工具名映射表</button>') +
      '<div class="row" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn" data-act="setAddSrc">' + ic('plus', 14) + '添加自定义来源…</button><span class="cap" style="font-size:11px">支持 JSONL、SQLite、Markdown 导出</span></div>' +
      card('索引方式', '', '<div class="form">' + row('更新', seg('setIdx', S.index, [['live', '实时（FSEvents）'], ['hour', '每小时'], ['manual', '仅手动']], '索引方式'), '低电量时自动降为每小时') + row('暂停采集', swBtn(S.paused, 'setPause', '', '暂停采集'), '暂停后菜单栏图标不显示状态角标，也不产生任何事件') + row('立即重新索引', '<button type="button" class="btn sm" data-act="setReindex">' + ic('sync', 13) + '重新索引</button>', '已索引 ' + srcIndexed() + ' 个会话') + '</div>');
  } else if (t === 'privacy') {
    const rd = redact(S.ruleSample);
    body = card('脱敏规则', '入库前执行；命中的内容替换为占位符，原文不会写入 Orbit 的数据库', ruleRows().map((r) => '<div class="row" style="padding:7px 0;border-bottom:1px solid var(--hair)"><span style="flex:1;font-size:13px">' + r.label + '</span><span class="mono cap" style="font-size:11px">' + esc(r.ph) + '</span>' + swBtn(r.on, 'setRule', ' data-k="' + esc(r.k) + '"' + (r.locked ? ' disabled' : ''), String(r.label).replace(/<[^>]*>/g, '').trim()) + '</div>').join('') +
      (S.ruleTest ? '<div class="col" style="gap:8px;margin-top:12px"><label class="eb" for="rdIn">测试文本</label><textarea id="rdIn" data-in="setTestIn" rows="4" style="width:100%;border-radius:8px;border:1px solid var(--line);background:var(--surface);padding:8px 10px;font:12px/1.6 var(--font-mono);color:var(--ink-1);resize:vertical">' + esc(S.ruleSample) + '</textarea><div class="row" style="justify-content:space-between"><span class="eb">入库后</span><span class="mono cap" id="rdN" style="font-size:11px">命中 ' + rd.n + ' 处</span></div><div id="rdOut" style="padding:8px 10px;border-radius:8px;background:var(--sunken);font:12px/1.7 var(--font-mono);white-space:pre-wrap;word-break:break-all">' + rd.html + '</div></div>' : ''),
      '<button type="button" class="btn sm" data-act="setTest">' + (S.ruleTest ? '收起测试' : '测试规则…') + '</button>') +
      card('匿名贡献', S.anon ? '已开启：只上传人格代码与已装资源名，用于「相似用户」统计' : '关闭：不上传任何内容。开启后只上传人格代码与已装资源名', '<div class="row" style="gap:10px">' + swBtn(S.anon, 'setAnon', '', '匿名贡献') + '<span class="cap" style="font-size:11px">会话内容、项目名、路径永远不会上传</span></div>') +
      card('数据存储', '', '<div class="col" style="gap:8px"><div class="row" style="flex-wrap:wrap"><span class="mono" style="font-size:12px;flex:1;min-width:200px">~/Library/Application Support/Orbit</span><b class="mono" style="font-size:12px">812 MB</b></div><div class="row" style="flex-wrap:wrap;gap:8px"><button type="button" class="btn sm" data-act="setFinder">在 Finder 中显示</button><button type="button" class="btn sm" data-act="setExport">导出全部（JSON）</button><button type="button" class="btn sm dg" data-act="setClear">清除全部数据…</button></div></div>');
  } else if (t === 'analysis') {
    const chOff = S.engine === 'stats';
    body = card('分析引擎', '语义分析与生成依赖此项', '<div class="col" style="gap:8px">' + seg('setEngine', S.engine, [['stats', '仅统计'], ['agent', '本地 Agent'], ['ollama', '本机模型（Ollama）']], '分析引擎') + '<span style="font-size:13px;line-height:1.5;color:var(--ink-2)">' + ENGINE_TXT[S.engine] + '</span>' + (S.engine === 'agent' ? '<div class="row" style="gap:8px"><span class="cap">执行者</span><button type="button" class="chip sm" data-act="studioAgent">' + agent(S.studio.agent).name + ic('chev', 12) + '</button></div>' : '') + '</div>') +
      card('AI 通道', chOff ? '「仅统计」不会把任何内容交给 AI' : '交给' + (S.engine === 'agent' ? '本地 Agent' : '本机模型') + '的内容，按层级勾选；传出前都先过脱敏规则', '<div class="aich' + (chOff ? ' off' : '') + '">' + AI_CH.map((c) => { const dis = chOff || (c[0] === 'raw' && S.engine !== 'ollama'); const on = !chOff && !!S.aiCh[c[0]] && !(c[0] === 'raw' && S.engine !== 'ollama'); return '<div class="row aich-r"><div style="flex:1;min-width:0"><div style="font-size:13px">' + c[1] + '</div><div class="cap" style="font-size:11px">' + c[2] + '</div></div>' + swBtn(on, 'setAiCh', ' data-k="' + c[0] + '"' + (dis ? ' disabled' : ''), c[1]) + '</div>'; }).join('') + '</div><div class="row" style="gap:8px;margin-top:8px;flex-wrap:wrap"><button type="button" class="btn sm" data-act="setTab" data-v="privacy">查看脱敏规则</button><span class="cap" style="font-size:11px">当前启用 ' + Object.keys(S.rules).filter((k) => S.rules[k]).length + ' / ' + Object.keys(S.rules).length + ' 条</span></div>') +
      card('协作人格', '', '<div class="col" style="gap:6px;font-size:13px;color:var(--ink-2)"><span>· 至少 30 个会话才判断类型；项目级至少 8 个</span><span>· 任一维度落在 45–55 之间时显示「?」，不强行归类</span><span>· 信号与权重是初版设想，需要真实数据校准</span><div><button type="button" class="btn sm" data-act="method">查看计算方法与 16 型</button></div></div>') +
      card('不计入分析的会话', S.excluded.size ? S.excluded.size + ' 个会话被你手动排除' : '没有被排除的会话 · 在会话详情的「⋯」菜单里排除', '<button type="button" class="btn sm" data-act="setRestoreEx"' + (S.excluded.size ? '' : ' disabled') + '>全部恢复</button>') +
      card('每周报告', '', '<div class="row" style="gap:10px">' + swBtn(S.weekly, 'setWeekly', '', '每周报告') + '<span class="cap" style="font-size:11px">每周一 09:00 生成并通知 · 也可在「文件 › 导出报告」随时生成</span></div>');
  } else if (t === 'notify') {
    // each column is its own channel: a row with only 悬浮组件 ticked changes the HUD and nothing else (BUG-40)
    const nOn = (c) => NEV.filter((e) => S.notif[e[0]][c]).length;
    body = card('投递矩阵', '默认克制：只在需要你动作或有明确结果时打扰', '<div class="scroll-x"><table class="tbl nmx"><thead><tr><th>事件</th>' + NEV_COL.map((c, i) => '<th><span class="col" style="gap:1px;align-items:center"><span>' + c[0] + '</span><span class="cap mono" style="font-size:10px;font-weight:400">' + nOn(i) + ' / ' + NEV.length + '</span></span></th>').join('') + '</tr></thead><tbody>' + NEV.map((e) => '<tr><td>' + e[1] + '</td>' + [0, 1, 2].map((c) => '<td><input type="checkbox" data-chg="setNotif" data-e="' + e[0] + '" data-c="' + c + '"' + (S.notif[e[0]][c] ? ' checked' : '') + ' aria-label="' + e[1] + ' · ' + NEV_COL[c][0] + '"></td>').join('') + '</tr>').join('') + '</tbody></table></div><div class="nmx-legend">' + NEV_COL.map((c) => '<span><b>' + c[0] + '</b> ' + c[1] + '</span>').join('') + '</div><div class="cap" style="font-size:11px;margin-top:6px">每列独立生效 · 用菜单栏「演示」菜单模拟事件即可预览</div>', '<div class="row" style="gap:6px"><button type="button" class="btn sm" data-act="setNotifPreset" data-v="quiet">只留必须的</button><button type="button" class="btn sm" data-act="setNotifPreset" data-v="all">全部打开</button></div>') +
      card('暂停提醒', '', '<div class="col" style="gap:8px"><div class="row" style="gap:10px">' + swBtn(S.hud.mute, 'setMute', '', '暂停所有提醒') + '<span style="font-size:13px">暂停横幅与悬浮组件提醒</span></div><span class="cap" style="font-size:11px">菜单栏角标仍然更新，方便你回头查看</span><div class="row" style="gap:10px;padding-top:6px;border-top:1px solid var(--hair)">' + swBtn(!S.hud.tipOff, 'setTipOn', '', '悬浮组件里的上下文提示') + '<span style="flex:1;min-width:0;font-size:13px">悬浮组件里的上下文提示<span class="cap" style="display:block;font-size:11px">上下文超过 60% 时建议「先总结进度」' + (S.hud.tipOff ? '；已被「不再提示此类」关闭' : '') + '</span></span></div><div><button type="button" class="btn sm" data-act="setTestNotif">发送测试通知</button></div></div>');
  } else {
    body = '<div class="col" style="align-items:center;text-align:center;gap:8px;padding:24px 0"><span class="appicon" style="width:64px;height:64px">' + appIcon(64) + '</span><div style="font-size:22px;font-weight:700">Orbit</div><div class="mono cap">1.0（演示版）· 2026-10-01</div><div style="font-size:13px;color:var(--ink-2)">本地的跨 Agent 会话分析</div><div class="row" style="gap:8px;flex-wrap:wrap;justify-content:center;margin-top:10px"><button type="button" class="btn sm" data-act="openAbout">' + (LV.live ? '关于 Orbit' : '关于这个 Demo') + '</button><button type="button" class="btn sm" data-act="openKeys">键盘快捷键</button><button type="button" class="btn sm" data-act="obReplay">重新播放首次启动</button><button type="button" class="btn sm" data-act="setUpdate">检查更新</button></div></div>';
  }
  el.innerHTML = '<div class="ptop"><div class="lights" role="group" aria-label="窗口控制"><button type="button" class="r" data-act="setClose" aria-label="关闭设置"></button><button type="button" class="y" aria-label="最小化" disabled></button><button type="button" class="g" aria-label="缩放" disabled></button></div><span class="ptitle">' + curTab[1] + '</span></div>' +
    '<div class="tabs" role="tablist" aria-label="设置分区">' + SET_TABS.map((x) => '<button type="button" role="tab" aria-selected="' + (x[0] === t) + '" data-act="setTab" data-v="' + x[0] + '" class="' + (x[0] === t ? 'on' : '') + '">' + ic(x[2], 18) + x[1] + '</button>').join('') + '</div><div class="body">' + body + '</div>';
}
function doReset() {
  store.set('theme', 'system'); store.set('hud', null); store.set('win', null); store.set('side', null); store.set('range', null); store.set('wgSize', null);
  try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* sandboxed */ }
  try { location.reload(); } catch (e) { toast('请手动刷新页面'); }
}
function resetDemo() {
  openModal(modalHead('重置演示数据？', '恢复到初始状态：筛选、已安装的建议、设置、窗口与悬浮组件位置都会还原') + '<div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="doReset">重置</button></div>');
}
Object.assign(ACT, {
  openSettings: (el) => openSettings(el && el.dataset ? el.dataset.tab : undefined),
  setTab: (el) => { S.setTab = el.dataset.v; setDropSheet(); renderSet(); },
  setClose: () => closeSettings(),
  setTheme: (el) => { setTheme(el.dataset.v); render(); },
  setHud: () => toggleHud(),
  setWidgets: () => { S.widgets = !S.widgets; render(); },
  setNumOnly: () => { S.numOnly = !S.numOnly; render(); },
  setLogin: () => { S.login = !S.login; renderSet(); },
  setRange: (el) => { S.range = +el.dataset.v; store.set('range', S.range); render(); },
  setSrc: (el) => { const id = el.dataset.a; if (S.srcOff.has(id)) S.srcOff.delete(id); else S.srcOff.add(id); render(); toast(S.srcOff.has(id) ? agent(id).name + ' 已停用：数据在所有页面隐藏，但不删除' : agent(id).name + ' 已重新启用'); },
  setAddSrc: (el) => { S.addSrc = el.dataset.v || '自定义'; S.addSrcFmt = S.addSrc === 'Cursor' ? 'sqlite' : 'jsonl'; renderSet(); const n = $('#srcPath'); if (n) n.focus(); },
  setAddCancel: () => { S.addSrc = false; renderSet(); },
  setParser: (el) => { S.addSrcFmt = el.dataset.v; const nm = $('#srcName'), pa = $('#srcPath'); const keep = [nm ? nm.value : '', pa ? pa.value : '']; renderSet(); if ($('#srcName')) $('#srcName').value = keep[0]; if ($('#srcPath')) $('#srcPath').value = keep[1]; },
  setAddDo: () => { const nm = $('#srcName'), pa = $('#srcPath'); const name = (nm && nm.value.trim()) || '自定义来源', path = pa ? pa.value.trim() : ''; if (!path) { toast('先填写来源位置'); if (pa) pa.focus(); return; } S.extraSrc.push({ name, path, fmt: S.addSrcFmt, n: 37 }); S.addSrc = false; render(); toast('已添加「' + name + '」，正在索引 37 个会话（示例）'); },
  setRmSrc: (el) => { const x = S.extraSrc.splice(+el.dataset.i, 1)[0]; render(); toast('已移除「' + (x ? x.name : '') + '」，已索引的数据 30 天后清理'); },
  setMap: () => openModal(modalHead('工具名映射表', '把各 Agent 的工具名归一，才能跨 Agent 统计（示例映射，需按实际日志核实）') + '<div class="mb scroll-x"><table class="tbl"><thead><tr><th>统一名</th>' + AG.map((a) => '<th>' + a.short + '</th>').join('') + '</tr></thead><tbody>' + [['Read', 'Read', 'read_file', 'read_file', 'fs.read', 'view'], ['Edit', 'Edit', 'apply_patch', 'replace', 'fs.edit', 'edit'], ['Bash', 'Bash', 'shell', 'run_shell_command', 'exec', 'bash'], ['Grep', 'Grep', 'shell: rg', 'search_file_content', 'grep', 'grep'], ['WebFetch', 'WebFetch', 'web.fetch', 'web_fetch', 'http.get', 'fetch'], ['Task', 'Task', '—', '—', 'spawn', '—']].map((r) => '<tr>' + r.map((c, i) => '<td class="' + (i ? 'mono' : '') + '" style="' + (i ? 'font-size:12px' : 'font-weight:600') + '">' + esc(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide'),
  setIdx: (el) => { S.index = el.dataset.v; render(); },
  setReindex: () => reindex(),
  setPause: () => { S.paused = !S.paused; render(); toast(S.paused ? '已暂停采集' : '已恢复采集'); },
  setRule: (el) => { const k = el.dataset.k; S.rules[k] = !S.rules[k]; render(); },
  setTest: () => { S.ruleTest = !S.ruleTest; renderSet(); const a = $('#rdIn'); if (a) a.focus(); },
  setTestIn: (el) => { S.ruleSample = el.value; const r = redact(S.ruleSample); const o = $('#rdOut'); if (o) o.innerHTML = r.html; const c = $('#rdN'); if (c) c.textContent = '命中 ' + r.n + ' 处'; },
  setAnon: () => { S.anon = !S.anon; render(); toast(S.anon ? '已开启匿名贡献：只上传人格代码与已装资源名' : '已关闭匿名贡献'); },
  setFinder: () => toast('已在 Finder 中显示（演示）：~/Library/Application Support/Orbit'),
  setExport: () => {
    const L = sel({ range: 0, noExtra: true }); const p = persona(L);
    CUR.exportJSON = JSON.stringify({ app: 'Orbit', version: '1.0-demo', exported_at: '2026-10-01T15:30:00+08:00', sources: AG.map((a) => ({ agent: a.name, path: a.path, enabled: !S.srcOff.has(a.id), sessions: a.all })).concat(S.extraSrc.map((x) => ({ agent: x.name, path: x.path, enabled: true, sessions: x.n }))), persona: p.ok ? { code: p.code, name: p.zh, scores: { D: Math.round(p.v.D), I: Math.round(p.v.I), M: Math.round(p.v.M), V: Math.round(p.v.V) } } : null, installed: Array.from(S.installed.keys()), redaction_rules: Object.keys(S.rules).filter((k) => S.rules[k]), sessions: L.slice(-3).map((s) => ({ id: s.id, agent: agent(s.a).name, project: PJI[s.p].name, date: md(s.d), minutes: Math.round(s.dur), messages: s.msgs, tool_calls: s.tools, outcome: s.out })), sessions_total: L.length }, null, 2);
    openModal(modalHead('导出全部（JSON）', '这里只显示结构与最近 3 个会话；App 会导出完整文件') + '<div class="mb"><pre class="code" style="padding:12px;white-space:pre-wrap;max-height:50vh">' + esc(CUR.exportJSON) + '</pre></div><div class="mf"><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="copyExport">复制 JSON</button></div>', 'wide');
  },
  copyExport: () => copyText(CUR.exportJSON || '', 'JSON'),
  setClear: () => openModal(modalHead('清除全部数据？', '会删除索引、分析结果与备份，不会动各 Agent 自己的会话日志') + '<div class="mb col" style="gap:8px"><label for="clrIn" style="font-size:13px">输入 <b class="mono">清除</b> 以确认：</label><input id="clrIn" data-in="setClearIn" autocomplete="off" style="' + FIELD + ';height:28px;font-size:13px"></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" id="clrBtn" data-act="setClearDo" disabled style="background:var(--crit);border-color:var(--crit);color:#fff">清除全部数据</button></div>'),
  setClearIn: (el) => { const b = $('#clrBtn'); if (b) b.disabled = el.value.trim() !== '清除'; },
  setClearDo: () => { closeModal(); toast('Demo 不会删除任何文件；正在恢复初始示例数据…'); setTimeout(doReset, 1300); },
  setEngine: (el) => { S.engine = el.dataset.v; render(); toast(S.engine === 'stats' ? '已切换为「仅统计」：语义相关功能暂停' : '已切换分析引擎'); },
  setRestoreEx: () => { const n = S.excluded.size; S.excluded.clear(); render(); toast('已恢复 ' + n + ' 个会话，所有页面已重算'); },
  setWeekly: () => { S.weekly = !S.weekly; renderSet(); },
  setNotif: (el) => { S.notif[el.dataset.e][+el.dataset.c] = el.checked ? 1 : 0; simSettle(); render(); },
  setNotifPreset: (el) => { const quiet = el.dataset.v === 'quiet'; NEV.forEach((e) => { S.notif[e[0]] = quiet ? ({ waiting: [1, 1, 1], done: [0, 1, 0], stuck: [0, 1, 1], ctx: [0, 1, 0], weekly: [0, 0, 0] })[e[0]] : [1, 1, 1]; }); simSettle(); render(); toast(quiet ? '只保留需要你动作的横幅' : '已打开全部提醒渠道'); },
  setTipOn: () => { S.hud.tipOff = !S.hud.tipOff; render(); toast(S.hud.tipOff ? '已关闭悬浮组件里的上下文提示' : '已恢复悬浮组件里的上下文提示'); },
  setAiCh: (el) => { const k = el.dataset.k; S.aiCh[k] = !S.aiCh[k]; renderSet(); },
  setMute: () => setHudMuted(!S.hud.mute),
  setTestNotif: () => notify({ t: '测试通知', b: '看到这条，说明通知工作正常。', force: true }),
  setUpdate: () => toast('已是最新版本（演示）'),
  obReplay: () => openOnboarding(0),
  doReset: () => doReset()
});
