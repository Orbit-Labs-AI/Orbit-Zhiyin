/* ============ live binding: status strip + endpoint wiring (OrbitLive, js/06-live-client.js; core in 90-live-core.js) ============
   Mock mode (file://, opened on its own) changes nothing. Live mode keeps every polished page: 90-live-core hydrates the
   demo globals from /v1/uiview/facts and page feeds (LV.feed) overwrite page constants right before each render. This file
   only puts the status strip (import progress, service banner, connecting / computing / stale / failed badge) at the top of
   the content and keeps the sidebar footer honest. TL_VIEWS / lvScope / lvView / TL_PAGES / lvKey stay as the round-2
   compatibility surface used by 97-* / 98-* until their slices move to LV.feed. */
const TL_VIEWS = {};
const TL_PAGES = {};
function lvScope() {
  const on = AG.filter((a) => S.agents.has(a.id) && !S.srcOff.has(a.id)).map((a) => a.id);
  return { range: S.range, agents: on.length === AG.length ? null : on, projects: null, tz: TL_TZ };
}
function lvView(page) { const v = TL.view(page, lvScope()); TL_VIEWS[page] = v; return v; }
function lvTable(cols, rows, rowAttr) {
  return '<table class="tl-table"><thead><tr>' + cols.map((c) => '<th' + (c.n ? ' class="n"' : '') + '>' + c.t + '</th>').join('') + '</tr></thead><tbody>' +
    rows.map((r) => '<tr' + (rowAttr ? rowAttr(r) : '') + '>' + cols.map((c) => '<td' + (c.n ? ' class="n"' : '') + '>' + c.v(r) + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
}
const lvKey = (route) => (TO_ADV[route] && TL_PAGES[TO_ADV[route]] ? TO_ADV[route] : route);
ACT.lvSess = (el) => { S.lvSess = el.dataset.id; render(); };

// 重新计算 next to a failed analysis: the spine (LV.recompute) and every feed resource of the page that failed the same way
const lvRecBtn = () => '<button type="button" class="btn sm" data-act="lvRecompute" data-tl="recompute" style="margin-left:8px">重新计算</button>';
function lvFailedFeeds(route) {
  const out = [];
  (LV.feeds[route] || []).forEach((f) => lvFeedRes(f).forEach((x) => { if (x.r.state === 'error' && TLU.unavailable(x.r.error) && out.indexOf(x.r) < 0) out.push(x.r); }));
  return out;
}
ACT.lvRecompute = (el) => {
  if (el) el.disabled = true;
  const jobs = [];
  if (LV.failed) jobs.push(LV.recompute());
  const v = TL_VIEWS[lvKey(S.route)];
  const rs = lvFailedFeeds(S.route).concat(v && v.res ? Object.keys(v.res).map((n) => v.res[n]).filter((r) => r.state === 'error' && TLU.unavailable(r.error)) : []);
  rs.forEach((r) => jobs.push(TL.recompute(r, r.section ? null : { sections: [LV_SECTION], scope: { display_timezone: TL_TZ || 'UTC' } }).catch(() => {})));
  if (!jobs.length) LV.loadSpine();
  render();
};
ACT.lvRetry = (el) => { if (el) el.disabled = true; TL.retry(); LV.loadSpine(); render(); };
// The published data stays behind with no import running (one was stopped half way, /v1/status projection_info.stuck):
// say so, keep showing the last published data (only claimed when there is some), and 重新导入 posts the retry the gateway offers (all enabled sources).
function lvStuck() {
  const info = TL.status && TL.status.projection_info;
  if (!info || !info.stuck) return '';
  const files = info.pending_files ? '（' + fmt(info.pending_files) + ' 个文件）' : '';
  const what = info.state === 'invalid' ? '数据需要按新版本重建' : '最近的会话变化还没有发布' + files;
  return '<div class="tl-banner" role="alert" data-tl="projection-stuck">' + esc(what) + (ALL.length ? ' · 显示上次发布的数据' : '') +
    '<button type="button" class="btn sm" data-act="lvReimport" data-tl="reimport" style="margin-left:auto">重新导入</button></div>';
}
ACT.lvReimport = (el) => {
  if (el) el.disabled = true;
  const info = TL.status && TL.status.projection_info;
  const retry = (info && info.retry) || { method: 'POST', path: '/v1/app/jobs', body: { kind: 'import' } };
  TL.send(retry.method || 'POST', retry.path, retry.body).then(() => toast('已开始重新导入'),
    (e) => { if (el) el.disabled = false; toast(e.code === 'job_conflict' ? '已有导入任务在进行' : '重新导入失败：' + (e.message || e.code)); })
    .then(() => { TL.invalidate((r) => r === TL.statusResource()); return TL.ensureStatus(); }).catch(() => {});
};
function lvJobNote() {
  const j = LV.job; if (!j || j.elapsed_s == null) return '';
  return ' · 已用 ' + Math.round(j.elapsed_s) + (j.timeout_s ? ' / ' + Math.round(j.timeout_s) : '') + ' 秒';
}
// 202 meta.progress of the route's computing feed resource → 「已用 N / M 秒 · K 条事件」
function lvFeedProgress(route) {
  let p = null;
  (LV.feeds[route] || []).forEach((f) => lvFeedRes(f).forEach((x) => { if (!p && x.r.state === 'computing' && x.r.meta && x.r.meta.progress) p = x.r.meta.progress; }));
  return LV.progressNote(p);
}
// the spine's 202 progress, with the polled job's elapsed time once the job poll reports it
function lvSpineProgress() {
  const j = LV.job && LV.job.elapsed_s != null ? { elapsed_s: LV.job.elapsed_s, budget_s: LV.job.timeout_s || (LV.progress && LV.progress.budget_s) } : null;
  return LV.progress ? LV.progressNote(Object.assign({}, LV.progress, j)) : lvJobNote();
}
function lvSpineBadge() {
  if (LV.failed) return '<span class="tl-badge" data-tl="unavailable">' + esc(TLU.reason(LV.failed.reason)) + (ALL.length ? ' · 显示上次结果' : '') + '</span>' + lvRecBtn();
  if (LV.state === 'connecting') return '<span class="tl-badge" data-tl="connecting">正在连接本机服务</span>';
  // the first import is still being published (projection_pending): normal progress, not an error
  if (LV.pending && (LV.state === 'computing' || LV.stale)) return '<span class="tl-badge" data-tl="pending">正在整理数据…' + (ALL.length ? ' · 显示上次结果' : '') + '</span>';
  if (LV.state === 'computing') return '<span class="tl-badge" data-tl="computing">分析中' + lvSpineProgress() + '</span>';
  if (LV.state === 'error') return '<span class="tl-badge" data-tl="error">' + (ALL.length ? '刷新失败 · 显示上次结果' : '读取失败 · 稍后自动重试') + '</span>';
  if (LV.stale) return '<span class="tl-badge" data-tl="stale">分析中 · 显示上次结果</span>';
  return '';
}
function lvStrip(route) {
  const k = lvKey(route);
  const failed = lvFailedFeeds(route);
  const page = TL.isBound(k) ? TLU.badge(TL_VIEWS[k]) + (TL_VIEWS[k] && TLU.unavailable(TL_VIEWS[k].error) ? lvRecBtn() : '')
    : failed.length ? '<span class="tl-badge" data-tl="unavailable">' + esc(TLU.unavailable(failed[0].error)) + '</span>' + lvRecBtn()
      : LV.feedState(route) === 'computing' ? '<span class="tl-badge" data-tl="computing">分析中' + lvFeedProgress(route) + '</span>' : '';
  // the wanted range is wider than the window served so far (first-open fast path): say so, calmly
  const hint = LV.windowHint(route);
  // 「正在整理数据…」 already stands in the banner (or the import note above says it): no second 分析中 / 整理中 badge
  const calm = (x) => (TLU.pending && (TL.isPending && TL.isPending()) && /data-tl="(computing|pending)"/.test(x) ? '' : x);
  const b = (calm(lvSpineBadge()) || calm(page)) + (hint ? '<span class="tl-badge" data-tl="window"' + (calm(lvSpineBadge()) || calm(page) ? ' style="margin-left:8px"' : '') + '>' + esc(hint) + '</span>' : '');
  // offline / unavailable banner: 重试 refetches now (failed resources also retry by themselves with backoff, R4-11)
  let banner = TLU.banner(TL);
  if (banner && (TL.error || TL.failure)) banner = banner.replace(/<\/div>$/, '<button type="button" class="btn sm" data-act="lvRetry" data-tl="retry" style="margin-left:auto">重试</button></div>');
  const html = TLU.progress(TL) + (banner || lvStuck()) + (b ? '<div>' + b + '</div>' : '');
  return html ? '<div class="tl-strip" data-tl="strip">' + html + '</div>' : '';
}

if (LV.live) {
  TLU.ensureStyle(document);
  // while the published data is behind (pending / invalid) the gateway turns it "stuck" after a minute without an
  // import; re-read /v1/status meanwhile so the banner appears without waiting for another event
  setInterval(() => {
    const p = TL.status && TL.status.projection;
    if (p !== 'pending' && p !== 'invalid') return;
    TL.invalidate((r) => r === TL.statusResource());
    TL.ensureStatus().catch(() => { /* the strip keeps the last status */ });
  }, 20000);
  const baseRender = render;
  render = function () {
    if (TL.markRender) TL.markRender();
    LV.pump(S.route);
    baseRender();
    const c = $('#content'); if (!c) return;
    // the page restored its scroll before the strip went back in on top: put it back once more (scroll anchoring would
    // otherwise push the page down by the strip's height on every render)
    const top = c.scrollTop;
    const old = c.querySelector(':scope > [data-tl="strip"]'); if (old) old.remove();
    const strip = lvStrip(S.route);
    if (strip) c.insertAdjacentHTML('afterbegin', strip);
    c.scrollTop = top;
    ddFollow();
  };
  // sidebar indicator, in order: gateway unreachable / connecting, collection paused, spine read failed, computing; once ready
  // the index mode — S.paused / S.index mirror the gateway's collection.paused and settings.sync_mode (97-live-studio-settings)
  sideIdx = function () {
    if (LV.state === 'connecting') return TL.error ? { st: 'err', n: null, t: '本机服务未连接' } : { st: 'busy', n: null, t: '正在连接本机服务' };
    if (S.paused) return sideMode(null);   // the gateway answered collection.paused; nothing is being indexed
    if (LV.state === 'error') return { st: 'err', n: ALL.length || null, t: '数据读取失败' };
    if (LV.state === 'computing') return { st: 'busy', n: ALL.length || null, t: '索引中' };
    return sideMode(ALL.length);
  };
  TL.start();
}
