/* Tandem promo: a beat-locked timeline. Two live copies of the app take turns showing ONE component each (everything
   else in that copy is hidden), framed by a virtual camera next to the copy that explains it. Transitions overlap the
   outgoing and incoming component with long eases; there are no beat-synced shakes or flashes.
   Everything is a pure function of the master time t (seconds), so the page plays in real time with the soundtrack
   (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM, END = 106;              // beats; music.py uses the same grid
const RENDER = location.search.includes('render');
const DEBUG = location.search.includes('debug');
const $ = (s, r) => (r || document).querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  lin: (p) => p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  quart: (p) => 1 - Math.pow(1 - p, 4),
  in: (p) => p * p * p,
  inOut: (p) => (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  sine: (p) => -(Math.cos(Math.PI * p) - 1) / 2,
  expo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p))
};
const stage = $('#stage'), fxEl = $('#fx'), glowEl = $('#glow');

/* ---------- the two app copies ("decks") and their cameras ---------- */
// x,y: the app point (frame px) put at screen point (ax, ay); s: zoom; rx/ry/rz: tilt around (ax, ay); z: dolly;
// o: opacity; bl: blur. Tweens start from wherever the deck's camera is when they fire.
const ZERO = { x: 800, y: 500, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 0, bl: 0 };
const decks = [0, 1].map((i) => ({ i, frame: $('#app' + i), cam: $('#cam' + i), rig: $('#rig' + i), C: Object.assign({}, ZERO), W: null, D: null }));
const tweens = [];
const BOX = { C: [960, 560, 1560, 760], R: [1250, 540, 1060, 800], L: [670, 540, 1060, 800] };
function find(d, sel) {
  const D = decks[d].D; if (!D) return null;
  if (typeof sel === 'function') return sel(D);
  return D.querySelector(sel);
}
function rectOf(d, sel) {
  const list = (Array.isArray(sel) ? sel : [sel]).map((s) => find(d, s)).filter(Boolean);
  if (!list.length) { console.warn('promo: no target', String(sel)); return { x: 600, y: 400, w: 400, h: 200 }; }
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const el of list) { const r = el.getBoundingClientRect(); x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom); }
  if (DEBUG) console.warn('rect', d, String(sel).slice(0, 40), Math.round(x0), Math.round(y0), Math.round(x1 - x0), Math.round(y1 - y0));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
