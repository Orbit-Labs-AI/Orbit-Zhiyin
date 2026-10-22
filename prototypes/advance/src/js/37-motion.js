/* ============ motion: page enter cascade, count-up, page guide, micro-interactions (both editions) ============ */
// Everything here runs from RENDER_HOOKS (25-nav.js) and works on any page of either edition, keyed off plain markup:
//   enter cascade  go() into a page → the blocks of #content rise 8px and fade in, 38ms apart (first 10 blocks; the rest
//                  arrive together). Blocks = #content children, descending into layout wrappers (any non-card div that
//                  holds cards, plus the known grid classes) — so new Lite / Advance layouts are covered without a list.
//   count-up       any element with data-count="<number>" (optional data-dec="1", data-suffix, data-ck = stable key) rolls
//                  from 0 on page enter, and from its previous value when a filter re-render changes it. The rendered text
//                  is the final value; prefix / suffix / thousands separators are read from it. VZ.kpi values are tagged
//                  automatically. countUp(root, { fromZero }) can be called directly for DOM updated outside render().
//   page guide     one line under the toolbar: 「这页回答：… · 先看 …」. × hides it in both editions (store 'guideOff');
//                  「显示 › 页面导读」 brings it back.
//   micro          press scale .97 + spring back, hover lift on clickable cards (37-motion.css); the selected block of a
//                  .seg slides to the new option; filter chips pop in / shrink out; chart ↔ table views cross-fade.
// prefers-reduced-motion: no cascade, numbers show their final value at once, no slides or pops (CSS turns off the rest).
// Toasts, sheets, the persona reveal, replay, studio streaming and vizkit's first-draw animation keep their own motion:
// the cascade only moves whole blocks (opacity / transform on the block), vizkit animates inside its own <svg>.
const MOTION = { prev: new Map(), runs: [], raf: 0, seg: null, vt: -1, chips: null, chipsRoute: null };
const reduceMotion = () => !!window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE_OUT = 'cubic-bezier(.2,.8,.2,1)';

/* ---------- enter cascade ---------- */
const MOTION_WRAP = ['stack', 'two', 'three', 'tiles', 'sess', 'pj', 'pj-two', 'recs', 'studio', 'tt-grid', 'lb-two', 'sn-two', 'grid', 'cols'];
function motionBlocks(root) {
  const out = [];
  const isWrap = (c) => c.nodeName === 'DIV' && !c.classList.contains('card') && !c.classList.contains('frow') && c.children.length > 1 &&
    (MOTION_WRAP.some((k) => c.classList.contains(k)) || Array.from(c.children).some((x) => x.classList.contains('card')));
  const walk = (el, depth) => Array.from(el.children).forEach((c) => {
    if (c.hidden || c.nodeName === 'SCRIPT' || c.nodeName === 'STYLE') return;
    if (depth < 3 && isWrap(c)) walk(c, depth + 1); else out.push(c);
  });
  walk(root, 0);
  return out;
}
function enterCascade(root) {
  if (!root || reduceMotion() || typeof root.animate !== 'function') return;
  motionBlocks(root).forEach((el, i) => {
    el.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
      { duration: 300, delay: Math.min(i, 9) * 38, easing: EASE_OUT, fill: 'backwards' });   // backwards: nothing stays after the end
  });
}

