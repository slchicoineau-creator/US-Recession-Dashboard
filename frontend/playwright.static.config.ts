import { defineConfig, devices } from '@playwright/test';

/**
 * Tests for the read-only static snapshot (tools/export_static.py output).
 *
 * Build it first:
 *   python tools/export_static.py --base /recession-dashboard/
 * then:
 *   npx playwright test -c playwright.static.config.ts
 *
 * tools/serve_static.py mimics GitHub Pages: the site lives under the
 * /recession-dashboard/ sub-path and unknown paths get 404.html (the SPA).
 */
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: /static\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5055',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'python tools/serve_static.py --dir site --base /recession-dashboard/ --port 5055',
    cwd: '..',
    url: 'http://127.0.0.1:5055/recession-dashboard/',
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
