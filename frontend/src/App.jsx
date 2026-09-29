import React, { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link, useSearchParams } from "react-router-dom";
import HomePage from "./pages/HomePage.jsx";
import CategoryPage from "./pages/CategoryPage.jsx";
import KpiDetailPage from "./pages/KpiDetailPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import ModelPerformancePage from "./pages/ModelPerformancePage.jsx";
import { IS_STATIC, staticDataUrl } from "./staticMode.js";
import "./styles.css";

/**
 * Top nav must preserve the Time Machine ?as_of= param on every link (FRD rule:
 * the param propagates through ALL navigation; the Live Mode button is the only
 * way to exit historical view). The read-only snapshot has no Time Machine and
 * no Settings page.
 */
function TopNav() {
  const [searchParams] = useSearchParams();
  const simDate = IS_STATIC ? null : searchParams.get("as_of");
  const qs = simDate ? `?as_of=${simDate}` : "";
  return (
    <nav className="top-nav">
      <NavLink to={`/${qs}`} end className="nav-brand">
        US Economy KPI Dashboard
      </NavLink>
      <div className="nav-links">
        <NavLink to={`/${qs}`} end className={({ isActive }) => isActive ? "active" : ""}>Overview</NavLink>
        <NavLink to={`/performance${qs}`} className={({ isActive }) => isActive ? "active" : ""}>Model Performance</NavLink>
        {!IS_STATIC && (
          <NavLink to={`/settings${qs}`} className={({ isActive }) => isActive ? "active" : ""}>Settings</NavLink>
        )}
      </div>
    </nav>
  );
}

/** Read-only snapshot banner: when the data was exported, and where the code lives. */
function SnapshotBanner() {
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    fetch(staticDataUrl("meta.json"))
      .then(r => (r.ok ? r.json() : null))
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);
  const when = meta?.generated_at
    ? new Date(meta.generated_at).toLocaleString("en-US", {
        month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      })
    : null;
  return (
    <div className="snapshot-banner" role="note">
      <strong>Read-only snapshot</strong>
      {when && <> · snapshot taken {when}</>}
      {" "}· refreshed daily · not investment advice
      {meta?.repo_url && (
        <> · <a href={meta.repo_url} target="_blank" rel="noopener noreferrer">source code &amp; setup</a></>
      )}
    </div>
  );
}

/** Static mode: a shared Time Machine link must not silently show live data. */
function StaticAsOfNotice() {
  const [searchParams] = useSearchParams();
  const asOf = searchParams.get("as_of");
  if (!asOf) return null;
  return (
    <div className="static-notice" role="status" style={{
      background: "#e7f1ff", border: "1px solid #9ec5fe", borderRadius: 8,
      padding: "8px 16px", marginBottom: 12, fontSize: ".85rem", color: "#084298",
    }}>
      The Time Machine (viewing {asOf}) needs the full app — this read-only snapshot shows live data only.
    </div>
  );
}

function NotFound() {
  return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      <h1 style={{ fontSize: "1.3rem" }}>Page not found</h1>
      <p><Link to="/">Back to the overview</Link></p>
    </div>
  );
}

function StaticSettingsNotice() {
  return (
    <div className="no-data" style={{ padding: 48, textAlign: "center" }}>
      Settings (alert thresholds, email, CSV uploads) are only available when you run the dashboard yourself.
    </div>
  );
}

// Vite's BASE_URL is "/" locally and "/<repo>/" on GitHub Pages.
const ROUTER_BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

export default function App() {
  return (
    <BrowserRouter basename={ROUTER_BASENAME}>
      <div className="app-shell">
        {IS_STATIC && <SnapshotBanner />}
        <TopNav />
        <main className="main-content">
          {IS_STATIC && <StaticAsOfNotice />}
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/category/:id" element={<CategoryPage />} />
            <Route path="/kpi/:id" element={<KpiDetailPage />} />
            <Route path="/performance" element={<ModelPerformancePage />} />
            <Route path="/settings" element={IS_STATIC ? <StaticSettingsNotice /> : <SettingsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
