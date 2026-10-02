// Guards the motion and live effects of the baseline demo (artifact v2 = main c97c818). Redesigns may change how these
// look, but each effect must keep working; replacing one needs an equal-or-better substitute and an update here.
//
// Test flow (each test starts from a fresh page at mac-14 unless noted):
//  1 keyframes      stylesheet still defines spin / pulse / blink (caret) / shim (shimmer) / fadein / grow
//  2 reveal         openReveal() plays a staged ~3 s sequence (stage label advances), click skips to the end;
//                   with prefers-reduced-motion it opens already settled
//  3 onboarding     step 3 of first launch completes its steps one by one (OB.prog 0 → 3 over time)
//  4 replay         startPlay() advances S.sess.ph over ~8 s and stops at the end; ⌘/Ctrl + wheel zooms;
//                   the time/step axis toggle switches S.sess.axis; the playhead can be set and re-rendered
//  5 studio         a generation run walks its steps, streams code lines, keeps a live log, and can be stopped
//  6 typing         「重新生成」types the AI lede progressively; 「问本地 Agent」streams its answer with a caret
//  7 hud            dragging the pill shows 6 snap points and snaps on release; ⌥ places it freely;
//                   the live timer ticks
//  8 status         menu-bar badge differs by shape and colour per state and pulses while running;
//                   notifications slide in and stay while hovered; the undo toast counts down
//  9 transitions    switch knob, sidebar and window close/minimise animate; reduced motion collapses durations
import { test, expect } from '@playwright/test';
import { openDemo, go, closeAll } from './helpers.mjs';

const ONLY = (name) => test.skip(test.info().project.name !== name, 'effects run once, at ' + name);
const textLen = (page, sel) => page.evaluate((s) => (document.querySelector(s)?.textContent || '').length, sel);

test('keyframes for spin, pulse, caret, shimmer, fade-in and grow exist', async ({ page }) => {
  ONLY('mac-14');
  await openDemo(page);
  const names = await page.evaluate(() => {
    const out = new Set();
    for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; } for (const r of rules) if (r.type === CSSRule.KEYFRAMES_RULE) out.add(r.name); }
    return [...out];
  });
  for (const k of ['spin', 'pulse', 'blink', 'shim', 'fadein', 'grow']) expect(names, 'missing @keyframes ' + k).toContain(k);
});

test('persona reveal plays in stages, can be skipped, and respects reduced motion', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => openReveal());
  const box = page.locator('#revBox');
  await expect(box).toBeVisible();
  await expect(box).not.toHaveClass(/skip/);
  const stage0 = await page.locator('#revStage').textContent();
  await expect.poll(() => page.locator('#revStage').textContent(), { timeout: 2500 }).not.toBe(stage0);
  await box.click({ position: { x: 20, y: 200 } });
  await expect(box).toHaveClass(/skip/);
  await page.evaluate(() => closeOverlay());
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revBox')).toHaveClass(/skip/);
  expect(errors).toEqual([]);
});

test('first-launch step 3 completes its steps one by one', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.evaluate(() => { openOnboarding(0); ACT.obNext(); ACT.obStart(); });
  const seen = new Set();
  await expect.poll(async () => { const p = await page.evaluate(() => (typeof OB !== 'undefined' && OB ? OB.prog : null)); seen.add(p); return p; }, { timeout: 10000 }).toBeGreaterThanOrEqual(3);   // the Genesis sequence reaches step 4 at ≈ 6.7 s
  expect([...seen].filter((x) => typeof x === 'number').length, 'progress should pass through intermediate steps').toBeGreaterThan(2);
  expect(errors).toEqual([]);
});

