/**
 * Home page — Recession gauge + historical score chart + category summary cards.
 * Supports Time Machine mode via ?as_of=YYYY-MM-DD URL param.
 * Includes 3-month forecast score panel with Time Machine validation.
 */
import React, { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import RecessionGauge from "../components/RecessionGauge.jsx";
import ScoreHistoryChart from "../components/ScoreHistoryChart.jsx";
import ScoreDriversPanel from "../components/ScoreDriversPanel.jsx";
import SparkLine from "../components/SparkLine.jsx";
import AlertBanner from "../components/AlertBanner.jsx";
import RefreshButton from "../components/RefreshButton.jsx";
import AiCommentaryPanel from "../components/AiCommentaryPanel.jsx";
import { api } from "../api.js";
import { IS_STATIC } from "../staticMode.js";

const BAND_COLOR = {
  yield_curve:       "#5b6aff",
  labor_market:      "#e07b39",
  consumer_health:   "#1a9850",
  housing:           "#c0392b",
  financial_stress:  "#8e44ad",
  business_activity: "#2980b9",
  energy:            "#d35400",
  automotive:        "#7f8c8d",
  ai_bubble:         "#b83280",
};

const RISK_BAND_COLOR = {
  LOW:      "#1a9850",
  ELEVATED: "#856404",
  HIGH:     "#d35400",
  CRITICAL: "#842029",
};

const RISK_BAND_BG = {
  LOW:      "#d4edda",
  ELEVATED: "#fff3cd",
  HIGH:     "#ffe5d0",
  CRITICAL: "#f8d7da",
};

/** Format "2009-01-15" → "Jan 2009" */
function fmtMonthYear(iso) {
  if (!iso) return "";
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

/** Color for a 0-100 recession probability. */
function probColor(p) {
  if (p == null) return "#495057";
  if (p >= 50) return "#842029";
  if (p >= 25) return "#d35400";
  if (p >= 10) return "#856404";
  return "#1a9850";
}

/**
 * Plain-English hover explanations for the headline metrics.
 * Paragraphs are separated with \n\n and rendered as <p> blocks.
 */
const EXPLAIN = {
  score:
    "**Recession Risk Score** — the main gauge. All 82 indicators are scored 0–1 against their " +
    "warning/danger thresholds, rolled up into 8 category scores (labor, housing, financial stress…), " +
    "then combined with fixed weights into 0–100.\n\n" +
    "It measures how much stress is present RIGHT NOW (it rises as trouble arrives, not before). " +
    "The tiles below are the forward-looking views.\n\n" +
    "Bands: 0–24 LOW · 25–49 ELEVATED · 50–74 HIGH · 75+ CRITICAL.",
  probability:
    "Statistical models (logistic regression) trained on NBER recession history since 2006. They " +
    "compare today's 8 category stress scores with the patterns that preceded past recessions and " +
    "output the odds a recession starts within 12 or 6 months, plus “now”. A reading of 6% means " +
    "months like this were followed by a recession about 1 time in 16.\n\n" +
    "Caveats: the models have only seen two recessions (2008, 2020) and use revised data. See the " +
    "Model Performance page for the out-of-sample track record.\n\n" +
    "**Independent cross-checks:** the **yield-curve model** (NY Fed method) uses only the 10-year " +
    "minus 3-month Treasury spread, fitted on every recession since 1959 that was known at the time — " +
    "compare it with the 12-month figure; it runs higher when the curve has recently been inverted. " +
    "**Chauvet–Piger** estimates whether the US is in recession that month (published ~2 months late " +
    "and revised with hindsight) — compare it with “now”.",
  leading:
    "The same 0–100 scoring as the main gauge, applied only to the 29 indicators that historically " +
    "turn BEFORE the economy: yield curve, jobless claims, building permits, temp-help jobs, credit " +
    "spreads, heavy truck sales…\n\n" +
    "“Deteriorating” is the diffusion index: the share of those 29 that got worse over the past " +
    "3 months. Noise runs ~40–60%; readings above ~70% mean trouble is broad-based.\n\n" +
    "For calibration: on the eve of Lehman (Sep 2008) these read 61.5 and 78%.",
  severity:
    "Not how LIKELY a downturn is, but how SEVERE one would be. It watches " +
    "1930s-style debt-deflation mechanics: falling prices, contracting bank credit, shrinking money " +
    "supply, depression-scale unemployment, and how long the main score has stayed CRITICAL.\n\n" +
    "Calibration: Oct 2009 scored 65 (SEVERE), COVID 2020 only 31 (deep, but no credit collapse), " +
    "normal times 0. Sitting at zero is by design — it only wakes up when a downturn has " +
    "depression mechanics.",
  aiBubble:
    "Is the AI-led stock market a bubble, and is it breaking? NOT part of the Recession Risk " +
    "Score — a separate market-risk view.\n\n" +
    "**Exposure** (how big and stretched): tech capex as % of GDP, how few stocks carry the " +
    "index (equal-weight vs S&P 500), the CAPE ratio and market cap / GDP. These are levels " +
    "and can stay high for years.\n\n" +
    "**Puncture** (is it deflating): semiconductors, the S&P 500 and private-credit lenders (BDCs) " +
    "breaking below their 200-day averages, and junk-bond spreads widening.\n\n" +
    "Calibration: Dec 2021 read exposure ~53 with puncture 0 (“inflated but intact”); " +
    "by Jun 2022 puncture was ~82 (“bursting”). A high exposure reading says the fall " +
    "would be large if it comes — it does not say when.",
  forecast:
    "Pure momentum. Fits a straight-line trend through each KPI's last 24 data " +
    "points, projects 3 months ahead, and re-scores the composite on those projected values.\n\n" +
    "It answers: “if every current trend simply continues, where is the gauge in 3 months?” " +
    "It cannot foresee turning points.\n\n" +
    "When viewing a past date, it also shows what the score actually turned out to be, so you can " +
    "judge its accuracy.",
};

/** Render an EXPLAIN string: paragraphs on \n\n, **bold** spans. */
function TooltipBody({ text }) {
  return (
    <div className="hover-tooltip">
      {text.split("\n\n").map((para, i) => (
        <p key={i}>
          {para.split(/\*\*(.+?)\*\*/g).map((chunk, j) =>
            j % 2 === 1 ? <strong key={j}>{chunk}</strong> : chunk
          )}
        </p>
      ))}
    </div>
  );
}

/**
 * Uniform stat tile used in the horizontal strip under the score chart.
 * The tile itself is the bordered box; `accent` tints the background.
 * `info` adds a hover tooltip; `tipAlign="right"` anchors it to the right
 * edge (for tiles near the right side of the viewport).
 */
function StatTile({ title, accent, info, tipAlign, children }) {
  // Tooltips open upward by default; flip below when the tile sits too close
  // to the top of the viewport for the tooltip to fit above it.
  const [below, setBelow] = useState(false);
  const onEnter = (e) => {
    if (!info) return;
    const tip = e.currentTarget.querySelector(".hover-tooltip");
    const needed = (tip?.scrollHeight || 420) + 80;   // + fixed nav
    setBelow(e.currentTarget.getBoundingClientRect().top < needed);
  };
  return (
    <div
      onMouseEnter={onEnter}
      className={info ? `hover-explainer${tipAlign === "right" ? " tip-right" : ""}${below ? " tip-below" : ""}` : undefined}
      style={{
        background: accent || "#f8f9fa",
        border: "1px solid #dee2e6",
        borderRadius: 8,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: ".7rem", fontWeight: 700, color: "#6c757d", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 8 }}>
        {title}
        {info && <span className="info-glyph">ⓘ</span>}
      </div>
      {children}
      {info && <TooltipBody text={info} />}
    </div>
  );
}

function BenchmarkLine({ benchmarks }) {
  if (!benchmarks) return null;
  const yc = benchmarks.yield_curve;
  const cp = benchmarks.chauvet_piger;
  const simulated = benchmarks.simulated;
  return (
    <div data-testid="benchmark-line" style={{ marginTop: 8, paddingTop: 6, borderTop: "1px dashed #dee2e6", fontSize: ".74rem", color: "#6c757d" }}>
      <div style={{ fontWeight: 700, letterSpacing: ".04em", fontSize: ".64rem", textTransform: "uppercase", marginBottom: 2 }}>
        Independent cross-checks
      </div>
      {yc ? (
        <div title={`Yield-curve probit: 10y-3m spread ${yc.spread.toFixed(2)} pp (${fmtMonthYear(yc.spread_month)}), fitted on ${yc.n_observations} months (${yc.n_recessions} recessions) since ${fmtMonthYear(yc.train_start)}`}>
          Yield-curve model:{" "}
          <strong style={{ color: probColor(yc.prob_12m) }}>{yc.prob_12m.toFixed(1)}%</strong> / 12 mo
        </div>
      ) : (
        <div>Yield-curve model: n/a (too little history)</div>
      )}
      {cp ? (
        <div title="Chauvet–Piger smoothed recession probability (FRED RECPROUSM156N): is the US in recession that month? Its whole history is re-estimated with each release.">
          Chauvet–Piger, in recession?{" "}
          <strong style={{ color: probColor(cp.prob) }}>{cp.prob.toFixed(1)}%</strong>
          <span> · {fmtMonthYear(cp.month)}, revised</span>
          {simulated && (
            <div style={{ fontSize: ".66rem", fontStyle: "italic" }}>
              today's revised estimate, not what was published then
            </div>
          )}
        </div>
      ) : (
        <div>Chauvet–Piger: n/a (series starts Jun 1967)</div>
      )}
    </div>
  );
}

function ProbabilityPanel({ scoreData, benchmarks }) {
  if (!scoreData?.ml_model_available) return null;
  const p12 = scoreData.ml_prob_12m;
  const p6 = scoreData.ml_prob_6m;
  const pNow = scoreData.ml_score;

  return (
    <StatTile title="Recession Probability (ML)" info={EXPLAIN.probability}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: "1.7rem", fontWeight: 700, color: probColor(p12) }}>
          {p12 != null ? `${p12.toFixed(1)}%` : "—"}
        </span>
        <span style={{ fontSize: ".75rem", color: "#6c757d" }}>within 12 months</span>
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 6, fontSize: ".78rem" }}>
        <span>
          <strong style={{ color: probColor(p6) }}>{p6 != null ? `${p6.toFixed(1)}%` : "—"}</strong>
          <span style={{ color: "#6c757d" }}> / 6 mo</span>
        </span>
        <span>
          <strong style={{ color: probColor(pNow) }}>{pNow != null ? `${pNow.toFixed(1)}%` : "—"}</strong>
          <span style={{ color: "#6c757d" }}> / now</span>
        </span>
      </div>
      <div style={{ fontSize: ".68rem", color: "#adb5bd", paddingTop: 6 }}>
        ML: logit models trained on NBER history
      </div>
      <BenchmarkLine benchmarks={benchmarks} />
    </StatTile>
  );
}

