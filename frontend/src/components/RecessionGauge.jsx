/**
 * SVG arc gauge for the Recession Risk Score (0–100).
 * Color transitions: green (LOW) → yellow (ELEVATED) → orange (HIGH) → red (CRITICAL)
 */
import React from "react";

const BAND_COLOR = {
  LOW:      "#1a9850",
  ELEVATED: "#d4ac0d",
  HIGH:     "#e07b39",
  CRITICAL: "#c0392b",
};

const BAND_INTERP = {
  LOW:      "Economy broadly healthy. No imminent recession signals.",
  ELEVATED: "Warning signals accumulating across multiple indicators. Weighted composite reflects building economic stress — monitor closely for further deterioration.",
  HIGH:     "Multiple recession signals active. Historical precedent suggests recession within 6–12 months.",
  CRITICAL: "Broad-based recession signals. Historical analogs: 2008 financial crisis, 2020 COVID shock.",
};

function polarToXY(cx, cy, r, angleDeg) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function arcPath(cx, cy, r, startDeg, endDeg) {
  const s = polarToXY(cx, cy, r, startDeg);
  const e = polarToXY(cx, cy, r, endDeg);
  const large = endDeg - startDeg > 180 ? 1 : 0;
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${large} 1 ${e.x} ${e.y}`;
}

export default function RecessionGauge({ score, band }) {
  const cx = 150, cy = 150, r = 110, strokeW = 22;
  // Arc spans from -135° to +135° (270° total)
  const START = -135, END = 135;
  const total = END - START;
  const filled = START + (score / 100) * total;
  const color = BAND_COLOR[band] || "#aaa";

  return (
    <div className="gauge-section">
      <svg width="300" height="200" viewBox="0 0 300 200" aria-label={`Recession Risk Score ${score}`}>
        {/* Background track */}
        <path
          d={arcPath(cx, cy, r, START, END)}
          fill="none" stroke="#e9ecef" strokeWidth={strokeW} strokeLinecap="round"
        />
        {/* Colored arc segments for thresholds */}
        <path d={arcPath(cx, cy, r, START, START + total * 0.25)}
          fill="none" stroke="#1a9850" strokeWidth={strokeW} strokeLinecap="butt" opacity=".25" />
        <path d={arcPath(cx, cy, r, START + total * 0.25, START + total * 0.50)}
          fill="none" stroke="#d4ac0d" strokeWidth={strokeW} strokeLinecap="butt" opacity=".25" />
        <path d={arcPath(cx, cy, r, START + total * 0.50, START + total * 0.75)}
          fill="none" stroke="#e07b39" strokeWidth={strokeW} strokeLinecap="butt" opacity=".25" />
        <path d={arcPath(cx, cy, r, START + total * 0.75, END)}
          fill="none" stroke="#c0392b" strokeWidth={strokeW} strokeLinecap="butt" opacity=".25" />

        {/* Active arc */}
        {score > 0 && (
          <path
            d={arcPath(cx, cy, r, START, filled)}
            fill="none" stroke={color} strokeWidth={strokeW} strokeLinecap="round"
          />
        )}

        {/* Score text */}
        <text x={cx} y={cy - 10} textAnchor="middle" fontSize="44" fontWeight="800" fill={color}>
          {score !== null ? Math.round(score) : "—"}
        </text>
        <text x={cx} y={cy + 22} textAnchor="middle" fontSize="14" fontWeight="700"
          fill={color} letterSpacing="1">
          {band || "—"}
        </text>

        {/* Tick labels */}
        {[0, 25, 50, 75, 100].map(v => {
          const deg = START + (v / 100) * total;
          const pos = polarToXY(cx, cy, r + 22, deg);
          return (
            <text key={v} x={pos.x} y={pos.y} textAnchor="middle"
              fontSize="10" fill="#6c757d" dominantBaseline="central">{v}</text>
          );
        })}
      </svg>
      <div className="gauge-interp">{BAND_INTERP[band] || "Loading…"}</div>
    </div>
  );
}
