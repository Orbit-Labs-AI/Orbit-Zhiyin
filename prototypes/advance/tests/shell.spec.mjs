// Shell (window model + global controls) tests. Each runs in all six Mac viewports (see playwright.config.mjs).
//
// Flow per test:
//  1. window model     open the demo → read #win (left/top/size/data-mode). Stage too small for 900×600 → "fit" (16px margins).
//                      Otherwise the default is the published layout: the window fills the stage (24px sides, 18px top /
//                      bottom) and on stages ≥ 1500px starts at x = 412 so the desktop widgets keep their column (visible,
//                      never covered); shrinking the viewport re-fits an untouched window. Then: drag the title row by (60,40)
//                      → window moved (clamped to the stage); drag the SE handle by (−100,−80) → smaller; drag it far →
//                      clamped to 900×600; a viewport change now keeps the user's size; double-click the title → zoom (fills
//                      the area under the menu bar) → double-click → restored; ⌃⌘F → full screen (menu bar slides away,
//                      window fills the stage) → green light → restored; reload → rect comes back from localStorage.
//  2. sidebar          ⌃⌘S hides / shows the sidebar (toolbar shifts right of the lights); in a window narrower than 900px the
//                      sidebar is hidden by default and the toggle shows it as an overlay that the content scrim closes.
//  3. container query  at the same viewport, narrow the window (S.win.w = 1000) → the overview .two grid drops to one column
//                      and the metric tiles to 3 per row; widen again → restored. Narrow stages assert the single column.
//                      Thresholds follow 90-responsive.css: .two, .sess and .tiles 800 (tiles again at 640), in content-column px.
//                      A toolbar that cannot fit its page title moves items into the » popover instead of clipping it.
//  4. settings         openSettings() → #set fully inside the viewport, six tabs visible, each tab renders, main window
//                      inactive (grey lights); Esc closes it.
//  5. menu-bar panel   click the Orbit status item → #pop right edge aligns with the status item (±1.5px), 6px under the bar.
//  6. HUD              the pill never covers the window's title row; when any snap point is free of the window and the
//                      visible desktop widgets it covers neither — checked at the default layout and again with the window
//                      shrunk to 900×600 in a corner, where the top row is certainly free.
//  7. sheet            openModal() → focus lands on the default (.btn.p) button, the scrim covers exactly the window, the sheet
//                      hangs 52px under the window top; Return triggers the default button, Esc closes.
//  8. shortcuts        ⌥2 → persona, ⌘K → palette, ⌥0 restores a closed window; menu labels match the bindings.
//  9. page hook/event  PAGES[route].keys(e) returning true consumes the key, false lets globals run; toggling the sidebar
//                      dispatches window 'tandem:layout' with {win, side, main}.
// 10. dark contrast    selected sidebar row vs sidebar ≥ 1.3; window / sidebar / card pairwise ≥ 1.15 in dark mode.
// 11. overflow         no horizontal overflow (document, #main, #win inside the viewport) with the sidebar shown / hidden,
//                      zoomed and in full screen, on three representative pages.
// 12. type & chrome    shell text only uses the macOS type scale (10/11/12/13/15/17/22/26); the page title is serif, meta /
//                      counts / eyebrows are mono, nav and the system clock are the system font; resize handles are invisible
//                      (no background, no pseudo content); notifications are 344px wide, 16px from the stage edge, and reveal
//                      their actions on hover.
// 13. motion           every effect of the published demo is still wired up (mac-14 only): keyframes blink / fadein / grow /
//                      pulse / shim / spin plus popin / sheetin / slidein / slideout; .nt slides + fades in and survives hover;
//                      the toast undo countdown ticks; the menu-bar badge changes shape / colour per state and pulses while
//                      running; the switch knob slides; the window scales away on close; the HUD drag shows six snap points,
//                      ⌥-release places it freely, the expanded card grows away from the anchor, the timer / tool name tick;
//                      the reveal runs its ~5s Genesis storyboard; onboarding step 3 appears line by line (Genesis facts).
import { test, expect } from '@playwright/test';
import { openDemo, go } from './helpers.mjs';

const MB = 24, PAD = 16, MIN = { w: 900, h: 600 };
const winBox = (page) => page.evaluate(() => { const el = document.querySelector('#win'); const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height, mode: el.dataset.mode }; });
const box = (page, sel) => page.evaluate((s) => { const el = document.querySelector(s); if (!el) return null; const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }, sel);
async function drag(page, from, to) {
  await page.mouse.move(from.x, from.y); await page.mouse.down();
  await page.mouse.move(from.x + (to.x - from.x) / 2, from.y + (to.y - from.y) / 2, { steps: 3 });
  await page.mouse.move(to.x, to.y, { steps: 3 }); await page.mouse.up();
}
const clampN = (v, a, b) => Math.max(a, Math.min(b, v));
// wait for CSS transitions / animations (sidebar slide, sheet drop, popover scale) before measuring
const settle = (page) => page.evaluate(() => Promise.race([
  Promise.all(document.getAnimations().filter((a) => { const t = a.effect && a.effect.getTiming(); return t && t.iterations !== Infinity; }).map((a) => a.finished.catch(() => {}))),
  new Promise((r) => setTimeout(r, 1500))
]));