// fit a component into a screen box [cx, cy, w, h]
function framing(d, sel, box, o = {}) {
  const r = rectOf(d, sel); const [cx, cy, w, h] = typeof box === 'string' ? BOX[box] : box;
  const s = Math.min(w / r.w, h / r.h, o.max || 2.3);
  return { x: r.x + r.w * (o.px ?? .5), y: r.y + r.h * (o.py ?? .5), s, ax: cx, ay: cy, rx: 0, ry: 0, rz: o.rz || 0, z: 0, o: 1, bl: 0 };
}
// tween(d, b, dur, to, ease, from): to = object or () => object; from(T) gives the start state relative to the target
function tween(d, b, dur, to, ease = E.inOut, from = null) { tweens.push({ d, b, dur, to, ease, from }); }
const IN = {
  rise: (T) => ({ ay: T.ay + 150, s: T.s * .97, o: 0, bl: 10 }),
  sink: (T) => ({ ay: T.ay - 150, s: T.s * .97, o: 0, bl: 10 }),
  depth: (T) => ({ s: T.s * .8, o: 0, bl: 8 }),
  near: (T) => ({ s: T.s * 1.18, o: 0, bl: 10 }),
  fromR: (T) => ({ ax: T.ax + 380, o: 0, bl: 6 }),
  fromL: (T) => ({ ax: T.ax - 380, o: 0, bl: 6 }),
  tilt: () => ({ ry: -24, rx: 10, z: -180, o: 0, bl: 4 }),
  fade: () => ({ o: 0 })
};
const OUT = {
  up: (C) => ({ ay: C.ay - 150, o: 0, bl: 10 }),
  down: (C) => ({ ay: C.ay + 150, o: 0, bl: 10 }),
  far: (C) => ({ s: C.s * .84, o: 0, bl: 8 }),
  near: (C) => ({ s: C.s * 1.35, o: 0, bl: 14 }),
  toL: (C) => ({ ax: C.ax - 380, o: 0, bl: 6 }),
  toR: (C) => ({ ax: C.ax + 380, o: 0, bl: 6 }),
  fade: () => ({ o: 0 })
};
// shot: show one component of deck d from beat b until `until`, entering with o.inn and leaving with o.out
function shot(d, b, until, o) {
  if (o.prep) at(b - (o.lead || .05), () => o.prep(app(d)));
  at(b - .02, () => solo(d, o.sel));
  const inDur = o.inDur || 1, outDur = o.outDur || .9;
  tween(d, b, inDur, () => framing(d, o.frame || o.sel, o.box || 'C', o), o.ease || E.quart, IN[o.inn || 'rise']);
  // the component keeps moving while it holds: slow push and an optional pan/turn/orbit
  const hold = until - b - inDur;
  if (hold > 0) tween(d, b + inDur, hold + outDur, () => { const C = decks[d].C; const r = { s: C.s * (o.push || 1.035) }; if (o.pan) r.ax = C.ax + o.pan; if (o.turn) r.rz = C.rz + o.turn; if (o.orbit) r.ry = C.ry + o.orbit; return r; }, E.sine);
  tween(d, until, outDur, () => OUT[o.out || 'up'](decks[d].C), o.outEase || E.in);
}
function applyCams(t) {
  for (const tw of tweens) {
    const t0 = tw.b * BEAT; if (t < t0 || tw.done) continue;
    const C = decks[tw.d].C;
    if (!tw.res) {
      tw.res = Object.assign({}, typeof tw.to === 'function' ? tw.to() : tw.to);
      if (tw.from) Object.assign(C, ZERO, tw.res, tw.from(tw.res));
      tw.start = Object.assign({}, C);
      // a newer move owns its keys: older moves on the same deck let go of them
      for (const o of tweens) if (o !== tw && o.d === tw.d && o.res && !o.done) for (const k in tw.res) delete o.res[k];
    }
    const p = tw.dur ? clamp((t - t0) / (tw.dur * BEAT)) : 1, e = tw.ease(p);
    for (const k in tw.res) C[k] = lerp(tw.start[k], tw.res[k], e);
    if (p >= 1) tw.done = true;
  }
  for (const k of decks) {
    const c = k.C;
    k.cam.style.transformOrigin = c.ax.toFixed(1) + 'px ' + c.ay.toFixed(1) + 'px';
    k.cam.style.transform = 'perspective(2400px) translateZ(' + c.z.toFixed(1) + 'px) rotateX(' + c.rx.toFixed(3) + 'deg) rotateY(' + c.ry.toFixed(3) + 'deg) rotateZ(' + c.rz.toFixed(3) + 'deg)';
    k.rig.style.transform = 'translate(' + (c.ax - c.x * c.s).toFixed(2) + 'px,' + (c.ay - c.y * c.s).toFixed(2) + 'px) scale(' + c.s.toFixed(4) + ')';
    k.cam.style.opacity = c.o.toFixed(3);
    k.cam.style.filter = c.bl > .05 ? 'blur(' + c.bl.toFixed(2) + 'px)' : 'none';
    k.cam.style.visibility = c.o < .002 ? 'hidden' : 'visible';
  }
}