test('trajectory replay advances the playhead, zooms with ⌘/Ctrl + wheel and switches to step layout', async ({ page }) => {
  ONLY('mac-14');
  test.setTimeout(30_000);
  const errors = await openDemo(page);
  await go(page, 'sessions');
  await page.evaluate(() => { S.sess.ph = 0; startPlay(); });
  await expect.poll(() => page.evaluate(() => S.sess.playing)).toBe(true);
  const ph1 = await page.evaluate(() => S.sess.ph);
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => S.sess.ph)).toBeGreaterThan(ph1);
  await expect.poll(() => page.evaluate(() => S.sess.playing), { timeout: 12_000 }).toBe(false);
  const end = await page.evaluate(() => { const s = BYID[S.sess.sel]; return [S.sess.ph, traj(s).T]; });
  expect(end[0]).toBeGreaterThanOrEqual(end[1] - 0.1);
  // ⌘/Ctrl + wheel over the timeline zooms in.
  const z0 = await page.evaluate(() => S.sess.zoom);
  const box = page.locator('#tlBox');
  await box.hover();
  await page.keyboard.down('Control');
  await page.mouse.wheel(0, -200);
  await page.keyboard.up('Control');
  await expect.poll(() => page.evaluate(() => S.sess.zoom)).toBeGreaterThan(z0);
  // Step layout and a manually placed playhead re-render the timeline.
  await page.evaluate(() => { S.sess.axis = 'step'; S.sess.ph = 5; updTimeline(); });
  await expect(box).not.toBeEmpty();
  expect(errors).toEqual([]);
});

test('studio run walks its steps, streams lines and can be stopped', async ({ page }) => {
  ONLY('mac-14');
  test.setTimeout(30_000);
  const errors = await openDemo(page);
  await go(page, 'studio');
  await page.evaluate(() => { S.studio.goal = S.studio.goal || '测试目标'; ACT.studioStart(); });
  await expect.poll(() => page.evaluate(() => S.studio.run && S.studio.run.step), { timeout: 8000 }).toBeGreaterThanOrEqual(2);
  await expect.poll(() => page.evaluate(() => S.studio.run.lines), { timeout: 8000 }).toBeGreaterThan(1);
  const logN = await page.evaluate(() => S.studio.run.log.length);
  expect(logN).toBeGreaterThan(1);
  await page.evaluate(() => ACT.studioStop());
  const stopped = await page.evaluate(() => [S.studio.run.stopped, S.studio.run.step]);
  expect(stopped[0]).toBe(true);
  await page.waitForTimeout(1500);
  expect(await page.evaluate(() => S.studio.run.step), 'stopped run must not advance').toBe(stopped[1]);
  // A full run finishes on its own.
  await page.evaluate(() => ACT.studioStart());
  await expect.poll(() => page.evaluate(() => S.studio.run.done), { timeout: 15_000 }).toBe(true);
  expect(errors).toEqual([]);
});

test('AI lede regeneration types out, and the local-agent answer streams with a caret', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await go(page, 'overview');
  await page.evaluate(() => ACT.regen());
  await page.waitForTimeout(120);
  const a = await textLen(page, '#aiLead');
  await page.waitForTimeout(400);
  const b = await textLen(page, '#aiLead');
  expect(b).toBeGreaterThan(a);
  await page.evaluate(() => { openAsk('overview'); ACT.askPick({ dataset: { i: 0 } }); });
  await expect(page.locator('#askA .caret')).toBeVisible();
  const c = await textLen(page, '#askT');
  await page.waitForTimeout(300);
  expect(await textLen(page, '#askT')).toBeGreaterThan(c);
  expect(errors).toEqual([]);
});

test('floating HUD shows six snap points while dragged, snaps, places freely with ⌥, and its timer ticks', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  const pill = page.locator('#hudPill');
  await expect(pill).toBeVisible();
  const t0 = await page.locator('#hud [data-live]').first().textContent();
  await expect.poll(() => page.locator('#hud [data-live]').first().textContent(), { timeout: 3000 }).not.toBe(t0);
  // The pill rests at the first snap point free of the window and widgets (bottom-left at mac-14), so drag towards the stage
  // centre to stay inside the viewport.
  const vw = page.viewportSize();
  const r = await pill.boundingBox();
  await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2);
  await page.mouse.down();
  await page.mouse.move(vw.width / 2, vw.height / 2, { steps: 8 });
  await expect(page.locator('.snap')).toHaveCount(6);
  await page.mouse.up();
  await expect(page.locator('.snap')).toHaveCount(0);
  expect(await page.evaluate(() => S.hud.snap)).toBeTruthy();
  const r2 = await pill.boundingBox();
  await page.mouse.move(r2.x + r2.width / 2, r2.y + r2.height / 2);
  await page.mouse.down();
  await page.keyboard.down('Alt');
  await page.mouse.move(r2.x + r2.width / 2 - 40, r2.y + r2.height / 2 + (r2.y > vw.height / 2 ? -60 : 60), { steps: 8 });
  await page.mouse.up();
  await page.keyboard.up('Alt');
  expect(await page.evaluate(() => S.hud.snap)).toBeNull();
  expect(errors).toEqual([]);
});

