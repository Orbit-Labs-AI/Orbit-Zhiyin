// Every page renders without runtime errors, and no page scrolls the desktop sideways.
import { test, expect } from '@playwright/test';
import { ROUTES, openDemo, go } from './helpers.mjs';

test('all pages render without errors or horizontal overflow', async ({ page }) => {
  const errors = await openDemo(page);
  for (const r of ROUTES) {
    await go(page, r);
    await expect(page.locator('#main')).not.toBeEmpty();
    const over = await page.evaluate(() => {
      const m = document.querySelector('#main');
      return { page: document.documentElement.scrollWidth - window.innerWidth, main: m.scrollWidth - m.clientWidth };
    });
    expect.soft(over.page, r + ' page overflow').toBeLessThanOrEqual(0);
    expect.soft(over.main, r + ' main overflow').toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});
