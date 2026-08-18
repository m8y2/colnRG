import { useMemo } from 'react';
import {
  ComposedChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts';
import { categoryScaleFor, categoryColor } from '../lib/categories.js';
import { formatDate } from '../lib/format.js';

/**
 * Ordinal (word-scale) readings — see V2_SPEC_ADDENDUM_2.md Rule B. These
 * are never averaged into a number and never WFD-band-classified: a
 * verbal "Clear"/"Cloudy" judgement is a different instrument from a
 * meter reading, so this file never computes or displays a mean rank —
 * only counts and the single most common category (a real, observed
 * category, never a blend of two).
 */

// The category actually seen most often — a real observed value, never an
// average. Ties break towards the clearer/lower-rank category.
export function modalCategory(points, categories) {
  if (!points.length) return null;
  const counts = new Map();
  for (const p of points) counts.set(p.category, (counts.get(p.category) || 0) + 1);
  let best = null;
  for (const [key, count] of counts) {
    const cat = categories.find((c) => c.key === key);
    if (!best || count > best.count || (count === best.count && (cat?.rank ?? 99) < (best.cat?.rank ?? 99))) {
      best = { key, count, cat };
    }
  }
  return best;
}

function DistributionTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{point.label}</div>
      <div className="chart-tooltip__row">
        <span className="chart-tooltip__value">{point.count}</span>
        <span className="chart-tooltip__key">{point.count === 1 ? 'visit' : 'visits'}</span>
      </div>
    </div>
  );
}

/**
 * How often each category was recorded, ordered clearest/lowest to
 * worst/highest — "most samples here were recorded as Clear" as a chart.
 * Used where there's no room for a time axis (e.g. the river-wide
 * overview); `CategoryTimeline` below is the "is it changing" view.
 */
export function CategoryDistribution({ points, parameterKey, title }) {
  const categories = categoryScaleFor(parameterKey, points);
  const counts = useMemo(() => {
    const byKey = new Map();
    for (const p of points) byKey.set(p.category, (byKey.get(p.category) || 0) + 1);
    return categories.map((c, i) => ({ key: c.key, label: c.label, rank: c.rank, count: byKey.get(c.key) || 0, color: categoryColor(i) }));
  }, [points, categories]);

  if (points.length === 0) {
    return <p className="text-secondary">No written observations recorded for this yet.</p>;
  }

  const mode = modalCategory(points, categories);

  return (
    <div>
      {mode && (
        <p className="text-secondary" style={{ marginTop: 0 }}>
          Most visits recorded this as <strong>{mode.cat?.label || mode.key}</strong> ({mode.count} of {points.length}
          {' '}visit{points.length === 1 ? '' : 's'}).
        </p>
      )}
      <div style={{ width: '100%', height: Math.max(160, counts.length * 34) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={counts} layout="vertical" margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
            <CartesianGrid horizontal={false} stroke="var(--gridline)" />
            <XAxis type="number" allowDecimals={false} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }} tickLine={false} axisLine={{ stroke: 'var(--baseline)' }} />
            <YAxis type="category" dataKey="label" width={110} tick={{ fill: 'var(--text-primary)', fontSize: 12 }} tickLine={false} axisLine={false} />
            <Tooltip content={<DistributionTooltip />} cursor={{ fill: 'var(--surface-sunken)' }} isAnimationActive={false} />
            <Bar dataKey="count" maxBarSize={20} radius={[0, 4, 4, 0]} isAnimationActive={false} label={{ position: 'right', fill: 'var(--text-primary)', fontSize: 12, fontWeight: 700 }}>
              {counts.map((c) => <Cell key={c.key} fill={c.color} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function TimelineTooltip({ active, payload, label, categories }) {
  if (!active || !payload || !payload.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  const cat = categories.find((c) => c.rank === point.category_rank);
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">{formatDate(label)}</div>
      <div className="chart-tooltip__row">
        <span className="chart-tooltip__value">{cat?.label || point.category}</span>
      </div>
    </div>
  );
}

/**
 * Ordinal readings over time — a category strip so a reader can see
 * whether "Clear" is giving way to "Cloudy", which a distribution alone
 * cannot show. The y-axis is category names, evenly spaced for
 * readability (a standard ordinal-axis convention); no arithmetic is ever
 * done on the rank numbers — they exist only to order and place the axis.
 */
export function CategoryTimeline({ points, parameterKey }) {
  const categories = categoryScaleFor(parameterKey, points);
  const maxRank = categories.length ? Math.max(...categories.map((c) => c.rank)) : 1;

  const sorted = useMemo(
    () => [...points]
      .map((p) => ({ ...p, t: new Date(`${p.date}T00:00:00`).getTime() }))
      .sort((a, b) => a.t - b.t),
    [points]
  );

  if (sorted.length === 0) {
    return <p className="text-secondary">No written observations recorded for this yet.</p>;
  }

  if (sorted.length === 1) {
    const only = sorted[0];
    const cat = categories.find((c) => c.rank === only.category_rank);
    return (
      <p className="text-secondary">
        There is only one observation so far — not enough to show a pattern. It was recorded as{' '}
        <strong>{cat?.label || only.category}</strong> on {formatDate(only.date)}.
      </p>
    );
  }

  const tMin = sorted[0].t;
  const tMax = sorted[sorted.length - 1].t;

  return (
    <div style={{ width: '100%', height: Math.max(220, categories.length * 36) }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={sorted} margin={{ top: 16, right: 24, bottom: 8, left: 4 }}>
          <CartesianGrid horizontal vertical={false} stroke="var(--gridline)" />
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
            dataKey="category_rank"
            type="number"
            domain={[0.5, maxRank + 0.5]}
            ticks={categories.map((c) => c.rank)}
            tickFormatter={(r) => categories.find((c) => c.rank === r)?.label || r}
            stroke="var(--baseline)"
            tick={{ fill: 'var(--text-primary)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={100}
            reversed
          />
          <Tooltip content={<TimelineTooltip categories={categories} />} cursor={{ stroke: 'var(--text-muted)', strokeWidth: 1 }} isAnimationActive={false} />
          <Line
            type="linear"
            dataKey="category_rank"
            stroke="var(--text-muted)"
            strokeWidth={1.5}
            isAnimationActive={false}
            dot={(props) => {
              const { cx, cy, index, payload } = props;
              if (cx === undefined || cy === undefined) return null;
              const idx = categories.findIndex((c) => c.rank === payload.category_rank);
              return (
                <circle
                  key={index}
                  cx={cx}
                  cy={cy}
                  r={6}
                  fill={categoryColor(idx < 0 ? 0 : idx)}
                  stroke="var(--surface-card)"
                  strokeWidth={2}
                />
              );
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
