import { useState, useEffect, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Cell,
} from "recharts";
import { getSiteAverages } from "../api";
import ChemicalSelect from "./ChemicalSelect";

const REF_COLORS = { Good: "#22c55e", Moderate: "#eab308", Poor: "#ef4444" };

export default function SiteAverages() {
  const [chemical, setChemical] = useState("phosphate");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSiteAverages(chemical).then((result) => {
      if (cancelled) return;
      setData(result);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [chemical]);

  const refLevels = data?.reference_levels;

  const orangeThreshold = refLevels?.Moderate ?? null;

  const chartData = useMemo(
    () => (data?.sites || []).map((s) => ({
      site: s.code,
      value: s.mean,
      name: s.name,
      count: s.count,
      overThreshold: orangeThreshold != null && s.mean > orangeThreshold,
    })),
    [data, orangeThreshold]
  );

  if (loading) return <div className="loading">Loading site averages...</div>;

  return (
    <div className="chart-section">
      <h2 className="chart-section-heading">Long-term Site Averages — {data?.chemical} ({data?.unit})</h2>
      <p style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: 12 }}>
        Mean value per site across all testing rounds.
        {refLevels && " Bars are highlighted in orange when the average exceeds the Moderate reference threshold."}
      </p>
      <div className="chart-controls">
        <label>Chemical:</label>
        <ChemicalSelect value={chemical} onChange={setChemical} />
      </div>
      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={500}>
          <BarChart data={chartData} margin={{ bottom: 60 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="site"
              tick={{ fontSize: 10 }}
              angle={-40}
              textAnchor="end"
              height={60}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              label={{
                value: data?.unit || "",
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: "#4b5563" },
              }}
            />
            <Tooltip
              formatter={(v, n, props) => [v?.toFixed?.(4) ?? v, "Mean"]}
              labelFormatter={(label) => label}
            />
            {refLevels &&
              Object.entries(refLevels).map(([label, val]) => (
                <ReferenceLine
                  key={label}
                  y={val}
                  stroke={REF_COLORS[label] || "#4b5563"}
                  strokeDasharray="6 4"
                  strokeWidth={1.5}
                  label={{
                    value: `${label} (${val})`,
                    position: "right",
                    fontSize: 10,
                    fill: REF_COLORS[label] || "#4b5563",
                  }}
                />
              ))}
            <Bar dataKey="value" radius={[4, 4, 0, 0]} name="Mean">
              {chartData.map((entry) => (
                <Cell
                  key={entry.site}
                  fill={entry.overThreshold ? "#f97316" : "#3b82f6"}
                  fillOpacity={entry.overThreshold ? 0.85 : 0.7}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p style={{ color: "#4b5563", textAlign: "center", padding: 24 }}>
          No data available.
        </p>
      )}
    </div>
  );
}
