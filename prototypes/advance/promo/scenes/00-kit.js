/* Shared type forms and effects for the scenes (STORYBOARD.md「文字形式」「转场」), learned from the reference films in
   REFERENCES.md. Every form is a pure function of time and is used as the anim of a txt() or tag():
     txt(b0, b1, lines, pos, { anim: K.blurIn() })            txt(b0, b1, lines, pos, { anim: K.all(K.rise(), K.mark(1)) })
   Times inside a form are beats from the start of its text (b0); `out` is the exit length in beats at the end of its life.
   Markup the forms look for:  .w = a word (words / big / swap)   .mk = marker highlight   .st = strike-through
   .sw = a swap slot holding one <span> per word   [data-to] = a number that counts (count)   .pill = a chip that pops. */
'use strict';
const K = {};
css(`
/* v18.3 eyebrow: CJK at .06em (no more 「0 3 · 会 话 轨 迹」), Latin / digit / · runs inside .ebl (K.eb).
   v18.7: the runs at .12em (at .3em「03」still read as「0 3」), the · set off by thin spaces instead, white .7 */
.eb{font-size:26px;letter-spacing:.06em;color:rgba(255,255,255,.7)}
.pe-it .eb.eb{color:rgba(255,255,255,.7)}
.eb .ebl{letter-spacing:.12em;margin-right:-.06em}   /* the run's trailing tracking trimmed back to .06em */
.eb .ebs{font-family:-apple-system,'SF Pro Text',sans-serif;letter-spacing:0}   /* SF Mono has no thin space: its fallback is a full .6em cell */
.gi{font-size:230px;font-weight:700;letter-spacing:-.02em;line-height:1}
.k .w{display:inline-block;white-space:pre;will-change:transform,opacity,filter}
.k .ch{display:inline-block;white-space:pre;will-change:transform,opacity,filter}
/* silver type that is split into words / characters: the gradient has to sit on each piece, or hidden pieces still
   show through the parent's background-clip:text */
.ln.sv>span:has(.w,.ch){background:none;color:#fff}
.ln.sv .w,.ln.sv .ch{background:linear-gradient(180deg,#fff 35%,#b4b8c2);-webkit-background-clip:text;background-clip:text;color:transparent}
.ln.sv .w:has(.ch){background:none;color:#fff}
.k .mk{background:linear-gradient(var(--mk,rgba(226,96,43,.55)),var(--mk,rgba(226,96,43,.55))) no-repeat 0 88%/0% .26em;padding:0 .04em}
.k .st{background:linear-gradient(currentColor,currentColor) no-repeat 0 56%/0% .07em}
.k .sw{display:inline-block;position:relative;vertical-align:bottom;overflow:hidden;padding:.06em 0 .12em;margin:-.06em 0 -.12em;white-space:nowrap}
.k .sw>span{display:inline-block;position:absolute;left:0;top:.06em;white-space:nowrap}
.k .pill{display:inline-flex;align-items:center;gap:.35em;padding:.18em .62em;border-radius:999px;font-family:var(--mono);font-weight:600;transform-origin:50% 60%}
.k .caret{display:inline-block;width:.08em;height:1em;margin-left:.06em;vertical-align:-.12em;background:currentColor}
.bloom{position:absolute;left:0;top:0;width:0;height:0;pointer-events:none;z-index:4}
.bloom i{position:absolute;left:0;top:0;border-radius:50%}
.bloom .bf{background:var(--c)}
.bloom .bg{background:radial-gradient(closest-side,var(--c),transparent)}
`);

