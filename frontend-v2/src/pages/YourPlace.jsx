import { useMemo } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from '../components/AsyncState.jsx';
import LocationMap from '../components/LocationMap.jsx';
import LocationList from '../components/LocationList.jsx';
import { BandChip } from '../components/BandChip.jsx';
import Sparkline from '../components/Sparkline.jsx';
import UsableCount from '../components/UsableCount.jsx';
import { formatDate, formatReading, TOTAL_MAPPED_LOCATIONS, isWrittenObservation } from '../lib/format.js';
import { isBanded, classifyBand } from '../lib/bands.js';

function trendWords(trend) {
  if (!trend || trend.status === 'insufficient_data') return "There aren't enough readings yet to see a trend.";
  if (trend.direction === 'improving') return 'Getting better over time.';
  if (trend.direction === 'worsening') return 'Getting worse over time.';
  return 'No clear change over time.';
}

function positionSentence(location, ordered) {
  if (!location || location.river_order == null) return null;
  const idx = ordered.findIndex((l) => l.w3w === location.w3w);
  const upstream = idx > 0 ? ordered[idx - 1] : null;
  const downstream = idx >= 0 && idx < ordered.length - 1 ? ordered[idx + 1] : null;
  const parts = [`Point ${location.river_order} on the river, of ${TOTAL_MAPPED_LOCATIONS} mapped.`];
  if (upstream || downstream) {
    const bits = [];
    if (upstream) bits.push(`downstream of ${upstream.w3w}`);
    if (downstream) bits.push(`upstream of ${downstream.w3w}`);
    parts.push(bits.join(', ') + '.');
  }
  return parts.join(' ');
}

function LocationDetail({ w3w, ordered }) {
  const { status, data, error, reload } = useApi(
    () => Promise.all([api.getLocation(w3w), api.getParameters()]).then(([location, paramsResp]) => ({
      location,
      parameters: paramsResp.parameters || [],
    })),
    [w3w]
  );

  if (status === 'loading') return <LoadingState label={`Loading ${w3w}…`} />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const { location, parameters } = data;
  const paramsByKey = Object.fromEntries(parameters.map((p) => [p.key, p]));
  const stats = location.summary?.parameters || {};
  const trends = location.trends || {};
  const nonNumeric = location.non_numeric_observations || [];

  return (
    <div className="stack" aria-live="polite">
      <div>
        <h2 style={{ marginBottom: 4 }}>{location.w3w}</h2>
        <p className="text-secondary mt-0">{positionSentence(location, ordered)}</p>
        <p className="site-position">
          <span><strong>First sampled:</strong> {formatDate(location.first_sampled)}</span>
          <span><strong>Last sampled:</strong> {formatDate(location.last_sampled)}</span>
          <span>
            <strong>Readings:</strong>{' '}
            <UsableCount nUsable={location.n_usable ?? location.n_entries} nExcluded={location.n_excluded} />
          </span>
        </p>
      </div>

      <div className="grid grid--2">
        {Object.keys(stats).map((key) => {
          const parameter = paramsByKey[key];
          if (!parameter) return null;
          const stat = stats[key];
          const banded = isBanded(parameter);
          const latest = stat?.latest;
          const band = latest ? (banded ? classifyBand(latest.value, parameter) : null) : null;
          const numericSeries = (stat?.readings || []).filter((r) => r.value !== null && r.value !== undefined);
          const notes = nonNumeric.filter((n) => n.parameter === key);

          return (
            <div key={key} className="card parameter-card">
              <div className="parameter-card__head">
                <h3 style={{ margin: 0 }}>{parameter.label}</h3>
                <span className="parameter-card__unit">{parameter.unit}</span>
              </div>
              {latest ? (
                <>
                  <p className="mt-0" style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>
                    {formatReading(latest, parameter.unit)}
                    <span className="text-secondary" style={{ fontWeight: 400, fontSize: 'var(--fs-sm)' }}>
                      {' '}on {formatDate(latest.date)}
                    </span>
                  </p>
                  {banded && band && <BandChip band={band} parameter={parameter} />}
                </>
              ) : (
                <p className="text-muted mt-0">No numeric readings yet.</p>
              )}
              <div className="sparkline-wrap">
                <Sparkline data={numericSeries} />
                <span className="text-sm text-secondary">{trendWords(trends[key])}</span>
              </div>
              {notes.length > 0 && (
                <p className="text-sm text-secondary">
                  Also recorded as {notes.map((n) => `“${n.value_raw}”`).join(', ')} on{' '}
                  {notes.length === 1 ? 'one visit' : `${notes.length} visits`} — not shown as a number.
                </p>
              )}
            </div>
          );
        })}
      </div>

      {location.photos && location.photos.length > 0 && (
        <div>
          <h3>Photos from this spot</h3>
          <div className="grid grid--3">
            {location.photos.map((photo, i) => (
              <figure key={photo.url + i} className="card card--tight" style={{ margin: 0 }}>
                <img src={photo.url} alt={photo.description || `Photo taken at ${location.w3w}`} style={{ borderRadius: 'var(--radius-sm)', width: '100%' }} />
                <figcaption className="text-sm text-secondary" style={{ marginTop: 4 }}>
                  {formatDate(photo.date)}{photo.description ? ` — ${photo.description}` : ''}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function YourPlace({ routeParam, navigate }) {
  const selected = routeParam ? decodeURIComponent(routeParam) : null;

  const { status, data, error, reload } = useApi(() => api.getLocations(), []);

  const ordered = useMemo(() => {
    const list = data?.locations || [];
    return [...list].sort((a, b) => (a.river_order ?? 9999) - (b.river_order ?? 9999));
  }, [data]);

  const goTo = (w3w) => navigate(`your-place/${encodeURIComponent(w3w)}`);

  return (
    <div className="stack">
      <div className="page-header">
        <h1>Your place</h1>
        <p className="lead">
          Pick a location on the map or in the list below to see its readings. Each one is a what3words address — a
          real, checkable 3-metre square on the riverbank, not a made-up place name.
        </p>
      </div>

      {status === 'loading' && <LoadingState label="Loading locations…" />}
      {status === 'error' && <ErrorState message={error} onRetry={reload} />}

      {status === 'ready' && ordered.length === 0 && (
        <EmptyState message="No locations have been mapped yet." />
      )}

      {status === 'ready' && ordered.length > 0 && (
        <>
          <div className="map-layout">
            <LocationMap locations={data.locations} onSelectLocation={goTo} selected={selected} />
            <LocationList locations={ordered} onSelect={goTo} selected={selected} />
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-hairline)' }} />

          {selected ? (
            <LocationDetail w3w={selected} ordered={ordered} />
          ) : (
            <EmptyState message="Choose a location above to see its readings." />
          )}
        </>
      )}
    </div>
  );
}
