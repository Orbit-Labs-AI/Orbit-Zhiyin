/* ============ exports: report, csv, share card ============ */
const REP_SECS = [['ov', '概览'], ['persona', '协作人格'], ['proj', '项目'], ['fric', '主要摩擦'], ['recs', '建议']];
// Active filters, as one line for the report header. The persona uses the shared persona scope (personaNow, BUG-06):
// session-level filters such as topic or outcome do not change it, and the report says so.
function filterNote() {
  const f = [];
  const agN = AG.filter((a) => S.agents.has(a.id)).length; if (agN !== AG.length) f.push('Agent · ' + AG.filter((a) => S.agents.has(a.id)).map((a) => a.name).join('、'));
  if (S.project) f.push('项目 · ' + PJI[S.project].name); if (S.topic) f.push('主题 · ' + TOPICS[S.topic]); if (S.outcome) f.push('结果 · ' + ({ ok: '完成', part: '部分完成', fail: '放弃' })[S.outcome]); if (S.fric) f.push('摩擦 · ' + S.fric); if (S.hour != null) f.push('时段 · ' + S.hour + ':00–' + (S.hour + 1) + ':00');
  return f.join(' · ');
}
function reportMD() {
  const L = sel(); const st = stats(L); const p = personaNow(); const fn = filterNote();
  const out = ['# Orbit 协作报告 · ' + rangeLabel(), '', '> ' + winLabel() + ' · 示例数据 · 生成于 ' + nowText(), ''];
  if (fn) out.push('> 筛选：' + fn, '');
  if (S.rep.has('ov')) out.push('## 概览', '', '| 指标 | 数值 |', '| --- | ---: |', '| 会话 | ' + fmt(st.n) + ' |', '| 协作时长 | ' + f1(st.hours) + ' 小时 |', '| 你的消息 | ' + fmt(st.msgs) + ' |', '| 自主比 | ' + f1(st.auto) + '× |', '| 摩擦率 | ' + f1(st.fric) + '% |', '| 完成率 | ' + Math.round(st.ok) + '% |', '');
  if (S.rep.has('persona')) {
    out.push('## 协作人格', '', p.ok ? '**' + p.code + ' · ' + p.zh + '**（' + p.en + '）：' + p.line + (fn ? '　—　' + (personaScopeNote() || '按上面的筛选计算') + '，' + p.n + ' 个会话' : '') : '所选范围还没有会话，暂不判断。', '');
    if (p.ok) { AXES.forEach((ax, i) => { const v = axisView(p, i); out.push('- ' + ax.dim + '：' + v.letter + ' ' + v.name + ' ' + v.strong); }); out.push(''); }
  }
  if (S.rep.has('proj')) { out.push('## 项目', '', '| 项目 | 会话 | 时长 | 自主比 | 摩擦率 |', '| --- | ---: | ---: | ---: | ---: |'); projRows(L).filter((r) => r.st.n).sort((a, b) => b.st.hours - a.st.hours).slice(0, 6).forEach((r) => out.push('| ' + r.p.name + ' | ' + r.st.n + ' | ' + f1(r.st.hours) + 'h | ' + f1(r.st.auto) + '× | ' + f1(r.st.fric) + '% |')); out.push(''); }
  if (S.rep.has('fric')) { out.push('## 主要摩擦', ''); Object.entries(countBy(L, 'fric')).sort((a, b) => b[1] - a[1]).slice(0, 4).forEach((f, i) => out.push((i + 1) + '. ' + f[0] + '：' + f[1] + ' 个会话')); out.push(''); }
  if (S.rep.has('recs')) { out.push('## 建议', ''); visibleRecs().slice(0, 6).forEach((r) => out.push('- [' + (S.installed.has(r.id) ? 'x' : ' ') + '] ' + r.title + '（' + r.type + ' · ' + LEVELS[r.lvl] + ' · ' + r.gain + '）')); out.push(''); }
  return out.join('\n');
}
function openReport() {
  CUR.report = reportMD();
  openModal(modalHead('导出报告', rangeLabel() + ' · ' + winLabel() + ' · 跟随主窗口的筛选') + '<div class="mb" style="display:flex;flex-wrap:wrap;gap:16px"><div class="col" style="gap:8px;width:150px;flex:none"><span class="eb">包含</span>' + REP_SECS.map((x) => '<label class="row" style="font-size:13px"><input type="checkbox" data-chg="repSec" data-k="' + x[0] + '"' + (S.rep.has(x[0]) ? ' checked' : '') + ' style="accent-color:var(--ink-1)">' + x[1] + '</label>').join('') + '<span class="eb" style="margin-top:8px">格式</span><span style="font-size:13px">Markdown</span></div><textarea readonly id="repText" aria-label="报告内容" style="flex:1;min-width:min(260px,100%);min-height:340px;font:12px/1.55 var(--font-mono);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--surface);color:var(--ink-1);resize:vertical">' + esc(CUR.report) + '</textarea></div><div class="mf"><span class="cap" style="margin-right:auto;font-size:11px">Demo 不能直接下载 · 复制后粘贴到任意 Markdown 编辑器</span><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="repCopy">复制 Markdown</button></div>', 'wide');
  MODAL_KEY = 'report';
}
function openCSV() {
  const rows = toolRows(sel());
  CUR.csv = ['tool,calls,error_rate,failures,avg_duration,approval_rate'].concat(rows.map((r) => [r.name, r.n, (r.err * 100).toFixed(1) + '%', r.fails, r.avg, Math.round(r.ap * 100) + '%'].join(','))).join('\n');
  openModal(modalHead('导出工具明细 CSV', rangeLabel() + ' · ' + rows.length + ' 种工具 · 复制后可以粘贴到表格软件') + '<div class="mb"><textarea readonly aria-label="CSV 内容" style="width:100%;min-height:260px;font:12px/1.6 var(--font-mono);border:1px solid var(--line);border-radius:9px;padding:10px 12px;background:var(--surface);color:var(--ink-1);resize:vertical">' + esc(CUR.csv) + '</textarea></div><div class="mf"><button type="button" class="btn" data-act="closeModal">关闭</button><button type="button" class="btn p" data-act="copyCSV">复制 CSV</button></div>', 'wide');
}
const SHAREQ = { DIMV: ['把目标交出去，', '把验收留给自己。'], DIFV: ['让 Agent 带路，', '方向由我来核实。'], DIMT: ['同时开很多条线，', '顺着结果往前走。'], DIFT: ['放手让它发挥，', '享受意外的收获。'], DPMV: ['先把规格写清楚，', '再让每个 Agent 各司其职。'], SIFV: ['一次只做一件事，', '每一步都亲自确认。'], SPFV: ['先规划，再打磨，', '每一处都亲手确认。'] };
function sharePersona() { const per = PERIODS[S.persona.period]; const L = sel({ win: [per[0], per[1]] }); return { L, p: persona(L), label: /月$/.test(per[2]) ? '2026 年 ' + per[2].replace(' ', ' ') : per[2] }; }
function qrSVG(seed, C) {
  const r = rng(hash(seed)); const N = 17; let cells = '';
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) { if ((x < 5 && y < 5) || (x > N - 6 && y < 5) || (x < 5 && y > N - 6)) continue; if (r() < 0.45) cells += '<rect x="' + x + '" y="' + y + '" width="1" height="1"/>'; }
  const fin = (x, y) => '<rect x="' + (x + 0.5) + '" y="' + (y + 0.5) + '" width="4" height="4" fill="none" stroke="' + C.ink + '"/><rect x="' + (x + 1.5) + '" y="' + (y + 1.5) + '" width="2" height="2"/>';
  return '<svg viewBox="-1 -1 ' + (N + 2) + ' ' + (N + 2) + '" style="width:14cqw;height:14cqw;flex:none" role="img" aria-label="二维码占位"><g fill="' + C.ink + '">' + cells + fin(0, 0) + fin(N - 5, 0) + fin(0, N - 5) + '</g></svg>';
}
function shareCard(sp) {
  const p = sp.p, L = sp.L, dk = S.shareDark, nn = S.shareNoNum;
  const C = dk ? { bg: '#131417', ink: '#f1f1f3', ink2: '#c3c6cc', ink3: '#8f949c', line: 'rgba(255,255,255,.14)', mj: '#f1f1f3', mn: '#4a4d54' } : { bg: '#f5f4f0', ink: '#17181b', ink2: '#45484f', ink3: '#62666f', line: '#dcd9d2', mj: '#17181b', mn: '#c0bdb5' };
  const g = petals(p, 40, 0.68); const q = SHAREQ[p.code] || ['和 AI 一起，', '找到自己的节奏。'];
  const nAg = new Set(L.map((s) => s.a)).size;
  return '<div class="sharecard" style="background:' + C.bg + ';color:' + C.ink + '"><div style="position:relative;height:100%;padding:7cqw 7.5cqw 6.5cqw;display:flex;flex-direction:column">' +
    '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:2cqw"><span style="font:700 2.6cqw/1 var(--font-num);letter-spacing:.32em">ORBIT</span><span style="font-size:2.5cqw;color:' + C.ink3 + '">我的 AI 协作人格 · ' + esc(sp.label) + '</span></div>' +
    '<svg viewBox="0 0 80 80" style="position:absolute;right:5cqw;top:12cqw;width:32cqw;height:32cqw" aria-hidden="true"><path d="' + g.minor + '" fill="' + C.mn + '"/><path d="' + g.major + '" fill="' + C.mj + '"/></svg>' +
    '<div style="display:flex;gap:3.4cqw;margin-top:9cqw;align-items:flex-end;position:relative">' + AXES.map((ax, i) => { const v = axisView(p, i); return '<div style="display:flex;flex-direction:column;gap:.8cqw"><span style="font:600 14cqw/.9 var(--font-display)">' + v.letter + '</span><span style="font-size:2.6cqw;color:' + C.ink2 + '">' + v.name + '</span>' + (nn ? '' : '<span style="font:600 2.4cqw/1 var(--font-num);color:' + C.ink3 + '">' + v.strong + '%</span>') + '</div>'; }).join('') + '</div>' +
    '<div style="margin-top:7cqw;font:600 8.4cqw/1.05 var(--font-display)">' + esc(p.zh) + '</div><div style="font:italic 400 3.6cqw/1.3 var(--font-display);color:' + C.ink3 + ';margin-top:1cqw">' + esc(p.en) + '</div>' +
    '<div style="margin-top:5cqw;font:500 4.6cqw/1.5 var(--font-display)">「' + esc(q[0]) + '<br>' + esc(q[1]) + '」</div>' +
    (nn ? '' : '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2cqw;margin-top:6cqw;padding-top:4cqw;border-top:1px solid ' + C.line + '">' + [[fmt(p.st.n), '会话'], [Math.round(p.st.hours) + 'h', '协作时长'], [nAg, 'Agent'], [f1(p.st.auto) + '×', '自主比']].map((x) => '<div><div style="font:600 5.4cqw/1.1 var(--font-num)">' + x[0] + '</div><div style="font-size:2.4cqw;color:' + C.ink3 + ';margin-top:.6cqw">' + x[1] + '</div></div>').join('') + '</div>') +
    '<div style="margin-top:auto;display:flex;align-items:flex-end;gap:3cqw"><div style="flex:1;min-width:0"><div style="font-size:3.4cqw;font-weight:600">测测你和 AI 是哪种搭档</div><div style="font-size:2.3cqw;color:' + C.ink3 + ';margin-top:1cqw">[下载链接] · 全部分析在本机完成</div></div>' + qrSVG(p.code, C) + '</div></div></div>';
}
function shareBody() {
  const sp = sharePersona();
  return '<div style="flex:1 1 300px;max-width:360px;min-width:0">' + shareCard(sp) + '</div><div class="col" style="flex:1 1 220px;gap:14px;min-width:0"><div class="col" style="gap:6px"><span class="eb">外观</span><div class="seg" role="radiogroup" aria-label="外观" style="align-self:flex-start"><button type="button" role="radio" aria-checked="' + S.shareDark + '" data-act="shareTheme" data-v="dark" class="' + (S.shareDark ? 'on' : '') + '">深色</button><button type="button" role="radio" aria-checked="' + !S.shareDark + '" data-act="shareTheme" data-v="light" class="' + (!S.shareDark ? 'on' : '') + '">浅色</button></div></div><div class="row" style="gap:10px">' + swBtn(S.shareNoNum, 'shareNum', '', '隐藏具体数字') + '<span style="font-size:13px">隐藏具体数字</span></div><div class="col" style="gap:4px"><span class="eb">周期</span><span style="font-size:13px">' + esc(sp.label) + ' · ' + sp.p.n + ' 个会话</span><span class="cap" style="font-size:11px">在「协作人格」页切换周期</span></div><div class="col" style="gap:4px;padding:10px 12px;border-radius:9px;background:var(--sunken);font-size:12px;line-height:1.55;color:var(--ink-2)"><b style="color:var(--ink-1)">包含</b>类型代号、四个维度' + (S.shareNoNum ? '' : '、会话数与协作时长') + '<b style="color:var(--ink-1);margin-top:4px">不包含</b>项目名、会话标题与任何对话原文</div></div>';
}
function openShare() {
  const sp = sharePersona();
  if (!sp.p.ok) { toast('所选范围还没有会话，暂时不能生成分享卡'); return; }
  openModal(modalHead('导出分享卡', '1080 × 1350 · 适合朋友圈、小红书与 X') + '<div class="mb" id="shareBody" style="display:flex;flex-wrap:wrap;gap:18px;align-items:flex-start">' + shareBody() + '</div><div class="mf"><button type="button" class="btn" data-act="shareCopy">' + ic('copy', 13) + '复制分享文案</button><button type="button" class="btn p" data-act="shareSave">' + ic('down', 13) + '保存图片</button></div>', 'wide');
  MODAL_KEY = 'share';
}
Object.assign(ACT, {
  repSec: (el) => { const k = el.dataset.k; if (el.checked) S.rep.add(k); else S.rep.delete(k); CUR.report = reportMD(); const t = $('#repText'); if (t) t.value = CUR.report; },
  repCopy: () => copyText(CUR.report || reportMD(), '报告'),
  copyCSV: () => copyText(CUR.csv || '', 'CSV'),
  shareTheme: (el) => { S.shareDark = el.dataset.v === 'dark'; $('#shareBody').innerHTML = shareBody(); },
  shareNum: () => { S.shareNoNum = !S.shareNoNum; $('#shareBody').innerHTML = shareBody(); },
  shareCopy: () => { const sp = sharePersona(); copyText('我的 AI 协作人格是 ' + sp.p.code + '「' + sp.p.zh + '」：' + sp.p.line + (S.shareNoNum ? '' : '（' + sp.label + ' · ' + sp.p.n + ' 个会话）') + ' —— 来自 Orbit，全部分析在本机完成。', '分享文案'); },
  shareSave: () => toast('浏览器 Demo 不能下载文件；App 会把 1080×1350 的 PNG 存到「下载」')
});
/* ---- saving exports (live / native): ORBIT.native.request('save') → orbit:saved; the browser fallback downloads a Blob.
   A saved file gets a toast with「在 Finder 中显示」(reveal). Used by 98-live-ops.js; the mock demo keeps its copy buttons. */
