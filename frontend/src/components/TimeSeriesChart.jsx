import { useState, useEffect } from "react";
import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  ReferenceLine,
} from "recharts";
import { getRounds } from "../api";
import { fmtShortDate } from "../utils";

const REF_LEVEL_LABELS = [
  { key: "Good", color: "#22c55e" },
  { key: "Moderate", color: "#eab308" },
  { key: "Poor", color: "#ef4444" },
];

const LABELS = {
  phosphate: { label: "Phosphate", unit: "mg/L", color: "#ef4444" },
  ammonia: { label: "Ammonia", unit: "mg/L", color: "#f59e0b" },
  nitrate: { label: "Nitrate", unit: "mg/L", color: "#3b82f6" },
  turbidity: { label: "Turbidity", unit: "NTU", color: "#8b5cf6" },
  dissolved_oxygen: { label: "Dissolved O₂", unit: "mg/L", color: "#10b981" },
  conductivity: { label: "Conductivity", unit: "µS/cm", color: "#06b6d4" },
  water_depth: { label: "Water Depth", unit: "cm", color: "#6366f1" },
};

const REF_COLORS = {
  Good: "#22c55e",
  Moderate: "#eab308",
  Poor: "#ef4444",
};

export default function TimeSeriesChart({
  chemical,
  siteFilter,
  height = 300,
}) {
  const [data, setData] = useState([]);
  const [refLevels, setRefLevels] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const params = { chemical };
    if (siteFilter) params.site = siteFilter;
    getRounds(chemical, siteFilter).then((result) => {
      if (cancelled) return;
      const chartData = result.rounds.map((r) => {
        const entry = {
          round: `R${r.round}\n${fmtShortDate(r.start)}`,
          roundNum: r.round,
          mean: r.mean,
          low: r.min,
          high: r.max,
          count: r.count,
        };
        if (r.site_readings && r.site_readings.length > 0) {
          entry.siteValue = r.site_readings[r.site_readings.length - 1].value;
        }
        return entry;
      });
      setData(chartData);
      setRefLevels(result.reference_levels);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [chemical, siteFilter]);

  const info = LABELS[chemical] || { label: chemical, unit: "", color: "#666" };
  const lineType = chemical === "nitrate" ? "stepBefore" : "monotone";

  if (loading) return <div className="loading">Loading chart...</div>;

  if (data.length === 0) {
    return (
      <div className="chart-section">
        <h2 className="chart-section-heading">{info.label} ({info.unit}) — Testing Rounds</h2>
        <p style={{ color: "#6b7280", textAlign: "center", padding: 24 }}>
          No round data available.
        </p>
      </div>
    );
  }

  return (
    <div className="chart-section">
      <h2 className="chart-section-heading">
        {info.label} ({info.unit}) — Testing Rounds
        {siteFilter && <span style={{ fontWeight: 400, fontSize: "0.85rem", color: "#6b7280" }}> — site: {siteFilter}</span>}
      </h3>
      <p style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: 4 }}>
        Each round is a cluster of &gt;10 samples taken within 4 days.
        The blue band shows the high/low range across all sites.
      </p>
      {refLevels && (
        <p style={{ fontSize: "0.75rem", color: "#6b7280", marginBottom: 8 }}>
          Dashed lines show WFD reference levels:&nbsp;
          {REF_LEVEL_LABELS.filter((r) => refLevels[r.key] != null).map((r, i) => (
            <span key={r.key}>
              {i > 0 && "  "}
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 2,
                  background: r.color,
                  verticalAlign: "middle",
                  marginRight: 3,
                }}
              />
              {r.key} ({refLevels[r.key]} {info.unit})
            </span>
          ))}
        </p>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey="round" tick={{ fontSize: 10 }} />
          <YAxis
            tick={{ fontSize: 11 }}
            label={{
              value: info.unit,
              angle: -90,
              position: "insideLeft",
              style: { fontSize: 11, fill: "#6b7280" },
            }}
          />
          <Tooltip
            formatter={(value, name) => [
              value?.toFixed?.(4) ?? value,
              { low: "Min", high: "Max", count: "Samples", siteValue: siteFilter || "Site", mean: "Mean" }[name] || name,
            ]}
          />
          <Legend />
          {refLevels &&
            Object.entries(refLevels).map(([label, val]) => (
              <ReferenceLine
                key={label}
                y={val}
                stroke={REF_COLORS[label] || "#6b7280"}
                strokeDasharray="6 4"
                strokeWidth={1.5}
                label={{
                  value: `${label} (${val})`,
                  position: "right",
                  fontSize: 10,
                  fill: REF_COLORS[label] || "#6b7280",
                }}
              />
            ))}
          {!siteFilter && (
            <Area
              type={lineType}
              dataKey="high"
              fill="#93c5fd"
              stroke="none"
              name="Max"
            />
          )}
          {!siteFilter && (
            <Area
              type={lineType}
              dataKey="low"
              fill="#ffffff"
              stroke="none"
              name="Min"
            />
          )}
          <Line
            type={lineType}
            dataKey="mean"
            stroke="#ef4444"
            strokeWidth={2}
            dot={{ r: 4, fill: "#ef4444" }}
            name="Mean"
          />
          {siteFilter && (
            <Line
              type={lineType}
              dataKey="siteValue"
              stroke="#f97316"
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={{ r: 5, fill: "#f97316" }}
              connectNulls
              name={siteFilter}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
