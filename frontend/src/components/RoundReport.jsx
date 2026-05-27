import { useState, useEffect, useMemo, useRef } from "react";
import { getRounds, getAllRoundReports, getRoundReport, getRoundReportVersions, triggerRoundReport, getReportStatus } from "../api";
import { fmtDate } from "../utils";
import AnimatedSelect from "./AnimatedSelect";

function VersionSelector({ versions, selectedVersion, onSelect }) {
  if (!versions || versions.length < 2) return null;
  const sorted = [...versions].sort((a, b) => a.version - b.version);
  const opts = sorted.map((v) => ({ value: String(v.version), label: `v${v.version} — ${fmtDate(v.generated_at?.slice(0, 10))}` }));
  return (
    <AnimatedSelect options={opts} value={String(selectedVersion)} onChange={(v) => onSelect(Number(v))} className="version-select" />
  );
}

export default function RoundReport({ onReportTriggered }) {
  const [rounds, setRounds] = useState([]);
  const [allReports, setAllReports] = useState([]);
  const [selectedRound, setSelectedRound] = useState("");
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
      const key = r.round_label;
      if (!map[key] || r.version > map[key].version) {
        map[key] = r;
      }
    }
    return Object.values(map).sort((a, b) => (a.round_start || "").localeCompare(b.round_start || ""));
  }, [allReports]);

  useEffect(() => {
    getRounds().then((data) => {
      const rs = data.rounds || [];
      setRounds(rs);
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await getReportStatus();
        if (cancelled) return;
        const roundTasks = (status.running || []).filter((t) => t.type === "round");
        if (roundTasks.length === 0 && prevCount.current > 0) {
          const r = await getAllRoundReports();
          if (!cancelled) setAllReports(r.reports || []);
        }
        if (roundTasks.length === 0 && genState.current.active && (prevCount.current > 0 || Date.now() - genState.current.ts > 30000)) {
          setGenerating(false);
          genState.current = { active: false, ts: null };
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
    setGenerating(true);
    genState.current = { active: true, ts: Date.now() };
    const label = `Round ${round.round}`;
    if (onReportTriggered) onReportTriggered(label);
    try {
      await triggerRoundReport(label, round.start, round.end);
    } catch (e) {
      setError(e.message);
      setGenerating(false);
      genState.current = { active: false, ts: null };
    }
  };

  const handleView = async (id, roundLabel) => {
    if (viewing?.id === id) {
      setViewing(null);
      setVersions(null);
      return;
    }
    try {
      const [report, vers] = await Promise.all([
        getRoundReport(roundLabel),
        getRoundReportVersions(roundLabel),
      ]);
      setViewing({ id, report_text: report.report_text, generated_at: report.generated_at, version: report.version });
      setVersions(vers.versions || []);
      setSelectedVersion(report.version);
    } catch {
      setViewing({ id, report_text: "Error loading report", generated_at: "", version: 0 });
    }
  };

  const handleVersionChange = async (roundLabel, version) => {
    setSelectedVersion(version);
    try {
      const report = await getRoundReport(roundLabel, version);
      setViewing((prev) => ({ ...prev, report_text: report.report_text, generated_at: report.generated_at, version: report.version }));
    } catch {
      setViewing((prev) => ({ ...prev, report_text: "Error loading report" }));
    }
  };

  return (
    <div>
      {error && <div className="error">{error}</div>}

      <div className="chart-section">
        <h2 className="chart-section-heading">Generate New Round Report</h2>
        <div className="filters">
          <label>
            Round:
            <AnimatedSelect
              options={[
                { value: "", label: "Select round..." },
                ...rounds.map((r) => ({ value: String(r.round), label: `Round ${r.round} — ${r.start} to ${r.end}` })),
              ]}
              value={selectedRound}
              onChange={setSelectedRound}
            />
          </label>
          <button className="sync-btn" onClick={handleGenerate} disabled={generating || !selectedRound}>
            Generate
          </button>
        </div>
      </div>

      <div className="chart-section">
        <h2 className="chart-section-heading">All Round Reports ({latestReports.length})</h2>
        {latestReports.length === 0 ? (
          <p style={{ color: "var(--text-muted)", padding: 24, textAlign: "center" }}>No reports generated yet.</p>
        ) : (
          <div>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Round</th>
                  <th>Latest</th>
                  <th>Generated</th>
                  <th>Preview</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {latestReports.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.round_label}</strong></td>
                    <td>v{r.version}</td>
                    <td>{fmtDate(r.generated_at?.slice(0, 10))}</td>
                    <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)", fontSize: "0.8rem" }}>
                      {r.preview?.slice(0, 100)}…
                    </td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <button className="sync-btn" style={{ padding: "4px 10px", fontSize: "0.8rem" }} onClick={() => handleView(r.id, r.round_label)}>
                          {viewing?.id === r.id ? "▲" : "▼"}
                        </button>
                        {viewing?.id === r.id && (
                          <VersionSelector
                            versions={versions}
                            selectedVersion={selectedVersion}
                            onSelect={(v) => handleVersionChange(r.round_label, v)}
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
