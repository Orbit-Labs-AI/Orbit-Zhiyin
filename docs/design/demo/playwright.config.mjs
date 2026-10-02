// Viewports mirror common Mac displays plus a narrow window that triggers the compact (<900px) layout.
import { defineConfig } from '@playwright/test';

const mac = (name, width, height, dpr = 2) => ({ name, use: { viewport: { width, height }, deviceScaleFactor: dpr } });

export default defineConfig({
  testDir: 'tests',
  timeout: 30_000,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    channel: 'chrome',
    headless: true,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    baseURL: 'file://' + new URL('./tandem-demo.html', import.meta.url).pathname,
  },
  projects: [
    mac('mac-14', 1512, 982),
    mac('mac-13', 1280, 800),
    mac('mac-16', 1728, 1117),
    mac('studio', 2560, 1440, 1),
    mac('small', 1024, 700, 1),
    mac('compact', 820, 760, 1),
  ],
});
