/* Tandem promo: a beat-locked timeline that drives the live app (in #app) and a virtual camera over it.
   Everything is a pure function of the master time t (seconds), so the same page plays in real time with the
   soundtrack (preview) or frame by frame on Playwright's fake clock (render.mjs). Times are written in beats. */
'use strict';
const BPM = 124, BEAT = 60 / BPM, END = 108;              // beats; music.py uses the same grid
const RENDER = location.search.includes('render');
const $ = (s, r) => (r || document).querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, p) => a + (b - a) * p;
const E = {
  lin: (p) => p,
  out: (p) => 1 - Math.pow(1 - p, 3),
  inOut: (p) => (p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  expo: (p) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  expoIn: (p) => (p <= 0 ? 0 : Math.pow(2, 10 * p - 10)),
  expoInOut: (p) => (p <= 0 ? 0 : p >= 1 ? 1 : p < .5 ? Math.pow(2, 20 * p - 10) / 2 : (2 - Math.pow(2, -20 * p + 10)) / 2),
  back: (p) => 1 + 2.2 * Math.pow(p - 1, 3) + 1.2 * Math.pow(p - 1, 2)
};
const stage = $('#stage'), cam = $('#cam'), rig = $('#rig'), fxEl = $('#fx'), flashEl = $('#flash'), glowEl = $('#glow'), frame = $('#app');
let W = null, D = null;                                     // the app's window / document
const A = (s) => D && D.querySelector(s);
const AS = () => W.eval('S');                                // the app's state (a top-level const, not on window)
const IW = 1600, IH = 1000;                                 // the app's viewport inside the frame

/* ---------- camera ---------- */
// x,y: the app point (frame px) shown at screen point (ax, ay); s: zoom; rx/ry/rz: tilt (deg); z: dolly (px);
// o: app opacity; bl: blur (px). Tweens start from wherever the camera is when their cue fires.
const CAM = { x: 800, y: 500, s: 1, ax: 960, ay: 540, rx: 0, ry: 0, rz: 0, z: 0, o: 0, bl: 0 };
const KEYS = Object.keys(CAM);
let tweens = [], shakes = [], flashes = [], fx = [], glow = { v: 0, to: 0 };
function rectOf(sel) {
  const el = typeof sel === 'string' ? A(sel) : sel; if (!el) { console.warn('promo: no target', sel); return null; }
  const r = el.getBoundingClientRect(); if (location.search.includes('debug')) console.warn('rect', sel, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)); return { x: r.x, y: r.y, w: r.width, h: r.height };
}
// focus(sel, {fill, s, at, dx, dy}): centre on an element; fill = share of the frame it should occupy
function focus(sel, o = {}) {
  const r = rectOf(sel); if (!r) return {};
  const fill = o.fill || .82;
  const s = o.s || Math.min(1920 * fill / r.w, 1080 * fill / r.h);
  const at = o.at || [960, 540];
  return { x: r.x + r.w * (o.px ?? .5) + (o.dx || 0), y: r.y + r.h * (o.py ?? .5) + (o.dy || 0), s, ax: at[0], ay: at[1] };
}
function camTo(b, dur, to, ease = E.expoInOut) { tweens.push({ b, dur, to, ease, from: null, res: null }); }
function camSet(b, to) { camTo(b, 0, to, E.lin); }
function shake(b, amp = 10, beats = 1) { shakes.push({ b, amp, beats }); }
function flash(b, v = .9, beats = 1) { flashes.push({ b, v, beats }); }
function applyCam(t) {
  for (const tw of tweens) {
    const t0 = tw.b * BEAT; if (t < t0) continue;
    if (!tw.res) {
      tw.from = Object.assign({}, CAM); tw.res = Object.assign({}, typeof tw.to === 'function' ? tw.to() : tw.to);
      // a newer move owns its keys: older moves still running let go of them
      for (const o of tweens) if (o !== tw && o.res && !o.done) for (const k in tw.res) delete o.res[k];
    }
    const p = tw.dur ? clamp((t - t0) / (tw.dur * BEAT)) : 1;
    if (tw.done) continue;
    const e = tw.ease(p);
    for (const k in tw.res) CAM[k] = lerp(tw.from[k], tw.res[k], e);
    if (p >= 1) tw.done = true;
  }
  let sx = 0, sy = 0, sr = 0;
  for (const s of shakes) {
    const d = (t - s.b * BEAT) / (s.beats * BEAT); if (d < 0 || d > 1) continue;
    const a = s.amp * Math.pow(1 - d, 2.2);
    sx += a * Math.sin(d * 71); sy += a * Math.cos(d * 53); sr += a * .02 * Math.sin(d * 37);
  }
  const c = CAM;
  cam.style.transform = 'perspective(2200px) translate3d(' + sx.toFixed(2) + 'px,' + sy.toFixed(2) + 'px,' + c.z.toFixed(1) + 'px) rotateX(' + c.rx.toFixed(3) + 'deg) rotateY(' + c.ry.toFixed(3) + 'deg) rotateZ(' + (c.rz + sr).toFixed(3) + 'deg)';
  rig.style.transform = 'translate(' + (c.ax - c.x * c.s).toFixed(2) + 'px,' + (c.ay - c.y * c.s).toFixed(2) + 'px) scale(' + c.s.toFixed(4) + ')';
  rig.style.opacity = c.o.toFixed(3);
  rig.style.filter = c.bl > .05 ? 'blur(' + c.bl.toFixed(2) + 'px)' : 'none';
  let fl = 0;
  for (const f of flashes) { const d = (t - f.b * BEAT) / (f.beats * BEAT); if (d >= 0 && d <= 1) fl = Math.max(fl, f.v * Math.pow(1 - d, 2)); }
  flashEl.style.opacity = fl.toFixed(3);
}

