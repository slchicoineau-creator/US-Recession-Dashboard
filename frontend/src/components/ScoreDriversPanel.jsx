/**
 * "What moved the score" — day-over-day attribution of the Recession Risk Score.
 *
 * Data: GET /api/score/drivers (see backend/score_history.py).
 *   basis "snapshot"      — live: diff of the per-KPI values the dashboard used
 *                           on the two most recent refresh days (exact).
 *   basis "category_only" — live, before two KPI snapshots exist: category
 *                           split from the stored live scores (exact), no KPI rows.
 *   basis "reconstructed" — Time Machine: as_of vs previous business day,
 *                           rebuilt from current (revised) data.
 *
 * KPI impact = today's score minus today's score with only that KPI put back
 * to its previous value. Positive = pushed risk up.
 */
import React, { useState } from "react";
import { Link } from "react-router-dom";

const STATUS_CLASS = { OK: "badge-ok", WARNING: "badge-warn", DANGER: "badge-danger" };
const WORSE = "#c0392b";
const BETTER = "#1a9850";

function fmtDay(iso) {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtVal(v) {
  if (v == null) return "—";
  const a = Math.abs(v);
  const digits = a >= 1000 ? 0 : a >= 100 ? 1 : 2;
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function fmtImpact(x) {
  if (x == null) return "—";
  const s = x.toFixed(2);
  return x > 0 ? `+${s}` : s;
}

function StatusBadge({ status }) {
  if (!status || status === "NO_DATA") return <span style={{ color: "#adb5bd" }}>—</span>;
  return <span className={`badge ${STATUS_CLASS[status] || ""}`} style={{ fontSize: ".68rem" }}>{status}</span>;
}

function ImpactBar({ impact, max }) {
  const pct = max > 0 ? Math.min(100, (Math.abs(impact) / max) * 100) : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 120 }}>
      <div style={{ flex: 1, height: 8, background: "#f1f3f5", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: impact > 0 ? WORSE : BETTER }} />
      </div>
      <span style={{ fontWeight: 700, color: impact > 0 ? WORSE : BETTER, fontVariantNumeric: "tabular-nums", minWidth: 44, textAlign: "right" }}>
        {fmtImpact(impact)}
      </span>
    </div>
  );
}

