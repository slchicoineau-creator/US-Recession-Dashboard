/**
 * Historical Recession Risk Score chart.
 *
 * Four zoom levels:
 *   Since 2007 — monthly (cached server-side; passed in via `data`)
 *   5Y         — weekly
 *   2Y         — every other business day
 *   1Y         — every business day
 * The purple dashed line is the ML probability of a recession within 12
 * months (ml_12m), the headline of the Recession Probability card; the tooltip
 * also shows the 6-month and "now" horizons.
 *
 * Zoomed views are fetched on demand from /api/score/history?resolution=…,
 * auto-fit the score axis (ML gets its own right-hand % axis), and show orange dots for the score the live dashboard
 * actually published that day (the line is reconstructed from today's revised
 * data, so the two can legitimately differ).
 *
 * Uses Recharts ComposedChart with NBER recession shading and band threshold lines.
 * The X axis is categorical, so every ReferenceArea/ReferenceLine x value must
 * be a date that exists in the data array — NBER periods and the Time Machine
 * marker are snapped onto the visible points.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, ReferenceArea,
} from "recharts";
import { api } from "../api.js";

const BAND_LINES = [
  { y: 25, color: "#1a9850", label: "LOW→ELEVATED" },
  { y: 50, color: "#d4ac0d", label: "ELEVATED→HIGH" },
  { y: 75, color: "#e07b39", label: "HIGH→CRITICAL" },
];

const RANGES = [
  { id: "max", label: "Since 2007", detail: "monthly" },
  { id: "5y", label: "5Y", detail: "weekly" },
  { id: "2y", label: "2Y", detail: "every other business day" },
  { id: "1y", label: "1Y", detail: "every business day" },
];

const PUBLISHED_COLOR = "#e67e22";

function fmtDate(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

function fmtDay(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function CustomTooltip({ active, payload, label, zoomed }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload || {};
  const score = point.score;
  const band = point.band;
  const ml12 = point.ml_12m;
  const ml6 = point.ml_6m;
  const mlNow = point.ml_score;
  const published = point.published;
  const BAND_COLOR = { LOW: "#1a9850", ELEVATED: "#d4ac0d", HIGH: "#e07b39", CRITICAL: "#c0392b" };
  return (
    <div style={{
      background: "#fff", border: "1px solid #dee2e6",
      borderRadius: 6, padding: "8px 12px", fontSize: ".82rem",
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{zoomed ? fmtDay(label) : fmtDate(label)}</div>
      <div>
        Score: <strong>{typeof score === "number" ? score.toFixed(1) : "—"}</strong>
        {band && (
          <span style={{
            marginLeft: 8, fontWeight: 700,
            color: BAND_COLOR[band] || "#495057",
          }}>{band}</span>
        )}
      </div>
      {published != null && (
        <div style={{ marginTop: 2, color: PUBLISHED_COLOR }}>
          As published that day: <strong>{published.toFixed(1)}</strong>
        </div>
      )}
      {ml12 != null && (
        <div style={{ marginTop: 2, color: "#7d3c98" }}>
          ML recession probability: <strong>{ml12.toFixed(1)}%</strong> within 12 mo
          <div style={{ fontSize: ".76rem", color: "#9b59b6" }}>
            {ml6 != null && <>{ml6.toFixed(1)}% / 6 mo</>}
            {mlNow != null && <>{ml6 != null ? " · " : ""}{mlNow.toFixed(1)}% / now</>}
          </div>
        </div>
      )}
    </div>
  );
}

/** Snap NBER periods onto dates present in the (sorted) data, dropping any outside it. */
function snapPeriods(periods, dates) {
  if (!dates.length) return [];
  const out = [];
  for (const p of periods) {
    const x1 = dates.find(d => d >= p.start);
    const x2 = [...dates].reverse().find(d => d <= p.end);
    if (x1 && x2 && x1 <= x2) out.push({ x1, x2 });
  }
  return out;
}

/** Last data date on or before `target` (or the first date if target precedes all). */
function snapDate(target, dates) {
  if (!target || !dates.length) return null;
  if (target < dates[0] || target > dates[dates.length - 1]) return null;
  let best = dates[0];
  for (const d of dates) {
    if (d <= target) best = d; else break;
  }
  return best;
}

