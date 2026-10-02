/* ============ menu bar panel ============ */
function popLiveCard() {
  if (!sourceEnabled(ALL.find((s) => s.id === LIVE_ID))) return '';
  return '<div class="sec col" style="gap:6px"><div class="row"><span class="dot live" style="background:var(--a1)"></span><b style="font-size:12.5px">Claude Code</b><span class="cap">· Hackathon</span><span style="flex:1"></span><span class="mono" style="font-size:12px" data-live>' + liveElapsed() + '</span></div><div style="font-size:13px;font-weight:600">设计 Tandem Mac App 视觉案例</div><div class="row cap" style="font-size:11.5px;min-width:0"><span class="aib">进行中</span><span class="mono" data-hudtool style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + HUD_TOOLS[HUD_T % HUD_TOOLS.length] + '</span></div>' +
    '<div class="col" style="gap:3px;margin-top:2px"><div class="row" style="justify-content:space-between;font-size:11px;color:var(--ink-3)"><span>上下文 <b class="mono" style="color:var(--ink-1)">' + S.live.ctx + '%</b></span><span class="mono">80% 压缩</span></div><div style="position:relative;height:6px;border-radius:3px;background:var(--line)"><span style="position:absolute;left:0;top:0;bottom:0;width:' + S.live.ctx + '%;border-radius:3px;background:' + (S.live.ctx >= 75 ? 'var(--warn-m)' : 'var(--ink-1)') + '"></span><span style="position:absolute;left:80%;top:-3px;width:1.5px;height:12px;background:var(--ink-3)"></span></div></div>' +
    '<div class="row" style="margin-top:4px"><button type="button" class="btn sm" data-act="popTraj">查看轨迹</button><button type="button" class="btn sm gh" data-act="hudMute">' + (S.hud.mute ? '恢复提醒' : '暂停提醒') + '</button></div></div>';
}
/* the panel hangs 6px under the menu bar with its right edge aligned to the Tandem status item */
function popPlace() {
  const el = $('#pop'); if (el.hidden) return;
  const g = $('.mbar [data-act="pop"]'); const d = desk.getBoundingClientRect();
  if (g) { const r = g.getBoundingClientRect(); el.style.right = Math.max(8, Math.round(d.right - r.right)) + 'px'; }
  el.style.top = (MB_H + 6) + 'px';
}
function renderPop() {
  const el = $('#pop'); el.hidden = false; popPlace();
  const p = personaNow();
  const available = ALL.filter((s) => sourceEnabled(s) && !S.excluded.has(s.id));
  const attn = new Set([...S.attn].filter((k) => sourceEnabled({ a: k === 'stuck' ? 'cx' : 'cc' })));
  const today = available.filter((s) => s.d === 120);
  const liveMin = (Date.now() - S.live.t0) / 60000;
  const head = (title, meta, badge) => '<div class="row" style="padding:12px 14px 10px"><div style="flex:1;min-width:0"><div class="row" style="gap:6px"><b style="font-size:13px">' + title + '</b>' + (badge || '') + '</div><div class="mono cap" style="font-size:11px">' + meta + '</div></div><button type="button" class="ib" data-act="openSettings" data-tab="notify" aria-label="通知设置">' + ic('settings', 15) + '</button></div>';
  const foot = '<div class="sec row" style="background:var(--sunken)">' + (p.ok ? glyphSVG(p, 30) : '') + '<div style="flex:1;min-width:0"><b class="mono" style="letter-spacing:.04em">' + (p.ok ? p.code : '—') + '</b> <span style="font-size:12.5px">' + (p.ok ? p.zh : '样本不足') + '</span></div><button type="button" class="btn sm p" data-act="popOpen">打开 Tandem <span style="opacity:.7;font-size:11px">' + kb('⌥0') + '</span></button></div>';
  const days = []; for (let d = 114; d <= 120; d++) days.push([d, available.filter((s) => s.d === d).length]);
  const mx = Math.max(1, ...days.map((x) => x[1]));
  const week = '<div class="sec"><div class="row" style="justify-content:space-between"><span class="eb">近 7 天</span><span class="cap" style="font-size:11px">今天 ' + today.length + ' 个会话</span></div><div class="row" style="align-items:flex-end;gap:6px;height:48px;margin-top:6px">' + days.map((x) => '<span class="col" style="flex:1;align-items:center;gap:3px"><span style="width:100%;height:' + Math.max(3, x[1] / mx * 30).toFixed(1) + 'px;border-radius:3px 3px 1px 1px;background:' + (x[0] === 120 ? 'var(--a1)' : 'var(--h2)') + '" data-tip="' + md(x[0]) + ' 周' + WD[wd(x[0])] + '：' + x[1] + ' 个会话"></span><span class="mono cap" style="font-size:9.5px">' + WD[wd(x[0])] + '</span></span>').join('') + '</div></div>';
  const top = visibleRecs().find((r) => !S.installed.has(r.id));
  const rec = top ? '<div class="sec row" style="gap:10px"><span style="width:28px;height:28px;flex:none;border-radius:7px;background:var(--sunken);display:grid;place-items:center">' + ic(top.icon, 15) + '</span><div style="flex:1;min-width:0"><div style="font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(top.title) + '</div><div class="cap" style="font-size:11px">本周最值得做 · ' + top.gain + '</div></div><button type="button" class="btn sm" data-act="openRec" data-id="' + top.id + '">预览</button></div>' : '';
  let html;
  if (S.paused) {
    html = head('采集已暂停', '不会产生事件，也不会更新统计') + '<div class="sec row"><span style="flex:1;font-size:12.5px;color:var(--ink-2)">恢复后会补齐暂停期间的会话。</span><button type="button" class="btn sm p" data-act="setPause">恢复采集</button></div>' + foot;
  } else if (attn.size) {
    html = head('需要关注', '10 月 1 日 周四', '<span class="bdg" style="background:var(--crit-bg);color:var(--crit)">' + attn.size + ' 件事</span>') +
      (attn.has('stuck') ? '<div class="sec col" style="gap:6px"><div class="row">' + ic('alert', 15, 'color:var(--crit)') + '<b style="font-size:12.5px">同一命令连续失败 4 次</b></div><div class="cap" style="font-size:11.5px">Codex · Surge 规则 · 15:02 开始</div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--sunken)">python gen_rules.py --publish</div><div style="font-size:12px;color:var(--ink-2)">可能原因：CDN token 过期（4 次输出里 3 次是 401）</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="popTerm">在终端中处理</button><button type="button" class="btn sm" data-act="popStuckSess">打开会话</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="stuck">忽略 1 小时</button></div></div>' : '') +
      (attn.has('ctx') ? '<div class="sec col" style="gap:6px"><div class="row">' + ic('gauge', 15, 'color:var(--warn)') + '<b style="font-size:12.5px">上下文即将压缩</b><span style="flex:1"></span><b class="mono" style="color:var(--warn)">78%</b></div><div class="cap" style="font-size:11.5px">Claude Code · latentskill · 审阅第 3 节</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudTip">复制「先总结进度」提示语</button><button type="button" class="btn sm gh" data-act="popIgnore" data-k="ctx">忽略</button></div></div>' : '') +
      popLiveCard() + foot;
  } else if (S.sim === 'idle') {
    const y = available.filter((s) => s.d === 119); const ys = stats(y);
    html = head('今天', '10 月 1 日 周四 · 还没有会话') + '<div class="sec col" style="gap:8px"><div class="row" style="justify-content:space-between"><b style="font-size:12.5px">昨天 · 9 月 30 日</b><span class="mono cap" style="font-size:11px">' + y.length + ' 会话 · ' + dur(sum(y, (s) => s.dur)) + '</span></div><div class="row" style="gap:18px">' + [['摩擦率', f1(ys.fric) + '%'], ['纠偏', ys.corr], ['完成', y.filter((s) => s.out === 'ok').length + ' / ' + y.length]].map((x) => '<span class="col" style="gap:0"><span class="cap" style="font-size:11px">' + x[0] + '</span><b class="mono" style="font-size:15px">' + x[1] + '</b></span>').join('') + '</div></div>' + week +
      '<div class="sec row" style="align-items:flex-start;gap:8px;background:var(--ai-bg)"><span class="aib" style="background:var(--surface)">AI</span><span style="font-size:12px;line-height:1.5;color:var(--ink-2)"><b style="color:var(--ink-1)">开始之前</b>：今天 Hackathon 的任务较大。先写好完成条件，你过去这样做时纠偏少了约 30%。</span></div>' + foot;
  } else {
    html = head('今天', '10 月 1 日 周四 · ' + today.length + ' 会话 · ' + dur(sum(today, (s) => s.live ? liveMin : s.dur)), S.sim === 'done' ? '<span class="bdg" style="background:var(--good-bg);color:var(--good)">刚刚完成 1 个</span>' : '') + popLiveCard() +
      (sourceEnabled({ a: 'cx' }) ? (S.sim === 'waiting' ? '<div class="sec col" style="gap:6px;background:var(--warn-bg)"><div class="row"><span style="width:9px;height:9px;border-radius:2px;background:var(--warn-m)"></span><b style="font-size:12.5px">Codex · team-hub</b><span style="flex:1"></span><span class="cap" style="font-size:11px">等你确认 · 2 分钟</span></div><div class="mono" style="font-size:12px;padding:6px 8px;border-radius:6px;background:var(--surface)">git push origin collab</div><div class="row" style="flex-wrap:wrap"><button type="button" class="btn sm p" data-act="hudGo" data-v="waiting">在终端中处理</button><span class="cap" style="font-size:11px">Tandem 不会代你批准</span></div></div>' : '<button type="button" class="sec row" data-act="openSession" data-id="sess-1001-0903" style="width:100%;border:0;border-top:1px solid var(--hair);background:none;text-align:left;font-size:12px"><span class="dot" style="background:var(--a2)"></span><span style="flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">Codex · team-hub · 同步 collab 并审核日报</span><span class="mono cap" style="font-size:11px">09:03 · 12m ✓</span></button>') : '') +
      week + rec + foot;
  }
  el.innerHTML = html;
}
Object.assign(ACT, {
  popOpen: () => { S.pop = false; S.winGone = false; render(); },
  popTraj: () => { S.pop = false; ACT.openSession({ dataset: { id: LIVE_ID } }); },
  popTerm: () => toast('已切换到对应的终端标签页（演示）'),
  popStuckSess: () => { const s = ALL.filter((x) => sourceEnabled(x) && x.p === 'surge' && x.a === 'cx' && !x.live).sort((a, b) => b.d - a.d)[0] || ALL.filter((x) => sourceEnabled(x) && x.p === 'surge').pop(); S.pop = false; if (s) { S.sess.sel = s.id; S.sess.mode = 'single'; } go('sessions'); },
  popIgnore: (el) => { S.attn.delete(el.dataset.k); if (!S.attn.size && (S.sim === 'stuck' || S.sim === 'ctx')) S.sim = 'running'; render(); toast(el.dataset.k === 'stuck' ? '已忽略 1 小时' : '已忽略'); }
});

