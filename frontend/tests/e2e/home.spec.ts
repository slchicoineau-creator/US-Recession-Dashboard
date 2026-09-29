import { test, expect } from '@playwright/test';

test.describe('HomePage — gauge, score, banners', () => {
  test('renders gauge with valid score 0–100', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    // Gauge SVG carries aria-label="Recession Risk Score N"
    const gauge = page.locator('svg[aria-label*="Recession Risk Score"]').first();
    await expect(gauge).toBeVisible();
    const aria = await gauge.getAttribute('aria-label');
    expect(aria).toMatch(/Recession Risk Score [\d.]+/);
    const score = parseFloat(aria!.match(/Recession Risk Score ([\d.]+)/)![1]);
    expect(score).toBeGreaterThanOrEqual(0);
    expect(score).toBeLessThanOrEqual(100);
  });

  test('band displayed in gauge matches score band', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    // Pull score from /api/score and verify the gauge SVG shows the matching band text.
    const apiResp = await page.request.get('/api/score');
    const { score, band } = await apiResp.json();
    expect(['LOW', 'ELEVATED', 'HIGH', 'CRITICAL']).toContain(band);
    // Confirm the band name renders inside the gauge SVG text.
    const gauge = page.locator('svg[aria-label*="Recession Risk Score"]').first();
    await expect(gauge).toBeVisible();
    await expect(gauge.locator('text').filter({ hasText: band })).toHaveCount(1);
    expect(score).toBeGreaterThanOrEqual(0);
    expect(score).toBeLessThanOrEqual(100);
  });

  test('time-machine bar present with date input + presets', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Time Machine')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('button', { name: /Sep 2008/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /Apr 2020/ })).toBeVisible();
    const dateInput = page.locator('input[type="date"]').first();
    await expect(dateInput).toBeVisible();
    // max attribute should be today (no future dates)
    const maxAttr = await dateInput.getAttribute('max');
    expect(maxAttr).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(new Date(maxAttr!).getTime()).toBeLessThanOrEqual(Date.now() + 24 * 3600 * 1000);
  });

  test('all 8 categories rendered as clickable cards', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('KPI Categories')).toBeVisible({ timeout: 30_000 });
    const cards = page.locator('.category-card');
    await expect(cards).toHaveCount(8);
  });

  test('refresh button present in live mode', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('button', { name: /Refresh Now/ })).toBeVisible();
  });

  test('refresh button hidden in time-machine mode', async ({ page }) => {
    await page.goto('/?as_of=2020-04-15');
    await expect(page.getByText('HISTORICAL VIEW')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('button', { name: /Refresh Now/ })).toHaveCount(0);
  });

  test('historical banner appears with as_of param', async ({ page }) => {
    await page.goto('/?as_of=2008-09-15');
    await expect(page.getByText(/HISTORICAL VIEW.*2008-09-15/)).toBeVisible({ timeout: 30_000 });
  });
});