export default function ScoreHistoryChart({ data = [], nber = [], highlightDate = null, asOf = null }) {
  const [range, setRange] = useState("max");
  const [zoomCache, setZoomCache] = useState({});   // { "5y": [...], ... } for the current asOf
  const [zoomLoading, setZoomLoading] = useState(false);
  const [zoomError, setZoomError] = useState(null);
  const seqRef = useRef(0);

  // Time Machine date changed → cached zoom data belongs to a different end date.
  // Bumping the token also discards any in-flight response for the old date.
  useEffect(() => {
    seqRef.current++;
    setZoomCache({});
    setZoomError(null);
    setZoomLoading(false);
  }, [asOf]);

  // A new monthly array means the page reloaded (e.g. "Refresh Now") — the
  // zoomed points are stale too. Guarded on length: the page empties `data`
  // mid-load, and refetching then would be wasted.
  useEffect(() => {
    if (!data.length) return;
    seqRef.current++;
    setZoomCache({});
    setZoomLoading(false);
  }, [data]);

  useEffect(() => {
    if (range === "max" || zoomCache[range]) return;
    const token = ++seqRef.current;
    setZoomLoading(true);
    setZoomError(null);
    api.scoreHistoryZoom(range, asOf)
      .then(rows => {
        if (token !== seqRef.current) return;
        setZoomCache(c => ({ ...c, [range]: rows }));
      })
      .catch(err => {
        if (token === seqRef.current) setZoomError(err.message || "Failed to load");
      })
      .finally(() => {
        if (token === seqRef.current) setZoomLoading(false);
      });
  }, [range, asOf, zoomCache]);

  const zoomed = range !== "max";
  const shown = zoomed ? (zoomCache[range] || []) : data;
  const dates = useMemo(() => shown.map(p => p.date), [shown]);
  const shading = useMemo(() => snapPeriods(nber, dates), [nber, dates]);
  const marker = useMemo(() => snapDate(highlightDate, dates), [highlightDate, dates]);
  const hasPublished = zoomed && shown.some(p => p.published != null);

  // Zoomed views auto-fit the Y axis so day-to-day moves are visible.
  const yDomain = useMemo(() => {
    if (!zoomed || !shown.length) return [0, 100];
    const vals = shown.flatMap(p => [p.score, p.published]).filter(v => typeof v === "number");
    if (!vals.length) return [0, 100];
    const lo = Math.max(0, Math.floor((Math.min(...vals) - 3) / 5) * 5);
    const hi = Math.min(100, Math.ceil((Math.max(...vals) + 3) / 5) * 5);
    return [lo, Math.max(hi, lo + 10)];
  }, [zoomed, shown]);

  const yTicks = useMemo(() => {
    if (!zoomed) return [0, 25, 50, 75, 100];
    const step = yDomain[1] - yDomain[0] <= 30 ? 5 : 10;
    const ticks = [];
    for (let t = Math.ceil(yDomain[0] / step) * step; t <= yDomain[1]; t += step) ticks.push(t);
    return ticks;
  }, [zoomed, yDomain]);

  // ML probability (12-month horizon). Monthly view: same 0–100 scale as the
  // score, right axis hidden. Zoomed views: the score axis is zoomed to e.g.
  // 20–50 and a ~14% probability would fall off it, so ML gets its own
  // right-hand percentage axis fitted to its own range.
  const mlVals = shown.map(p => p.ml_12m).filter(v => typeof v === "number");
  const hasMl = mlVals.length > 0;
  const mlDomain = useMemo(() => {
    if (!zoomed || !mlVals.length) return [0, 100];
    const hi = Math.min(100, Math.max(20, Math.ceil((Math.max(...mlVals) + 3) / 10) * 10));
    return [0, hi];
  }, [zoomed, mlVals.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps
  const mlTicks = useMemo(() => {
    const step = mlDomain[1] <= 50 ? 10 : 20;
    const ticks = [];
    for (let t = 0; t <= mlDomain[1]; t += step) ticks.push(t);
    return ticks;
  }, [mlDomain]);

  if (!data.length) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 260, color: "#6c757d", fontSize: ".9rem" }}>
        Loading score history… (first load may take ~15 seconds)
      </div>
    );
  }

  const activeRange = RANGES.find(r => r.id === range);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <div>
          <span className="section-title" style={{ marginBottom: 0 }}>Recession Risk Score History</span>
          <span style={{ marginLeft: 8, fontSize: ".78rem", color: "#6c757d" }}>
            {activeRange.detail}{zoomed ? " · Y axis zoomed" : ""}
          </span>
        </div>
        <div role="group" aria-label="History range" style={{ display: "flex", gap: 4 }}>
          {RANGES.map(r => (
            <button
              key={r.id}
              data-testid={`history-range-${r.id}`}
              onClick={() => setRange(r.id)}
              aria-pressed={range === r.id}
              title={r.detail}
              style={{
                fontSize: ".76rem", padding: "3px 10px", cursor: "pointer", borderRadius: 4,
                border: `1px solid ${range === r.id ? "#1a73e8" : "#ced4da"}`,
                background: range === r.id ? "#1a73e8" : "#fff",
                color: range === r.id ? "#fff" : "#495057",
                fontWeight: range === r.id ? 600 : 400,
              }}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {zoomed && !shown.length ? (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, color: zoomError ? "#c0392b" : "#6c757d", fontSize: ".9rem" }}>
          {zoomError ? `Could not load ${activeRange.label} history: ${zoomError}` : zoomLoading ? `Computing ${activeRange.detail} scores…` : ""}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={shown} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />

            {/* NBER recession shading (snapped onto visible dates) */}
            {shading.map((p, i) => (
              <ReferenceArea
                key={i}
                yAxisId="score"
                x1={p.x1}
                x2={p.x2}
                fill="#e0e0e0"
                fillOpacity={0.55}
              />
            ))}

            {/* Band threshold lines (hidden when outside a zoomed Y range) */}
            {BAND_LINES.filter(({ y }) => y >= yDomain[0] && y <= yDomain[1]).map(({ y, color, label }) => (
              <ReferenceLine
                key={y}
                yAxisId="score"
                y={y}
                stroke={color}
                strokeDasharray="6 3"
                strokeWidth={1.5}
                label={{ value: label, position: "insideRight", fontSize: 9, fill: color }}
              />
            ))}

            {/* Time Machine date marker */}
            {marker && (
              <ReferenceLine
                yAxisId="score"
                x={marker}
                stroke="#f97316"
                strokeWidth={2}
                strokeDasharray="4 2"
                label={{
                  value: "Simulated",
                  // At the right edge the label would be clipped — put it left of the line.
                  position: marker === dates[dates.length - 1] ? "insideTopRight" : "insideTopLeft",
                  fontSize: 10, fill: "#f97316",
                }}
              />
            )}

            <XAxis
              dataKey="date"
              tickFormatter={fmtDate}
              tick={{ fontSize: 10, fill: "#6c757d" }}
              minTickGap={70}
            />
            <YAxis
              yAxisId="score"
              domain={yDomain}
              ticks={yTicks}
              allowDecimals={false}
              allowDataOverflow={zoomed}
              tick={{ fontSize: 10, fill: "#6c757d" }}
              width={32}
            />
            <YAxis
              yAxisId="ml"
              orientation="right"
              hide={!zoomed}
              domain={mlDomain}
              ticks={mlTicks}
              allowDataOverflow
              tickFormatter={v => `${v}%`}
              tick={{ fontSize: 10, fill: "#9b59b6" }}
              width={36}
            />
            <Tooltip content={<CustomTooltip zoomed={zoomed} />} />

            <Line
              yAxisId="score"
              type="monotone"
              dataKey="score"
              name="Risk Score"
              stroke="#1a73e8"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
            {hasMl && <Line
              yAxisId="ml"
              type="monotone"
              dataKey="ml_12m"
              name="ML recession probability (12 mo)"
              stroke="#9b59b6"
              strokeWidth={1.5}
              strokeDasharray="5 3"
              dot={false}
              isAnimationActive={false}
              connectNulls
            />}
            {hasPublished && (
              <Line
                yAxisId="score"
                dataKey="published"
                name="As published"
                stroke="none"
                dot={{ r: 2.5, fill: PUBLISHED_COLOR, stroke: PUBLISHED_COLOR }}
                activeDot={{ r: 4, fill: PUBLISHED_COLOR }}
                isAnimationActive={false}
                connectNulls={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}

      {shown.length > 0 && (
        <div style={{ fontSize: ".72rem", color: "#6c757d", marginTop: 4, display: "flex", gap: 14, flexWrap: "wrap" }}>
          <span><span style={{ color: "#1a73e8", fontWeight: 700 }}>━</span> {zoomed ? "Score, recomputed from current (revised) data" : "Risk score"}</span>
          {hasPublished && (
            <span><span style={{ color: PUBLISHED_COLOR, fontWeight: 700 }}>●</span> Score the dashboard showed that day</span>
          )}
          {hasMl && (
            <span><span style={{ color: "#9b59b6", fontWeight: 700 }}>┅</span> ML recession probability within 12 months{zoomed ? " (right axis, %)" : " (%)"}</span>
          )}
        </div>
      )}
    </div>
  );
}
