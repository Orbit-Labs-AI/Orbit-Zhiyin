/* ============ state ============ */
const S = {
  route: 'overview', range: 30, agents: new Set(AG.map((a) => a.id)), srcOff: new Set(),
  project: null, topic: null, outcome: null, fric: null, hour: null,
  compare: true, metric: 'n', view: 'chart', theme: store.get('theme', 'system'),
  // shell: sidebar shown (user intent) / sidebar as an overlay in a narrow window / collapsible groups / key window /
  // main window rect {x,y,w,h} (all null = fills the stage and follows the viewport; set once the user moved or resized it)
  // + zoom / full-screen flags (loaded from localStorage in 22-window.js)
  side: true, sideOver: false, sideOpen: { insight: true, action: true, agents: true, pins: true }, keyWin: 'main',
  win: { x: null, y: null, w: null, h: null, zoom: false, full: false }, setPos: null,
  winGone: false, widgets: false,
  persona: { period: 'sep', vs: 'past' },
  sess: { sel: FEAT_ID, q: '', mode: 'single', cmp: null, zoom: 1, axis: 'time', ph: 30.8, playing: false, hi: null },
  tools: { sort: 'n', dir: -1, failOnly: false, open: null, figma: true, openFail: null },
  proj: { sel: 'latentskill', group: 'project', cmp: null },
  recs: { dim: 'all', lv: new Set([1, 2, 3]), aud: 1, sel: 'pr-wrapup', tab: 'preview', scope: 'global', gone: new Set() },
  lib: { tab: 'for', kind: '全部', q: '' },
  studio: { type: 'Skill', goal: '把我常用的 PR 收尾流程做成一个 Skill：最多两轮 review，只修 P0 / P1，合并后删除分支，第二轮后有剩余意见就停下来汇报。', ctx: { sum: true, fric: true, rules: true, raw: false, redact: true }, agent: 'cc', run: null, from: 'A7 建议「PR 收尾」' },
  installed: new Map(), history: [],
  setTab: 'sources', engine: 'agent', anon: false, index: 'live', paused: false,
  rules: { '路径中的用户名': true, '邮箱': true, 'API Key / Token': true, '内网 IP 与主机名': true, '手机号': true },
  notif: { waiting: [1, 1, 1], done: [1, 1, 0], stuck: [0, 1, 1], ctx: [0, 1, 1], weekly: [1, 0, 0] },
  hud: { show: true, open: false, x: null, y: null, mute: false },
  sim: 'running', pop: false, extraSrc: [],
  live: { t0: Date.now() - (18 * 60 + 42) * 1000, tools: 61, ctx: 62 }
};
const CLOCK0 = Date.UTC(2026, 9, 1, 7, 30, 0) - Date.now();
function nowText() { const d = new Date(Date.now() + CLOCK0 + 8 * 3600000); return (d.getUTCMonth() + 1) + '月' + d.getUTCDate() + '日 周四 ' + hm(d.getUTCHours(), d.getUTCMinutes()); }
function liveElapsed() { const s = Math.floor((Date.now() - S.live.t0) / 1000); return hm(Math.floor(s / 60), s % 60); }
