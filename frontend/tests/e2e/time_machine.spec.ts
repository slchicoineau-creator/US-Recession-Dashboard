import { test, expect } from '@playwright/test';

test.describe('Time Machine — preset buttons & param propagation', () => {
  test('Sep 2008 preset sets as_of=2008-09-15', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: /Sep 2008/ }).click();
    await expect(page).toHaveURL(/as_of=2008-09-15/);
    await expect(page.getByText(/HISTORICAL VIEW.*2008-09-15/)).toBeVisible();
  });

  test('Apr 2020 preset sets as_of=2020-04-15', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: /Apr 2020/ }).click();
    await expect(page).toHaveURL(/as_of=2020-04-15/);
    await expect(page.getByText(/HISTORICAL VIEW.*2020-04-15/)).toBeVisible();
  });

  test('Live Mode button clears as_of', async ({ page }) => {
    await page.goto('/?as_of=2020-04-15');
    await expect(page.getByText(/HISTORICAL VIEW/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: /Live Mode/ }).click();
    await expect(page).not.toHaveURL(/as_of=/);
    await expect(page.getByText(/HISTORICAL VIEW/)).toHaveCount(0);
  });

  test('as_of propagates from home → category page', async ({ page }) => {
    await page.goto('/?as_of=2008-09-15');
    await expect(page.getByText('KPI Categories')).toBeVisible({ timeout: 30_000 });
    await page.locator('.category-card').first().click();
    await expect(page).toHaveURL(/\/category\/[^/]+\?as_of=2008-09-15/);
  });

  test('as_of propagates from category → kpi detail and back', async ({ page }) => {
    await page.goto('/category/yield_curve?as_of=2020-04-15');
    await expect(page.locator('table tbody tr').first()).toBeVisible({ timeout: 30_000 });
    await page.locator('table tbody tr').first().click();
    await expect(page).toHaveURL(/\/kpi\/[^/]+\?as_of=2020-04-15/);
    // Back link preserves param
    const backLink = page.locator('a').filter({ hasText: /←/ }).first();
    await backLink.click();
    await expect(page).toHaveURL(/\/category\/[^/]+\?as_of=2020-04-15/);
  });

  test('Lehman 2008 score should be HIGH or CRITICAL', async ({ page }) => {
    // API contract is the source of truth; UI just mirrors it.
    const resp = await page.request.get('/api/score?as_of=2008-09-15');
    const { band } = await resp.json();
    expect(['HIGH', 'CRITICAL']).toContain(band);
  });

  test('COVID 2020 score should be HIGH or CRITICAL', async ({ page }) => {
    const resp = await page.request.get('/api/score?as_of=2020-04-15');
    const { band } = await resp.json();
    expect(['HIGH', 'CRITICAL']).toContain(band);
  });

  test('Live Mode button does not appear when no as_of', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Risk Overview')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('button', { name: /Live Mode/ })).toHaveCount(0);
  });
});
