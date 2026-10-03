/* ============ ui plumbing: theme, tooltip, toast, sheets (#modal), dropdown menus, notifications ============ */
const desk = $('#desk');
const APP_MARK = appIcon(32);
function setTheme(t) {
  S.theme = t; store.set('theme', t);
  if (t === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t);
  // native shell: NSApp.appearance follows (system → nil), so open / save panels, notifications and popovers match the page
  const n = window.ORBIT && window.ORBIT.native;
  if (n && n.isNative && n.has('appearance') && n.hasHost()) n.post('appearance', { mode: t === 'light' || t === 'dark' ? t : 'system' });
}
/* tooltip: light, 11px, shows after a 0.8s hover delay (tipOn() itself is immediate) */
let TIPS = {}, TIP_T = null;
function tipOn(el, ev) {
  let html = null;
  if (el.dataset.tip) html = esc(el.dataset.tip);
  else if (el.dataset.tf) { const [k, ...args] = el.dataset.tf.split('|'); if (TIPS[k]) html = TIPS[k](...args); }
  if (!html) return;
  const t = $('#tip'); t.innerHTML = html; t.hidden = false; tipMove(ev);
}
function tipMove(ev) {
  const t = $('#tip'); if (t.hidden) return;
  const w = t.offsetWidth, h = t.offsetHeight;
  let x = ev.clientX + 12, y = ev.clientY + 18;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - 12;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - 12;
  t.style.left = Math.max(8, x) + 'px'; t.style.top = Math.max(8, y) + 'px';
}
function tipOff() { clearTimeout(TIP_T); $('#tip').hidden = true; }
document.addEventListener('mouseover', (e) => {
  const el = e.target.closest('[data-tip],[data-tf]'); clearTimeout(TIP_T);
  if (el) { const ev = { clientX: e.clientX, clientY: e.clientY }; TIP_T = setTimeout(() => tipOn(el, ev), 800); } else tipOff();
});
document.addEventListener('mousemove', tipMove);
document.addEventListener('mousedown', () => tipOff(), true);
document.addEventListener('focusin', (e) => { const el = e.target.closest('[data-tip],[data-tf]'); if (el && el.matches(':focus-visible')) { const r = el.getBoundingClientRect(); tipOn(el, { clientX: r.left + r.width / 2, clientY: r.bottom }); } });
document.addEventListener('focusout', tipOff);

/* toast(msg, {act, sec, onAct}) — a status / undo bar inside the main window (top of the content column) */
let toastTimer = null;
function toast(msg, opt) {
  opt = opt || {};
  const t = $('#toast'); clearInterval(toastTimer);
  let left = opt.sec || 0;
  const draw = () => { t.innerHTML = '<div class="toast-in"><span>' + esc(msg) + '</span>' + (opt.act ? '<button type="button" data-act="toastAct">' + esc(opt.act) + (left ? ' · ' + left : '') + '</button>' : '') + '</div>'; };
  t.onAct = opt.onAct || null; draw(); t.hidden = false; toastPlace();
  let life = opt.sec ? opt.sec : 4;
  toastTimer = setInterval(() => { life--; if (opt.sec) { left = life; draw(); } if (life <= 0) { clearInterval(toastTimer); t.hidden = true; } }, 1000);
}
function toastPlace() {
  const t = $('#toast'); if (t.hidden) return;
  const d = desk.getBoundingClientRect(); const m = $('#main');
  if (m && !S.winGone) { const r = m.getBoundingClientRect(); t.style.left = Math.round(r.left - d.left) + 'px'; t.style.width = Math.round(r.width) + 'px'; t.style.top = Math.round(r.top - d.top + 60) + 'px'; t.style.bottom = 'auto'; }
  else { t.style.left = '0px'; t.style.width = Math.round(d.width) + 'px'; t.style.top = 'auto'; t.style.bottom = '28px'; }
}

/* sheets: openModal(html, cls) attaches #modal under the title bar of the key window (main window or settings), the scrim only
   covers that window; cls "pal" is the floating command palette (no scrim). Focus lands on the default button, Return
   triggers it (85-keyboard.js), Esc closes; the previously focused element gets focus back on close. */
