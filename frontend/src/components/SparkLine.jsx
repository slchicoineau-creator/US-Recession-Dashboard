/**
 * Tiny 90-day sparkline using Recharts AreaChart.
 * Used in category summary cards on the home page.
 */
import React from "react";
import { AreaChart, Area, ResponsiveContainer, Tooltip } from "recharts";

export default function SparkLine({ data, color = "#1a73e8" }) {
  if (!data || data.length === 0) {
    return <div style={{ height: 52, display: "flex", alignItems: "center",
      justifyContent: "center", color: "#aaa", fontSize: ".75rem" }}>No data</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={52}>
      <AreaChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <defs>
          <linearGradient id={`sg-${color.replace("#","")}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.25} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Tooltip
          formatter={(v) => [typeof v === "number" ? v.toLocaleString() : v, ""]}
          labelFormatter={(l) => l}
          contentStyle={{ fontSize: ".75rem", padding: "4px 8px" }}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.5}
          fill={`url(#sg-${color.replace("#","")})`}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