/* ---------- kinetic type ---------- */
// show(b0, b1, html, {cls, style, anim, out}): an element that lives from beat b0 to b1; anim(el, p, tl) runs every frame
function show(b0, b1, html, o = {}) { if (o.scrim) scrim(b0 - .1, b1, o.scrim); fx.push({ b0, b1, html, o, el: null }); }
const ANIM = {
  // fade/blur/scale in over `inB` beats, out over `outB` beats
  pop: (inB = .5, outB = .35, from = 1.25) => (el, tl, life) => {
    const pi = E.expo(clamp(tl / (inB * BEAT))), po = clamp((life - tl) / (outB * BEAT));
    const s = lerp(from, 1, pi) * (1 + (1 - po) * .06);
    el.style.opacity = (pi * po).toFixed(3); el.style.filter = 'blur(' + ((1 - pi) * 18 + (1 - po) * 10).toFixed(1) + 'px)';
    el.style.transform = (el.dataset.base || '') + ' scale(' + s.toFixed(4) + ')';
  },
  slam: (from = 1.7) => (el, tl, life) => {
    const pi = E.expo(clamp(tl / (.28 * BEAT)));
    el.style.opacity = clamp(tl / (.08 * BEAT)).toFixed(3);
    el.style.transform = (el.dataset.base || '') + ' scale(' + lerp(from, 1, pi).toFixed(4) + ')';
    el.style.filter = 'blur(' + ((1 - pi) * 14).toFixed(1) + 'px)';
  },
  rise: (inB = .6, outB = .4, dy = 40) => (el, tl, life) => {
    const pi = E.expo(clamp(tl / (inB * BEAT))), po = E.out(clamp((life - tl) / (outB * BEAT)));
    el.style.opacity = (pi * po).toFixed(3);
    el.style.transform = (el.dataset.base || '') + ' translateY(' + ((1 - pi) * dy - (1 - po) * dy * .5).toFixed(1) + 'px)';
    el.style.filter = 'blur(' + ((1 - pi) * 10).toFixed(1) + 'px)';
  },
  // type the text of every [data-type] child one character per `cps`
  type: (cps = 26, outB = .4) => (el, tl, life) => {
    el.querySelectorAll('[data-type]').forEach((n) => { const s = n.dataset.type; const k = Math.floor(Math.max(0, tl - (+n.dataset.d || 0) * BEAT) * cps); n.textContent = s.slice(0, k); n.classList.toggle('cur', k < s.length); });
    el.style.opacity = E.out(clamp((life - tl) / (outB * BEAT))).toFixed(3);
  }
};
function scrim(b0, b1, side) { show(b0, b1, '', { cls: 'scrim ' + (side || 'l'), base: '', anim: (el, tl, life) => { el.style.opacity = (E.out(clamp(tl / (.6 * BEAT))) * clamp((life - tl) / (.4 * BEAT))).toFixed(3); } }); }
function caption(b0, b1, n, title, sub, o = {}) {
  scrim(b0 - .2, b1 + .2, o.r ? 'r' : 'l');
  show(b0, b1, '<span class="eb">' + n + '</span><span class="t">' + title + '</span>' + (sub ? '<span class="s">' + sub + '</span>' : ''), Object.assign({ cls: 'cap' + (o.r ? ' r' : '') + (o.top ? ' top' : ''), anim: ANIM.rise(.7, .4, 36) }, o));
}
function applyFx(t) {
  for (const f of fx) {
    const t0 = f.b0 * BEAT, t1 = f.b1 * BEAT, live = t >= t0 && t < t1;
    if (live && !f.el) {
      f.el = document.createElement('div'); f.el.className = 'k ' + (f.o.cls || 'c'); f.el.innerHTML = f.html;
      if (f.o.style) f.el.setAttribute('style', f.o.style);
      f.el.dataset.base = f.o.base ?? ((f.o.cls || 'c') === 'c' ? 'translate(-50%,-50%)' : '');
      fxEl.appendChild(f.el);
    }
    if (!live && f.el) { f.el.remove(); f.el = null; }
    if (f.el) (f.o.anim || ANIM.pop())(f.el, t - t0, t1 - t0);
    if (f.el && f.o.tick) f.o.tick(f.el, t - t0);
  }
}

