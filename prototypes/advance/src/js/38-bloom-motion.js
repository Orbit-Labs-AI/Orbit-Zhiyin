/* ============ bloom motion: the persona flower folds and re-blooms when the shown type changes (both editions) ============ */
// Every surface keeps rendering plain markup; this layer compares each flower with the one it replaced and animates the change.
// Times are from the click; all of it is WAAPI on a few nodes (transform / opacity) plus one rAF loop that writes the band
// paths, and that loop reads its progress from a WAAPI clock, so pausing / seeking document.getAnimations() freezes the
// whole switch on one frame (the frame captures do that).
//   dial (svg.fp2 in #main, persona / l-persona; RENDER_HOOKS)
//     type changed   收起 0–350 ms: the old flower (a renamed copy kept behind the new one, .bm-*) turns toward the new type
//                    and folds into its heart while its petals twist 28° (ink ring 300 ms, the gray ring 50 ms behind,
//                    ease-in, fading in the last quarter); the heart swaps (ring ↔ dot) at the fold point.
//                    绽开 260–860 ms: the new petals unfold from the heart while the whole flower keeps turning the rest of
//                    the way to the new type and the petals untwist 32°, a slight overshoot (≈4 %) and settle; the gray
//                    ring trails the ink ring by 80 ms. The letters of the code that changed rise in with the bloom.
//     same type      the flower settles (a 5° turn back and a breath, 560 ms) when the flower or the bands moved — a
//                    re-render that changes nothing (hover, a type sector opened) plays nothing.
//     always         the Agent layers morph from the old to the new curves (every number of each path blended, 560 ms,
//                    ease-in-out; layer paths are sampled at fixed angles, so blending the path is blending the radii —
//                    whether the layers are stacked or each drawn from the baseline); new layers fade in, gone layers fade
//                    out from their old shape; the badges glide along the orbit to their new mean angles (shortest arc,
//                    40 ms apart, the logo counter-turns to stay upright); the --orbit triangle turns to the new type
//                    (760 ms, shortest arc, a small settle); the 16 codes on the bezel stay, only the emphasis moves from the
//                    old type's code to the new one (old fades to gray from 60 ms, new darkens from 420 ms as the triangle lands).
//     page entry     the damped sway (.fp-bd) + band sweep + badge run (41-a2-persona.js), with the petals opening from the
//                    Genesis bud (FPG.BUD) under the sway. A dial that appears in place (data arrived) only blooms.
//                    Lite ↔ Advance: the other edition's dial is the "old" one, so a type change folds / re-blooms and an
//                    unchanged dial plays the entry as before. Nothing plays while the Genesis overlay is open (OVL).
//   small flowers (glyphSVG svg[data-bloom] anywhere — menubar panel, widgets, share span list, method table — and the
//     flower on the share card svg[data-span]; RENDER_HOOKS in #main, a MutationObserver elsewhere): the same fold / unfold,
//     quicker (fold 170 ms, unfold 150–520 ms), when the type at the same place changes. Hover turn is CSS (43-bloom-motion.css).
//   type codes (the persona letters [data-hero="code"], the overview code .ov-code-l, the sidebar user row): the letters
//     that changed rise in (380 ms from 80 ms, 45 ms apart), landing as the new flower opens.
// prefers-reduced-motion: no fold, no morph, no glide — the new flower cross-fades in (160 ms) and everything else is instant.
const BM = { snap: new Map(), small: new WeakMap(), codes: new Map(), ed: null };
const BM_IN = 'cubic-bezier(.55,.06,.8,.4)', BM_OUT = 'cubic-bezier(.22,.7,.28,1)', BM_IO = 'cubic-bezier(.45,.05,.3,1)';
const BM_SMALL = 'svg[data-bloom], svg[data-span]';
const BM_O = '200px 200px';
const bmDelta = (a, b) => ((b - a) % 360 + 540) % 360 - 180;
// the ghost of an old flower: same markup, classes renamed so selectors and CSS for the live flower never see it
const bmGhost = (html) => '<g class="bm-ghost" aria-hidden="true">' + html.replace(/<title>[\s\S]*?<\/title>/g, '').replace(/class="([^"]*)"/g, (m, c) => 'class="' + c.replace(/\bfp-/g, 'bm-') + '"') + '</g>';
// remove a ghost once its animations are over (also settles in a throttled tab; waits while a capture holds them paused)
function bmDrop(el, ms) {
  let t = 0;
  const kill = () => { clearTimeout(t); el.remove(); };
  const check = () => { if (!el.isConnected) return; if (el.getAnimations && el.getAnimations({ subtree: true }).some((a) => a.playState === 'paused')) { t = setTimeout(check, 400); return; } kill(); };
  t = setTimeout(check, ms + 400);
  return kill;
}