/* ---------- count-up ---------- */
const NUM_RE = /^(\D*?)(-?[\d,]*\.?\d+)(.*)$/s;
function countFmt(v, dec, group) {
  return group ? v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }) : v.toFixed(dec);
}
// tag VZ.kpi values (plain numbers such as 1,234 / 11.8) so every metric tile counts without touching vizkit
function countTag(root) {
  $$('.vz-kpi .v:not([data-count])', root).forEach((el) => {
    const t = el.textContent.trim(); if (!/^-?[\d,]*\.?\d+$/.test(t)) return;
    el.dataset.count = t.replace(/,/g, ''); const d = t.split('.')[1]; if (d) el.dataset.dec = d.length;
  });
}
function countUp(root, opt) {
  opt = opt || {}; root = root || document;
  const scope = opt.scope || S.route; const todo = [];
  $$('[data-count]', root).forEach((el, i) => {
    const to = parseFloat(el.dataset.count); if (!isFinite(to)) return;
    const key = el.dataset.ck || scope + ':' + i;
    const had = MOTION.prev.has(key); const from = opt.fromZero ? 0 : had ? MOTION.prev.get(key) : to;
    MOTION.prev.set(key, to);
    if (from === to || el.children.length || reduceMotion()) return;
    const final = el.textContent; const m = final.match(NUM_RE); if (!m) return;
    const dec = el.dataset.dec != null ? +el.dataset.dec : ((m[2].split('.')[1] || '').length);
    const pre = m[1], suf = el.dataset.suffix != null && !m[3] ? el.dataset.suffix : m[3], group = m[2].includes(',');
    todo.push({ el, from, to, dec, pre, suf, group, final, t0: 0, dur: opt.dur || 600 });
  });
  if (!todo.length) { if (MOTION.runs.length && !MOTION.raf) MOTION.raf = requestAnimationFrame(countTick); return; }
  // keep the box as wide as the final value while digits are missing (tabular-nums keeps each digit the same width);
  // all widths are read before any text is written, so a re-render with many changed numbers forces one layout, not one each
  const widths = todo.map((r) => getComputedStyle(r.el).display !== 'inline' ? r.el.getBoundingClientRect().width : null);
  const els = new Set(todo.map((r) => r.el)); MOTION.runs = MOTION.runs.filter((r) => !els.has(r.el));
  todo.forEach((run, i) => {
    const el = run.el;
    if (widths[i] != null) el.style.minWidth = widths[i] + 'px';
    MOTION.runs.push(run);
    el.textContent = run.pre + countFmt(run.from, run.dec, run.group) + run.suf;
    setTimeout(() => countEnd(run), run.dur + 300);   // settles even when rAF is throttled (hidden tab)
  });
  if (MOTION.runs.length && !MOTION.raf) MOTION.raf = requestAnimationFrame(countTick);
}
function countEnd(r) { if (r.done) return; r.done = true; r.el.textContent = r.final; r.el.style.minWidth = ''; }
function countTick(now) {
  MOTION.runs = MOTION.runs.filter((r) => {
    if (r.done || !r.el.isConnected) return false;
    if (!r.t0) r.t0 = now;
    const p = Math.min(1, (now - r.t0) / r.dur);
    if (p >= 1) { countEnd(r); return false; }
    const e = 1 - Math.pow(1 - p, 3);
    r.el.textContent = r.pre + countFmt(r.from + (r.to - r.from) * e, r.dec, r.group) + r.suf;
    return true;
  });
  MOTION.raf = MOTION.runs.length ? requestAnimationFrame(countTick) : 0;
}

