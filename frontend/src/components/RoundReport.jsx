import { useState, useEffect, useCallback } from "react";
import { getRounds, getAllRoundReports, getRoundReport, triggerRoundReport } from "../api";
import { fmtDate } from "../utils";

export default function RoundReport() {
  const [rounds, setRounds] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedRound, setSelectedRound] = useState("");
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [r, reports] = await Promise.all([getRounds(), getAllRoundReports()]);
    setRounds(r.rounds || []);
    setAllReports(reports.reports || []);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleGenerate = async () => {
    if (!selectedRound) return;
    const round = rounds.find((r) => String(r.round) === selectedRound);
    if (!round) return;
    setGenerating(true);
    setError("");
    try {
      await triggerRoundReport(`Round ${round.round}`, round.start, round.end);
      let found = false;
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const reports = await getAllRoundReports();
        if (reports.reports.length > allReports.length) {
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

  const handleView = async (id, roundLabel) => {
    if (expanded?.id === id) { setExpanded(null); return; }
    try {
      const report = await getRoundReport(roundLabel);
      setExpanded({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
    } catch { setExpanded({ id, report_text: "Error loading report", generated_at: "", version: 0 }); }
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
          <button className="sync-btn" onClick={handleGenerate} disabled={generating || !selectedRound}>
            {generating ? "Generating..." : "Generate"}
          </button>
        </div>
      </div>

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
