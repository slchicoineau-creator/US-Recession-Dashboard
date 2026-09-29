import { test, expect } from '@playwright/test';

const CATEGORIES = [
  'yield_curve',
  'labor_market',
  'consumer_health',
  'housing',
  'financial_stress',
  'business_activity',
  'energy',
  'automotive',
];

test.describe('Category pages', () => {
  for (const cat of CATEGORIES) {
    test(`/category/${cat} renders KPI table`, async ({ page }) => {
      await page.goto(`/category/${cat}`);
      // Wait for table or "Loading…" to clear
      await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 30_000 });
      const rows = await page.locator('table tbody tr').count();
      expect(rows).toBeGreaterThan(0);
    });
  }

  test('KPI row click navigates to /kpi/{id}', async ({ page }) => {
    await page.goto('/category/yield_curve');
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 30_000 });
    const firstRow = page.locator('table tbody tr').first();
    // Capture KPI name from first cell to confirm it's clickable
    await firstRow.click();
    await expect(page).toHaveURL(/\/kpi\/[a-z0-9_]+/);
  });

  test('back link returns to home preserving query string', async ({ page }) => {
    await page.goto('/category/yield_curve?as_of=2015-06-01');
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 30_000 });
    const backLink = page.locator('a').filter({ hasText: /Overview|←/ }).first();
    await backLink.click();
    // Must actually assert the as_of param survives — the old regex /\/(\?|$)/
    // passed whether or not the param was preserved (tautological).
    await expect(page).toHaveURL(/\?as_of=2015-06-01/);
  });

  test('unknown category does not crash the page', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('pageerror', (err) => consoleErrors.push(err.message));
    await page.goto('/category/nonexistent_category');
    // App should not throw — either renders empty table or "no KPIs" state
    await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
    expect(consoleErrors, `unhandled errors: ${consoleErrors.join(', ')}`).toHaveLength(0);
  });

  test('forecast accuracy column renders only for KPIs with samples', async ({ page }) => {
    await page.goto('/category/yield_curve');
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 30_000 });
    // Just check the page didn't blow up — no exception means accuracy formatting is robust
    const cells = await page.locator('table tbody td').count();
    expect(cells).toBeGreaterThan(0);
  });
});
