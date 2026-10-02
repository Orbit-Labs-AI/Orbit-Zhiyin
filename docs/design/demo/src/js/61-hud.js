/* ============ floating HUD ============ */
let HUD_MUTE_TIMER = null;
function setHudMuted(muted, durationMs) {
  clearTimeout(HUD_MUTE_TIMER);
  HUD_MUTE_TIMER = null;
  S.hud.mute = muted;
  if (muted && durationMs) HUD_MUTE_TIMER = setTimeout(() => setHudMuted(false), durationMs);
  render();
}
function hudCard() {
  const r = rng(77);
  const lane = (label, n, color, w) => { let ticks = ''; for (let i = 0; i < n; i++) ticks += '<rect x="' + (2 + r() * 300).toFixed(1) + '" y="1" width="' + w + '" height="10" rx="1" fill="' + color + '"/>'; return '<div class="lane"><span>' + label + '</span><svg viewBox="0 0 312 12" width="100%" height="12" preserveAspectRatio="none" aria-hidden="true"><line x1="0" x2="312" y1="6" y2="6" stroke="var(--hud-line)"/>' + ticks + '<line x1="310" x2="310" y1="0" y2="12" stroke="var(--hud-ink-3)" stroke-dasharray="2 2"/></svg></div>'; };
  const tip = !S.hud.tipOff && S.live.ctx >= 60;
  return '<div class="hcard" role="dialog" aria-label="会话详情"><div class="row"><span class="dot live" style="background:var(--a1)"></span><b style="font-size:13px">Claude Code</b><span style="color:var(--hud-ink-3);font-size:12px">· Hackathon</span><span style="flex:1"></span><span class="mono" data-live style="font-size:12px">' + liveElapsed() + '</span></div>' +
    '<div class="col" style="gap:3px"><div class="serif" style="font-size:17px;font-weight:600;line-height:22px">设计 Tandem Mac App 视觉案例</div><div class="row" style="font-size:12px;color:var(--hud-ink-2)"><span style="padding:1px 6px;border-radius:4px;background:rgba(180,168,255,.18);color:#c9c0ff;font-weight:600">进行中</span><span class="mono" data-hudtool>' + HUD_TOOLS[HUD_T % HUD_TOOLS.length] + '</span></div></div>' +
    '<div class="col" style="gap:5px"><div class="row" style="justify-content:space-between;font-size:11px;color:var(--hud-ink-3)"><span>最近 20 分钟</span><span>现在</span></div>' + lane('你', 4, 'var(--hud-ink)', 3) + lane('工具', 26, 'var(--a1)', 2) + lane('错误', 1, '#ff7d74', 3) + '</div>' +
    '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">' + [['上下文', S.live.ctx + '%'], ['工具', S.live.tools], ['错误', 1], ['消息', 4]].map((x) => '<div style="border-radius:9px;background:var(--hud-2);padding:6px 8px"><div style="font-size:11px;color:var(--hud-ink-3)">' + x[0] + '</div><b class="mono" style="font-size:15px"' + (x[0] === '工具' ? ' data-livetools' : '') + '>' + x[1] + '</b></div>').join('') + '</div>' +
    (tip ? '<div style="border-radius:12px;background:rgba(243,184,67,.12);padding:10px 12px;display:flex;flex-direction:column;gap:8px"><div style="font-size:12px;line-height:1.55;color:var(--hud-ink-2)"><b style="color:#f3b843">提示</b> · 上下文已用 ' + S.live.ctx + '%。如果还要做 3 个以上的画板，先让 Agent 总结进度再继续，可以避免压缩时丢失细节。</div><div class="row"><button type="button" class="hb" data-act="hudTip">复制提示语</button><button type="button" class="hg" data-act="hudTipOff">不再提示此类</button></div></div>' : '') +
    (sourceEnabled({ a: 'cx' }) ? '<div class="col" style="gap:6px"><span style="font-size:11px;color:var(--hud-ink-3)">另外 1 个会话</span><div class="row" style="font-size:12px"><span class="dot" style="background:var(--a2)"></span><span style="flex:1;min-width:0">Codex · team-hub' + (S.sim === 'waiting' ? ' · <span style="color:#f3b843">等你确认 2 分钟</span>' : ' · 09:03 已完成') + '</span>' + (S.sim === 'waiting' ? '<button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>' : '<button type="button" class="hg" data-act="openSession" data-id="sess-1001-0903">打开轨迹</button>') + '</div></div>' : '') +
    '<div class="row" style="flex-wrap:wrap;border-top:1px solid var(--hud-line);padding-top:10px"><button type="button" class="hg" data-act="hudMute">' + (S.hud.mute ? '恢复提醒' : '暂停提醒 30 分钟') + '</button><span style="flex:1"></span><button type="button" class="hg" data-act="hudHide">隐藏</button><button type="button" class="hb" data-act="hudTraj">打开轨迹</button></div></div>';
}
function hudPill() {
  let st = S.attn.has('stuck') ? 'stuck' : S.sim;
  if ((st === 'stuck' || st === 'waiting') && !sourceEnabled({ a: 'cx' })) st = 'running';
  const dens = '<svg width="34" height="18" viewBox="0 0 34 18" aria-hidden="true">' + [5, 9, 6, 12, 8].map((h, i) => '<rect x="' + (i * 7) + '" y="' + (18 - h) + '" width="4" height="' + h + '" rx="1" fill="' + (i === 4 ? 'var(--a1)' : 'rgba(255,255,255,.28)') + '"/>').join('') + '</svg>';
  if (st === 'stuck') return ic('alert', 16, 'color:#ff7d74') + '<b>同一命令失败 4 次</b><span style="color:var(--hud-ink-3);font-size:12px">Codex · Surge</span><button type="button" class="hb" data-act="hudGo" data-v="stuck">查看原因</button>';
  if (st === 'waiting') return '<span style="width:10px;height:10px;border-radius:2px;background:#f3b843;flex:none"></span><b>Codex</b><span style="color:var(--hud-ink-2)">请求执行 git push</span><button type="button" class="hb" data-act="hudGo" data-v="waiting">去处理</button>';
  if (st === 'done') return ic('okc', 16, 'color:#5dd08a') + '<b>完成</b><span style="color:var(--hud-ink-2)">42 分钟 · 186 步</span><button type="button" class="hb" data-act="hudTraj">查看</button>';
  if (st === 'ctx') return ic('gauge', 16, 'color:#f3b843') + '<b>上下文 78%</b><span style="color:var(--hud-ink-2)">latentskill 即将压缩</span><button type="button" class="hb" data-act="hudTip">复制提示语</button>';
  return '<span class="dot live" style="width:9px;height:9px;background:var(--a1)"></span><b>Hackathon</b><span class="mono" data-live>' + liveElapsed() + '</span><span data-hudtool style="color:var(--hud-ink-2);max-width:150px;overflow:hidden;text-overflow:ellipsis">' + HUD_TOOLS[HUD_T % HUD_TOOLS.length] + '</span>' + dens + (sourceEnabled({ a: 'cx' }) ? '<span class="mono" style="font-size:11px;color:var(--hud-ink-3)" data-tip="另有 1 个会话今天已完成">+1</span>' : '');
}
function renderHud() {
  const h = $('#hud');
  if (!S.hud.show || S.sim === 'idle' || S.paused || !sourceEnabled(ALL.find((s) => s.id === LIVE_ID))) { h.hidden = true; h.innerHTML = ''; return; }
  h.hidden = false;
  h.innerHTML = '<div class="pill" id="hudPill" role="button" tabindex="0" aria-expanded="' + S.hud.open + '" aria-label="悬浮组件，点击展开，拖动可移动">' + hudPill() + '</div>' + (S.hud.open ? hudCard() : '');
  hudPlace();
}
/* six snap points (top row under the menu bar, bottom row above the stage edge), in order of preference.
   Notification banners also live in the top-right corner (above the HUD), so a top-row pill that would sit under them is
   pushed below the visible stack; it moves back up as banners slide out (notify / noteDismiss call hudPlace). */
