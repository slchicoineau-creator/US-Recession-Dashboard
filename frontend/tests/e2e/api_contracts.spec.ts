import { test, expect } from '@playwright/test';

test.describe('API contract tests (no browser)', () => {
  test('GET /api/score returns valid score + band', async ({ request }) => {
    const resp = await request.get('/api/score');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty('score');
    expect(body).toHaveProperty('band');
    expect(typeof body.score).toBe('number');
    expect(body.score).toBeGreaterThanOrEqual(0);
    expect(body.score).toBeLessThanOrEqual(100);
    expect(['LOW', 'ELEVATED', 'HIGH', 'CRITICAL']).toContain(body.band);
  });

  test('GET /api/score?as_of=2008-09-15 returns simulated=true', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=2008-09-15');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.simulated).toBe(true);
    expect(body.band).toMatch(/HIGH|CRITICAL/);
  });

  test('GET /api/score?as_of=invalid returns valid (defaults to live)', async ({ request }) => {
    const resp = await request.get('/api/score?as_of=not-a-date');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty('score');
  });

  test('GET /api/kpis returns array of KPIs with required fields', async ({ request }) => {
    const resp = await request.get('/api/kpis');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body)).toBeTruthy();
    expect(body.length).toBeGreaterThan(0);
    const k = body[0];
    for (const f of ['id', 'name', 'category', 'source', 'frequency']) {
      expect(k).toHaveProperty(f);
    }
  });

  test('GET /api/kpis status field is OK | WARNING | DANGER | NO_DATA', async ({ request }) => {
    const resp = await request.get('/api/kpis');
    const body = await resp.json();
    const valid = new Set(['OK', 'WARNING', 'DANGER', 'NO_DATA']);
    for (const k of body) {
      expect(valid.has(k.status)).toBeTruthy();
    }
  });

  test('GET /api/categories returns 8 scored categories + the AI bubble monitor', async ({ request }) => {
    const resp = await request.get('/api/categories');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.filter((c: any) => c.in_composite === true).length).toBe(8);
    const monitor = body.filter((c: any) => c.in_composite === false);
    expect(monitor.map((c: any) => c.id)).toEqual(['ai_bubble']);
    for (const c of body) {
      expect(c).toHaveProperty('id');
      expect(c).toHaveProperty('label');
      expect(c).toHaveProperty('kpi_count');
      expect(Array.isArray(c.sparkline)).toBeTruthy();
    }
  });

  test('GET /api/score/history returns monthly scores', async ({ request }) => {
    const resp = await request.get('/api/score/history?from_date=2024-01-01');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body)).toBeTruthy();
    if (body.length > 0) {
      const first = body[0];
      expect(first).toHaveProperty('date');
      expect(first).toHaveProperty('score');
      expect(first).toHaveProperty('band');
    }
  });

  for (const res of ['5y', '2y', '1y']) {
    test(`GET /api/score/history?resolution=${res} ends at the as_of date`, async ({ request }) => {
      const resp = await request.get(`/api/score/history?resolution=${res}&as_of=2008-09-15`);
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body.length).toBeGreaterThan(200);
      expect(body[body.length - 1].date).toBe('2008-09-15');
      const dates = body.map((p: any) => p.date);
      expect([...dates].sort()).toEqual(dates);
      for (const p of body.slice(0, 5)) {
        expect(typeof p.score).toBe('number');
        expect(p).toHaveProperty('band');
      }
    });
  }

  test('GET /api/score/history rejects an unknown resolution', async ({ request }) => {
    const resp = await request.get('/api/score/history?resolution=10y');
    expect(resp.status()).toBe(400);
  });

  test('GET /api/score/drivers explains the Time Machine day', async ({ request }) => {
    const resp = await request.get('/api/score/drivers?as_of=2008-09-15');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.basis).toBe('reconstructed');
    expect(body.to_date).toBe('2008-09-15');
    expect(body.from_date).toBe('2008-09-12');
    expect(Array.isArray(body.kpis)).toBeTruthy();
    expect(Array.isArray(body.categories)).toBeTruthy();
    for (const k of body.kpis) {
      expect(k).toHaveProperty('impact');
      expect(k).toHaveProperty('status_from');
      expect(k).toHaveProperty('status_to');
    }
  });

  test('GET /api/score/drivers (live) returns a known basis', async ({ request }) => {
    const resp = await request.get('/api/score/drivers');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(['snapshot', 'category_only', 'none']).toContain(body.basis);
  });

  test('GET /api/nber-shading returns recession periods', async ({ request }) => {
    const resp = await request.get('/api/nber-shading');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body)).toBeTruthy();
    if (body.length > 0) {
      expect(body[0]).toHaveProperty('start');
      expect(body[0]).toHaveProperty('end');
    }
  });

  test('GET /api/kpis/{id}/history returns time series', async ({ request }) => {
    const resp = await request.get('/api/kpis/t10y2y/history');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(Array.isArray(body)).toBeTruthy();
    if (body.length > 0) {
      expect(body[0]).toHaveProperty('date');
      expect(body[0]).toHaveProperty('value');
    }
  });

  test('GET /api/kpis/unknown_id/history returns 404 or empty array, not 500', async ({ request }) => {
    const resp = await request.get('/api/kpis/zzz_unknown/history');
    expect(resp.status(), 'must not 500').toBeLessThan(500);
  });

  test('GET /api/score/forecast returns forecast_score + forecast_band', async ({ request }) => {
    const resp = await request.get('/api/score/forecast');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty('forecast_score');
    expect(body).toHaveProperty('forecast_band');
    expect(body).toHaveProperty('forecast_date');
  });

  test('GET /api/config returns alert config', async ({ request }) => {
    const resp = await request.get('/api/config');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    for (const f of ['warning_threshold', 'critical_threshold', 'alerts_enabled']) {
      expect(body).toHaveProperty(f);
    }
  });

  test('POST /api/refresh returns 200 or 409', async ({ request }) => {
    const resp = await request.post('/api/refresh');
    expect([200, 202, 409]).toContain(resp.status());
  });

  test('GET /api/refresh/status returns running flag', async ({ request }) => {
    const resp = await request.get('/api/refresh/status');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty('running');
    expect(typeof body.running).toBe('boolean');
  });

  test('every kpi_id from /api/kpis has a working /history endpoint', async ({ request }) => {
    const kpisResp = await request.get('/api/kpis');
    const kpis = await kpisResp.json();
    // Spot-check 5 KPIs to keep this test fast
    const sample = kpis.slice(0, 5);
    for (const kpi of sample) {
      const hist = await request.get(`/api/kpis/${kpi.id}/history`);
      expect(hist.status(), `history endpoint for ${kpi.id}`).toBeLessThan(500);
    }
  });

  test('GET /api/benchmarks returns yield-curve + Chauvet-Piger', async ({ request }) => {
    const resp = await request.get('/api/benchmarks');
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.simulated).toBe(false);
    expect(body.yield_curve.coefficients.spread).toBeLessThan(0);
    expect(body.yield_curve.prob_12m).toBeGreaterThanOrEqual(0);
    expect(body.yield_curve.prob_12m).toBeLessThanOrEqual(100);
    expect(body.chauvet_piger.retrospective).toBe(true);
  });

  test('GET /api/benchmarks?as_of=2008-09-15 trains only on public labels', async ({ request }) => {
    const body = await (await request.get('/api/benchmarks?as_of=2008-09-15')).json();
    expect(body.simulated).toBe(true);
    expect(body.yield_curve.train_end <= '2006-09-01').toBeTruthy();
    expect(body.yield_curve.spread_month).toBe('2008-08-01');
    expect(body.chauvet_piger.month <= '2008-07-01').toBeTruthy();
  });

  test('GET /api/backtest has walk-forward, benchmark and common-window blocks', async ({ request }) => {
    test.setTimeout(180_000);
    const resp = await request.get('/api/backtest', { timeout: 170_000 });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    for (const id of ['composite', 'ml_12m', 'ml_12m_wf', 'ml_6m_wf', 'yield_curve', 'chauvet_piger']) {
      expect(body.signals, id).toHaveProperty(id);
    }
    expect(body.signals.ml_12m.validation).toBe('in-sample');
    expect(body.signals.yield_curve.validation).toBe('walk-forward');
    expect(body.signals.yield_curve.brier).not.toBeNull();
    expect(body.common_window.signals).not.toContain('chauvet_piger');
    expect(body.common_window.positive_months).toBeGreaterThan(0);
    expect(body.walk_forward_note).toMatch(/hindsight/);
  });
});
