/* ============ shared bits for overlays ============ */
S.attn = new Set(); S.numOnly = false; S.login = true; S.weekly = true; S.shareDark = true; S.shareNoNum = false;
S.rep = new Set(['ov', 'persona', 'proj', 'fric', 'recs']); S.addSrc = false; S.addSrcFmt = 'jsonl'; S.ruleTest = false;
S.rules['自定义正则 2 条'] = true;
S.ruleSample = 'cd /Users/alex/Projects/demo && git push\n联系 alex@example.com，token = sk-demo-0000aaaa1111\n服务器 192.168.1.20，构建机 build-01.local\n电话 13800001234，内部代号-X7，工号 004213';
Object.assign(S.hud, { snap: 'br', tipOff: false }, (() => { const v = store.get('hud', null); return v && typeof v === 'object' ? v : {}; })());
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
const kb = (s) => IS_MAC ? s : s.replace(/⌘/g, 'Ctrl+').replace(/⌥/g, 'Alt+').replace(/⌃/g, 'Ctrl+').replace(/⇧/g, 'Shift+');
const isDark = () => S.theme === 'dark' || (S.theme === 'system' && !!window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
function swBtn(on, act, attrs, label) { return '<button type="button" class="sw' + (on ? ' on' : '') + '" role="switch" aria-checked="' + !!on + '" aria-label="' + esc(label || '') + '" data-act="' + act + '"' + (attrs || '') + '></button>'; }
const FIELD = 'height:30px;border-radius:7px;border:1px solid var(--line);background:var(--surface);padding:0 9px;font-size:12.5px;color:var(--ink-1);width:100%;min-width:0';
const LIVE_ID = 'sess-1001-1512';
const HUD_TOOLS = ['Edit Main.dc.html', 'Read Sessions.dc.html', 'Bash node lint.js', 'Edit tandem-demo.html', 'Read canvas.json', 'Bash git status'];
let HUD_T = 0, OVL = null, SIMT = null, ASKT = null;