/* ---------- type ---------- */
// txt(b0, b1, lines, pos): lines = [[cls, html], …] ('gap' for a spacer); pos = {x, y, align: 'l'|'c'|'r'}.
// Lines rise through a mask one after another (o.st beats apart) and leave together, drifting up.
const fx = [];
function txt(b0, b1, lines, pos, o = {}) {
  const html = lines.map(([c, h]) => (c === 'gap' ? '<div class="gap"></div>' : '<span class="ln ' + c + '"><span>' + h + '</span></span>')).join('');
  const al = pos.align || 'l';
  const style = 'left:' + pos.x + 'px;top:' + pos.y + 'px;text-align:' + ({ l: 'left', c: 'center', r: 'right' })[al] + (o.style ? ';' + o.style : '');
  fx.push({ b0, b1, html, style, base: 'translate(' + ({ l: '0', c: '-50%', r: '-100%' })[al] + ',-50%)', anim: o.anim || mask(o.st ?? .18, o.inB || 1, o.outB || .6), tick: o.tick, el: null });
}
function mask(st, inB, outB) {
  return (el, tl, life) => {
    const q = E.inOut(clamp((life - tl) / (outB * BEAT)));
    el.querySelectorAll('.ln>span').forEach((s, i) => {
      const p = E.expo(clamp((tl - i * st * BEAT) / (inB * BEAT)));
      s.style.transform = 'translateY(' + ((1 - p) * 130 - (1 - q) * 30).toFixed(2) + '%)';
      s.style.opacity = (Math.min(1, p * 1.4) * q).toFixed(3);
      s.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none';
    });
  };
}
// count-up for [data-count] spans
const count = (beats) => (el, tl) => el.querySelectorAll('[data-count]').forEach((n) => { n.textContent = Math.round(+n.dataset.count * E.out(clamp(tl / (beats * BEAT)))); });
function applyFx(t) {
  for (const f of fx) {
    const t0 = f.b0 * BEAT, t1 = f.b1 * BEAT, live = t >= t0 && t < t1;
    if (live && !f.el) { f.el = document.createElement('div'); f.el.className = 'k'; f.el.innerHTML = f.html; f.el.setAttribute('style', f.style); f.el.style.transform = f.base; fxEl.appendChild(f.el); }
    if (!live && f.el) { f.el.remove(); f.el = null; }
    if (f.el) { f.anim(f.el, t - t0, t1 - t0, t); if (f.tick) f.tick(f.el, t - t0, t1 - t0, t); }
  }
}
let glow = { b: null, from: 0, to: 0, v: 0, dur: 2 };
function glowAt(b, v, dur = 2) { at(b, () => { glow = { b, from: glow.v, to: v, v: glow.v, dur }; }); }
function applyGlow(t) { if (glow.b == null) return; glow.v = lerp(glow.from, glow.to, E.inOut(clamp((t / BEAT - glow.b) / glow.dur))); glowEl.style.opacity = glow.v.toFixed(3); }

/* ---------- app control ---------- */
const cues = [];
function at(b, fn) { cues.push({ b, fn, done: false }); }
function app(d) {
  const k = decks[d], W = k.W, D = k.D;
  return {
    W, D, S: W.eval('S'),
    go: (r) => { if (W.closeOverlay) W.closeOverlay(); if (W.closeModal) W.closeModal(); W.go(r); },
    click: (sel) => { const el = typeof sel === 'string' ? D.querySelector(sel) : sel; if (el) el.click(); else console.warn('promo: no click target', sel); },
    render: () => W.render()
  };
}
// show only these elements of deck d (they are scrolled into view first)
function solo(d, sel) {
  const D = decks[d].D; decks[d].solo = sel;
  D.querySelectorAll('.promo-solo').forEach((e) => e.classList.remove('promo-solo'));
  for (const s of Array.isArray(sel) ? sel : [sel]) {
    const el = find(d, s); if (!el) { console.warn('promo: no solo target', String(s)); continue; }
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.bottom > D.documentElement.clientHeight) el.scrollIntoView({ block: 'center', behavior: 'instant' });
    el.classList.add('promo-solo');
  }
}
const byText = (sel, text) => (D) => [...D.querySelectorAll(sel)].find((e) => e.textContent.includes(text));
const PROMO_CSS = 'html,body,.desk{background:transparent!important}.desk .wall{display:none!important}.tip{display:none!important}' +
  'html body *{visibility:hidden!important}html body .promo-solo,html body .promo-solo *{visibility:visible!important}' +
  'html body .promo-solo:not(svg){box-shadow:0 0 0 .5px rgba(255,255,255,.14),0 30px 90px rgba(0,0,0,.55)!important}' +
  '.promo-solo [hidden]{visibility:hidden!important}:root{color-scheme:light!important}';

