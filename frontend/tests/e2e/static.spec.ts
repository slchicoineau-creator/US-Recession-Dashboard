import { test, expect, Page } from '@playwright/test';

/**
 * Read-only static snapshot (GitHub Pages build). Run with
 *   npx playwright test -c playwright.static.config.ts
 *
 * Every test fails on (a) any non-200 response for a /data/ JSON file — that
 * catches drift between staticKey() in staticMode.js and static_key() in
 * tools/export_static.py — and (b) any uncaught page error.
 */

const BASE = '/recession-dashboard';

function guard(page: Page) {
  const dataMisses: string[] = [];
  const pageErrors: string[] = [];
  page.on('response', (r) => {
    if (r.url().includes(`${BASE}/data/`) && r.status() !== 200) dataMisses.push(`${r.status()} ${r.url()}`);
  });
  page.on('pageerror', (e) => pageErrors.push(e.message));
  return () => {
    expect(dataMisses, `missing snapshot files: ${dataMisses.join(', ')}`).toHaveLength(0);
    expect(pageErrors, `page errors: ${pageErrors.join('; ')}`).toHaveLength(0);
  };
}

test.describe('Static snapshot', () => {
  test('home renders read-only with benchmarks and no mutation UI', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/`);
    await expect(page.getByText('Read-only snapshot')).toBeVisible();
    await expect(page.getByText(/snapshot taken/)).toBeVisible();
    // The repo link appears only when the export was given a real --repo-url
    // (placeholder URLs such as github.com/example/... are dropped).
    const meta = await (await page.request.get(`${BASE}/data/meta.json`)).json();
    const repoLink = page.getByRole('link', { name: 'source code & setup' });
    if (meta.repo_url) {
      await expect(repoLink).toHaveAttribute('href', meta.repo_url);
    } else {
      await expect(repoLink).toHaveCount(0);
    }
    await expect(page.getByRole('heading', { name: 'Recession Risk Overview' })).toBeVisible();
    await expect(page.getByTestId('benchmark-line')).toBeVisible();

    // No mutation / Time Machine / settings controls
    await expect(page.locator('input[type="date"]')).toHaveCount(0);
    await expect(page.getByText('Time Machine:')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Refresh/ })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Generate Analysis|Regenerate/ })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Settings' })).toHaveCount(0);
    check();
  });

  test('score-history zoom levels load from snapshot files', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/`);
    await expect(page.getByRole('heading', { name: 'Recession Risk Overview' })).toBeVisible();
    for (const label of ['5Y', '2Y', '1Y', 'Since 2007']) {
      await page.getByRole('button', { name: label, exact: true }).click();
      await expect(page.locator('.recharts-responsive-container svg').first()).toBeVisible();
    }
    await page.waitForLoadState('networkidle');
    check();
  });

  test('deep links are real files (HTTP 200), not the 404.html fallback', async ({ page }) => {
    const check = guard(page);
    let resp = await page.goto(`${BASE}/category/yield_curve`);
    expect(resp?.status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Yield Curve & Rates' })).toBeVisible();

    resp = await page.goto(`${BASE}/kpi/t10y2y`);
    expect(resp?.status()).toBe(200);
    await expect(page.locator('.recharts-responsive-container svg').first()).toBeVisible();

    resp = await page.goto(`${BASE}/performance`);
    expect(resp?.status()).toBe(200);
    check();
  });

  test('unknown routes render a not-found page', async ({ page }) => {
    await page.goto(`${BASE}/nope`);
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  });

  test('as_of notice appears on category and KPI pages too', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/category/housing?as_of=2008-09-15`);
    await expect(page.getByText(/Time Machine \(viewing 2008-09-15\) needs the full app/)).toBeVisible();
    await page.goto(`${BASE}/kpi/payems?as_of=2008-09-15`);
    await expect(page.getByText(/Time Machine \(viewing 2008-09-15\) needs the full app/)).toBeVisible();
    check();
  });

  test('in-app navigation stays under the base path', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/`);
    await page.getByRole('link', { name: 'Model Performance' }).click();
    await expect(page).toHaveURL(`${BASE}/performance`);
    await expect(page.locator('.metrics-table')).toBeVisible();
    await expect(page.locator('.common-window-table')).toBeVisible();
    await page.getByRole('link', { name: 'Overview' }).click();
    // React Router renders the basename without a trailing slash; GitHub Pages
    // redirects /repo -> /repo/ on reload, so both forms are correct.
    await expect(page).toHaveURL(/\/recession-dashboard\/?$/);
    await expect(page.getByRole('heading', { name: 'Recession Risk Overview' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Recession Risk Overview' })).toBeVisible();
    check();
  });

  test('as_of in the URL shows a notice instead of breaking', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/?as_of=2008-09-15`);
    await expect(page.getByText(/Time Machine \(viewing 2008-09-15\) needs the full app/)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recession Risk Overview' })).toBeVisible();
    check();
  });

  test('settings route explains it is unavailable', async ({ page }) => {
    const check = guard(page);
    await page.goto(`${BASE}/settings`);
    await expect(page.getByText(/only available when you run the dashboard yourself/)).toBeVisible();
    check();
  });

  test('config endpoint was never exported', async ({ request }) => {
    const r = await request.get(`${BASE}/data/config.json`);
    expect(r.status()).toBe(404);
  });
});