test('window model: fit / move / resize / minimum / zoom / full screen / persistence', async ({ page }) => {
  const errors = await openDemo(page);
  const vw = page.viewportSize();
  // the floating HUD is its own always-on-top panel; keep it out of the way so drags land on the window
  await page.evaluate(() => { S.hud.show = false; renderHud(); });
  let r = await winBox(page);
  if (r.mode === 'fit') {
    expect(r.x).toBe(PAD); expect(r.y).toBe(MB + PAD); expect(r.w).toBe(vw.width - PAD * 2); expect(r.h).toBe(vw.height - MB - PAD * 2);
    await expect(page.locator('#win .rz[data-rz="se"]')).toBeHidden();
  } else {
    expect(r.mode).toBe('win');
    // default = the published layout: fills the stage with 24px sides and 18px top / bottom; on stages ≥ 1500px the desktop
    // widgets are shown and the window starts right of their column (x = 24 + 364 + 24), never covering them
    const fill = (w, h) => { const wide = w >= 1500; const x = wide ? 412 : 24; return { x, y: MB + 18, w: w - x - 24, h: h - MB - 36 }; };
    expect(r).toMatchObject(fill(vw.width, vw.height));
    if (vw.width >= 1500) {
      await expect(page.locator('#widgets')).toBeVisible();
      const wg = await box(page, '#widgets'); expect(wg.x).toBe(24); expect(wg.y).toBe(r.y); expect(wg.x + wg.w).toBeLessThanOrEqual(r.x);
    } else await expect(page.locator('#widgets')).toBeHidden();
    // an untouched window follows the viewport (the widget column is given up under 1500px) and comes back with it
    // (−40 / −20 keeps every project above the 900×600 + margins "fit" threshold)
    await page.setViewportSize({ width: vw.width - 40, height: vw.height - 20 });
    await expect.poll(() => winBox(page)).toMatchObject(fill(vw.width - 40, vw.height - 20));
    await page.setViewportSize(vw);
    await expect.poll(() => winBox(page)).toMatchObject(fill(vw.width, vw.height));
    // move by the title row (the page title is not a control)
    const h1 = await box(page, '#main .tbar h1');
    await drag(page, { x: h1.x + h1.w / 2, y: h1.y + h1.h / 2 }, { x: h1.x + h1.w / 2 + 60, y: h1.y + h1.h / 2 + 40 });
    const r2 = await winBox(page);
    expect(r2.x).toBe(clampN(r.x + 60, 0, vw.width - r.w)); expect(r2.y).toBe(clampN(r.y + 40, MB, vw.height - r.h)); expect(r2.w).toBe(r.w);
    // resize from the bottom-right corner
    let se = await box(page, '#win .rz[data-rz="se"]');
    await drag(page, { x: se.x + 5, y: se.y + 5 }, { x: se.x + 5 - 100, y: se.y + 5 - 80 });
    const r3 = await winBox(page);
    expect(r3.w).toBe(Math.max(MIN.w, r2.w - 100)); expect(r3.h).toBe(Math.max(MIN.h, r2.h - 80)); expect(r3.x).toBe(r2.x); expect(r3.y).toBe(r2.y);
    // never below 900×600
    se = await box(page, '#win .rz[data-rz="se"]');
    await drag(page, { x: se.x + 5, y: se.y + 5 }, { x: Math.max(1, se.x - 1500), y: Math.max(1, se.y - 1500) });
    const r4 = await winBox(page);
    expect(r4.w).toBe(MIN.w); expect(r4.h).toBe(MIN.h);
    // once the user has sized it, a viewport change keeps the size (only clamps the position) instead of re-fitting
    await page.setViewportSize({ width: vw.width - 40, height: vw.height - 20 });
    await expect.poll(() => winBox(page)).toMatchObject({ w: MIN.w, h: MIN.h, x: Math.min(r4.x, vw.width - 40 - MIN.w), y: Math.min(r4.y, vw.height - 20 - MIN.h) });
    await page.setViewportSize(vw);
    await expect.poll(() => winBox(page)).toMatchObject(r4);
    r = r4;
  }
  // double-click the title row → zoom → double-click → restore
  await page.locator('#main .tbar h1').dblclick();
  const z = await winBox(page);
  expect(z.mode).toBe('zoom'); expect(z.x).toBe(0); expect(z.y).toBe(MB); expect(z.w).toBe(vw.width); expect(z.h).toBe(vw.height - MB);
  await page.locator('#main .tbar h1').dblclick();
  const back = await winBox(page);
  expect(back.mode).toBe(r.mode); expect(back.w).toBe(r.w); expect(back.h).toBe(r.h);
  // ⌃⌘F → full screen (menu bar away, stage filled) → green light → back
  await page.keyboard.press('Control+Meta+KeyF');
  await expect(page.locator('#desk')).toHaveClass(/\bfs\b/);
  const f = await winBox(page);
  expect(f.mode).toBe('full'); expect(f).toMatchObject({ x: 0, y: 0, w: vw.width, h: vw.height });
  await expect.poll(() => page.evaluate(() => document.querySelector('#mbar').getBoundingClientRect().bottom)).toBeLessThanOrEqual(0.5);
  await page.locator('#wtop .lights .g').click();
  await expect(page.locator('#desk')).not.toHaveClass(/\bfs\b/);
  const g = await winBox(page);
  expect(g.mode).toBe(r.mode); expect(g.w).toBe(r.w); expect(g.h).toBe(r.h);
  // persistence: the rect survives a reload
  await page.reload(); await expect(page.locator('#main')).not.toBeEmpty();
  const p = await winBox(page);
  expect(p.mode).toBe(r.mode); expect(p.w).toBe(r.w); expect(p.h).toBe(r.h); expect(p.x).toBe(r.x); expect(p.y).toBe(r.y);
  expect(errors).toEqual([]);
});

