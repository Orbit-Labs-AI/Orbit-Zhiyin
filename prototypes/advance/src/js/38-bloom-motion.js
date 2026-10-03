/* ============ bloom motion: the persona flower folds and re-blooms when the shown type changes (both editions) ============ */
// Every surface keeps rendering plain markup; this layer compares each flower with the one it replaced and animates the change.
//   dial (svg.fp2 in #main, persona / l-persona; RENDER_HOOKS)
//     type changed   收起: the old flower (a renamed copy kept behind the new one, .bm-*) turns 28° and folds into its heart,
//                    ink ring first, the gray ring 50 ms later (300 ms, ease-in); 绽开: from 260 ms the new petals unfold from
//                    the heart while turning 32° into place, a slight overshoot and settle (520 ms), gray ring 80 ms behind;
//                    the heart swaps (ring ↔ dot) at the fold point. The letters that changed rise in with the bloom.
//     same type      a gentle settle of the petals when the flower's proportions moved; nothing when the dial is unchanged.
//     always         the Agent bands morph from the old to the new distribution (the 144 sampled radii, 520 ms; same-angle
//                    points, so a linear blend of the path numbers is a blend of radii), new / gone Agents fade; the badges
//                    glide along the orbit to their new mean angles (shortest arc); the --orbit triangle turns to the new type.
//     page entry     the existing damped sway (.fp-bd) + band sweep + badge run (41-a2-persona.js), now with the petals
//                    unfolding from the bud (FPG.BUD) under the sway. A dial that appears in place (data arrived) only blooms.
//                    Lite ↔ Advance: the dial of the other edition is the "old" one, so a type change folds / re-blooms and
//                    an unchanged dial plays the entry as before. Nothing plays while the Genesis overlay is open (OVL).
//   small flowers (glyphSVG svg[data-bloom] anywhere — overview card, menubar panel, widgets, share span list, method table —
//     and the flower on the share card svg[data-span]; MutationObserver outside #main): the same fold / unfold, quicker
//     (170 + 320 ms), when the type at the same place changes. Hover turn is CSS (43-bloom-motion.css).
// prefers-reduced-motion: no fold, no morph, no glide — the new flower cross-fades in (160 ms) and everything else is instant.
const BM = { snap: new Map(), ed: null, lock: false };
const BM_IN = 'cubic-bezier(.55,.06,.8,.4)', BM_OUT = 'cubic-bezier(.22,.7,.28,1)', BM_IO = 'cubic-bezier(.45,.05,.3,1)';
const BM_SMALL = 'svg[data-bloom], svg[data-span]';
const bmDelta = (a, b) => ((b - a) % 360 + 540) % 360 - 180;
// the ghost of an old flower: same markup, classes renamed so selectors and CSS for the live flower never see it
const bmGhost = (html) => '<g class="bm-ghost" aria-hidden="true">' + html.replace(/<title>[\s\S]*?<\/title>/g, '').replace(/class="([^"]*)"/g, (m, c) => 'class="' + c.replace(/\bfp-/g, 'bm-') + '"') + '</g>';
const bmDrop = (el, ms) => { const t = setTimeout(() => el.remove(), ms + 400); return () => { clearTimeout(t); el.remove(); }; };   // also settles in a throttled (hidden) tab

