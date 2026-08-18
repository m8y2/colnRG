import { LineChart, Line } from 'recharts';

/**
 * A small decorative trend line for a parameter card. It is deliberately
 * `aria-hidden` — the words next to it ("Getting better over the last
 * year") carry the same meaning already (see spec: "sparkline each, trend
 * in words"), so the chart doesn't need its own screen-reader description.
 * Handles the sparse cases directly (no data / a single reading) rather
 * than rendering an empty or misleading line.
 */
export default function Sparkline({ data, valueKey = 'value', width = 96, height = 32 }) {
  const points = (data || []).filter((d) => d[valueKey] !== null && d[valueKey] !== undefined);

  if (points.length === 0) {
    return <span className="text-muted text-sm">No readings yet</span>;
  }
  if (points.length === 1) {
    return <span className="text-muted text-sm">Only one reading so far</span>;
  }

  return (
    <LineChart width={width} height={height} data={points} margin={{ top: 4, right: 4, bottom: 4, left: 4 }} aria-hidden="true">
      <Line
        type="monotone"
        dataKey={valueKey}
        stroke="var(--series-reading)"
        strokeWidth={2}
        dot={false}
        isAnimationActive={false}
      />
    </LineChart>
  );
}