/* ---------- page guide: 「这页回答：…」 ---------- */
// [the question this page answers, where to look first]
const GUIDE = {
  // the hint names the badge the top card actually wears (OV_BADGE, set by the overview render): AI 解读 only when the lede is
  // a model's, 规则解读 for the template, and no badge name while there is no lede at all
  overview: () => [rangeLabel() + '你和 Agent 协作得怎么样', (typeof OV_BADGE !== 'undefined' && OV_BADGE ? '先看顶部「' + OV_BADGE + '」' : '先看顶部的协作画像') + '，再看三张指标卡'],
  persona: () => ['你属于哪一类协作者、和过去相比变了什么', '先看人格代码和四个维度的条'],
  sessions: () => ['某一次会话里发生了什么、卡在了哪一刻', '先在左侧选会话，再看时间线上的失败与关键时刻'],
  tools: () => ['Agent 最常用哪些工具、哪里在失败或在等你审批', '先看「错误率」卡，再看表里失败多的工具'],
  projects: () => ['不同项目里你的协作方式有何不同、哪个项目最该加护栏', '先看散点图里高于回归线的项目'],
  sentiment: () => ['你的情绪和纠偏集中在什么时候、因为什么，平时最常说哪些词', '先看「情绪分布与纠偏」，再看下方的「高频词」'],
  recs: () => ['下一步最值得改什么、改完能省多少', '先看列表第一条和右侧预览'],
  library: () => ['有哪些现成的 Skill、规则和配置适合你', '先看「为你推荐」'],
  studio: () => ['怎样把一条建议或工作流交给本地 Agent 做成可用的配置', '先确认目标与上下文，再点生成'],
  'l-home': () => [rangeLabel() + '协作得怎么样', '先看最上面的一句话结论'],
  'l-persona': () => ['你是哪种协作者', '先看人格代码'],
  'l-sessions': () => ['最近的关键任务进展如何', '先看时间线上标红的地方'],
  'l-recs': () => ['下一步先改什么', '先看第一条建议']
};
const guideOff = () => !!store.get('guideOff', false);
function guideHTML(route) {
  const g = GUIDE[route]; if (!g) return '';
  const t = g();
  return '<div class="pg-guide" role="note">' + ic('info', 13) + '<span class="pg-guide-t"><b>这页回答</b>' + esc(t[0]) + '<span class="pg-guide-s"> · ' + esc(t[1]) + '</span></span>' +
    '<button type="button" class="pg-guide-x" data-act="guideOff" aria-label="收起页面导读" data-tip="收起导读（可在「显示」菜单重新打开）">' + ic('x', 12) + '</button></div>';
}
function guideInsert(mainEl) {
  const c = $('#content', mainEl); if (!c || guideOff() || $('.pg-guide', c)) return;
  const h = guideHTML(S.route); if (h) c.insertAdjacentHTML('afterbegin', h);
}
function guideSet(on) { store.set('guideOff', !on); render(); }
ACT.guideOff = (el) => {
  const g = el.closest('.pg-guide');
  const done = () => { store.set('guideOff', true); $$('.pg-guide').forEach((x) => x.remove()); toast('已收起页面导读 · 可在「显示」菜单重新打开'); };
  if (!g || reduceMotion()) { done(); return; }
  const h = g.offsetHeight;
  g.animate([{ opacity: 1, height: h + 'px' }, { opacity: 0, height: '0px', marginTop: '0px', marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px' }], { duration: 200, easing: EASE_OUT, fill: 'forwards' }).onfinish = done;
};
// 「显示」menu: 页面导读 toggle, placed after 桌面小组件 (wrapped so the menu itself stays owned by 30-actions.js)
{ const v0 = MENUS.view; MENUS.view = () => { const it = v0(); const i = it.findIndex((x) => x.t === '桌面小组件'); const item = { t: '页面导读', on: !guideOff(), v: () => guideSet(guideOff()) }; it.splice(i >= 0 ? i + 1 : it.length, 0, item); return it; }; }

/* ---------- seg slide · chips · chart ↔ table ---------- */
// The page re-renders on every control change, so the old selection is read before the action runs (capture phase) and the
// new one after (render hook, or the next tick when a control updated the DOM in place).
function segSlide(seg, from) {
  const on = seg.querySelector('button.on'); if (!on || !from) return;
  const sr = seg.getBoundingClientRect(), r = on.getBoundingClientRect();
  const to = { x: r.left - sr.left, y: r.top - sr.top, w: r.width, h: r.height };
  if (Math.abs(to.x - from.x) < 1 && Math.abs(to.y - from.y) < 1) return;
  const cs = getComputedStyle(on);
  const ind = document.createElement('span'); ind.className = 'seg-ind'; ind.setAttribute('aria-hidden', 'true');
  ind.style.cssText = 'background:' + cs.backgroundColor + ';box-shadow:' + cs.boxShadow + ';border-radius:' + cs.borderRadius;
  seg.classList.add('seg-mv'); seg.prepend(ind);
  const box = (b) => ({ left: b.x + 'px', top: b.y + 'px', width: b.w + 'px', height: b.h + 'px' });
  const a = ind.animate([box(from), box(to)], { duration: 260, easing: 'cubic-bezier(.3,.8,.25,1)', fill: 'forwards' });
  const done = () => { ind.remove(); seg.classList.remove('seg-mv'); };
  a.onfinish = done; a.oncancel = done;
}
document.addEventListener('click', (e) => {
  if (reduceMotion()) return;
  const t = e.target;
  // seg: remember which segment group and where its selected block was
  const sb = t.closest && t.closest('#main .seg button');
  if (sb && !sb.classList.contains('on') && !sb.disabled) {
    const seg = sb.closest('.seg'); const on = seg.querySelector('button.on');
    if (on) {
      const sr = seg.getBoundingClientRect(), r = on.getBoundingClientRect();
      MOTION.seg = { idx: $$('#main .seg').indexOf(seg), el: seg, route: S.route, from: { x: r.left - sr.left, y: r.top - sr.top, w: r.width, h: r.height } };
      setTimeout(() => { const m = MOTION.seg; MOTION.seg = null; if (m && m.el.isConnected && m.el.querySelector('button.on') !== on) segSlide(m.el, m.from); }, 0);
    }
  }
  // chart ↔ table: remember which card asked
  const vb = t.closest && t.closest('#main [data-v="chart"], #main [data-v="table"]');
  if (vb && !vb.classList.contains('on')) { const card = vb.closest('.card'); MOTION.vt = card ? $$('#main .card').indexOf(card) : -1; setTimeout(() => { MOTION.vt = -1; }, 0); }
  // filter chip removal: shrink out first, then run the action
  const ch = t.closest && t.closest('#main [data-act="clearFilter"]');
  if (ch && !ch._leaving && typeof ch.animate === 'function') {
    e.stopPropagation(); ch._leaving = true;
    if (!$('#dd').hidden) closeDD();
    ch.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'scale(.86)' }], { duration: 150, easing: 'ease-in', fill: 'forwards' })
      .onfinish = () => { if (ch.isConnected) ACT.clearFilter(ch); };
  }
}, true);
function chipKeys(main) { return $$('.frow [data-act="clearFilter"]', main).map((x) => x.dataset.k + '|' + x.textContent); }

