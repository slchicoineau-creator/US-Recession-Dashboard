/**
 * Model Performance page — backtest & calibration of every recession signal
 * against NBER history: lead times, false alarms, AUROC, Brier score, a
 * common-window comparison, a calibration (reliability) chart, the signal
 * chart, and model coefficients (per-horizon Logit + yield-curve probit).
 *
 * Validation types are shown on every row so in-sample numbers are never
 * mistaken for out-of-sample ones.
 */
import React, { useEffect, useState, useCallback, useRef } from "react";
import {
  ComposedChart, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from "recharts";
import { api } from "../api.js";

const SIGNAL_COLORS = {
  composite: "#1a73e8",
  leading_index: "#e07b39",
  ml_12m: "#9b59b6",
  ml_6m: "#c39bd3",
  ml_12m_wf: "#6c3483",
  ml_6m_wf: "#a569bd",
  yield_curve: "#138d75",
  chauvet_piger: "#7f8c8d",
};

// Short legend labels for the chart (table uses the full backend names)
const SHORT_NAMES = {
  composite: "Risk Score",
  leading_index: "Leading Index",
  ml_12m: "ML 12mo (in-sample)",
  ml_6m: "ML 6mo (in-sample)",
  ml_12m_wf: "ML 12mo (walk-fwd)",
  ml_6m_wf: "ML 6mo (walk-fwd)",
  yield_curve: "Yield-curve model",
  chauvet_piger: "Chauvet–Piger (retro)",
};

const DEFAULT_HIDDEN = new Set(["leading_index", "ml_6m", "ml_6m_wf"]);

const VALIDATION_STYLE = {
  "rules":         { bg: "#e9ecef", fg: "#495057", label: "rules-based" },
  "in-sample":     { bg: "#fdecea", fg: "#a93226", label: "in-sample" },
  "walk-forward":  { bg: "#d4efdf", fg: "#1e8449", label: "walk-forward" },
  "retrospective": { bg: "#eaecee", fg: "#566573", label: "retrospective" },
};

function fmtDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function fmtNum(v, digits = 3) {
  return v == null ? "—" : v.toFixed(digits);
}

/** Merge per-signal series into one array keyed by date for Recharts. */
function mergeSeries(signals) {
  const byDate = new Map();
  for (const [sigId, sig] of Object.entries(signals)) {
    if (!sig.available) continue;
    for (const { date, value } of sig.series) {
      if (!byDate.has(date)) byDate.set(date, { date });
      byDate.get(date)[sigId] = value;
    }
  }
  return [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
}

function ValidationBadge({ validation }) {
  const st = VALIDATION_STYLE[validation] || VALIDATION_STYLE.rules;
  return (
    <span className="validation-badge" style={{
      background: st.bg, color: st.fg, borderRadius: 10, padding: "1px 8px",
      fontSize: ".7rem", fontWeight: 600, whiteSpace: "nowrap",
    }}>
      {st.label}
    </span>
  );
}

function SignalTooltip({ active, payload, label, kinds = {} }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "#fff", border: "1px solid #dee2e6",
      borderRadius: 6, padding: "8px 12px", fontSize: ".82rem",
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{fmtDate(label)}</div>
      {payload.map(p => (
        <div key={p.dataKey} style={{ color: p.stroke }}>
          {p.name}: <strong>{typeof p.value === "number"
            ? `${p.value.toFixed(1)}${kinds[p.dataKey] === "probability" ? "%" : " / 100"}` : "—"}</strong>
        </div>
      ))}
    </div>
  );
}

function LeadCell({ r }) {
  if (r.status === "led") return (
    <strong style={{ color: "#1a9850" }}
            title={r.lead_censored ? "Already alarming in the first month of data — the true lead may be longer" : undefined}>
      {r.lead_censored ? "≥" : ""}{r.lead_months} mo
    </strong>
  );
  if (r.status === "missed") return <span style={{ color: "#c0392b" }}>missed</span>;
  if (r.status === "no_data") return <span style={{ color: "#868e96" }} title="The model had no out-of-sample prediction yet: too few recession labels were public">no model yet</span>;
  return <span style={{ color: "#868e96" }} title="Coincident measure: lead time does not apply">n/a</span>;
}

function SignalRow({ sigId, sig, onsets, dim }) {
  if (!sig.available) return (
    <tr><td style={{ textAlign: "left" }}>{sig.name}</td>
      <td colSpan={onsets.length + 6} style={{ color: "#6c757d" }}>unavailable</td></tr>
  );
  const isProb = sig.kind === "probability";
  return (
    <tr style={dim ? { color: "#6c757d" } : undefined}>
      <td style={{ textAlign: "left" }}>
        <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: SIGNAL_COLORS[sigId], marginRight: 6 }} />
        {sig.name}
        {sig.fit_stats?.fits > 0 && sig.fit_stats.failed_fits > 0 && (
          <div className="fit-stats" style={{ fontSize: ".7rem", color: "#a93226", marginLeft: 16 }}>
            {sig.fit_stats.failed_fits} of {sig.fit_stats.fits} monthly refits failed (too few recessions to fit)
          </div>
        )}
      </td>
      <td style={{ textAlign: "center" }}><ValidationBadge validation={sig.validation} /></td>
      {sig.recessions.map(r => (
        <td key={r.onset} style={{ textAlign: "center" }}><LeadCell r={r} /></td>
      ))}
      <td style={{ textAlign: "center" }}>
        <span style={{ color: dim ? undefined : sig.false_alarm_episodes > 0 ? "#d35400" : "#1a9850", fontWeight: 600 }}>
          {sig.false_alarm_episodes}
        </span>
      </td>
      <td style={{ textAlign: "center", fontWeight: 600 }}
          title={sig.auroc_12m == null ? "No recession within this signal's coverage — AUROC undefined" : undefined}>
        {fmtNum(sig.auroc_12m)}
      </td>
      <td style={{ textAlign: "center" }}>{sig.months_evaluated}</td>
      <td style={{ textAlign: "center" }}
          title={isProb ? `Scored on ${sig.months_scored} months against its own ${sig.horizon ? `${sig.horizon}-month` : "coincident"} label` : undefined}>
        {isProb ? fmtNum(sig.brier) : "—"}
      </td>
      <td style={{ textAlign: "center", fontWeight: 600,
                   color: dim || !isProb || sig.brier_skill == null ? undefined : sig.brier_skill >= 0 ? "#1a9850" : "#c0392b" }}
          title={isProb && sig.brier_skill == null ? "Undefined: no recession inside this signal's coverage" : undefined}>
        {isProb ? fmtNum(sig.brier_skill) : "—"}
      </td>
    </tr>
  );
}