test('sidebar: ⌃⌘S hides and restores; narrow windows get an overlay sidebar', async ({ page }) => {
  const errors = await openDemo(page);
  const narrow = await page.evaluate(() => document.querySelector('#win').classList.contains('narrow'));
  const w = await winBox(page);
  if (!narrow) {
    await expect(page.locator('#side')).toBeVisible();
    await settle(page);
    const side = await box(page, '#side'); expect(side.w).toBe(240); expect(side.x).toBe(w.x);
    const h1a = await box(page, '#main .tbar h1'); expect(h1a.x - w.x).toBeGreaterThanOrEqual(240 + 16);
    await page.keyboard.press('Control+Meta+KeyS');
    await expect(page.locator('#win')).toHaveClass(/\bnosb\b/);
    await expect(page.locator('#side')).toBeHidden();
    // the toolbar moves right of the lights + sidebar toggle
    await expect.poll(async () => (await box(page, '#main .tbar h1')).x - w.x).toBeGreaterThanOrEqual(140);
    const main = await box(page, '#main'); expect(main.x).toBe(w.x); expect(main.w).toBe(w.w);
    await page.locator('#wtop [data-act="sideToggle"]').click();
    await expect(page.locator('#win')).not.toHaveClass(/\bnosb\b/);
    await expect(page.locator('#side')).toBeVisible();
    // re-open through the menu-bar "显示" menu entry to make sure the label matches the state
    const label = await page.evaluate(() => MENUS.view().find((i) => /侧边栏/.test(i.t)));
    expect(label.k).toBe('⌃⌘S'); expect(label.t).toBe('隐藏侧边栏');
  } else {
    await expect(page.locator('#win')).toHaveClass(/\bnosb\b/);
    await expect(page.locator('#side')).toBeHidden();
    await page.locator('#wtop [data-act="sideToggle"]').click();
    await expect(page.locator('#win')).toHaveClass(/\bsbover\b/);
    await expect(page.locator('#side')).toBeVisible();
    await settle(page);
    const side = await box(page, '#side'); expect(side.x).toBe(w.x); expect(side.h).toBe(w.h);
    await page.locator('#sidescrim').click({ position: { x: 600, y: 300 } });
    await expect(page.locator('#win')).not.toHaveClass(/\bsbover\b/);
    await expect(page.locator('#side')).toBeHidden();
  }
  expect(errors).toEqual([]);
});

test('container queries: narrowing the window at a fixed viewport collapses page grids', async ({ page }) => {
  const errors = await openDemo(page);
  const cols = (sel) => page.evaluate((s) => getComputedStyle(document.querySelector(s)).gridTemplateColumns.trim().split(/\s+/).length, sel);
  const mainW = () => page.evaluate(() => document.querySelector('#main').clientWidth);
  const mw = await mainW();
  expect(await cols('.two')).toBe(mw >= 800 ? 2 : 1);
  expect(await cols('.tiles')).toBe(mw >= 800 ? 5 : mw >= 640 ? 3 : 2);
  const r = await winBox(page);
  if (r.mode === 'win' && mw >= 800) {
    await page.evaluate(() => { S.win.w = 1000; applyWin(); });
    await expect.poll(() => mainW()).toBeLessThan(800);
    expect(await cols('.two')).toBe(1); expect(await cols('.tiles')).toBe(3);
    await page.evaluate((w) => { S.win.w = w; applyWin(); }, r.w);
    await expect.poll(() => cols('.two')).toBe(2);
  }
  // sessions page: list + detail side by side only when the content column is ≥ 800px wide
  await go(page, 'sessions');
  expect(await cols('.sess')).toBe((await mainW()) >= 800 ? 2 : 1);
  expect(errors).toEqual([]);
});