const BB = (beats) => beats * BEAT;                       // beats → seconds
const ease = { back: (p) => { const c = 1.7; return 1 + (c + 1) * Math.pow(p - 1, 3) + c * Math.pow(p - 1, 2); } };
// deterministic 0..1 noise per index (no Math.random: renders must be repeatable)
const hash01 = (i, seed = 1) => { const x = Math.sin(i * 127.1 + seed * 311.7) * 43758.5453; return x - Math.floor(x); };
// exit factor: 1 while the text lives, eases to 0 over the last `out` beats
const exitQ = (tl, life, out) => (out > 0 ? E.inOut(clamp((life - tl) / BB(out))) : 1);
// split the visible text of el into one span per character (once); returns them in reading order
function chars(el, root) {
  if (el._ch && !root) return el._ch;
  const out = [], walk = (n) => {
    for (const c of [...n.childNodes]) {
      if (c.nodeType === 3) { const f = document.createDocumentFragment(); for (const ch of c.textContent) { const s = document.createElement('span'); s.className = 'ch'; s.textContent = ch; f.appendChild(s); out.push(s); } c.replaceWith(f); }
      else if (c.nodeType === 1 && !c.classList.contains('ch')) walk(c);
    }
  };
  walk(root || el);
  if (!root) el._ch = out;
  return out;
}
// the exit most forms share: blur + fade, optionally the letters drift apart.
// v18.3 (opt-in, default unchanged): o.dir = {dx, dy} px the block drifts during the blur (24–40 px toward where the
// dots go next; same long E.inOut as the fade, no overshoot); o.push = end scale of a push-through (true = 1.06,
// or a number 1.04–1.10). Both use the CSS `translate` / `scale` properties, so they compose with any transform a form
// or tick sets.
function drift(el, q, o) {
  const d = o && o.dir, pu = o && o.push, on = q < .999;
  if (d) el.style.translate = on ? ((d.dx || 0) * (1 - q)).toFixed(1) + 'px ' + ((d.dy || 0) * (1 - q)).toFixed(1) + 'px' : '';
  if (pu) el.style.scale = on ? lerp(1, pu === true ? 1.06 : pu, 1 - q).toFixed(4) : '';
}
function leave(el, q, spread, o) {
  el.style.opacity = q.toFixed(3);
  el.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none';
  if (spread) el.style.letterSpacing = q < .999 ? ((1 - q) * .45).toFixed(3) + 'em' : '';
  drift(el, q, o);
}
// the drift / push alone, for blocks whose fade is done elsewhere (e.g. the engine's mask):
//   txt(…, { anim: K.all(mask(.18, 1, .6), K.exit({ out: .6, dir: { dx: -32, dy: 0 }, push: 1.06 })) })
K.exit = (o = {}) => (el, tl, life) => drift(el, exitQ(tl, life, o.out ?? .6), o);
// v18.3 eyebrow markup: wraps each Latin / digit / · run in <span class="ebl"> (.3em)
// and leaves CJK at the .eb tracking (.06em). Tags and entities are left alone; idempotent.
const EB_RUN = /[A-Za-z0-9·]+/g;
// v18.7: the spaces around every · become U+2009 thin spaces (mono word spaces left a hole), as do the spaces between digits and CJK (「16 种」), so the separator, not the tracking, splits the groups
K.eb = (html) => (/class="ebl"/.test(html) ? html : String(html).split(/(<[^>]*>|&#?\w+;)/).map((s, i) => (i % 2 ? s : s.replace(/[ \u2009]*·[ \u2009]*/g, '\u2009·\u2009').replace(/(?<=[0-9A-Za-z]) (?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff]) (?=[0-9A-Za-z])/g, '\u2009').replace(EB_RUN, '<span class="ebl">$&</span>').replace(/\u2009/g, '<span class="ebs">\u2009</span>'))).join(''));
// every eyebrow switches to it: txt() lines whose class has `eb` get K.eb before they are built, and any other .eb that
// a scene writes as raw html (e.g. the persona column) is wrapped the moment it is added to the stage
{
  const txt0 = txt;
  txt = (b0, b1, lines, pos, o) => txt0(b0, b1, lines.map((l) => (/(^|\s)eb(\s|$)/.test(l[0]) && typeof l[1] === 'string' ? [l[0], K.eb(l[1])].concat(l.slice(2)) : l)), pos, o);
  const fixEb = (root) => (root.querySelectorAll ? root.querySelectorAll('.eb') : []).forEach((e) => {
    if (e._eb || e.querySelector('.ebl,.ch')) return; e._eb = 1;
    const tn = []; const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); while (w.nextNode()) tn.push(w.currentNode);
    tn.forEach((n) => { if (!EB_RUN.test(n.textContent)) return; EB_RUN.lastIndex = 0; const sp = document.createElement('span'); sp.innerHTML = K.eb(n.textContent.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])); n.replaceWith(...sp.childNodes); });
  });
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) { fixEb(n); if (n.classList.contains('eb')) fixEb(n.parentNode); } }))).observe(stage, { childList: true, subtree: true });
}
K.all = (...fs) => (el, tl, life, t) => fs.forEach((f) => f(el, tl, life, t));
// the engine's masked rise, line after line (st = beats between lines)
K.rise = (o = {}) => mask(o.st ?? .18, o.in || 1, o.out || .6, o.spread);