/* ============================== the script ============================== */
// 0–8 open · 8–14 logo · 14–32 overview · 32–38 DIMV · 38–48 persona · 48–64 trajectory · 64–72 ask (build)
// 72–88 eight features, two beats each · 88–96 desktop · 96–106 end card
const L = 160, R = 1760;                                    // text margins
function script() {
  // --- open (缓)
  txt(.25, 3.9, [['lt', '你每天都在和 Agent 协作']], { x: 960, y: 470, align: 'c' });
  const AGS = [['Claude Code', 'var(--a1)'], ['Codex', 'var(--a2)'], ['Gemini CLI', 'var(--a3)'], ['DeepSeek', 'var(--a4)'], ['Copilot', 'var(--a5)']];
  txt(1.5, 3.9, [['', AGS.map((a) => '<span class="chip"><i style="background:' + a[1] + '"></i>' + a[0] + '</span>').join('')]], { x: 960, y: 560, align: 'c' }, {
    anim: (el, tl, life) => { // the chips arrive one by one on the dotted rhythm
      const q = E.inOut(clamp((life - tl) / (.6 * BEAT)));
      el.querySelectorAll('.chip').forEach((c, i) => { const p = E.expo(clamp((tl - i * .375 * BEAT) / (.8 * BEAT))); c.style.opacity = (p * q).toFixed(3); c.style.transform = 'translateY(' + ((1 - p) * 24).toFixed(1) + 'px)'; c.style.marginRight = i < 4 ? '44px' : '0'; c.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none'; });
    }
  });
  txt(4, 5.9, [['md', '却很少回头看看']], { x: 960, y: 540, align: 'c' });
  txt(6, 7.9, [['md', '自己是<span class="serif"><i>怎样</i></span>和它们协作的']], { x: 960, y: 540, align: 'c' });

  // --- logo
  glowAt(8, 1, 3);
  txt(8, 13.8, [['', '<img class="mark" src="mark.svg" alt="">']], { x: 960, y: 420, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.quart(clamp(tl / (2.2 * BEAT))), q = E.in(clamp(1 - (life - tl) / (1.2 * BEAT)));
      el.style.opacity = (p * (1 - q)).toFixed(3); el.style.filter = 'blur(' + ((1 - p) * 16 + q * 10).toFixed(1) + 'px)';
      el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(1.12, 1, p) * (1 + tl * .01) * (1 - q * .12)).toFixed(4) + ')';
    }
  });
  txt(9, 13.8, [['word', 'Tandem']], { x: 960, y: 620, align: 'c' }, { inB: 1.4, outB: 1 });
  txt(10.5, 13.8, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 730, align: 'c' }, { inB: 1.4, outB: 1 });
  glowAt(13, .5, 2);

  // --- overview
  shot(0, 13.4, 19, { sel: '.tiles', box: [960, 650, 1700, 420], inn: 'depth', inDur: 2.2, out: 'up', prep: (a) => a.go('overview'), lead: .3, push: 1.03 });
  txt(14.6, 19, [['eb', '01 · Overview'], ['gap'], ['hv', '一屏看懂近 30 天']], { x: 960, y: 380, align: 'c' });
  shot(1, 19.25, 23.25, { sel: '.ov-out', box: [1190, 560, 1340, 600], inn: 'rise', out: 'toL', prep: (a) => a.go('overview') });
  txt(19.6, 23.25, [['xl', '<span data-count="87">0</span><span style="font-size:.5em">%</span>'], ['lt', '的会话一次完成']], { x: L, y: 540 }, { tick: count(1.6) });
  const trend = byText('.card.pad', 'Agent 使用趋势');
  shot(0, 23.4, 27.5, { sel: trend, box: [690, 540, 1060, 820], inn: 'fromR', out: 'up', prep: (a) => { a.S.ov.stack = 'stacked'; a.go('overview'); } });
  txt(23.8, 27.5, [['eb', 'Agents'], ['gap'], ['hv', '五个 Agent'], ['lt', '一张图对齐']], { x: R, y: 540, align: 'r' });
  at(25.5, () => app(0).click('[data-act="stackMode"][data-v="pct"]'));
  at(26.5, () => app(0).click('[data-act="stackMode"][data-v="stacked"]'));
  shot(1, 27.6, 31.2, { sel: '#aiCard', box: [960, 640, 1640, 420], inn: 'rise', out: 'near', outDur: .8, prep: (a) => a.go('overview') });
  at(28.1, () => app(1).click('#aiCard [data-act="regen"]'));
  txt(28, 31.2, [['eb', 'AI 解读'], ['gap'], ['md', '本地 Agent，<span class="ai">一句话说透</span>你的协作']], { x: 960, y: 330, align: 'c' });
  glowAt(31, 0, 1);

  // --- DIMV (重): four letters land one per beat, then settle into the name
  const DIMV = [['D', '委托 72'], ['I', '即兴 61'], ['M', '多线 73'], ['V', '求证 67']];
  DIMV.forEach((x, i) => txt(32 + i, 37.8, [['letter', x[0]]], { x: 960 + (i - 1.5) * 290, y: 470, align: 'c' }, {
    anim: (el, tl, life, t) => {
      const p = E.quart(clamp(tl / (.75 * BEAT))), q = E.inOut(clamp((life - tl) / (.8 * BEAT)));
      const g = E.inOut(clamp((t / BEAT - 36) / 1.4));       // the row settles up and smaller
      const sp = el.querySelector('.ln>span');
      sp.style.transform = 'translateY(' + ((1 - p) * 130).toFixed(2) + '%)'; sp.style.opacity = (Math.min(1, p * 1.6) * q).toFixed(3);
      sp.style.filter = q < .999 ? 'blur(' + ((1 - q) * 10).toFixed(1) + 'px)' : 'none';
      el.style.transform = 'translate(-50%,-50%) translate(' + (-(i - 1.5) * 290 * g * .3).toFixed(1) + 'px,' + (-110 * g).toFixed(1) + 'px) scale(' + lerp(1, .7, g).toFixed(4) + ')';
    }
  }));
  DIMV.forEach((x, i) => txt(32.3 + i, 36, [['dimv-l', x[1]]], { x: 960 + (i - 1.5) * 290, y: 680, align: 'c' }, { inB: .8, outB: .6 }));
  txt(36.3, 37.8, [['md', '指挥家 <span class="serif dim"><i>The Conductor</i></span>']], { x: 960, y: 610, align: 'c' }, { outB: .8 });

  // --- persona (缓)
  glowAt(37.6, .5, 2);
  shot(0, 37.6, 43.2, { sel: '#revBox', box: [1250, 540, 880, 900], inn: 'depth', inDur: 1.6, out: 'far', outDur: 1.2, push: 1.06, prep: (a) => { a.go('persona'); a.W.openReveal(); }, lead: .1 });
  txt(38.5, 43.2, [['lt', '从 186 个会话里'], ['gap'], ['hv', '长出你的'], ['hv', '协作人格']], { x: L, y: 540 }, { st: .3 });
  shot(1, 43.4, 47.5, { sel: '.persona-hero svg.fp2', box: [700, 540, 860, 860], inn: 'depth', inDur: 1.6, out: 'toL', rz: -14, turn: 16, push: 1.04, prep: (a) => a.go('persona') });
  txt(44.2, 47.5, [['eb', 'Fingerprint'], ['gap'], ['md', '协作指纹'], ['gap'], ['lt', '四维雷达 · 24 小时节律'], ['lt', '按 Agent 堆叠的会话']], { x: R, y: 540, align: 'r' });

  // --- trajectory
  const head = (D) => { const tl = D.querySelector('.tl-card'); return tl && tl.previousElementSibling; };
  shot(0, 47.7, 51.4, { sel: head, box: [1300, 540, 1000, 700], inn: 'fromR', out: 'toL', prep: (a) => a.go('sessions') });
  txt(48, 51.4, [['eb', '03 · Trajectory'], ['gap'], ['hv', '每一次会话'], ['lt', 'Claude Code · 42 分钟 · 142 次工具调用']], { x: L, y: 540 });
  shot(1, 51.6, 57.4, { sel: '.tl-card', box: [1310, 540, 1040, 900], inn: 'fromR', out: 'up', pan: -40, push: 1.05, prep: (a) => a.go('sessions') });
  at(52.2, () => app(1).click('[data-act="playToggle"]'));
  txt(52.3, 57.4, [['lt', '逐秒回放'], ['gap'], ['hv', '卡在哪一刻'], ['hv', '一眼看清']], { x: L, y: 540 }, { st: .3 });
  shot(0, 57.6, 63.2, { sel: byText('.card.pad.col', '这次会话的启示'), box: [1300, 540, 700, 860], inn: 'rise', out: 'far', prep: (a) => a.go('sessions') });
  txt(58, 63.2, [['lt', '然后告诉你'], ['gap'], ['hv', '下次怎么做']], { x: L, y: 540 }, { st: .4 });

  // --- ask the local agent (build)
  shot(1, 63.5, 71, { sel: '#modal', box: [1310, 560, 980, 760], inn: 'depth', inDur: 1.4, out: 'near', outDur: 1, push: 1.14, prep: (a) => { a.go('overview'); a.W.openAsk('overview'); } });
  at(64.2, () => app(1).click('[data-act="askPick"]'));
  txt(64, 71, [['eb', '04 · Ask'], ['gap'], ['hv', '问你自己的'], ['hv', '<span class="ai">本地 Agent</span>'], ['gap'], ['lt', '数据不出本机 · 0 B 上传']], { x: L, y: 540 }, { st: .5 });
  glowAt(70.5, 0, 1.5);

  // --- eight features, two beats each (急): component and a word, alternating sides
  const feat = (i, d, sel, word, sub, prep, o = {}) => {
    const b = 72 + i * 2, right = i % 2 === 0;
    shot(d, b - .3, b + 1.75, Object.assign({ sel, box: o.box || (right ? [1330, 540, 920, 760] : [590, 540, 920, 760]), inn: right ? 'fromR' : 'fromL', inDur: .8, out: right ? 'toL' : 'toR', outDur: .6, prep, lead: o.lead || .3, push: 1.03 }, o));
    txt(b, b + 1.75, [['hv', word], ['lt', sub]], o.tpos || (right ? { x: L, y: 540 } : { x: R, y: 540, align: 'r' }), { inB: .7, outB: .45, st: .12 });
  };
  at(70.4, () => { const a = app(0); a.go('studio'); a.click('[data-act="studioStart"]'); });
  feat(0, 0, (D) => D.querySelectorAll('#main .card.pad.col')[1], '生成工坊', '把建议变成 Skill、Hook 与规则', null);
  feat(1, 1, '.rcard.sel', '12 条建议', '每月约省下 20 小时', (a) => a.go('recs'));
  feat(2, 0, trend, '深色模式', '跟随系统外观', (a) => a.go('overview'));
  at(76.9, () => app(0).W.setTheme('dark'));
  feat(3, 1, '.edsw', 'Lite / Advance', '一键切换 · ⌃⌘L', (a) => { a.W.closeModal(); a.go('overview'); }, { box: [960, 400, 1000, 300], max: 4, tpos: { x: 960, y: 700, align: 'c' } });
  at(78.8, () => app(1).W.edSet('lite'));
  feat(4, 0, '#notes .nt', '第一时间提醒', '会话等你确认时', (a) => { a.W.setTheme('light'); a.go('overview'); a.D.querySelectorAll('#notes .nt').forEach((n) => n.remove()); a.W.simEvent('waiting'); }, { max: 3, lead: .5 });
  feat(5, 1, '#modal', '⌘K', '任何页面、会话与操作', (a) => { a.W.edSet('advance'); a.W.openPalette(); }, { lead: .5 });
  feat(6, 0, '#hud', '悬浮组件', '会话运行时，陪在桌面一角', (a) => { a.S.hud.show = true; a.S.sim = 'running'; a.render(); }, { max: 3.2 });
  feat(7, 1, '#widgets', '桌面小组件', '人格 · 今日 · 本周 · 最值得做', (a) => { a.W.closeModal(); a.S.widgets = true; a.go('overview'); }, { out: 'far' });

  // --- close on the fingerprint, big and slowly turning (缓)
  shot(0, 88, 95, { sel: '.persona-hero svg.fp2', box: [960, 470, 700, 700], inn: 'depth', inDur: 2.4, out: 'far', outDur: 1.4, rz: -10, turn: 22, push: 1.06,
    prep: (a) => { a.W.closeModal(); a.S.widgets = false; a.W.edSet('advance'); a.go('persona'); }, lead: .8 });
  glowAt(88, .7, 3);
  txt(89.5, 95, [['lt', '只读本地日志 · 数据不出本机'], ['gap'], ['eb', 'local-first · 0 B uploaded']], { x: 960, y: 950, align: 'c' }, { st: .4 });
  glowAt(95, 0, 1);

  // --- end card
  glowAt(96, 1, 3);
  txt(96, 105.6, [['', '<img class="mark" src="mark.svg" alt="">']], { x: 960, y: 420, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.quart(clamp(tl / (2.4 * BEAT))), q = E.inOut(clamp((life - tl) / (2 * BEAT)));
      el.style.opacity = (p * q).toFixed(3); el.style.filter = 'blur(' + ((1 - p) * 16 + (1 - q) * 8).toFixed(1) + 'px)';
      el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(.9, 1, p) * (1 + tl * .008)).toFixed(4) + ')';
    }
  });
  txt(97, 105.6, [['word', 'Tandem']], { x: 960, y: 620, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(98.5, 105.6, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 730, align: 'c' }, { inB: 1.5, outB: 2 });
  txt(100.5, 105.6, [['eb', 'for macOS · ActionMesh AI']], { x: 960, y: 810, align: 'c' }, { inB: 1.5, outB: 2 });
  glowAt(103.5, 0, 2.5);
}