test('menu-bar badge encodes state by shape and colour and pulses while running', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  const badge = page.locator('#mbar .badge');
  const look = () => badge.evaluate((el) => { const cs = getComputedStyle(el); return [cs.backgroundColor, cs.borderRadius, cs.transform, cs.animationName, el.className].join('|'); });
  const looks = {};
  for (const k of ['running', 'waiting', 'stuck', 'done']) { await page.evaluate((x) => { simEvent(x); render(); }, k); looks[k] = await look(); }
  expect(new Set(Object.values(looks)).size, JSON.stringify(looks)).toBe(4);
  // Shape differs between waiting and stuck, not only colour.
  const shape = (s) => s.split('|').slice(1, 3).join('|');
  expect(shape(looks.waiting)).not.toBe(shape(looks.stuck));
  // While running, the live dot (HUD pill and menu-bar panel) pulses.
  await page.evaluate(() => { simEvent('running'); S.pop = true; render(); });
  const pulsing = await page.evaluate(() => ['#hud', '#pop'].map((root) => [...document.querySelectorAll(root + ' .live')].some((el) => getComputedStyle(el).animationName.includes('pulse'))));
  expect(pulsing, 'HUD / panel live dot pulses').toEqual([true, true]);
  expect(errors).toEqual([]);
});

test('notifications slide in and stay while hovered; the undo toast counts down', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  await page.waitForTimeout(900); // let the welcome notification (posted ~0.8 s after load) arrive first
  await page.evaluate(() => { document.querySelectorAll('#notes .nt').forEach((n) => n.remove()); notify({ t: '测试通知', b: '悬停时不消失', ms: 900 }); });
  const nt = page.locator('#notes .nt', { hasText: '测试通知' });
  await expect(nt).toBeVisible();
  expect(await nt.evaluate((el) => getComputedStyle(el).animationName)).not.toBe('none');
  await nt.hover();
  await page.waitForTimeout(1600);
  await expect(nt).toBeVisible();
  await page.mouse.move(5, 5);
  await expect(nt).toHaveCount(0, { timeout: 4000 });
  await page.evaluate(() => toast('已安装', { act: '撤销', sec: 5, onAct: () => {} }));
  const btn = page.locator('[data-act="toastAct"]');
  await expect(btn).toContainText('5');
  await expect(btn).toContainText('4', { timeout: 2500 });
  expect(errors).toEqual([]);
});

test('switches, sidebar and window close/minimise animate; reduced motion collapses them', async ({ page }) => {
  ONLY('mac-14');
  const errors = await openDemo(page);
  const dur = (sel, pseudo) => page.evaluate(([s, p]) => { const el = document.querySelector(s); if (!el) return null; const cs = getComputedStyle(el, p || null); return Math.max(...cs.transitionDuration.split(',').map((x) => parseFloat(x) || 0)); }, [sel, pseudo]);
  await page.evaluate(() => openSettings('general'));
  expect(await dur('#set .sw', '::after'), 'switch knob slides').toBeGreaterThan(0.05);
  await closeAll(page);
  expect(await dur('#win'), 'window close/minimise transition').toBeGreaterThan(0.05);
  // In a narrow window the sidebar becomes a drawer that slides.
  await page.setViewportSize({ width: 820, height: 760 });
  await page.evaluate(() => render());
  expect(await dur('#side'), 'narrow-window sidebar drawer slides').toBeGreaterThan(0.05);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  expect(await dur('#win'), 'reduced motion').toBeLessThan(0.01);
  expect(await dur('#side'), 'reduced motion').toBeLessThan(0.01);
  expect(errors).toEqual([]);
});
