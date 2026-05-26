import { useState, useEffect, useCallback, useMemo, lazy, Suspense } from "react";
import { getStats, getSites, triggerSync, getSyncLog, clearCache } from "./api";
import StatsCards from "./components/StatsCards";
import ChemicalSelect from "./components/ChemicalSelect";
import AnimatedSelect from "./components/AnimatedSelect";
import { CHEMICALS } from "./utils";

const SiteMap = lazy(() => import("./components/SiteMap"));
const ColnLine = lazy(() => import("./components/ColnLine"));
const TimeSeriesChart = lazy(() => import("./components/TimeSeriesChart"));
const LocationSeries = lazy(() => import("./components/LocationSeries"));
const SiteAverages = lazy(() => import("./components/SiteAverages"));
const DataTable = lazy(() => import("./components/DataTable"));

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
          <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>
            Water quality monitoring on the River Coln
          </p>
        </div>
        <div className="header-sub">
          <span className="last-sync">Last sync: {lastSync}</span>
          <button className="sync-btn" onClick={handleSync} disabled={syncing}>
            {syncing ? "Syncing..." : "Sync Now"}
          </button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

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
          Time Series
        </button>
        <button
          className={`tab ${tab === "site-averages" ? "active" : ""}`}
          onClick={() => switchTab("site-averages")}
        >
          Site Averages
        </button>
        <button
          className={`tab ${tab === "location-series" ? "active" : ""}`}
          onClick={() => switchTab("location-series")}
        >
          Location Series
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
      </div>

      <div className="tab-content" key={tab}>
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
            <OverviewChart
              chemical={overviewChemical}
              onSwitch={setOverviewChemical}
            />
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
            {sitesTab === "map" ? <SiteMap sites={sites} /> : <ColnLine />}
          </Suspense>
        )}
      </div>
    </div>
  );
}

function OverviewChart({ chemical, onSwitch }) {
  const idx = CHEMICALS.findIndex((c) => c.value === chemical);
  const cycle = () => {
    const next = (idx + 1) % CHEMICALS.length;
    onSwitch(CHEMICALS[next].value);
  };

  return (
    <div className="chart-section" style={{ cursor: "pointer" }} onClick={cycle} title="Click to cycle chemicals">
      <TimeSeriesChart chemical={chemical} height={250} />
      <p style={{ fontSize: "0.7rem", color: "#9ca3af", textAlign: "center", marginTop: 4 }}>
        Click to cycle through chemicals
      </p>
    </div>
  );
}

function ChartView({ siteFilter, dateFrom, dateTo }) {
  const [chemical, setChemical] = useState("phosphate");

  return (
    <div className="chart-section">
      <h3>Chemical Time Series</h3>
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