/* ---------- clock & frame loop ---------- */
const PROMO = window.PROMO = { ready: false, duration: END * BEAT, t: 0 };
let t0 = null, offset = 0, audio = null, actx = null;
function now() {
  if (actx && audio) return actx.currentTime - audio.start + offset;
  return t0 == null ? 0 : (performance.now() - t0) / 1000 + offset;
}
function step(tt) {
  const t = tt ?? now(); PROMO.t = t;
  for (const c of cues) if (!c.done && t >= c.b * BEAT) { c.done = true; try { c.fn(); } catch (e) { console.error('cue @' + c.b, e); } }
  // the app re-renders on clicks and route changes: re-mark the solo component when its element was replaced
  for (const k of decks) if (k.solo && k.D) for (const s of Array.isArray(k.solo) ? k.solo : [k.solo]) { const el = find(k.i, s); if (el && !el.classList.contains('promo-solo')) el.classList.add('promo-solo'); }
  applyCams(t); applyFx(t); applyGlow(t);
}
// Pin every CSS animation/transition (here and in both app copies) to the virtual clock: each one is paused and its
// currentTime set from the moment it was first seen; finished ones are finished explicitly so the end events still fire.
const SEEN = new WeakMap();
function syncAnims() {
  const n = performance.now();
  for (const doc of [document, decks[0].D, decks[1].D]) {
    if (!doc) continue;
    for (const a of doc.getAnimations()) {
      if (a.playState === 'finished') continue;
      let s = SEEN.get(a); if (s === undefined) { s = n - (a.currentTime || 0); SEEN.set(a, s); }
      const el = (n - s) * (a.playbackRate || 1), tm = a.effect && a.effect.getComputedTiming();
      if (tm && isFinite(tm.endTime) && el >= tm.endTime) { a.finish(); continue; }
      a.pause(); a.currentTime = el;
    }
  }
}
PROMO.start = (from = 0) => {
  offset = from; t0 = performance.now();
  for (const c of cues) if (c.b * BEAT < from) { c.done = true; try { c.fn(); } catch (e) { console.error(e); } }
  if (!RENDER) (function loop() { step(); requestAnimationFrame(loop); })();
};
PROMO.sync = (t) => { step(t); syncAnims(); };
function fit() { if (RENDER) return; const k = Math.min(innerWidth / 1920, innerHeight / 1080); stage.style.transform = 'scale(' + k + ')'; }
addEventListener('resize', fit); fit();
if (RENDER) document.documentElement.classList.add('render');
let loaded = 0;
decks.forEach((k) => k.frame.addEventListener('load', () => {
  k.W = k.frame.contentWindow; k.D = k.frame.contentDocument;
  const st = k.D.createElement('style'); st.textContent = PROMO_CSS; k.D.head.appendChild(st);
  if (RENDER) k.D.startViewTransition = undefined;              // view transitions run off the virtual clock
  const S = k.W.eval('S'); S.widgets = false; S.hud.show = false; k.W.render();
  k.D.querySelectorAll('#notes .nt').forEach((n) => n.remove());
  if (++loaded < 2) return;
  script(); tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step(0);
  if (DEBUG) { const d = document.createElement('div'); d.className = 'dbg'; stage.appendChild(d); setInterval(() => { d.textContent = 'b' + (PROMO.t / BEAT).toFixed(2); }, 50); }
  PROMO.ready = true;
}));
$('#play').addEventListener('click', async () => {
  $('#play').remove();
  const from = +(new URLSearchParams(location.search).get('t') || 0);
  try {
    actx = new AudioContext();
    const buf = await (await fetch('out/soundtrack.wav')).arrayBuffer();
    const src = actx.createBufferSource(); src.buffer = await actx.decodeAudioData(buf); src.connect(actx.destination);
    audio = { start: actx.currentTime + .1 }; src.start(audio.start, from);
    PROMO.start(from);
  } catch (e) { console.warn('no soundtrack, playing silent', e); actx = null; audio = null; PROMO.start(from); }
});
