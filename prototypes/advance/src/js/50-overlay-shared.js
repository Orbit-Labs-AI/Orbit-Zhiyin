/* ============ shared bits for overlays ============ */
S.attn = new Set(); S.numOnly = false; S.login = false; S.weekly = true; S.shareDark = true; S.shareNoNum = false;
S.rep = new Set(['ov', 'persona', 'proj', 'fric', 'recs']); S.addSrc = false; S.addSrcFmt = 'jsonl'; S.ruleTest = false;
S.rules['自定义正则 2 条'] = true;
S.ruleSample = 'cd /Users/alex/Projects/demo && git push\n联系 alex@example.com，token = sk-demo-0000aaaa1111\n服务器 192.168.1.20，构建机 build-01.local\n电话 13800001234，内部代号-X7，工号 004213';
// HUD defaults: snapped top-right under the menu bar; hudPlace() moves it off the main window until the user drags it (user:true)
Object.assign(S.hud, { snap: 'tr', tipOff: false, user: false }, (() => { const v = store.get('hud', null); return v && typeof v === 'object' ? v : {}; })());
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
const kb = (s) => IS_MAC ? s : s.replace(/⌘/g, 'Ctrl+').replace(/⌥/g, 'Alt+').replace(/⌃/g, 'Ctrl+').replace(/⇧/g, 'Shift+');
const isDark = () => S.theme === 'dark' || (S.theme === 'system' && !!window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
function swBtn(on, act, attrs, label) { return '<button type="button" class="sw' + (on ? ' on' : '') + '" role="switch" aria-checked="' + !!on + '" aria-label="' + esc(label || '') + '" data-act="' + act + '"' + (attrs || '') + '></button>'; }
const FIELD = 'height:30px;border-radius:7px;border:1px solid var(--line);background:var(--surface);padding:0 9px;font-size:13px;color:var(--ink-1);width:100%;min-width:0';
const LIVE_ID = 'sess-1001-1512';
const HUD_TOOLS = ['Edit Main.dc.html', 'Read Sessions.dc.html', 'Bash node lint.js', 'Edit orbit-demo.html', 'Read canvas.json', 'Bash git status'];
let HUD_T = 0, OVL = null, SIMT = null, ASKT = null;

// page guide (「这页回答」, inserted by 37-motion.js's render hook, which runs before this one): the full sentence is also its
// tooltip, so the line can stay one short row — on narrow content columns the 「先看 …」 half is hidden (90-responsive.css)
RENDER_HOOKS.push((m) => { const t = m.querySelector('.pg-guide-t'); if (t && !t.dataset.tip) t.dataset.tip = t.textContent.replace(/^这页回答/, '这页回答：'); });

// #modal is role=dialog + aria-modal: name it after its sheet title (the palette, which has none, is「命令面板」), and when a
// sheet closes with nothing to return to (opened from a host command while <body> had the focus), the keyboard continues in
// the settings window if it is the key window, else on the page title, instead of falling back to <body>.
{
  const baseOpen = openModal, baseClose = closeModal;
  openModal = function (html, cls) {
    baseOpen(html, cls);
    const m = $('#modal'); const h = m.querySelector('.mh h2');
    if (h) { h.id = 'modalTitle'; m.setAttribute('aria-labelledby', 'modalTitle'); m.removeAttribute('aria-label'); }
    else { m.removeAttribute('aria-labelledby'); m.setAttribute('aria-label', /\bpal\b/.test(cls || '') ? '命令面板' : '对话框'); }
  };
  closeModal = function () {
    const was = !$('#modal').hidden;
    baseClose();
    if (!was) return;
    $('#modal').removeAttribute('aria-labelledby'); $('#modal').removeAttribute('aria-label');
    const a = document.activeElement; if (a && a !== document.body && a.isConnected) return;
    if (!$('#set').hidden && S.keyWin === 'set' && typeof setFocusIn === 'function') { setFocusIn(); return; }
    const t = $('#main .tbar h1'); if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }
  };
}