// Apple: words added on the beat with a hard cut (1–2 frames), never a slow fade. o.at = beats of each .w;
// o.fit = max width in px: words not yet shown take no room and the block shrinks to keep the shown ones within fit
// (each new word re-sets the line, as in the Mac Studio film); o.shrink = [[b, scale, dx, dy, dur], …]: afterwards
// the whole block scales/moves (the premise shrinking into an eyebrow).
K.words = (o = {}) => (el, tl, life) => {
  const ws = el.querySelectorAll('.w'), at = o.at || [];
  ws.forEach((w, i) => { const b = at[i] ?? i * .5; const p = clamp((tl - BB(b)) / (2 / 60)); w.style.opacity = p.toFixed(3); if (o.fit) w.style.display = p > 0 ? '' : 'none'; });
  let sc = 1, dx = 0, dy = 0;
  if (o.fit) { el.style.transform = el._base ?? el.style.transform; sc = Math.min(1, o.fit / Math.max(1, el.offsetWidth)); }
  for (const [b, s1, x1, y1, dur] of o.shrink || []) { const p = E.inOut(clamp((tl - BB(b)) / BB(dur || .4))); sc = lerp(sc, s1, p); dx = lerp(dx, x1, p); dy = lerp(dy, y1, p); }
  if (el._base == null) el._base = el.style.transform;
  el.style.transform = el._base + ' translate(' + dx.toFixed(1) + 'px,' + dy.toFixed(1) + 'px) scale(' + sc.toFixed(4) + ')';
  el.style.transformOrigin = o.origin || '50% 50%';
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// Membrain: every character arrives on its own (random order), from blur to sharp. spread = beats over which they start.
K.blurIn = (o = {}) => (el, tl, life) => {
  const cs = chars(el), spread = o.spread ?? .55, dur = o.dur ?? .3, start = o.start || 0;
  cs.forEach((c, i) => { const d = start + hash01(i, o.seed || 3) * spread; const p = E.out(clamp((tl - BB(d)) / BB(dur))); c.style.opacity = p.toFixed(3); c.style.filter = p < .999 ? 'blur(' + ((1 - p) * 9).toFixed(1) + 'px)' : 'none'; });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread2, o);
};
// Membrain hero word: characters reveal from the middle outwards (step = beats between neighbours)
K.centerOut = (o = {}) => (el, tl, life) => {
  const cs = chars(el), c0 = (cs.length - 1) / 2, step = o.step ?? .1, dur = o.dur ?? .35, start = o.start || 0;
  cs.forEach((c, i) => { const p = E.out(clamp((tl - BB(start + Math.abs(i - c0) * step)) / BB(dur))); c.style.opacity = p.toFixed(3); c.style.filter = p < .999 ? 'blur(' + ((1 - p) * 10).toFixed(1) + 'px)' : 'none'; c.style.transform = 'scale(' + lerp(1.18, 1, p).toFixed(3) + ')'; });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// GWI: a reply decodes — letters start wide apart and faint, then close up one after another
K.decode = (o = {}) => (el, tl, life) => {
  const cs = chars(el), step = o.step ?? .06, dur = o.dur ?? .4, start = o.start || 0;
  cs.forEach((c, i) => { const p = E.out(clamp((tl - BB(start + i * step)) / BB(dur))); c.style.opacity = lerp(0, 1, Math.min(1, p * 1.6)).toFixed(3); c.style.marginRight = ((1 - p) * (o.from ?? .6)).toFixed(3) + 'em'; });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// Membrain / Apple: glyphs scramble, then lock left to right (per = beats between locks). pool: glyphs to cycle through.
const POOL_CJK = '协作会话代理规划验证委托即兴多线求证节奏轨迹人格推荐安装分析时间小时数据本地记录';
const POOL_LAT = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
K.scramble = (o = {}) => (el, tl, life, t) => {
  const cs = chars(el), start = o.start || 0, per = o.per ?? .1, frame = Math.floor(t * 30);
  cs.forEach((c, i) => {
    if (c._f == null) c._f = c.textContent;
    const lock = tl >= BB(start + i * per), show = tl >= BB(start + Math.max(0, i * per - (o.lead ?? .6)));
    const pool = o.pool || (/[一-鿿]/.test(c._f) ? POOL_CJK : POOL_LAT);
    c.textContent = lock || /\s/.test(c._f) ? c._f : pool[Math.floor(hash01(i + frame * 7, 9) * pool.length)];
    c.style.opacity = show ? (lock ? '1' : '.55') : '0';
  });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// GWI: typing at cps characters per second (slower for the first three), with a solid caret
K.type = (o = {}) => (el, tl, life) => {
  const cs = chars(el), cps = o.cps ?? 10, t0 = BB(o.start || 0), dt = Math.max(0, tl - t0);
  const n = Math.min(cs.length, Math.floor(dt < 3 / (cps * .6) ? dt * cps * .6 : 3 + (dt - 3 / (cps * .6)) * cps));
  cs.forEach((c, i) => { c.style.display = i < n ? '' : 'none'; });
  let car = el.querySelector('.caret'); if (o.caret !== false && !car) { car = document.createElement('span'); car.className = 'caret'; (cs[cs.length - 1] || el).parentNode.appendChild(car); }
  if (car) { const last = cs[Math.max(0, n - 1)]; if (last && last.nextSibling !== car) last.after(car); car.style.opacity = n >= cs.length && Math.floor(tl * 2.2) % 2 ? '0' : '1'; }
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// GWI: a fixed sentence whose last word is swapped. markup: <span class="sw"><span>a</span><span>b</span>…</span>;
// o.at = beats at which word i (i ≥ 1) replaces the previous one; mode 'v' = vertical cross (old up, new from below),
// 'scr' = the new word scrambles in. The slot's width follows the word.
K.swap = (o = {}) => (el, tl, life, t) => {
  el.querySelectorAll('.sw').forEach((sw) => {
    const ws = [...sw.children], at = [0].concat(o.at || []), dur = o.dur ?? .3;
    let cur = 0; at.forEach((b, i) => { if (tl >= BB(b)) cur = i; });
    const p = cur ? E.inOut(clamp((tl - BB(at[cur])) / BB(dur))) : 1;
    ws.forEach((w, i) => {
      const on = i === cur, prev = i === cur - 1;
      if (o.mode === 'scr') {                              // the new word scrambles in, locking left to right
        const cs = chars(w), frame = Math.floor(t * 30);
        cs.forEach((c, j) => { if (c._f == null) c._f = c.textContent; const lk = !on || p >= (j + 1) / cs.length; const pool = /[\u4e00-\u9fff]/.test(c._f) ? POOL_CJK : POOL_LAT; c.textContent = lk || /\s/.test(c._f) ? c._f : pool[Math.floor(hash01(j + frame * 7, 5) * pool.length)]; c.style.opacity = lk ? '1' : '.6'; });
        w.style.opacity = on ? '1' : prev ? (1 - E.out(clamp(p * 3))).toFixed(3) : '0';
        w.style.transform = 'none';
        return;
      }
      w.style.opacity = on ? p.toFixed(3) : prev ? (1 - p).toFixed(3) : '0';
      w.style.transform = 'translateY(' + (on ? (1 - p) * 45 : prev ? -p * 45 : 45).toFixed(1) + '%)';
    });
    const wa = ws[Math.max(0, cur - 1)].offsetWidth, wb = ws[cur].offsetWidth; sw.style.width = lerp(cur ? wa : wb, wb, p).toFixed(1) + 'px'; sw.style.height = ws[cur].offsetHeight + 'px';
  });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// Alpha: the first word lands huge and blurred and shrinks into the line; the other words fly in from lower right
K.big = (o = {}) => (el, tl, life) => {
  const ws = el.querySelectorAll('.w'), sc = o.scale ?? 3.2, dur = o.dur ?? .45, fly = o.fly ?? .12, start = o.start || 0;
  ws.forEach((w, i) => {
    if (!i) { const p = E.out(clamp((tl - BB(start)) / BB(dur))); w.style.transform = 'scale(' + lerp(sc, 1, p).toFixed(3) + ')'; w.style.filter = p < .999 ? 'blur(' + ((1 - p) * 14).toFixed(1) + 'px)' : 'none'; w.style.opacity = Math.min(1, p * 2).toFixed(3); w.style.transformOrigin = '100% 60%'; return; }
    const p = E.out(clamp((tl - BB(start + dur * .7 + (i - 1) * fly)) / BB(.35)));
    w.style.transform = 'translate(' + ((1 - p) * 60).toFixed(1) + 'px,' + ((1 - p) * 40).toFixed(1) + 'px)'; w.style.opacity = p.toFixed(3); w.style.filter = p < .999 ? 'blur(' + ((1 - p) * 6).toFixed(1) + 'px)' : 'none';
  });
  leave(el, exitQ(tl, life, o.out ?? .5), o.spread, o);
};
// a highlighter swept under .mk words (at = beat, dur = beats)
K.mark = (at = .8, dur = .4) => (el, tl) => el.querySelectorAll('.mk').forEach((m) => { m.style.backgroundSize = (E.inOut(clamp((tl - BB(at)) / BB(dur))) * 100).toFixed(1) + '% .26em'; });
// a strike-through swept across .st words
K.strike = (at = .8, dur = .3) => (el, tl) => el.querySelectorAll('.st').forEach((m) => { m.style.backgroundSize = (E.inOut(clamp((tl - BB(at)) / BB(dur))) * 100).toFixed(1) + '% .07em'; });
// [data-to] numbers roll from data-from (default 0) to data-to, ease-out; over = overshoot that settles back (GWI 30→72→69);
// data-dec = decimals. at/dur in beats.
K.count = (at = 0, dur = 1, over = 0) => (el, tl) => el.querySelectorAll('[data-to]').forEach((n) => {
  const a = +(n.dataset.from || 0), b = +n.dataset.to, dec = +(n.dataset.dec || 0), p = clamp((tl - BB(at)) / BB(dur));
  const v = over ? (p < .72 ? lerp(a, b + over, E.out(p / .72)) : lerp(b + over, b, E.inOut((p - .72) / .28))) : lerp(a, b, E.out(p));
  n.textContent = v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
});
// .pill chips pop in with a small overshoot, one after another (gap = beats)
K.pop = (at = 0, gap = .15, dur = .3) => (el, tl) => el.querySelectorAll('.pill').forEach((c, i) => { const p = clamp((tl - BB(at + i * gap)) / BB(dur)); c.style.opacity = Math.min(1, p * 2).toFixed(3); c.style.transform = 'scale(' + (p >= 1 ? 1 : lerp(.6, 1, ease.back(p))).toFixed(3) + ')'; });

// GWI / Apple: a circular portal. The hole (#hole0 / #hole1, which holds deck 0 / 1) opens from a point on screen to
// cover the frame; at = (b, dur), from = [x, y] or () => [x, y] (e.g. () => elXY(1, sel)), r1 = final radius.
// pre = beats before b during which the hole is already shut (so the deck behind it can be framed unseen).
// ring = colour of an outline that rides the edge of the opening and thins out as it grows (the GWI star iris), or null.
// The centre is recorded in PORTAL[hole] from its first frame on, so the scene behind can put something under it.
const PORTAL = {};
function portal(hole, b, dur, from, r1 = 2300, ez = E.in, pre = .6, ring = 'rgba(226,96,43,.95)') {
  let c = null, rg = null;
  every(b - pre, b + dur + .1, (p, bb) => {
    const h = $('#hole' + hole); if (!c) { c = typeof from === 'function' ? from() : from; PORTAL[hole] = c; }
    const q = clamp((bb - b) / dur), r = r1 * ez(q);
    h.style.clipPath = bb < b ? 'circle(0px at ' + c[0] + 'px ' + c[1] + 'px)' : q >= 1 ? 'none' : 'circle(' + r.toFixed(1) + 'px at ' + c[0].toFixed(1) + 'px ' + c[1].toFixed(1) + 'px)';
    if (!ring) return;
    if (!rg) { rg = document.createElement('div'); rg.className = 'portal-ring'; stage.insertBefore(rg, fxEl); }
    const a = bb < b || q >= 1 ? 0 : Math.min(1, q * 12) * (1 - E.in(clamp((q - .55) / .45)));
    const w = lerp(5, 1.2, E.out(q));
    rg.style.cssText = 'position:absolute;left:' + c[0].toFixed(1) + 'px;top:' + c[1].toFixed(1) + 'px;width:' + (2 * r).toFixed(1) + 'px;height:' + (2 * r).toFixed(1) + 'px;margin:' + (-r).toFixed(1) + 'px 0 0 ' + (-r).toFixed(1) + 'px;border-radius:50%;pointer-events:none;' +
      'border:' + w.toFixed(2) + 'px solid ' + ring + ';box-shadow:0 0 ' + (18 * (1 - q) + 4).toFixed(1) + 'px ' + ring + ',inset 0 0 ' + (14 * (1 - q) + 3).toFixed(1) + 'px ' + ring + ';opacity:' + a.toFixed(3);
  });
}