let MODAL_KEY = null, MODAL_PREV = null, MODAL_HOST = null;
function sheetHost() { const set = $('#set'); return (!set.hidden && S.keyWin === 'set') ? set : $('#win'); }
function openModal(html, cls) {
  const m = $('#modal'); const pal = /\bpal\b/.test(cls || '');
  if (m.hidden) MODAL_PREV = document.activeElement;
  MODAL_HOST = pal ? null : sheetHost();
  if (MODAL_HOST === $('#win') && S.winGone) { S.winGone = false; render(); }
  m.className = 'modal' + (cls ? ' ' + cls : ''); m.innerHTML = html; m.hidden = false;
  if (!pal) { const mh = m.querySelector('.mh'); if (mh && !mh.querySelector('[data-act="closeModal"]')) mh.insertAdjacentHTML('beforeend', '<button type="button" class="ib mx" data-act="closeModal" aria-label="关闭对话框" data-tip="关闭（Esc）">' + ic('x', 14) + '</button>'); }
  $('#scrim').hidden = pal; closeDD(); tipOff(); sheetPlace();
  const f = m.querySelector('[autofocus]') || m.querySelector('.mf .btn.p:not([disabled])') || m.querySelector('input:not([type="checkbox"]):not([type="radio"]),textarea') || m.querySelector('button.p:not([disabled])') || m.querySelector('button:not([disabled]):not(.mx)');
  if (f) setTimeout(() => { if (!m.hidden && m.contains(f)) f.focus({ preventScroll: true }); }, 20);
}
function closeModal() {
  const m = $('#modal'); const was = !m.hidden;
  m.hidden = true; $('#scrim').hidden = true; m.innerHTML = ''; m.className = 'modal'; MODAL_KEY = null; MODAL_HOST = null;
  const p = MODAL_PREV; MODAL_PREV = null;
  if (was && p && p.isConnected && typeof p.focus === 'function' && !p.closest('#modal')) { try { p.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
}
function sheetPlace() {
  const m = $('#modal'), sc = $('#scrim'); if (m.hidden) return;
  const d = desk.getBoundingClientRect();
  if (!MODAL_HOST) { m.style.left = Math.max(8, Math.round((d.width - m.offsetWidth) / 2)) + 'px'; m.style.top = Math.round(Math.max(40, d.height * 0.14)) + 'px'; m.style.maxHeight = Math.round(d.height * 0.72) + 'px'; return; }
  const r = MODAL_HOST.getBoundingClientRect();
  const hx = Math.round(r.left - d.left), hy = Math.round(r.top - d.top), hw = Math.round(r.width), hh = Math.round(r.height);
  sc.style.left = hx + 'px'; sc.style.top = hy + 'px'; sc.style.width = hw + 'px'; sc.style.height = hh + 'px'; sc.style.borderRadius = getComputedStyle(MODAL_HOST).borderRadius;
  m.style.setProperty('--sheet-max-w', Math.max(260, hw - 80) + 'px');
  m.style.maxHeight = Math.max(160, hh - 52 - 24) + 'px';
  m.style.left = Math.round(hx + (hw - m.offsetWidth) / 2) + 'px'; m.style.top = (hy + 52) + 'px';
}
function modalHead(title, sub) { return '<div class="mh"><div style="flex:1;min-width:0"><h2>' + title + '</h2>' + (sub ? '<div class="cap" style="margin-top:3px">' + sub + '</div>' : '') + '</div></div>'; }

/* dropdown menus: openDD(anchor, items, onPick, {keep, refresh, align}) — menu-bar menus hang from the bar, others open under
   the anchor and flip left / up when they would leave the stage */
let DD = null;
function openDD(anchor, items, onPick, opt) {
  opt = opt || {};
  const dd = $('#dd');
  const draw = (its) => { dd.innerHTML = its.map((it, i) => it.sep ? '<hr>' : it.h ? '<div class="h">' + esc(it.h) + '</div>' : '<button type="button" role="menuitem" data-i="' + i + '"' + (it.dis ? ' disabled' : '') + '><span class="ck">' + (it.on ? '✓' : '') + '</span><span>' + esc(it.t) + '</span>' + (it.k ? '<span class="k">' + esc(it.k) + '</span>' : it.sub ? '<span class="sub">▶</span>' : '') + '</button>').join(''); };
  draw(items);
  DD = { items, onPick, keep: opt.keep, refresh: opt.refresh, draw, anchor };
  dd.hidden = false;
  const r = anchor.getBoundingClientRect(), d = desk.getBoundingClientRect();
  const inBar = !!anchor.closest('.mbar');
  let left = Math.round(r.left - d.left), top = Math.round(r.bottom - d.top) + (inBar ? 1 : 4);
  const w = dd.offsetWidth, h = dd.offsetHeight;
  if (opt.align === 'right' || left + w > d.width - 8) left = Math.max(8, Math.round(r.right - d.left) - w);
  if (top + h > d.height - 8) top = Math.max(8, Math.round(r.top - d.top) - h - 4);
  dd.style.left = left + 'px'; dd.style.top = top + 'px';
  $$('.mbar button.on').forEach((b) => b.classList.remove('on'));
  if (inBar) anchor.classList.add('on');
}
function closeDD() { $('#dd').hidden = true; DD = null; $$('.mbar button.on').forEach((b) => b.classList.remove('on')); }
$('#dd').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-i]'); if (!b || !DD) return;
  const it = DD.items[+b.dataset.i]; const d = DD;
  if (!d.keep) closeDD();
  d.onPick(it.v, it, e);
  if (d.keep && DD === d && d.refresh) { d.items = d.refresh(); d.draw(d.items); }
});
function copyText(text, label) {
  const done = () => toast((label || '内容') + '已复制到剪贴板');
  const fail = () => { openModal(modalHead('手动复制', '浏览器拒绝了剪贴板访问，请选中下面的文字后复制') + '<div class="mb"><textarea id="copyArea" style="width:100%;min-height:200px;font:12px/1.5 var(--font-mono);border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--surface)">' + esc(text) + '</textarea></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>'); setTimeout(() => { const a = $('#copyArea'); if (a) a.select(); }, 30); };
  try { navigator.clipboard.writeText(text).then(done, fail); } catch (e) { fail(); }
}
/* notifications: 344px banners, slide in from the right (300ms, fades in while sliding), slide back out on dismiss (250ms);
   hovering keeps a banner alive; actions and the × appear on hover */
