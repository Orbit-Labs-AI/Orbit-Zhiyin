/* ============ navigation history, main action, studio guard ============ */
const NAVH = [];
const _go = go;
// eslint-disable-next-line no-func-assign
go = function (route, keepScroll) { if (PAGES[route] && route !== S.route) { NAVH.push(S.route); if (NAVH.length > 30) NAVH.shift(); } _go(route, keepScroll); };
function goBack() { const r = NAVH.pop(); if (r) _go(r); else toast('没有可以返回的页面'); }
function mainAction() {
  const r = S.route;
  if (r === 'recs') { const rec = RECI[S.recs.sel]; if (rec && !S.installed.has(rec.id)) openInstall(rec.id); else toast('这条建议已经安装'); }
  else if (r === 'studio') ACT.studioStart();
  else if (r === 'sessions') ACT.resume();
  else if (r === 'persona') openShare();
  else if (r === 'projects') ACT.projRule();
  else if (r === 'sentiment') ACT.phrasesToRule();
  else if (r === 'library') { const x = LIB[0]; if (x) openInstall(x.rec, x); }
  else openReport();
}
const _studioStart = ACT.studioStart;
ACT.studioStart = (el, e) => { if (S.engine === 'stats') { toast('分析引擎是「仅统计」，生成工坊不可用', { act: '去设置', onAct: () => openSettings('analysis') }); return; } _studioStart(el, e); };

