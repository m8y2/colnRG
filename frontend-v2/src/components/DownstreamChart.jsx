import { useMemo } from 'react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceArea, ResponsiveContainer,
} from 'recharts';
import { bandZones, bandColorVar, bandGlyph, classifyBand, isBanded } from '../lib/bands.js';
import { formatReading } from '../lib/format.js';

const SOURCE_LABEL = 'Source, near Sevenhampton';
const THAMES_LABEL = 'Joins the Thames at Lechlade';

function DownstreamTooltip({ active, payload, unit, parameter, banded }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  const band = banded ? classifyBand(point.value, parameter) : null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{point.w3w}</div>
      <div className="chart-tooltip__row">
        <span className="chart-tooltip__value">{formatReading(point, unit)}</span>
      </div>
      {band && (
        <div className="chart-tooltip__row">
          <span style={{ color: bandColorVar(band) }} aria-hidden="true">{bandGlyph(band)}</span>
          <span className="chart-tooltip__key">{band} band</span>
        </div>
      )}
    </div>
  );
}

// Renders nothing for most bars — only the highest and lowest reading get
// a direct label (value + full what3words address), so the chart reads as
// a journey with two landmarks rather than 40-odd numbers stacked on an
// axis nobody can read at 320px.
function NotableLabel({ x, y, width, index, notableIndex, points, unit }) {
  if (index !== notableIndex || x === undefined) return null;
  const point = points[index];
  const cx = x + width / 2;
  return (
    <g transform={`translate(${cx}, ${y - 8})`}>
      <text textAnchor="middle" fontSize={12} fontWeight={700} fill="var(--text-primary)">
        {formatReading(point, unit)}
      </text>
      <text textAnchor="start" fontSize={10} fill="var(--text-secondary)" transform="rotate(-32 0 14)" y={16}>
        {point.w3w}
      </text>
    </g>
  );
}

/**
 * One reading per location, ordered strictly by `river_order` (source to
 * Thames) — the reader should be able to read it as a journey downstream.
 * Each bar is coloured by ITS OWN WFD band (not a value ramp); band zones
 * are shaded behind the bars too, so the two encodings reinforce each
 * other. The axis is labelled with the river's two real endpoints rather
 * than a bare 1–48, and the highest/lowest reading are directly labelled
 * with their full what3words address — a journey with landmarks, not a
 * numbered strip.
 *
 * `points`: `[{w3w, river_order, value, value_raw, qualifier, usable}]`,
 * already sorted by river_order, numeric-usable only (the caller mentions
 * written-observation locations separately — see AlongTheRiver.jsx).
 */
export default function DownstreamChart({ points, parameter }) {
  const banded = isBanded(parameter);
  const { unit } = parameter;

  const sorted = useMemo(
    () => (points || []).filter((p) => p.value !== null && p.value !== undefined),
    [points]
  );

  const dataMax = sorted.length ? Math.max(...sorted.map((p) => p.value)) : 0;
  const boundMax = banded
    ? (parameter.direction === 'higher_better' ? (parameter.bands.High ?? dataMax) : (parameter.bands.Poor ?? dataMax))
    : dataMax;
  const domainMax = Math.max(dataMax * 1.15, boundMax * 1.25, boundMax + 1, 1);
  const zones = banded ? bandZones(parameter, domainMax) : [];

  let maxIndex = -1;
  let minIndex = -1;
  sorted.forEach((p, i) => {
    if (maxIndex === -1 || p.value > sorted[maxIndex].value) maxIndex = i;
    if (minIndex === -1 || p.value < sorted[minIndex].value) minIndex = i;
  });

  const minWidth = Math.max(sorted.length * 52, 360);

  return (
    <div className="full-bleed-x">
      {/* `width: max(100%, Npx)` rather than `width:100%` on a min-width
          wrapper. Recharts' ResponsiveContainer measures its parent, and
          inside an overflow-x container a percentage width has nothing
          definite to resolve against — it measured 0 and the chart
          rendered as blank space, which is exactly how v1's bar charts
          fail. This keeps one bar per location legible and scrolls when
          there are more locations than fit. */}
      <div style={{ width: `max(100%, ${minWidth}px)` }}>
        <div style={{ width: '100%', height: 380 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sorted} margin={{ top: 32, right: 16, bottom: 8, left: 4 }} barCategoryGap="20%">
              <CartesianGrid horizontal vertical={false} stroke="var(--gridline)" />
              {zones.map((zone) => (
                <ReferenceArea
                  key={zone.band}
                  y1={zone.from}
                  y2={zone.to}
                  ifOverflow="visible"
                  fill={bandColorVar(zone.band)}
                  fillOpacity={0.1}
                  stroke="none"
                  label={{
                    value: `${bandGlyph(zone.band)} ${zone.band}`,
                    position: 'insideTopLeft',
                    fill: 'var(--text-secondary)',
                    fontSize: 12,
                    fontWeight: 600,
                    offset: 6,
                  }}
                />
              ))}
              <XAxis
                dataKey="river_order"
                stroke="var(--baseline)"
                tick={{ fill: 'var(--text-secondary)', fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: 'var(--baseline)' }}
                interval={0}
              />
              <YAxis
                domain={[0, domainMax]}
                stroke="var(--baseline)"
                tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={44}
                label={{ value: unit, angle: -90, position: 'insideLeft', fill: 'var(--text-muted)', fontSize: 12 }}
              />
              <Tooltip
                content={<DownstreamTooltip unit={unit} parameter={parameter} banded={banded} />}
                cursor={{ fill: 'var(--surface-sunken)' }}
                isAnimationActive={false}
              />
              <Bar
                dataKey="value"
                maxBarSize={24}
                radius={[4, 4, 0, 0]}
                isAnimationActive={false}
                label={(props) => {
                  if (props.index === maxIndex) {
                    return <NotableLabel {...props} notableIndex={maxIndex} points={sorted} unit={unit} />;
                  }
                  if (props.index === minIndex) {
                    return <NotableLabel {...props} notableIndex={minIndex} points={sorted} unit={unit} />;
                  }
                  return null;
                }}
              >
                {sorted.map((p) => {
                  const band = banded ? classifyBand(p.value, parameter) : null;
                  return <Cell key={p.w3w} fill={band ? bandColorVar(band) : 'var(--series-reading)'} />;
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="cluster" style={{ justifyContent: 'space-between', fontSize: 'var(--fs-sm)', color: 'var(--text-secondary)', fontWeight: 600, padding: '0 8px' }}>
          <span>↑ {SOURCE_LABEL}</span>
          <span>{THAMES_LABEL} ↓</span>
        </div>
      </div>
    </div>
  );
}