/* ---------- app cues ---------- */
const cues = [];
function at(b, fn) { cues.push({ b, fn, done: false }); }
const app = {
  go: (r) => { W.closeOverlay && W.closeOverlay(); W.closeModal && W.closeModal(); W.go(r); },
  click: (sel) => { const el = A(sel); if (el) el.click(); else console.warn('promo: no click target', sel); },
  clearNotes: () => D.querySelectorAll('#notes .nt').forEach((n) => n.remove()),
  chrome: (mbar, widgets) => { D.documentElement.classList.toggle('promo-mbar', !!mbar); AS().widgets = !!widgets; AS().hud.show = false; W.render(); },
  scroll: (sel, b0, b1, from, to) => { scrolls.push({ sel, b0, b1, from, to }); }
};
const scrolls = [];
function applyScroll(t) {
  for (const s of scrolls) {
    const p = (t / BEAT - s.b0) / (s.b1 - s.b0); if (p < 0 || p > 1.02) continue;
    const el = A(s.sel); if (el) el.scrollTop = lerp(s.from, s.to, E.inOut(clamp(p)));
  }
}
const PROMO_CSS = 'html,body,.desk{background:transparent!important}.desk .wall{display:none!important}' +
  'html:not(.promo-mbar) .mbar{opacity:0!important;pointer-events:none}.tip{display:none!important}' +
  '.desk .win{box-shadow:0 0 0 .5px rgba(255,255,255,.18),0 40px 120px rgba(0,0,0,.6)!important}';