function LeadingPanel({ leadingData, simDate }) {
  if (!leadingData) return null;
  const { leading_index, diffusion_index, n_deteriorating, n_leading_kpis } = leadingData;
  const diffColor = diffusion_index == null ? "#495057"
    : diffusion_index >= 70 ? "#842029"
    : diffusion_index >= 55 ? "#d35400"
    : "#1a9850";
  const leadColor = leading_index == null ? "#495057"
    : leading_index >= 50 ? "#842029"
    : leading_index >= 25 ? "#d35400"
    : "#1a9850";

  return (
    <StatTile title="Leading Indicators" info={EXPLAIN.leading}>
      <div style={{ display: "flex", gap: 18 }}>
        <div>
          <div style={{ fontSize: "1.7rem", fontWeight: 700, color: leadColor, lineHeight: 1.15 }}>
            {leading_index != null ? leading_index.toFixed(1) : "—"}
          </div>
          <div style={{ fontSize: ".7rem", color: "#6c757d" }}>Leading Index</div>
        </div>
        <div>
          <div style={{ fontSize: "1.7rem", fontWeight: 700, color: diffColor, lineHeight: 1.15 }}>
            {diffusion_index != null ? `${Math.round(diffusion_index)}%` : "—"}
          </div>
          <div style={{ fontSize: ".7rem", color: "#6c757d" }}>
            Deteriorating ({n_deteriorating}/{n_leading_kpis})
          </div>
        </div>
      </div>
      <div style={{ fontSize: ".68rem", color: "#adb5bd", marginTop: "auto", paddingTop: 6 }}>
        3-month breadth of {n_leading_kpis} leading KPIs
      </div>
    </StatTile>
  );
}