test('settings window is fully visible, becomes the key window, every tab renders', async ({ page }) => {
  const errors = await openDemo(page);
  const vw = page.viewportSize();
  await page.evaluate(() => openSettings('general'));
  await expect(page.locator('#set')).toBeVisible();
  const s = await box(page, '#set');
  expect(s.x).toBeGreaterThanOrEqual(0); expect(s.y).toBeGreaterThanOrEqual(MB); expect(s.x + s.w).toBeLessThanOrEqual(vw.width + 0.5); expect(s.y + s.h).toBeLessThanOrEqual(vw.height + 0.5);
  expect(Math.abs(s.x + s.w / 2 - vw.width / 2)).toBeLessThanOrEqual(1);
  await expect(page.locator('#set .tabs button')).toHaveCount(6);
  for (const b of await page.locator('#set .tabs button').all()) { const bb = await b.boundingBox(); expect(bb.x).toBeGreaterThanOrEqual(s.x); expect(bb.x + bb.width).toBeLessThanOrEqual(s.x + s.w + 0.5); }
  await expect(page.locator('#win')).toHaveClass(/\binactive\b/);
  await expect(page.locator('#set')).not.toHaveClass(/\binactive\b/);
  for (const tab of ['sources', 'privacy', 'analysis', 'notify', 'about']) {
    await page.locator('#set .tabs button[data-v="' + tab + '"]').click();
    await expect(page.locator('#set .body')).not.toBeEmpty();
    await expect(page.locator('#set .ptitle')).toHaveText(({ sources: '数据源', privacy: '隐私', analysis: '分析', notify: '通知', about: '关于' })[tab]);
  }
  // a sheet opened from settings attaches to the settings window
  await page.locator('#set .tabs button[data-v="privacy"]').click();
  await page.locator('#set [data-act="setClear"]').click();
  await expect(page.locator('#modal')).toBeVisible();
  await settle(page);
  const sc = await box(page, '#scrim'); const s2 = await box(page, '#set');
  expect(Math.abs(sc.x - s2.x)).toBeLessThanOrEqual(1); expect(Math.abs(sc.w - s2.w)).toBeLessThanOrEqual(1); expect(Math.abs(sc.y - s2.y)).toBeLessThanOrEqual(1);
  await page.keyboard.press('Escape');
  await expect(page.locator('#modal')).toBeHidden();
  await page.keyboard.press('Escape');
  await expect(page.locator('#set')).toBeHidden();
  await expect(page.locator('#win')).not.toHaveClass(/\binactive\b/);
  expect(errors).toEqual([]);
});

test('menu-bar panel hangs under the bar with its right edge on the status item', async ({ page }) => {
  const errors = await openDemo(page);
  await page.locator('.mbar [data-act="pop"]').click();
  await expect(page.locator('#pop')).toBeVisible();
  await settle(page);
  const g = await box(page, '.mbar [data-act="pop"]'); const p = await box(page, '#pop');
  expect(Math.abs((p.x + p.w) - (g.x + g.w))).toBeLessThanOrEqual(1.5);
  expect(p.y).toBe(MB + 6);
  expect(p.x).toBeGreaterThanOrEqual(0);
  await page.keyboard.press('Escape');
  await expect(page.locator('#pop')).toBeHidden();
  expect(errors).toEqual([]);
});

test('HUD stays off the title row and avoids the window and widgets whenever a snap point is free', async ({ page }) => {
  const errors = await openDemo(page);
  await expect(page.locator('#hudPill')).toBeVisible();
  // occupied = the main window plus the visible desktop widgets; "free" = some snap point touches neither
  const probe = () => page.evaluate(() => {
    const rect = (s) => { const el = document.querySelector(s); return el && !el.hidden ? el.getBoundingClientRect() : null; };
    const pill = rect('#hudPill'), w = rect('#win'), g = rect('#widgets');
    const hit = (x, y, pw, ph, r) => !!r && x < r.right && x + pw > r.left && y < r.bottom && y + ph > r.top;
    const occupied = (x, y, pw, ph) => hit(x, y, pw, ph, w) || hit(x, y, pw, ph, g);
    const free = snapPts(pill.width).some((p) => !occupied(p.x, p.y, pill.width, 44));
    return { free, hitsAny: occupied(pill.left, pill.top, pill.width, pill.height), hitsTitle: pill.left < w.right && pill.right > w.left && pill.top < w.top + 52 && pill.bottom > w.top, inside: pill.left >= 0 && pill.top >= 0 && pill.right <= innerWidth && pill.bottom <= innerHeight };
  });
  const res = await probe();
  expect(res.inside).toBe(true);
  expect(res.hitsTitle).toBe(false);
  if (res.free) expect(res.hitsAny).toBe(false);
  // the window shrunk to its minimum in the bottom-left corner frees the top row: the pill must leave window and widgets alone
  if ((await winBox(page)).mode === 'win') {
    await page.evaluate(() => { S.win.x = 0; S.win.y = innerHeight - 600; S.win.w = 900; S.win.h = 600; applyWin(); renderHud(); });
    const r2 = await probe();
    expect(r2.free).toBe(true); expect(r2.hitsAny).toBe(false); expect(r2.hitsTitle).toBe(false); expect(r2.inside).toBe(true);
  }
  expect(errors).toEqual([]);
});