/* ---------- keyframes ---------- */
// fold into the heart: turn, shrink to `to`, fade in the last quarter
function bmFold(el, o) {
  if (!el || !el.animate) return null;
  return el.animate([{ transform: 'rotate(0deg) scale(1)', opacity: 1, transformOrigin: o.origin }, { opacity: 1, offset: 0.72 },
    { transform: 'rotate(' + o.turn + 'deg) scale(' + (o.to || 0.06) + ')', opacity: 0, transformOrigin: o.origin }],
  { duration: o.dur, delay: o.delay || 0, easing: BM_IN, fill: 'both' });
}
// unfold from the heart: untwist into place with a slight overshoot (scale `over` at 62 %) and settle
function bmOpen(el, o) {
  if (!el || !el.animate) return null;
  const t = o.turn || 0, from = o.from == null ? 0.06 : o.from;
  return el.animate([{ transform: 'rotate(' + (-t) + 'deg) scale(' + from + ')', opacity: from >= 0.3 ? 1 : 0, transformOrigin: o.origin },
    { opacity: 1, offset: 0.16 }, { transform: 'rotate(' + (t * 0.08).toFixed(2) + 'deg) scale(' + (o.over || 1.045) + ')', offset: 0.62, transformOrigin: o.origin },
    { transform: 'rotate(0deg) scale(1)', opacity: 1, transformOrigin: o.origin }],
  { duration: o.dur, delay: o.delay || 0, easing: BM_OUT, fill: 'backwards' });
}
// heart swap at the fold point: the old heart fades, the new one pops
function bmHeart(nh, gh, at, origin, dur) {
  if (gh && gh.animate) gh.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 110, delay: at - 40, fill: 'both' });
  if (nh && nh.animate) nh.animate([{ transform: 'scale(.4)', opacity: 0, transformOrigin: origin }, { transform: 'scale(1.14)', opacity: 1, offset: 0.55, transformOrigin: origin },
    { transform: 'scale(1)', opacity: 1, transformOrigin: origin }], { duration: dur || 320, delay: at - 40, easing: BM_OUT, fill: 'backwards' });
}
// a gentle settle (same type, different numbers)
function bmSettle(els, origin, s) {
  els.forEach((el, i) => { if (el && el.animate) el.animate([{ transform: 'rotate(' + (-5 * s) + 'deg) scale(.95)', transformOrigin: origin }, { transform: 'rotate(' + s + 'deg) scale(1.015)', offset: 0.6, transformOrigin: origin }, { transform: 'none', transformOrigin: origin }], { duration: 560, delay: i * 60, easing: BM_OUT }); });
}

/* ---------- path morph (bands) ---------- */
// every number of the old path blended into the new one; only when both have the same commands and count (fixed-angle samples)
const BM_NUM = /-?\d*\.?\d+(?:e[-+]?\d+)?/g;
function bmParse(d) { return { n: (d.match(BM_NUM) || []).map(Number), s: d.split(BM_NUM) }; }
function bmTween(items, dur, delay) {
  if (!items.length) return;
  // the clock is an empty WAAPI animation on the first path: the loop reads its time, so it pauses / seeks with the rest
  const clock = items[0].el.animate([], { duration: dur, delay: delay || 0, fill: 'both' });
  let done = false, t = 0;
  const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const draw = (e) => items.forEach((it) => {
    let d = ''; for (let i = 0; i < it.b.length; i++) d += it.s[i] + (it.a[i] + (it.b[i] - it.a[i]) * e).toFixed(1);
    it.el.setAttribute('d', d + it.s[it.b.length]);
  });
  const end = () => { if (done) return; done = true; clearTimeout(t); items.forEach((it) => it.el.setAttribute('d', it.fin)); };
  const step = () => {
    if (done) return;
    if (!items.some((it) => it.el.isConnected) || clock.playState === 'idle') { done = true; return; }
    if (clock.playState === 'finished') { end(); return; }
    draw(ease(Math.min(1, Math.max(0, ((clock.currentTime || 0) - (delay || 0)) / dur)))); requestAnimationFrame(step);
  };
  const guard = () => { if (done) return; if (clock.playState === 'paused') { t = setTimeout(guard, 400); return; } end(); };
  clock.finished.then(end, () => {}); t = setTimeout(guard, (delay || 0) + dur + 600);
  draw(0); requestAnimationFrame(step);
}