const SEVERITY_COLOR = {
  "NORMAL": "#1a9850",
  "SERIOUS": "#856404",
  "SEVERE": "#d35400",
  "DEPRESSION-SCALE": "#842029",
};

function SeverityPanel({ severityData }) {
  if (!severityData || severityData.severity_score == null) return null;
  const { severity_score, severity_band, components, persistence_months_critical } = severityData;
  const color = SEVERITY_COLOR[severity_band] || "#495057";
  const active = (components || []).filter(c => (c.sub_score ?? 0) > 0.1);

  return (
    <StatTile title="Depression Severity" info={EXPLAIN.severity}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: "1.7rem", fontWeight: 700, color }}>
          {severity_score.toFixed(1)}
        </span>
        <span style={{
          fontSize: ".72rem", fontWeight: 700, color: "#fff",
          background: color, borderRadius: 4, padding: "1px 6px",
        }}>
          {severity_band}
        </span>
      </div>
      {active.length > 0 && (
        <div style={{ fontSize: ".72rem", color: "#c0392b", marginTop: 4 }}>
          Active: {active.map(c => c.label).join(", ")}
          {persistence_months_critical > 0 && `, ${persistence_months_critical} mo at CRITICAL`}
        </div>
      )}
      <div style={{ fontSize: ".68rem", color: "#adb5bd", marginTop: "auto", paddingTop: 6 }}>
        Debt-deflation dynamics: how severe a downturn would be, not how likely.
      </div>
    </StatTile>
  );
}

