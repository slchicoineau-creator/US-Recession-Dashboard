import { test, expect } from '@playwright/test';

test.describe('Settings page', () => {
  test('threshold inputs populate from /api/config', async ({ page }) => {
    await page.goto('/settings');
    const warnInput = page.locator('input[type="number"]').first();
    const critInput = page.locator('input[type="number"]').nth(1);
    await expect(warnInput).toBeVisible({ timeout: 15_000 });
    await expect(critInput).toBeVisible();
    const warn = parseFloat(await warnInput.inputValue());
    const crit = parseFloat(await critInput.inputValue());
    expect(warn).toBeGreaterThanOrEqual(0);
    expect(warn).toBeLessThanOrEqual(100);
    expect(crit).toBeGreaterThanOrEqual(0);
    expect(crit).toBeLessThanOrEqual(100);
  });

  test('threshold inputs honor min=0 and max=100', async ({ page }) => {
    await page.goto('/settings');
    const warnInput = page.locator('input[type="number"]').first();
    await expect(warnInput).toBeVisible({ timeout: 15_000 });
    expect(await warnInput.getAttribute('min')).toBe('0');
    expect(await warnInput.getAttribute('max')).toBe('100');
  });

  test('alerts-enabled checkbox present', async ({ page }) => {
    await page.goto('/settings');
    const checkbox = page.locator('input[type="checkbox"]').first();
    await expect(checkbox).toBeVisible({ timeout: 15_000 });
  });

  test('save button posts settings and shows confirmation', async ({ page }) => {
    await page.goto('/settings');
    const warnInput = page.locator('input[type="number"]').first();
    await expect(warnInput).toBeVisible({ timeout: 15_000 });
    const original = await warnInput.inputValue();
    // Bump value by 1, save, then put it back.
    const bumped = String(parseFloat(original) + 1);
    await warnInput.fill(bumped);
    await page.getByRole('button', { name: /Save/ }).click();
    await expect(page.getByText(/Saved|✓/).first()).toBeVisible({ timeout: 10_000 });
    // Restore
    await warnInput.fill(original);
    await page.getByRole('button', { name: /Save/ }).click();
    await expect(page.getByText(/Saved|✓/).first()).toBeVisible({ timeout: 10_000 });
  });

  test('CSV uploaders match exactly the manual_csv KPIs in config', async ({ page, request }) => {
    // The list must be config-driven: a hard-coded list once showed KPIs the
    // upload endpoint rejects (already automated) and hid a real manual one.
    const kpis = await (await request.get('/api/kpis')).json();
    const manualIds = kpis.filter((k: any) => k.source === 'manual_csv').map((k: any) => k.id).sort();
    await page.goto('/settings');
    const uploaders = page.locator('[data-testid^="csv-upload-"]');
    if (manualIds.length === 0) {
      await expect(page.getByTestId('manual-csv-empty')).toBeVisible();
      await expect(uploaders).toHaveCount(0);
    } else {
      await expect(uploaders).toHaveCount(manualIds.length);
      const shown = (await uploaders.evaluateAll(els =>
        els.map(e => (e.getAttribute('data-testid') || '').replace('csv-upload-', '')))).sort();
      expect(shown).toEqual(manualIds);
      await expect(page.locator('input[type="file"]')).toHaveCount(manualIds.length);
    }
  });

  test('CSV upload rejects bad payload with 4xx', async ({ request }) => {
    // Server-side guarded path — should not 500
    const resp = await request.post('/api/upload-csv/used_vehicle_price', {
      multipart: {
        file: {
          name: 'bad.csv',
          mimeType: 'text/csv',
          buffer: Buffer.from('not,a,valid,csv\nrows\nwithout,date,column'),
        },
      },
    });
    expect(resp.status()).toBeGreaterThanOrEqual(400);
    expect(resp.status()).toBeLessThan(500);
  });

  test('CSV upload to unknown KPI returns 4xx', async ({ request }) => {
    const resp = await request.post('/api/upload-csv/nonexistent_kpi', {
      multipart: {
        file: { name: 'a.csv', mimeType: 'text/csv', buffer: Buffer.from('date,value\n2024-01-01,1.0\n') },
      },
    });
    expect(resp.status()).toBeGreaterThanOrEqual(400);
    expect(resp.status()).toBeLessThan(500);
  });
});
