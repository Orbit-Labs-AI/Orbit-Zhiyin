/* ============ keys, about, method ============ */
// One source of truth for shortcut copy: the bindings live in 85-keyboard.js, the menus (30-actions.js) show the same keys.
const KEYS = [['⌘K', '命令面板'], ['⌥1 – ⌥9', '切换页面（App 内是 ⌘1–9）'], ['⌥0', '主窗口（App 内是 ⌘0）'], ['⌃⌘S', '显示 / 隐藏侧边栏'], ['⌃⌘F', '进入 / 退出全屏'], ['⌘M', '最小化窗口'], ['⌘F', '页内搜索'], ['⌥R', '重新索引（App 内是 ⌘R）'], ['Space', '回放 / 暂停轨迹'], ['⌘↩', '当前页主操作'], ['⌘Z', '撤销最近一次安装'], ['⌥T', '图表 ↔ 表格（App 内是 ⌘T）'], ['⌘[', '返回上一页'], ['⌘,', '设置'], ['⇧⌘S', '导出分享卡'], ['⇧⌘E', '导出报告'], ['⌥⌘P', '显示 / 隐藏悬浮组件'], ['⌃⌥T', '菜单栏面板'], ['?', '本页快捷键'], ['Esc', '关闭弹窗与面板']];
function openKeys() {
  // in the native App the App key is the key: no ⌥ stand-ins, no grey「App 内」hints
  const app = nativeShell();
  const keys = app ? KEYS.map((k) => { const m = /（App 内是 (.+?)）/.exec(k[1]); return m ? [m[1], k[1].replace(m[0], '')] : k; }) : KEYS;
  openModal(modalHead('键盘快捷键', app ? 'Orbit 的全部快捷键' : '浏览器占用的组合在 Demo 里改用 ⌥，灰字是 App 内的按键') + '<div class="mb" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));gap:0 20px">' + keys.map((k) => '<div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--hair);gap:12px"><span style="font-size:13px;min-width:0">' + esc(k[1]).replace(/（App 内是 (.+?)）/, '<span class="cap" style="font-size:11px;margin-left:6px">App 内 $1</span>') + '</span><span class="kbd">' + esc(kb(k[0])) + '</span></div>').join('') + '</div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide');
}
// Live: version and components from GET /v1/app/about (+ the shell's __ORBIT_NATIVE__.app); the mock keeps the demo note.
let ABOUT = null;
function aboutRows(a) {
  const n = window.ORBIT && ORBIT.native && ORBIT.native.info;
  const app = (a && a.app) || {}, c = (a && a.components) || {}, rt = (a && a.runtime) || {};
  // the product version is the App's (the shell); the gateway's own name, version and contract go on the 本机服务 row
  return [['版本', (n && n.app) || app.version || '—'], ['App 外壳', n ? (n.app || '—') + ' · ' + (n.platform || 'macos') : '浏览器'], ['本机服务', [app.name, app.version, app.contract].filter(Boolean).join(' · ') || '—'],
    ['数据库结构', c.db_schema_version != null ? 'v' + c.db_schema_version : '—'], ['规则 / 分析', [c.rules_version, c.analytics_version].filter(Boolean).join(' · ') || '—'],
    ['脱敏规则', c.redaction_version || '—'], ['支持的 Agent', (c.mappers || []).map((k) => lvAgentOf(k).name).join('、') || '—'],
    ['运行环境', [rt.python && 'Python ' + rt.python, rt.platform, rt.arch].filter(Boolean).join(' · ') || '—']];
}
function drawAbout(first) {
  if (!first && (MODAL_KEY !== 'about' || $('#modal').hidden)) return;
  const n = window.ORBIT && ORBIT.native && ORBIT.native.info;
  const a = ABOUT, ver = (n && n.app) || (a && a.data && a.data.app && a.data.app.version);
  const body = !a || a.state === 'pending' ? LV.pend(180) : a.state === 'error' ? '<p style="margin:0">' + LV.na('暂时读不到版本信息（本机服务未响应）') + '</p>'
    : '<div class="col" data-about="rows" style="gap:0">' + aboutRows(a.data).map((r) => '<div class="row" style="justify-content:space-between;gap:16px;padding:7px 0;border-bottom:1px solid var(--hair)"><span class="cap" style="font-size:12px;flex:none">' + esc(r[0]) + '</span><span class="mono" style="font-size:12px;text-align:right;min-width:0;overflow-wrap:anywhere">' + esc(String(r[1])) + '</span></div>').join('') + '</div>';
  openModal(modalHead('关于 Orbit', 'Orbit' + (ver ? ' ' + ver : '') + ' · 本地的跨 Agent 会话分析') + '<div class="mb col" style="gap:12px;font-size:13px;line-height:1.65;color:var(--ink-2)"><div class="row" style="gap:12px"><span class="appicon" style="width:44px;height:44px;flex:none">' + appIcon(44) + '</span><div class="col" style="gap:6px">' + wordmark(20) + '<span class="mono cap" data-about="version">' + esc(ver || '—') + '</span></div></div>' + body + '<p class="cap" style="margin:0">全部数据只在本机；Orbit 不上传会话内容。</p></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>', 'wide'); MODAL_KEY = 'about';
}
function openAboutLive() {
  ABOUT = { state: 'pending', data: null };
  drawAbout(true);
  TL.get('/v1/app/about').then((r) => { ABOUT = { state: r.data ? 'ready' : 'error', data: r.data }; }, () => { ABOUT = { state: 'error', data: null }; }).then(drawAbout);
}
function openAbout() {
  if (LV.live) { openAboutLive(); return; }
  openModal(modalHead('关于这个 Demo', 'Orbit 交互 Demo · v1 · 2026-10-01') + '<div class="mb col" style="gap:10px;font-size:13px;line-height:1.65;color:var(--ink-2)"><p style="margin:0">这是 ActionMesh AI Hackathon 产品 Orbit·知音 的交互原型：一个本地的跨 Agent 会话分析 Mac App。</p><p style="margin:0"><b style="color:var(--ink-1)">能操作的：</b>9 个页面、菜单栏面板、悬浮组件、桌面小组件、设置、命令面板、安装与撤销、7 天效果追踪、生成工坊、首次启动、人格揭晓与分享卡。</p><p style="margin:0"><b style="color:var(--ink-1)">模拟的：</b>所有数据都是示例；写文件、运行命令、调用 Agent 与下载都不会真的发生。</p><p style="margin:0"><b style="color:var(--ink-1)">还没定的：</b>MVP 范围、人格维度的权重，需要团队三人确认。</p><div class="row" style="flex-wrap:wrap;gap:8px;margin-top:4px"><button type="button" class="btn sm" data-act="copyCanvas">' + ic('copy', 13) + '复制视觉案例画布链接</button><button type="button" class="btn sm" data-act="openKeys">键盘快捷键</button></div></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>');
}
// 「你」follows the persona page: same period (S.persona.period, default 近 90 天) and the same answer (live persona when the
// page uses it), labelled with that period. Axis names are the pole words the persona page uses (委托 / 即兴 / 多线 / 求证).
const METHOD_POLE = { D: '委托', I: '即兴', M: '多线', V: '求证' };
function methodPersona() {
  try {
    const key = PERIODS[S.persona.period] ? S.persona.period : '90'; const per = PERIODS[key];
    const L = personaScope([per[0], per[1]]);
    const p = LV.live && L.length >= 30 && !lvHasUnits(L) ? LV.personaFor(key, L) : persona(L);
    return { p: p || { ok: false }, label: per[2] };
  } catch (e) { return { p: personaNow(), label: '默认时间范围' }; }
}
function openMethod() {
  const mp = methodPersona(); const p = mp.p;
  openModal(modalHead('协作人格如何计算', '四个维度各取一极，组成 16 型 · 1 个会话即可出结论，样本越多越准') +
    '<div class="mb col" style="gap:14px">' + AXES.map((ax, i) => { const v = p.ok ? axisView(p, i) : null; return '<div class="col" style="gap:3px"><div class="row" style="gap:8px;flex-wrap:wrap"><b class="mono" style="font-size:13px;min-width:36px">' + ax.L + ' / ' + ax.R + '</b><b style="font-size:13px">' + METHOD_POLE[ax.k] + '</b><span class="cap" style="font-size:12px">' + ax.Ln + ' ↔ ' + ax.Rn + '</span>' + (v ? '<span class="mono cap" style="margin-left:auto" data-method="you">你 · ' + esc(mp.label) + '：' + v.letter + ' ' + v.name + ' ' + v.strong + '</span>' : '') + '</div><span class="cap" style="font-size:12px">' + ax.q + ' 信号：' + ax.sig + '</span></div>'; }).join('') +
    '<div class="code" style="padding:10px 12px;white-space:pre-wrap;font-size:12px;line-height:1.7">委托 D = 50 + (自主比 − 8) × 5.8\n即兴 I、求证 V = 各项目特征按协作时长加权\n多线 M = 20 + 7 × 日均会话 + 5 × 日均 Agent 数 − 6\n「你」一栏是偏向那一极的强度（50–100），不是百分比\n每个维度以 50 为界：≥ 50 取 D / I / M / V，< 50 取 S / P / F / T（恰好 50 归前者）\n始终给出完整 4 字母；少于 30 个会话时置信度标「低」</div>' +
    '<div class="eb">16 型 · 16 朵花 · 点击查看</div><div class="cap" style="font-size:12px;margin-top:-8px">花型由四个字母决定：瓣数看多线 M（12 瓣）/ 专注 F（5 瓣），旋卷看即兴 I / 规划 P（端正尖头），瓣长与花心看委托 D（长瓣小花心）/ 掌舵 S（短阔瓣大花心），重瓣看求证 V / 信任 T（单瓣）</div><div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">' + Object.keys(TYPES).map((k) => '<button type="button" data-act="typeInfo" data-k="' + k + '" style="border-radius:8px;padding:6px 8px;text-align:left;display:grid;grid-template-columns:auto minmax(0,1fr);column-gap:8px;align-items:center;' + (p.ok && p.code === k ? 'border:1.5px solid var(--ink-1);background:var(--surface)' : 'border:1px solid var(--line);background:var(--bg)') + '"><span style="grid-row:span 2;display:flex">' + glyphSVG(typeP(k), 30) + '</span><b class="tcode" style="font-size:12px;letter-spacing:.04em">' + k + '</b><span style="font-size:12px;color:var(--ink-2)">' + TYPES[k][0] + '</span></button>').join('') + '</div><div id="typeLine" style="min-height:20px;font-size:13px;line-height:20px;color:var(--ink-2)">' + (p.ok ? '<b style="color:var(--ink-1)">' + p.code + ' ' + p.zh + '</b>：' + esc(p.line) : '点击任一类型查看描述') + '</div></div><div class="mf"><span class="cap" style="margin-right:auto;font-size:11px">维度信号与权重是初版设想，待真实数据校准</span><button type="button" class="btn" data-act="openSettings" data-tab="analysis">分析设置</button><button type="button" class="btn p" data-act="closeModal">知道了</button></div>', 'wide');
}
Object.assign(ACT, {
  openKeys: () => openKeys(),
  openAbout: () => openAbout(),
  copyCanvas: () => copyText('https://claude.ai/artifact/DgXdy7dfYpuA7oi2JSv3sV', '画布链接'),
  typeInfo: (el) => { const k = el.dataset.k; const t = $('#typeLine'); if (t) t.innerHTML = '<b style="color:var(--ink-1)">' + k + ' ' + TYPES[k][0] + '</b> <i class="serif" style="color:var(--ink-3)">' + TYPES[k][1] + '</i>：' + esc(TYPES[k][2]); }
});