const BUBBLE_COLOR = {
  LOW: "#1a9850", MODERATE: "#856404", HIGH: "#d35400", EXTREME: "#842029",
  INTACT: "#1a9850", CRACKING: "#856404", BREAKING: "#d35400", BURSTING: "#842029",
};

function AiBubblePanel({ bubbleData }) {
  if (!bubbleData || bubbleData.exposure?.score == null) return null;
  const { exposure, puncture, verdict } = bubbleData;
  const hot = [...(exposure.components || []), ...(puncture?.components || [])]
    .filter(c => (c.sub_score ?? 0) >= 0.5);
  const gauge = (label, g) => (
    <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
      <span style={{ fontSize: ".72rem", color: "#6c757d", width: 62 }}>{label}</span>
      <span style={{ fontSize: "1.35rem", fontWeight: 700, color: BUBBLE_COLOR[g?.band] || "#495057" }}>
        {g?.score != null ? g.score.toFixed(0) : "—"}
      </span>
      {g?.band && (
        <span style={{
          fontSize: ".68rem", fontWeight: 700, color: "#fff",
          background: BUBBLE_COLOR[g.band] || "#495057", borderRadius: 4, padding: "1px 6px",
        }}>{g.band}</span>
      )}
    </div>
  );
  return (
    <StatTile title="AI Bubble Monitor" info={EXPLAIN.aiBubble} tipAlign="right">
      <div data-testid="ai-bubble-tile">
        {gauge("Exposure", exposure)}
        {gauge("Puncture", puncture)}
      </div>
      {verdict && (
        <div style={{ fontSize: ".75rem", fontWeight: 600, marginTop: 4 }}>{verdict}</div>
      )}
      {hot.length > 0 && (
        <div style={{ fontSize: ".72rem", color: "#c0392b", marginTop: 2 }}>
          High: {hot.map(c => c.label).join(", ")}
        </div>
      )}
      <div style={{ fontSize: ".68rem", color: "#adb5bd", marginTop: "auto", paddingTop: 6 }}>
        Market-bubble view — not part of the Recession Risk Score.
      </div>
    </StatTile>
  );
}

