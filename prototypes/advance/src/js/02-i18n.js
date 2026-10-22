/* ============ i18n: 中文 / English ============ */
// The UI text lives in the render code as Chinese literals. Instead of rewriting every
// template string, a translation pass runs after each render (and on dynamically added
// nodes): an exact trimmed text node, or a user-facing attribute, that matches a key in
// the dictionary is replaced. Dictionary coverage grows per round; anything missing
// stays in the source language rather than showing a broken half-translation.
const I18N = {
  lang: store.get('lang', 'en') === 'en' ? 'en' : 'zh',
  dict: {
    // shell / sidebar
    '概览': 'Overview', '协作人格': 'Collaboration style', '协作画像': 'Collaboration profile',
    '会话轨迹': 'Session traces', '优化建议': 'Suggestions', '资源库': 'Library',
    '情绪语义': 'Sentiment', '项目习惯': 'Project habits', '工具调用': 'Tool calls', '生成工坊': 'Studio',
    '洞察': 'Insights', '行动': 'Actions', '更多': 'More', '置顶项目': 'Pinned projects', 'Agents': 'Agents',
    '实时': 'Live', '采集已暂停': 'Paused', '查看完整画像': 'Open full profile',
    // toolbar / filters / menus
    '分享报告': 'Share report', '问本地 Agent': 'Ask local agent', '重新索引': 'Reindex',
    '键盘快捷键': 'Keyboard shortcuts', '对比上一周期': 'Compare last period', '添加筛选': 'Add filter',
    '项目': 'Project', '全部': 'All', '7 天': '7 days', '30 天': '30 days', '90 天': '90 days',
    '文件': 'File', '编辑': 'Edit', '显示': 'View', '窗口': 'Window', '帮助': 'Help',
    '设置…': 'Settings…', '关于 Orbit': 'About Orbit', '隐藏 Orbit': 'Hide Orbit', '退出 Orbit': 'Quit Orbit',
    '高级模式': 'Advanced mode', '界面': 'Interface',
    '关闭时使用精简界面；打开后显示全部分析与工具页面': 'Use the compact pages by default; turn on to show every analysis and tool page',
    '跟随系统': 'System', '浅色': 'Light', '深色': 'Dark', '悬浮组件': 'Floating HUD',
    '桌面小组件': 'Desktop widgets', '语言': 'Language', '中文': '中文', '外观': 'Appearance',
    // overview
    'AI 解读': 'AI reading', '重新生成': 'Regenerate', '卡在哪': 'Where you get stuck',
    '立刻可做': 'Do now', '证据': 'Evidence', '会话': 'Sessions', '协作时长': 'Collaboration time',
    '摩擦率': 'Friction rate', '完成率': 'Completion rate', '你发出的消息': 'Messages sent',
    '自主比': 'Autonomy ratio', 'Agent 使用趋势': 'Agent usage', '活跃节律': 'Activity rhythm',
    '消息数': 'Messages', '纠偏率': 'Correction rate', '本周建议': 'This week', '查看 3 条建议': 'View 3 suggestions',
    '实验性': 'Experimental', '置信度': 'Confidence', '这页回答': 'This page answers',
    '点击图例隐藏 · 拖选时段重算指标卡': 'Click a legend to hide it · drag on the chart to recompute the cards',
    // editions / common actions
    'Lite': 'Lite', 'Advance': 'Advance', '设置': 'Settings', '关闭': 'Close', '完成': 'Done',
    '取消': 'Cancel', '保存': 'Save', '复制': 'Copy', '删除': 'Delete', '安装': 'Install',
    '预览并安装': 'Preview and install', '分享': 'Share', '导出分享卡': 'Export share card',
    '算法说明': 'Method notes', '让 Agent 写一份自述': 'Ask the agent to write about me',
    // settings tabs and sections
    '通用': 'General', '数据源': 'Sources', '隐私': 'Privacy', '分析': 'Analysis', '通知': 'Notifications',
    '关于': 'About', '数据存储': 'Data storage', '在 Finder 中显示': 'Show in Finder',
    '导出全部（JSON）': 'Export all (JSON)', '清除全部数据…': 'Clear all data…',
    // states
    '加载中…': 'Loading…', '没有数据': 'No data', '暂无数据': 'No data yet',
  },
};

