/**
 * AiCommentaryPanel — reusable AI analysis panel used on CategoryPage and HomePage.
 *
 * Props:
 *   getEndpoint   fn(asOf) -> Promise<{commentary, generated_at, model, cached}>
 *   postEndpoint  fn(asOf, force) -> Promise<{commentary, generated_at, model, cached}>
 *   asOf          string|null   (Time Machine date, e.g. "2008-09-15")
 *   title         string        (e.g. "AI Category Analysis")
 */
import React, { useEffect, useState, useRef } from "react";
import { IS_STATIC } from "../staticMode.js";

function fmtDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function AiCommentaryPanel({ getEndpoint, postEndpoint, asOf, title }) {
  const [commentary, setCommentary] = useState(null);
  const [generatedAt, setGeneratedAt] = useState(null);
  const [model, setModel] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [disabled, setDisabled] = useState(false);
  const tokenRef = useRef(0);

  // On mount (or asOf change): check for cached commentary
  useEffect(() => {
    const token = ++tokenRef.current;
    setCommentary(null);
    setGeneratedAt(null);
    setError(null);
    getEndpoint(asOf)
      .then(data => {
        if (token !== tokenRef.current) return;
        if (data.commentary) {
          setCommentary(data.commentary);
          setGeneratedAt(data.generated_at);
          setModel(data.model);
        }
      })
      .catch(() => {
        // Silently ignore GET errors — panel will show "not yet generated"
      });
  }, [asOf]);

  async function handleRefresh(force = false) {
    setLoading(true);
    setError(null);
    const token = ++tokenRef.current;
    try {
      const data = await postEndpoint(asOf, force);
      if (token !== tokenRef.current) return;
      if (data.error) {
        if (data.error.includes("ANTHROPIC_API_KEY")) {
          setDisabled(true);
          setError("Configure ANTHROPIC_API_KEY in .env to enable AI analysis.");
        } else {
          setError(data.error);
        }
      } else {
        setCommentary(data.commentary);
        setGeneratedAt(data.generated_at);
        setModel(data.model);
      }
    } catch (err) {
      if (token !== tokenRef.current) return;
      if (err.message && err.message.includes("503")) {
        setDisabled(true);
        setError("Configure ANTHROPIC_API_KEY in .env to enable AI analysis.");
      } else {
        setError("Failed to generate analysis. Try again.");
      }
    } finally {
      if (token === tokenRef.current) setLoading(false);
    }
  }

  // Read-only snapshot: show commentary only if the export captured one.
  if (IS_STATIC && !commentary) return null;

  return (
    <div className="ai-commentary-panel card" style={{ marginTop: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span style={{ fontSize: "1.2rem" }}>🤖</span>
        <span style={{ fontWeight: 700, fontSize: "1rem" }}>{title || "AI Analysis"}</span>
        <div style={{ marginLeft: "auto", display: IS_STATIC ? "none" : "flex", gap: 8 }}>
          {commentary && (
            <button
              className="btn btn-secondary"
              style={{ fontSize: ".75rem", padding: "4px 10px" }}
              onClick={() => handleRefresh(true)}
              disabled={loading || disabled}
            >
              {loading ? "Generating…" : "Regenerate"}
            </button>
          )}
          {!commentary && (
            <button
              className="btn btn-primary"
              style={{ fontSize: ".8rem", padding: "5px 14px" }}
              onClick={() => handleRefresh(false)}
              disabled={loading || disabled}
            >
              {loading ? "Generating…" : "Generate Analysis"}
            </button>
          )}
        </div>
      </div>

      {error && (
        <p style={{ color: "#842029", fontSize: ".85rem", margin: "6px 0 0" }}>{error}</p>
      )}

      {!commentary && !error && !loading && (
        <p style={{ color: "var(--color-muted)", fontSize: ".88rem", margin: "4px 0 0" }}>
          Click <em>Generate Analysis</em> to get an AI-written breakdown of current conditions
          and what to watch in this area.
        </p>
      )}

      {loading && !commentary && (
        <p style={{ color: "var(--color-muted)", fontSize: ".88rem", margin: "4px 0 0", fontStyle: "italic" }}>
          Analysing indicators…
        </p>
      )}

      {commentary && (
        <div>
          <p style={{
            fontSize: ".92rem",
            lineHeight: 1.65,
            color: "var(--color-text)",
            margin: "4px 0 10px",
            whiteSpace: "pre-wrap",
          }}>
            {commentary}
          </p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            {generatedAt && (
              <span style={{ fontSize: ".72rem", color: "var(--color-muted)" }}>
                Generated {fmtDate(generatedAt)}
              </span>
            )}
            {model && (
              <span style={{ fontSize: ".72rem", color: "var(--color-muted)" }}>
                · {model}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
