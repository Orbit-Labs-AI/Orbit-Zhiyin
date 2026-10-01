/* ============ settings window ============ */
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
const ENGINE_TXT = { stats: '只做计数与时序统计。语义主题、情绪曲线、AI 解读与生成工坊都不可用。', agent: '语义分析交给你本机的 Agent（默认 Claude Code），用它自己的登录与额度；Tandem 只传结构化摘要。', ollama: '用本机模型（如 qwen3:8b）做语义分析，完全离线但较慢；生成工坊仍然需要本地 Agent。' };
const NEV = [['waiting', '有会话等你确认'], ['done', '会话完成（超过 10 分钟的）'], ['stuck', '同一命令连续失败 / 长时间无进展'], ['ctx', '上下文即将压缩'], ['weekly', '每周报告已生成']];
function redact(text) {
  let n = 0; let t = text;
  Object.keys(RULE_RE).forEach((k) => { if (!S.rules[k]) return; const rr = RULE_RE[k]; t = t.replace(rr[0], (...m) => { n++; const pre = rr[1].startsWith('$1') ? m[1] : ''; return pre + '\u0001' + rr[1].replace('$1', '') + '\u0002'; }); });
  return { n, html: esc(t).replace(/\u0001/g, '<mark class="rd">').replace(/\u0002/g, '</mark>') };
}
function openSettings(tab) { if (tab) S.setTab = tab; S.pop = false; closeDD(); $('#set').hidden = false; render(); }
function renderSet() {
  const el = $('#set'); if (el.hidden) return;
  const t = S.setTab; const curTab = SET_TABS.find((x) => x[0] === t) || SET_TABS[0];
  const row = (l, ctrl, hint) => '<span class="l">' + l + '</span><div class="col" style="gap:4px;align-items:flex-start">' + ctrl + (hint ? '<span class="cap" style="font-size:11.5px">' + hint + '</span>' : '') + '</div>';
  const seg = (act, cur, opts, label) => '<div class="seg" role="radiogroup" aria-label="' + (label || '') + '">' + opts.map((o) => '<button type="button" role="radio" aria-checked="' + (cur === o[0]) + '" data-act="' + act + '" data-v="' + o[0] + '" class="' + (cur === o[0] ? 'on' : '') + '">' + o[1] + '</button>').join('') + '</div>';
  const card = (title, sub, inner, right) => '<div class="card"><div class="row" style="padding:12px 14px 0;flex-wrap:wrap;align-items:flex-start"><div style="flex:1;min-width:200px"><div class="ct">' + title + '</div>' + (sub ? '<div class="cap" style="font-size:11.5px">' + sub + '</div>' : '') + '</div>' + (right || '') + '</div><div style="padding:10px 14px 14px">' + inner + '</div></div>';
  let body = '';
  if (t === 'general') {
    body = card('外观与组件', '', '<div class="form">' + row('外观', seg('setTheme', S.theme, [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']], '外观')) + row('悬浮组件', swBtn(S.hud.show, 'setHud', '', '悬浮组件'), kb('⌥⌘P') + ' 显示或隐藏；拖动可吸附到 6 个位置，按住 ⌥ 松手可自由放置') + row('桌面小组件', swBtn(S.widgets, 'setWidgets', '', '桌面小组件'), '宽屏时显示在主窗口左侧，窄屏时浮在最上层') + row('小组件只显示数字', swBtn(S.numOnly, 'setNumOnly', '', '小组件只显示数字'), '隐藏项目名与会话标题，适合录屏与演示') + row('登录时启动', swBtn(S.login, 'setLogin', '', '登录时启动'), '只在菜单栏常驻，不打开主窗口') + '</div>') +
      card('统计', '', '<div class="form">' + row('默认时间范围', seg('setRange', String(S.range), [['7', '7 天'], ['30', '30 天'], ['90', '90 天'], ['0', '全部']], '默认时间范围')) + row('键盘快捷键', '<button type="button" class="btn sm" data-act="openKeys">查看全部</button>') + '</div>');
  } else if (t === 'sources') {
    const hasCursor = S.extraSrc.some((x) => /cursor/i.test(x.name));
    body = card('已检测到的 Agent', '自动扫描默认目录 · 只读会话日志，不读凭据文件', AG.map((a) => { const st = SRC_ST[a.id]; const on = !S.srcOff.has(a.id); return '<div class="srcrow" style="opacity:' + (on ? 1 : 0.55) + '"><span style="width:30px;height:30px;border-radius:8px;background:' + a.t + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + a.c) + '</span><div style="min-width:0"><div class="row" style="gap:6px;flex-wrap:wrap"><b style="font-size:13px">' + a.name + '</b><span class="mono cap" style="font-size:10.5px">' + a.ver + '</span><span class="row" style="gap:3px;font-size:11px;color:' + st[2] + '">' + ic(st[1], 12) + st[0] + '</span></div><div class="mono cap" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + a.path + ' · ' + fmt(a.all) + ' 个会话</div></div><span class="mono cap when" style="font-size:11px">' + st[3] + '</span>' + swBtn(on, 'setSrc', ' data-a="' + a.id + '"', '启用 ' + a.name) + '</div>'; }).join('') +
      S.extraSrc.map((x, i) => '<div class="srcrow"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('db', 15) + '</span><div style="min-width:0"><div class="row" style="gap:6px"><b style="font-size:13px">' + esc(x.name) + '</b><span class="bdg">' + ({ jsonl: 'JSONL', sqlite: 'SQLite', md: 'Markdown' })[x.fmt] + '</span><span class="row" style="gap:3px;font-size:11px;color:var(--good)">' + ic('okc', 12) + '正常</span></div><div class="mono cap" style="font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(x.path) + ' · ' + x.n + ' 个会话</div></div><span class="mono cap when" style="font-size:11px">刚刚</span><button type="button" class="btn sm gh" data-act="setRmSrc" data-i="' + i + '">移除</button></div>').join('') +
      (hasCursor ? '' : '<div class="srcrow" style="opacity:.75"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('minus', 15) + '</span><div><b style="font-size:13px">Cursor</b><div class="cap" style="font-size:11px">未检测到 · 可以手动指定数据库位置</div></div><span class="when"></span><button type="button" class="btn sm" data-act="setAddSrc" data-v="Cursor">指定…</button></div>') +
      (S.addSrc ? '<div class="col" style="gap:10px;margin-top:10px;padding:12px;border-radius:10px;background:var(--sunken)"><div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:8px 12px"><label class="l" for="srcName">名称</label><input id="srcName" value="' + esc(S.addSrc === 'Cursor' ? 'Cursor' : '导出的聊天记录') + '" style="' + FIELD + '"><label class="l" for="srcPath">位置</label><input id="srcPath" value="' + esc(S.addSrc === 'Cursor' ? '~/Library/Application Support/Cursor/User/workspaceStorage' : '~/Documents/chat-export') + '" style="' + FIELD + ';font-family:var(--mono)"><span class="l">格式</span>' + seg('setParser', S.addSrcFmt, [['jsonl', 'JSONL'], ['sqlite', 'SQLite'], ['md', 'Markdown 导出']], '格式') + '</div><div class="row" style="justify-content:flex-end"><button type="button" class="btn sm" data-act="setAddCancel">取消</button><button type="button" class="btn sm p" data-act="setAddDo">添加并索引</button></div></div>' : ''),
      '<button type="button" class="btn sm" data-act="setMap">工具名映射表</button>') +
      '<div class="row" style="gap:8px;flex-wrap:wrap"><button type="button" class="btn" data-act="setAddSrc">' + ic('plus', 14) + '添加自定义来源…</button><span class="cap" style="font-size:11.5px">支持 JSONL、SQLite、Markdown 导出</span></div>' +
      card('索引方式', '', '<div class="form">' + row('更新', seg('setIdx', S.index, [['live', '实时（FSEvents）'], ['hour', '每小时'], ['manual', '仅手动']], '索引方式'), '低电量时自动降为每小时') + row('暂停采集', swBtn(S.paused, 'setPause', '', '暂停采集'), '暂停后菜单栏图标显示为空心，不产生任何事件') + row('立即重新索引', '<button type="button" class="btn sm" data-act="setReindex">' + ic('sync', 13) + '重新索引</button>', '已索引 ' + fmt(2416 + S.extraSrc.length * 37) + ' 个会话') + '</div>');
  } else if (t === 'privacy') {
    const rd = redact(S.ruleSample);
    body = card('脱敏规则', '入库前执行；命中的内容替换为占位符，原文不会写入 Tandem 的数据库', Object.keys(S.rules).map((k) => '<div class="row" style="padding:7px 0;border-bottom:1px solid var(--hair)"><span style="flex:1;font-size:12.5px">' + k + '</span><span class="mono cap" style="font-size:11px">' + esc(RULE_RE[k] ? RULE_RE[k][1].replace('$1', '') : '') + '</span>' + swBtn(S.rules[k], 'setRule', ' data-k="' + esc(k) + '"', k) + '</div>').join('') +
      (S.ruleTest ? '<div class="col" style="gap:8px;margin-top:12px"><label class="eb" for="rdIn">测试文本</label><textarea id="rdIn" data-in="setTestIn" rows="4" style="width:100%;border-radius:8px;border:1px solid var(--line);background:var(--surface);padding:8px 10px;font:12px/1.6 var(--mono);color:var(--ink-1);resize:vertical">' + esc(S.ruleSample) + '</textarea><div class="row" style="justify-content:space-between"><span class="eb">入库后</span><span class="mono cap" id="rdN" style="font-size:11px">命中 ' + rd.n + ' 处</span></div><div id="rdOut" style="padding:8px 10px;border-radius:8px;background:var(--sunken);font:12px/1.7 var(--mono);white-space:pre-wrap;word-break:break-all">' + rd.html + '</div></div>' : ''),
      '<button type="button" class="btn sm" data-act="setTest">' + (S.ruleTest ? '收起测试' : '测试规则…') + '</button>') +
      card('匿名贡献', S.anon ? '已开启：只上传人格代码与已装资源名，用于「相似用户」统计' : '关闭：不上传任何内容。开启后只上传人格代码与已装资源名', '<div class="row" style="gap:10px">' + swBtn(S.anon, 'setAnon', '', '匿名贡献') + '<span class="cap" style="font-size:11.5px">会话内容、项目名、路径永远不会上传</span></div>') +
      card('数据存储', '', '<div class="col" style="gap:8px"><div class="row" style="flex-wrap:wrap"><span class="mono" style="font-size:12px;flex:1;min-width:200px">~/Library/Application Support/Tandem</span><b class="mono" style="font-size:12px">812 MB</b></div><div class="row" style="flex-wrap:wrap;gap:8px"><button type="button" class="btn sm" data-act="setFinder">在 Finder 中显示</button><button type="button" class="btn sm" data-act="setExport">导出全部（JSON）</button><button type="button" class="btn sm dg" data-act="setClear">清除全部数据…</button></div></div>');
  } else if (t === 'analysis') {
    body = card('分析引擎', '语义分析与生成依赖此项', '<div class="col" style="gap:8px">' + seg('setEngine', S.engine, [['stats', '仅统计'], ['agent', '本地 Agent'], ['ollama', '本机模型（Ollama）']], '分析引擎') + '<span style="font-size:12.5px;line-height:1.55;color:var(--ink-2)">' + ENGINE_TXT[S.engine] + '</span>' + (S.engine === 'agent' ? '<div class="row" style="gap:8px"><span class="cap">执行者</span><button type="button" class="chip sm" data-act="studioAgent">' + agent(S.studio.agent).name + ic('chev', 12) + '</button></div>' : '') + '</div>') +
      card('协作人格', '', '<div class="col" style="gap:6px;font-size:12.5px;color:var(--ink-2)"><span>· 至少 30 个会话才判断类型；项目级至少 8 个</span><span>· 任一维度落在 45–55 之间时显示「?」，不强行归类</span><span>· 信号与权重是初版设想，需要真实数据校准</span><div><button type="button" class="btn sm" data-act="method">查看计算方法与 16 型</button></div></div>') +
      card('不计入分析的会话', S.excluded.size ? S.excluded.size + ' 个会话被你手动排除' : '没有被排除的会话。在会话详情的「⋯」菜单里可以排除', '<button type="button" class="btn sm" data-act="setRestoreEx"' + (S.excluded.size ? '' : ' disabled') + '>全部恢复</button>') +
      card('每周报告', '', '<div class="row" style="gap:10px">' + swBtn(S.weekly, 'setWeekly', '', '每周报告') + '<span class="cap" style="font-size:11.5px">每周一 09:00 生成，通过通知提醒；可以在「文件 › 导出报告」随时生成</span></div>');
  } else if (t === 'notify') {
    body = card('投递矩阵', '克制是默认值：只有需要你动作，或带来明确结果时才打扰', '<div class="scroll-x"><table class="tbl"><thead><tr><th>事件</th><th style="text-align:center">横幅</th><th style="text-align:center">悬浮组件</th><th style="text-align:center">菜单栏角标</th></tr></thead><tbody>' + NEV.map((e) => '<tr><td>' + e[1] + '</td>' + [0, 1, 2].map((c) => '<td style="text-align:center"><input type="checkbox" data-chg="setNotif" data-e="' + e[0] + '" data-c="' + c + '"' + (S.notif[e[0]][c] ? ' checked' : '') + ' aria-label="' + e[1] + ' · ' + ['横幅', '悬浮组件', '菜单栏角标'][c] + '" style="accent-color:var(--ink-1);width:15px;height:15px"></td>').join('') + '</tr>').join('') + '</tbody></table></div><div class="cap" style="font-size:11.5px;margin-top:8px">用菜单栏的「演示」菜单模拟事件，可以看到这里的设置立即生效。</div>') +
      card('暂停提醒', '', '<div class="col" style="gap:8px"><div class="row" style="gap:10px">' + swBtn(S.hud.mute, 'setMute', '', '暂停所有提醒') + '<span style="font-size:12.5px">暂停横幅与悬浮组件提醒</span></div><span class="cap" style="font-size:11.5px">菜单栏角标仍然更新，方便你回头查看</span><div><button type="button" class="btn sm" data-act="setTestNotif">发送测试通知</button></div></div>');
  } else {
    body = '<div class="col" style="align-items:center;text-align:center;gap:8px;padding:24px 0"><span class="appicon" style="width:64px;height:64px;border-radius:16px"><svg width="38" height="28" viewBox="0 0 24 18" aria-hidden="true" fill="none" stroke="#f5f4f0" stroke-width="1.8"><circle cx="8.5" cy="9" r="6"/><circle cx="15.5" cy="9" r="6"/></svg></span><div class="serif" style="font-size:26px;font-weight:600">Tandem</div><div class="mono cap">1.0（演示版）· 2026-10-01</div><div style="font-size:13px;color:var(--ink-2)">本地的跨 Agent 会话分析</div><div class="row" style="gap:8px;flex-wrap:wrap;justify-content:center;margin-top:10px"><button type="button" class="btn sm" data-act="openAbout">关于这个 Demo</button><button type="button" class="btn sm" data-act="openKeys">键盘快捷键</button><button type="button" class="btn sm" data-act="obReplay">重新播放首次启动</button><button type="button" class="btn sm" data-act="setUpdate">检查更新</button></div></div>';
  }
  el.innerHTML = '<div class="lights" style="height:40px;padding:0 14px"><button type="button" class="r" data-act="setClose" aria-label="关闭设置"></button><button type="button" class="y" data-act="setClose" aria-label="最小化设置"></button><button type="button" class="g" aria-label="缩放" disabled style="opacity:.4"></button><span style="flex:1;text-align:center;font-weight:600;font-size:13px;margin-right:52px">' + curTab[1] + '</span></div><div class="tabs" role="tablist" aria-label="设置分区">' + SET_TABS.map((x) => '<button type="button" role="tab" aria-selected="' + (x[0] === t) + '" data-act="setTab" data-v="' + x[0] + '" class="' + (x[0] === t ? 'on' : '') + '">' + ic(x[2], 18) + x[1] + '</button>').join('') + '</div><div class="body">' + body + '</div>';
}
function doReset() {
  store.set('theme', 'system'); store.set('hud', null);
  try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* sandboxed */ }
  try { location.reload(); } catch (e) { toast('请手动刷新页面'); }
}
function resetDemo() {
  openModal(modalHead('重置演示数据？', '恢复到初始状态：筛选、已安装的建议、设置与悬浮组件位置都会还原') + '<div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="doReset">重置</button></div>');
}
Object.assign(ACT, {
  openSettings: (el) => openSettings(el && el.dataset ? el.dataset.tab : undefined),
  setTab: (el) => { S.setTab = el.dataset.v; renderSet(); },
  setClose: () => { $('#set').hidden = true; },
  setTheme: (el) => { setTheme(el.dataset.v); render(); },
  setHud: () => toggleHud(),
  setWidgets: () => { S.widgets = !S.widgets; render(); },
  setNumOnly: () => { S.numOnly = !S.numOnly; render(); },
  setLogin: () => { S.login = !S.login; renderSet(); },
  setRange: (el) => { S.range = +el.dataset.v; render(); },
  setSrc: (el) => { const id = el.dataset.a; if (S.srcOff.has(id)) S.srcOff.delete(id); else S.srcOff.add(id); render(); toast(S.srcOff.has(id) ? agent(id).name + ' 已停用：数据在所有页面隐藏，但不删除' : agent(id).name + ' 已重新启用'); },
  setAddSrc: (el) => { S.addSrc = el.dataset.v || '自定义'; S.addSrcFmt = S.addSrc === 'Cursor' ? 'sqlite' : 'jsonl'; renderSet(); const n = $('#srcPath'); if (n) n.focus(); },
  setAddCancel: () => { S.addSrc = false; renderSet(); },
  setParser: (el) => { S.addSrcFmt = el.dataset.v; const nm = $('#srcName'), pa = $('#srcPath'); const keep = [nm ? nm.value : '', pa ? pa.value : '']; renderSet(); if ($('#srcName')) $('#srcName').value = keep[0]; if ($('#srcPath')) $('#srcPath').value = keep[1]; },
  setAddDo: () => { const nm = $('#srcName'), pa = $('#srcPath'); const name = (nm && nm.value.trim()) || '自定义来源', path = pa ? pa.value.trim() : ''; if (!path) { toast('先填写来源位置'); if (pa) pa.focus(); return; } S.extraSrc.push({ name, path, fmt: S.addSrcFmt, n: 37 }); S.addSrc = false; render(); toast('已添加「' + name + '」，正在索引 37 个会话（示例）'); },
  setRmSrc: (el) => { const x = S.extraSrc.splice(+el.dataset.i, 1)[0]; render(); toast('已移除「' + (x ? x.name : '') + '」，已索引的数据 30 天后清理'); },
  setMap: () => openModal(modalHead('工具名映射表', '把各 Agent 的工具名归一，才能跨 Agent 统计（示例映射，需按实际日志核实）') + '<div class="mb scroll-x"><table class="tbl"><thead><tr><th>统一名</th>' + AG.map((a) => '<th>' + a.short + '</th>').join('') + '</tr></thead><tbody>' + [['Read', 'Read', 'read_file', 'read_file', 'fs.read', 'view'], ['Edit', 'Edit', 'apply_patch', 'replace', 'fs.edit', 'edit'], ['Bash', 'Bash', 'shell', 'run_shell_command', 'exec', 'bash'], ['Grep', 'Grep', 'shell: rg', 'search_file_content', 'grep', 'grep'], ['WebFetch', 'WebFetch', 'web.fetch', 'web_fetch', 'http.get', 'fetch'], ['Task', 'Task', '—', '—', 'spawn', '—']].map((r) => '<tr>' + r.map((c, i) => '<td class="' + (i ? 'mono' : '') + '" style="' + (i ? 'font-size:11.5px' : 'font-weight:600') + '">' + esc(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide'),
  setIdx: (el) => { S.index = el.dataset.v; render(); },
  setReindex: () => reindex(),
  setPause: () => { S.paused = !S.paused; render(); toast(S.paused ? '已暂停采集' : '已恢复采集'); },
  setRule: (el) => { const k = el.dataset.k; S.rules[k] = !S.rules[k]; render(); },
  setTest: () => { S.ruleTest = !S.ruleTest; renderSet(); const a = $('#rdIn'); if (a) a.focus(); },
  setTestIn: (el) => { S.ruleSample = el.value; const r = redact(S.ruleSample); const o = $('#rdOut'); if (o) o.innerHTML = r.html; const c = $('#rdN'); if (c) c.textContent = '命中 ' + r.n + ' 处'; },
  setAnon: () => { S.anon = !S.anon; render(); toast(S.anon ? '已开启匿名贡献：只上传人格代码与已装资源名' : '已关闭匿名贡献'); },
  setFinder: () => toast('已在 Finder 中显示（演示）：~/Library/Application Support/Tandem'),
  setExport: () => {
    const L = sel({ range: 0, noExtra: true }); const p = persona(L);
    CUR.exportJSON = JSON.stringify({ app: 'Tandem', version: '1.0-demo', exported_at: '2026-10-01T15:30:00+08:00', sources: AG.map((a) => ({ agent: a.name, path: a.path, enabled: !S.srcOff.has(a.id), sessions: a.all })).concat(S.extraSrc.map((x) => ({ agent: x.name, path: x.path, enabled: true, sessions: x.n }))), persona: p.ok ? { code: p.code, name: p.zh, scores: { D: Math.round(p.v.D), I: Math.round(p.v.I), M: Math.round(p.v.M), V: Math.round(p.v.V) } } : null, installed: Array.from(S.installed.keys()), redaction_rules: Object.keys(S.rules).filter((k) => S.rules[k]), sessions: L.slice(-3).map((s) => ({ id: s.id, agent: agent(s.a).name, project: PJI[s.p].name, date: md(s.d), minutes: Math.round(s.dur), messages: s.msgs, tool_calls: s.tools, outcome: s.out })), sessions_total: L.length }, null, 2);
    openModal(modalHead('导出全部（JSON）', '这里只显示结构与最近 3 个会话；App 会导出完整文件') + '<div class="mb"><pre class="code" style="padding:12px;white-space:pre-wrap;max-height:50vh">' + esc(CUR.exportJSON) + '</pre></div><div class="mf"><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="copyExport">复制 JSON</button></div>', 'wide');
  },
  copyExport: () => copyText(CUR.exportJSON || '', 'JSON'),
  setClear: () => openModal(modalHead('清除全部数据？', '会删除索引、分析结果与备份，不会动各 Agent 自己的会话日志') + '<div class="mb col" style="gap:8px"><label for="clrIn" style="font-size:13px">输入 <b class="mono">清除</b> 以确认：</label><input id="clrIn" data-in="setClearIn" autocomplete="off" style="' + FIELD + ';height:34px;font-size:13px"></div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" id="clrBtn" data-act="setClearDo" disabled style="background:var(--crit);border-color:var(--crit);color:#fff">清除全部数据</button></div>'),
  setClearIn: (el) => { const b = $('#clrBtn'); if (b) b.disabled = el.value.trim() !== '清除'; },
  setClearDo: () => { closeModal(); toast('Demo 不会删除任何文件；正在恢复初始示例数据…'); setTimeout(doReset, 1300); },
  setEngine: (el) => { S.engine = el.dataset.v; render(); toast(S.engine === 'stats' ? '已切换为「仅统计」：语义相关功能暂停' : '已切换分析引擎'); },
  setRestoreEx: () => { const n = S.excluded.size; S.excluded.clear(); render(); toast('已恢复 ' + n + ' 个会话，所有页面已重算'); },
  setWeekly: () => { S.weekly = !S.weekly; renderSet(); },
  setNotif: (el) => { S.notif[el.dataset.e][+el.dataset.c] = el.checked ? 1 : 0; },
  setMute: () => { S.hud.mute = !S.hud.mute; render(); },
  setTestNotif: () => notify({ t: '测试通知', b: '看到这条，说明通知工作正常。', force: true }),
  setUpdate: () => toast('已是最新版本（演示）'),
  obReplay: () => openOnboarding(0),
  doReset: () => doReset()
});