function expStamp() { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
function expSave(filename, mime, data) {
  const payload = Object.assign({ filename, mime }, data);
  return ORBIT.native.request('save', payload, { timeoutMs: 120000 }).then((r) => {
    r = r || {};
    if (r.cancelled) return r;
    if (r.ok === false) { toast('保存失败：' + (r.error || '未知错误')); return r; }
    if (r.path) toast('已保存 ' + filename, { act: '在 Finder 中显示', onAct: () => ORBIT.native.request('reveal', { path: r.path }) });
    else toast('已下载 ' + filename);
    return r;
  }, (e) => { toast('保存失败：' + ((e && (e.message || e.code)) || '未知错误')); return { ok: false }; });
}
/* share card → 1080 × 1350 PNG drawn with canvas 2D (WebKit taints a canvas that draws SVG foreignObject, so the HTML card
   cannot be rasterised as is). The model mirrors shareCard(): colours, code letters, names, quote, stats, glyph, QR seed. */
function shareModel(sp) {
  const p = sp.p; const q = SHAREQ[p.code] || ['和 AI 一起，', '找到自己的节奏。'];
  const g = petals(p, 40, 0.68); const nAg = new Set(sp.L.map((s) => s.a)).size;
  return { code: p.code, label: sp.label, zh: p.zh, en: p.en, q, glyph: g,
    axes: AXES.map((ax, i) => { const v = axisView(p, i); return { L: v.letter, name: v.name, strong: v.strong + '%' }; }),
    stats: [[fmt(p.st.n), '会话'], [Math.round(p.st.hours) + 'h', '协作时长'], [String(nAg), 'Agent'], [f1(p.st.auto) + '×', '自主比']], foot: '全部分析在本机完成' };
}
async function sharePNG(m, dark, noNum) {
  try { if (document.fonts && document.fonts.ready) await document.fonts.ready; } catch (e) { /* fonts optional */ }
  const W = 1080, H = 1350, u = W / 100; const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const x = cv.getContext('2d'); const cs = getComputedStyle(document.documentElement);
  const F = { serif: cs.getPropertyValue('--font-display').trim() || 'sans-serif', mono: cs.getPropertyValue('--font-num').trim() || 'sans-serif', sans: cs.getPropertyValue('--font-sans').trim() || 'sans-serif' };
  const C = dark ? { bg: '#131417', ink: '#f1f1f3', ink2: '#c3c6cc', ink3: '#8f949c', line: 'rgba(255,255,255,.14)', mj: '#f1f1f3', mn: '#4a4d54' } : { bg: '#f5f4f0', ink: '#17181b', ink2: '#45484f', ink3: '#62666f', line: '#dcd9d2', mj: '#17181b', mn: '#c0bdb5' };
  const L = 7.5 * u, R = W - 7.5 * u;
  const text = (t, px, py, font, col, align) => { x.font = font; x.fillStyle = col; x.textAlign = align || 'left'; x.fillText(t, px, py); };
  x.fillStyle = C.bg; x.fillRect(0, 0, W, H); x.textBaseline = 'alphabetic';
  if ('letterSpacing' in x) x.letterSpacing = (0.32 * 2.6 * u).toFixed(1) + 'px';
  text('ORBIT', L, 7 * u + 2.6 * u, '700 ' + 2.6 * u + 'px ' + F.mono, C.ink);
  if ('letterSpacing' in x) x.letterSpacing = '0px';
  text('我的 AI 协作人格 · ' + m.label, R, 7 * u + 2.6 * u, 2.5 * u + 'px ' + F.sans, C.ink3, 'right');
  if (m.glyph && typeof Path2D === 'function') {
    const k = 32 * u / 80; x.save(); x.translate(W - 5 * u - 32 * u, 12 * u); x.scale(k, k);
    x.fillStyle = C.mn; x.fill(new Path2D(m.glyph.minor)); x.fillStyle = C.mj; x.fill(new Path2D(m.glyph.major)); x.restore();
  }
  let cx = L; const by = 7 * u + 2.6 * u + 9 * u + 12.6 * u;
  m.axes.forEach((a) => {
    x.font = '600 ' + 14 * u + 'px ' + F.serif; const w1 = x.measureText(a.L).width; x.font = 2.6 * u + 'px ' + F.sans; const w2 = x.measureText(a.name).width;
    text(a.L, cx, by, '600 ' + 14 * u + 'px ' + F.serif, C.ink); text(a.name, cx, by + 3.8 * u, 2.6 * u + 'px ' + F.sans, C.ink2);
    if (!noNum && a.strong) text(a.strong, cx, by + 7.2 * u, '600 ' + 2.4 * u + 'px ' + F.mono, C.ink3);
    cx += Math.max(w1, w2) + 3.4 * u;
  });
  let y = by + (noNum ? 4 : 7.2) * u + 7 * u + 7.6 * u;
  text(m.zh || '', L, y, '600 ' + 8.4 * u + 'px ' + F.serif, C.ink); y += 4.7 * u;
  text(m.en || '', L, y, 'italic 400 ' + 3.6 * u + 'px ' + F.serif, C.ink3); y += 5 * u + 5.6 * u;
  text('「' + (m.q[0] || ''), L, y, '500 ' + 4.6 * u + 'px ' + F.serif, C.ink); y += 6.9 * u;
  text((m.q[1] || '') + '」', L, y, '500 ' + 4.6 * u + 'px ' + F.serif, C.ink);
  if (!noNum && m.stats.length) {
    y += 6 * u; x.fillStyle = C.line; x.fillRect(L, y, R - L, Math.max(1, u / 4)); y += 4 * u + 5.4 * u;
    const cw = (R - L - 6 * u) / 4;
    m.stats.slice(0, 4).forEach((s, i) => { const sx = L + i * (cw + 2 * u); text(String(s[0]), sx, y, '600 ' + 5.4 * u + 'px ' + F.mono, C.ink); text(s[1], sx, y + 3.4 * u, 2.4 * u + 'px ' + F.sans, C.ink3); });
  }
  const qs = 14 * u, qx = R - qs, qy = H - 6.5 * u - qs, N = 17, cell = qs / (N + 2); const r = rng(hash(m.code));
  x.fillStyle = C.ink;
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) { if ((i < 5 && j < 5) || (i > N - 6 && j < 5) || (i < 5 && j > N - 6)) continue; if (r() < 0.45) x.fillRect(qx + (i + 1) * cell, qy + (j + 1) * cell, cell, cell); }
  [[0, 0], [N - 5, 0], [0, N - 5]].forEach((f) => { x.strokeStyle = C.ink; x.lineWidth = cell; x.strokeRect(qx + (f[0] + 1.5) * cell, qy + (f[1] + 1.5) * cell, 4 * cell, 4 * cell); x.fillRect(qx + (f[0] + 2.5) * cell, qy + (f[1] + 2.5) * cell, 2 * cell, 2 * cell); });
  text('测测你和 AI 是哪种搭档', L, H - 6.5 * u - 4.4 * u, '600 ' + 3.4 * u + 'px ' + F.sans, C.ink);
  text(m.foot || '', L, H - 6.5 * u, 2.3 * u + 'px ' + F.sans, C.ink3);
  return cv.toDataURL('image/png').split(',')[1];
}