function noteDismiss(el) {
  if (!el || !el.isConnected || el.classList.contains('out')) return;
  el.classList.add('out');
  let done = false; const rm = () => { if (!done) { done = true; el.remove(); } };
  el.addEventListener('animationend', rm, { once: true }); setTimeout(rm, 400);
  if (typeof hudPlace === 'function') hudPlace();
}
function notify(n) {
  if (S.paused && !n.force) return;
  const box = $('#notes'); const id = 'n' + Math.random().toString(36).slice(2, 8);
  const el = document.createElement('div'); el.className = 'nt'; el.id = id; el.setAttribute('role', 'status');
  el.innerHTML = '<span class="appicon">' + APP_MARK + '</span><div style="min-width:0;display:flex;flex-direction:column;gap:1px"><div class="nt-t"><b>' + esc(n.t) + '</b><span class="cap" style="font-size:11px;flex:none">' + esc(n.when || '现在') + '</span></div><div class="nt-b">' + esc(n.b) + '</div>' +
    (n.a1 || n.a2 ? '<div class="nt-a">' + (n.a1 ? '<button type="button" class="btn sm p" data-act="noteAct" data-n="' + id + '" data-k="1">' + esc(n.a1) + '</button>' : '') + (n.a2 ? '<button type="button" class="btn sm" data-act="noteAct" data-n="' + id + '" data-k="2">' + esc(n.a2) + '</button>' : '') + '</div>' : '') +
    '</div><button type="button" class="nt-x" data-act="noteClose" data-n="' + id + '" aria-label="关闭通知">' + ic('x', 11) + '</button>';
  el._n = n; box.prepend(el);
  while (box.children.length > 3) box.lastChild.remove();
  if (typeof hudPlace === 'function') hudPlace();
  let hover = false; el.addEventListener('mouseenter', () => { hover = true; }); el.addEventListener('mouseleave', () => { hover = false; });
  const kill = () => { if (hover) { setTimeout(kill, 1500); return; } noteDismiss(el); };
  setTimeout(kill, n.ms || 7000);
}
