/* ============ onboarding & reveal (overlay) ============ */
let OB = null, REV = null;
function closeOverlay() {
  const o = $('#overlay'); o.hidden = true; o.innerHTML = '';
  if (OB) OB.timers.forEach(clearTimeout);
  if (REV) REV.timers.forEach(clearTimeout);
  OVL = null;
}
function obFacts() {
  const L = sel({ range: 0, noExtra: true }); const st = stats(L);
  const hc = new Array(24).fill(0); L.forEach((s) => { hc[s.h] += s.msgs; });
  let bh = 0; hc.forEach((v, h) => { if (v > hc[bh]) bh = h; });
  const byA = AG.map((a) => [a, sum(L.filter((s) => s.a === a.id), (s) => s.dur)]).sort((x, y) => y[1] - x[1]);
  const fr = Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]);
  return [
    ['统计', fmt(L.length) + ' 个会话 · ' + fmt(st.tools) + ' 次工具调用', '你最常在 ' + bh + ':00–' + (bh + 1) + ':00 和 Agent 协作'],
    ['轨迹', '还原每个会话的时间线', byA[0][0].name + ' 占你协作时长的 ' + Math.round(byA[0][1] / Math.max(1, st.hours * 60) * 100) + '%'],
    ['语义', '本地 Agent 正在归类你的消息', '摩擦最多的是「' + (fr[0] ? fr[0][0] : '—') + '」'],
    ['人格', '四个维度', '你在 ' + Math.round(st.verify) + '% 的会话里要求验证结果']
  ];
}
function openOnboarding(step) {
  closeModal(); closeDD(); closeOverlay();
  OB = { step: step || 0, src: new Set(AG.map((a) => a.id).filter((id) => !S.srcOff.has(id))), recent: true, prog: -1, timers: [] };
  OVL = 'ob'; $('#overlay').hidden = false; drawOB();
}
function drawOB() {
  const s = OB.step;
  const dots = '<div class="ob-dots" aria-hidden="true">' + [0, 1, 2, 3].map((i) => '<i class="' + (i <= s ? 'on' : '') + '"></i>').join('') + '</div>';
  const top = '<div class="row">' + dots + '<span class="mono cap" style="font-size:11px">' + (s + 1) + ' / 4</span><span style="flex:1"></span>' + (s < 3 ? '<button type="button" class="btn sm gh" data-act="obClose">跳过</button>' : '') + '</div>';
  let b = '';
  if (s === 0) {
    b = '<span class="appicon" style="width:56px;height:56px;border-radius:14px"><svg width="32" height="24" viewBox="0 0 24 18" aria-hidden="true" fill="none" stroke="#f5f4f0" stroke-width="1.8"><circle cx="8.5" cy="9" r="6"/><circle cx="15.5" cy="9" r="6"/></svg></span><div><div class="eb">Tandem</div><h2 class="serif" style="margin:4px 0 0;font-size:28px;line-height:1.2">看见你和 Agent 怎么协作</h2></div><p style="margin:0;font-size:13.5px;line-height:1.6;color:var(--ink-2)">没有注册，也没有账号。Tandem 读取本机各个 Agent 的会话日志，告诉你协作习惯、卡点和下一步该装什么。四步里只有一次需要你做决定：分析哪些数据。</p>' +
      [['eye', '只读本地日志', '不碰凭据文件，也不需要「完全磁盘访问」'], ['shield', '数据不出本机', '0 B 上传；匿名贡献默认关闭'], ['bot', '不调用云端模型', '语义分析交给你自己的本地 Agent']].map((x) => '<div class="row" style="align-items:flex-start;gap:10px">' + ic(x[0], 18, 'margin-top:1px') + '<span class="col" style="gap:1px"><b style="font-size:13px">' + x[1] + '</b><span class="cap">' + x[2] + '</span></span></div>').join('') +
      '<div class="row" style="justify-content:space-between;margin-top:6px"><button type="button" class="lnk" data-act="obPrivacy">完整隐私说明</button><button type="button" class="btn p" data-act="obNext" style="height:32px;padding:0 18px">开始</button></div>';
  } else if (s === 1) {
    const tot = AG.filter((a) => OB.src.has(a.id)).reduce((x, a) => x + a.all, 0);
    b = '<div><h2 class="serif" style="margin:0;font-size:24px">找到了这些 Agent 的会话</h2><p class="cap" style="margin:6px 0 0">只读取会话日志。取消勾选的来源不会被索引。</p></div><div class="card" style="padding:2px 0">' +
      AG.map((a) => '<label class="srcrow"><span style="width:30px;height:30px;border-radius:8px;background:' + a.t + ';display:grid;place-items:center">' + ic('term', 15, 'color:' + a.c) + '</span><span style="min-width:0"><b style="font-size:13px">' + a.name + '</b><span class="mono cap" style="display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + a.path + '</span></span><span class="mono cap" style="font-size:11.5px">' + fmt(a.all) + '</span><input type="checkbox" data-chg="obSrc" data-a="' + a.id + '"' + (OB.src.has(a.id) ? ' checked' : '') + ' aria-label="分析 ' + a.name + '" style="width:16px;height:16px;accent-color:var(--ink-1)"></label>').join('') +
      '<div class="srcrow" style="opacity:.6"><span style="width:30px;height:30px;border-radius:8px;background:var(--sunken);display:grid;place-items:center">' + ic('minus', 15) + '</span><span><b style="font-size:13px">Cursor</b><span class="cap" style="display:block;font-size:11px">未检测到 · 可稍后在设置中手动指定</span></span><span></span><span></span></div></div>' +
      '<div class="row" style="align-items:flex-start;gap:10px">' + swBtn(OB.recent, 'obRecent', '', '只分析最近 90 天') + '<span class="col" style="gap:2px"><b style="font-size:12.5px">只分析最近 90 天</b><span class="cap" style="font-size:11.5px">首次约 40 秒；之后可以在设置中扩展到全部历史</span></span></div><div class="mono cap" style="font-size:11.5px">共 ' + fmt(tot) + ' 个会话 · 最早 2025-11-03</div>' +
      '<div class="row" style="justify-content:space-between"><button type="button" class="btn gh" data-act="obBack">返回</button><button type="button" class="btn p" data-act="obStart" style="height:32px;padding:0 18px"' + (OB.src.size ? '' : ' disabled') + '>开始分析</button></div>';
  } else if (s === 2) {
    const F = obFacts();
    b = '<div><h2 class="serif" style="margin:0;font-size:24px">正在建立你的协作画像</h2><p class="cap" style="margin:6px 0 0">每完成一步就先给你看结果，不用等到最后。</p></div><div style="height:4px;border-radius:2px;background:var(--line)"><div style="height:4px;border-radius:2px;background:var(--ink-1);width:' + ((OB.prog + 1) / 4 * 100) + '%;transition:width .4s"></div></div><div class="col" style="gap:0">' +
      F.map((f, i) => { const st = i <= OB.prog ? 'done' : i === OB.prog + 1 ? 'run' : 'todo'; return '<div class="step"><span class="mk" style="background:' + (st === 'done' ? 'var(--ink-1)' : st === 'run' ? 'var(--ai-bg)' : 'var(--surface)') + ';color:' + (st === 'done' ? 'var(--surface)' : 'var(--ink-3)') + ';box-shadow:' + (st === 'todo' ? 'inset 0 0 0 1.5px var(--line)' : 'none') + '">' + (st === 'done' ? '✓' : st === 'run' ? '<span class="spin" style="width:12px;height:12px"></span>' : i + 1) + '</span><div><div style="font-size:12.5px;font-weight:600;color:' + (st === 'todo' ? 'var(--ink-3)' : 'var(--ink-1)') + '">' + f[0] + '</div><div class="cap" style="font-size:11.5px">' + f[1] + '</div></div><span></span></div>'; }).join('') +
      '</div><div class="col" style="gap:6px;min-height:96px"><span class="eb">已经知道的</span>' + F.filter((f, i) => i <= OB.prog).map((f) => '<div class="row fade" style="font-size:12.5px;align-items:flex-start">' + ic('check', 14, 'color:var(--good);margin-top:2px') + '<span>' + esc(f[2]) + '</span></div>').join('') + (OB.prog < 0 ? '<span class="cap">第一条结果马上出来…</span>' : '') + '</div>' +
      '<div class="row" style="justify-content:space-between;flex-wrap:wrap"><span class="cap" style="font-size:11.5px">可以关闭窗口，完成后通知你</span><button type="button" class="btn" data-act="obBg">在后台继续</button></div>';
  } else {
    const p = personaNow(); const vr = visibleRecs();
    b = '<div class="col" style="align-items:center;text-align:center;gap:6px">' + (p.ok ? glyphSVG(p, 92) : '') + '<span class="eb">你的协作人格</span><div class="serif" style="font-size:56px;font-weight:600;line-height:1;letter-spacing:.03em">' + (p.ok ? p.code : '—') + '</div><div class="serif" style="font-size:20px;font-weight:600">' + (p.ok ? p.zh + ' <i style="font-weight:400;font-size:15px;color:var(--ink-3)">' + p.en + '</i>' : '样本不足') + '</div><p style="margin:0;font-size:13px;line-height:1.6;color:var(--ink-2);max-width:380px">' + esc(p.ok ? p.line : '已选来源的会话少于 30 个，先用一段时间再来看。') + '</p></div>' +
      '<div class="col" style="gap:8px">' + [['看看优化建议', vr.length + ' 条，其中 ' + vr.filter((r) => r.lvl === 1).length + ' 条可以一键应用'], ['打开悬浮组件', kb('⌥⌘P') + ' · 会话运行时陪着你'], ['去生成工坊', '让本地 Agent 依据你的会话写 Skill 与规则']].map((x, i) => '<div class="row" style="align-items:flex-start;gap:10px"><span class="mono" style="width:20px;height:20px;flex:none;border-radius:50%;background:var(--sunken);font-size:10.5px;font-weight:700;display:grid;place-items:center">' + (i + 1) + '</span><span class="col" style="gap:1px"><b style="font-size:12.5px">' + x[0] + '</b><span class="cap" style="font-size:11.5px">' + x[1] + '</span></span></div>').join('') + '</div>' +
      '<div class="row" style="justify-content:center;gap:8px;flex-wrap:wrap"><button type="button" class="btn" data-act="obShare">导出分享卡</button><button type="button" class="btn p" data-act="obDone" style="height:32px;padding:0 18px">查看完整画像</button></div><button type="button" class="lnk" data-act="obReveal" style="align-self:center">播放揭晓动画</button>';
  }
  $('#overlay').innerHTML = '<div class="obox" role="dialog" aria-modal="true" aria-label="首次启动">' + top + b + '</div>';
  const f = $('#overlay button.p'); if (f && !f.disabled) f.focus();
}
function obRun() {
  OB.timers.forEach(clearTimeout); OB.timers = [];
  const tick = () => { if (!OB || OVL !== 'ob' || OB.step !== 2) return; OB.prog++; drawOB(); if (OB.prog < 3) OB.timers.push(setTimeout(tick, 950)); else OB.timers.push(setTimeout(() => { if (OB && OVL === 'ob') { OB.step = 3; drawOB(); render(); } }, 800)); };
  OB.timers.push(setTimeout(tick, 700));
}
function openReveal() {
  closeModal(); closeDD(); closeOverlay();
  const per = PERIODS[S.persona.period]; const L = S.route === 'persona' ? sel({ win: [per[0], per[1]] }) : sel({ noExtra: true }); const p = persona(L);
  if (!p.ok) { toast('样本不足（少于 30 个会话），暂时不能揭晓'); return; }
  const reduce = !!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  REV = { done: reduce, timers: [] }; OVL = 'reveal';
  const o = $('#overlay'); o.hidden = false;
  o.innerHTML = '<div class="reveal' + (reduce ? ' skip' : '') + '" id="revBox" role="dialog" aria-modal="true" aria-label="人格揭晓：' + p.code + ' ' + p.zh + '"><div class="row" style="width:100%"><span class="mono cap" id="revStage" style="font-size:11px;text-align:left">' + (reduce ? '05 / 停留' : '01 / 汇集 · 读取 ' + fmt(L.length) + ' 个会话') + '</span><span style="flex:1"></span><button type="button" class="btn sm gh" data-act="revSkip"' + (reduce ? ' hidden' : '') + '>跳过</button></div><div style="width:min(300px,62vw)">' + fpSVG(L, p, 300, { labels: true }) + '</div><div class="code">' + p.code + '</div><div class="nm"><div class="serif" style="font-size:22px;font-weight:600">' + p.zh + ' <i style="font-weight:400;font-size:16px;color:var(--ink-3)">' + p.en + '</i></div><div style="font-size:13px;line-height:1.55;color:var(--ink-2);max-width:330px;margin:6px auto 0">' + esc(p.line) + '</div></div><div class="acts row" style="margin-top:14px;gap:8px;justify-content:center"><button type="button" class="btn" data-act="revShare">导出分享卡</button><button type="button" class="btn p" data-act="revGo">查看完整画像</button></div></div>';
  if (!reduce) [[600, '02 / 归位 · 按开始时间排到 24 小时表盘上'], [1400, '03 / 生长 · D I M V 四个维度'], [2200, '04 / 定型 · ' + p.code], [3000, '']].forEach((x) => REV.timers.push(setTimeout(() => { if (!x[1]) { revealSkip(); return; } const s = $('#revStage'); if (s) s.textContent = x[1]; }, x[0])));
}
function revealSkip() {
  if (!REV || REV.done) return;
  REV.done = true; REV.timers.forEach(clearTimeout);
  const b = $('#revBox'); if (b) b.classList.add('skip');
  const s = $('#revStage'); if (s) s.textContent = '05 / 停留';
  const k = $('#revBox [data-act="revSkip"]'); if (k) k.hidden = true;
  const g = $('#revBox [data-act="revGo"]'); if (g) g.focus();
}
$('#overlay').addEventListener('click', (e) => {
  if (OVL !== 'reveal' || !REV) return;
  if (!REV.done && !e.target.closest('button')) { revealSkip(); return; }
  if (REV.done && e.target.id === 'overlay') closeOverlay();
});
Object.assign(ACT, {
  obNext: () => { OB.step = 1; drawOB(); },
  obBack: () => { OB.step = 0; drawOB(); },
  obClose: () => { closeOverlay(); render(); },
  obPrivacy: () => { closeOverlay(); openSettings('privacy'); },
  obSrc: (el) => { const id = el.dataset.a; if (el.checked) OB.src.add(id); else OB.src.delete(id); drawOB(); },
  obRecent: () => { OB.recent = !OB.recent; drawOB(); },
  obStart: () => { AG.forEach((a) => { if (OB.src.has(a.id)) S.srcOff.delete(a.id); else S.srcOff.add(a.id); }); OB.step = 2; OB.prog = -1; drawOB(); obRun(); },
  obBg: () => { closeOverlay(); render(); setTimeout(() => { const p = personaNow(); notify({ t: '协作画像已生成', b: p.ok ? '你是 ' + p.code + '「' + p.zh + '」。点开看看四个维度和协作指纹。' : '已选来源的会话不足 30 个，暂不判断类型。', a1: '查看', on1: () => go('persona'), force: true }); }, 2600); },
  obDone: () => { closeOverlay(); go('persona'); },
  obShare: () => { closeOverlay(); render(); openShare(); },
  obReveal: () => { closeOverlay(); render(); openReveal(); },
  revSkip: () => revealSkip(),
  revGo: () => { closeOverlay(); go('persona'); },
  revShare: () => { closeOverlay(); openShare(); }
});

