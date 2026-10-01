/* ============ desktop widgets ============ */
function renderWidgets() {
  const w = $('#widgets'); const on = S.widgets && !S.max;
  w.hidden = !on; if (!on) { w.innerHTML = ''; return; }
  const over = window.innerWidth < 1500; w.classList.toggle('over', over);
  const p = personaNow();
  const L7 = sel({ range: 7, noExtra: true }), P7 = sel({ win: [106, 112], noExtra: true });
  const s7 = stats(L7), sp = stats(P7);
  const today = ALL.filter((s) => s.d === 120 && S.agents.has(s.a));
  const liveMin = (Date.now() - S.live.t0) / 60000;
  const days = []; for (let d = 113; d <= 119; d++) { const xs = L7.filter((s) => s.d === d); days.push([d, xs.filter((s) => s.a === 'cc').length, xs.filter((s) => s.a === 'cx').length, xs.filter((s) => s.a !== 'cc' && s.a !== 'cx').length]); }
  const mx = Math.max(1, ...days.map((x) => x[1] + x[2] + x[3]));
  const recs = visibleRecs().filter((r) => !S.installed.has(r.id)); const top = recs[0];
  const delta = sp.n ? Math.round((s7.n - sp.n) / sp.n * 100) : 0;
  const bar = (v, c) => v ? '<span style="height:' + (v / mx * 64).toFixed(1) + 'px;background:' + c + ';border-radius:2px"></span>' : '';
  w.innerHTML = (over ? '<div class="row" style="justify-content:space-between;color:#fff"><b style="font-size:13px;text-shadow:0 1px 2px rgba(0,0,0,.35)">桌面小组件</b><button type="button" class="btn sm" data-act="wgClose">完成</button></div>' : '') +
    '<div class="wg-row"><button type="button" class="wg" data-act="wgGo" data-r="persona" style="aspect-ratio:1;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-start"><span class="lbl">协作人格</span>' + (p.ok ? glyphSVG(p, 56) : '') + '<span><span class="serif" style="display:block;font-size:26px;font-weight:600;line-height:1;letter-spacing:.02em">' + (p.ok ? p.code : '—') + '</span><span style="font-size:12px;color:var(--ink-2)">' + (p.ok ? p.zh + ' · 置信度' + p.conf : '样本不足') + '</span></span></button>' +
    '<button type="button" class="wg" data-act="wgGo" data-r="sessions" style="aspect-ratio:1;display:flex;flex-direction:column;justify-content:space-between;align-items:flex-start"><span class="lbl">今日</span><span><span class="mono" style="display:block;font-size:34px;font-weight:600;line-height:1">' + today.length + '</span><span style="font-size:12px;color:var(--ink-2)">会话 · ' + dur(sum(today, (s) => s.live ? liveMin : s.dur)) + '</span></span><span class="row" style="font-size:11.5px;gap:6px">' + (S.sim === 'idle' ? '<span class="cap">没有运行中的会话</span>' : '<span class="dot live" style="background:var(--a1)"></span>' + (S.numOnly ? '1 个运行中' : 'Hackathon · <span class="mono" data-live>' + liveElapsed() + '</span>')) + '</span></button></div>' +
    '<button type="button" class="wg" data-act="wgGo" data-r="overview" style="display:grid;grid-template-columns:minmax(0,1fr) 150px;gap:12px;align-items:end"><span class="col" style="gap:4px"><span class="lbl">本周</span><span class="mono" style="font-size:34px;font-weight:600;line-height:1">' + s7.n + '</span><span style="font-size:12px;color:var(--ink-2)">会话 · ' + (delta >= 0 ? '↑ ' : '↓ ') + Math.abs(delta) + '%</span><span style="font-size:12px;color:var(--ink-2)">摩擦率 ' + f1(s7.fric) + '% · 较上周 ' + (s7.fric <= sp.fric ? '↓ ' : '↑ ') + f1(Math.abs(s7.fric - sp.fric)) + ' pt</span></span><span class="col" style="gap:5px"><span class="row" style="align-items:flex-end;gap:5px;height:66px">' + days.map((x) => '<span class="col" style="flex:1;gap:2px;justify-content:flex-end" data-tip="' + md(x[0]) + '：Claude ' + x[1] + ' · Codex ' + x[2] + ' · 其他 ' + x[3] + '">' + bar(x[3], 'var(--h2)') + bar(x[2], 'var(--a2)') + bar(x[1], 'var(--a1)') + '</span>').join('') + '</span><span class="row cap" style="font-size:10px;gap:6px"><span class="row" style="gap:3px"><i class="dot" style="width:6px;height:6px;background:var(--a1)"></i>Claude</span><span class="row" style="gap:3px"><i class="dot" style="width:6px;height:6px;background:var(--a2)"></i>Codex</span><span class="row" style="gap:3px"><i class="dot" style="width:6px;height:6px;background:var(--h2)"></i>其他</span></span></span></button>' +
    (top ? '<button type="button" class="wg" data-act="wgRec" data-id="' + top.id + '" style="display:flex;flex-direction:column;gap:6px;align-items:flex-start"><span class="lbl">本周最值得做</span><span style="font-size:15px;font-weight:600;line-height:1.35">' + esc(top.title) + '</span><span class="cap">' + top.type + ' · ' + LEVELS[top.lvl] + ' · ' + top.gain + '</span><span class="row" style="width:100%;justify-content:space-between;margin-top:4px"><span class="cap">还有 ' + Math.max(0, recs.length - 1) + ' 条建议</span><span class="btn sm">预览</span></span></button>' : '');
}
Object.assign(ACT, {
  wgGo: (el) => { if (window.innerWidth < 1500) S.widgets = false; go(el.dataset.r); },
  wgRec: (el) => { if (window.innerWidth < 1500) S.widgets = false; ACT.openRec(el); },
  wgClose: () => { S.widgets = false; render(); }
});

