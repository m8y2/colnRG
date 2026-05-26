import { useState, useEffect, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { getLocationSeries } from "../api";
import ChemicalSelect from "./ChemicalSelect";
import AnimatedSelect from "./AnimatedSelect";
import { fmtShortDate } from "../utils";

const REF_COLORS = { Good: "#22c55e", Moderate: "#eab308", Poor: "#ef4444" };

export default function LocationSeries({ sites }) {
  const [chemical, setChemical] = useState("phosphate");
  const [roundFilter, setRoundFilter] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getLocationSeries(chemical).then((result) => {
      if (cancelled) return;
      setData(result);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [chemical]);

  const currentRound = useMemo(
    () => roundFilter || (data?.rounds?.[data.rounds.length - 1]?.round) || null,
    [roundFilter, data]
  );
  const roundOptions = useMemo(
    () => (data?.rounds || []).map((r) => ({
      value: r.round,
      label: `Round ${r.round} (${fmtShortDate(r.start)}–${fmtShortDate(r.end)})`,
    })),
    [data]
  );

  const roundData = useMemo(
    () => data?.rounds?.find((r) => r.round === currentRound),
    [data, currentRound]
  );
  const chartData = useMemo(
    () => (roundData?.sites || []).map((s) => ({
      site: s.code,
      value: s.mean,
      count: s.count,
      name: s.name,
    })),
    [roundData]
  );

  const refLevels = data?.reference_levels;

  if (loading) return <div className="loading">Loading location series...</div>;

  return (
    <div className="chart-section">
      <h2 className="chart-section-heading">Location Series — {data?.chemical}</h2>
      <div className="chart-controls">
        <label>Chemical:</label>
        <ChemicalSelect value={chemical} onChange={setChemical} />
        <label>Round:</label>
        <AnimatedSelect
          options={roundOptions}
          value={currentRound}
          onChange={setRoundFilter}
        />
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
              formatter={(v, n, props) => [v?.toFixed?.(4) ?? v, props.payload.name || n]}
              labelFormatter={(label) => `Site: ${label}`}
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
            <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} name={data?.chemical} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <p style={{ color: "#4b5563", textAlign: "center", padding: 24 }}>
          No data for this round.
        </p>
      )}
    </div>
  );
}
