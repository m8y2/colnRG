import { useMemo, useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import ChartFrame from '../components/ChartFrame.jsx';
import DataTable from '../components/DataTable.jsx';
import NativeSelect from '../components/NativeSelect.jsx';
import TimeSeriesChart from '../components/TimeSeriesChart.jsx';
import { BandLegend } from '../components/BandChip.jsx';
import { formatDate, formatReading, spelledOutUnit, isWrittenObservation } from '../lib/format.js';
import { isBanded, classifyBand } from '../lib/bands.js';

const SCOPES = [
  { value: 'whole-river', label: 'The whole river, round by round' },
  { value: 'one-place', label: 'One place over time' },
];

function trendTitle(parameterLabel, trend) {
  if (!trend || trend.status === 'insufficient_data') {
    return `${parameterLabel}: not enough readings yet to see a trend`;
  }
  if (trend.direction === 'improving') return `${parameterLabel} has been getting better`;
  if (trend.direction === 'worsening') return `${parameterLabel} has been getting worse`;
  return `${parameterLabel} has not changed much`;
}

export default function OverTime() {
  const [scope, setScope] = useState('whole-river');
  const [parameterKey, setParameterKey] = useState('phosphate');
  const [locationW3w, setLocationW3w] = useState('');

  const { status: paramsStatus, data: paramsData } = useApi(() => api.getParameters(), []);
  const { status: locsStatus, data: locsData } = useApi(() => api.getLocations(), []);

  // Dissolved oxygen and conductivity are barely measured (a handful of
  // readings each out of hundreds), so a trend line drawn from that few
  // points would look like a real signal and isn't one. Hidden the same
  // way they're hidden from the "river right now" headline measures.
  const hidden = new Set(['dissolved_oxygen', 'conductivity']);
  const parameters = (paramsData?.parameters || []).filter((p) => !hidden.has(p.key));
  const parameter = parameters.find((p) => p.key === parameterKey);

  const orderedLocations = useMemo(() => {
    const list = locsData?.locations || [];
    return [...list].sort((a, b) => (a.river_order ?? 9999) - (b.river_order ?? 9999));
  }, [locsData]);

  const effectiveLocation = scope === 'one-place' ? (locationW3w || orderedLocations[0]?.w3w || '') : '';

  const seriesDeps = [parameterKey, scope, effectiveLocation];
  const { status: seriesStatus, data: seriesData, error: seriesError, reload: reloadSeries } = useApi(() => {
    if (scope === 'one-place') {
      const calls = [api.getSeries({ parameter: parameterKey, w3w: effectiveLocation })];
      if (effectiveLocation) calls.push(api.getLocation(effectiveLocation));
      return Promise.all(calls).then(([series, location]) => ({ series, location: location || null }));
    }
    return api.getRounds().then((roundsResp) => ({ rounds: roundsResp.rounds || [], location: null }));
  }, seriesDeps);

  if (paramsStatus === 'loading' || locsStatus === 'loading') {
    return <p className="text-secondary">Loading…</p>;
  }

  const points = scope === 'one-place'
    ? (seriesData?.series?.points || [])
    : (seriesData?.rounds || []).map((r) => {
      const p = r.parameters?.[parameterKey];
      return {
        date: r.start,
        value: p?.mean ?? null,
        value_raw: null,
        qualifier: 'exact',
        usable: true,
        n: p?.n,
      };
    });

  const trend = scope === 'one-place' ? seriesData?.location?.trends?.[parameterKey] : null;
  const title = scope === 'one-place'
    ? trendTitle(parameter?.label || parameterKey, trend)
    : `${parameter?.label || parameterKey} across the whole river, round by round`;

  const chartStatus = seriesStatus === 'loading' ? 'loading' : seriesStatus === 'error' ? 'error' : points.length === 0 ? 'empty' : 'ready';

  const tableRows = points.map((p) => ({
    date: p.date,
    reading: isWrittenObservation(p) ? `“${p.value_raw}”` : (formatReading(p, parameter?.unit) ?? '—'),
    band: parameter && isBanded(parameter) && p.value != null ? classifyBand(p.value, parameter) : '—',
  }));

  return (
    <div className="stack">
      <div className="page-header">
        <h1>Change over time</h1>
        <p className="lead">See whether a measure has been getting better, worse, or staying about the same.</p>
      </div>

      <div className="filter-row">
        <NativeSelect
          label="Show me"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          options={SCOPES}
        />
        <NativeSelect
          label="Which measure"
          value={parameterKey}
          onChange={(e) => setParameterKey(e.target.value)}
          options={parameters.map((p) => ({ value: p.key, label: p.label }))}
        />
        {scope === 'one-place' && (
          <NativeSelect
            label="Which place"
            value={effectiveLocation}
            onChange={(e) => setLocationW3w(e.target.value)}
            options={orderedLocations.map((l, i) => ({ value: l.w3w, label: `#${i + 1} ${l.w3w}` }))}
          />
        )}
      </div>

      {parameter && (
        <ChartFrame
          title={title}
          status={chartStatus}
          errorMessage={seriesError}
          onRetry={reloadSeries}
          emptyMessage="No readings for this yet."
          footnote={spelledOutUnit(parameter.unit) ? `${parameter.label} is measured in ${spelledOutUnit(parameter.unit)}.` : undefined}
          table={
            <DataTable
              caption={`${title}: every reading behind this chart`}
              columns={[
                { key: 'date', label: 'Date', render: (r) => formatDate(r.date) },
                { key: 'reading', label: 'Reading' },
                { key: 'band', label: 'Band' },
              ]}
              rows={tableRows}
              getRowKey={(r, i) => `${r.date}-${i}`}
            />
          }
        >
          <TimeSeriesChart points={points} parameter={parameter} />
        </ChartFrame>
      )}

      {parameter && isBanded(parameter) && <BandLegend parameter={parameter} />}
    </div>
  );
}
