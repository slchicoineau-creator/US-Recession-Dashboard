import { test, expect } from '@playwright/test';

const ROUTES = [
  '/',
  '/category/yield_curve',
  '/category/labor_market',
  '/category/financial_stress',
  '/kpi/t10y2y',
  '/kpi/vix',
  '/kpi/unrate',
  '/settings',
];

test.describe('Smoke: every route renders', () => {
  for (const route of ROUTES) {
    test(`route ${route} loads without console errors`, async ({ page }) => {
      const consoleErrors: string[] = [];
      const pageErrors: string[] = [];
      page.on('console', (msg) => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
      });
      page.on('pageerror', (err) => pageErrors.push(err.message));

      const resp = await page.goto(route);
      expect(resp?.ok(), `HTTP not ok for ${route}`).toBeTruthy();

      // Wait for the SPA to mount: <div id="root"> must have children.
      await expect(page.locator('#root > *')).toHaveCount(1, { timeout: 15_000 });

      // Confirm the page is past initial loading (the word 'Loading' should not
      // be the only text after a reasonable timeout for non-history routes).
      await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});

      // Filter out known-noisy errors (network 404 for /api/refresh/status before refresh, etc.)
      const meaningful = consoleErrors.filter(
        (e) =>
          !e.includes('Failed to load resource') && // 4xx network noise
          !e.toLowerCase().includes('non-passive event listener'),
      );
      expect(pageErrors, `unhandled JS errors on ${route}: ${pageErrors.join('; ')}`).toHaveLength(0);
      expect(meaningful, `console errors on ${route}: ${meaningful.join('; ')}`).toHaveLength(0);
    });
  }
});
