/**
 * Static (read-only snapshot) mode — enabled at build time with VITE_STATIC=1.
 *
 * In static mode there is no Flask server: every GET the app would make is
 * served from a pre-exported JSON file under `${BASE_URL}data/`, written by
 * tools/export_static.py. Mutations (refresh, settings, CSV upload, AI
 * commentary generation, ML retraining) are unavailable, and the Time Machine
 * is disabled because only live-mode responses are exported.
 *
 * staticKey() MUST stay identical to static_key() in tools/export_static.py —
 * that is the contract between the exporter and the SPA. The static
 * Playwright spec fails on any 404 under /data/, which catches drift.
 */

// Optional chaining keeps this module importable from plain Node (the
// pytest parity test in tests/test_static_export.py imports staticKey).
export const IS_STATIC = import.meta.env?.VITE_STATIC === "1";

/** "/score/history?resolution=5y&include_ml=true" -> "score__history--include_ml=true--resolution=5y.json" */
export function staticKey(path) {
  const [rawPath, query = ""] = path.split("?");
  const params = new URLSearchParams(query);
  params.delete("as_of");
  const entries = [...params.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  let key = rawPath.replace(/^\/+/, "").replace(/\//g, "__");
  if (entries.length) key += "--" + entries.map(([k, v]) => `${k}=${v}`).join("--");
  return key.replace(/[^A-Za-z0-9_.=-]/g, "_") + ".json";
}

export function staticDataUrl(file) {
  return `${import.meta.env?.BASE_URL ?? "/"}data/${file}`;
}

export class ReadOnlySnapshotError extends Error {
  constructor(what = "This action") {
    super(`${what} is not available in the read-only snapshot.`);
    this.name = "ReadOnlySnapshotError";
  }
}