/* ---------- keyframes ---------- */
// fold into the heart: turn, shrink to `to`, fade at the very end
function bmFold(el, o) {
  if (!el || !el.animate) return null;
  return el.animate([{ transform: 'rotate(0deg) scale(1)', opacity: 1, transformOrigin: o.origin }, { opacity: 1, offset: 0.72 },
    { transform: 'rotate(' + o.turn + 'deg) scale(' + (o.to || 0.06) + ')', opacity: 0, transformOrigin: o.origin }],
  { duration: o.dur, delay: o.delay || 0, easing: BM_IN, fill: 'both' });
}
// unfold from the heart: turn into place with a slight overshoot (scale 1.045 at 62 %) and settle
function bmOpen(el, o) {
  if (!el || !el.animate) return null;
  const t = o.turn || 0;
  return el.animate([{ transform: 'rotate(' + (-t) + 'deg) scale(' + (o.from == null ? 0.06 : o.from) + ')', opacity: o.from >= 0.3 ? 1 : 0, transformOrigin: o.origin },
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

/* ---------- path morph (bands) ---------- */
const BM_NUM = /-?\d*\.?\d+/g;
function bmParse(d) { return { n: (d.match(BM_NUM) || []).map(Number), s: d.split(BM_NUM) }; }
function bmTween(items, dur) {
  if (!items.length) return;
  let t0 = 0, done = false;
  const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const draw = (e) => items.forEach((it) => {
    let d = ''; for (let i = 0; i < it.b.length; i++) d += it.s[i] + (it.a[i] + (it.b[i] - it.a[i]) * e).toFixed(1);
    it.el.setAttribute('d', d + it.s[it.b.length]);
  });
  const end = () => { if (done) return; done = true; items.forEach((it) => it.el.setAttribute('d', it.fin)); };
  const step = (now) => {
    if (done) return; if (!t0) t0 = now;
    if (!items.some((it) => it.el.isConnected)) { done = true; return; }
    const u = Math.min(1, (now - t0) / dur); if (u >= 1) { end(); return; }
    draw(ease(u)); requestAnimationFrame(step);
  };
  draw(0); requestAnimationFrame(step); setTimeout(end, dur + 400);
}

/* ---------- dial ---------- */
function bmDialSnap(svg) {
  const fl = svg.querySelector('.fp-flower'), bl = svg.querySelector('.fp-bloom'), h = svg.querySelector('.fp-heart');
  const paths = new Map(); svg.querySelectorAll('.fpo[data-a], .fpc[data-a]').forEach((p) => paths.set(p.classList[0] + ':' + p.dataset.a, p.getAttribute('d')));
  const pl = new Map(); svg.querySelectorAll('.fp-pl').forEach((g) => pl.set(g.dataset.a, +g.dataset.pa));
  return { code: fl ? fl.dataset.code : '', hd: bl ? +bl.dataset.hd : 0, fl: fl ? fl.outerHTML.replace(/<title>[\s\S]*?<\/title>/, '') : '', heart: h ? h.innerHTML : '', paths, pl };
}
// entry: the existing sway + band sweep + badge run, with the petals opening from the bud underneath; soft = bloom only
function bmEnter(svg, soft) {
  if (!svg || reduceMotion()) return;
  if (!soft) { fpWobble(svg); fpOrbitIn(svg); }
  const O = '200px 200px';
  bmOpen(svg.querySelector('.fp-front'), { origin: O, dur: soft ? 560 : 820, from: soft ? 0.06 : FPG.BUD, turn: soft ? 32 : 0, over: 1.05 });
  bmOpen(svg.querySelector('.fp-back'), { origin: O, dur: soft ? 560 : 820, delay: soft ? 80 : 120, from: soft ? 0.06 : FPG.BUD, turn: soft ? 32 : 0, over: 1.05 });
}
// old → new on the same dial; returns true when something moved
function bmDial(svg, old, now) {
  const O = '200px 200px', reduce = reduceMotion(); let moved = false;
  const nf = svg.querySelector('.fp-flower');
  if (nf && old.code !== now.code) {
    moved = true;
    if (reduce) nf.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease-out' });
    else {
      nf.insertAdjacentHTML('beforebegin', bmGhost(old.fl));
      const gh = nf.previousElementSibling, drop = bmDrop(gh, 360);
      const a = bmFold(gh.querySelector('.bm-front'), { origin: O, dur: 300, turn: 28 });
      bmFold(gh.querySelector('.bm-back'), { origin: O, dur: 300, delay: 50, turn: 28 });
      if (a) a.onfinish = () => setTimeout(drop, 60);
      bmOpen(nf.querySelector('.fp-front'), { origin: O, dur: 520, delay: 260, turn: 32 });
      bmOpen(nf.querySelector('.fp-back'), { origin: O, dur: 520, delay: 340, turn: 32 });
      if (old.heart !== now.heart) bmHeart(nf.querySelector('.fp-heart'), gh.querySelector('.bm-heart'), 270, O);
      else { const g2 = gh.querySelector('.bm-heart'); if (g2) g2.style.display = 'none'; }
    }
  } else if (nf && old.fl !== now.fl && !reduce) {
    moved = true;   // same type, proportions moved (strength): a gentle settle
    nf.querySelectorAll('.fp-pw').forEach((el, i) => el.animate([{ transform: 'rotate(-5deg) scale(.95)', transformOrigin: O }, { transform: 'rotate(1deg) scale(1.015)', offset: 0.6, transformOrigin: O }, { transform: 'none', transformOrigin: O }], { duration: 560, delay: i * 60, easing: BM_OUT }));
  }
  if (reduce) return moved;
  // the --orbit triangle (an SVG transform attribute: rotate(hd 200 200)) turns along the shortest arc with a small settle
  const n0 = svg.querySelector('.fp-n0');
  if (n0 && n0.animate && old.hd !== now.hd) {
    moved = true; const d = bmDelta(old.hd, now.hd), from = now.hd - d;
    n0.animate([{ transform: 'rotate(' + from + 'deg)', transformOrigin: O }, { transform: 'rotate(' + (now.hd + d * 0.04).toFixed(2) + 'deg)', offset: 0.78, transformOrigin: O }, { transform: 'rotate(' + now.hd + 'deg)', transformOrigin: O }], { duration: 760, easing: BM_IO });
  }
  // bands: blend each Agent's layer and edge; Agents that appear fade in, Agents that left fade out from their old shape
  const items = [];
  svg.querySelectorAll('.fpo[data-a], .fpc[data-a]').forEach((p) => {
    const k = p.classList[0] + ':' + p.dataset.a, od = old.paths.get(k), nd = p.getAttribute('d');
    if (od == null) { moved = true; p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, delay: 120, easing: 'ease-out', fill: 'backwards' }); return; }
    if (od === nd) return;
    const A = bmParse(od), B = bmParse(nd);
    if (A.n.length !== B.n.length || A.s.join('|') !== B.s.join('|')) { p.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300 }); return; }
    items.push({ el: p, a: A.n, b: B.n, s: B.s, fin: nd });
  });
  const body = svg.querySelector('.fp-body'), orb = svg.querySelector('.fp-orb');
  old.paths.forEach((d, k) => {
    const [cl, a] = k.split(':'); if (svg.querySelector('.' + cl + '[data-a="' + a + '"]')) return;
    const host = cl === 'fpo' ? body : orb; if (!host) return;
    const src = cl === 'fpo' ? '<path class="bm-o" d="' + d + '" fill="var(--h2)" fill-opacity=".6"/>' : '<path class="bm-c" d="' + d + '" fill="none" stroke="var(--h4)" stroke-width=".9"/>';
    host.insertAdjacentHTML('beforeend', src); const g = host.lastElementChild; moved = true;
    g.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 360, easing: 'ease-in', fill: 'forwards' }).onfinish = () => g.remove(); bmDrop(g, 360);
  });
  if (items.length) { moved = true; bmTween(items, 520); }
  // badges glide along the orbit (outer group turns, the logo counter-turns to stay upright)
  let gi = 0;
  svg.querySelectorAll('.fp-pl').forEach((g) => {
    const to = +g.dataset.pa, from0 = old.pl.get(g.dataset.a);
    if (from0 == null) { moved = true; g.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, delay: 260, easing: 'ease-out', fill: 'backwards' }); return; }
    const d = bmDelta(from0, to); if (Math.abs(d) < 0.3) return;
    moved = true; const from = to - d, pd = g.querySelector('.fp-pd'), o = { duration: 640, delay: gi++ * 40, easing: BM_IO, fill: 'backwards' };
    g.animate([{ transform: 'rotate(' + from + 'deg)' }, { transform: 'rotate(' + to + 'deg)' }], o);
    if (pd) pd.animate([{ transform: 'rotate(' + (-from) + 'deg)' }, { transform: 'rotate(' + (-to) + 'deg)' }], o);
  });
  return moved;
}
// the letters of the persona code that changed rise in with the bloom
function bmLetters(m) {
  const Ls = $$('[data-hero="code"] .L', m), now = Ls.map((x) => x.textContent), old = BM.snap.get('letters');
  BM.snap.set('letters', { route: S.route, v: now });
  if (!old || old.route !== S.route || reduceMotion()) return;
  Ls.forEach((el, i) => {
    if (old.v[i] == null || old.v[i] === now[i] || !el.animate) return;
    el.animate([{ opacity: 0, transform: 'translateY(.22em) scale(.94)' }, { opacity: 1, transform: 'none' }], { duration: 340, delay: 260 + i * 45, easing: BM_OUT, fill: 'backwards' });
  });
}

