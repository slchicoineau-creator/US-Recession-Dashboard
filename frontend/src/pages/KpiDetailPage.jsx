/**
 * Individual KPI detail view.
 * Shows: 5-year chart with NBER shading + thresholds, last 24 data points, metadata panel.
 */
import React, { useEffect, useRef, useState } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import { IS_STATIC } from "../staticMode.js";
import KpiDetailChart from "../components/KpiDetailChart.jsx";

export default function KpiDetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const simDate = IS_STATIC ? null : (searchParams.get("as_of") || null);
  const [kpi, setKpi] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadSeqRef = useRef(0);

  useEffect(() => {
    // Sequence token discards stale responses when id/simDate changes rapidly
    // (same pattern as HomePage).
    const token = ++loadSeqRef.current;
    setLoading(true);
    setError(null);
    Promise.all([api.kpis(simDate), api.kpiHistory(id, simDate)]).then(([kpis, hist]) => {
      if (token !== loadSeqRef.current) return;
      setKpi(kpis.find(k => k.id === id) || null);
      setHistory(hist);
    }).catch(err => {
      if (token !== loadSeqRef.current) return;
      setError(err.message || "Failed to load KPI");
    }).finally(() => {
      if (token === loadSeqRef.current) setLoading(false);
    });
  }, [id, simDate]);

  if (loading) return <div className="no-data" style={{ padding: 48 }}>Loading…</div>;
  if (error) return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      <div style={{ color: "#c0392b", marginBottom: 8 }}>Failed to load KPI data: {error}</div>
      <Link to={`/${simDate ? `?as_of=${simDate}` : ""}`} className="back-link">← Overview</Link>
    </div>
  );
  if (!kpi) return <div className="no-data" style={{ padding: 48 }}>KPI not found.</div>;

  const last24 = [...history].reverse().slice(0, 24);

  const statusColor = { OK: "#1a9850", WARNING: "#856404", DANGER: "#842029", NO_DATA: "#6c757d" };

  return (
    <div>
      <Link
        to={`/category/${kpi.category}${simDate ? `?as_of=${simDate}` : ""}`}
        className="back-link"
      >← {kpi.category}</Link>

      <div className="page-header">
        <h1>{kpi.name}</h1>
        <p>
          {kpi.unit && <><strong>Unit:</strong> {kpi.unit} &nbsp;·&nbsp;</>}
          <strong>Frequency:</strong> {kpi.frequency} &nbsp;·&nbsp;
          <strong>Source:</strong> {kpi.source?.toUpperCase()}
          {kpi.series_id && <> &nbsp;·&nbsp; <strong>Series:</strong> {kpi.series_id}</>}
        </p>
      </div>

      {/* Current value summary */}
      <div className="card" style={{ marginBottom: 20, display: "flex", gap: 32, alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: ".78rem", color: "#6c757d", textTransform: "uppercase", letterSpacing: ".5px" }}>Current Value</div>
          <div style={{ fontSize: "2rem", fontWeight: 800 }}>
            {kpi.latest_value != null ? kpi.latest_value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : "—"}
            {kpi.unit && <span style={{ fontSize: "1rem", fontWeight: 400, marginLeft: 4 }}>{kpi.unit}</span>}
          </div>
          <div style={{ fontSize: ".8rem", color: "#6c757d" }}>
            Reporting period: {kpi.latest_date || "—"}
          </div>
          <div style={{ fontSize: ".75rem", color: "#adb5bd" }}>
            Retrieved{kpi.source === "fred" ? " from FRED" : ""}: {kpi.data_retrieved ? new Date(kpi.data_retrieved).toLocaleDateString() : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: ".78rem", color: "#6c757d", textTransform: "uppercase", letterSpacing: ".5px" }}>Status</div>
          <div style={{ fontSize: "1.2rem", fontWeight: 700, color: statusColor[kpi.status] }}>{kpi.status}</div>
        </div>
        {kpi.change_abs != null && (
          <div>
            <div style={{ fontSize: ".78rem", color: "#6c757d", textTransform: "uppercase", letterSpacing: ".5px" }}>Change vs Prior</div>
            <div style={{ fontSize: "1.1rem", fontWeight: 600,
              color: kpi.change_abs >= 0 ? "#1a9850" : "#c0392b" }}>
              {kpi.change_abs >= 0 ? "+" : ""}{kpi.change_abs?.toFixed(3)}
              {kpi.change_pct != null && (
                <span style={{ fontSize: ".85rem", marginLeft: 6 }}>
                  ({kpi.change_pct >= 0 ? "+" : ""}{kpi.change_pct?.toFixed(2)}%)
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Chart + meta panel */}
      <div className="detail-grid">
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title" style={{ marginBottom: 12 }}>
              20-Year History{simDate ? ` (as of ${simDate})` : ""}
            </div>
            <KpiDetailChart kpi={kpi} highlightDate={simDate} chartYMin={kpi.chart_y_min} chartYMax={kpi.chart_y_max} />
          </div>

          {/* Last 24 data points */}
          <div className="card">
            <div className="section-title">Recent Data Points</div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr><th>Date</th><th>Value</th></tr>
                </thead>
                <tbody>
                  {last24.map(row => (
                    <tr key={row.date}>
                      <td>{row.date}</td>
                      <td>{row.value != null
                        ? row.value.toLocaleString(undefined, { maximumFractionDigits: 4 })
                        : "—"}</td>
                    </tr>
                  ))}
                  {last24.length === 0 && (
                    <tr><td colSpan={2} className="no-data">No data yet</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Metadata panel */}
        <div className="card meta-panel" style={{ alignSelf: "flex-start" }}>
          <div className="section-title">About This Indicator</div>
          <p style={{ fontSize: ".88rem", lineHeight: 1.6, color: "#495057" }}>
            {kpi.description || "No description available."}
          </p>

          <label>Source</label>
          <p>{kpi.source?.toUpperCase()}</p>

          {kpi.series_id && <><label>Series ID</label><p style={{ fontFamily: "monospace" }}>{kpi.series_id}</p></>}

          <label>Update Frequency</label>
          <p style={{ textTransform: "capitalize" }}>{kpi.frequency}</p>

          <label>Category</label>
          <p style={{ textTransform: "capitalize" }}>{kpi.category?.replace("_", " ")}</p>

          {kpi.warning_threshold != null && (
            <><label>Warning Threshold</label><p style={{ color: "#856404" }}>{kpi.warning_threshold} {kpi.unit}</p></>
          )}
          {kpi.danger_threshold != null && (
            <><label>Danger Threshold</label><p style={{ color: "#842029" }}>{kpi.danger_threshold} {kpi.unit}</p></>
          )}
        </div>
      </div>
    </div>
  );
}