test('sheet: default-button focus, scrim limited to the window, Return and Esc', async ({ page }) => {
  const errors = await openDemo(page);
  const open = () => page.evaluate(() => { ACT.__hit = () => { window.__hit = (window.__hit || 0) + 1; closeModal(); }; openModal(modalHead('测试工作表', '副标题') + '<div class="mb">正文</div><div class="mf"><button type="button" class="btn" data-act="closeModal">取消</button><button type="button" class="btn p" data-act="__hit">确定</button></div>'); });
  await open();
  await expect(page.locator('#modal')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.activeElement && document.activeElement.textContent)).toBe('确定');
  await settle(page);
  const w = await winBox(page); const sc = await box(page, '#scrim'); const m = await box(page, '#modal');
  expect(Math.abs(sc.x - w.x)).toBeLessThanOrEqual(1); expect(Math.abs(sc.y - w.y)).toBeLessThanOrEqual(1); expect(Math.abs(sc.w - w.w)).toBeLessThanOrEqual(1); expect(Math.abs(sc.h - w.h)).toBeLessThanOrEqual(1);
  expect(Math.abs(m.y - (w.y + 52))).toBeLessThanOrEqual(1); expect(m.x).toBeGreaterThanOrEqual(w.x); expect(m.x + m.w).toBeLessThanOrEqual(w.x + w.w + 0.5);
  await page.keyboard.press('Enter');
  expect(await page.evaluate(() => window.__hit)).toBe(1);
  await expect(page.locator('#modal')).toBeHidden(); await expect(page.locator('#scrim')).toBeHidden();
  await open();
  await page.keyboard.press('Escape');
  await expect(page.locator('#modal')).toBeHidden();
  expect(await page.evaluate(() => window.__hit)).toBe(1);
  // the command palette stays a floating panel without a scrim
  await page.keyboard.press('Meta+KeyK');
  await expect(page.locator('#modal.pal')).toBeVisible(); await expect(page.locator('#scrim')).toBeHidden();
  await page.keyboard.press('Escape');
  expect(errors).toEqual([]);
});

test('shortcuts: ⌥digits switch pages, ⌥0 restores the window, labels match bindings', async ({ page }) => {
  const errors = await openDemo(page);
  await page.keyboard.press('Alt+Digit2');
  await expect.poll(() => page.evaluate(() => S.route)).toBe('persona');
  await page.keyboard.press('Alt+Digit1');
  await expect.poll(() => page.evaluate(() => S.route)).toBe('overview');
  await page.evaluate(() => ACT.winClose());
  await expect(page.locator('#win')).toHaveClass(/\bgone\b/);
  await expect(page.locator('#toast')).toContainText('⌥0');
  await page.keyboard.press('Alt+Digit0');
  await expect(page.locator('#win')).not.toHaveClass(/\bgone\b/);
  const labels = await page.evaluate(() => ({
    main: MENUS.window().find((i) => i.t === '主窗口').k, side: MENUS.view().find((i) => /侧边栏/.test(i.t)).k, full: MENUS.view().find((i) => /全屏/.test(i.t)).k,
    page2: MENUS.window().find((i) => i.t === '协作人格').k, keys: Object.fromEntries(KEYS.map((k) => [k[1], k[0]]))
  }));
  expect(labels.main).toBe('⌥0'); expect(labels.side).toBe('⌃⌘S'); expect(labels.full).toBe('⌃⌘F'); expect(labels.page2).toBe('⌥2');
  expect(labels.keys['主窗口（App 内是 ⌘0）']).toBe('⌥0'); expect(labels.keys['显示 / 隐藏侧边栏']).toBe('⌃⌘S'); expect(labels.keys['进入 / 退出全屏']).toBe('⌃⌘F');
  expect(errors).toEqual([]);
});