// 动态文案的规则：数字 + 中文单位/连接词
I18N.rules = [
  [/sessionsRequires/g, 'sessions require'],
  [/today每小时开始 sessions数/g, 'sessions started per hour today'], [/未detection到/g, 'Not detected'],
  [/可稍后/g, 'can later '], [/手动指定/g, 'set manually'],
  [/ 时compaction/g, ' at compaction'], [/每小时开始/g, 'started per hour '], [/检测/g, 'detection'],
  [/跳转/g, 'to jump'], [/高峰/g, 'Peak '], [/ 时 ·/g, ' ·'],
  [/周四/g, 'Thu'], [/周五/g, 'Fri'], [/周六/g, 'Sat'], [/周日/g, 'Sun'], [/周一/g, 'Mon'], [/周二/g, 'Tue'], [/周三/g, 'Wed'],
  [/weeks四/g, 'Thu'], [/weeks五/g, 'Fri'], [/weeks六/g, 'Sat'], [/weeks日/g, 'Sun'], [/weeks一/g, 'Mon'], [/weeks二/g, 'Tue'], [/weeks三/g, 'Wed'],
  [/点击/g, 'click '], [/拖动/g, 'drag '], [/可移动/g, 'to move'], [/已用/g, 'used '],
  [/每分钟的events数/g, 'events per minute'], [/每天 sessions数/g, 'sessions per day'], [/每小时开始 sessions数/g, 'sessions started per hour'],
  [/另有 /g, 'plus '], [/today已done/g, ' done today'], [/并审核日报/g, 'and review the daily report'],
  [/省时/g, 'time saved '], [/^今$/g, 'Today'], [/在table/g, 'in the table'], [/或scatter plot/g, 'or scatter plot'],
  [/点另一/g, 'click another'], [/作为 B/g, 'as B'], [/日均/g, 'daily average '], [/进行中/g, 'in progress'],
  [/没有运行中的会话/g, 'No session running'], [/还有 /g, ''], [/ 条建议/g, ' more suggestions'],
  [/近 7 天每天的会话数，按 Agent 堆叠/g, 'Sessions per day over the last 7 days, stacked by agent'],
  [/识别到的工作流/g, 'Detected workflows'], [/出现在 /g, 'in '],
  [/固定成一个 Skill 后，每次可少说约 4 条指令。/g, 'Pinning this as a Skill saves about 4 instructions each time.'],
  [/封装为 Skill/g, 'Package as Skill'], [/为此项目起草规则/g, 'Draft rules for this project'],
  [/摩擦率 /g, 'Friction rate '], [/ vs 上周/g, ' vs last week'], [/本周最值得做/g, "This week's top action"],
  [/预览/g, 'Preview'], [/协作人格/g, 'Collaboration style'], [/上周无会话/g, 'No sessions last week'],
  [/1 个运行中/g, '1 running'], [/其他/g, 'Other'], [/会话 · /g, 'sessions · '],
  [/occurred在/g, 'occurred in'], [/支持度/g, 'support'], [/confidence高/g, 'high confidence'],
  [/confidence中/g, 'medium confidence'], [/confidence低/g, 'low confidence'],
  [/上周/g, 'last week'], [/本周/g, 'this week'], [/今日/g, 'today'],
  [/不会被索引/g, 'are not indexed'], [/Cancelchecked/g, 'Cancel checked'],
  [/的sessions/g, ' sessions'], [/的sources/g, ' sources'], [/的calls/g, ' calls'], [/的filter/g, ' filter'], [/的tools/g, ' tools'],
  [/在profile page/g, ' in profile page'], [/在Settings/g, ' in Settings'], [/Settings中/g, 'Settings, '],
  [/占Collaboration/g, ' accounts for collaboration'], [/与"/g, ' and "'], [/与code/g, ' and code'], [/与backups/g, ' and backups'],
  [/把relevant/g, 'put relevant '], [/把opening/g, 'put the opening '], [/把各/g, 'put each '],
  [/只stats/g, 'only stats '], [/只Readingsessionslogs/g, 'only Reading session logs'], [/会Delete/g, 'will delete '],
  [/各 Agent/g, 'each Agent '], [/需by/g, 'need '], [/或you denied/g, 'or you denied '], [/跨 Agent/g, 'across Agent '],
  [/到allhistory/g, 'to all history'], [/。/g, '. '], [/can把/g, 'can put the '], [/as a template。/g, 'as a template. '],
  [/占比/g, 'share'], [/名归一/g, ' names normalized '], [/allof/g, 'all of '], [/只/g, 'only '],
  [/会/g, 'will '], [/索引/g, 'index'], [/结果/g, 'result'], [/备份/g, 'backups'], [/不会动/g, 'will not touch '],
  [/自己/g, 'own '], [/勾选/g, 'checked'], [/来源/g, 'sources'], [/不会被索引/g, 'are not indexed'],
  [/基于 /g, 'Based on '], [/之后/g, 'then '], [/在/g, 'in '], [/画像页/g, 'profile page'],
  [/这次协作很顺/g, 'This collaboration went smoothly'], [/目标清楚/g, 'clear goals'], [/failed少/g, 'few failures'],
  [/开场方式/g, 'opening'], [/记成模板/g, 'as a template'], [/首次/g, 'First run '], [/扩展/g, 'extend '],
  [/移动焦点/g, 'move focus'], [/选择/g, 'select'], [/占/g, 'accounts for '], [/推断/g, 'inferred'],
  [/次数/g, 'count'], [/各/g, 'each '], [/归一/g, 'normalized '], [/才能/g, 'so '], [/跨/g, 'across '],
  [/映射/g, 'mapping '], [/需/g, 'need '], [/实际/g, 'real '], [/日志/g, 'logs '], [/核实/g, 'verify '],
  [/周期/g, 'period'], [/生成/g, 'generated'], [/page单独/g, 'page separately '], [/countlogarithmic/g, 'count · logarithmic'],
  [/要求验证/g, 'require verification'], [/先看/g, 'start with '], [/再看/g, 'then '],
  [/顶部/g, 'the top '], [/三张指标卡/g, 'the three KPI cards'], [/摩擦率/g, 'friction rate'],
  [/开始后/g, 'started '], [/第 /g, ''], [/事件/g, 'events'], [/把/g, 'put '], [/相关about/g, 'relevant '],
  [/hover看/g, 'hover for '], [/统计/g, 'stats'], [/最后一次/g, 'last '], [/结束/g, 'end'],
  [/已发生/g, 'occurred '], [/处于/g, 'in '], [/找到了这些/g, 'Found these '], [/复现/g, 'Reproduce '],
  [/总览/g, 'Overview'],
  [/这页回答/g, 'This page answers'], [/事件推断/g, 'inferred from events'], [/hover看统计/g, 'hover for stats'],
  [/看/g, 'see '], [/没有手动置顶/g, 'Without manual pins, '], [/all历史/g, 'all history'], [/历史/g, 'history'],
  [/会话最多的/g, 'with the most sessions '], [/个项目/g, ' projects'], [/点击图钉可置顶/g, 'click the pin to pin'],
  [/定写进/g, ' into '], [/相关/g, 'relevant '], [/规则/g, 'rule'], [/轨迹/g, 'trace'],
  [/修复/g, 'Fix'], [/合并/g, 'Merge'], [/同步/g, 'Sync'], [/实施/g, 'Implement'], [/审查/g, 'Review'],
  [/探索/g, 'Explore'], [/清理/g, 'Cleanup'], [/调试/g, 'Debug'], [/验证/g, 'Validation'], [/规划/g, 'Plan'],
  [/(\d+)\s*分钟/g, '$1 min'], [/完成率/g, 'completion rate'],
  [/（/g, '('], [/）/g, ')'], [/：/g, ': '], [/；/g, '; '], [/！/g, '!'], [/？/g, '?'],
  [/连续/g, 'consecutive '], [/审批/g, 'approval '], [/或/g, 'or '], [/被你拒绝/g, 'you denied '],
  [/上下文/g, 'context '], [/阶段/g, ' stage'], [/点列头/g, 'Click a column header to '],
  [/点行/g, 'click a row to '], [/迷你线为/g, 'sparkline shows '], [/本次有 /g, 'This session had '],
  [/把相关/g, 'put the relevant '], [/写进/g, 'into '], [/下次/g, 'next time '], [/少说一次/g, 'say it once fewer'],
  [/command占/g, 'commands account for '],
  [/(\d+)\s*分/g, '$1 min'], [/(\d+)\s*日/g, '$1'], [/你发了/g, 'You sent '],
  [/次纠偏/g, ' corrections'], [/sessionsoccurred/g, 'sessions occurred'],
  [/方向error/g, 'direction errors'], [/完成/g, 'done'], [/压缩/g, 'compaction'], [/追踪/g, 'traces'],
  [/搜索/g, 'search'], [/编辑/g, 'edit'], [/命令/g, 'command'], [/只分析最/g, 'Only analyze the last '],
  [/最近/g, 'last '], [/no手动置顶/g, 'Without manual pins, '], [/manual pins when,/g, 'manual pins, '],
  [/定型/g, 'typing'], [/返工/g, 'rework'], [/散点图/g, 'scatter plot'], [/不是/g, 'not '],
  [/this意思/g, 'what this means'],
  [/environmentfailed/g, 'environment'], [/environment failed/g, 'environment'],
  [/按输出聚类/g, 'grouped by output'], [/输出聚类/g, 'grouped by output'],
  [/"AI 解读"/g, '"AI insights"'], [/你的协作人格/g, 'your collaboration style'], [/你的/g, 'your '],
  [/口径/g, 'Same definition as'], [/page: ：/g, 'page: '], [/projectsfilter/g, 'project filters'],
  [/跟随主窗口/g, 'follows the main window '], [/带为/g, 'band is '], [/次数/g, 'count'], [/与/g, ' and '],
  [/都can用/g, 'can all use '], [/高频词云, 共 ([\d,]+)\s*词/g, 'Top words cloud · $1 words'],
  [/我的 /g, 'My '], [/你的 /g, 'Your '], [/先看最上面/g, 'start with the '], [/一句话结论/g, 'one-line summary'],
  [/这页回答：/g, 'This page answers: '],
  [/你和 Agent/g, 'you and Agent'], [/先看顶部/g, 'start with '], [/再看三张指标卡/g, 'then the three KPI cards'],
  [/高频词云, 共 ([\d,]+) 词/g, 'Top words cloud · $1 words'],
  [/前两类占/g, 'the top two account for '], [/摩擦的/g, 'of friction '], [/都可用/g, 'can all use '], [/rule前置/g, 'rule up front'],
  [/字号/g, 'font size '], [/取对数/g, 'logarithmic '], [/只统计/g, 'counts only '], [/你发出的/g, 'you sent '],
  [/不含/g, 'excluding '], [/回复/g, 'replies'], [/输出/g, 'output'], [/代码/g, 'code'],
  [/拟合/g, 'fit '], [/置信区间/g, 'confidence interval'], [/样本少/g, 'few samples'], [/仅供参考/g, 'for reference only'],
  [/摩擦最多的是/g, 'highest friction is '], [/统计周期/g, 'period'], [/单独/g, 'separately '], [/全局为/g, 'global is '],
  [/点图钉/g, 'click the pin'], [/可置顶/g, 'to pin'], [/时,/g, ' when,'], [/的/g, ' '],
  [/，/g, ', '], [/、/g, ', '],
  [/([\d,]+(?:\.\d+)?)% 的会话要求验证/g, '$1% of sessions require verification'],
  [/([\d,]+(?:\.\d+)?) 条纠偏消息/g, '$1 correction messages'],
  [/会话要求验证/g, 'sessions require verification'],
  [/条纠偏消息/g, 'correction messages'],
  [/纠偏消息/g, 'correction messages'],
  [/近 ([\d,]+) 天协作得怎么样/g, 'collaboration over the last $1 days'],
  [/协作得怎么样/g, 'collaboration'],
  [/完成率 /g, 'completion '],
  [/([\d,]+(?:\.\d+)?)\s*次工具调用/g, '$1 tool calls'],
  [/保留第 ([\d,]+) 行/g, 'Keep line $1'],
  [/(\d+) 种(?:type|类型)里最接近/g, 'closest of $1 types'],
  [/近 ([\d,]+) days/g, 'last $1 days'],
  [/([\d,]+(?:\.\d+)?)\s*个 MCP 服务/g, '$1 MCP servers'],
  [/([\d,]+(?:\.\d+)?)\s*个会话/g, '$1 sessions'],
  [/([\d,]+(?:\.\d+)?)\s*个 Agent/g, '$1 agents'],
  [/([\d,]+(?:\.\d+)?)\s*个工具/g, '$1 tools'],
  [/([\d,]+(?:\.\d+)?)\s*条消息/g, '$1 messages'],
  [/([\d,]+(?:\.\d+)?)\s*[条个]建议/g, '$1 suggestions'],
  [/([\d,]+(?:\.\d+)?)\s*条/g, '$1 items'],
  [/([\d,]+(?:\.\d+)?)\s*次/g, '$1 times'],
  [/([\d,]+(?:\.\d+)?)\s*行/g, '$1 rows'],
  [/([\d,]+(?:\.\d+)?)\s*张/g, '$1 images'],
  [/([\d,]+(?:\.\d+)?)\s*个/g, '$1'],
  [/([\d,]+(?:\.\d+)?)\s*个月/g, '$1 months'],
  [/([\d,]+(?:\.\d+)?)\s*个月/g, '$1 months'],
  [/([\d,]+(?:\.\d+)?)\s*小时/g, '$1 h'],
  [/([\d,]+(?:\.\d+)?)\s*分钟/g, '$1 min'],
  [/([\d,]+(?:\.\d+)?)\s*秒/g, '$1 s'],
  [/([\d,]+(?:\.\d+)?)\s*个月/g, '$1 months'],
  [/([\d,]+(?:\.\d+)?)\s*天/g, '$1 days'],
  [/([\d,]+(?:\.\d+)?)\s*周/g, '$1 weeks'],
  [/([\d,]+(?:\.\d+)?)\s*月/g, '$1 months'],
  [/近 ([\d,]+) 天/g, 'last $1 days'],
  [/上期/g, 'last period'],
  [/本页/g, 'this page'],
  [/全部 ([\d,]+) 条/g, 'all $1'],
  [/[「」]/g, '"'],
];

// 动态拼接文案的片段词典：只放多字短语，按长度降序，避免单字误伤
// 防护：单字中文规则极易误伤（如 会→will 命中“会话”），统一剔除；数字单位规则不受影响
I18N.rules = I18N.rules.filter(([re]) => {
  const src = String(re).replace(/^\//, '').replace(/\/[gimsuy]*$/, '');
  return !(src.length === 1 && /[\u3400-\u9fff]/.test(src));
});

I18N.frags = [
  ['会话轨迹','session traces'], ['协作人格','collaboration style'], ['协作画像','collaboration profile'],
  ['优化建议','suggestions'], ['资源库','library'], ['情绪语义','sentiment'], ['项目习惯','project habits'],
  ['生成工坊','studio'], ['工具调用','tool calls'], ['分享卡','share card'], ['分享报告','share report'],
  ['要求验证','require verification'], ['置信度','confidence'], ['指挥家','Conductor'], ['协调者','Coordinator'],
  ['委托','delegation'], ['即兴','improvisation'], ['规划','planning'], ['多线','multithread'], ['求证','verifying'],
  ['掌舵','steering'], ['信任','trust'], ['专注','focus'], ['上期','last period'], ['本期','this period'],
  ['其中','of which'], ['可以','can'], ['已经','already'], ['没有','no'], ['这个','this'], ['那个','that'],
  ['全部','all'], ['展开','expand'], ['收起','collapse'], ['查看','View'], ['打开','Open'], ['关闭','Close'],
  ['设置','Settings'], ['保存','Save'], ['取消','Cancel'], ['删除','Delete'], ['复制','Copy'], ['刚刚','just now'],
  ['分钟前','min ago'], ['小时前','h ago'], ['天前','days ago'], ['已完成','done'], ['运行中','running'],
  ['失败','failed'], ['成功','succeeded'], ['读取','Reading'], ['汇集','Collecting'], ['导入','Import'],
  ['分析','Analysis'], ['推荐','Recommend'], ['安装','Install'], ['撤销','Revert'], ['导出','Export'],
  ['时间长度','range'], ['朋友圈','WeChat Moments'], ['小红书','Xiaohongshu'], ['一键应用','one-click apply'],
  ['保留','keep'], ['属于','belongs to'], ['类型','type'], ['表格','table'], ['图表','chart'], ['卡片','card'],
  ['明细','details'], ['筛选','filter'], ['排序','sort'], ['会话','sessions'], ['纠偏','corrections'], ['消息','messages'],
  ['建议','suggestions'], ['项目','projects'], ['工具','tools'], ['脚本','script'], ['规则','rule'], ['技能','skill'],
  ['插件','plugin'], ['模型','model'], ['数据','data'], ['报告','report'], ['阶段','stage'], ['进度','progress'],
  ['结果','result'], ['原因','reason'], ['证据','evidence'], ['样本','samples'], ['覆盖','coverage'], ['时间','time'],
  ['错误','error'], ['本地','local'], ['云端','cloud'], ['隐私','privacy'], ['数据源','sources'], ['通用','general'],
  ['通知','notifications'], ['关于','about'], ['外观','appearance'], ['语言','language'], ['高级模式','advanced mode'],
]
  .filter((x) => x[0].length >= 2)
  .sort((a, b) => b[0].length - a[0].length);
I18N.frags.push(
  ['置信度 高','high confidence'], ['置信度 中','medium confidence'], ['置信度 低','low confidence'],
  ['已读取','Read'], ['我的','My'], ['概览','Overview'], ['为预置回答','is a preset answer'],
  ['全时卡','All-time card'], ['周卡','Weekly card'], ['月卡','Monthly card'], ['季卡','Quarterly card'],
  ['口径与','Same definition as '], ['页相同',' page: '], ['时间窗','time window'],
  ['跟随主窗口的','follows the main window '], ['预置回答','preset answer'], ['种','types'], ['里','of'],
  ['今天','today'], ['调用','calls'], ['种工具','tool types'], ['时长','duration'], ['条宽','bar width'],
  ['会话占比','share of sessions'], ['出现','occurred'], ['集中在','concentrated in'], ['按协作时长排序','sorted by collaboration time'],
  ['按输出聚类','grouped by output'], ['每日调用','daily calls'], ['命令占','commands account for '], ['示例','sample'],
  ['规则','rules'], ['运行中','running'], ['协作时长','collaboration time'], ['占比','share'], ['排序','sorted'],
  ['聚类','grouped'], ['平均','average'], ['最长','longest'], ['最短','shortest'], ['中位','median'],
  ['会话出现','sessions occurred'], ['环境','environment'], ['平均等待','average wait'], ['被打断','interrupted'],
  ['手动置顶','manual pins'], ['自动显示','automatically shows'], ['按当前','by current'], ['会话最多','most sessions'],
  ['悬停','hover'], ['图钉','pin'], ['可置顶','to pin'], ['等待','wait'], ['打断','interrupt'], ['约','about '], ['按','by '],
  ['运行中的','running '], ['失败的','failed '], ['最近的','recent '], ['全部的','all '], ['每个','each '], ['每秒','per second '],


);
I18N.frags.sort((a, b) => b[0].length - a[0].length);

function i18nPhrases() {
  // 字典里的完整中文短语（≥4 字）按长度降序，用于替换嵌在长句/提示里的数据标题
  const size = Object.keys(I18N.dict).length;
  if (I18N.phrasesSize !== size) {
    I18N.phrasesSize = size;
    I18N.phrases = Object.keys(I18N.dict)
      .filter((k) => !k.startsWith('@') && /[\u3400-\u9fff]/.test(k) && k.length >= 4 && k.length <= 60)
      .sort((a, b) => b.length - a.length);
  }
  return I18N.phrases;
}

function i18nDynamic(value) {
  let out = value;
  // 先整段替换字典里的中文短语（数据标题、完整句子），再处理零散片段
  if (/[\u3400-\u9fff]/.test(out)) {
    for (const zh of i18nPhrases()) if (out.includes(zh)) out = out.split(zh).join(I18N.dict[zh]);
  }
  for (const [re, rep] of I18N.rules) out = out.replace(re, rep);
  for (const [zh, en] of I18N.frags) out = out.split(zh).join(en);
  out = out.replace(/(times|days|weeks|months|items|images|types)(?=[A-Za-z])/g, '$1 ');
  out = out.replace(/ {2,}/g, ' ');
  return out;
}

const I18N_SKIP = new Set(['SCRIPT', 'STYLE', 'CODE', 'PRE', 'KBD', 'TEXTAREA', 'INPUT']);

function i18nText(value) {
  if (I18N.lang !== 'en') return value;
  const out = value.trim();
  if (!out) return value;
  const hit = I18N.dict[out];
  if (hit) return value.replace(out, hit);
  // 动态文案：整句查不到时按规则和片段替换
  return i18nDynamic(value);
}

function i18nNode(node) {
  if (node.nodeType === 3) {
    const next = i18nText(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
    return;
  }
  if (node.nodeType !== 1) return;
  const skipChildren = I18N_SKIP.has(node.tagName);
  // 表单控件自身的文本不翻译，但它们的 aria/tooltip/placeholder 是可见文案，仍要翻译
  for (const name of ['data-tip', 'aria-label', 'title', 'placeholder']) {
    const old = node.getAttribute(name);
    if (old && I18N.lang === 'en') {
      const key = old.trim();
      const hit = I18N.dict['@' + key] || I18N.dict[key];
      if (hit && hit !== old) node.setAttribute(name, old.replace(key, hit));
      else if (!hit) node.setAttribute(name, i18nDynamic(old));
    }
  }
  if (skipChildren) return;
  for (const child of node.childNodes) i18nNode(child);
}

function i18nApply(root) {
  const host = root && root.nodeType === 1 ? root : document.body;
  if (!host || !host.querySelectorAll) return;
  if (I18N.lang === 'en') {
    const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.parentElement && I18N_SKIP.has(node.parentElement.tagName)) continue;
      const next = i18nText(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
    for (const el of host.querySelectorAll('[data-tip],[aria-label],[title],[placeholder]')) i18nNode(el);
  }
}

function i18nSet(lang) {
  I18N.lang = lang === 'en' ? 'en' : 'zh';
  store.set('lang', I18N.lang);
  document.documentElement.lang = I18N.lang === 'en' ? 'en' : 'zh-CN';
  if (typeof render === 'function') render();
}

// Dynamic UI (sheets, dropdowns, toasts, live frames) is built after render; translate
// its added subtrees. A low-frequency full pass catches text and attributes written by
// charts, timers and live frames after the render hook ran.
if (typeof MutationObserver === 'function') {
  let queued = false;
  const observer = new MutationObserver((records) => {
    if (I18N.lang !== 'en' || queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === 1) i18nNode(node);
          else if (node.nodeType === 3 && node.parentElement && !I18N_SKIP.has(node.parentElement.tagName)) {
            const next = i18nText(node.nodeValue);
            if (next !== node.nodeValue) node.nodeValue = next;
          }
        }
      }
    });
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}
setInterval(() => {
  if (I18N.lang === 'en' && typeof i18nApply === 'function') i18nApply();
}, 300);
document.documentElement.lang = I18N.lang === 'en' ? 'en' : 'zh-CN';
