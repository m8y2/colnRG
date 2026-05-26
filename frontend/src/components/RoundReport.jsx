import { useState, useEffect } from "react";
import { getRounds } from "../api";
import ReportViewer from "./ReportViewer";
import {
  getRoundReport,
  getRoundReportVersions,
  triggerRoundReport,
} from "../api";

export default function RoundReport() {
  const [rounds, setRounds] = useState([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    getRounds().then((data) => {
      const rs = data.rounds || [];
      setRounds(rs);
      if (rs.length > 0) setSelected(String(rs[rs.length - 1].round));
    });
  }, []);

  const current = rounds.find((r) => String(r.round) === selected);
  if (!current && rounds.length === 0) return <div className="loading">Loading rounds...</div>;
  if (!current) return <div className="loading">Select a round...</div>;

  return (
    <div>
      <div className="filters">
        <label>
          Round:
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {rounds.map((r) => (
              <option key={r.round} value={r.round}>
                Round {r.round} — {r.start} to {r.end}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ReportViewer
        key={selected}
        fetchReport={(version) => getRoundReport(`Round ${current.round}`, version)}
        fetchVersions={() => getRoundReportVersions(`Round ${current.round}`)}
        triggerGenerate={() => triggerRoundReport(`Round ${current.round}`, current.start, current.end)}
        generateArgs={[`Round ${current.round}`, current.start, current.end]}
        label="Round"
      />
    </div>
  );
}
