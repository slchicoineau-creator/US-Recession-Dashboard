/**
 * Settings page — alert thresholds, email config, manual CSV uploads.
 */
import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// The upload list is derived from kpi_config.yaml (source: manual_csv) via
// /api/kpis, never hard-coded: a hard-coded list drifted out of sync, listing
// KPIs already automated from FRED while omitting a real manual one.

function CsvUploader({ kpi }) {
  const [status, setStatus] = useState(null);
  const [uploading, setUploading] = useState(false);

  const handleFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setStatus(null);
    try {
      const res = await api.uploadCsv(kpi.id, file);
      setStatus(res.error
        ? `Error: ${res.error}`
        : `✓ ${res.rows_saved} rows saved`);
    } catch (err) {
      setStatus(`Error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={{ marginBottom: 16 }} data-testid={`csv-upload-${kpi.id}`}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{kpi.name}</div>
      <div style={{ fontSize: ".78rem", color: "#6c757d", marginBottom: 6 }}>
        Expected CSV columns: <code>date (YYYY-MM-DD), value (float)</code>
      </div>
      <label className="upload-area" style={{ display: "block" }}>
        {uploading
          ? <><span className="spinner" /> Uploading…</>
          : <>📂 Click to upload CSV for {kpi.name}</>}
        <input type="file" accept=".csv" style={{ display: "none" }} onChange={handleFile} disabled={uploading} />
      </label>
      {status && <div style={{ marginTop: 6, fontSize: ".82rem",
        color: status.startsWith("✓") ? "#1a9850" : "#c0392b" }}>{status}</div>}
    </div>
  );
}

export default function SettingsPage() {
  const [cfg, setCfg] = useState({ warning_threshold: 50, critical_threshold: 75, alerts_enabled: true });
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [manualKpis, setManualKpis] = useState(null);   // null = loading
  const [manualError, setManualError] = useState(null);

  useEffect(() => {
    api.getConfig()
      .then(data => setCfg(data))
      .catch(() => setLoadError("Could not load saved settings — values shown are defaults."));
    api.kpis()
      .then(kpis => setManualKpis(kpis.filter(k => k.source === "manual_csv")))
      .catch(() => setManualError("Could not load the KPI list."));
  }, []);

  const handleChange = (key, val) => {
    setCfg(prev => ({ ...prev, [key]: val }));
    setSaved(false);
    setError(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.saveConfig({
        warning_threshold: Number(cfg.warning_threshold),
        critical_threshold: Number(cfg.critical_threshold),
        alerts_enabled: cfg.alerts_enabled,
      });
      setSaved(true);
    } catch (err) {
      setError(err.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <p>Configure alert thresholds and upload manual data.</p>
      </div>

      {loadError && (
        <div style={{ background: "#fff3cd", color: "#856404", borderRadius: 8,
          padding: "8px 16px", marginBottom: 12, fontSize: ".88rem" }}>
          ⚠ {loadError}
        </div>
      )}

      {/* Alert thresholds */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div className="section-title">Alert Thresholds</div>
        <div className="settings-form">
          <label>Warning Threshold (default: 50)</label>
          <input
            type="number" min="0" max="100" step="1"
            value={cfg.warning_threshold}
            onChange={e => handleChange("warning_threshold", e.target.value)}
          />
          <div className="hint">Email alert sent when score crosses this value (HIGH band).</div>

          <label>Critical Threshold (default: 75)</label>
          <input
            type="number" min="0" max="100" step="1"
            value={cfg.critical_threshold}
            onChange={e => handleChange("critical_threshold", e.target.value)}
          />
          <div className="hint">Second email alert sent when score crosses this value (CRITICAL band).</div>

          <label style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="checkbox"
              checked={!!cfg.alerts_enabled}
              onChange={e => handleChange("alerts_enabled", e.target.checked)}
              style={{ width: "auto" }}
            />
            Enable email alerts
          </label>

          <div className="settings-save-bar">
            <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
              {saving ? <><span className="spinner" /> Saving…</> : "Save Settings"}
            </button>
            {saved && <span style={{ color: "#1a9850", fontWeight: 600 }}>✓ Saved</span>}
            {error && <span style={{ color: "#c0392b", fontWeight: 600 }}>Save failed: {error}</span>}
          </div>
        </div>
      </div>

      {/* Email credentials note */}
      <div className="card" style={{ marginBottom: 20, background: "#f8f9fa" }}>
        <div className="section-title">Email Credentials</div>
        <p style={{ fontSize: ".88rem", color: "#495057", lineHeight: 1.6 }}>
          Email credentials (ALERT_EMAIL_FROM, ALERT_EMAIL_TO, ALERT_EMAIL_PASSWORD)
          are configured in the <code>.env</code> file in the project root, not stored
          here. Edit that file and restart the server to update them.
        </p>
        {cfg.alert_email_to && (
          <p style={{ marginTop: 8, fontSize: ".88rem" }}>
            Current alert recipient: <strong>{cfg.alert_email_to}</strong>
          </p>
        )}
      </div>

      {/* Manual CSV uploads */}
      <div className="card">
        <div className="section-title">Manual Data Upload</div>
        <p style={{ fontSize: ".88rem", color: "#6c757d", marginBottom: 20, lineHeight: 1.5 }}>
          KPIs with no free public API are listed here for manual CSV upload.
          Each CSV must have two columns: <code>date</code> (YYYY-MM-DD) and <code>value</code> (numeric).
        </p>
        {manualError && <div data-testid="manual-csv-error" style={{ color: "#c0392b", fontSize: ".88rem" }}>{manualError}</div>}
        {!manualError && manualKpis === null && <p style={{ fontSize: ".88rem" }}>Loading…</p>}
        {manualKpis && manualKpis.length === 0 && (
          <p data-testid="manual-csv-empty" style={{ fontSize: ".88rem" }}>
            No KPIs currently require manual upload. Every KPI is fetched automatically.
          </p>
        )}
        {manualKpis && manualKpis.map(kpi => <CsvUploader key={kpi.id} kpi={kpi} />)}
      </div>
    </div>
  );
}