/* ---------- small flowers ---------- */
// parts of a small flower: the glyph svg itself, or the flower group on the share card (drawn from the 80-unit glyph, heart at 40,40)
function bmSmallParts(svg) {
  if (svg.hasAttribute('data-bloom')) return { box: svg, own: true, code: svg.getAttribute('data-bloom'), front: '.fp-pet', back: '.fp-bk', heart: 'circle' };
  const c = svg.querySelector('g > circle[cx="40"][cy="40"]'); if (!c) return null;
  return { box: c.parentNode, own: false, code: svg.getAttribute('data-code') || '', front: 'path:last-of-type', back: 'path:first-of-type:not(:last-of-type)', heart: 'circle' };
}
function bmSmallKey(svg, kind) {
  const root = (svg.parentElement && svg.parentElement.closest('[id]')) || document.body;
  const sib = root.querySelectorAll(kind === 'glyph' ? 'svg[data-bloom]' : 'svg[data-span]');
  return root.id + '|' + kind + '|' + Array.prototype.indexOf.call(sib, svg) + '|' + (svg.getAttribute('width') || '') + (root.closest('#main') ? '|' + S.route : '');
}
function bmSmall(svg, fresh) {
  if (svg.closest('#overlay, .g-fly, .bm-ghost')) return;
  const q = bmSmallParts(svg); if (!q) return;
  const key = bmSmallKey(svg, q.own ? 'glyph' : 'card'), old = BM.snap.get(key);
  const html = q.own ? svg.innerHTML : q.box.outerHTML;
  BM.snap.set(key, { code: q.code, html });
  if (fresh || !old || old.code === q.code || !old.html || svg.getClientRects().length === 0) return;
  const O = '40px 40px', all = (root, sel) => (sel ? Array.from(root.querySelectorAll(':scope > ' + sel)) : []);
  if (reduceMotion()) { q.box.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: 'ease-out' }); return; }
  let gh;
  if (q.own) { svg.insertAdjacentHTML('afterbegin', bmGhost(old.html)); gh = svg.firstElementChild; } else { q.box.insertAdjacentHTML('beforebegin', bmGhost(old.html)); gh = q.box.previousElementSibling.firstElementChild; }
  const ghost = q.own ? gh : gh.parentNode, drop = bmDrop(ghost, 260);
  const ren = (sel) => sel && sel.replace(/\.fp-/g, '.bm-');
  all(gh, ren(q.front)).forEach((el) => { const a = bmFold(el, { origin: O, dur: 170, turn: 26, to: 0.1 }); if (a) a.onfinish = () => setTimeout(drop, 40); });
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
  if (entered) BM.snap.delete('letters'); bmLetters(m);
  m.querySelectorAll(BM_SMALL).forEach((svg) => bmSmall(svg, entered || !!OVL));
});
// everything outside #main (sidebar, menubar panel, widgets, share dialog, method table): any flower that was added
if (typeof MutationObserver === 'function') {
  new MutationObserver((recs) => {
    const seen = new Set();
    recs.forEach((r) => r.addedNodes.forEach((n) => {
      if (n.nodeType !== 1) return;
      if (n.matches(BM_SMALL)) seen.add(n); else if (n.firstElementChild) n.querySelectorAll(BM_SMALL).forEach((x) => seen.add(x));
    }));
    seen.forEach((svg) => { if (svg.isConnected && !svg.closest('#main')) bmSmall(svg, false); });
  }).observe(document.documentElement, { childList: true, subtree: true });
}
