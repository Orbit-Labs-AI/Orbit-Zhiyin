// Shared helpers: open the demo with fonts blocked (offline-safe), collect page errors, wait for a route.
import { expect } from '@playwright/test';

export const ROUTES = ['overview', 'persona', 'sessions', 'tools', 'projects', 'sentiment', 'recs', 'library', 'studio'];

export async function openDemo(page, hash = '') {
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error' && !/fonts\.googleapis|ERR_/.test(m.text())) errors.push(m.text()); });
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
  await page.goto(hash ? '#' + hash : '');
  await expect(page.locator('#main')).not.toBeEmpty();
  return errors;
}

// The demo exposes its state through globals in a classic script; read them in page context.
export const state = (page, expr) => page.evaluate(expr);
export async function go(page, route) {
  await page.evaluate((r) => go(r), route);
  await expect.poll(() => page.evaluate(() => S.route)).toBe(route);
}
