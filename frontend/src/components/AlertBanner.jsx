/**
 * Persistent alert banner shown when score >= 50.
 * Lists the top 3 contributing KPIs.
 */
import React from "react";

export default function AlertBanner({ score, band, topKpis = [] }) {
  if (!band || (band !== "HIGH" && band !== "CRITICAL")) return null;

  return (
    <div className={`alert-banner ${band}`}>
      <span style={{ fontSize: "1.4rem" }}>{band === "CRITICAL" ? "🚨" : "⚠️"}</span>
      <div>
        <strong>Recession Risk: {band} ({Math.round(score)}/100)</strong>
        {topKpis.length > 0 && (
          <div style={{ fontWeight: 400, marginTop: 4, fontSize: ".85rem" }}>
            Top signals:&nbsp;
            {topKpis.slice(0, 3).map((k, i) => {
              // /api/kpis returns the reading as `latest_value`
              const v = k.latest_value ?? k.value;
              return (
                <span key={k.kpi_id}>
                  {k.name} ({typeof v === "number" ? v.toFixed(2) : v ?? "—"})
                  {i < Math.min(topKpis.length, 3) - 1 ? " · " : ""}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
