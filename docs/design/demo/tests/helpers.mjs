// Shared helpers: open the demo with fonts blocked (offline-safe), collect page errors, wait for a route.
import { expect } from '@playwright/test';

// Route ids come from the page itself (ROUTES in src/js/25-nav.js), so a new page is covered automatically.
export const routeIds = (page) => page.evaluate(() => ROUTES.map((r) => r[0]));

export async function openDemo(page, hash = '') {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  // Only the blocked Google Fonts requests may fail; match on the request URL, not the message text.
  page.on('console', (m) => { if (m.type() === 'error' && !/fonts\.(googleapis|gstatic)\.com/.test(m.location().url)) errors.push(m.text()); });
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto(hash ? '#' + hash : '');
  await expect(page.locator('#main')).not.toBeEmpty();
  return errors;
}

export async function go(page, route) {
  await page.evaluate((r) => go(r), route);
  await expect.poll(() => page.evaluate(() => S.route)).toBe(route);
}

// Close whatever an entry point opened so the next one starts from the plain window.
export const closeAll = (page) => page.evaluate(() => {
  closeOverlay(); closeModal(); closeDD();
  $('#set').hidden = true; S.pop = false; S.hud.open = false; render();
});