function ForecastScorePanel({ forecastData, simDate }) {
  if (!forecastData) return null;

  const { forecast_score, forecast_band, forecast_date, actual_score, actual_band } = forecastData;
  const fmtDate = fmtMonthYear(forecast_date);
  const bandColor = RISK_BAND_COLOR[forecast_band] || "#495057";
  const bandBg = RISK_BAND_BG[forecast_band] || "#f8f9fa";

  return (
    <StatTile title="3-Month Forecast" accent={bandBg} info={EXPLAIN.forecast} tipAlign="right">
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: "1.7rem", fontWeight: 700, color: bandColor }}>
          {forecast_score != null ? forecast_score.toFixed(1) : "—"}
        </span>
        <span style={{
          fontSize: ".72rem", fontWeight: 700, color: "#fff",
          background: bandColor, borderRadius: 4, padding: "1px 6px",
        }}>
          {forecast_band || "—"}
        </span>
        <span style={{ fontSize: ".75rem", color: "#6c757d" }}>→ {fmtDate}</span>
      </div>

      {/* Actual score validation (Time Machine only) */}
      {actual_score != null ? (
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: ".7rem", color: "#6c757d" }}>✓ Actual @ {fmtDate}</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontSize: "1.1rem", fontWeight: 700, color: RISK_BAND_COLOR[actual_band] || "#495057" }}>
              {actual_score.toFixed(1)}
            </span>
            <span style={{
              fontSize: ".7rem", fontWeight: 600,
              color: RISK_BAND_COLOR[actual_band] || "#495057",
            }}>
              {actual_band}
            </span>
            {(() => {
              const err = forecast_score - actual_score;
              const sign = err > 0 ? "+" : "";
              const col = Math.abs(err) < 5 ? "#1a9850" : Math.abs(err) < 15 ? "#856404" : "#842029";
              return (
                <span style={{ fontSize: ".68rem", color: col }}>
                  error {sign}{err.toFixed(1)} pts
                </span>
              );
            })()}
          </div>
        </div>
      ) : (
        <div style={{ fontSize: ".68rem", color: "#adb5bd", marginTop: "auto", paddingTop: 6 }}>
          Linear trend projection of all KPIs
        </div>
      )}
    </StatTile>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // The static snapshot only exports live-mode data, so the Time Machine is off.
  const simDate = IS_STATIC ? null : (searchParams.get("as_of") || null);
  const today = new Date().toISOString().slice(0, 10);

  const [scoreData, setScoreData] = useState(null);
  const [categories, setCategories] = useState([]);
  const [topKpis, setTopKpis] = useState([]);
  const [scoreHistory, setScoreHistory] = useState([]);
  const [nber, setNber] = useState([]);
  const [forecastData, setForecastData] = useState(null);
  const [leadingData, setLeadingData] = useState(null);
  const [severityData, setSeverityData] = useState(null);
  const [bubbleData, setBubbleData] = useState(null);
  const [driversData, setDriversData] = useState(null);
  const [benchmarks, setBenchmarks] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadSeqRef = useRef(0);

  const setSimDate = (d) => {
    if (d) {
      setSearchParams({ as_of: d });
    } else {
      setSearchParams({});
    }
  };

  const load = useCallback(async () => {
    const token = ++loadSeqRef.current;
    setScoreData(null);
    setCategories([]);
    setTopKpis([]);
    setScoreHistory([]);
    setForecastData(null);
    setLeadingData(null);
    setSeverityData(null);
    setBubbleData(null);
    setDriversData(null);
    setBenchmarks(null);
    setError(null);
    try {
      // Core data — all required for the dashboard to render
      const [score, cats, kpis, history, nberData] = await Promise.all([
        api.score(simDate),
        api.categories(simDate),
        api.kpis(simDate),
        api.scoreHistoryWithML("2007-01-01", simDate),
        api.nberShading(),
      ]);
      // Forecast + leading + severity + drivers are optional — silently degrade on failure
      const [forecast, leading, severity, drivers, bench, bubble] = await Promise.all([
        api.scoreForecast(simDate).catch(() => null),
        api.leading(simDate).catch(() => null),
        api.severity(simDate).catch(() => null),
        api.scoreDrivers(simDate).catch(() => null),
        api.benchmarks(simDate).catch(() => null),
        api.aiBubble(simDate).catch(() => null),
      ]);
      if (token !== loadSeqRef.current) return;
      setScoreData(score);
      setCategories(cats);
      setScoreHistory(history);
      setNber(nberData);
      setForecastData(forecast);
      setLeadingData(leading);
      setSeverityData(severity);
      setBubbleData(bubble);
      setDriversData(drivers);
      setBenchmarks(bench);
      const sorted = [...kpis]
        // Monitor-only KPIs (ai_bubble) are not score drivers — keep them out
        // of the alert banner's "top contributors".
        .filter(k => k.sub_score != null && k.in_composite !== false)
        .sort((a, b) => b.sub_score - a.sub_score);
      setTopKpis(sorted.slice(0, 3));
    } catch (err) {
      if (token === loadSeqRef.current) setError(err.message || "Failed to load dashboard data");
    } finally {
      if (token === loadSeqRef.current) setLoading(false);
    }
  }, [simDate]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="no-data" style={{ padding: 48, textAlign: "center" }}>Loading dashboard…</div>;
  if (error) return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      <div style={{ color: "#c0392b", marginBottom: 12 }}>Failed to load dashboard: {error}</div>
      <button className="btn btn-primary" onClick={() => { setLoading(true); load(); }}>Retry</button>
    </div>
  );

  return (
    <div>

      {/* Time Machine bar */}
      {!IS_STATIC && <div style={{
        background: simDate ? "#fff3cd" : "#f8f9fa",
        border: `1px solid ${simDate ? "#ffc107" : "#dee2e6"}`,
        borderRadius: 8, padding: "10px 16px", marginBottom: 16,
        display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      }}>
        <span style={{ fontWeight: 600, fontSize: ".85rem", color: "#495057" }}>
          ⏱ Time Machine:
        </span>
        <input
          type="date"
          max={today}
          value={simDate || ""}
          onChange={e => setSimDate(e.target.value || null)}
          style={{ borderRadius: 4, border: "1px solid #ced4da", padding: "3px 8px", fontSize: ".85rem" }}
        />
        <button
          onClick={() => setSimDate("2008-09-15")}
          style={{ fontSize: ".78rem", padding: "3px 10px", cursor: "pointer",
                   background: "#fff", border: "1px solid #adb5bd", borderRadius: 4 }}
        >
          Sep 2008 (Lehman)
        </button>
        <button
          onClick={() => setSimDate("2020-04-15")}
          style={{ fontSize: ".78rem", padding: "3px 10px", cursor: "pointer",
                   background: "#fff", border: "1px solid #adb5bd", borderRadius: 4 }}
        >
          Apr 2020 (COVID)
        </button>
        {simDate && (
          <button
            onClick={() => setSimDate(null)}
            style={{ fontSize: ".78rem", padding: "3px 10px", cursor: "pointer",
                     background: "#dc3545", color: "#fff", border: "none", borderRadius: 4 }}
          >
            Live Mode
          </button>
        )}
        {!simDate && (
          <span style={{ fontSize: ".78rem", color: "#6c757d" }}>
            Pick a past date to see what the dashboard would have shown then.
          </span>
        )}
      </div>}

      {/* Historical view banner */}
      {simDate && (
        <div style={{
          background: "#f97316", color: "#fff", borderRadius: 8,
          padding: "8px 16px", marginBottom: 12, fontWeight: 700,
          fontSize: ".9rem", textAlign: "center",
        }}>
          HISTORICAL VIEW — Dashboard state as of {simDate}
        </div>
      )}

      {/* Stale warning (live mode only) */}
      {!simDate && !IS_STATIC && scoreData?.stale && (
        <div className="stale-warning">
          ⚠️ Data is more than 26 hours old. Click "Refresh Now" to fetch the latest values.
        </div>
      )}

      {/* Alert banner */}
      <AlertBanner score={scoreData?.score ?? 0} band={scoreData?.band} topKpis={topKpis} />

      {/* Header row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div className="page-header" style={{ marginBottom: 0 }}>
          <h1>Recession Risk Overview</h1>
          {scoreData?.last_refresh && !simDate && (
            <p>Last updated: {new Date(scoreData.last_refresh).toLocaleString()}</p>
          )}
        </div>
        {!simDate && !IS_STATIC && <RefreshButton onDone={load} />}
      </div>

      {/* Gauge + History chart, with the forward-looking stat strip below */}
      <div className="card" style={{ marginBottom: 24, padding: 20 }}>
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 400px", minWidth: 0 }}>
            <ScoreHistoryChart data={scoreHistory} nber={nber} highlightDate={simDate} asOf={simDate} />
          </div>
          <div className="hover-explainer tip-right tip-below" style={{ flex: "0 0 280px" }}>
            <RecessionGauge score={scoreData?.score ?? 0} band={scoreData?.band ?? "LOW"} />
            <TooltipBody text={EXPLAIN.score} />
          </div>
        </div>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
          gap: 12,
          marginTop: 18,
          borderTop: "1px solid #dee2e6",
          paddingTop: 18,
        }}>
          <ProbabilityPanel scoreData={scoreData} benchmarks={benchmarks} />
          <LeadingPanel leadingData={leadingData} simDate={simDate} />
          <SeverityPanel severityData={severityData} />
          <AiBubblePanel bubbleData={bubbleData} />
          <ForecastScorePanel forecastData={forecastData} simDate={simDate} />
        </div>
      </div>

      {/* Day-over-day attribution: which KPIs moved the score */}
      <ScoreDriversPanel
        drivers={driversData}
        simDate={simDate}
        categoryLabels={Object.fromEntries(categories.map(c => [c.id, c.label]))}
      />

      {/* Category cards */}
      <div className="section-title">KPI Categories</div>
      <div className="category-grid">
        {categories.map(cat => (
          <div
            key={cat.id}
            className="card category-card"
            onClick={() => navigate(`/category/${cat.id}${simDate ? `?as_of=${simDate}` : ""}`)}
          >
            <div className="category-card-header">
              <span className="category-icon">{cat.icon}</span>
              <span className="category-name">{cat.label}</span>
            </div>
            <div className="category-counts">
              {cat.danger_count > 0 && (
                <span className="badge badge-danger">🔴 {cat.danger_count} danger</span>
              )}
              {cat.warning_count > 0 && (
                <span className="badge badge-warn">🟡 {cat.warning_count} warning</span>
              )}
              {cat.danger_count === 0 && cat.warning_count === 0 && (
                <span className="badge badge-ok">🟢 All clear</span>
              )}
            </div>
            <div style={{ marginTop: 12 }}>
              <SparkLine
                data={cat.sparkline}
                color={BAND_COLOR[cat.id] || "#1a73e8"}
              />
            </div>
            <div style={{ fontSize: ".75rem", color: "#6c757d", marginTop: 6 }}>
              {cat.kpi_count} indicators
              {cat.in_composite === false && " · monitor only, not in score"}
            </div>
          </div>
        ))}
      </div>

      {/* Global AI Market Outlook — below category cards */}
      <AiCommentaryPanel
        title="AI Market Outlook"
        asOf={simDate}
        getEndpoint={(asOf) => api.getCommentaryGlobal(asOf)}
        postEndpoint={(asOf, force) => api.generateCommentaryGlobal(asOf, force)}
      />
    </div>
  );
}