test('page key hook runs before global shortcuts; layout changes dispatch tandem:layout', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => {
    window.__k = 0; PAGES[S.route].keys = (e) => { if (e.key === 'j') { window.__k++; return true; } return false; };
    window.__lay = []; window.addEventListener('tandem:layout', (e) => window.__lay.push(e.detail));
  });
  await page.keyboard.press('j');
  expect(await page.evaluate(() => window.__k)).toBe(1);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator('#modal')).toBeVisible();
  await expect(page.locator('#modal')).toContainText('键盘快捷键');
  await page.keyboard.press('Escape');
  await page.keyboard.press('j');
  expect(await page.evaluate(() => window.__k)).toBe(2);
  await page.evaluate(() => { delete PAGES[S.route].keys; });
  const narrow = await page.evaluate(() => document.querySelector('#win').classList.contains('narrow'));
  await page.keyboard.press('Control+Meta+KeyS');
  await expect.poll(() => page.evaluate(() => window.__lay.length)).toBeGreaterThanOrEqual(1);
  const d = await page.evaluate(() => window.__lay[window.__lay.length - 1]);
  expect(d.win).toEqual(expect.objectContaining({ w: expect.any(Number), h: expect.any(Number), mode: expect.any(String) }));
  expect(d.main.w).toBeGreaterThan(0);
  expect(d.side).toBe(narrow);
  expect(errors).toEqual([]);
});

test('dark mode: selected row ≥ 1.3 against the sidebar; window / sidebar / card layers pairwise ≥ 1.15', async ({ page }) => {
  const errors = await openDemo(page);
  await page.evaluate(() => { setTheme('dark'); render(); });
  const r = await page.evaluate(() => {
    const parse = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); const p = m[1].split(',').map(parseFloat); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const over = (t, b) => ({ r: t.r * t.a + b.r * (1 - t.a), g: t.g * t.a + b.g * (1 - t.a), b: t.b * t.a + b.b * (1 - t.a), a: 1 });
    const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const bg = (sel) => parse(getComputedStyle(document.querySelector(sel)).backgroundColor);
    const desk = bg('#desk'), win = bg('#main'), side = over(bg('#side'), desk), card = over(bg('#main .card'), win);
    const sel = over(bg('.nav button[aria-current="page"]'), side);
    return { sideSel: ratio(side, sel), winSide: ratio(win, side), sideCard: ratio(side, card), winCard: ratio(win, card) };
  });
  expect(r.sideSel).toBeGreaterThanOrEqual(1.3);
  expect(r.winSide).toBeGreaterThanOrEqual(1.15); expect(r.sideCard).toBeGreaterThanOrEqual(1.15); expect(r.winCard).toBeGreaterThanOrEqual(1.15);
  await page.evaluate(() => { setTheme('system'); render(); });
  expect(errors).toEqual([]);
});

test('shell text uses the macOS type scale and system font; resize handles are invisible', async ({ page }) => {
  const errors = await openDemo(page);
  // open the shell surfaces that render text: menu-bar panel, HUD card, a menu, the settings window, the shortcuts sheet
  await page.evaluate(() => { S.hud.open = true; S.pop = true; render(); openSettings('general'); openKeys(); document.querySelector('.mbar [data-m="view"]').click(); notify({ t: '字号', b: '正文', a1: 'A', force: true }); });
  const r = await page.evaluate(() => {
    const scale = new Set([10, 11, 12, 13, 15, 17, 22, 26]);
    const roots = ['#mbar', '#wtop', '#side', '#main .tbar', '#pop', '#hud', '#dd', '#set', '#modal', '#notes'];
    const offScale = new Set();
    roots.forEach((root) => document.querySelectorAll(root + ', ' + root + ' *').forEach((el) => {
      if (el.closest('svg') || !el.childNodes.length || !Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) return;
      const fs = parseFloat(getComputedStyle(el).fontSize); if (!scale.has(fs)) offScale.add(fs + 'px @ ' + root + ' ' + el.className);
    }));
    const fam = (sel) => getComputedStyle(document.querySelector(sel)).fontFamily;
    const handles = Array.from(document.querySelectorAll('#win .rz')).map((h) => { const cs = getComputedStyle(h), ps = getComputedStyle(h, '::after'); return { bg: cs.backgroundColor, after: ps.content, w: h.offsetWidth, h: h.offsetHeight, radius: cs.borderRadius }; });
    return { offScale: [...offScale], title: fam('#main .tbar h1'), nav: fam('.nav button'), clock: fam('.mbar .clock'), meta: fam('#main .tbar .meta'), eb: fam('#pop .eb'), ct: fam('.nav .ct'), handles };
  });
  expect(r.offScale).toEqual([]);
  expect(r.title.split(',')[0].trim()).toBe('"Source Serif 4"');
  for (const f of [r.nav, r.clock]) expect(f.split(',')[0].trim()).toBe('system-ui');
  expect(r.meta.split(',')[0].trim()).toBe('"JetBrains Mono"'); expect(r.eb.split(',')[0].trim()).toBe('"JetBrains Mono"'); expect(r.ct.split(',')[0].trim()).toBe('"JetBrains Mono"');
  expect(r.handles).toHaveLength(8);
  for (const h of r.handles) { expect(h.bg).toBe('rgba(0, 0, 0, 0)'); expect(h.after).toBe('none'); expect(Math.max(h.w, h.h) <= 10 || Math.min(h.w, h.h) <= 6).toBe(true); expect(h.radius).toBe('0px'); }
  expect(errors).toEqual([]);
});

