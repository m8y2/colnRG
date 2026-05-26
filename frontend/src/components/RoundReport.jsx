import { useState, useEffect, useRef } from "react";
import { getRounds, getAllRoundReports, getRoundReport, triggerRoundReport, getReportStatus } from "../api";
import { fmtDate } from "../utils";

function ProgressCard({ task }) {
  const pct = task.progress < 0 ? 0 : task.progress;
  const barWidth = task.progress < 0 ? 100 : pct;
  const isError = task.progress < 0;
  const barColor = isError ? "var(--error)" : "var(--primary)";
  return (
    <div className="report-progress" style={{ marginBottom: 8, padding: "8px 12px", borderRadius: 6, background: isError ? "var(--error-bg)" : "var(--bg)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: "0.85rem" }}>
        <span><strong>{task.identifier}</strong></span>
        <span style={{ color: isError ? "var(--error-text)" : "var(--text-secondary)" }}>
          {isError ? "Failed" : `${pct}%`}
        </span>
      </div>
      <div style={{ height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden", marginBottom: 4 }}>
        <div style={{ width: `${barWidth}%`, height: "100%", background: barColor, borderRadius: 3, transition: "width 0.5s ease" }} />
      </div>
      <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{task.message}</div>
    </div>
  );
}

export default function RoundReport() {
  const [rounds, setRounds] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedRound, setSelectedRound] = useState("");
  const [runningTasks, setRunningTasks] = useState([]);
  const [viewing, setViewing] = useState(null);
  const [error, setError] = useState("");
  const prevCount = useRef(0);

  useEffect(() => {
    getRounds().then((data) => {
      const rs = data.rounds || [];
      setRounds(rs);
    });
  }, []);

  // Poll status + refresh reports on completion
  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getReportStatus();
        if (cancelled) return;
        const roundTasks = (status.running || []).filter((t) => t.type === "round");
        setRunningTasks(roundTasks);
        if (prevCount.current > 0 && roundTasks.length === 0) {
          const r = await getAllRoundReports();
          if (!cancelled) setAllReports(r.reports || []);
        }
        prevCount.current = roundTasks.length;
      } catch {}
    };
    getAllRoundReports().then((r) => { if (!cancelled) setAllReports(r.reports || []); });
    tick();
    const id = setInterval(tick, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const handleGenerate = async () => {
    if (!selectedRound) return;
    const round = rounds.find((r) => String(r.round) === selectedRound);
    if (!round) return;
    setError("");
    try {
      await triggerRoundReport(`Round ${round.round}`, round.start, round.end);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleView = async (id, roundLabel) => {
    if (viewing?.id === id) { setViewing(null); return; }
    try {
      const report = await getRoundReport(roundLabel);
      setViewing({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
    } catch { setViewing({ id, report_text: "Error loading report", generated_at: "", version: 0 }); }
  };

  return (
    <div>
      {error && <div className="error">{error}</div>}

      <div className="chart-section">
        <h2 className="chart-section-heading">Generate New Round Report</h2>
        <div className="filters">
          <label>
            Round:
            <select value={selectedRound} onChange={(e) => setSelectedRound(e.target.value)}>
              <option value="">Select round...</option>
              {rounds.map((r) => (
                <option key={r.round} value={r.round}>
                  Round {r.round} — {r.start} to {r.end}
                </option>
              ))}
            </select>
          </label>
          <button className="sync-btn" onClick={handleGenerate} disabled={runningTasks.length > 0 || !selectedRound}>
            Generate
          </button>
        </div>
      </div>

      {runningTasks.length > 0 && (
        <div className="chart-section">
          <h2 className="chart-section-heading" style={{ color: "var(--text-primary)" }}>{runningTasks.length > 0 ? `Generating (${runningTasks.length} running)` : "No reports in progress"
          {runningTasks.map((t) => (
            <ProgressCard key={t.id} task={t} />
          ))}
        </div>
      )}

      <div className="chart-section">
        <h2 className="chart-section-heading">All Round Reports ({allReports.length})</h2>
        {allReports.length === 0 ? (
          <p style={{ color: "var(--text-muted)", padding: 24, textAlign: "center" }}>No reports generated yet.</p>
        ) : (
          <div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Round</th>
                  <th>Version</th>
                  <th>Generated</th>
                  <th>Preview</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {allReports.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.round_label}</strong></td>
                    <td>v{r.version}</td>
                    <td>{fmtDate(r.generated_at?.slice(0, 10))}</td>
                    <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "#6b7280", fontSize: "0.8rem" }}>
                      {r.preview?.slice(0, 100)}…
                    </td>
                    <td>
                      <button className="sync-btn" style={{ padding: "4px 10px", fontSize: "0.8rem" }} onClick={() => handleView(r.id, r.round_label)}>
                        {viewing?.id === r.id ? "Hide" : "View"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {viewing && (
              <div className="report-text" style={{ marginTop: 16, borderTop: "1px solid #e5e7eb", paddingTop: 16 }}>
                <p style={{ fontSize: "0.8rem", color: "#6b7280", marginBottom: 8 }}>
                  v{viewing.version} — {fmtDate(viewing.generated_at?.slice(0, 10))}
                </p>
                {viewing.report_text.split("\n").map((p, i) => (
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
