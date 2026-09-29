import { test, expect } from '@playwright/test';

test.describe('Time Machine — extreme/malformed inputs', () => {
  test('as_of=1990-01-01 (before most data) does not crash', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=1990-01-01');
    expect(resp.status()).toBeLessThan(500);
    const body = await resp.json();
    expect(body).toHaveProperty('score');
    expect(typeof body.score).toBe('number');
    expect(Number.isFinite(body.score)).toBeTruthy();
  });

  test('as_of=2099-01-01 (future) does not crash', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=2099-01-01');
    expect(resp.status()).toBeLessThan(500);
    const body = await resp.json();
    expect(body).toHaveProperty('score');
  });

  test('as_of=invalid-date defaults gracefully', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=not-a-date');
    expect(resp.status()).toBeLessThan(500);
  });

  test('as_of= empty value defaults gracefully', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=');
    expect(resp.status()).toBeLessThan(500);
  });

  test('as_of=2008-02-29 (invalid leap day for 2008) — actually valid since 2008 is leap', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=2008-02-29');
    expect(resp.status()).toBeLessThan(500);
  });

  test('as_of=2007-02-29 (invalid leap day) handled', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=2007-02-29');
    expect(resp.status()).toBeLessThan(500);
  });

  test('as_of with SQL-injection-looking string handled', async ({ request }) => {
    const resp = await request.get("/api/score?as_of='; DROP TABLE kpi_data;--");
    expect(resp.status()).toBeLessThan(500);
  });

  test('homepage with extreme as_of in URL still loads', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('pageerror', (err) => consoleErrors.push(err.message));
    await page.goto('/?as_of=1990-01-01');
    await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
    expect(consoleErrors, `unhandled errors: ${consoleErrors.join('; ')}`).toHaveLength(0);
  });

  test('score history with from_date in future returns empty or sane', async ({ request }) => {
    const resp = await request.get('/api/score/history?from_date=2099-01-01');
    expect(resp.status()).toBeLessThan(500);
    const body = await resp.json();
    expect(Array.isArray(body)).toBeTruthy();
  });
});
