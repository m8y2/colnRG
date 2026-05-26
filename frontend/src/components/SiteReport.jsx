import { useState, useEffect, useCallback } from "react";
import { getSites, getAllSiteReports, getSiteReport, triggerSiteReport } from "../api";
import { fmtDate } from "../utils";
import AnimatedSelect from "./AnimatedSelect";

export default function SiteReport() {
  const [sites, setSites] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedSite, setSelectedSite] = useState("");
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(null); // { id, report_text, versions }
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [s, r] = await Promise.all([getSites(), getAllSiteReports()]);
    setSites(s);
    setAllReports(r.reports || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setGenerating(true);
    setError("");
    try {
      await triggerSiteReport(selectedSite);
      let found = false;
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const reports = await getAllSiteReports();
        const existing = reports.reports.filter((rr) => rr.site_code === selectedSite);
        if (existing.length > (allReports.filter((rr) => rr.site_code === selectedSite).length || 0)) {
          found = true;
          setAllReports(reports.reports || []);
          break;
        }
      }
      if (!found) setError("Report generation timed out");
      else setError("");
    } catch (e) {
      setError(e.message);
    }
    setGenerating(false);
  };

  const handleView = async (id, siteCode) => {
    if (expanded?.id === id) { setExpanded(null); return; }
    try {
      const report = await getSiteReport(siteCode);
      setExpanded({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
    } catch { setExpanded({ id, report_text: "Error loading report", generated_at: "", version: 0 }); }
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
              options={sites.map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }))}
              value={selectedSite}
              onChange={setSelectedSite}
            />
          </label>
          <button className="sync-btn" onClick={handleGenerate} disabled={generating || !selectedSite}>
            {generating ? "Generating..." : "Generate"}
          </button>
        </div>
      </div>

      <div className="chart-section">
        <h2 className="chart-section-heading">All Site Reports ({allReports.length})</h2>
        {allReports.length === 0 ? (
          <p style={{ color: "#6b7280", padding: 24, textAlign: "center" }}>No reports generated yet.</p>
        ) : (
          <div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Site</th>
                  <th>Version</th>
                  <th>Generated</th>
                  <th>Preview</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {allReports.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.site_code}</strong></td>
                    <td>v{r.version}</td>
                    <td>{fmtDate(r.generated_at?.slice(0, 10))}</td>
                    <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#6b7280", fontSize: "0.8rem" }}>
                      {r.preview?.slice(0, 100)}…
                    </td>
                    <td>
                      <button className="sync-btn" style={{ padding: "4px 10px", fontSize: "0.8rem" }} onClick={() => handleView(r.id, r.site_code)}>
                        {expanded?.id === r.id ? "Hide" : "View"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {expanded && (
              <div className="report-text" style={{ marginTop: 16, borderTop: "1px solid #e5e7eb", paddingTop: 16 }}>
                <p style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: 8 }}>
                  v{expanded.version} — {fmtDate(expanded.generated_at?.slice(0, 10))}
                </p>
                {expanded.report_text.split("\n").map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
