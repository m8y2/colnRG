import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from "react";
import { getStats, getSites, triggerSync, getSyncLog, getReportStatus, clearCache } from "./api";
import StatsCards from "./components/StatsCards";
import ChemicalSelect from "./components/ChemicalSelect";
import AnimatedSelect from "./components/AnimatedSelect";
const OverviewChart = lazy(() => import("./components/OverviewChart"));
const TimeSeriesChart = lazy(() => import("./components/TimeSeriesChart"));
const LocationSeries = lazy(() => import("./components/LocationSeries"));
const SiteAverages = lazy(() => import("./components/SiteAverages"));
const DataTable = lazy(() => import("./components/DataTable"));
const PhotoGallery = lazy(() => import("./components/PhotoGallery"));
const SiteReport = lazy(() => import("./components/SiteReport"));
const RoundReport = lazy(() => import("./components/RoundReport"));

const SiteMap = lazy(() => import("./components/SiteMap"));
const ColnLine = lazy(() => import("./components/ColnLine"));

export default function App() {
  const [stats, setStats] = useState(null);
  const [sites, setSites] = useState([]);
  const [syncLog, setSyncLog] = useState([]);
  const [syncing, setSyncing] = useState(false);
  const [tab, setTab] = useState("overview");
  const [siteFilter, setSiteFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("2025-06-06");
  const [dateTo, setDateTo] = useState("");
  const [overviewChemical, setOverviewChemical] = useState("phosphate");
  const [sitesTab, setSitesTab] = useState("map");
  const [error, setError] = useState("");
  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem("coln-dark-mode");
    if (saved !== null) return saved === "true";
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  });
  const [reportRunningTasks, setReportRunningTasks] = useState([]);
  const [completedTasks, setCompletedTasks] = useState([]);
  const prevBackendTasks = useRef([]);

  useEffect(() => {
    document.body.classList.toggle("dark", isDark);
    localStorage.setItem("coln-dark-mode", isDark);
  }, [isDark]);

  useEffect(() => {
    const tick = async () => {
      try {
        const status = await getReportStatus();
        const backendTasks = (status.running || []).filter((t) => t.type !== "infra");
        const backendIds = new Set(backendTasks.map((t) => t.id));

        for (const pt of prevBackendTasks.current) {
          if (!backendIds.has(pt.id) && pt.progress >= 0) {
            setCompletedTasks((prev) => {
              if (prev.some((c) => c.id === pt.id)) return prev;
              return [...prev, { ...pt, progress: 100, message: "Complete", completedAt: Date.now() }];
            });
          }
        }
        prevBackendTasks.current = backendTasks;

        setReportRunningTasks((prev) => {
          const merged = [...backendTasks];
          for (const t of prev) {
            if (t.id && t.id.startsWith("opt-") && !backendTasks.some((bt) => bt.identifier === t.identifier && bt.type === t.type)) {
              merged.push(t);
            }
          }
          return merged;
        });
        setCompletedTasks((prev) => prev.filter((c) => Date.now() - c.completedAt < 60000));
      } catch {}
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => clearInterval(id);
  }, []);

  const addOptimisticTask = useCallback((identifier, type) => {
    const task = { id: `opt-${identifier}-${Date.now()}`, identifier, progress: 0, message: "Queued...", type };
    setReportRunningTasks((prev) => [...prev, task]);
  }, []);



  const toggleTheme = () => setIsDark((d) => !d);

  const switchTab = (t) => {
    setTab(t);
    setSiteFilter("");
    setDateFrom("2025-06-06");
    setDateTo("");
  };

  const loadData = useCallback(async () => {
    try {
      setError("");
      const [s, sitesData, log] = await Promise.all([
        getStats(),
        getSites(),
        getSyncLog(5),
      ]);
      setStats(s);
      setSites(sitesData);
      setSyncLog(log);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleSync = async () => {
    setSyncing(true);
    setError("");
    try {
      await triggerSync();
      clearCache();
      await loadData();
    } catch (e) {
      setError(e.message);
    }
    setSyncing(false);
  };

  const lastSync = useMemo(() => {
    if (!stats?.last_sync) return "Never";
    const d = new Date(stats.last_sync);
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const yyyy = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    return `${dd}/${mm}/${yyyy} ${hh}:${mi}`;
  }, [stats?.last_sync]);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Coln River Guardians</h1>
          <p style={{ color: "var(--text-muted)", fontSize: "0.875rem" }}>
            Water quality monitoring on the River Coln
          </p>
        </div>
        <div className="header-sub">
          <span className="last-sync">Last sync: {lastSync}</span>
          <button className="sync-btn" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync Now"}
          </button>
          <button className="theme-toggle" onClick={toggleTheme} title={isDark ? "Switch to light mode" : "Switch to dark mode"}>
            {isDark ? "\u2600" : "\u263E"}
          </button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      {(reportRunningTasks.length > 0 || completedTasks.length > 0) && (
        <div style={{ padding: "8px 16px", background: "var(--primary-bg)", borderBottom: "1px solid var(--border)", fontSize: "0.85rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {reportRunningTasks.length > 0 && (
              <span style={{ fontWeight: 600, color: "var(--primary)" }}>Generating ({reportRunningTasks.length} running)</span>
            )}
            {reportRunningTasks.filter((t) => t.type !== "infra").map((t) => {
              const etaMap = { "Queued...": "", "Spinning up droplet": "~2 min", "Droplet ready": "~1 min", "Copying data to droplet": "~1 min", "Generating report via LLM": "~30s", "Saving report": "~5s", "Complete": "Done" };
              const eta = etaMap[t.message] || (t.progress >= 80 ? "<1 min" : t.progress >= 40 ? "~1 min" : t.progress > 0 ? "~2 min" : "");
              return (
                <span key={t.id} style={{ color: "var(--text-secondary)" }}>
                  {t.identifier}: {t.progress < 0 ? "Failed" : `${t.progress}%`}
                  <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>{t.message}</span>
                  {eta && <span style={{ color: "var(--text-muted)", marginLeft: 4 }}>({eta})</span>}
                </span>
              );
            })}
            <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
              {reportRunningTasks.filter((t) => t.type !== "infra").map((t) => (
                <div key={t.id} style={{ width: 80, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${Math.max(0, t.progress)}%`, height: "100%", background: t.progress < 0 ? "var(--error)" : "var(--primary)", borderRadius: 3, transition: "width 0.5s ease" }} />
                </div>
              ))}
            </div>
          </div>
          {completedTasks.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginTop: 6, paddingTop: 6, borderTop: "1px solid var(--border)" }}>
              <span style={{ fontWeight: 600, color: "var(--success)" }}>Complete ({completedTasks.length})</span>
              {completedTasks.map((t) => (
                <span key={t.id} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ color: "var(--success)" }}>{t.identifier} ✓</span>
                  <button
                    className="sync-btn"
                    style={{ padding: "2px 8px", fontSize: "0.75rem", background: "var(--success)", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
                    onClick={() => {
                      const target = t.type === "site" ? "site-report" : "round-report";
                      switchTab(target);
                    }}
                  >
                    View
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mobile-notice">Optimised for desktop — works on mobile</div>

      <div className="tabs">
        <button
          className={`tab ${tab === "overview" ? "active" : ""}`}
          onClick={() => switchTab("overview")}
        >
          Overview
        </button>
        <button
          className={`tab ${tab === "chart" ? "active" : ""}`}
          onClick={() => switchTab("chart")}
        >
          Chemical levels over time
        </button>
        <button
          className={`tab ${tab === "site-averages" ? "active" : ""}`}
          onClick={() => switchTab("site-averages")}
        >
          Long-term Site Averages
        </button>
        <button
          className={`tab ${tab === "location-series" ? "active" : ""}`}
          onClick={() => switchTab("location-series")}
        >
          Round by round results
        </button>
        <button
          className={`tab ${tab === "sites" ? "active" : ""}`}
          onClick={() => switchTab("sites")}
        >
          Sites
        </button>
        <button
          className={`tab ${tab === "data" ? "active" : ""}`}
          onClick={() => switchTab("data")}
        >
          Data Table
        </button>
        <button
          className={`tab ${tab === "photos" ? "active" : ""}`}
          onClick={() => switchTab("photos")}
        >
          Photo Gallery
        </button>
        <div className="beta-group">
          <span className="beta-badge">Beta</span>
          <button
            className={`tab ${tab === "site-report" ? "active" : ""}`}
            onClick={() => switchTab("site-report")}
          >
            Site Report
          </button>
          <button
            className={`tab ${tab === "round-report" ? "active" : ""}`}
            onClick={() => switchTab("round-report")}
          >
            Round Report
          </button>
        </div>
      </div>

      <main className="tab-content" key={tab}>
        {(tab === "chart" || tab === "data") && (
          <div className="filters">
            <label>
              Site:
              <AnimatedSelect
                options={[
                  { value: "", label: "All Sites" },
                  ...sites.map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` })),
                ]}
                value={siteFilter}
                onChange={setSiteFilter}
              />
            </label>
            <label>
              From:
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
              />
            </label>
            <label>
              To:
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
              />
            </label>
          </div>
        )}

        {tab === "overview" && (
          <>
            <StatsCards stats={stats} />
            <Suspense fallback={<div className="loading">Loading chart...</div>}>
              <OverviewChart
                chemical={overviewChemical}
                onSwitch={setOverviewChemical}
              />
            </Suspense>
          </>
        )}

        {tab === "chart" && (
          <Suspense fallback={<div className="loading">Loading chart...</div>}>
            <ChartView
              siteFilter={siteFilter}
              dateFrom={dateFrom}
              dateTo={dateTo}
            />
          </Suspense>
        )}

        {tab === "data" && (
          <Suspense fallback={<div className="loading">Loading data...</div>}>
            <DataTable
              siteFilter={siteFilter}
              dateFrom={dateFrom}
              dateTo={dateTo}
            />
          </Suspense>
        )}

        {tab === "location-series" && (
          <Suspense fallback={<div className="loading">Loading location series...</div>}>
            <LocationSeries sites={sites} />
          </Suspense>
        )}
        {tab === "site-averages" && (
          <Suspense fallback={<div className="loading">Loading site averages...</div>}>
            <SiteAverages />
          </Suspense>
        )}
        {tab === "photos" && (
          <Suspense fallback={<div className="loading">Loading photos...</div>}>
            <PhotoGallery />
          </Suspense>
        )}
        {tab === "site-report" && (
          <Suspense fallback={<div className="loading">Loading site report...</div>}>
            <SiteReport onReportTriggered={(id) => addOptimisticTask(id, "site")} />
          </Suspense>
        )}
        {tab === "round-report" && (
          <Suspense fallback={<div className="loading">Loading round report...</div>}>
            <RoundReport onReportTriggered={(id) => addOptimisticTask(id, "round")} />
          </Suspense>
        )}
        {tab === "sites" && (
          <Suspense fallback={<div className="loading">Loading sites...</div>}>
            <div className="sites-subtabs">
              <button
                className={`tab ${sitesTab === "map" ? "active" : ""}`}
                onClick={() => setSitesTab("map")}
              >
                Map
              </button>
              <button
                className={`tab ${sitesTab === "line" ? "active" : ""}`}
                onClick={() => setSitesTab("line")}
              >
                The Coln Line
              </button>
            </div>
            {sitesTab === "map" ? <SiteMap sites={sites} /> : <ColnLine darkMode={isDark} />}
          </Suspense>
        )}
      </main>
    </div>
  );
}

function ChartView({ siteFilter, dateFrom, dateTo }) {
  const [chemical, setChemical] = useState("phosphate");

  return (
    <div className="chart-section">
      <h2 className="chart-section-heading">Chemical levels over time</h2>
      <div className="chart-controls">
        <label>Chemical:</label>
        <ChemicalSelect value={chemical} onChange={setChemical} />
      </div>
      <TimeSeriesChart
        chemical={chemical}
        siteFilter={siteFilter}
        dateFrom={dateFrom}
        dateTo={dateTo}
        height={400}
      />
    </div>
  );
}
