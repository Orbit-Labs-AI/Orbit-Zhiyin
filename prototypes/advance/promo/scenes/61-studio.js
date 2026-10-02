/* v6 port: insight → studio (a vertical feed: everything rises) */
scene('61-studio', () => {
  shot(1, 71.2, 75.6, { sel: byText('.card.pad.col', '这次会话的启示'), box: [1300, 540, 700, 860], inn: 'rise', out: 'up', rz: 3, prep: (a) => a.go('sessions') });
  txt(71.5, 75.6, [['eb', 'Insight'], ['gap'], ['hv sv', '下次怎么做'], ['md acc', '复盘直接给出改法']], { x: L, y: 540 }, { st: .3 });
  clickAt(1, 74.4, (D) => smallest(D, '.card.pad.col button', '生成规则'), () => {});
  const runCard = (D) => D.querySelectorAll('#main .card.pad.col')[1], skillCard = (D) => smallest(D, '#main .card.col', 'SKILL.md');
  at(75.2, () => { const a = app(0); a.go('studio'); a.click('[data-act="studioStart"]'); solo(0, [runCard, skillCard]); });
  tween(0, 75.8, 1.3, () => Object.assign(framing(0, runCard, [1250, 540, 900, 860]), { ry: -10 }), E.quart, IN.rise);
  txt(76.2, 79.8, [['eb', 'Studio'], ['gap'], ['hv sv', '交给本地 Agent'], ['md acc', '生成 Skill、Hook 与规则']], { x: L, y: 540 }, { st: .3 });
  drive(0, 79.6, 81.6, (p, b, D) => { const ct = D.querySelector('#content'), sk = skillCard(D); if (ct && sk) { if (ct._s0 == null) { ct._s0 = ct.scrollTop; ct._s1 = Math.max(0, sk.offsetTop - 120); } ct.scrollTop = lerp(ct._s0, ct._s1, E.inOut(lp(b, 79.8, 1.6))); } });
  drive(0, 80.6, 84.9, (p, b, D) => { const c = runCard(D); if (c) c.style.opacity = (1 - E.inOut(lp(b, 80.8, .9))).toFixed(3); });
  tween(0, 81.4, 1.2, () => Object.assign(framing(0, skillCard, [1220, 540, 1040, 880], { max: 2.2 }), { ry: 0 }), E.inOut);
  txt(81, 83.8, [['hv sv', '边写边验'], ['md acc', '自检 · 回放 dry-run · 第二视角评分']], { x: L, y: 540 }, { st: .25 });
  tween(0, 83.9, .9, () => OUT.up(decks[0].C), E.in);
});