/* ---------- dial ---------- */
// the Agent layers of the orbit: every path with data-a inside the orbit group (stacked bands or per-Agent curves alike)
const bmLayers = (svg) => Array.from(svg.querySelectorAll('.fp-orbw path[data-a]'));
const bmLayerKey = (p) => (p.getAttribute('class') || '') + ':' + p.dataset.a;
function bmDialSnap(svg) {
  const fl = svg.querySelector('.fp-flower'), bl = svg.querySelector('.fp-bloom'), h = svg.querySelector('.fp-heart');
  const paths = new Map(); bmLayers(svg).forEach((p) => paths.set(bmLayerKey(p), { d: p.getAttribute('d'), html: p.outerHTML, host: p.parentNode.getAttribute('class') || '' }));
  const pl = new Map(); svg.querySelectorAll('.fp-pl').forEach((g) => pl.set(g.dataset.a, +g.dataset.pa));
  const me = svg.querySelector('.fp-code.me');
  return { code: fl ? fl.dataset.code : '', hd: bl ? +bl.dataset.hd : 0, fl: fl ? fl.outerHTML.replace(/<title>[\s\S]*?<\/title>/, '') : '', heart: h ? h.innerHTML : '', paths, pl, me: me ? me.dataset.t : null };
}
// entry: the existing sway + band sweep + badge run, with the petals opening from the bud underneath; soft = bloom only
function bmEnter(svg, soft) {
  if (!svg || reduceMotion()) return;
  if (!soft) { fpWobble(svg); fpOrbitIn(svg); }
  bmOpen(svg.querySelector('.fp-front'), { origin: BM_O, dur: soft ? 600 : 820, from: soft ? 0.06 : FPG.BUD, turn: soft ? 32 : 0, over: 1.05 });
  bmOpen(svg.querySelector('.fp-back'), { origin: BM_O, dur: soft ? 600 : 820, delay: soft ? 80 : 120, from: soft ? 0.06 : FPG.BUD, turn: soft ? 32 : 0, over: 1.05 });
}
// old → new on the same dial; returns true when something moved
function bmDial(svg, old, now) {
  const reduce = reduceMotion(); let moved = false;
  const nf = svg.querySelector('.fp-flower'), d = bmDelta(old.hd, now.hd), s = d < 0 ? -1 : 1;
  const bands = bmLayers(svg).some((p) => { const o = old.paths.get(bmLayerKey(p)); return !o || o.d !== p.getAttribute('d'); }) || old.paths.size !== bmLayers(svg).length;
  if (nf && old.code !== now.code) {
    moved = true;
    if (reduce) nf.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease-out' });
    else {
      nf.insertAdjacentHTML('beforebegin', bmGhost(old.fl));
      const gh = nf.previousElementSibling; bmDrop(gh, 360);
      // the whole flower turns toward the new type with the triangle: the ghost covers the first 30 % while folding, the new
      // flower the rest while it unfolds
      const gb = gh.querySelector('.bm-bloom'), nb = nf.querySelector('.fp-bloom');
      if (gb && gb.animate && d) gb.animate([{ transform: 'rotate(' + old.hd + 'deg)' }, { transform: 'rotate(' + (old.hd + d * 0.3).toFixed(2) + 'deg)' }], { duration: 300, easing: BM_IN, fill: 'both' });
      if (nb && nb.animate && d) nb.animate([{ transform: 'rotate(' + (now.hd - d * 0.7).toFixed(2) + 'deg)' }, { transform: 'rotate(' + now.hd + 'deg)' }], { duration: 600, delay: 260, easing: BM_OUT, fill: 'backwards' });
      bmFold(gh.querySelector('.bm-front'), { origin: BM_O, dur: 300, turn: 28 * s });
      bmFold(gh.querySelector('.bm-back'), { origin: BM_O, dur: 300, delay: 50, turn: 28 * s });
      bmOpen(nf.querySelector('.fp-front'), { origin: BM_O, dur: 520, delay: 260, turn: 32 * s });
      bmOpen(nf.querySelector('.fp-back'), { origin: BM_O, dur: 520, delay: 340, turn: 32 * s });
      if (old.heart !== now.heart) bmHeart(nf.querySelector('.fp-heart'), gh.querySelector('.bm-heart'), 270, BM_O);
      else { const g2 = gh.querySelector('.bm-heart'); if (g2) g2.style.display = 'none'; }
    }
  } else if (nf && (old.fl !== now.fl || bands) && !reduce) {
    moved = true;   // same type, other numbers: a gentle settle
    bmSettle(Array.from(nf.querySelectorAll('.fp-pw')), BM_O, s);
  }
  if (reduce) return moved || bands;
  // the --orbit triangle (an SVG transform attribute: rotate(hd 200 200)) turns along the shortest arc with a small settle
  const n0 = svg.querySelector('.fp-n0');
  if (n0 && n0.animate && d) {
    moved = true;
    n0.animate([{ transform: 'rotate(' + (now.hd - d) + 'deg)', transformOrigin: BM_O }, { transform: 'rotate(' + (now.hd + d * 0.04).toFixed(2) + 'deg)', offset: 0.78, transformOrigin: BM_O }, { transform: 'rotate(' + now.hd + 'deg)', transformOrigin: BM_O }], { duration: 760, easing: BM_IO });
  }
  // the 16 type codes on the bezel stay put; only the emphasis (ink-1, bold) moves from the old type's code to the new one,
  // the old fading back to gray as the triangle leaves it and the new one darkening as it arrives
  if (old.me !== now.me) {
    const nm = svg.querySelector('.fp-code.me'), om = old.me != null ? svg.querySelector('.fp-code[data-t="' + old.me + '"]') : null;
    if (om && om.animate) { moved = true; om.animate([{ fill: 'var(--ink-1)', fontWeight: 800 }, { fill: 'var(--ink-3)', fontWeight: 600 }], { duration: 380, delay: 60, easing: 'ease-out', fill: 'backwards' }); }
    if (nm && nm.animate) { moved = true; nm.animate([{ fill: 'var(--ink-3)', fontWeight: 600, opacity: 0.55 }, { fill: 'var(--ink-1)', fontWeight: 800, opacity: 1 }], { duration: 420, delay: 420, easing: 'ease-out', fill: 'backwards' }); }
  }
  // layers: blend each Agent's path; Agents that appear fade in, Agents that left fade out from their old shape
  const items = [];
  bmLayers(svg).forEach((p) => {
    const o = old.paths.get(bmLayerKey(p)), nd = p.getAttribute('d');
    if (!o) { moved = true; p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, delay: 120, easing: 'ease-out', fill: 'backwards' }); return; }
    if (o.d === nd) return;
    const A = bmParse(o.d), B = bmParse(nd);
    if (A.n.length !== B.n.length || A.s.join('|') !== B.s.join('|')) { moved = true; p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: 'ease-out' }); return; }
    items.push({ el: p, a: A.n, b: B.n, s: B.s, fin: nd });
  });
  old.paths.forEach((o, k) => {
    if (bmLayers(svg).some((p) => bmLayerKey(p) === k)) return;
    const host = (o.host && svg.querySelector('.fp-orbw .' + o.host.split(/\s+/)[0])) || svg.querySelector('.fp-orb'); if (!host) return;
    host.insertAdjacentHTML('beforeend', o.html.replace(/data-a="[^"]*"/, 'data-bm="gone"')); const g = host.lastElementChild; moved = true;
    g.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 360, easing: 'ease-in', fill: 'forwards' }); bmDrop(g, 360);
  });
  if (items.length) { moved = true; bmTween(items, 560); }
  // badges glide along the orbit (outer group turns, the logo counter-turns to stay upright)
  let gi = 0;
  svg.querySelectorAll('.fp-pl').forEach((g) => {
    const to = +g.dataset.pa, from0 = old.pl.get(g.dataset.a);
    if (from0 == null) { moved = true; g.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, delay: 260, easing: 'ease-out', fill: 'backwards' }); return; }
    const dd = bmDelta(from0, to); if (Math.abs(dd) < 0.3) return;
    moved = true; const from = to - dd, pd = g.querySelector('.fp-pd'), o = { duration: 640, delay: gi++ * 40, easing: BM_IO, fill: 'backwards' };
    g.animate([{ transform: 'rotate(' + from + 'deg)' }, { transform: 'rotate(' + to + 'deg)' }], o);
    if (pd) pd.animate([{ transform: 'rotate(' + (-from) + 'deg)' }, { transform: 'rotate(' + (-to) + 'deg)' }], o);
  });
  return moved;
}

