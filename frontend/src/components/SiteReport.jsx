import { useState, useEffect, useMemo, useRef } from "react";
import { getSites, getAllSiteReports, getSiteReport, getSiteReportVersions, triggerSiteReport, getReportStatus } from "../api";
import { fmtDate } from "../utils";
import AnimatedSelect from "./AnimatedSelect";

function VersionSelector({ versions, selectedVersion, onSelect }) {
  if (!versions || versions.length < 2) return null;
  const sorted = [...versions].sort((a, b) => a.version - b.version);
  return (
    <select className="version-select" value={selectedVersion} onChange={(e) => onSelect(Number(e.target.value))}>
      {sorted.map((v) => (
        <option key={v.version} value={v.version}>v{v.version} — {fmtDate(v.generated_at?.slice(0, 10))}</option>
      ))}
    </select>
  );
}

export default function SiteReport({ onReportTriggered }) {
  const [sites, setSites] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedSite, setSelectedSite] = useState("");
  const [generating, setGenerating] = useState(false);
  const [viewing, setViewing] = useState(null);
  const [versions, setVersions] = useState(null);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [error, setError] = useState("");
  const prevCount = useRef(0);
  const genState = useRef({ active: false, ts: null });

  const latestReports = useMemo(() => {
    const map = {};
    for (const r of allReports) {
      const key = r.site_code;
      if (!map[key] || r.version > map[key].version) {
        map[key] = r;
      }
    }
    return Object.values(map).sort((a, b) => (b.generated_at || "").localeCompare(a.generated_at || ""));
  }, [allReports]);

  useEffect(() => {
    getSites().then((s) => setSites(s));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getReportStatus();
        if (cancelled) return;
        const siteTasks = (status.running || []).filter((t) => t.type === "site");
        if (siteTasks.length === 0 && prevCount.current > 0) {
          const r = await getAllSiteReports();
          if (!cancelled) setAllReports(r.reports || []);
        }
        if (siteTasks.length === 0 && genState.current.active && (prevCount.current > 0 || Date.now() - genState.current.ts > 30000)) {
          setGenerating(false);
          genState.current = { active: false, ts: null };
        }
        prevCount.current = siteTasks.length;
      } catch {}
    };
    getAllSiteReports().then((r) => { if (!cancelled) setAllReports(r.reports || []); });
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setError("");
    setGenerating(true);
    genState.current = { active: true, ts: Date.now() };
    if (onReportTriggered) onReportTriggered(selectedSite);
    try {
      await triggerSiteReport(selectedSite);
    } catch (e) {
      setError(e.message);
      setGenerating(false);
      genState.current = { active: false, ts: null };
    }
  };

  const handleView = async (id, siteCode) => {
    if (viewing?.id === id) {
      setViewing(null);
      setVersions(null);
      return;
    }
    try {
      const [report, vers] = await Promise.all([
        getSiteReport(siteCode),
        getSiteReportVersions(siteCode),
      ]);
      setViewing({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
      setVersions(vers.versions || []);
      setSelectedVersion(report.version);
    } catch {
      setViewing({ id, report_text: "Error loading report", generated_at: "", version: 0 });
    }
  };

  const handleVersionChange = async (siteCode, version) => {
    setSelectedVersion(version);
    try {
      const report = await getSiteReport(siteCode, version);
      setViewing((prev) => ({ ...prev, report_text: report.report_text, generated_at: report.generated_at, version: report.version }));
    } catch {
      setViewing((prev) => ({ ...prev, report_text: "Error loading report" }));
    }
  };

  return (
    <div>
      {error && <div className="error">{error}</div>}

      <div className="chart-section">
        <h2 className="chart-section-heading">Generate New Site Report</h2>
        <div className="filters">
          <label>
            Site:
            <AnimatedSelect
              options={sites.map((s) => ({ value: s.code, label: s.code }))}
              value={selectedSite}
              onChange={setSelectedSite}
            />
          </label>
          <button className="sync-btn" onClick={handleGenerate} disabled={!selectedSite}>
            Generate
          </button>
        </div>
      </div>

      <div className="chart-section">
        <h2 className="chart-section-heading">All Site Reports ({latestReports.length})</h2>
        {latestReports.length === 0 ? (
          <p style={{ color: "var(--text-muted)", padding: 24, textAlign: "center" }}>No reports generated yet.</p>
        ) : (
          <div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Site</th>
                  <th>Latest</th>
                  <th>Generated</th>
                  <th>Preview</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {latestReports.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.site_code}</strong></td>
                    <td>v{r.version}</td>
                    <td>{fmtDate(r.generated_at?.slice(0, 10))}</td>
                    <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: "0.8rem" }}>
                      {r.preview?.slice(0, 100)}…
                    </td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <button className="sync-btn" style={{ padding: "4px 10px", fontSize: "0.8rem" }} onClick={() => handleView(r.id, r.site_code)}>
                          {viewing?.id === r.id ? "▲" : "▼"}
                        </button>
                        {viewing?.id === r.id && (
                          <VersionSelector
                            versions={versions}
                            selectedVersion={selectedVersion}
                            onSelect={(v) => handleVersionChange(r.site_code, v)}
                          />
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {latestReports.map((r) => viewing?.id === r.id && (
                  <tr key={`expanded-${r.id}`}>
                    <td colSpan="5" style={{ padding: "12px 16px", whiteSpace: "normal" }}>
                      <div className="report-text">
                        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: 8 }}>
                          v{viewing.version} — {fmtDate(viewing.generated_at?.slice(0, 10))}
                        </p>
                        {viewing.report_text.split("\n").map((p, i) => (
                          <p key={i}>{p}</p>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