function MetricsTable({ backtest }) {
  const onsets = backtest.recession_onsets;
  const entries = Object.entries(backtest.signals);
  const forecasts = entries.filter(([, s]) => s.validation !== "retrospective");
  const reference = entries.filter(([, s]) => s.validation === "retrospective");
  const nCols = onsets.length + 7;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="data-table metrics-table" style={{ width: "100%", fontSize: ".85rem" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Signal</th>
            <th>Validation</th>
            {onsets.map(o => <th key={o}>Lead before {fmtDate(o)}</th>)}
            <th>False alarms</th>
            <th>AUROC (12-mo warning)</th>
            <th title="Months used for AUROC (not already in recession)">Months (AUROC)</th>
            <th>Brier</th>
            <th>Skill vs base rate</th>
          </tr>
        </thead>
        <tbody>
          {forecasts.map(([id, sig]) => <SignalRow key={id} sigId={id} sig={sig} onsets={onsets} />)}
          {reference.length > 0 && (
            <tr><td colSpan={nCols} style={{ textAlign: "left", fontSize: ".72rem", fontWeight: 700, color: "#6c757d",
                                              textTransform: "uppercase", letterSpacing: ".05em", background: "#f8f9fa" }}>
              Reference only — retrospective, not ranked
            </td></tr>
          )}
          {reference.map(([id, sig]) => <SignalRow key={id} sigId={id} sig={sig} onsets={onsets} dim />)}
        </tbody>
      </table>
    </div>
  );
}

function CommonWindowTable({ backtest }) {
  const cw = backtest.common_window;
  if (!cw || !cw.months) return null;
  const rows = cw.signals
    .map(id => ({ id, sig: backtest.signals[id], m: cw.metrics[id] }))
    .sort((a, b) => (b.m.auroc_12m ?? -1) - (a.m.auroc_12m ?? -1));
  return (
    <div>
      <p style={{ fontSize: ".85rem", color: "#495057", margin: "0 0 10px" }}>
        Every signal re-scored on the <strong>same {cw.months} months</strong> ({fmtDate(cw.from)} – {fmtDate(cw.to)},
        {" "}{cw.positive_months} of them within 12 months before a recession), so the rows are directly comparable.
        Sorted best first.
      </p>
      <div style={{ overflowX: "auto" }}>
        <table className="data-table common-window-table" style={{ width: "100%", fontSize: ".85rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Signal</th>
              <th>Validation</th>
              <th>AUROC (12-mo warning)</th>
              <th>Brier (12-mo probabilities)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ id, sig, m }) => (
              <tr key={id}>
                <td style={{ textAlign: "left" }}>
                  <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 2, background: SIGNAL_COLORS[id], marginRight: 6 }} />
                  {sig.name}
                </td>
                <td style={{ textAlign: "center" }}><ValidationBadge validation={sig.validation} /></td>
                <td style={{ textAlign: "center", fontWeight: 600 }}>{fmtNum(m.auroc_12m)}</td>
                <td style={{ textAlign: "center" }}>{fmtNum(m.brier)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cw.excluded_no_recession_in_coverage?.length > 0 && (
        <div style={{ fontSize: ".75rem", color: "#6c757d", marginTop: 8 }}>
          Not in this comparison (no recession inside their coverage, so AUROC is undefined):{" "}
          {cw.excluded_no_recession_in_coverage.map(id => backtest.signals[id]?.name || id).join(", ")}.
        </div>
      )}
    </div>
  );
}

function CalibrationTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.n == null) return null;
  return (
    <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: 6, padding: "8px 12px", fontSize: ".82rem" }}>
      <div style={{ fontWeight: 600 }}>Forecast {p.bin_low}–{p.bin_high}%</div>
      <div>Mean forecast: <strong>{p.mean_predicted}%</strong></div>
      <div>Actually happened: <strong>{p.observed_rate}%</strong></div>
      <div style={{ color: "#6c757d" }}>{p.n} months</div>
    </div>
  );
}

function CalibrationChart({ backtest }) {
  const probIds = Object.entries(backtest.signals)
    .filter(([, s]) => s.available && s.kind === "probability" && s.calibration?.length)
    .map(([id]) => id);
  const [sel, setSel] = useState(probIds.includes("yield_curve") ? "yield_curve" : probIds[0]);
  if (!probIds.length) return null;
  const sig = backtest.signals[sel];
  const points = sig.calibration.map(b => ({ ...b, x: b.mean_predicted, y: b.observed_rate }));
  const diagonal = [{ x: 0, diag: 0 }, { x: 100, diag: 100 }];
  const outcomeText = sig.horizon === 0
    ? "the economy actually was in recession that month"
    : `the economy was in recession at some point in the following ${sig.horizon} months`;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
        <label htmlFor="calib-signal" style={{ fontSize: ".85rem", color: "#495057" }}>Signal:</label>
        <select id="calib-signal" value={sel} onChange={e => setSel(e.target.value)}
                style={{ borderRadius: 4, border: "1px solid #ced4da", padding: "3px 8px", fontSize: ".85rem" }}>
          {probIds.map(id => <option key={id} value={id}>{backtest.signals[id].name}</option>)}
        </select>
        <ValidationBadge validation={sig.validation} />
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart margin={{ top: 8, right: 16, left: 0, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" dataKey="x" domain={[0, 100]} ticks={[0, 20, 40, 60, 80, 100]}
                 tick={{ fontSize: 10, fill: "#6c757d" }} tickFormatter={v => `${v}%`}
                 label={{ value: "Forecast probability", position: "insideBottom", offset: -8, fontSize: 11, fill: "#6c757d" }} />
          <YAxis type="number" domain={[0, 100]} ticks={[0, 20, 40, 60, 80, 100]}
                 tick={{ fontSize: 10, fill: "#6c757d" }} tickFormatter={v => `${v}%`} width={40} />
          <Tooltip content={<CalibrationTooltip />} />
          <Line data={diagonal} dataKey="diag" stroke="#adb5bd" strokeDasharray="5 4" dot={false}
                isAnimationActive={false} name="Perfect calibration" legendType="none" />
          <Scatter data={points} dataKey="y" fill={SIGNAL_COLORS[sel]} name="Observed" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <div style={{ fontSize: ".75rem", color: "#6c757d" }}>
        Each dot groups the months where the signal forecast a similar probability (10-point bins) and shows how often
        {" "}{outcomeText}. Dots on the dashed diagonal are well calibrated; dots below it mean the signal was
        overconfident, dots above it under-confident. Scored on {sig.months_scored} months against its own horizon
        (months already inside a recession are excluded for forward-looking signals); hover a dot for its month
        count — bins with few months are noisy.
      </div>
    </div>
  );
}

function CoefficientsTable({ mlStatus }) {
  if (!mlStatus?.available) return null;
  const horizons = Object.entries(mlStatus.horizons || {});
  if (!horizons.length) return null;
  const coefNames = horizons[0][1].coef_names || [];
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="data-table" style={{ width: "100%", fontSize: ".82rem" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Horizon</th>
            <th>n</th>
            <th>Positives</th>
            <th>Pseudo R2</th>
            {coefNames.map(c => <th key={c}>{c.replace("_", " ")}</th>)}
          </tr>
        </thead>
        <tbody>
          {horizons.map(([h, m]) => (
            <tr key={h}>
              <td style={{ textAlign: "left", fontWeight: 600 }}>{h === "now" ? "Nowcast" : `${h} ahead`}</td>
              <td style={{ textAlign: "center" }}>{m.n_observations}</td>
              <td style={{ textAlign: "center" }}>{m.n_positive_months}</td>
              <td style={{ textAlign: "center" }}>{typeof m.pseudo_r2 === "number" ? m.pseudo_r2.toFixed(3) : "—"}</td>
              {coefNames.map(c => (
                <td key={c} style={{ textAlign: "center", color: (m.coefficients?.[c] ?? 0) >= 0 ? "#495057" : "#c0392b" }}>
                  {m.coefficients?.[c]?.toFixed(2) ?? "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function YieldCurveModelCard({ benchmarks }) {
  const yc = benchmarks?.yield_curve;
  if (!yc) return null;
  return (
    <div className="card" style={{ marginBottom: 24, padding: 20 }}>
      <div className="section-title" style={{ marginBottom: 12 }}>Yield-Curve Benchmark Model (current fit)</div>
      <div style={{ overflowX: "auto" }}>
      <table className="data-table" style={{ width: "100%", fontSize: ".82rem" }}>
        <thead>
          <tr><th style={{ textAlign: "left" }}>Model</th><th>Training months</th><th>Constant</th><th>Spread coefficient</th><th>Latest spread</th><th>P(recession within 12 mo)</th></tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ textAlign: "left", fontWeight: 600 }}>Probit on 10y − 3m spread</td>
            <td style={{ textAlign: "center" }}>{yc.n_observations} ({fmtDate(yc.train_start)} – {fmtDate(yc.train_end)})</td>
            <td style={{ textAlign: "center" }}>{yc.coefficients.const?.toFixed(3)}</td>
            <td style={{ textAlign: "center", color: "#c0392b" }}>{yc.coefficients.spread?.toFixed(3)}</td>
            <td style={{ textAlign: "center" }}>{yc.spread.toFixed(2)} pp ({fmtDate(yc.spread_month)})</td>
            <td style={{ textAlign: "center", fontWeight: 700 }}>{yc.prob_12m.toFixed(1)}%</td>
          </tr>
        </tbody>
      </table>
      </div>
      <div style={{ fontSize: ".75rem", color: "#6c757d", marginTop: 8 }}>
        The NY Fed's method (Estrella &amp; Mishkin): a flatter or inverted curve (lower spread) raises the probability,
        hence the negative coefficient. The 3-month bill is converted to a bond-equivalent yield. Unlike the NY Fed's
        published model, which targets a recession in exactly 12 months' time, this one targets any recession month
        within the next 12, the same target as the dashboard's 12-month ML model. Training stops at
        {" "}{fmtDate(yc.train_end)} because later outcomes were not yet known.
      </div>
    </div>
  );
}

export default function ModelPerformancePage() {
  const [backtest, setBacktest] = useState(null);
  const [mlStatus, setMlStatus] = useState(null);
  const [benchmarks, setBenchmarks] = useState(null);
  const [nber, setNber] = useState([]);
  const [hidden, setHidden] = useState(DEFAULT_HIDDEN);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadSeqRef = useRef(0);

  const load = useCallback(async () => {
    const token = ++loadSeqRef.current;
    setError(null);
    try {
      const [bt, status, nberData, bench] = await Promise.all([
        api.backtest(),
        api.mlStatus().catch(() => null),
        api.nberShading().catch(() => []),
        api.benchmarks().catch(() => null),
      ]);
      if (token !== loadSeqRef.current) return;
      setBacktest(bt);
      setMlStatus(status);
      setNber(nberData);
      setBenchmarks(bench);
    } catch (err) {
      if (token === loadSeqRef.current) setError(err.message || "Failed to load backtest");
    } finally {
      if (token === loadSeqRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleSeries = (o) => {
    const key = o?.dataKey;
    if (!key) return;
    setHidden(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  if (loading) return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      Running backtest… (first load computes ~20 years of monthly history and may take a minute)
    </div>
  );
  if (error) return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      <div style={{ color: "#c0392b", marginBottom: 12 }}>Failed to load: {error}</div>
      <button className="btn btn-primary" onClick={() => { setLoading(true); load(); }}>Retry</button>
    </div>
  );

  const chartData = mergeSeries(backtest.signals);
  const chartIds = Object.keys(SIGNAL_COLORS).filter(id => backtest.signals[id]?.available);

  return (
    <div>
      <div className="page-header">
        <h1>Model Performance</h1>
        <p>
          How each signal would have scored NBER recessions since {fmtDate(backtest.from_date)}.
          Grey bands are NBER recessions; a useful early-warning signal rises before the band starts.
        </p>
      </div>

      {/* Honesty caveats */}
      <div style={{
        background: "#fff3cd", border: "1px solid #ffc107", borderRadius: 8,
        padding: "10px 16px", marginBottom: 16, fontSize: ".85rem", color: "#664d03",
      }}>
        <div>⚠ {backtest.caveat}</div>
        {backtest.walk_forward_note && (
          <div style={{ marginTop: 6 }}><strong>In-sample vs walk-forward:</strong> {backtest.walk_forward_note}</div>
        )}
      </div>

      {/* Metrics table */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div className="section-title" style={{ marginBottom: 12 }}>Warning Record</div>
        <MetricsTable backtest={backtest} />
        <div style={{ fontSize: ".75rem", color: "#6c757d", marginTop: 8 }}>
          <p style={{ margin: "0 0 4px" }}>
            <strong>Validation:</strong> <em>in-sample</em> = the live model scored on the months it was trained on
            (optimistic); <em>walk-forward</em> = refit every month using only outcomes known at the time;
            <em> rules-based</em> = fixed thresholds, no fitting; <em>retrospective</em> = revised with hindsight.
          </p>
          <p style={{ margin: "0 0 4px" }}>
            Lead = months between the first alarm and the recession's first NBER month, counting only alarms within
            the signal's horizon + 6 months (18 for 12-month signals and scores, 12 for 6-month models).
            "≥" = the alarm was already on when the data starts. "No model yet" = too few recessions had been dated
            for an out-of-sample fit. False alarms = alarm episodes not followed by a recession within that same window.
          </p>
          <p style={{ margin: "0 0 4px" }}>
            AUROC measures how well the signal separates months that were 12 or fewer months before a recession
            from calm months (0.5 = coin flip, 1.0 = perfect; below 0.5 means the signal ran higher in calm periods
            than before recessions — worse than a coin flip). It is computed over each signal's own coverage
            ("Months"), so compare rows in the apples-to-apples table below. A big drop from an in-sample row to its
            walk-forward row means the in-sample numbers are overfit: trust the walk-forward row.
          </p>
          <p style={{ margin: 0 }}>
            Brier = mean squared error of the probability (0 = perfect; 0.25 = no better than always saying 50%),
            scored against the signal's own horizon on months not already inside a recession. Skill vs base rate
            compares it with always forecasting that sample's recession frequency: above 0 beats it, below 0 does worse.
            Because this sample drops the recession months themselves, even an in-sample model can score below 0
            here. {backtest.retrospective_note}
          </p>
        </div>
      </div>

      {/* Common window */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div className="section-title" style={{ marginBottom: 12 }}>Apples-to-Apples Comparison</div>
        <CommonWindowTable backtest={backtest} />
      </div>

      {/* Signals chart */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div className="section-title" style={{ marginBottom: 8 }}>Signals vs NBER Recessions</div>
        <div style={{ fontSize: ".75rem", color: "#6c757d", marginBottom: 6 }}>
          Click a legend entry to show or hide that line.
        </div>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            {nber.map((period, i) => (
              <ReferenceArea key={i} x1={period.start} x2={period.end}
                fill="#e0e0e0" fillOpacity={0.55} ifOverflow="extendDomain" />
            ))}
            <ReferenceLine y={50} stroke="#d4ac0d" strokeDasharray="6 3" strokeWidth={1.5}
              label={{ value: "Alarm threshold", position: "insideTopLeft", fontSize: 9, fill: "#d4ac0d" }} />
            <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 10, fill: "#6c757d" }} minTickGap={70} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 10, fill: "#6c757d" }} width={32} />
            <Tooltip content={<SignalTooltip kinds={Object.fromEntries(Object.entries(backtest.signals).map(([k, v]) => [k, v.kind]))} />} />
            <Legend wrapperStyle={{ fontSize: ".78rem", cursor: "pointer" }} onClick={toggleSeries}
              formatter={(value, entry) => (
                <span style={{ color: hidden.has(entry.dataKey) ? "#ced4da" : "#495057",
                               textDecoration: hidden.has(entry.dataKey) ? "line-through" : "none" }}>{value}</span>
              )} />
            {chartIds.map(id => (
              <Line key={id} type="monotone" dataKey={id} name={SHORT_NAMES[id]} stroke={SIGNAL_COLORS[id]}
                strokeWidth={id === "composite" || id === "yield_curve" ? 2 : 1.5}
                strokeDasharray={id === "chauvet_piger" ? "2 3" : id.endsWith("_wf") ? "6 3" : undefined}
                hide={hidden.has(id)} dot={false} isAnimationActive={false} connectNulls={false} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Calibration */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div className="section-title" style={{ marginBottom: 8 }}>Calibration: When It Said X%, Did It Happen X% of the Time?</div>
        <CalibrationChart backtest={backtest} />
      </div>

      <YieldCurveModelCard benchmarks={benchmarks} />

      {/* Model metadata */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div className="section-title" style={{ marginBottom: 12 }}>Logit Model Coefficients (per horizon)</div>
        <CoefficientsTable mlStatus={mlStatus} />
        <div style={{ fontSize: ".75rem", color: "#6c757d", marginTop: 8 }}>
          Features are the 8 category sub-scores (0-1). Negative coefficients on coincident categories in the
          forward-horizon models are expected: when coincident stress is already high, the recession has usually
          started, so it no longer predicts a <em>future</em> onset.
        </div>
      </div>
    </div>
  );
}
