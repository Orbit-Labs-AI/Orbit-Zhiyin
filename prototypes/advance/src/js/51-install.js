/* ============ install flow: preview → confirm → undo → 7-day tracking ============ */
let INST = null, LAST_INSTALL = null;
function instInfo(id, extra) {
  if (id && RECI[id]) { const r = RECI[id]; return { key: id, rec: r, title: r.title.split('：')[0], target: r.target, file: r.file, compat: r.compat, lib: extra ? extra.id : null }; }
  if (!extra) return null;
  if (id === '__studio') return { key: extra.id, rec: null, title: extra.title, target: extra.target, file: extra.file, compat: agent(S.studio.agent).name, lib: null, studio: true };
  const tgt = extra.kind === 'Hook' ? '~/.claude/settings.json' : extra.kind === '子代理' ? '~/.claude/agents/' + extra.id + '.md' : extra.kind === 'MCP' ? '~/.claude/mcp.json' : extra.kind === '插件' ? '~/.claude/plugins/' + extra.id + '/plugin.json' : '~/.claude/skills/' + extra.id + '/SKILL.md';
  return { key: extra.id, rec: null, title: extra.id, target: tgt, file: [['---', ' '], ['name: ' + extra.id, '+'], ['description: ' + extra.desc, '+'], ['source: ' + extra.src, '+'], ['---', ' ']], compat: extra.compat, lib: extra.id };
}
function openInstall(id, extra) {
  const info = instInfo(id, extra); if (!info) return;
  if (info.rec && S.installed.has(info.key)) { ACT.openRec({ dataset: { id: info.key, tab: 'track' } }); return; }
  INST = { info, step: 1, off: new Set(), codex: false };
  drawInstall();
}
function drawInstall() {
  const st = INST, f = st.info;
  const adds = f.file.filter((l, i) => (l[1] === '+' || l[1] === 'ai') && !st.off.has(i)).length;
  const dels = f.file.filter((l) => l[1] === '-').length;
  const name = f.target.split('/').pop();
  const steps = ['预览变更', '确认写入', '已安装'];
  const prog = '<div class="row" style="gap:6px;padding:12px 20px 0;flex-wrap:wrap">' + steps.map((s, i) => '<span class="row" style="gap:6px;font-size:12px;color:' + (i + 1 <= st.step ? 'var(--ink-1)' : 'var(--ink-3)') + ';font-weight:' + (i + 1 === st.step ? 600 : 400) + '"><span class="mono" style="width:18px;height:18px;border-radius:50%;display:grid;place-items:center;font-size:10px;background:' + (i + 1 < st.step ? 'var(--ink-1)' : i + 1 === st.step ? 'var(--ai-bg)' : 'var(--sunken)') + ';color:' + (i + 1 < st.step ? 'var(--surface)' : i + 1 === st.step ? 'var(--ai)' : 'var(--ink-3)') + '">' + (i + 1 < st.step ? '✓' : i + 1) + '</span>' + s + '</span>' + (i < 2 ? '<span style="width:16px;height:1px;background:var(--line)"></span>' : '')).join('') + '</div>';
  let html;
  if (st.step === 1) {
    const sc = $('#modal .code'); const top = sc ? sc.scrollTop : 0;
    html = modalHead('预览变更 · ' + esc(f.title), '将修改 1 个文件 · <b class="mono" style="color:var(--good)">+' + adds + ' 行</b>' + (dels ? ' · <b class="mono" style="color:var(--crit)">−' + dels + ' 行</b>' : '') + ' · 确认前不会改动任何文件') + prog +
      '<div class="mb col" style="gap:10px"><div class="row" style="padding:6px 10px;border-radius:8px;background:var(--sunken)">' + ic('file', 14) + '<span class="mono" style="font-size:12px;flex:1;min-width:0;word-break:break-all">' + esc(f.target) + '</span></div>' +
      '<div class="code" style="max-height:min(320px,42vh)">' + f.file.map((l, i) => { const can = l[1] === '+' || l[1] === 'ai'; const off = st.off.has(i); return '<div class="' + (l[1] === '+' && !off ? 'add' : l[1] === 'ai' && !off ? 'ai' : '') + '" style="grid-template-columns:34px 22px minmax(0,1fr);' + (l[1] === '-' ? 'background:var(--crit-bg)' : '') + '"><span class="n">' + (l[1] === '+' ? '+' : l[1] === '-' ? '−' : l[1] === 'ai' ? '✦' : i + 1) + '</span><span>' + (can ? '<input type="checkbox" data-chg="instLine" data-i="' + i + '"' + (off ? '' : ' checked') + ' aria-label="保留第 ' + (i + 1) + ' 行" style="margin:3px 0 0;accent-color:var(--ink-1)">' : '') + '</span><span class="t" style="' + (off ? 'text-decoration:line-through;opacity:.45' : l[1] === '-' ? 'text-decoration:line-through;color:var(--crit)' : '') + '">' + (esc(l[0]) || ' ') + '</span></div>'; }).join('') + '</div>' +
      '<div class="cap" style="font-size:11.5px">每一行新增都可以取消勾选。' + (f.key === 'ro-allow' ? '含写操作的前缀（git push、gh pr merge、rm）已排除，永远不会出现在可选列表里。' : '紫色 ✦ 行是按你的会话改写的内容。') + '</div></div>' +
      '<div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="instNext" autofocus' + (adds || dels ? '' : ' disabled') + '>下一步</button></div>';
    openModal(html, 'wide'); MODAL_KEY = 'install';
    const nc = $('#modal .code'); if (nc) nc.scrollTop = top;
    return;
  }
  const bk = '…/Tandem/backups/' + name + '.1001-' + nowText().slice(-5).replace(':', '');
  const codexOk = /Codex|所有/.test(f.compat || '');
  html = modalHead('写入 ' + esc(name) + '？', '修改前会自动备份，随时可以撤销') + prog +
    '<div class="mb col" style="gap:12px"><div class="form" style="grid-template-columns:52px minmax(0,1fr);gap:8px 12px"><span class="l">写入</span><span class="mono" style="font-size:12px;word-break:break-all">' + esc(f.target) + '</span><span class="l">备份</span><span class="mono" style="font-size:12px;color:var(--ink-3);word-break:break-all">' + esc(bk) + '</span><span class="l">变更</span><span class="mono" style="font-size:12px">+' + adds + (dels ? ' / −' + dels : '') + ' 行</span></div>' +
    (codexOk ? '<label class="row" style="align-items:flex-start;gap:8px;padding:10px 12px;border-radius:9px;border:1px solid var(--line)"><input type="checkbox" data-chg="instCodex"' + (st.codex ? ' checked' : '') + ' style="margin-top:2px;accent-color:var(--ink-1)"><span class="col" style="gap:2px"><b style="font-size:12.5px">同时应用到 Codex</b><span class="cap" style="font-size:11.5px">写入 ~/.codex/config.toml 的等价配置。默认只改当前 Agent。</span></span></label>' : '') +
    '<div class="row cap" style="font-size:11.5px;align-items:flex-start">' + ic('info', 13, 'margin-top:2px') + '<span>这是整个流程里唯一真正写盘的一步（Demo 中只是模拟）。写入后 10 秒内可直接撤销，之后在建议卡与历史产物里撤销。</span></div></div>' +
    '<div class="mf"><button type="button" class="btn gh" data-act="instBack">返回</button><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="instDo" autofocus>确认写入</button></div>';
  openModal(html, 'wide'); MODAL_KEY = 'install';
}
function undoInstall(f) {
  f = f || LAST_INSTALL;
  if (!f) { toast('没有可以撤销的安装'); return; }
  if (f.rec) S.installed.delete(f.key);
  if (f.lib) S.libInst.delete(f.lib);
  S.history.unshift({ t: '撤销 ' + f.title, when: '刚刚' }); LAST_INSTALL = null;
  render(); toast('已撤销「' + f.title + '」，文件已从备份恢复');
}
Object.assign(ACT, {
  instLine: (el) => { const i = +el.dataset.i; if (el.checked) INST.off.delete(i); else INST.off.add(i); drawInstall(); },
  instNext: () => { INST.step = 2; drawInstall(); },
  instBack: () => { INST.step = 1; drawInstall(); },
  instCodex: (el) => { INST.codex = el.checked; },
  instDo: () => {
    const f = INST.info, codex = INST.codex; closeModal();
    if (f.rec) S.installed.set(f.key, { days: 1, codex, at: Date.now() });
    if (f.lib) S.libInst.add(f.lib);
    S.history.unshift({ t: '安装 ' + f.title + (codex ? '（含 Codex）' : ''), when: '刚刚' });
    LAST_INSTALL = f; render();
    toast('已应用「' + f.title + '」' + (f.rec ? '，开始 7 天效果追踪' : ''), { act: '撤销', sec: 10, onAct: () => undoInstall(f) });
  }
});

