/* ============ ui plumbing ============ */
const desk = $('#desk');
function setTheme(t) {
  S.theme = t; store.set('theme', t);
  if (t === 'system') document.documentElement.removeAttribute('data-theme'); else document.documentElement.setAttribute('data-theme', t);
}
let TIPS = {};
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
  let x = ev.clientX + 14, y = ev.clientY + 16;
  if (x + w > window.innerWidth - 8) x = ev.clientX - w - 14;
  if (y + h > window.innerHeight - 8) y = ev.clientY - h - 14;
  t.style.left = Math.max(8, x) + 'px'; t.style.top = Math.max(8, y) + 'px';
}
function tipOff() { $('#tip').hidden = true; }
document.addEventListener('mouseover', (e) => { const el = e.target.closest('[data-tip],[data-tf]'); if (el) tipOn(el, e); else tipOff(); });
document.addEventListener('mousemove', tipMove);
document.addEventListener('focusin', (e) => { const el = e.target.closest('[data-tip],[data-tf]'); if (el) { const r = el.getBoundingClientRect(); tipOn(el, { clientX: r.left + r.width / 2, clientY: r.bottom }); } });
document.addEventListener('focusout', tipOff);

let toastTimer = null;
function toast(msg, opt) {
  opt = opt || {};
  const t = $('#toast'); clearInterval(toastTimer);
  let left = opt.sec || 0;
  const draw = () => { t.innerHTML = '<span>' + esc(msg) + '</span>' + (opt.act ? '<button type="button" data-act="toastAct">' + esc(opt.act) + (left ? ' · ' + left : '') + '</button>' : ''); };
  t.onAct = opt.onAct || null; draw(); t.hidden = false;
  let life = opt.sec ? opt.sec : 4;
  toastTimer = setInterval(() => { life--; if (opt.sec) { left = life; draw(); } if (life <= 0) { clearInterval(toastTimer); t.hidden = true; } }, 1000);
}
function openModal(html, cls) {
  const m = $('#modal'); m.className = 'modal' + (cls ? ' ' + cls : ''); m.innerHTML = html; m.hidden = false; $('#scrim').hidden = false;
  closeDD(); const f = m.querySelector('[autofocus],input,textarea,button.p,button'); if (f) setTimeout(() => f.focus(), 20);
}
function closeModal() { $('#modal').hidden = true; $('#scrim').hidden = true; $('#modal').innerHTML = ''; MODAL_KEY = null; }
let MODAL_KEY = null;
function modalHead(title, sub) { return '<div class="mh"><div style="flex:1;min-width:0"><h2>' + title + '</h2>' + (sub ? '<div class="cap" style="margin-top:4px">' + sub + '</div>' : '') + '</div><button type="button" class="ib" data-act="closeModal" aria-label="关闭">' + ic('x') + '</button></div>'; }
let DD = null;
function openDD(anchor, items, onPick, opt) {
  opt = opt || {};
  const dd = $('#dd');
  const draw = (its) => { dd.innerHTML = its.map((it, i) => it.sep ? '<hr>' : it.h ? '<div class="h">' + esc(it.h) + '</div>' : '<button type="button" role="menuitem" data-i="' + i + '"' + (it.dis ? ' disabled' : '') + '><span class="ck">' + (it.on ? '✓' : '') + '</span><span>' + esc(it.t) + '</span>' + (it.k ? '<span class="k">' + esc(it.k) + '</span>' : '') + '</button>').join(''); };
  draw(items);
  DD = { items, onPick, keep: opt.keep, refresh: opt.refresh, draw, anchor };
  dd.hidden = false;
  const r = anchor.getBoundingClientRect(), d = desk.getBoundingClientRect();
  let left = r.left - d.left; const top = r.bottom - d.top + 4;
  const w = dd.offsetWidth;
  if (left + w > d.width - 8) left = Math.max(8, d.width - w - 8);
  dd.style.left = left + 'px'; dd.style.top = top + 'px';
  $$('.mbar button.on').forEach((b) => b.classList.remove('on'));
  if (anchor.closest('.mbar')) anchor.classList.add('on');
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
  const fail = () => { openModal(modalHead('手动复制', '浏览器拒绝了剪贴板访问，请选中下面的文字后复制') + '<div class="mb"><textarea id="copyArea" style="width:100%;min-height:200px;font:12px/1.5 var(--mono);border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--surface)">' + esc(text) + '</textarea></div><div class="mf"><button type="button" class="btn p" data-act="closeModal">完成</button></div>'); setTimeout(() => { const a = $('#copyArea'); if (a) a.select(); }, 30); };
  try { navigator.clipboard.writeText(text).then(done, fail); } catch (e) { fail(); }
}
function notify(n) {
  if (S.paused && !n.force) return;
  const box = $('#notes'); const id = 'n' + Math.random().toString(36).slice(2, 8);
  const el = document.createElement('div'); el.className = 'nt'; el.id = id; el.setAttribute('role', 'status');
  el.innerHTML = '<span class="appicon"><svg width="22" height="16" viewBox="0 0 24 18" aria-hidden="true" fill="none" stroke="#f5f4f0" stroke-width="1.8"><circle cx="8.5" cy="9" r="6"/><circle cx="15.5" cy="9" r="6"/></svg></span><div style="min-width:0;display:flex;flex-direction:column;gap:2px"><div style="display:flex;gap:8px;align-items:baseline"><b style="flex:1;min-width:0;font-size:13px">' + esc(n.t) + '</b><span class="cap" style="font-size:11px">' + esc(n.when || '现在') + '</span></div><span style="font-size:12.5px;line-height:1.45;color:var(--ink-2)">' + esc(n.b) + '</span><div class="row" style="margin-top:6px;gap:6px">' + (n.a1 ? '<button type="button" class="btn sm p" data-act="noteAct" data-n="' + id + '" data-k="1">' + esc(n.a1) + '</button>' : '') + (n.a2 ? '<button type="button" class="btn sm" data-act="noteAct" data-n="' + id + '" data-k="2">' + esc(n.a2) + '</button>' : '') + '</div></div><button type="button" class="ib" data-act="noteClose" data-n="' + id + '" aria-label="关闭通知" style="width:22px;height:22px">' + ic('x', 12) + '</button>';
  el._n = n; box.prepend(el);
  while (box.children.length > 3) box.lastChild.remove();
  let hover = false; el.addEventListener('mouseenter', () => { hover = true; }); el.addEventListener('mouseleave', () => { hover = false; });
  const kill = () => { if (hover) { setTimeout(kill, 1500); return; } el.remove(); };
  setTimeout(kill, n.ms || 7000);
}