/* ============================== the script ============================== */
// 0–8 cold open · 8–16 logo + window fly-in · 16–32 drop: overview · 32–38 DIMV slams · 38–48 persona
// 48–64 trajectory · 64–72 ask / build · 72–88 drop: montage · 88–96 hero · 96–108 end card
function script() {
  // --- cold open: the five agents, one per beat
  const AGS = [['Claude Code', 'var(--a1)'], ['Codex', 'var(--a2)'], ['Gemini CLI', 'var(--a3)'], ['DeepSeek Harness', 'var(--a4)'], ['Copilot CLI', 'var(--a5)']];
  AGS.forEach((a, i) => show(i * .75, i < 4 ? i * .75 + .75 : 4, '<span class="agent"><i style="background:' + a[1] + '"></i>' + a[0] + '</span>', { anim: ANIM.slam(1.12) }));
  show(4, 6, '<div class="h2">每天，你和 <b style="color:var(--a1)">5</b> 个 Agent 协作上百次</div>', { anim: ANIM.pop(.6, .3, 1.08) });
  show(6, 7.85, '<div class="h2">可你看见过<span class="serif" style="font-style:italic">自己</span>的协作方式吗？</div>', { anim: ANIM.pop(.5, .2, 1.1) });

  // --- logo
  flash(8, 1, 1.5); shake(8, 0, 1);
  show(8, 12, '<img class="mark" src="mark.svg" alt="">', { cls: 'c', style: 'margin-top:-70px', anim: (el, tl, life) => {
    const pi = E.expo(clamp(tl / (1.2 * BEAT))), po = clamp((life - tl) / (.5 * BEAT));
    el.style.opacity = (pi * po).toFixed(3); el.style.filter = 'blur(' + ((1 - pi) * 20 + (1 - po) * 14).toFixed(1) + 'px)';
    el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(1.6, 1, pi) * (1 + tl * .02) * (1 + (1 - po) * .8)).toFixed(4) + ')';
  } });
  show(9, 12, '<div class="word">Tandem</div>', { style: 'margin-top:150px', anim: ANIM.rise(.8, .5, 30) });
  show(10, 12, '<div class="eb" style="letter-spacing:.42em">see how you work with agents</div>', { style: 'margin-top:240px', anim: ANIM.rise(.8, .5, 20) });

  // --- window flies in from depth (b12–16)
  at(12, () => { app.chrome(false, false); app.go('overview'); app.clearNotes(); });
  camSet(11.99, () => Object.assign(focus('#win', { fill: .9 }), { rx: 52, ry: -28, rz: 14, z: -2600, o: 0, bl: 12 }));
  camTo(12, 4, () => Object.assign(focus('#win', { fill: .86 }), { rx: 0, ry: 0, rz: 0, z: 0, o: 1, bl: 0 }), E.expo);
  glowAt(12, 1);

  // --- drop 1: overview (b16–32)
  at(16, () => app.go('overview'));
  flash(16, .35, .75); shake(16, 14, 1);
  camTo(16, 4, () => focus('#win', { fill: .76, at: [1200, 540] }), E.out);
  caption(16.5, 19.6, '01 · Overview', '一屏看懂近 30 天的协作', '186 个会话 · 5 个 Agent · 9 个项目');
  // KPI row with fresh count-ups
  at(19.75, () => app.go('overview'));
  camTo(20, .75, () => focus('.vz-kpi:nth-of-type(3)', { s: 2.15, dy: 0 }), E.expo);
  camTo(20.75, 3.25, () => ({ x: CAM.x + 60, s: CAM.s * 1.04 }), E.lin);
  shake(20, 8, .6);
  // Agent trend chart, switch stacked → grouped on the beat
  camTo(24, .75, () => focus('#main .card.pad:not(.ov-ai):not(.ov-pers)', { fill: .8, at: [1220, 540] }), E.expo);
  caption(24.3, 27.8, 'Agents', '五个 Agent，一张图对齐', null, { style: 'left:96px;bottom:84px;max-width:560px' });
  at(26, () => app.click('[data-act="stackMode"][data-v="pct"]') );
  at(27, () => app.click('[data-act="stackMode"][data-v="stacked"]') );
  // AI read-out regenerates (purple typing)
  camTo(28, .75, () => focus('#aiCard', { px: .14, s: 2.9, at: [1180, 560] }), E.expo);
  at(28.25, () => app.click('#aiCard [data-act="regen"]'));
  glowAt(28, 0);
  camTo(31.25, .75, () => Object.assign(focus('#aiCard', { px: .14, s: 4.2 }), { rz: -12, bl: 16, o: 0 }), E.expoIn);

  // --- DIMV slams (b32–38)
  const DIMV = [['D', '委托', '72'], ['I', '即兴', '61'], ['M', '多线', '73'], ['V', '求证', '67']];
  DIMV.forEach((d, i) => { const b = 32 + i; show(b, b + 1, '<div class="letter">' + d[0] + '</div>', { anim: ANIM.slam(1.9), style: 'margin-top:-60px' }); show(b, b + 1, '<div class="mono" style="font-size:40px;color:rgba(255,255,255,.7);letter-spacing:.2em">' + d[1] + ' ' + d[2] + '</div>', { style: 'margin-top:270px', anim: ANIM.rise(.3, .1, 16) }); flash(b, .22, .5); });
  show(36, 38, '<div class="letter" style="font-size:300px;letter-spacing:.06em">DIMV</div>', { anim: ANIM.slam(1.35), style: 'margin-top:-80px' });
  show(36.5, 38, '<div class="h2 serif">指挥家 <i style="font-weight:400;color:rgba(255,255,255,.6)">The Conductor</i></div>', { style: 'margin-top:150px', anim: ANIM.rise(.6, .3, 24) });
  shake(36, 0, 1); flash(36, .5, .8);

  // --- persona reveal (b38–48)
  at(37.9, () => { app.go('persona'); W.openReveal(); });
  camSet(37.95, () => Object.assign(focus('#revBox', { fill: .78, at: [1220, 540] }), { rz: 6, z: -400, o: 0, bl: 10, rx: 0, ry: 0 }));
  camTo(38, 1.5, () => Object.assign(focus('#revBox', { fill: .84, at: [1220, 540] }), { rz: 0, z: 0, o: 1, bl: 0 }), E.expo);
  camTo(39.5, 4.5, () => ({ s: CAM.s * 1.12 }), E.inOut);
  caption(39, 43.6, '02 · Persona', '你的协作人格', '读取 186 个会话 · 排到 24 小时表盘 · 长出四个维度');
  at(44, () => app.go('persona'));
  camSet(43.99, () => Object.assign(focus('.persona-hero svg.fp2', { fill: .8, at: [1180, 540] }), { rz: -16, o: 1 }));
  camTo(44, 2, () => Object.assign(focus('.persona-hero svg.fp2', { fill: .86, at: [1180, 540] }), { rz: 0 }), E.expo);
  flash(44, .3, .6); shake(44, 10, .8);
  caption(44.3, 47.7, 'Fingerprint', '协作指纹', '内核四维雷达 · 中环 24 小时节律 · 外环按 Agent 堆叠');
  camTo(46, 1.75, () => focus('.persona-hero', { fill: .95, px: .3, py: .28, s: 1.9 }), E.expoInOut);

  // --- trajectory replay (b48–64)
  at(48, () => app.go('sessions'));
  camSet(47.99, () => Object.assign(focus('.tl-card', { fill: .9 }), { rx: 0, ry: 30, z: -300, o: 1 }));
  camTo(48, 1.5, () => Object.assign(focus('.tl-card', { fill: .92, at: [1200, 540] }), { ry: 0, z: 0 }), E.expo);
  flash(48, .3, .6); shake(48, 10, .8);
  at(49, () => app.click('[data-act="playToggle"]'));
  caption(48.5, 55.5, '03 · Trajectory', '每个会话，逐秒回放', '纠偏 · 失败 · 上下文压缩，一条时间线看清卡在哪');
  camTo(52, 4, () => ({ s: CAM.s * 1.18, x: CAM.x + 40 }), E.inOut);
  // tilted pass over the session list
  camSet(55.99, () => Object.assign(focus('#main .card', { fill: .9, py: .3 }), { rx: 24, ry: -26, rz: 4, s: 1.9 }));
  at(56, () => app.scroll('#main .card .list, #main .card [class*="list"]', 56, 60, 0, 900));
  camTo(56, 4, () => ({ rx: 14, ry: -14, rz: 2, y: CAM.y + 60 }), E.inOut);
  flash(56, .25, .5);
  caption(56.3, 59.7, 'Sessions', '186 个会话，五个 Agent', '本地索引 2,416 个会话 · 实时', { r: true });
  // pull back to whole window while the build starts
  camTo(60, 4, () => Object.assign(focus('#win', { fill: .78 }), { rx: 0, ry: 0, rz: 0 }), E.inOut);

  // --- ask the local agent (b64–72, build)
  at(64, () => { W.openAsk('overview'); });
  at(64.6, () => app.click('[data-act="askPick"]'));
  camTo(64, 1.25, () => Object.assign(focus('#modal', { fill: .8, at: [1180, 540] }), { rz: 0 }), E.expo);
  glowAt(64, 1, '143,123,255');
  caption(64.5, 70.5, '04 · Ask', '问你自己的本地 Agent', '数据不出本机 · 0 B 上传 · 不调用云端模型');
  camTo(66, 5.5, () => ({ s: CAM.s * 1.25, rz: -3 }), E.expoIn);
  camTo(71.5, .5, () => ({ s: CAM.s * 2.2, bl: 24, o: 0 }), E.expoIn);
  glowAt(71.5, 0);

  // --- drop 2: montage, a cut every 2 beats (b72–88)
  at(71.9, () => { W.closeModal(); app.go('studio'); });
  camSet(71.95, () => Object.assign(focus('#main .card.pad.col:nth-of-type(2)', { fill: .8 }), { o: 1, bl: 0, rz: 0, z: 0 }));
  at(72, () => app.click('[data-act="studioStart"]'));
  flash(72, .6, .8); shake(72, 18, 1.2);
  show(72.1, 73.8, '<div class="h1">生成工坊</div>', { cls: 'cap', style: 'left:96px;bottom:84px', anim: ANIM.slam(1.3), scrim: 'l' });
  camTo(72, 2, () => ({ s: CAM.s * 1.08 }), E.out);

  at(74, () => app.go('recs'));
  camSet(73.99, () => focus('.rcard', { fill: .55, at: [760, 540] }));
  camTo(74, 2, () => ({ x: CAM.x + 40, s: CAM.s * 1.06 }), E.out);
  shake(74, 10, .6);
  show(74.1, 75.85, '<div class="h1">12 条建议</div><div class="h3 dim" style="margin-top:8px">每月省下 ≈ 20 小时</div>', { scrim: 'r', cls: 'cap r', style: 'right:96px;left:auto;bottom:84px;text-align:right', anim: ANIM.slam(1.3) });

  at(76, () => { W.setTheme('dark'); app.go('overview'); });
  camSet(75.99, () => Object.assign(focus('#win', { fill: .86 }), { ry: -18, rx: 6 }));
  camTo(76, 2, () => ({ ry: 0, rx: 0 }), E.expo);
  flash(76, .8, .7); shake(76, 12, .8);
  show(76.2, 77.85, '<div class="h1">深色模式</div>', { cls: 'cap', anim: ANIM.slam(1.3), scrim: 'l' });

  at(78, () => { W.setTheme('light'); W.edSet('lite'); });
  camSet(77.99, () => focus('#win', { fill: .86 }));
  camTo(78, 2, () => focus('#win', { fill: .9, px: .38 }), E.expo);
  flash(78, .5, .6); shake(78, 12, .8);
  show(78.3, 79.85, '<div class="h1">Lite <span class="dim">/</span> Advance</div><div class="h3 dim" style="margin-top:8px">一键切换 · ⌃⌘L</div>', { cls: 'cap', anim: ANIM.slam(1.3), scrim: 'l' });

  at(80, () => { W.edSet('advance'); app.chrome(true, false); W.simEvent('waiting'); });
  camSet(79.99, () => ({ x: 1360, y: 120, s: 1.9, ax: 1200, ay: 380 }));
  camTo(80, 2, () => ({ s: CAM.s * 1.08, y: CAM.y + 10 }), E.out);
  shake(80, 12, .8);
  show(80.2, 81.85, '<div class="h1">菜单栏常驻</div><div class="h3 dim" style="margin-top:8px">会话等你确认时，第一时间提醒</div>', { cls: 'cap', anim: ANIM.slam(1.3), scrim: 'l' });

  at(82, () => { app.clearNotes(); W.openPalette(); });
  camSet(81.99, () => focus('#modal, .pal, [class*="palette"]', { fill: .7 }));
  camTo(82, 2, () => ({ s: CAM.s * 1.06 }), E.out);
  shake(82, 10, .6);
  show(82.2, 83.85, '<div class="h1">⌘K</div><div class="h3 dim" style="margin-top:8px">任何页面、会话与操作</div>', { scrim: 'r', cls: 'cap r', style: 'right:96px;left:auto;bottom:84px;text-align:right', anim: ANIM.slam(1.3) });

  at(84, () => { W.closeModal(); AS().hud.show = true; AS().sim = 'running'; W.render(); });
  camSet(83.99, () => focus('#hud', { fill: .45, at: [1100, 600] }));
  camTo(84, 2, () => ({ s: CAM.s * 1.08 }), E.out);
  shake(84, 10, .6);
  show(84.2, 85.85, '<div class="h1">悬浮组件</div><div class="h3 dim" style="margin-top:8px">会话运行时，陪在桌面一角</div>', { cls: 'cap', anim: ANIM.slam(1.3), scrim: 'l' });

  at(86, () => { app.chrome(true, true); app.go('overview'); });
  camSet(85.99, () => focus('#widgets', { fill: .8, at: [760, 540] }));
  camTo(86, 2, () => ({ s: CAM.s * 1.06 }), E.out);
  shake(86, 10, .6);
  show(86.2, 87.85, '<div class="h1">桌面小组件</div><div class="h3 dim" style="margin-top:8px">人格 · 今日 · 本周 · 最值得做</div>', { scrim: 'r', cls: 'cap r', style: 'right:96px;left:auto;bottom:84px;text-align:right', anim: ANIM.slam(1.3) });

  // --- hero: the whole desktop, slow orbit (b88–96)
  camSet(87.99, () => ({ x: 800, y: 500, s: 1.02, ax: 960, ay: 540, rx: 18, ry: -24, rz: 3, z: -500 }));
  camTo(88, 8, () => ({ rx: 8, ry: 14, rz: -1, z: -120, s: 1.04 }), E.inOut);
  flash(88, .4, .8);
  glowAt(88, 1);
  show(89, 95.6, '<div class="eb" style="letter-spacing:.3em">local-first · read-only · 0 B uploaded</div>', { cls: 'cap', base: 'translateX(-50%)', style: 'left:50%;bottom:64px', anim: ANIM.rise(1, .6, 20) });
  camTo(95.5, .5, () => ({ o: 0, bl: 20, s: CAM.s * 1.3 }), E.expoIn);
  glowAt(95.5, 0);

  // --- end card (b96–108)
  flash(96, 1, 2); shake(96, 0, 1);
  show(96, 107.5, '<img class="mark" src="mark.svg" alt="">', { style: 'margin-top:-90px', anim: (el, tl, life) => {
    const pi = E.expo(clamp(tl / (1.5 * BEAT))), po = clamp((life - tl) / (2 * BEAT));
    el.style.opacity = (pi * po).toFixed(3); el.style.filter = 'blur(' + ((1 - pi) * 22).toFixed(1) + 'px)';
    el.style.transform = 'translate(-50%,-50%) scale(' + (lerp(1.5, 1, pi) * (1 + tl * .012)).toFixed(4) + ')';
  } });
  show(97, 107.5, '<div class="word">Tandem</div>', { style: 'margin-top:140px', anim: ANIM.rise(1, 2, 30) });
  show(98.5, 107.5, '<div class="h3" style="color:rgba(255,255,255,.75)">看见你与 Agent 的每一次协作</div>', { style: 'margin-top:240px', anim: ANIM.rise(1, 2, 20) });
  show(100.5, 107.5, '<div class="eb">for macOS · ActionMesh AI</div>', { style: 'margin-top:320px', anim: ANIM.rise(1, 2, 14) });
}
function glowAt(b, v, rgb) { at(b, () => { glow.to = v; glow.b = b; glow.from = glow.v; if (rgb) glowEl.style.background = 'radial-gradient(60% 55% at 50% 52%,rgba(' + rgb + ',.16),transparent 70%)'; else glowEl.style.background = ''; }); }
function applyGlow(t) { if (glow.b == null) return; const p = clamp((t / BEAT - glow.b) / 2); glow.v = lerp(glow.from, glow.to, E.inOut(p)); glowEl.style.opacity = glow.v.toFixed(3); }

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
  applyScroll(t); applyCam(t); applyFx(t); applyGlow(t);
}
// Pin every CSS animation/transition (here and in the app) to the virtual clock: each one is paused and its currentTime
// set from the moment it was first seen; finished ones are finished explicitly so animationend/transitionend still fire.
const SEEN = new WeakMap();
function syncAnims() {
  const n = performance.now();
  for (const doc of [document, D]) {
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
frame.addEventListener('load', () => {
  W = frame.contentWindow; D = frame.contentDocument;
  const st = D.createElement('style'); st.textContent = PROMO_CSS; D.head.appendChild(st);
  if (RENDER) D.startViewTransition = undefined;              // view transitions run off the virtual clock
  app.chrome(false, false); app.clearNotes();
  script(); tweens.sort((a, b) => a.b - b.b); cues.sort((a, b) => a.b - b.b); step();
  if (location.search.includes('debug')) { const d = document.createElement('div'); d.className = 'dbg'; stage.appendChild(d); setInterval(() => { d.textContent = 'b' + (PROMO.t / BEAT).toFixed(2); }, 50); }
  PROMO.ready = true;
});
$('#play').addEventListener('click', async () => {
  $('#play').remove();
  try {
    actx = new AudioContext();
    const buf = await (await fetch('out/soundtrack.wav')).arrayBuffer();
    const src = actx.createBufferSource(); src.buffer = await actx.decodeAudioData(buf); src.connect(actx.destination);
    const from = +(new URLSearchParams(location.search).get('t') || 0);
    audio = { start: actx.currentTime + .1 }; src.start(audio.start, from);
    PROMO.start(from); offset = from;
  } catch (e) { console.warn('no soundtrack, playing silent', e); actx = null; audio = null; PROMO.start(0); }
});
