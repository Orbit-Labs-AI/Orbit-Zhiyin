/* 1 片头：两个问题（b0–7.9）+ 2 标志 + 下潜（b7.9–14.6）. STORYBOARD.md KF 1.1–2.4.
   Words cut in on the beat and the line refits; the five Agent chips pop under it, then collapse into the five planets
   that orbitAt draws; two questions swap in the middle; the planets fall onto the mark's tail, the mark is traced,
   tips over and the camera dives into its hole (OPEN timings, drawn by orbitAt in promo.js). */
scene('10-open', () => {
  Object.assign(OPEN, { planets: 3.0, pull: 7.5, trace: 7.9, tilt: 11.4, dive: 12.8, end: 14.6 });
  css(`
.op-line .sv-t{display:inline-block}
.op-o{color:var(--a1)}
.op-line .odo{font-size:inherit;font-weight:inherit;letter-spacing:0;vertical-align:top}
.ln.op-q,.ln.op-chips{overflow:visible}
.op-q .w,.op-q .ln>span{will-change:auto}
.ochip{position:absolute;left:0;top:0;display:flex;align-items:center;gap:16px;padding:14px 30px 14px 22px;border-radius:999px;
  border:1.5px solid rgba(255,255,255,.22);background:rgba(255,255,255,.045);font:500 40px var(--mono);color:#fff;white-space:nowrap;will-change:transform,opacity}
.ocov{position:absolute;left:0;top:0;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;background:#000}
.ochip i{width:16px;height:16px;border-radius:50%;flex:none}
`);
  const Y = 470;                                                     // the sentence's centre line

  // KF 1.1–1.4: 每天 → 和 5 个 Agent → 协作上百次, one hard cut per beat; the line refits to 1700 px, then shrinks into
  // a 40 px eyebrow at y≈300 (b3.0–3.4) and leaves with its letters drifting apart (b7.5–8.1)
  const S1 = 40 / 230;
  txt(0, 8.1, [['gi op-line',
    '<span class="w"><span class="sv-t">每天</span></span>' +
    '<span class="w"><span class="sv-t">和 </span><span class="op-o"><span class="odo">' + odo(5) + '</span></span><span class="sv-t"> 个 Agent </span></span>' +
    '<span class="w"><span class="sv-t">协作</span><span class="op-o">上百次</span></span>']],
  { x: 960, y: Y, align: 'c' }, {
    anim: K.words({ at: [.25, 1.0, 2.0], fit: 1700, shrink: [[3.0, S1, 0, 300 - Y, .4]], out: .6, spread: 1 }),
    tick: (el, tl, life, t) => {
      const b = t / BEAT;
      rollOdo(el, b, 1.0, .5);
      el.querySelector('.ln').style.opacity = lerp(1, .6, E.inOut(lp(b, 3.0, .4))).toFixed(3);
    }
  });

  // KF 1.2 / 1.4: the five Agents (the app's AG list and colours) pop in under the line every 0.2 beat with an
  // overshoot (b1.2–2.0), then each chip folds into its coloured dot, which flies onto its planet (b3.0–3.45); the
  // chip hides on arrival, where orbitAt's planet takes over at the same point
  const AGS = [['Claude Code', 'var(--a1)'], ['Codex', 'var(--a2)'], ['Gemini CLI', 'var(--a3)'], ['DeepSeek', 'var(--a4)'], ['Copilot', 'var(--a5)']];
  const planet = (i, b) => { const a = ((b - OPEN.planets) * 95 + i * 72) * Math.PI / 180; return [960 + Math.cos(a) * 380, 790 + Math.sin(a) * 64]; };
  txt(1.2, 3.6, [['op-chips', AGS.map(() => '<div class="ocov"></div>').join('') + AGS.map((a) => '<div class="ochip"><i style="background:' + a[1] + '"></i><span>' + a[0] + '</span></div>').join('')]], { x: 0, y: 0 }, {
    anim: (el, tl, life, t) => {
      const b = t / BEAT, cs = [...el.querySelectorAll('.ochip')];
      el.style.transform = 'none';
      if (!el._lay) {                                               // lay the row out once, centred on x 960, y 664
        const ws = cs.map((c) => c.offsetWidth), gap = 26, tot = ws.reduce((s, w) => s + w, 0) + gap * 4;
        let x = 960 - tot / 2; el._lay = ws.map((w) => { const r = { x, w, h: cs[0].offsetHeight }; x += w + gap; return r; });
      }
      // until a chip lands, a black disc in the type layer hides orbitAt's planet underneath, so each Agent is only one dot
      el.querySelectorAll('.ocov').forEach((v, i) => { const f = clamp((b - 3.0 - i * .03) / .42), q = planet(i, b); v.style.display = b >= OPEN.planets && f < 1 ? '' : 'none'; v.style.transform = 'translate(' + q[0].toFixed(1) + 'px,' + q[1].toFixed(1) + 'px)'; });
      cs.forEach((c, i) => {
        const L0 = el._lay[i], dot = [L0.x + 30, 664];                 // the dot's centre at rest (padding 22 + radius 8)
        const pop = clamp((b - 1.2 - i * .2) / .3), sc0 = pop >= 1 ? 1 : lerp(.6, 1, ease.back(pop));
        const f0 = 3.0 + i * .03, f = clamp((b - f0) / .42), fe = E.inOut(f);
        const tg = planet(i, Math.max(b, f0)), px = lerp(dot[0], tg[0], fe), py = lerp(dot[1], tg[1], fe) - Math.sin(fe * Math.PI) * 40;
        const sc = sc0 * lerp(1, 14 / 16, fe), lab = 1 - E.out(clamp(f * 2.2));
        c.style.transformOrigin = '30px 50%';
        c.style.transform = 'translate(' + (px - 30).toFixed(1) + 'px,' + (py - L0.h / 2).toFixed(1) + 'px) scale(' + sc.toFixed(4) + ')';
        c.style.opacity = f >= 1 ? '0' : Math.min(1, pop * 2).toFixed(3);
        c.querySelector('span').style.opacity = lab.toFixed(3);
        c.style.borderColor = 'rgba(255,255,255,' + (.22 * lab).toFixed(3) + ')';
        c.style.background = 'rgba(255,255,255,' + (.045 * lab).toFixed(3) + ')';
        c.style.paddingRight = (30 * lab).toFixed(1) + 'px';
        c.style.filter = f > 0 && f < 1 ? 'blur(' + (Math.sin(f * Math.PI) * 1.5).toFixed(2) + 'px)' : 'none';
      });
    }
  });

  // KF 1.5: question 1 — 你是 lands huge and blurred and shrinks into the line, the rest fly in from lower right; a
  // highlighter sweeps under 怎样 from b4.2; at b5.6 the line moves up and out while question 2 comes up from below
  const SWAP = .3;
  const qOut = (at) => (el, tl) => { const p = E.inOut(clamp((tl - BB(at)) / BB(SWAP))); const s = el.querySelector('.ln>span'); s.style.transform = 'translateY(' + (-p * 110).toFixed(1) + 'px)'; s.style.opacity = (1 - clamp(p * 2.6)).toFixed(3); s.style.filter = p > 0 ? 'blur(' + (p * 6).toFixed(1) + 'px)' : 'none'; };
  txt(3.4, 5.6 + SWAP, [['hv op-q', '<span class="w">你是 </span><span class="w"><span class="mk">怎样</span></span><span class="w"> 协作的？</span>']], { x: 960, y: 540, align: 'c' }, {
    anim: K.all(K.big({ scale: 3.2, dur: .45, fly: .12, out: 0 }), K.mark(4.2 - 3.4, .4), qOut(5.6 - 3.4))
  });
  // KF 1.6: question 2 swaps in vertically (0.3 beat); KF 1.7: leaves with its letters drifting apart (b7.5–8.1)
  txt(5.6, 8.1, [['hv op-q', '<span class="op-o">时间</span>都花在了哪？']], { x: 960, y: 540, align: 'c' }, {
    anim: (el, tl, life) => {
      const p = E.inOut(clamp(tl / BB(SWAP))), s = el.querySelector('.ln>span');
      s.style.transform = 'translateY(' + ((1 - p) * 110).toFixed(1) + 'px)'; s.style.opacity = clamp((p - .5) / .5).toFixed(3);
      s.style.filter = p < 1 ? 'blur(' + ((1 - p) * 6).toFixed(1) + 'px)' : 'none';
      leave(el, exitQ(tl, life, .6), true);
    }
  });

  // 2: the mark (orbitAt) — brand words under it, gone before it tips over into the top view
  glowAt(7.9, 1, 3);
  txt(9.6, 12.2, [['', WORDMARK]], { x: 960, y: 690, align: 'c' }, { inB: 1.4, outB: .8 });
  txt(10.6, 12.2, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 800, align: 'c' }, { inB: 1.2, outB: .8 });
  glowAt(12.6, 0, 1.6);
});