test('notifications: 344px wide, 16px from the stage edge, actions revealed on hover', async ({ page }) => {
  const errors = await openDemo(page);
  const vw = page.viewportSize();
  // the welcome banner is posted 800ms after load (99-init.js): let it arrive, clear it, then post the banner under test
  await expect(page.locator('#notes .nt')).toHaveCount(1);
  await page.evaluate(() => { document.querySelectorAll('#notes .nt').forEach((n) => n.remove()); notify({ t: '测试通知', b: '正文', a1: '查看', a2: '稍后', force: true }); });
  const nt = page.locator('#notes .nt', { hasText: '测试通知' });
  await expect(nt).toBeVisible();
  await settle(page);
  const b = await nt.boundingBox();
  expect(Math.round(b.width)).toBe(Math.min(344, vw.width - 32)); expect(Math.round(vw.width - (b.x + b.width))).toBe(16); expect(b.y).toBeGreaterThanOrEqual(MB + 4);
  const acts = nt.locator('.nt-a');
  expect((await acts.boundingBox()).height).toBe(0);
  await nt.hover();
  await expect.poll(async () => (await acts.boundingBox()).height).toBeGreaterThanOrEqual(18);
  await expect(nt.locator('.nt-x')).toHaveCSS('opacity', '1');
  await nt.locator('.nt-a .btn.p').click();
  await expect(nt).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('no horizontal overflow with the sidebar shown / hidden, zoomed and in full screen', async ({ page }) => {
  const errors = await openDemo(page);
  const check = async (label) => {
    const o = await page.evaluate(() => { const m = document.querySelector('#main'), w = document.querySelector('#win').getBoundingClientRect(); return { page: document.documentElement.scrollWidth - window.innerWidth, main: m.scrollWidth - m.clientWidth, winRight: w.right - window.innerWidth, winLeft: w.left }; });
    expect.soft(o.page, label + ' page').toBeLessThanOrEqual(0); expect.soft(o.main, label + ' main').toBeLessThanOrEqual(1); expect.soft(o.winRight, label + ' win right').toBeLessThanOrEqual(0.5); expect.soft(o.winLeft, label + ' win left').toBeGreaterThanOrEqual(0);
  };
  for (const r of ['overview', 'sessions', 'studio']) {
    await go(page, r); await check(r);
    await page.evaluate(() => { S.side = false; applyWin(); }); await check(r + ' nosb');
    await page.evaluate(() => { S.side = true; S.win.zoom = true; applyWin(); }); await check(r + ' zoom');
    await page.evaluate(() => { S.win.zoom = false; S.win.full = true; applyWin(); }); await check(r + ' full');
    await page.evaluate(() => { S.win.full = false; applyWin(); });
  }
  expect(errors).toEqual([]);
});

test('motion inventory: the published effects plus the shell additions are wired up', async ({ page }) => {
  // effects.spec.mjs (from main) guards the baseline effects; this adds the shell's own: badge pulse, notification slide-out,
  // sheet / popover / palette entrances, HUD card direction, density bars, the reveal storyboard labels, reduced motion.
  test.skip(test.info().project.name !== 'mac-14', 'motion coverage runs once, at the default size');
  // a paused fake clock makes every timer deterministic: timeouts only fire through clock.runFor()
  const time = new Date('2026-10-02T04:00:00Z');
  await page.clock.install({ time }); await page.clock.pauseAt(time);
  const errors = await openDemo(page);
  const anim = (sel, pseudo) => page.evaluate(([s, p]) => { const el = document.querySelector(s); return el ? getComputedStyle(el, p || null).animationName : null; }, [sel, pseudo]);
  const rules = (name) => page.evaluate((n) => { for (const sh of document.styleSheets) { let rs; try { rs = sh.cssRules; } catch (e) { continue; } for (const r of rs) if (r.type === CSSRule.KEYFRAMES_RULE && r.name === n) return r.cssText; } return null; }, name);
  for (const k of ['blink', 'fadein', 'grow', 'pulse', 'shim', 'spin', 'popin', 'sheetin', 'slidein', 'slideout', 'badgepulse']) expect(await rules(k), '@keyframes ' + k).not.toBeNull();
  // notification: fades while sliding in from the right, survives hover, slides out on dismiss
  await page.clock.runFor(900); await expect(page.locator('#notes .nt')).toHaveCount(1);
  await page.evaluate(() => { document.querySelectorAll('#notes .nt').forEach((n) => n.remove()); notify({ t: '动效', b: '正文', a1: '好', ms: 700, force: true }); });
  const nt = page.locator('#notes .nt', { hasText: '动效' });
  await expect(nt).toBeVisible();
  expect(await anim('#notes .nt')).toBe('slidein');
  const kf = await rules('slidein'); expect(kf).toMatch(/opacity:\s*0/); expect(kf).toMatch(/translateX\(24px\)/);
  await nt.hover();
  await page.clock.runFor(1500);                      // lifetime (700ms) passed while hovered → kept, re-checked 1.5s later
  await expect(nt).toBeVisible(); await expect(nt).not.toHaveClass(/\bout\b/);
  await page.mouse.move(5, 500);
  await page.clock.runFor(800);                       // the deferred check fires → slide-out starts
  await expect(nt).toHaveClass(/\bout\b/);
  await page.clock.runFor(500); await expect(nt).toHaveCount(0);
  // menu-bar badge pulses only while running (shape / colour per state are guarded by effects.spec.mjs)
  expect(await anim('.mbar .glyph .badge')).toBe('badgepulse');
  await page.evaluate(() => { S.sim = 'waiting'; renderMbar(); });
  expect(await anim('.mbar .glyph .badge')).toBe('none');
  await page.evaluate(() => { S.sim = 'running'; renderMbar(); });
  // sheet / popover / palette entrances
  await page.evaluate(() => openKeys()); expect(await anim('#modal')).toBe('sheetin'); await page.evaluate(() => closeModal());
  await page.evaluate(() => { S.pop = true; render(); }); expect(await anim('#pop')).toBe('popin'); await page.evaluate(() => { S.pop = false; render(); });
  await page.evaluate(() => openPalette()); expect(await anim('#modal.pal')).toBe('popin'); await page.evaluate(() => closeModal());
  expect(await anim('#hudPill .dot.live')).toBe('pulse');
  // HUD: tool name scrolls every 4s, density bars drawn, the expanded card grows away from the anchor
  const tool0 = await page.locator('#hudPill [data-hudtool]').textContent();
  await page.clock.runFor(4100);
  expect(await page.locator('#hudPill [data-hudtool]').textContent()).not.toBe(tool0);
  expect(await page.locator('#hudPill svg rect').count()).toBe(5);
  await page.evaluate(() => { S.hud.snap = 'tr'; S.hud.user = true; S.hud.open = true; renderHud(); });
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#hud')).flexDirection)).toBe('column');
  await page.evaluate(() => { S.hud.snap = 'br'; renderHud(); });
  expect(await page.evaluate(() => getComputedStyle(document.querySelector('#hud')).flexDirection)).toBe('column-reverse');
  // a pill the user parked top-right steps below visible notification banners (they share the corner and stay on top)
  await page.evaluate(() => { S.hud.open = false; S.hud.snap = 'tr'; S.hud.user = true; renderHud(); });
  expect((await box(page, '#hudPill')).y).toBe(MB + 8);
  await page.evaluate(() => notify({ t: '占位', b: '横幅在悬浮组件上方', ms: 60000, force: true }));
  await expect.poll(async () => { const n = await box(page, '#notes .nt'); const p = await box(page, '#hudPill'); return p.y >= n.y + n.h + 7; }).toBe(true);
  // dismissing the banner (slide-out) re-places the pill at once, before the banner is gone
  await page.evaluate(() => document.querySelectorAll('#notes .nt').forEach((n) => noteDismiss(n)));
  await expect.poll(async () => (await box(page, '#hudPill')).y).toBe(MB + 8);
  await page.clock.runFor(500); await expect(page.locator('#notes .nt')).toHaveCount(0);
  await page.evaluate(() => { S.hud.user = false; renderHud(); });
  // reveal storyboard (Genesis 2–5, ~4.9s): five stage labels at 0 / 0.7 / 1.8 / 3.1 / 4.9 s; pet (radar) grows, code fades in
  await page.evaluate(() => openReveal());
  await expect(page.locator('#revStage')).toContainText('01 /');
  await page.clock.runFor(750); await expect(page.locator('#revStage')).toContainText('02 /');
  await page.clock.runFor(1150); await expect(page.locator('#revStage')).toContainText('03 /');
  await page.clock.runFor(1300); await expect(page.locator('#revStage')).toContainText('04 /');
  expect(await anim('.reveal .pet')).toBe('grow'); expect(await anim('.reveal .code')).toBe('fadein');
  await page.clock.runFor(1800); await expect(page.locator('#revStage')).toContainText('05 /');
  await page.evaluate(() => { closeOverlay(); render(); });
  // reduced motion: the sheet entrance collapses to ~0ms
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => openKeys());
  expect(parseFloat(await page.evaluate(() => getComputedStyle(document.querySelector('#modal')).animationDuration))).toBeLessThan(0.01);
  await page.evaluate(() => closeModal());
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  expect(errors).toEqual([]);
});