export default function ScoreDriversPanel({ drivers, simDate, categoryLabels = {} }) {
  const [showQuiet, setShowQuiet] = useState(false);
  if (!drivers || drivers.basis === "none") return null;

  const minImpact = drivers.min_impact ?? 0.05;
  const movers = drivers.kpis.filter(k => Math.abs(k.impact) >= minImpact);
  const quiet = drivers.kpis.filter(k => Math.abs(k.impact) < minImpact);
  const cats = drivers.categories.filter(c => Math.abs(c.impact) >= 0.005);
  const maxImpact = Math.max(0, ...movers.map(k => Math.abs(k.impact)), ...cats.map(c => Math.abs(c.impact)));
  // Delta from the rounded endpoints so the header never reads "39.3 → 40.3 (+0.9)".
  const delta = drivers.score_from != null && drivers.score_to != null
    ? Math.round((drivers.score_to - drivers.score_from) * 10) / 10
    : 0;
  const qs = simDate ? `?as_of=${simDate}` : "";
  const label = id => categoryLabels[id] || drivers.categories.find(c => c.id === id)?.label || id;

  return (
    <div className="card" style={{ marginBottom: 24, padding: 20 }} data-testid="score-drivers">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <div className="section-title" style={{ marginBottom: 4 }}>What moved the score</div>
        <div style={{ fontSize: ".85rem", color: "#495057" }}>
          {fmtDay(drivers.from_date)} → {fmtDay(drivers.to_date)}:{" "}
          <strong>{drivers.score_from?.toFixed(1)} → {drivers.score_to?.toFixed(1)}</strong>{" "}
          <span style={{ fontWeight: 700, color: delta > 0 ? WORSE : delta < 0 ? BETTER : "#6c757d" }}>
            ({delta > 0 ? "+" : ""}{delta.toFixed(1)})
          </span>
        </div>
      </div>

      {drivers.basis === "category_only" && (
        <p style={{ fontSize: ".78rem", color: "#6c757d", margin: "4px 0 12px" }}>
          Per-indicator detail needs indicator snapshots from two refresh days
          {drivers.first_snapshot_date ? ` (first recorded ${fmtDay(drivers.first_snapshot_date)})` : ""}.
          The category split below is exact, taken from the stored daily scores.
        </p>
      )}
      {drivers.basis === "reconstructed" && (
        <p style={{ fontSize: ".78rem", color: "#6c757d", margin: "4px 0 12px" }}>
          Time Machine: compares with the previous business day, rebuilt from today's (revised) data.
        </p>
      )}
      {drivers.basis === "snapshot" && (
        <p style={{ fontSize: ".78rem", color: "#6c757d", margin: "4px 0 12px" }}>
          Compares the indicator values the dashboard used on each refresh day. That includes new releases and revisions.
        </p>
      )}

      {cats.length === 0 && movers.length === 0 ? (
        <div style={{ fontSize: ".85rem", color: "#6c757d" }}>No indicator moved the score.</div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 20 }}>
          {/* By category */}
          <div>
            <div style={{ fontSize: ".72rem", fontWeight: 700, color: "#6c757d", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 8 }}>
              By category (score points)
            </div>
            {cats.map(c => (
              <div key={c.id} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "center", fontSize: ".82rem", padding: "4px 0" }}>
                <div>
                  <Link to={`/category/${c.id}${qs}`} style={{ color: "#212529", textDecoration: "none", fontWeight: 600 }}>{label(c.id)}</Link>
                  <span style={{ color: "#868e96", marginLeft: 6, fontSize: ".74rem" }}>
                    {c.score_from ?? "—"} → {c.score_to ?? "—"}
                  </span>
                </div>
                <ImpactBar impact={c.impact} max={maxImpact} />
              </div>
            ))}
          </div>

          {/* By indicator */}
          {drivers.basis !== "category_only" && (
            <div>
              <div style={{ fontSize: ".72rem", fontWeight: 700, color: "#6c757d", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 8 }}>
                By indicator (score points)
              </div>
              {movers.length === 0 && (
                <div style={{ fontSize: ".82rem", color: "#6c757d" }}>No single indicator moved the score by {minImpact} or more.</div>
              )}
              {movers.map(k => (
                <div key={k.kpi_id} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "center", fontSize: ".82rem", padding: "5px 0", borderBottom: "1px solid #f1f3f5" }}>
                  <div style={{ minWidth: 0 }}>
                    <Link to={`/kpi/${k.kpi_id}${qs}`} style={{ color: "#212529", textDecoration: "none", fontWeight: 600 }}>{k.name}</Link>
                    <div style={{ fontSize: ".74rem", color: "#868e96", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 2 }}>
                      <span>{label(k.category)}</span>
                      <span>·</span>
                      <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmtVal(k.value_from)} → {fmtVal(k.value_to)}{k.unit ? ` ${k.unit}` : ""}</span>
                      {k.status_from !== k.status_to && (
                        <><StatusBadge status={k.status_from} /><span>→</span><StatusBadge status={k.status_to} /></>
                      )}
                    </div>
                  </div>
                  <ImpactBar impact={k.impact} max={maxImpact} />
                </div>
              ))}
              {drivers.interaction != null && Math.abs(drivers.interaction) >= minImpact && (
                <div style={{ fontSize: ".74rem", color: "#868e96", marginTop: 6 }}>
                  Interaction between indicators: {fmtImpact(drivers.interaction)} points. Several indicators in the same category moving together, or a category gaining or losing data.
                </div>
              )}
              {quiet.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <button
                    onClick={() => setShowQuiet(s => !s)}
                    style={{ fontSize: ".74rem", background: "none", border: "none", color: "#1a73e8", cursor: "pointer", padding: 0 }}
                  >
                    {showQuiet ? "Hide" : "Show"} {quiet.length} other updated indicator{quiet.length === 1 ? "" : "s"} with no score impact
                  </button>
                  {showQuiet && (
                    <div style={{ marginTop: 6 }}>
                      {quiet.map(k => (
                        <div key={k.kpi_id} style={{ fontSize: ".74rem", color: "#6c757d", padding: "2px 0" }}>
                          <Link to={`/kpi/${k.kpi_id}${qs}`} style={{ color: "#495057" }}>{k.name}</Link>
                          <span style={{ marginLeft: 6, fontVariantNumeric: "tabular-nums" }}>{fmtVal(k.value_from)} → {fmtVal(k.value_to)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