/* ---------- type codes ---------- */
// the letters that changed rise in; a plain-text code is split into letter spans first (same text, same layout)
function bmCode(el, key, delay) {
  if (!el) return;
  let Ls = Array.from(el.querySelectorAll('.L'));
  const now = (Ls.length ? Ls.map((x) => x.textContent).join('') : el.textContent).trim(), old = BM.codes.get(key); BM.codes.set(key, now);
  if (old == null || old === now || old.length !== now.length || /[?？—]/.test(old + now) || reduceMotion()) return;
  if (!Ls.length) {
    if (el.children.length) return;
    el.innerHTML = now.split('').map((c) => '<span class="bm-l">' + esc(c) + '</span>').join(''); Ls = Array.from(el.children);
  }
  Ls.forEach((x, i) => {
    if (old[i] === now[i] || !x.animate) return;
    x.animate([{ opacity: 0, transform: 'translateY(.22em) scale(.94)' }, { opacity: 1, transform: 'none' }], { duration: 380, delay: (delay || 0) + i * 45, easing: BM_OUT, fill: 'backwards' });
  });
}
function bmCodes(m, entered) {
  if (entered) Array.from(BM.codes.keys()).forEach((k) => { if (k.startsWith('main|')) BM.codes.delete(k); });
  $$('[data-hero="code"], .ov-code-l', m).forEach((el, i) => { if (!el.closest('[data-hero="code"]') || el.matches('[data-hero="code"]')) bmCode(el, 'main|' + S.route + '|' + i, 80); });
}

