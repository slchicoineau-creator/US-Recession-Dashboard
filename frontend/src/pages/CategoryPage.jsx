/**
 * Category drill-down page — table of all KPIs in a category.
 * Includes 3-month forecast column (and Actual validation column in Time Machine mode).
 */
import React, { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { IS_STATIC } from "../staticMode.js";
import AiCommentaryPanel from "../components/AiCommentaryPanel.jsx";

const CATEGORY_LABELS = {
  yield_curve:       "Yield Curve & Rates",
  labor_market:      "Labor Market",
  consumer_health:   "Consumer Health",
  housing:           "Housing Market",
  financial_stress:  "Financial Stress",
  business_activity: "Business Activity",
  energy:            "Energy Market",
  automotive:        "Automotive Market",
  ai_bubble:         "AI Bubble Monitor",
};

const STATUS_COLOR = {
  OK:      "#1a9850",
  WARNING: "#856404",
  DANGER:  "#842029",
  NO_DATA: "#6c757d",
};

const TREND_ICON = {
  up:   "▲",
  down: "▼",
  flat: "→",
};

function TrafficLight({ status }) {
  return <span className={`tl tl-${status}`} title={status} />;
}

function fmtVal(v, unit) {
  if (v === null || v === undefined) return "—";
  const num = parseFloat(v);
  if (isNaN(num)) return v;
  const str = num.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return unit ? `${str} ${unit}` : str;
}

function StatusBadge({ status }) {
  if (!status || status === "NO_DATA") return <span style={{ color: STATUS_COLOR.NO_DATA, fontSize: ".75rem" }}>—</span>;
  return (
    <span style={{ fontWeight: 600, fontSize: ".75rem", color: STATUS_COLOR[status] || STATUS_COLOR.NO_DATA }}>
      {status}
    </span>
  );
}

/** Format a date string like "2009-01-15" → "Jan 2009" */
function fmtMonthYear(iso) {
  if (!iso) return "";
  try {
    return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

export default function CategoryPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const simDate = IS_STATIC ? null : (searchParams.get("as_of") || null);
  const [kpis, setKpis] = useState([]);
  const [forecastDate, setForecastDate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadSeqRef = useRef(0);

  useEffect(() => {
    // Sequence token discards stale responses when id/simDate changes rapidly
    // (same pattern as HomePage).
    const token = ++loadSeqRef.current;
    setLoading(true);
    setError(null);
    Promise.all([
      api.kpis(simDate),
      api.scoreForecast(simDate).catch(() => null),
    ]).then(([allKpis, forecastResp]) => {
      if (token !== loadSeqRef.current) return;
      setKpis(allKpis.filter(k => k.category === id));
      setForecastDate(forecastResp?.forecast_date || null);
    }).catch(err => {
      if (token !== loadSeqRef.current) return;
      setError(err.message || "Failed to load KPIs");
    }).finally(() => {
      if (token === loadSeqRef.current) setLoading(false);
    });
  }, [id, simDate]);

  const label = CATEGORY_LABELS[id] || id;
  const fmtFcDate = fmtMonthYear(forecastDate);

  // Show "Actual" column only in Time Machine mode
  const showActual = !!simDate;

  if (loading) return <div className="no-data" style={{ padding: 48 }}>Loading…</div>;
  if (error) return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      <div style={{ color: "#c0392b", marginBottom: 8 }}>Failed to load category data: {error}</div>
      <Link to={`/${simDate ? `?as_of=${simDate}` : ""}`} className="back-link">← Overview</Link>
    </div>
  );

  return (
    <div>
      <Link to={`/${simDate ? `?as_of=${simDate}` : ""}`} className="back-link">← Overview</Link>
      {simDate && (
        <div style={{
          background: "#f97316", color: "#fff", borderRadius: 8,
          padding: "8px 16px", marginBottom: 12, fontWeight: 700,
          fontSize: ".9rem", textAlign: "center",
        }}>
          HISTORICAL VIEW — Dashboard state as of {simDate}
        </div>
      )}
      <div className="page-header">
        <h1>{label}</h1>
        <p>{kpis.length} indicators in this category</p>
        {kpis.length > 0 && kpis.every(k => k.in_composite === false) && (
          <p data-testid="monitor-only-note" style={{ color: "#856404", fontSize: ".85rem" }}>
            Monitor only — these indicators are shown for context and are not part of the
            Recession Risk Score. They feed the AI Bubble tile on the Overview page.
          </p>
        )}
      </div>

      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        <table className="kpi-table">
          <thead>
            <tr>
              <th>KPI Name</th>
              <th>Current Value</th>
              <th>Change</th>
              <th>Change %</th>
              <th>Status</th>
              <th style={{ color: "#2980b9" }}>
                3M Forecast
                {fmtFcDate && <span style={{ fontWeight: 400, fontSize: ".75rem", marginLeft: 4 }}>→ {fmtFcDate}</span>}
              </th>
              <th style={{ color: "#2980b9", whiteSpace: "nowrap", textAlign: "center" }}>
                Accuracy
                <span style={{ display: "block", fontWeight: 400, fontSize: ".7rem" }}>(3M Backtest)</span>
              </th>
              <th style={{ color: "#2980b9" }}>Forecast Status</th>
              {showActual && (
                <th style={{ color: "#6c3483" }}>
                  Actual
                  {fmtFcDate && <span style={{ fontWeight: 400, fontSize: ".75rem", marginLeft: 4 }}>@ {fmtFcDate}</span>}
                </th>
              )}
              <th>Reporting Period</th>
            </tr>
          </thead>
          <tbody>
            {kpis.map(kpi => {
              const fcVal = kpi.forecast_value;
              const fcTrend = kpi.forecast_trend;
              const trendColor = fcTrend === "up" ? "#c0392b" : fcTrend === "down" ? "#1a9850" : "#6c757d";
              // For invert KPIs: up trend = more risk (bad), down = less risk (good)
              // We keep it neutral here since we show the status badge explicitly.

              return (
                <tr key={kpi.id} onClick={() => navigate(`/kpi/${kpi.id}${simDate ? `?as_of=${simDate}` : ""}`)}>
                  <td>
                    <TrafficLight status={kpi.status} />
                    {kpi.name}
                    {kpi.source === "manual_csv" && (
                      <span style={{ fontSize: ".7rem", color: "#6c757d", marginLeft: 6 }}>(manual)</span>
                    )}
                    {kpi.stale && (
                      <span
                        style={{ fontSize: ".7rem", color: "#b45309", marginLeft: 6, fontWeight: 600 }}
                        title="Latest data is older than expected for this publication frequency — source may be lagging or discontinued"
                      >
                        ⚠ stale
                      </span>
                    )}
                  </td>
                  <td>{fmtVal(kpi.latest_value, kpi.unit)}</td>
                  <td>
                    {kpi.change_abs != null ? (
                      <span className={kpi.change_abs >= 0 ? "change-pos" : "change-neg"}>
                        {kpi.change_abs >= 0 ? "+" : ""}{kpi.change_abs?.toFixed(3)}
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    {kpi.change_pct != null ? (
                      <span className={kpi.change_pct >= 0 ? "change-pos" : "change-neg"}>
                        {kpi.change_pct >= 0 ? "+" : ""}{kpi.change_pct?.toFixed(2)}%
                      </span>
                    ) : "—"}
                  </td>
                  <td>
                    <span style={{ fontWeight: 600, fontSize: ".8rem", color: STATUS_COLOR[kpi.status] }}>
                      {kpi.status}
                    </span>
                  </td>
                  {/* 3M Forecast value */}
                  <td style={{ color: "#2980b9" }}>
                    {fcVal != null ? (
                      <span>
                        {fmtVal(fcVal, kpi.unit)}
                        {fcTrend && (
                          <span style={{ marginLeft: 4, fontSize: ".8rem", color: trendColor }}>
                            {TREND_ICON[fcTrend] || ""}
                          </span>
                        )}
                      </span>
                    ) : "—"}
                  </td>
                  {/* Forecast accuracy (backtest) */}
                  <td style={{ textAlign: "center" }}>
                    {kpi.forecast_accuracy != null ? (
                      <span style={{
                        fontWeight: 600,
                        fontSize: ".85rem",
                        color: kpi.forecast_accuracy >= 85 ? "#27ae60"
                             : kpi.forecast_accuracy >= 60 ? "#f39c12"
                             : "#e74c3c"
                      }}
                        title={`${kpi.forecast_accuracy_samples ?? 0} sample(s) in past 3 months`}
                      >
                        {kpi.forecast_accuracy.toFixed(1)}%
                      </span>
                    ) : (
                      <span style={{ color: "#aaa" }}>—</span>
                    )}
                  </td>
                  {/* Forecast status badge */}
                  <td>
                    <StatusBadge status={kpi.forecast_status} />
                  </td>
                  {/* Actual value at forecast date (Time Machine only) */}
                  {showActual && (
                    <td style={{ color: "#6c3483" }}>
                      {kpi.actual_value_at_forecast_date != null
                        ? fmtVal(kpi.actual_value_at_forecast_date, kpi.unit)
                        : <span style={{ color: "#aaa" }}>—</span>}
                    </td>
                  )}
                  <td style={{ fontSize: ".8rem", color: "#6c757d" }}>
                    {kpi.latest_date || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <AiCommentaryPanel
        title="AI Category Analysis"
        asOf={simDate}
        getEndpoint={(asOf) => api.getCommentaryCategory(id, asOf)}
        postEndpoint={(asOf, force) => api.generateCommentaryCategory(id, asOf, force)}
      />
    </div>
  );
}
