import { useMemo, useId } from 'react';
import {
  ComposedChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceArea, ResponsiveContainer,
} from 'recharts';
import { bandZones, bandColorVar, bandGlyph, classifyBand, isBanded } from '../lib/bands.js';
import { formatDate, formatReading, qualifierNote } from '../lib/format.js';

// A dot for every usable numeric reading, ring in the surface colour so it
// reads cleanly against the line and the band zones behind it. The most
// recent reading also gets a direct value label (selective labelling, not
// one on every point).
function ReadingDot({ cx, cy, payload, isLast, unit }) {
  if (cx === undefined || cy === undefined) return null;
  return (
    <g>
      <circle cx={cx} cy={cy} r={5} fill="var(--series-reading)" stroke="var(--surface-card)" strokeWidth={2} />
      {isLast && (
        <text x={cx} y={cy - 12} textAnchor="middle" fontSize={13} fontWeight={700} fill="var(--text-primary)">
          {formatReading(payload, unit)}
        </text>
      )}
    </g>
  );
}

function ChartTooltip({ active, payload, label, unit, parameter, banded }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0]?.payload;
  if (!point || point.value === null || point.value === undefined) return null;
  const band = banded ? classifyBand(point.value, parameter) : null;
  const note = qualifierNote(point.qualifier);
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{formatDate(label)}</div>
      <div className="chart-tooltip__row">
        <span className="chart-tooltip__value">{formatReading(point, unit)}</span>
      </div>
      {note && <div className="chart-tooltip__row"><span className="chart-tooltip__key">{note}</span></div>}
      {band && (
        <div className="chart-tooltip__row">
          <span style={{ color: bandColorVar(band) }} aria-hidden="true">{bandGlyph(band)}</span>
          <span className="chart-tooltip__key">{band} band</span>
        </div>
      )}
    </div>
  );
}

/**
 * A single-location, single-parameter reading over time, with WFD band
 * zones shaded into the background (where the parameter is banded) so a
 * reader can see which zone a reading falls in without cross-referencing
 * an axis.
 *
 * `parameter` is the object from GET /api/v2/parameters. `points` is every
 * reading from GET /series (`[{date, value, value_raw, qualifier,
 * usable}]`, oldest first) — numeric and written-observation readings
 * mixed together; this component splits them itself. A written
 * observation ("cloudy") is never plotted against the value axis — it
 * gets its own strip below the chart with no numeric scale at all, so it
 * is not possible to misread a magnitude off it.
 */
