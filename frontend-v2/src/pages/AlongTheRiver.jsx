import { useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import ChartFrame from '../components/ChartFrame.jsx';
import DataTable from '../components/DataTable.jsx';
import NativeSelect from '../components/NativeSelect.jsx';
import DownstreamChart from '../components/DownstreamChart.jsx';
import { BandLegend } from '../components/BandChip.jsx';
import { formatReading } from '../lib/format.js';
import { isBanded, classifyBand } from '../lib/bands.js';

function downstreamFinding(points, paramLabel, higherBetter) {
  const numeric = points.filter((p) => p.value !== null && p.value !== undefined);
  if (numeric.length < 4) return `${paramLabel} along the river`;
  const third = Math.max(1, Math.floor(numeric.length / 3));
  const upstream = numeric.slice(0, third);
  const downstream = numeric.slice(-third);
  const avg = (arr) => arr.reduce((s, p) => s + p.value, 0) / arr.length;
  const a = avg(upstream);
  const b = avg(downstream);
  const rel = a !== 0 ? Math.abs(b - a) / Math.abs(a) : 0;
  if (rel < 0.1) return `${paramLabel} is similar all along the river`;
  const worse = higherBetter ? b < a : b > a;
  return worse ? `${paramLabel} is worse further downstream` : `${paramLabel} is better further downstream`;
}

export default function AlongTheRiver() {
  const [parameterKey, setParameterKey] = useState('phosphate');
  const [roundValue, setRoundValue] = useState('');

  const { status: paramsStatus, data: paramsData } = useApi(() => api.getParameters(), []);
  const { status: roundsStatus, data: roundsData } = useApi(() => api.getRounds(), []);

  const parameters = paramsData?.parameters || [];
  const parameter = parameters.find((p) => p.key === parameterKey);
  const rounds = roundsData?.rounds || [];

  const { status, data, error, reload } = useApi(
    () => api.getDownstream({ parameter: parameterKey, round: roundValue || undefined }),
    [parameterKey, roundValue]
  );

  if (paramsStatus === 'loading' || roundsStatus === 'loading') {
    return <p className="text-secondary">Loading…</p>;
  }

  // The endpoint returns one aggregated figure per location under `mean`
  // (a round may hold more than one reading at a place). DownstreamChart's
  // contract is `value`, so normalise here rather than making every
  // consumer know both names.
  const allPoints = (data?.locations || []).map((loc) => ({
    ...loc,
    value: loc.value ?? loc.mean ?? null,
  }));
  const numericPoints = allPoints.filter((p) => p.value !== null && p.value !== undefined);
  const nonNumeric = allPoints.filter((p) => (p.value === null || p.value === undefined) && p.value_raw);

  const title = parameter
    ? downstreamFinding(allPoints, parameter.label, parameter.direction === 'higher_better')
    : 'Along the river';

  const chartStatus = status === 'loading' ? 'loading' : status === 'error' ? 'error' : numericPoints.length === 0 ? 'empty' : 'ready';

  const tableRows = allPoints.map((p, i) => ({
    position: i + 1,
    w3w: p.w3w,
    reading: p.value !== null && p.value !== undefined
      ? formatReading(p, parameter?.unit)
      : (p.value_raw ? `“${p.value_raw}”` : 'No reading'),
    band: parameter && isBanded(parameter) && p.value != null ? classifyBand(p.value, parameter) : '—',
  }));

  return (
    <div className="stack">
      <div className="page-header">
        <h1>Along the river</h1>
        <p className="lead">
          The River Coln runs from its source near Sevenhampton to where it joins the
          Thames at Lechlade. This page follows the river downstream, in that order.
        </p>
      </div>

      <div className="filter-row">
        <NativeSelect
          label="Which measure"
          value={parameterKey}
          onChange={(e) => setParameterKey(e.target.value)}
          options={parameters.map((p) => ({ value: p.key, label: p.label }))}
        />
        <NativeSelect
          label="Which round"
          value={roundValue}
          onChange={(e) => setRoundValue(e.target.value)}
          options={[
            { value: '', label: 'All time (latest at each place)' },
            ...rounds.map((r) => ({ value: String(r.round), label: `Round ${r.round} (${r.start} – ${r.end})` })),
          ]}
        />
      </div>

      {parameter && (
        <ChartFrame
          title={title}
          status={chartStatus}
          errorMessage={error}
          onRetry={reload}
          emptyMessage="No located readings for this measure and round."
          footnote="Bars are coloured by their own band. Hover a bar, or use the table below, to see its value and location."
          table={
            <DataTable
              caption="Every location on the river, source to Thames"
              columns={[
                { key: 'position', label: 'Position', numeric: true },
                { key: 'w3w', label: 'Location (what3words)', wrap: true },
                { key: 'reading', label: 'Reading' },
                { key: 'band', label: 'Band' },
              ]}
              rows={tableRows}
              getRowKey={(r) => r.w3w}
            />
          }
        >
          <DownstreamChart points={numericPoints} parameter={parameter} />
        </ChartFrame>
      )}

      {nonNumeric.length > 0 && (
        <p className="text-sm text-secondary">
          {nonNumeric.length} more location{nonNumeric.length === 1 ? '' : 's'} recorded a written observation (like
          &ldquo;cloudy&rdquo;) instead of a number for {parameter?.label.toLowerCase()}; see the table above for what was
          written.
        </p>
      )}

      {parameter && isBanded(parameter) && <BandLegend parameter={parameter} />}
    </div>
  );
}
