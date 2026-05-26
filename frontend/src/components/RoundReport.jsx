import { useState, useEffect, useCallback, useRef } from "react";
import { getRounds, getAllRoundReports, getRoundReport, triggerRoundReport, getReportStatus } from "../api";
import { fmtDate } from "../utils";

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

export default function RoundReport() {
  const [rounds, setRounds] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedRound, setSelectedRound] = useState("");
  const [runningTasks, setRunningTasks] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [r, reports] = await Promise.all([getRounds(), getAllRoundReports()]);
    setRounds(r.rounds || []);
    setAllReports(reports.reports || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Poll status every 2s
  useEffect(() => {
    const poll = async () => {
      try {
        const status = await getReportStatus();
        const roundTasks = (status.running || []).filter((t) => t.type === "round");
        setRunningTasks(roundTasks);
        if (generating && roundTasks.length === 0) {
          const r = await getAllRoundReports();
          setAllReports(r.reports || []);
          setGenerating(false);
          setError("");
        }
      } catch {}
    };
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [generating]);

  const handleGenerate = async () => {
    if (!selectedRound) return;
    const round = rounds.find((r) => String(r.round) === selectedRound);
    if (!round) return;
    setGenerating(true);
    setError("");
    try {
      await triggerRoundReport(`Round ${round.round}`, round.start, round.end);
    } catch (e) {
      setError(e.message);
      setGenerating(false);
    }
  };

  const handleView = async (id, roundLabel) => {
    if (expanded?.id === id) { setExpanded(null); return; }
    try {
      const report = await getRoundReport(roundLabel);
      setExpanded({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
    } catch { setExpanded({ id, report_text: "Error loading report", generated_at: "", version: 0 }); }
  };

  const anyRunning = runningTasks.length > 0;

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
          <button className="sync-btn" onClick={handleGenerate} disabled={generating || anyRunning || !selectedRound}>
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
        <h2 className="chart-section-heading">All Round Reports ({allReports.length})</h2>
        {allReports.length === 0 ? (
          <p style={{ color: "#6b7280", padding: 24, textAlign: "center" }}>No reports generated yet.</p>
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
