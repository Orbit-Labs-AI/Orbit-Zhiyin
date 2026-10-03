/* ============ install flow: preview → confirm → written (undo countdown) → 7-day tracking ============ */
// INST is the open sheet; LAST_INSTALL the one ⌘Z / the toast can still undo; S.instLog the install / undo records
// (kept apart from S.history so the studio's 历史产物 stays studio-only, BUG-86); S.libInst the library items installed.
let INST = null, LAST_INSTALL = null, UNDO_T = 0;
S.instLog = S.instLog || [];
S.libInst = S.libInst || new Set();
const UNDO_SEC = 10;
// What a library item writes when installed on its own (BUG-28: a library item used to preview and write its *related*
// recommendation, so cloudflare-deploy wrote Confluo/AGENTS.md and marked release-verifier installed).
function libFile(x) {
  const k = x.kind;
  if (k === 'Hook') return { target: '~/.claude/settings.json', file: [['{', ' '], ['  "hooks": {', ' '], ['    "PreToolUse": [', ' '], ['      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "~/.claude/hooks/' + x.id + '.sh" }] }', '+'], ['    ]', ' '], ['  }', ' '], ['}', ' ']] };
  if (k === 'MCP') return { target: '~/.claude.json · mcpServers', file: [['{', ' '], ['  "mcpServers": {', ' '], ['    "' + x.id + '": {', '+'], ['      "command": "npx",', '+'], ['      "args": ["-y", "@orbit/' + x.id + '"]', '+'], ['    }', '+'], ['  }', ' '], ['}', ' ']] };
  if (k === '插件') return { target: '~/.claude/plugins/' + x.id + '/plugin.json', file: [['{', '+'], ['  "name": "' + x.id + '",', '+'], ['  "description": "' + x.desc + '",', '+'], ['  "source": "' + x.src + '",', '+'], ['  "commands": ["' + x.id.replace(/-.*$/, '') + '"]', '+'], ['}', '+']] };
  if (k === '子代理') return { target: '~/.claude/agents/' + x.id + '.md', file: [['---', '+'], ['name: ' + x.id, '+'], ['description: ' + x.desc, '+'], ['tools: Read, Grep, Bash(curl:*)', '+'], ['---', '+'], ['', '+'], ['你是独立的检查者：只读，不修改仓库；结果用表格汇报。', '+']] };
  return { target: '~/.claude/skills/' + x.id + '/SKILL.md', file: [['---', '+'], ['name: ' + x.id, '+'], ['description: ' + x.desc, '+'], ['source: ' + x.src, '+'], ['---', '+'], ['', '+'], ['# ' + x.id, '+'], ['', '+'], ['触发时按以下顺序执行，每步完成后汇报再继续。', 'ai']] };
}
function instInfo(id, extra) {
  if (id && RECI[id] && !(extra && extra.kind)) {
    const r = RECI[id]; const proj = S.recs.scope === 'proj' && recScoped(r);   // the chosen scope travels with the install (BUG-22)
    return { key: id, rec: r, title: r.title.split('：')[0], target: recTarget(r), file: r.file, compat: r.compat, lib: null, scope: proj ? 'proj' : 'global', scopeName: proj ? scopeProjName() : null };
  }
  if (!extra) return null;
  if (id === '__studio') return { key: extra.id, rec: null, title: extra.title, target: extra.target, file: extra.file, compat: agent(S.studio.agent).name, lib: null, studio: true, scope: 'global' };
  const f = libFile(extra);
  return { key: extra.id, rec: null, title: extra.id, target: f.target, file: f.file, compat: extra.compat, lib: extra.id, scope: 'global' };
}
const instDone = (info) => (info.rec && S.installed.has(info.key)) || (info.lib && S.libInst.has(info.lib)) || (info.studio && S.libInst.has('studio:' + info.key));
function openInstall(id, extra) {
  const info = instInfo(id, extra); if (!info) return;
  // Recs whose primary action is not an install never land here as an install (BUG-25: ⌘↩ used to "install" a tutorial).
  if (info.rec && !(extra && extra.kind)) { const p = info.rec.primary; const alt = /教程/.test(p) ? 'tutorial' : /复制/.test(p) ? 'copyRec' : /交给/.test(p) ? 'recToStudio' : null; if (alt) { ACT[alt]({ dataset: { id } }); return; } }
  if (instDone(info)) { if (info.rec) ACT.openRec({ dataset: { id: info.key, tab: 'track' } }); else toast('「' + info.title + '」已经安装'); return; }   // BUG-37: no second install
  INST = { info, step: 1, off: new Set(), codex: false, t: Date.now() };
  drawInstall();
}
const instBusy = () => !INST || Date.now() - INST.t < 400;   // a double click must not advance two steps or fall through to the page (BUG-64 / BUG-88)
// The second click of a double click lands wherever the redrawn sheet is not — usually the scrim, which would close it.
// Capture-phase on the document runs before the scrim's own listener (30-actions.js), so it can be swallowed here.
document.addEventListener('click', (e) => { if (e.target && e.target.id === 'scrim' && MODAL_KEY === 'install' && INST && Date.now() - INST.t < 400) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
function drawInstall() {
  const st = INST, f = st.info;
  const adds = f.file.filter((l, i) => (l[1] === '+' || l[1] === 'ai') && !st.off.has(i)).length;
  const dels = f.file.filter((l) => l[1] === '-').length;
  const name = f.target.split('/').pop();
  const steps = ['预览变更', '确认写入', '已写入', '7 天追踪'];
  const prog = '<div class="inst-steps">' + steps.map((s, i) => '<span class="' + (i + 1 < st.step ? 'done' : i + 1 === st.step ? 'cur' : '') + '"><span class="mono k">' + (i + 1 < st.step ? '✓' : i + 1) + '</span>' + s + '</span>' + (i < steps.length - 1 ? '<i></i>' : '')).join('') + '</div>';
  const scopeLine = f.scope === 'proj' ? '<span class="tag">仅 ' + esc(f.scopeName) + '</span>' : f.rec && recScoped(f.rec) ? '<span class="tag">全局</span>' : '';
  let html;
  if (st.step === 1) {
    const sc = $('#modal .code'); const top = sc ? sc.scrollTop : 0;
    html = modalHead('预览变更 · ' + esc(f.title), '将修改 1 个文件 · <b class="mono" style="color:var(--good)">+' + adds + ' 行</b>' + (dels ? ' · <b class="mono" style="color:var(--crit)">−' + dels + ' 行</b>' : '') + ' · 确认前不会改动任何文件') + prog +
      '<div class="mb col" style="gap:10px"><div class="row" style="padding:6px 10px;border-radius:8px;background:var(--sunken)">' + ic('file', 14) + '<span class="mono" style="font-size:12px;flex:1;min-width:0;word-break:break-all">' + esc(f.target) + '</span>' + scopeLine + '</div>' +
      '<div class="code" style="max-height:min(320px,42vh)">' + f.file.map((l, i) => { const can = l[1] === '+' || l[1] === 'ai'; const off = st.off.has(i); return '<div class="' + (l[1] === '+' && !off ? 'add' : l[1] === 'ai' && !off ? 'ai' : '') + '" style="grid-template-columns:34px 22px minmax(0,1fr);' + (l[1] === '-' ? 'background:var(--crit-bg)' : '') + '"><span class="n">' + (l[1] === '+' ? '+' : l[1] === '-' ? '−' : l[1] === 'ai' ? '✦' : i + 1) + '</span><span>' + (can ? '<input type="checkbox" data-chg="instLine" data-i="' + i + '"' + (off ? '' : ' checked') + ' aria-label="保留第 ' + (i + 1) + ' 行" style="margin:3px 0 0;accent-color:var(--ink-1)">' : '') + '</span><span class="t" style="' + (off ? 'text-decoration:line-through;opacity:.45' : l[1] === '-' ? 'text-decoration:line-through;color:var(--crit)' : '') + '">' + (esc(l[0]) || ' ') + '</span></div>'; }).join('') + '</div>' +
      '<div class="cap" style="font-size:11px">每行新增都可取消勾选 · ' + (f.key === 'ro-allow' ? '写操作前缀（git push、gh pr merge、rm）已排除' : '紫色 ✦ 行按你的会话改写') + '</div></div>' +
      '<div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="instNext" autofocus' + (adds || dels ? '' : ' disabled') + '>下一步</button></div>';
    openModal(html, 'wide'); MODAL_KEY = 'install';
    const nc = $('#modal .code'); if (nc) nc.scrollTop = top;
    return;
  }
  const bk = st.bk || ('…/Orbit/backups/' + name + '.1001-' + nowText().slice(-5).replace(':', ''));
  const codexOk = /Codex|所有/.test(f.compat || '');
  const facts = '<div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:8px 12px"><span class="l">写入</span><span class="mono row" style="font-size:12px;word-break:break-all;flex-wrap:wrap">' + esc(f.target) + scopeLine + '</span><span class="l">备份</span><span class="mono" style="font-size:12px;color:var(--ink-3);word-break:break-all">' + esc(bk) + '</span><span class="l">变更</span><span class="mono" style="font-size:12px">+' + adds + (dels ? ' / −' + dels : '') + ' 行' + (st.codex ? ' · 含 Codex 等价配置' : '') + '</span></div>';
  if (st.step === 2) {
    html = modalHead('写入 ' + esc(name) + '？', '修改前会自动备份，随时可以撤销') + prog +
      '<div class="mb col" style="gap:12px">' + facts +
      (codexOk ? '<label class="row" style="align-items:flex-start;gap:8px;padding:10px 12px;border-radius:9px;border:1px solid var(--line)"><input type="checkbox" data-chg="instCodex"' + (st.codex ? ' checked' : '') + ' style="margin-top:2px;accent-color:var(--ink-1)"><span class="col" style="gap:2px"><b style="font-size:13px">同时应用到 Codex</b><span class="cap" style="font-size:11px">写入 ~/.codex/config.toml 的等价配置。默认只改当前 Agent。</span></span></label>' : '') +
      '<div class="row cap" style="font-size:11px;align-items:flex-start">' + ic('info', 13, 'margin-top:2px') + '<span>这是整个流程里唯一真正写盘的一步（Demo 中只是模拟）。写入后 ' + UNDO_SEC + ' 秒内可直接撤销，之后在建议卡与「已安装」里撤销。</span></div></div>' +
      '<div class="mf"><button type="button" class="btn gh" data-act="instBack">返回</button><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="instDo" autofocus>确认写入</button></div>';
    openModal(html, 'wide'); MODAL_KEY = 'install';
    return;
  }
  // step 3: written. The undo countdown lives here while the sheet is open and moves to the toast when it closes.
  const left = Math.max(0, UNDO_SEC - Math.floor((Date.now() - st.at) / 1000));
  html = modalHead('已写入 ' + esc(name), '备份在 ' + esc(bk) + '，' + (left ? left + ' 秒内可直接撤销' : '撤销已转到建议卡与「已安装」')) + prog +
    '<div class="mb col" style="gap:12px">' + facts +
    '<div class="inst-undo' + (left ? '' : ' off') + '"><span class="row" style="gap:8px">' + ic(left ? 'undo' : 'okc', 14) + '<span style="font-size:13px"><b>' + (left ? '撤销倒计时' : '已生效') + '</b><span class="cap" style="margin-left:8px">' + (left ? '倒计时结束后文件保留，仍可在建议卡撤销' : '文件已保留，随时可从备份恢复') + '</span></span><span style="flex:1"></span><b class="mono" id="instLeft">' + (left ? left + ' s' : '') + '</b></span><span class="bar" aria-hidden="true"><i id="instBar" style="width:' + Math.round(left / UNDO_SEC * 100) + '%;transition:width 1s linear"></i></span></div>' +
    (f.rec ? '<div class="row" style="gap:8px;padding:10px 12px;border-radius:9px;background:var(--sunken);font-size:13px;align-items:flex-start">' + ic('clock', 14, 'margin-top:2px') + '<span><b>7 天效果追踪已开始</b><span class="cap" style="display:block;margin-top:2px">安装前 7 天作为基准（' + recX(f.key).n[0] + ' 个会话），满 7 天后逐项对比：' + f.rec.track.map((t) => t[0]).join('、') + '。</span></span></div>' : '') + '</div>' +
    '<div class="mf"><button type="button" class="btn" data-act="instUndo"' + (left ? '' : ' disabled') + '>撤销</button><span style="flex:1"></span>' + (f.rec ? '<button type="button" class="btn" data-act="instTrack" data-id="' + f.key + '">查看效果追踪</button>' : '') + '<button type="button" class="btn p" data-act="instClose" autofocus>完成</button></div>';
  openModal(html, 'wide'); MODAL_KEY = 'install';
}
function instTick() {
  clearInterval(UNDO_T); UNDO_T = 0;
  UNDO_T = setInterval(() => {
    if (!INST || INST.step !== 3 || MODAL_KEY !== 'install') { clearInterval(UNDO_T); UNDO_T = 0; return; }
    const left = Math.max(0, UNDO_SEC - Math.floor((Date.now() - INST.at) / 1000));
    const n = $('#instLeft'), b = $('#instBar'); if (n) n.textContent = left ? left + ' s' : ''; if (b) b.style.width = Math.round(left / UNDO_SEC * 100) + '%';
    if (!left) { clearInterval(UNDO_T); UNDO_T = 0; drawInstall(); }
  }, 1000);
}
// Removes an install (undo toast, ⌘Z, 撤销 on the card). Clears the pending undo when it is the same install (BUG-24).
function uninstallRec(id) {
  S.installed.delete(id);
  if (LAST_INSTALL && LAST_INSTALL.rec && LAST_INSTALL.key === id) LAST_INSTALL = null;
  const r = RECI[id]; S.instLog.unshift({ t: '撤销 ' + (r ? r.title.split('：')[0] : id), when: '刚刚' });
}
function undoInstall(f) {
  f = f || LAST_INSTALL;
  if (!f || !instDone(f)) { toast('没有可以撤销的安装'); return; }
  if (f.rec) { uninstallRec(f.key); } else { if (f.lib) S.libInst.delete(f.lib); if (f.studio) S.libInst.delete('studio:' + f.key); S.instLog.unshift({ t: '撤销 ' + f.title, when: '刚刚' }); }
  if (LAST_INSTALL === f) LAST_INSTALL = null;
  render(); toast('已撤销「' + f.title + '」，文件已从备份恢复');
}
Object.assign(ACT, {
  instLine: (el) => { const i = +el.dataset.i; if (el.checked) INST.off.delete(i); else INST.off.add(i); drawInstall(); },
  instNext: () => { if (instBusy() || INST.step !== 1) return; INST.step = 2; INST.t = Date.now(); drawInstall(); },
  instBack: () => { if (instBusy() || INST.step !== 2) return; INST.step = 1; INST.t = Date.now(); drawInstall(); },
  instCodex: (el) => { INST.codex = el.checked; },
  instDo: () => {
    if (instBusy() || INST.step !== 2) return;
    const st = INST, f = st.info, codex = st.codex;
    if (f.rec) S.installed.set(f.key, { days: 1, codex, at: Date.now(), scope: f.scope, target: f.target, off: st.off.size });
    if (f.lib) S.libInst.add(f.lib);
    if (f.studio) S.libInst.add('studio:' + f.key);
    S.instLog.unshift({ t: '安装 ' + f.title + (codex ? '（含 Codex）' : '') + (f.scope === 'proj' ? '（仅 ' + f.scopeName + '）' : ''), when: '刚刚', target: f.target });
    LAST_INSTALL = f; st.step = 3; st.at = Date.now(); st.t = Date.now(); st.bk = '…/Orbit/backups/' + f.target.split('/').pop() + '.1001-' + nowText().slice(-5).replace(':', '');
    renderMain(); drawInstall(); instTick();
  },
  instUndo: () => { if (instBusy()) return; const f = INST.info; closeModal(); INST = null; undoInstall(f); },
  instTrack: (el) => { if (instBusy()) return; const f = INST.info; const left = Math.max(0, UNDO_SEC - Math.floor((Date.now() - INST.at) / 1000)); closeModal(); INST = null; ACT.openRec({ dataset: { id: el.dataset.id, tab: 'track' } }); if (left) toast('已应用「' + f.title + '」，开始 7 天效果追踪', { act: '撤销', sec: left, onAct: () => undoInstall(f) }); },
  instClose: () => {
    if (instBusy()) return;
    const f = INST.info; const left = Math.max(0, UNDO_SEC - Math.floor((Date.now() - INST.at) / 1000)); closeModal(); INST = null; render();
    toast('已应用「' + f.title + '」' + (f.rec ? '，开始 7 天效果追踪' : ''), left ? { act: '撤销', sec: left, onAct: () => undoInstall(f) } : {});
  }
});
