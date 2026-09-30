/**
 * Thin API client — all fetch calls go through /api/* (proxied to Flask in dev,
 * served directly in production when Flask hosts the built SPA).
 */

import { IS_STATIC, staticKey, staticDataUrl, ReadOnlySnapshotError } from "./staticMode.js";

const BASE = "/api";

async function _get(path) {
  if (IS_STATIC) {
    const res = await fetch(staticDataUrl(staticKey(path)));
    if (!res.ok) throw new Error(`Not included in this snapshot (${path})`);
    return res.json();
  }
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function _post(path, body) {
  if (IS_STATIC) throw new ReadOnlySnapshotError(`POST ${path}`);
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API POST ${path} → ${res.status}`);
  return res.json();
}

export const api = {
  score:       (asOf)      => _get(`/score${asOf ? `?as_of=${asOf}` : ""}`),
  kpis:        (asOf)      => _get(`/kpis${asOf ? `?as_of=${asOf}` : ""}`),
  kpiHistory:  (id, asOf)  => _get(`/kpis/${id}/history${asOf ? `?as_of=${asOf}` : ""}`),
  nberShading: ()          => _get("/nber-shading"),
  categories:  (asOf)      => _get(`/categories${asOf ? `?as_of=${asOf}` : ""}`),
  refresh:     ()          => _post("/refresh", {}),
  refreshStatus: ()        => _get("/refresh/status"),
  getConfig:   ()          => _get("/config"),
  saveConfig:  (data)      => _post("/config", data),

  scoreHistory: (fromDate, asOf) =>
    _get(`/score/history?from_date=${fromDate || "2007-01-01"}${asOf ? `&as_of=${asOf}` : ""}`),

  scoreHistoryWithML: (fromDate, asOf) =>
    _get(`/score/history?from_date=${fromDate || "2007-01-01"}&include_ml=true${asOf ? `&as_of=${asOf}` : ""}`),

  // Zoomed history: resolution = "5y" (weekly) | "2y" (every other business day) | "1y" (every business day)
  scoreHistoryZoom: (resolution, asOf) =>
    _get(`/score/history?resolution=${resolution}&include_ml=true${asOf ? `&as_of=${asOf}` : ""}`),

  scoreDrivers: (asOf) => _get(`/score/drivers${asOf ? `?as_of=${asOf}` : ""}`),

  scoreForecast: (asOf) => _get(`/score/forecast${asOf ? `?as_of=${asOf}` : ""}`),

  mlStatus: () => _get("/ml/status"),
  mlTrain:  () => _post("/ml/train", {}),
  mlScoreHistory: (fromDate, asOf, horizon) =>
    _get(`/ml/score/history?from_date=${fromDate || "2007-01-01"}${asOf ? `&as_of=${asOf}` : ""}${horizon ? `&horizon=${horizon}` : ""}`),

  leading: (asOf) => _get(`/leading${asOf ? `?as_of=${asOf}` : ""}`),
  leadingHistory: (fromDate, asOf) =>
    _get(`/leading/history?from_date=${fromDate || "2007-01-01"}${asOf ? `&as_of=${asOf}` : ""}`),

  backtest: (fromDate) =>
    _get(`/backtest${fromDate ? `?from_date=${fromDate}` : ""}`),

  severity: (asOf) => _get(`/severity${asOf ? `?as_of=${asOf}` : ""}`),

  aiBubble: (asOf) => _get(`/ai-bubble${asOf ? `?as_of=${asOf}` : ""}`),

  benchmarks: (asOf) => _get(`/benchmarks${asOf ? `?as_of=${asOf}` : ""}`),

  uploadCsv: async (kpiId, file) => {
    if (IS_STATIC) throw new ReadOnlySnapshotError("CSV upload");
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/upload-csv/${kpiId}`, { method: "POST", body: form });
    // Backend returns structured JSON errors; fall back to status text when the
    // body isn't JSON (e.g. an HTML 500 page) so the user sees a real message.
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      throw new Error(body?.error || `Upload failed (HTTP ${res.status})`);
    }
    return body;
  },

  getCommentaryCategory: (categoryId, asOf) =>
    _get(`/commentary/category/${categoryId}${asOf ? `?as_of=${asOf}` : ""}`),

  generateCommentaryCategory: (categoryId, asOf, force = false) => {
    if (IS_STATIC) return Promise.reject(new ReadOnlySnapshotError("AI commentary"));
    const params = new URLSearchParams();
    if (asOf) params.set("as_of", asOf);
    if (force) params.set("force", "true");
    const qs = params.toString();
    return fetch(`${BASE}/commentary/category/${categoryId}${qs ? `?${qs}` : ""}`, { method: "POST" })
      .then(r => { if (!r.ok) throw new Error(`API POST /commentary/category/${categoryId} → ${r.status}`); return r.json(); });
  },

  getCommentaryGlobal: (asOf) =>
    _get(`/commentary/global${asOf ? `?as_of=${asOf}` : ""}`),

  generateCommentaryGlobal: (asOf, force = false) => {
    if (IS_STATIC) return Promise.reject(new ReadOnlySnapshotError("AI commentary"));
    const params = new URLSearchParams();
    if (asOf) params.set("as_of", asOf);
    if (force) params.set("force", "true");
    const qs = params.toString();
    return fetch(`${BASE}/commentary/global${qs ? `?${qs}` : ""}`, { method: "POST" })
      .then(r => { if (!r.ok) throw new Error(`API POST /commentary/global → ${r.status}`); return r.json(); });
  },
};
