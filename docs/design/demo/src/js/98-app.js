/* Live Advance adapter. The standalone design preview remains a separate mode. */
const LIVE = location.pathname === '/app';
const APP = {
  token: window.__TANDEM_TOKEN__ || new URLSearchParams(location.hash.slice(1)).get('token') || '',
  state: null, discovery: [], selected: new Set(), projects: [], page: null,
  key: '', loading: '', error: '', agent: '', project: '', days: 90, offset: 0,
  query: '', asOf: Date.now(), session: null, events: [], cursor: null, job: null, obStep: 0, limit: null
};

async function appRequest(path, body, method) {
  const response = await fetch(path, { method: method || (body ? 'POST' : 'GET'),
    headers: { Authorization: 'Bearer ' + APP.token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || data.error?.code ||
    (typeof data.detail === 'string' ? data.detail : '请求失败：' + response.status));
  return data;
}
function appButton(label, action, extra = '', primary = false) {
  return '<button type="button" class="btn ' + (primary ? 'p' : '') + '" data-act="' + action + '" ' + extra + '>' + esc(label) + '</button>';
}
function appNumber(value) { return value == null ? '未知' : typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : esc(String(value)); }
function appDate(value) { return value == null ? '时间未知' : new Date(value).toLocaleString('zh-CN'); }
function appTable(headers, rows) {
  if (!rows.length) return empty('当前范围没有可显示的记录。');
  return '<div class="card scroll-x"><table class="tbl"><thead><tr>' + headers.map(h => '<th>' + esc(h) + '</th>').join('') +
    '</tr></thead><tbody>' + rows.map(row => '<tr>' + row.map(cell => '<td>' + cell + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
}
function appCard(title, body) { return '<section class="card pad"><h2 class="serif" style="margin:0 0 12px">' + esc(title) + '</h2>' + body + '</section>'; }
function appJSON(value) { return '<details><summary>查看结构化依据</summary><pre class="app-json">' + esc(JSON.stringify(value, null, 2)) + '</pre></details>'; }
function appMetrics(values) { return '<div class="app-metrics">' + values.map(([title, value, note]) => '<div class="card pad"><div class="cap">' + esc(title) + '</div><div class="serif app-number">' + appNumber(value) + '</div><div class="cap">' + esc(note || '') + '</div></div>').join('') + '</div>'; }
function appScope() {
  const params = new URLSearchParams({ display_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" });
  if (APP.agent) params.set('agent', APP.agent);
  if (APP.project) params.set('project', APP.project);
  if (APP.days) params.set('from_ts', APP.asOf - APP.days * 86400000);
  return params;
}
function appFilters() {
  const sources = [...new Set(Object.values(APP.state?.sources || {}).map(s => s.agent))];
  const select = (label, action, options, value) => '<label class="row cap">' + label + '<select class="btn" data-chg="' + action + '">' + options.map(([v, name]) => '<option value="' + esc(v) + '"' + (String(value) === String(v) ? ' selected' : '') + '>' + esc(name) + '</option>').join('') + '</select></label>';
  return '<div class="frow app-filters">' + select('时间', 'appDays', [[7, '7 天'], [30, '30 天'], [90, '90 天'], [0, '全部']], APP.days) +
    select('Agent', 'appAgent', [['', '全部'], ...sources.map(a => [a, a])], APP.agent) +
    select('项目', 'appProject', [['', '全部'], ...APP.projects.map(p => [p.project_id, p.name])], APP.project) +
    '<span style="flex:1"></span>' + appButton('同步来源', 'appSync') + appButton('导出 JSON', 'appExport') + '</div>';
}
function appCoverage(data) {
  if (!data?.coverage) return '';
  const coverage = data.coverage.events || {};
  return (data.message ? '<div class="app-note">' + esc(data.message) + '</div>' : '') + '<div class="app-note">投影版本 ' + esc(data.versions?.projection_run_id ?? '—') + ' · 事件覆盖 ' + esc(coverage.status || 'unknown') +
    ' · 时间未知 ' + appNumber(coverage.time_unknown_rows) + ' · 截断 ' + appNumber(coverage.truncated_rows) +
    '。未知数值保留为未知；日志跨度不代表实际工作时长。</div>';
}
const APP_SECTIONS = { overview: 'overview', persona: 'preferences', tools: 'tools', projects: 'projects', sentiment: 'tasks', recs: 'recommendations', studio: 'instruction' };

async function appLoad(key) {
  APP.loading = key;
  try {
    let data;
    const params = appScope();
    if (S.route === 'sessions') {
      params.set('offset', APP.offset); params.set('q', APP.query);
      data = await appRequest('/v1/app/sessions?' + params);
    } else if (S.route === 'settings') {
      data = await appRequest('/v1/app/state'); APP.state = data;
    } else if (S.route === 'library') {
      data = await appRequest('/v1/app/inventory');
    } else {
      params.set('section', APP_SECTIONS[S.route] || 'overview');
      data = await appRequest('/v1/app/analysis?' + params);
    }
    if (APP.key === key) { APP.page = data; APP.error = ''; }
  } catch (error) { if (APP.key === key) APP.error = error.message; }
  if (APP.loading === key) APP.loading = '';
  if (APP.key === key) render();
}
function appPage() {
  const key = [S.route, APP.agent, APP.project, APP.days, APP.offset, APP.query].join('|');
  if (APP.key !== key) {
    APP.key = key; APP.page = null; APP.error = '';
    queueMicrotask(() => appLoad(key));
  }
  let body = APP.error ? appCard('需要处理', '<p>' + esc(APP.error) + '</p>' + appButton('重试', 'appRefresh') + ' ' + appButton('重算数据', 'appRebuild')) :
    !APP.page ? '<div class="card pad" role="status"><span class="spin"></span> 正在读取本地数据…</div>' : appPageBody(APP.page);
  const title = ROUTES.find(r => r[0] === S.route)?.[1] || '数据与设置';
  return tbar(title, '本地数据 · Advance', appButton('来源与存储', 'appSettings')) +
    '<div id="content" class="content app-content">' + (S.route === 'settings' ? '' : appFilters()) + appCoverage(APP.page) + body + '</div>';
}
function appPageBody(data) {
  if (S.route === 'overview') {
    const value = data.overview, counts = value.counts;
    return appMetrics([['主会话', counts.main_sessions], ['人类消息', counts.human_messages], ['标准事件', counts.events], ['已知请求用量', value.usage.total_tokens, 'tokens · ' + value.usage.status]]) +
      appCard('工具与协作记录', appTable(['工具', '调用', '失败', '状态未知'], (value.top_tools || []).map(t => [esc(t.name_raw || t.name || t.tool || '未知'), appNumber(t.call_count), appNumber(t.known_failure_count), appNumber(t.unknown_status_count)]))) +
      appCard('分析依据', '<p>数据来自你启用的本机来源。点击会话可回查脱敏事件和原始记录标识。</p>' + appButton('查看会话与轨迹', 'appSessions') + appJSON(value.subjective_outcomes));
  }
  if (S.route === 'sessions') {
    return '<div class="row"><input class="btn" aria-label="搜索会话标题" placeholder="搜索会话标题" data-chg="appSearch" value="' + esc(APP.query) + '"><span class="cap">共 ' + data.total + ' 个会话，当前 ' + (APP.offset + 1) + '–' + (APP.offset + data.items.length) + '</span></div>' +
      appTable(['会话', '来源', '项目', '时间', '类型 / 状态'], data.items.map(s => [appButton(s.display_title || s.title || s.agent + ' · ' + s.session_uid.slice(-8), 'appSession', 'data-id="' + esc(s.session_uid) + '"') + '<div class="cap">' + esc(({native_title:'原生标题',first_message:'取自首条消息',workflow_label:'来源任务标签',identity:'按来源与会话标识显示'})[s.display_title_source] || '') + '</div>', esc(s.agent), esc(s.project || '未知'), esc(appDate(s.started_at)), esc(s.kind + ' / ' + s.status)])) +
      '<div class="row">' + appButton('上一页', 'appPrevious', APP.offset ? '' : 'disabled') + appButton('下一页', 'appNext', data.next_offset == null ? 'disabled' : '') + '</div>';
  }
  if (S.route === 'tools') {
    return appMetrics([['调用', data.tools.totals?.call_count], ['已知失败', data.tools.totals?.known_failure_count], ['状态未知', data.tools.totals?.unknown_status_count]]) +
      appTable(['工具', '调用', '已知失败', '未知', '中位耗时 ms'], (data.tools.by_tool || []).map(t => [esc(t.name_raw || t.name || t.tool || '未知'), appNumber(t.call_count), appNumber(t.known_failure_count), appNumber(t.unknown_status_count), appNumber(t.median_duration_ms)]));
  }
  if (S.route === 'projects') return appTable(['项目', '主会话', '人类消息', '用量状态', '详情'], (data.projects || []).map(p => [esc(p.name || '未知'), appNumber(p.main_session_count), appNumber(p.human_message_count), esc(p.usage.status), appButton('筛选此项目', 'appSelectProject', 'data-id="' + esc(p.project_id || '') + '"')]));
  if (S.route === 'persona') return appCard('明确表达的协作偏好', '<p class="cap">当前展示有证据的偏好。四维人格分数尚未校准，不生成演示类型或人格结论。</p>' +
    appTable(['类型', '状态', '依据'], (data.preferences.records || []).map(p => [esc(p.preference_type || p.type || '偏好'), esc(p.status || p.confidence || '已观察'), appJSON(p)])));
  if (S.route === 'sentiment') return appCard('任务与语义记录', '<p class="cap">规则提取的任务与约束可以回查；情绪评分当前不可用。</p>' + appTable(['任务', '状态', '证据'], (data.tasks.records || []).map(t => [esc(t.task_id), esc(t.status || t.task_type || '已观察'), appJSON(t)])));
  if (S.route === 'recs') {
    const rec = data.recommendations;
    return appCard('有依据的优化建议', '<p class="cap">' + esc(rec.status) + ' · 建议收益尚未实测。安装与 Agent 执行需独立接入。</p>' +
      (rec.recommendations || []).map(r => appCard(r.title || r.name || r.resource_id, appJSON(r))).join('') + appJSON(rec.assessments));
  }
  if (S.route === 'library') {
    const items = data.inventory || data.items || [];
    return appCard('本机安装观察', '<p class="cap">会话导入不会自动读取配置。扫描仅保存白名单元数据，不保存命令和凭据；安装观察不等于运行时已生效。</p>' + appButton('扫描已启用的 Codex / Claude 配置', 'appInventory') +
      appTable(['名称', '类型', '来源证据', '启用'], items.map(i => [esc(i.name || i.id), esc(i.type), esc(i.evidence || i.agent || ''), i.enabled == null ? '未知' : i.enabled ? '是' : '否'])) + appJSON(data.coverage));
  }
  if (S.route === 'studio') return appCard('生成上下文包', '<p>导出当前筛选范围的脱敏特征与证据，供你选择的本地 Agent 使用。当前版本不自动发送会话或执行安装命令。</p>' + appButton('导出上下文 JSON', 'appExport', '', true) + appJSON(data.instruction.summary));
  return appSettingsBody(data);
}
function appSettingsBody(data) {
  const sources = Object.values(data.sources), storage = data.storage;
  return appCard('数据源', appButton('发现与添加来源', 'appOnboard') + appTable(['Agent', '目录', '状态', '操作'], sources.map(s => [esc(s.agent), '<span class="app-path">' + esc(s.root) + '</span>', esc(s.enabled ? '已启用' : '已停用'), appButton(s.enabled ? '停止后续采集' : '启用', 'appToggleSource', 'data-id="' + s.id + '"')])) + '<p class="cap">停用只停止后续采集，已归档记录仍保留。</p>') +
    appCard('索引', '<label class="row"><input type="checkbox" data-chg="appAuto"' + (data.settings.sync_mode === 'live' ? ' checked' : '') + '> 持续同步已启用来源（每 15 秒检查，按完整来源导入）</label>') +
    appCard('存储与维护', '<p class="app-path">' + esc(storage.home) + '</p>' + appMetrics([['会话', storage.tables.session], ['标准事件', storage.tables.event], ['原始记录', storage.tables.raw_record], ['压缩归档 MiB', storage.archive_bytes / 1048576]]) +
      '<div class="row">' + appButton('校验存储', 'appVerify') + appButton('重算数据', 'appRebuild') + appButton('备份数据', 'appBackup') + '</div>' + appJSON(storage)) +
    appCard('最近任务', Object.values(data.jobs).reverse().slice(0, 10).map(j => '<div class="app-job"><b>' + esc(j.kind + ' · ' + j.status) + '</b><span class="cap"> ' + esc(appDate(j.created_at)) + '</span>' + appJSON(j.results) + (['partial', 'failed', 'cancelled', 'interrupted'].includes(j.status) ? appButton('按原范围重试', 'appRetry', 'data-id="' + j.id + '"') : '') + '</div>').join('') || '<p>暂无任务。</p>');
}
async function appRefresh() {
  APP.state = await appRequest('/v1/app/state');
  try { APP.projects = (await appRequest('/v1/app/projects')).items; } catch (_) { APP.projects = []; }
  APP.key = ''; render();
}
async function appRunJob(kind, sourceIds, limit) {
  APP.job = await appRequest('/v1/app/jobs', { kind, source_ids: sourceIds || [], limit: limit || null });
  APP.obStep = 2; appDrawOB();
  await appPollJob();
}
async function appPollJob() {
  while (APP.job && ['queued', 'running'].includes(APP.job.status)) {
    await new Promise(resolve => setTimeout(resolve, 500));
    APP.job = await appRequest('/v1/app/jobs/' + APP.job.id);
    if (OVL === 'app-ob') appDrawOB();
  }
  await appRefresh();
  APP.obStep = 3;
  if (OVL === 'app-ob') appDrawOB();
  else toast('任务状态：' + APP.job.status);
}
async function appOpenSources() {
  APP.discovery = (await appRequest('/v1/app/discovery')).items;
  APP.selected = new Set(APP.discovery.filter(s => s.enabled).map(s => s.id));
  APP.obStep = 1; appDrawOB();
}
async function appAddSource() {
  const command = { agent: $('#appAgentRoot').value, root: $('#appRoot').value };
  // Keep a pending add from redrawing over the user's next source selection.
  const controls = [...document.querySelectorAll('#overlay button, #overlay input, #overlay select')];
  const disabled = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  try {
    const source = await appRequest('/v1/app/sources', command);
    const existing = APP.discovery.findIndex(item => item.id === source.id);
    if (existing >= 0) APP.discovery[existing] = { ...APP.discovery[existing], ...source };
    else APP.discovery.push({ ...source, files: null, status: '已选择' });
    APP.selected.add(source.id);
  } finally {
    controls.forEach((control, index) => { control.disabled = disabled[index]; });
  }
  appDrawOB();
}
function appDrawOB() {
  closeModal(); OVL = 'app-ob'; $('#overlay').hidden = false;
  let body = '';
  if (APP.obStep === 0) body = '<h2 class="serif">看见你和 Agent 怎么协作</h2><p>选择本机来源后才开始读取。原始记录保留在本机，分析使用脱敏投影。</p>' + appButton('选择数据源', 'appDiscover', '', true);
  if (APP.obStep === 1) body = '<h2 class="serif">选择要导入的来源</h2><p class="cap">文件数来自目录发现，不代表已读取或已解析的会话数。</p>' + APP.discovery.map(s => '<label class="srcrow"><input type="checkbox" data-chg="appSource" data-id="' + s.id + '"' + (APP.selected.has(s.id) ? ' checked' : '') + '><span><b>' + esc(s.agent) + '</b><span class="cap app-path">' + esc(s.root) + '</span></span><span>' + appNumber(s.files) + ' 文件</span><span class="cap">' + esc(s.status) + '</span></label>').join('') +
    '<div class="row"><select class="btn" id="appAgentRoot">' + ['codex', 'claude_code', 'dsh', 'pi', 'hermes', 'opencode', 'kimi'].map(a => '<option>' + a + '</option>').join('') + '</select><input class="btn" id="appRoot" aria-label="自定义来源目录" placeholder="输入 Agent 根目录"><button class="btn" data-act="appChooseFolder">选择目录</button>' + appButton('添加', 'appAddSource') + '</div>' +
    '<label class="row cap">首次导入<select class="btn" data-chg="appLimit"><option value="">全部来源文件</option><option value="2">每来源 2 个文件（样本验证）</option><option value="10">每来源 10 个文件（样本验证）</option></select></label>' +
    '<label class="row"><input type="checkbox" data-chg="appRecent"' + (APP.days === 90 ? ' checked' : '') + '>分析默认显示最近 90 天（归档仍保留选中数据）</label>' + appButton('开始导入', 'appImport', APP.selected.size ? '' : 'disabled', true);
  if (APP.obStep === 2) {
    const progress = APP.job?.progress || {};
    body = '<h2 class="serif">正在导入本地记录</h2><p role="status">' + esc(APP.job?.status || 'queued') + ' · ' + esc(progress.agent || '') + ' · ' + esc(progress.stage || '准备') + '</p>' +
      '<p class="mono">' + appNumber(progress.completed) + ' / ' + appNumber(progress.total) + ' 文件</p><p class="cap">大文件解析与事务发布需要时间。取消将在当前文件完成后生效。</p>' + appButton('请求取消', 'appCancel') + ' ' + appButton('在后台继续', 'appCloseOB');
  }
  if (APP.obStep === 3) {
    const storage = APP.state.storage;
    body = '<h2 class="serif">导入结果已保存</h2><p role="status">任务：' + esc(APP.job.status) + ' · ' + (APP.job.selection === 'sample' ? '有界样本，非全量回填' : '完整来源选择') + '</p>' +
      appMetrics([['会话', storage.tables.session], ['标准事件', storage.tables.event], ['原始记录', storage.tables.raw_record]]) +
      '<p class="cap">部分成功、未解析记录和采集失败保留在任务结果中，可在设置中重试或重算。</p>' + appJSON(APP.job.results) + appButton('查看会话与存储结果', 'appDone', '', true);
  }
  $('#overlay').innerHTML = '<div class="obox app-onboarding" role="dialog" aria-modal="true" aria-label="首次启动"><div class="row"><span class="eb">TANDEM · ' + (APP.obStep + 1) + ' / 4</span><span style="flex:1"></span>' + appButton('关闭', 'appCloseOB') + '</div>' + body + '</div>';
  const limitSelect = $('[data-chg=appLimit]');
  if (limitSelect) limitSelect.value = String(APP.limit || '');
}
function appEventCard(event) {
  const display = event.display || { title: event.kind, body: event.text, summary: '此事件只包含结构化信息。', fields: {} };
  const fields = Object.entries(display.fields || {});
  return '<article class="app-event"><div class="row"><b>' + esc(display.title) + '</b><span class="cap">#' + event.seq + ' · ' + esc(appDate(event.ts)) + '</span></div>' +
    '<p class="cap">' + esc(display.summary || '') + '</p>' +
    (display.body ? '<pre>' + esc(display.body) + '</pre>' : '') +
    (fields.length ? '<dl class="app-event-fields">' + fields.map(([key, value]) => '<dt>' + esc(key) + '</dt><dd>' + esc(String(value).slice(0, 240)) + '</dd>').join('') + '</dl>' : '') +
    (display.body_truncated ? '<span class="cap">正文预览已截断，完整原件保留在本机归档中。</span>' : '') +
    '<details><summary>证据与属性</summary><code>' + esc(event.record_uid) + '</code>' + appJSON({ kind: event.kind, event_uid: event.event_uid, record_uid: event.record_uid, event_path: event.event_path, attrs: event.attrs, ext: event.ext }) + '</details></article>';
}
function appEventList(events) {
  let output = '', contexts = [];
  const flush = () => {
    if (!contexts.length) return;
    const names = [...new Set(contexts.map(e => e.display?.title || '上下文更新'))];
    output += '<details class="app-context-group"><summary>系统上下文 · ' + contexts.length + ' 条 · ' + esc(names.slice(0, 3).join('、')) + '</summary>' + contexts.map(appEventCard).join('') + '</details>';
    contexts = [];
  };
  for (const event of events) {
    if (event.kind === 'context.inject') contexts.push(event);
    else { flush(); output += appEventCard(event); }
  }
  flush(); return output;
}
async function appShowSession(id, more = false) {
  if (!more) {
    APP.session = id; APP.events = []; APP.cursor = null;
    const row = APP.page?.items?.find(item => item.session_uid === id);
    APP.sessionTitle = row?.display_title || row?.title || '会话与轨迹';
  }
  const page = await appRequest('/v1/app/sessions/' + encodeURIComponent(id) + '/events?after_seq=' + (APP.cursor ?? -1));
  APP.events.push(...page.items); APP.cursor = page.next_after_seq;
  openModal(modalHead(APP.sessionTitle, '消息与工具记录按原生序号排列；连续系统上下文默认折叠，可展开查看摘要和证据。') + '<div class="mb app-events">' + appEventList(APP.events) + '</div><div class="mf">' + (APP.cursor == null ? '' : appButton('加载更多事件', 'appMoreEvents')) + appButton('关闭', 'closeModal') + '</div>');
}
function appDownload(data, name, type = 'application/json') {
  if (window.webkit?.messageHandlers?.tandem) {
    window.webkit.messageHandlers.tandem.postMessage({ action: 'save', name, text: data }); return;
  }
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function startLiveApp() {
  document.body.classList.add('tandem-live');
  document.title = 'Tandem'; history.replaceState(null, '', '/app');
  S.widgets = false; S.hud.show = false; S.sim = 'idle'; S.route = 'overview';
  for (const [route] of ROUTES) PAGES[route] = appPage;
  PAGES.settings = appPage;
  renderSide = () => {
    const n = APP.state?.storage.tables.session || 0;
    $('#side').innerHTML = '<div class="sb-scroll"><div class="sect"><span class="sh">洞察与行动</span></div><div class="nav">' + ROUTES.map(([id, name]) => '<button type="button" data-act="go" data-r="' + id + '"' + (S.route === id ? ' aria-current="page"' : '') + '>' + ic(id === 'sentiment' ? 'bot' : id, 15) + '<span class="lb">' + esc(name) + '</span></button>').join('') + '</div></div><div class="sb-foot"><div class="pv"><b>仅本地处理</b><p class="cap">已存储 ' + n + ' 个会话</p></div>' + appButton('数据与设置', 'appSettings') + '</div>';
  };
  renderMbar = () => { $('#mbar').innerHTML = '<b>Tandem</b><span class="cap">本地会话分析</span><span class="sp"></span>' + appButton('数据源', 'appOnboard') + appButton('外观', 'appTheme'); };
  renderHud = () => { $('#hud').hidden = true; };
  renderWidgets = () => { $('#widgets').innerHTML = ''; };
  openSettings = () => go('settings'); openOnboarding = () => appOpenSources();
  openPalette = () => { go('sessions'); setTimeout(() => $('[aria-label="搜索会话标题"]')?.focus(), 100); };
  openReport = () => ACT.appExport(); openShare = () => ACT.appExport(); openCSV = () => ACT.appExport();
  openReveal = () => go('persona');
  const guarded = fn => (...args) => Promise.resolve().then(() => fn(...args)).catch(error => toast(error.message));
  Object.assign(ACT, {
    winClose: () => { if (window.webkit?.messageHandlers?.tandem) window.webkit.messageHandlers.tandem.postMessage({ action: 'close' }); else toast('请使用浏览器窗口控制'); },
    winMin: () => { if (window.webkit?.messageHandlers?.tandem) window.webkit.messageHandlers.tandem.postMessage({ action: 'minimize' }); },
    winZoom: () => { if (window.webkit?.messageHandlers?.tandem) window.webkit.messageHandlers.tandem.postMessage({ action: 'fullscreen' }); },
    appTheme: () => { setTheme(S.theme === 'dark' ? 'light' : 'dark'); render(); },
    appSettings: () => go('settings'), appSessions: () => go('sessions'),
    appRefresh: guarded(appRefresh), appOnboard: guarded(appOpenSources), appDiscover: guarded(appOpenSources),
    appCloseOB: () => closeOverlay(), appSource: el => { el.checked ? APP.selected.add(el.dataset.id) : APP.selected.delete(el.dataset.id); appDrawOB(); },
    appLimit: el => { APP.limit = el.value ? +el.value : null; }, appRecent: el => { APP.days = el.checked ? 90 : 0; },
    appDays: el => { APP.days = +el.value; APP.offset = 0; render(); },
    appAgent: el => { APP.agent = el.value; APP.offset = 0; render(); }, appProject: el => { APP.project = el.value; APP.offset = 0; render(); },
    appSearch: el => { APP.query = el.value; APP.offset = 0; render(); },
    appNext: () => { APP.offset = APP.page.next_offset; render(); }, appPrevious: () => { APP.offset = Math.max(0, APP.offset - 50); render(); },
    appSelectProject: el => { APP.project = el.dataset.id; go('sessions'); },
    appSession: guarded(el => appShowSession(el.dataset.id)), appMoreEvents: guarded(() => appShowSession(APP.session, true)),
    appCancel: guarded(async () => { APP.job = await appRequest('/v1/app/jobs/' + APP.job.id + '/cancel', {}); appDrawOB(); }),
    appDone: guarded(async () => { await appRequest('/v1/app/settings', { onboarded: true, recent_days: APP.days }, 'PATCH'); closeOverlay(); go('sessions'); }),
    appImport: guarded(async () => {
      for (const source of APP.discovery.filter(s => APP.selected.has(s.id))) await appRequest('/v1/app/sources', { agent: source.agent, root: source.root });
      await appRequest('/v1/app/settings', { recent_days: APP.days }, 'PATCH');
      await appRunJob('import', [...APP.selected], APP.limit);
    }),
    appSync: guarded(() => appRunJob('import', Object.values(APP.state.sources).filter(s => s.enabled).map(s => s.id))),
    appRetry: guarded(async el => { APP.job = await appRequest('/v1/app/jobs/' + el.dataset.id + '/retry', {}); APP.obStep = 2; appDrawOB(); await appPollJob(); }),
    appVerify: guarded(() => appRunJob('verify')), appRebuild: guarded(() => appRunJob('rebuild')), appBackup: guarded(() => appRunJob('backup')),
    appInventory: guarded(() => appRunJob('inventory', Object.values(APP.state.sources).filter(s => s.enabled && ['codex', 'claude_code'].includes(s.agent)).map(s => s.id))),
    appAuto: guarded(async el => { await appRequest('/v1/app/settings', { sync_mode: el.checked ? 'live' : 'manual' }, 'PATCH'); await appRefresh(); }),
    appToggleSource: guarded(async el => { const s = APP.state.sources[el.dataset.id]; await appRequest('/v1/app/sources', { agent: s.agent, root: s.root, enabled: !s.enabled }); await appRefresh(); }),
    appChooseFolder: () => { if (window.webkit?.messageHandlers?.tandem) window.webkit.messageHandlers.tandem.postMessage({ action: 'chooseFolder' }); else toast('浏览器模式请填写来源目录；Mac App 支持系统目录选择器。'); },
    appAddSource: guarded(appAddSource),
    appExport: guarded(async () => { const data = await appRequest('/v1/app/export?' + appScope()); appDownload(JSON.stringify(data, null, 2), 'tandem-analysis.json'); })
  });
  try {
    await appRefresh(); APP.days = APP.state.settings.recent_days; APP.key = ''; render();
    const active = Object.values(APP.state.jobs).find(j => ['running', 'queued'].includes(j.status));
    if (active) { APP.job = active; APP.obStep = 2; appDrawOB(); appPollJob().catch(e => toast(e.message)); }
    else if (!APP.state.settings.onboarded) { APP.obStep = 0; appDrawOB(); }
  } catch (error) {
    $('#main').innerHTML = appCard('无法连接本地服务', '<p>' + esc(error.message) + '</p>');
  }
}