/* ---------- render hook ---------- */
RENDER_HOOKS.push((mainEl, entered) => {
  const c = $('#content', mainEl);
  guideInsert(mainEl);
  countTag(mainEl);
  const vt = document.getElementById('win');
  if (entered) {
    // an edition switch already cross-fades the whole main column (View Transitions in 26-edition.js)
    if (!(vt && vt.classList.contains('ed-vt'))) enterCascade(c);
    countUp(mainEl, { fromZero: true });
  } else {
    countUp(mainEl);
    if (!reduceMotion()) {
      const sg = MOTION.seg;
      if (sg && sg.route === S.route) { MOTION.seg = null; const seg = $$('#main .seg')[sg.idx]; if (seg) segSlide(seg, sg.from); }
      if (MOTION.vt >= 0) {
        const card = $$('.card', mainEl)[MOTION.vt];
        $$('.vz', card || document.createElement('i')).forEach((v) => v.animate([{ opacity: 0, transform: 'scale(.985)' }, { opacity: 1, transform: 'none' }], { duration: 240, easing: EASE_OUT, fill: 'backwards' }));
      }
      if (MOTION.chipsRoute === S.route && MOTION.chips) {
        const old = new Set(MOTION.chips);
        $$('.frow [data-act="clearFilter"]', mainEl).forEach((x) => {
          if (!old.has(x.dataset.k + '|' + x.textContent)) x.animate([{ opacity: 0, transform: 'scale(.86)' }, { opacity: 1, transform: 'scale(1.03)', offset: 0.7 }, { opacity: 1, transform: 'none' }], { duration: 240, easing: EASE_OUT });
        });
      }
    }
  }
  MOTION.vt = -1;
  MOTION.chips = chipKeys(mainEl); MOTION.chipsRoute = S.route;
});