/* ---------- small flowers ---------- */
// parts of a small flower: the glyph svg itself, or the flower group on the share card (drawn from the 80-unit glyph, heart at 40,40)
function bmSmallParts(svg) {
  if (svg.hasAttribute('data-bloom')) return { box: svg, own: true, code: svg.getAttribute('data-bloom'), front: '.fp-pet', back: '.fp-bk', heart: 'circle' };
  const c = svg.querySelector('g > circle[cx="40"][cy="40"]'); if (!c) return null;
  return { box: c.parentNode, own: false, code: svg.getAttribute('data-code') || '', front: 'path:last-of-type', back: 'path:first-of-type:not(:last-of-type)', heart: 'circle' };
}
// snapshots per place: the nearest element with an id (#main per route, #shareBody per open dialog, #pop, the widgets…),
// then the flower's index among the same kind there and its size
function bmSmallSlot(svg, kind) {
  const inMain = svg.closest('#main'), root = inMain || (svg.parentElement && svg.parentElement.closest('[id]')) || document.body;
  let m = BM.small.get(root); if (!m) { m = new Map(); BM.small.set(root, m); }
  const sib = root.querySelectorAll(kind === 'glyph' ? 'svg[data-bloom]' : 'svg[data-span]');
  return { m, key: kind + '|' + Array.prototype.indexOf.call(sib, svg) + '|' + (svg.getAttribute('width') || '') + (inMain ? '|' + S.route : '') };
}
function bmSmall(svg, fresh) {
  if (svg.closest('#overlay, .g-fly, .bm-ghost')) return;
  const q = bmSmallParts(svg); if (!q) return;
  const slot = bmSmallSlot(svg, q.own ? 'glyph' : 'card'), old = slot.m.get(slot.key);
  const html = q.own ? svg.innerHTML : q.box.outerHTML;
  slot.m.set(slot.key, { code: q.code, html });
  if (fresh || !old || old.code === q.code || !old.html || svg.getClientRects().length === 0) return;
  const O = '40px 40px', all = (root, sel) => (sel ? Array.from(root.querySelectorAll(':scope > ' + sel)) : []);
  if (reduceMotion()) { q.box.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease-out' }); return; }
  let gh;
  if (q.own) { svg.insertAdjacentHTML('afterbegin', bmGhost(old.html)); gh = svg.firstElementChild; } else { q.box.insertAdjacentHTML('beforebegin', bmGhost(old.html)); gh = q.box.previousElementSibling.firstElementChild; }
  bmDrop(q.own ? gh : gh.parentNode, 260);
  const ren = (sel) => sel && sel.replace(/\.fp-/g, '.bm-');
  all(gh, ren(q.front)).forEach((el) => bmFold(el, { origin: O, dur: 170, turn: 26, to: 0.1 }));
  all(gh, ren(q.back)).forEach((el) => bmFold(el, { origin: O, dur: 170, delay: 30, turn: 26, to: 0.1 }));
  all(q.box, q.front).forEach((el) => bmOpen(el, { origin: O, dur: 320, delay: 150, turn: 30, over: 1.06 }));
  all(q.box, q.back).forEach((el) => bmOpen(el, { origin: O, dur: 320, delay: 200, turn: 30, over: 1.06 }));
  const nh = all(q.box, q.heart), oh = all(gh, q.heart);
  if (nh.map((x) => x.outerHTML).join('') !== oh.map((x) => x.outerHTML).join('')) { oh.forEach((x) => bmHeart(null, x, 160, O)); nh.forEach((x) => bmHeart(x, null, 160, O, 260)); } else oh.forEach((x) => { x.style.display = 'none'; });
}

/* ---------- hooks ---------- */
// #main: synchronous, right after the page render (knows whether the route was entered and whether the edition switched)
RENDER_HOOKS.push((m, entered) => {
  const edSw = BM.ed != null && BM.ed !== S.ed; BM.ed = S.ed;
  const dial = m.querySelector('svg.fp2'), old = BM.snap.get('dial');
  if (!dial) BM.snap.delete('dial');
  else {
    const now = bmDialSnap(dial);
    if (!OVL) {
      if (entered && !(edSw && old)) bmEnter(dial);
      else if (old) { if (!bmDial(dial, old, now) && entered) bmEnter(dial); }   // edition switch with an unchanged dial: entry as before
      else if (!entered) bmEnter(dial, true);   // the dial appeared in place (data arrived)
    }
    BM.snap.set('dial', now);
  }
  bmCodes(m, entered && !(edSw && old));
  m.querySelectorAll(BM_SMALL).forEach((svg) => bmSmall(svg, entered || !!OVL));
});
// everything outside #main (sidebar, menubar panel, widgets, share dialog, method table): any flower that was added, and the
// sidebar's type code
if (typeof MutationObserver === 'function') {
  new MutationObserver((recs) => {
    const seen = new Set(); let side = false;
    recs.forEach((r) => {
      if (!side && r.target.closest && r.target.closest('#side')) side = true;
      r.addedNodes.forEach((n) => {
        if (n.nodeType !== 1 || n.classList.contains('bm-ghost')) return;
        if (n.matches(BM_SMALL)) seen.add(n); else if (n.firstElementChild) n.querySelectorAll(BM_SMALL).forEach((x) => seen.add(x));
      });
    });
    seen.forEach((svg) => { if (svg.isConnected && !svg.closest('#main')) bmSmall(svg, false); });
    if (side) bmCode(document.querySelector('#side .me .pc .tcode'), 'side', 120);
  }).observe(document.documentElement, { childList: true, subtree: true });
}