function notesRect() {
  const box = $('#notes'); if (!box || !box.querySelector('.nt:not(.out)')) return null;
  const d = desk.getBoundingClientRect(), r = box.getBoundingClientRect();
  return { x: r.left - d.left, y: r.top - d.top, w: r.width, h: r.height };
}
function snapPts(w) {
  const W = desk.clientWidth, H = desk.clientHeight;
  const xs = { l: 16, c: (W - w) / 2, r: W - w - 16 }, ys = { t: MB_H + 8, b: H - 44 - 16 };
  return [['t', 'r'], ['t', 'l'], ['t', 'c'], ['b', 'r'], ['b', 'l'], ['b', 'c']].map((p) => ({ k: p[0] + p[1], x: Math.max(4, xs[p[1]]), y: ys[p[0]] }));
}
// "occupied" = the main window (unless closed) and the visible desktop widgets: the pill should cover neither by default
function widgetsRect() {
  const el = $('#widgets'); if (!el || el.hidden || !el.offsetHeight) return null;
  const d = desk.getBoundingClientRect(), r = el.getBoundingClientRect();
  return { x: r.left - d.left, y: r.top - d.top, w: r.width, h: r.height };
}
function hudHitsWin(x, y, w, h) {
  const hit = (r) => !!r && x < r.x + r.w && x + w > r.x && y < r.y + r.h && y + h > r.y;
  return hit(S.winGone ? null : (WIN_LAST || winRect())) || hit(widgetsRect());
}
function nearestSnap(x, y, w) { let best = null, bd = Infinity; snapPts(w).forEach((p) => { const dd = Math.hypot(p.x - x, p.y - y); if (dd < bd) { bd = dd; best = p; } }); return best; }
function showSnaps(w) { hideSnaps(); snapPts(w).forEach((p) => { const s = document.createElement('div'); s.className = 'snap'; s.dataset.k = p.k; s.style.left = (p.x + w / 2) + 'px'; s.style.top = (p.y + 22) + 'px'; desk.appendChild(s); }); }
function hideSnaps() { $$('.snap').forEach((s) => s.remove()); }
function hudPlace() {
  const h = $('#hud'), pill = $('#hudPill'); if (h.hidden || !pill) return;
  const W = desk.clientWidth, H = desk.clientHeight, pw = pill.offsetWidth, ph = 44;
  let x, y;
  if (S.hud.snap) {
    const pts = snapPts(pw); let p = pts.find((q) => q.k === S.hud.snap) || pts[0];
    // until the user places it, keep the pill off the main window: first free snap point, else bottom-centre (never the title
    // row, and the window's resize corners stay reachable)
    if (!S.hud.user && hudHitsWin(p.x, p.y, pw, ph)) p = pts.find((q) => !hudHitsWin(q.x, q.y, pw, ph)) || pts.find((q) => q.k === 'bc') || p;
    x = p.x; y = p.y;
    const nr = notesRect();
    if (nr && p.k[0] === 't' && x < nr.x + nr.w && x + pw > nr.x && y < nr.y + nr.h + 8) y = Math.min(nr.y + nr.h + 8, H - ph - 4);
  }
  else { x = clamp(S.hud.x == null ? W - pw - 16 : S.hud.x, 4, Math.max(4, W - pw - 4)); y = clamp(S.hud.y == null ? H - 60 : S.hud.y, MB_H + 8, Math.max(MB_H + 8, H - ph - 4)); }
  const right = x + pw / 2 > W / 2 + 1, bottom = y + ph / 2 > H / 2;
  h.style.left = right ? 'auto' : x + 'px'; h.style.right = right ? Math.max(4, W - x - pw) + 'px' : 'auto';
  h.style.top = bottom ? 'auto' : y + 'px'; h.style.bottom = bottom ? Math.max(4, H - y - ph) + 'px' : 'auto';
  h.style.flexDirection = bottom ? 'column-reverse' : 'column'; h.style.alignItems = right ? 'flex-end' : 'flex-start';
}
function toggleHud() { S.hud.show = !S.hud.show; if (!S.hud.show) S.hud.open = false; render(); toast(S.hud.show ? '已显示悬浮组件 · ' + kb('⌥⌘P') + ' 隐藏' : '已隐藏悬浮组件 · ' + kb('⌥⌘P') + ' 重新显示'); }
let HDRAG = null;
$('#hud').addEventListener('pointerdown', (e) => {
  const pill = e.target.closest('#hudPill'); if (!pill || e.target.closest('button') || e.button !== 0) return;
  const r = pill.getBoundingClientRect(), d = desk.getBoundingClientRect();
  HDRAG = { sx: e.clientX, sy: e.clientY, x0: r.left - d.left, y0: r.top - d.top, w: r.width, moved: false, x: r.left - d.left, y: r.top - d.top };
  try { pill.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
});
$('#hud').addEventListener('pointermove', (e) => {
  if (!HDRAG) return;
  const dx = e.clientX - HDRAG.sx, dy = e.clientY - HDRAG.sy;
  if (!HDRAG.moved && Math.hypot(dx, dy) < 5) return;
  const h = $('#hud');
  if (!HDRAG.moved) { HDRAG.moved = true; const c = $('#hud .hcard'); if (c) c.remove(); S.hud.open = false; showSnaps(HDRAG.w); h.style.flexDirection = 'column'; h.style.alignItems = 'flex-start'; }
  const W = desk.clientWidth, H = desk.clientHeight;
  HDRAG.x = clamp(HDRAG.x0 + dx, 4, W - HDRAG.w - 4); HDRAG.y = clamp(HDRAG.y0 + dy, 30, H - 48);
  h.style.left = HDRAG.x + 'px'; h.style.top = HDRAG.y + 'px'; h.style.right = 'auto'; h.style.bottom = 'auto';
  const n = nearestSnap(HDRAG.x, HDRAG.y, HDRAG.w); $$('.snap').forEach((s) => s.classList.toggle('near', !e.altKey && s.dataset.k === n.k));
});
function hudDragEnd(e) {
  if (!HDRAG) return; const d = HDRAG; HDRAG = null; hideSnaps();
  if (!d.moved) { S.hud.open = !S.hud.open; renderHud(); return; }
  if (e.altKey) { S.hud.snap = null; S.hud.x = d.x; S.hud.y = d.y; } else S.hud.snap = nearestSnap(d.x, d.y, d.w).k;
  S.hud.user = true;
  store.set('hud', { snap: S.hud.snap, x: S.hud.x, y: S.hud.y, user: true });
  renderHud();
}
$('#hud').addEventListener('pointerup', hudDragEnd);
$('#hud').addEventListener('pointercancel', (e) => { if (HDRAG) { HDRAG.moved = true; hudDragEnd(e); } });
Object.assign(ACT, {
  hudGo: (el) => {
    const v = el.dataset.v;
    if (v === 'waiting') { S.sim = 'running'; render(); toast('已切换到 Codex 所在的终端标签页（演示）；批准仍由你在终端里完成'); }
    else if (v === 'stuck') { S.pop = true; S.hud.open = false; render(); }
  },
  hudTraj: () => { S.hud.open = false; if (S.sim === 'done') S.sim = 'running'; ACT.openSession({ dataset: { id: LIVE_ID } }); },
  hudTip: () => { copyText('先总结目前的进度：已完成的文件、关键决定和剩余待办，写成一段摘要，然后再继续下一步。', '提示语'); },
  hudTipOff: () => { S.hud.tipOff = true; renderHud(); toast('这类提示不会再出现；可以在设置 › 通知里恢复'); },
  hudMute: () => { setHudMuted(!S.hud.mute, 30 * 60 * 1000); if (S.hud.mute) toast('已暂停提醒 30 分钟', { act: '恢复', onAct: () => setHudMuted(false) }); else toast('已恢复提醒'); },
  hudHide: () => toggleHud()
});

