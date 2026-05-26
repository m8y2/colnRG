import { useState, useEffect, useCallback } from "react";

export default function ReportViewer({
  fetchReport,
  fetchVersions,
  triggerGenerate,
  generateArgs,
  label,
}) {
  const [report, setReport] = useState(null);
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const r = await fetchReport(selectedVersion);
      setReport(r);
    } catch (e) {
      if (e.message.includes("404")) {
        setReport(null);
      } else {
        setError(e.message);
      }
    }
    setLoading(false);
  }, [fetchReport, selectedVersion]);

  const loadVersions = useCallback(async () => {
    try {
      const v = await fetchVersions();
      setVersions(v.versions || []);
    } catch {
      setVersions([]);
    }
  }, [fetchVersions]);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError("");
    try {
      await triggerGenerate(...generateArgs);
      // poll for result
      let found = false;
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        try {
          const r = await fetchReport();
          if (r) {
            setReport(r);
            found = true;
            break;
          }
        } catch {}
      }
      if (!found) setError("Report generation timed out");
      await loadVersions();
    } catch (e) {
      setError(e.message);
    }
    setGenerating(false);
  };

  if (loading) return <div className="loading">Loading report...</div>;
  if (error) return <div className="error">{error}</div>;

  return (
    <div className="chart-section">
      <div className="report-header">
        <div className="report-version-select">
          {versions.length > 0 && (
            <select
              value={selectedVersion ?? ""}
              onChange={(e) => setSelectedVersion(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Latest (v{Math.max(...versions.map((v) => v.version))})</option>
              {versions.map((v) => (
                <option key={v.version} value={v.version}>
                  v{v.version} — {new Date(v.generated_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          )}
        </div>
        <button className="sync-btn" onClick={handleGenerate} disabled={generating}>
          {generating ? "Generating..." : `Generate ${label} Report`}
        </button>
      </div>
      {report ? (
        <div className="report-text">
          {report.report_text.split("\n").map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </div>
      ) : (
        <p style={{ color: "#6b7280", padding: 24, textAlign: "center" }}>
          No report yet. Click "Generate" to create one.
        </p>
      )}
    </div>
  );
}
