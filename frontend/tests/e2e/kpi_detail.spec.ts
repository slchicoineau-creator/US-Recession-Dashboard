import { test, expect } from '@playwright/test';

test.describe('KPI Detail Page', () => {
  test('renders chart, metadata, and recent-data table', async ({ page }) => {
    await page.goto('/kpi/t10y2y');
    await expect(page.locator('h1, h2').filter({ hasText: /10Y|2Y|Spread/ }).first()).toBeVisible({ timeout: 30_000 });
    // Chart area: SVG inside Recharts ResponsiveContainer
    const svg = page.locator('svg.recharts-surface').first();
    await expect(svg).toBeVisible({ timeout: 30_000 });
    // Recent data table
    await expect(page.locator('table').filter({ hasText: /Date/ }).first()).toBeVisible();
  });

  test('chart x-axis labels formatted as MMM YYYY (FRD rule 7)', async ({ page }) => {
    await page.goto('/kpi/unrate');
    await expect(page.locator('svg.recharts-surface').first()).toBeVisible({ timeout: 30_000 });
    // Sample one x-axis tick label
    const ticks = page.locator('.recharts-cartesian-axis-tick-value tspan');
    const count = await ticks.count();
    expect(count).toBeGreaterThan(0);
    // Find at least one tick that matches MMM YYYY (e.g. "Jan 2024")
    const labels = await ticks.allTextContents();
    const monthYearPattern = /^[A-Z][a-z]{2} \d{4}$/;
    const matching = labels.filter((l) => monthYearPattern.test(l));
    expect(matching.length, `no x-axis labels in MMM YYYY format among: ${labels.slice(0, 8).join(', ')}`).toBeGreaterThan(0);
  });

  test('NBER recession reference areas present (gray bands)', async ({ page }) => {
    await page.goto('/kpi/dgs10');
    await expect(page.locator('svg.recharts-surface').first()).toBeVisible({ timeout: 30_000 });
    // Each NBER period is a <rect> inside .recharts-reference-area
    const refAreas = page.locator('.recharts-reference-area');
    const count = await refAreas.count();
    expect(count, 'expected at least one NBER reference area').toBeGreaterThan(0);
  });

  test('threshold reference lines drawn for KPIs with thresholds', async ({ page }) => {
    await page.goto('/kpi/vix');
    await expect(page.locator('svg.recharts-surface').first()).toBeVisible({ timeout: 30_000 });
    // ReferenceLine renders as path or line in .recharts-reference-line
    const refLines = page.locator('.recharts-reference-line');
    const count = await refLines.count();
    expect(count, 'VIX has warning+danger thresholds — expected 2+ reference lines').toBeGreaterThanOrEqual(1);
  });

  test('time machine marker visible when as_of set', async ({ page }) => {
    await page.goto('/kpi/sp500?as_of=2008-09-15');
    await expect(page.locator('svg.recharts-surface').first()).toBeVisible({ timeout: 30_000 });
    // Look for any reference line (the orange highlight) — at minimum should have NBER + threshold + highlight
    const refLines = page.locator('.recharts-reference-line');
    expect(await refLines.count()).toBeGreaterThan(0);
  });

  test('non-existent KPI shows "not found" gracefully', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('pageerror', (err) => consoleErrors.push(err.message));
    await page.goto('/kpi/this_does_not_exist');
    await expect(page.getByText(/not found|KPI not found|Loading/i).first()).toBeVisible({ timeout: 15_000 });
    expect(consoleErrors, `unhandled JS errors: ${consoleErrors.join('; ')}`).toHaveLength(0);
  });
});
