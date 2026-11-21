import { useMemo, useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from '../components/AsyncState.jsx';
import LocationMap from '../components/LocationMap.jsx';
import LocationList from '../components/LocationList.jsx';
import PhotoTile from '../components/PhotoTile.jsx';
import PhotoLightbox from '../components/PhotoLightbox.jsx';
import { BandChip } from '../components/BandChip.jsx';
import Sparkline from '../components/Sparkline.jsx';
import UsableCount from '../components/UsableCount.jsx';
import { formatDate, formatReading, unitLabel } from '../lib/format.js';
import { isBanded, classifyBand } from '../lib/bands.js';

function trendWords(trend, parameterLabel) {
  if (!trend || trend.status === 'insufficient_data') return "There aren't enough readings yet to see a trend.";
  if (trend.direction === 'improving') return 'Getting better over time.';
  if (trend.direction === 'worsening') return 'Getting worse over time.';
  return `There is no clear trend in ${parameterLabel.toLowerCase()} at the moment.`;
}

function positionSentence(location) {
  if (!location) return null;
  const rank = location.downstream_rank ?? null;
  const total = location.n_locations_total ?? null;
  if (rank == null || total == null) return null;
  return `Point ${rank} of ${total} on the river.`;
}

function LocationDetail({ w3w }) {
  const [openPhotoUrl, setOpenPhotoUrl] = useState(null);
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
  // Dissolved oxygen and conductivity are not shown on location pages
  // (or the home page or What we measure): they are barely measured, so
  // a card for them mostly says "not measured here yet".
  const hidden = new Set(['dissolved_oxygen', 'conductivity']);
  const stats = Object.fromEntries(
    Object.entries(location.summary?.parameters || {}).filter(([key]) => !hidden.has(key))
  );
  const trends = location.trends || {};
  const nonNumeric = location.non_numeric_observations || [];

  return (
    <div className="stack" aria-live="polite">
      <div>
        <h2 style={{ marginBottom: 4 }}>{location.w3w}</h2>
        <p className="text-secondary mt-0">{positionSentence(location)}</p>
        <p className="site-position">
          <span><strong>First sampled:</strong> {formatDate(location.summary?.first_sampled)}</span>
          <span><strong>Last sampled:</strong> {formatDate(location.summary?.last_sampled)}</span>
        </p>
      </div>

      <div className="grid grid--2">
        {Object.keys(stats).map((key) => {
          const parameter = paramsByKey[key];
          if (!parameter) return null;
          // The API splits each parameter into `numeric` and `ordinal`
          // and never merges them — a measure can have both (turbidity has
          // ~10 meter readings and ~359 written ones). Read them apart here
          // for the same reason.
          const stat = stats[key];
          const numeric = stat?.numeric || {};
          const ordinal = stat?.ordinal || null;
          const banded = isBanded(parameter);
          const latest = numeric.latest;
          const band = latest ? (banded ? classifyBand(latest.value, parameter) : null) : null;
          const notes = nonNumeric.filter((n) => n.parameter === key);

          return (
            <div key={key} className="card parameter-card">
              <div className="parameter-card__head">
                <h3 style={{ margin: 0 }}>{parameter.label}</h3>
                <span className="parameter-card__unit">{unitLabel(parameter.unit)}</span>
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
              ) : ordinal && ordinal.n_usable ? (
                <p className="mt-0">
                  <strong>Usually {ordinal.modal_label?.toLowerCase()}</strong>
                  <span className="text-secondary">
                    {', '}{ordinal.n_usable} observation{ordinal.n_usable === 1 ? '' : 's'}
                  </span>
                </p>
              ) : (
                <p className="text-muted mt-0">Not measured here yet.</p>
              )}
              {numeric.n_usable > 0 && (
                <p className="text-sm text-secondary mt-0">
                  <UsableCount nUsable={numeric.n_usable} nExcluded={stat?.n_excluded} />
                  {trendWords(trends[key], parameter.label) ? `. ${trendWords(trends[key], parameter.label)}` : ''}
                </p>
              )}
              {notes.length > 0 && (
                <p className="text-sm text-secondary">
                  Also recorded as {notes.map((n) => `“${n.value_raw}”`).join(', ')} on{' '}
                  {notes.length === 1 ? 'one visit' : `${notes.length} visits`}, not shown as a number.
                </p>
              )}
            </div>
          );
        })}
      </div>

      {location.photos && location.photos.length > 0 && (
        <div>
          <h3>Photos from this spot</h3>
          <ul className="photo-grid" aria-label={`Photos taken at ${location.w3w}`}>
            {location.photos.map((photo) => (
              <PhotoTile
                key={photo.url}
                photo={{ ...photo, w3w: location.w3w }}
                open={openPhotoUrl === photo.url}
                overlay={false}
                onToggle={() =>
                  setOpenPhotoUrl((prev) => (prev === photo.url ? null : photo.url))
                }
              />
            ))}
          </ul>
        </div>
      )}

      {openPhotoUrl && (
        <PhotoLightbox
          photo={{
            url: openPhotoUrl,
            original_url: location.photos.find((p) => p.url === openPhotoUrl)?.original_url,
            w3w: location.w3w,
            date: location.photos.find((p) => p.url === openPhotoUrl)?.date,
            description: location.photos.find((p) => p.url === openPhotoUrl)?.description,
          }}
          onClose={() => setOpenPhotoUrl(null)}
        />
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
          Each location here is a what3words address: a 3-metre square on the
          riverbank. Volunteers sample it once a month.
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
            <LocationDetail w3w={selected} />
          ) : (
            <EmptyState message="Choose a location above to see its readings." />
          )}
        </>
      )}
    </div>
  );
}
