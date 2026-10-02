import { test, expect } from '@playwright/test';
import { readFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

const url = process.env.TANDEM_DESKTOP_TEST_URL;
const token = process.env.TANDEM_API_TOKEN;
test.skip(!url, 'Run against an isolated desktop helper with the acceptance script.');

test('Advance opening flow imports seven sources and shows stored sessions and analysis', async ({ page }) => {
  test.setTimeout(90000);
  const errors = [];
  const failedRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/v1/') && response.status() >= 400) failedRequests.push(response.status() + ' ' + response.url());
  });
  await page.addInitScript(value => { window.__TANDEM_TOKEN__ = value; }, token);
  await page.goto(url + '/app');
  const roots = JSON.parse(readFileSync(process.env.TANDEM_TEST_SOURCES, 'utf8'));
  await page.getByRole('button', { name: '选择数据源', exact: true }).click();
  for (const [agent, root] of Object.entries(roots)) {
    await page.locator('#appAgentRoot').selectOption(agent);
    await page.locator('#appRoot').fill(root);
    await page.getByRole('button', { name: '添加', exact: true }).click();
    await expect(page.locator('.srcrow').filter({ hasText: root }).locator('input')).toBeChecked();
  }
  await expect(page.locator('.srcrow input:checked')).toHaveCount(7);
  await page.locator('[data-chg=appRecent]').uncheck();
  await page.getByRole('button', { name: '开始导入', exact: true }).click();
  await expect(page.getByRole('heading', { name: '导入结果已保存' })).toBeVisible({ timeout: 30000 });
  await expect(page.locator('#overlay [role=status]')).toContainText('completed');
  const stored = await page.evaluate(async () => {
    const response = await fetch('/v1/app/state', { headers: { Authorization: 'Bearer ' + window.__TANDEM_TOKEN__ } });
    return response.json();
  });
  expect(stored.storage.tables.source).toBe(7);
  expect(stored.storage.tables.session).toBeGreaterThanOrEqual(9);
  expect(Object.values(stored.jobs).at(-1).results).toHaveLength(7);
  const shots = resolve(process.env.TANDEM_SCREENSHOTS || '../../../.local/desktop-demo/screenshots');
  mkdirSync(shots, { recursive: true });
  await page.screenshot({ path: shots + '/import-complete.png' });
  await page.getByRole('button', { name: '查看会话与存储结果' }).click();
  await expect(page.locator('.app-content tbody tr')).not.toHaveCount(0);
  await page.locator('[data-chg=appAgent]').selectOption('codex');
  await expect(page.locator('.app-content tbody')).toContainText('取自首条消息');
  await expect(page.locator('.app-content tbody')).not.toContainText('未命名会话');
  await page.locator('.app-content tbody button').first().click();
  await expect(page.locator('.app-event')).not.toHaveCount(0);
  await expect(page.locator('.app-context-group')).not.toHaveCount(0);
  await page.locator('.app-context-group > summary').first().click();
  await page.locator('.app-context-group').first().scrollIntoViewIfNeeded();
  await expect(page.locator('.app-context-group')).toContainText('运行环境快照');
  await expect(page.locator('.app-context-group .app-event > pre')).toHaveCount(0);
  await page.screenshot({ path: shots + '/session-evidence.png' });
  await page.locator('#modal').getByRole('button', { name: '关闭', exact: true }).click();
  for (const title of ['概览', '协作人格', '工具调用', '项目习惯', '情绪与语义', '优化建议', '资源库', '生成工坊']) {
    await page.locator('#side').getByRole('button', { name: title, exact: true }).click();
    await expect(page.locator('.app-content [role=status]')).toHaveCount(0);
    await expect(page.getByRole('heading', { name: '需要处理', exact: true })).toHaveCount(0);
  }
  await page.getByRole('button', { name: '数据与设置', exact: true }).click();
  await expect(page.getByRole('heading', { name: '存储与维护' })).toBeVisible();
  await page.screenshot({ path: shots + '/storage.png' });
  const download = page.waitForEvent('download');
  await page.locator('#side').getByRole('button', { name: '概览', exact: true }).click();
  await expect(page.locator('.app-content [role=status]')).toHaveCount(0);
  await page.getByRole('button', { name: '导出 JSON', exact: true }).click();
  expect((await download).suggestedFilename()).toBe('tandem-analysis.json');
  await page.reload();
  await expect(page.getByRole('dialog', { name: '首次启动' })).toHaveCount(0);
  await expect(page.locator('#side')).toContainText('已存储');
  expect(errors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
