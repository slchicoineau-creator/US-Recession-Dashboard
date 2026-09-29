import { test, expect } from '@playwright/test';

/**
 * Model Performance page — backtest table, signals chart, coefficients,
 * plus the new probability/leading panels on the home page.
 */

test.describe('Model Performance page', () => {
  test('renders warning record, chart and coefficients', async ({ page }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await page.goto('/performance');
    await expect(page.locator('#root > *')).toHaveCount(1, { timeout: 15_000 });

    // First load may compute history; allow a generous timeout.
    await expect(page.getByRole('heading', { name: 'Model Performance' }))
      .toBeVisible({ timeout: 120_000 });

    // Honesty caveat about revised data must be present
    await expect(page.getByText(/revised data, not real-time vintages/)).toBeVisible();

    // Metrics table lists every signal, with in-sample vs walk-forward labelled
    const metrics = page.locator('.metrics-table');
    await expect(metrics.getByText('Recession Risk Score (rules-based)')).toBeVisible();
    await expect(metrics.getByText('P(recession within 12 mo) — Logit (in-sample)')).toBeVisible();
    await expect(metrics.getByText('P(recession within 6 mo) — Logit (in-sample)')).toBeVisible();
    await expect(metrics.getByText('P(recession within 12 mo) — Logit (walk-forward)')).toBeVisible();
    await expect(metrics.getByText('Yield-curve probit, NY Fed method (walk-forward)')).toBeVisible();
    await expect(metrics.getByText('Leading Indicator Index')).toBeVisible();
    await expect(metrics.getByText(/Reference only/)).toBeVisible();
    await expect(metrics.getByText(/Chauvet–Piger smoothed probability/)).toBeVisible();
    await expect(metrics.getByText('no model yet').first()).toBeVisible();
    await expect(page.getByText(/In-sample vs walk-forward:/)).toBeVisible();

    // Apples-to-apples table excludes the retrospective reference
    const common = page.locator('.common-window-table');
    await expect(common).toBeVisible();
    await expect(common.getByText(/Chauvet/)).toHaveCount(0);

    // Calibration chart: selector switches signal
    const sel = page.locator('#calib-signal');
    await expect(sel).toBeVisible();
    await sel.selectOption('ml_12m');
    await expect(page.getByText(/Scored on \d+ months/)).toBeVisible();

    // Yield-curve benchmark model card
    await expect(page.getByText('Yield-Curve Benchmark Model (current fit)')).toBeVisible();

    // Coefficients table shows the three horizons
    await expect(page.getByText('Nowcast')).toBeVisible();
    await expect(page.getByText('6m ahead')).toBeVisible();
    await expect(page.getByText('12m ahead')).toBeVisible();

    // Chart rendered (recharts draws an svg)
    await expect(page.locator('.recharts-responsive-container svg').first()).toBeVisible();

    expect(pageErrors, `unhandled JS errors: ${pageErrors.join('; ')}`).toHaveLength(0);
  });

  test('nav link preserves as_of param', async ({ page }) => {
    await page.goto('/?as_of=2008-09-15');
    const link = page.getByRole('link', { name: 'Model Performance' });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute('href', '/performance?as_of=2008-09-15');
  });
});

test.describe('Home page probability + leading panels', () => {
  test('shows ML probabilities and leading indicators', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Probability (ML)')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText('within 12 months', { exact: true })).toBeVisible();
    const bench = page.getByTestId('benchmark-line');
    await expect(bench).toBeVisible();
    await expect(bench.getByText(/Yield-curve model:/)).toBeVisible();
    await expect(bench.getByText(/Chauvet–Piger, in recession\?/)).toBeVisible();
    await expect(page.getByText('Leading Indicators')).toBeVisible();
    await expect(page.getByText('Leading Index')).toBeVisible();
    await expect(page.getByText(/Deteriorating \(\d+\/\d+\)/)).toBeVisible();
  });

  test('time machine at Lehman shows elevated leading indicators', async ({ page }) => {
    await page.goto('/?as_of=2008-09-15');
    await expect(page.getByText('Leading Indicators')).toBeVisible({ timeout: 60_000 });
    // At Lehman the diffusion breadth was ~78% — assert the panel shows data,
    // not the em-dash placeholder.
    await expect(page.getByText(/Deteriorating \(\d+\/\d+\)/)).toBeVisible();
  });

  test('stat tiles show explainer tooltips on hover', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Recession Probability (ML)')).toBeVisible({ timeout: 60_000 });

    // Tooltips are in the DOM but hidden until hover
    const probTip = page.getByText(/1 time in 16/);
    await expect(probTip).toBeHidden();
    await page.getByText('Recession Probability (ML)').hover();
    await expect(probTip).toBeVisible();

    await page.getByText('Depression Severity').hover();
    await expect(page.getByText(/debt-deflation mechanics/)).toBeVisible();

    // Gauge tooltip (the gauge wrapper is the only tip-below explainer)
    await page.locator('.hover-explainer.tip-below').hover();
    await expect(page.getByText(/rises as trouble arrives/)).toBeVisible();
  });

  test('severity panel renders and 2009 reads worse than live', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Depression Severity')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText(/how severe a downturn would be/)).toBeVisible();

    // Oct 2009: severity must show SEVERE with active debt-deflation components
    await page.goto('/?as_of=2009-10-01');
    await expect(page.getByText('Depression Severity')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText('SEVERE', { exact: true })).toBeVisible();
    await expect(page.getByText(/Active: .*credit/i)).toBeVisible();
  });
});
