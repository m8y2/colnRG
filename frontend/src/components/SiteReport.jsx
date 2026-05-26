import { useState, useEffect, useCallback, useRef } from "react";
import { getSites, getAllSiteReports, getSiteReport, triggerSiteReport, getReportStatus } from "../api";
import { fmtDate } from "../utils";
import AnimatedSelect from "./AnimatedSelect";

function ProgressCard({ task }) {
  const pct = task.progress < 0 ? 0 : task.progress;
  const barWidth = task.progress < 0 ? 100 : pct;
  const isError = task.progress < 0;
  const isComplete = task.progress >= 100;
  const barColor = isError ? "#dc2626" : isComplete ? "#16a34a" : "#1a56db";
  return (
    <div className="report-progress" style={{ marginBottom: 8, padding: "8px 12px", borderRadius: 6, background: isError ? "#fef2f2" : "#f0f4f8" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: "0.85rem" }}>
        <span><strong>{task.type === "site" ? "Site" : "Round"}:</strong> {task.identifier}</span>
        <span style={{ color: isError ? "#dc2626" : "#374151" }}>
          {isError ? "Failed" : isComplete ? "Complete" : `${pct}%`}
        </span>
      </div>
      {!isComplete && (
        <div style={{ height: 6, background: "#e5e7eb", borderRadius: 3, overflow: "hidden", marginBottom: 4 }}>
          <div style={{ width: `${barWidth}%`, height: "100%", background: barColor, borderRadius: 3, transition: "width 0.5s ease" }} />
        </div>
      )}
      <div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{task.message}</div>
    </div>
  );
}

export default function SiteReport() {
  const [sites, setSites] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedSite, setSelectedSite] = useState("");
  const [runningTasks, setRunningTasks] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState("");
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    const [s, r] = await Promise.all([getSites(), getAllSiteReports()]);
    setSites(s);
    setAllReports(r.reports || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll status every 2s
  useEffect(() => {
    const poll = async () => {
      try {
        const status = await getReportStatus();
        const siteTasks = (status.running || []).filter((t) => t.type === "site");
        setRunningTasks(siteTasks);
        // Refresh reports when no tasks remain (just finished)
        if (generating && siteTasks.length === 0) {
          const r = await getAllSiteReports();
          setAllReports(r.reports || []);
          setGenerating(false);
          setError("");
        }
      } catch {}
    };
    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => clearInterval(pollRef.current);
  }, [generating]);

  const handleGenerate = async () => {
    if (!selectedSite) return;
    setGenerating(true);
    setError("");
    try {
      await triggerSiteReport(selectedSite);
    } catch (e) {
      setError(e.message);
      setGenerating(false);
    }
  };

  const handleView = async (id, siteCode) => {
    if (expanded?.id === id) { setExpanded(null); return; }
    try {
      const report = await getSiteReport(siteCode);
      setExpanded({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
    } catch { setExpanded({ id, report_text: "Error loading report", generated_at: "", version: 0 }); }
  };

  const runningHere = runningTasks.find((t) => t.identifier === selectedSite);
  const anyRunning = runningTasks.length > 0;

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
          <button className="sync-btn" onClick={handleGenerate} disabled={generating || anyRunning || !selectedSite}>
            {generating ? "Starting..." : "Generate"}
          </button>
        </div>
      </div>

      {runningTasks.length > 0 && (
        <div className="chart-section">
          <h2 className="chart-section-heading">Generating ({runningTasks.length} running)</h2>
          {runningTasks.map((t) => (
            <ProgressCard key={t.id} task={t} />
          ))}
        </div>
      )}

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