export default function TimeSeriesChart({ points, parameter }) {
  const gradientId = useId();
  const banded = isBanded(parameter);
  const { unit } = parameter;

  const numericPoints = useMemo(
    () => (points || [])
      .filter((d) => d.value !== null && d.value !== undefined)
      .map((d) => ({ ...d, t: new Date(`${d.date}T00:00:00`).getTime() }))
      .sort((a, b) => a.t - b.t),
    [points]
  );

  const writtenObservations = useMemo(
    () => (points || [])
      .filter((d) => (d.value === null || d.value === undefined) && d.value_raw)
      .map((d) => ({ ...d, t: new Date(`${d.date}T00:00:00`).getTime() }))
      .sort((a, b) => a.t - b.t),
    [points]
  );

  const hasEnoughForChart = numericPoints.length >= 2;

  const dataMax = numericPoints.length ? Math.max(...numericPoints.map((p) => p.value)) : 0;
  const boundMax = banded
    ? (parameter.direction === 'higher_better'
      ? (parameter.bands.Excellent ?? dataMax)
      // The last closed threshold is the top of the graded scale for
      // lower-better parameters; the worst band is open-ended above it.
      : (Math.max(...Object.values(parameter.bands)) ?? dataMax))
    : dataMax;
  const domainMax = Math.max(dataMax * 1.15, boundMax * 1.25, boundMax + 1, 1);
  const zones = banded ? bandZones(parameter, domainMax) : [];
  const domainMin = numericPoints.length ? Math.min(0, ...numericPoints.map((p) => p.value)) : 0;

  const allT = [...numericPoints, ...writtenObservations].map((p) => p.t);
  const tMin = allT.length ? Math.min(...allT) : 0;
  const tMax = allT.length ? Math.max(...allT) : 0;

  if (numericPoints.length === 0 && writtenObservations.length === 0) {
    return <p className="text-secondary">No readings for this yet.</p>;
  }

  if (numericPoints.length === 1 && writtenObservations.length === 0) {
    const only = numericPoints[0];
    const band = banded ? classifyBand(only.value, parameter) : null;
    return (
      <p className="text-secondary">
        There is only one reading so far, not enough to draw a chart. It was{' '}
        <strong>{formatReading(only, unit)}</strong> on {formatDate(only.date)}
        {band ? <> ({band} band)</> : null}.
      </p>
    );
  }

  return (
    <div>
      {hasEnoughForChart && (
        <div style={{ width: '100%', height: 340 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={numericPoints} margin={{ top: 16, right: 24, bottom: 8, left: 4 }}>
              <defs>
                <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--series-reading)" stopOpacity={0.12} />
                  <stop offset="100%" stopColor="var(--series-reading)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid horizontal vertical={false} stroke="var(--gridline)" strokeDasharray="0" />
              {zones.map((zone) => (
                <ReferenceArea
                  key={zone.band}
                  y1={zone.from}
                  y2={zone.to}
                  x1={tMin}
                  x2={tMax}
                  ifOverflow="visible"
                  fill={bandColorVar(zone.band)}
                  fillOpacity={0.12}
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
                dataKey="t"
                type="number"
                domain={[tMin, tMax]}
                tickFormatter={(t) => formatDate(new Date(t).toISOString().slice(0, 10))}
                stroke="var(--baseline)"
                tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
                tickLine={false}
                axisLine={{ stroke: 'var(--baseline)' }}
                minTickGap={40}
              />
              <YAxis
                domain={[domainMin, domainMax]}
                stroke="var(--baseline)"
                tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}
                tickLine={false}
                axisLine={false}
                width={44}
                label={{ value: unit, angle: -90, position: 'insideLeft', fill: 'var(--text-muted)', fontSize: 12 }}
              />
              <Tooltip
                content={<ChartTooltip unit={unit} parameter={parameter} banded={banded} />}
                cursor={{ stroke: 'var(--text-muted)', strokeWidth: 1 }}
                isAnimationActive={false}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke="var(--series-reading)"
                strokeWidth={2}
                fill={`url(#${gradientId})`}
                dot={(props) => (
                  <ReadingDot key={props.index} {...props} unit={unit} isLast={props.index === numericPoints.length - 1} />
                )}
                activeDot={{ r: 6, fill: 'var(--series-reading)', stroke: 'var(--surface-card)', strokeWidth: 2 }}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {!hasEnoughForChart && numericPoints.length > 0 && (
        <p className="text-secondary">
          Only {numericPoints.length} number{numericPoints.length === 1 ? '' : 's'} recorded here, not enough to draw a
          line yet. {numericPoints.map((p) => `${formatReading(p, unit)} (${formatDate(p.date)})`).join('; ')}.
        </p>
      )}

      {writtenObservations.length > 0 && (
        <>
          <p className="observation-strip__caption">
            Some visits recorded a written observation instead of a number (like &ldquo;cloudy&rdquo;). Those are marked
            below by date, not plotted as values, because they were never converted into a number.
          </p>
          <div className="observation-strip">
            {writtenObservations.map((obs) => {
              const pct = tMax > tMin ? ((obs.t - tMin) / (tMax - tMin)) * 100 : 50;
              return (
                <button
                  key={`${obs.date}-${obs.value_raw}`}
                  type="button"
                  className="observation-strip__mark"
                  style={{ left: `${pct}%` }}
                  title={`${formatDate(obs.date)}: recorded as "${obs.value_raw}"`}
                >
                  <span aria-hidden="true">✎</span>
                  <span className="visually-hidden">
                    {formatDate(obs.date)}: recorded as &ldquo;{obs.value_raw}&rdquo;
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
