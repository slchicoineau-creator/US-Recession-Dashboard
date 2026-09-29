/**
 * Full 5-year time-series chart for an individual KPI.
 * Uses Recharts ComposedChart with:
 *   - LineChart for KPI values
 *   - ReferenceArea for NBER recession shading (grey bands)
 *   - ReferenceLine for warning (yellow dashed) and danger (red dashed) thresholds
 *   - X-axis formatted as MMM YYYY
 */
import React, { useEffect, useRef, useState } from "react";
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea, Legend,
} from "recharts";
import { api } from "../api.js";
import { IS_STATIC } from "../staticMode.js";

function fmtDate(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#fff", border: "1px solid #dee2e6", borderRadius: 6, padding: "8px 12px", fontSize: ".82rem" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{fmtDate(label)}</div>
      {payload.map(p => (
        <div key={p.name}>
          <span style={{ color: p.color }}>●</span> {p.name}:{" "}
          <strong>{typeof p.value === "number" ? p.value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : p.value}</strong>
        </div>
      ))}
    </div>
  );
}

export default function KpiDetailChart({ kpi, highlightDate = null, chartYMin, chartYMax }) {
  const [history, setHistory] = useState([]);
  const [nber, setNber] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const loadSeqRef = useRef(0);

  useEffect(() => {
    if (!kpi) return;
    // Sequence token discards stale responses on rapid kpi/highlightDate changes
    // (same pattern as HomePage).
    const token = ++loadSeqRef.current;
    setLoading(true);
    setError(null);
    Promise.all([
      api.kpiHistory(kpi.id, highlightDate),
      api.nberShading(),
    ]).then(([hist, nberData]) => {
      if (token !== loadSeqRef.current) return;
      setHistory(hist);
      setNber(nberData);
    }).catch(err => {
      if (token !== loadSeqRef.current) return;
      setError(err.message || "Failed to load chart data");
    }).finally(() => {
      if (token === loadSeqRef.current) setLoading(false);
    });
  }, [kpi?.id, highlightDate]);

  if (loading) return <div className="no-data" style={{ padding: 32 }}>Loading chart…</div>;
  // Distinguish a failed fetch from a genuinely empty series (BUGS.md AR3-004)
  if (error) return <div className="no-data" style={{ padding: 32, color: "#c0392b" }}>Failed to load chart: {error}</div>;
  if (!history.length) return (
    <div className="no-data" style={{ padding: 32 }}>
      {IS_STATIC
        ? "No data in this snapshot for this indicator (it needs a manual CSV upload in the full app)."
        : "No historical data available yet. Run a refresh to fetch data."}
    </div>
  );

  return (
    <ResponsiveContainer width="100%" height={340}>
      <ComposedChart data={history} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />

        {/* NBER recession shading */}
        {nber.map((period, i) => (
          <ReferenceArea
            key={i}
            x1={period.start}
            x2={period.end}
            fill="#e0e0e0"
            fillOpacity={0.55}
            label={{ value: "Recession", position: "insideTop", fontSize: 10, fill: "#999" }}
            ifOverflow="extendDomain"
          />
        ))}

        {/* Warning threshold */}
        {kpi.warning_threshold !== null && kpi.warning_threshold !== undefined && (
          <ReferenceLine
            y={kpi.warning_threshold}
            stroke="#d4ac0d"
            strokeDasharray="6 3"
            strokeWidth={1.5}
            label={{ value: "Warning", position: "right", fontSize: 11, fill: "#d4ac0d" }}
          />
        )}

        {/* Danger threshold */}
        {kpi.danger_threshold !== null && kpi.danger_threshold !== undefined && (
          <ReferenceLine
            y={kpi.danger_threshold}
            stroke="#c0392b"
            strokeDasharray="6 3"
            strokeWidth={1.5}
            label={{ value: "Danger", position: "right", fontSize: 11, fill: "#c0392b" }}
          />
        )}

        {/* Time Machine simulation date marker */}
        {highlightDate && (
          <ReferenceLine
            x={highlightDate}
            stroke="#f97316"
            strokeWidth={2}
            strokeDasharray="4 2"
            label={{ value: "Simulated", position: "insideTopRight", fontSize: 11, fill: "#f97316" }}
          />
        )}

        <XAxis
          dataKey="date"
          tickFormatter={fmtDate}
          tick={{ fontSize: 11, fill: "#6c757d" }}
          minTickGap={60}
        />
        <YAxis
          domain={[
            chartYMin !== undefined && chartYMin !== null ? chartYMin : "auto",
            chartYMax !== undefined && chartYMax !== null ? chartYMax : "auto",
          ]}
          allowDataOverflow={true}
          tick={{ fontSize: 11, fill: "#6c757d" }}
          tickFormatter={v => typeof v === "number" ? v.toLocaleString() : v}
          width={72}
        />
        <Tooltip content={<CustomTooltip />} />

        <Line
          type="monotone"
          dataKey="value"
          name={kpi.name}
          stroke="#1a73e8"
          strokeWidth={2}
          // A line needs >= 2 points to be visible; show dots for tiny series
          // so single-data-point KPIs don't render a blank chart (BUGS.md AR3-002).
          dot={history.length < 3}
          isAnimationActive={false}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
