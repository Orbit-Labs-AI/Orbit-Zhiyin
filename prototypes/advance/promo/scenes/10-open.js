/* v6 port: open (缓): words, the five Agents, the Orbit mark, then down into it */
scene('10-open', () => {
  txt(.25, 3.9, [['row md', ['你每天', '和 <span class="acc">5</span> 个 Agent', '协作上百次']]], { x: 960, y: 450, align: 'c' }, { st: .6 });
  const AGS = [['Claude Code', 'var(--a1)'], ['Codex', 'var(--a2)'], ['Gemini CLI', 'var(--a3)'], ['DeepSeek', 'var(--a4)'], ['Copilot', 'var(--a5)']];
  txt(1.5, 3.9, [['', AGS.map((a) => '<span class="chip"><i style="background:' + a[1] + '"></i>' + a[0] + '</span>').join('')]], { x: 960, y: 560, align: 'c' }, {
    anim: (el, tl, life) => {
      const q = E.inOut(clamp((life - tl) / (.6 * BEAT)));
      el.querySelectorAll('.chip').forEach((c, i) => { const p = E.expo(clamp((tl - (.7 + i * .375) * BEAT) / (.8 * BEAT))); c.style.opacity = (p * q).toFixed(3); c.style.transform = 'translateY(' + ((1 - p) * 24).toFixed(1) + 'px)'; c.style.marginRight = i < 4 ? '44px' : '0'; c.style.filter = q < .999 ? 'blur(' + ((1 - q) * 8).toFixed(1) + 'px)' : 'none'; });
    }
  });
  txt(4, 5.9, [['row md', ['却很少', '回头看看']]], { x: 960, y: 540, align: 'c' }, { st: .5 });
  txt(6, 7.9, [['row md', ['自己是', '<span class="serif acc"><i>怎样</i></span>', '和它们协作的']]], { x: 960, y: 540, align: 'c' }, { st: .4 });
  glowAt(7.9, 1, 3);
  txt(9.6, 11.9, [['word', 'Orbit']], { x: 960, y: 690, align: 'c' }, { inB: 1.4, outB: .8 });
  txt(10.6, 11.9, [['lt', '看见你与 Agent 的每一次协作']], { x: 960, y: 790, align: 'c' }, { inB: 1.2, outB: .8 });
  glowAt(12.6, 0, 1.6);
});
