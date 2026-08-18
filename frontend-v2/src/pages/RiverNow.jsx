import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState } from '../components/AsyncState.jsx';
import ParameterCard from '../components/ParameterCard.jsx';
import LocationMap from '../components/LocationMap.jsx';
import LocationList from '../components/LocationList.jsx';
import UsableCount from '../components/UsableCount.jsx';
import { formatRelativeDate } from '../lib/format.js';

const GOOD_BANDS = new Set(['High', 'Good']);

// A deterministic, plain-English headline composed from the catchment
// band each banded parameter is currently in — never a made-up summary,
// just this dataset's own numbers turned into a sentence.
function buildHeadline(overviewParams, bandedParams) {
  const known = bandedParams
    .map((p) => ({ p, band: overviewParams?.[p.key]?.catchment_band }))
    .filter((x) => x.band);
  if (known.length === 0) {
    return "There isn't enough data yet to say how the river is doing overall.";
  }
  const watch = known.filter((x) => !GOOD_BANDS.has(x.band));
  if (watch.length === 0) {
    return 'Right now, the River Coln looks healthy: every measure volunteers check is in the Good band or better.';
  }
  const names = watch.map((x) => x.p.label.toLowerCase());
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
  const verb = watch.length === 1 ? 'needs' : 'need';
  return `Right now, ${known.length - watch.length} of ${known.length} measures volunteers check are Good or better, but ${list} ${verb} watching.`;
}

export default function RiverNow({ navigate }) {
  const { status, data, error, reload } = useApi(
    () => Promise.all([api.getOverview(), api.getParameters(), api.getLocations()]).then(
      ([overview, paramsResp, locsResp]) => ({
        overview,
        parameters: paramsResp.parameters || [],
        locations: locsResp.locations || [],
      })
    ),
    []
  );

  const goToLocation = (w3w) => navigate(`your-place/${encodeURIComponent(w3w)}`);

  return (
    <div className="stack">
      <div className="page-header">
        <h1>The river right now</h1>
      </div>

      {status === 'loading' && <LoadingState label="Loading the latest readings…" />}
      {status === 'error' && <ErrorState message={error} onRetry={reload} />}

      {status === 'ready' && (() => {
        const { overview, parameters, locations } = data;
        const bandedParams = parameters.filter((p) => p.bands);
        const headline = buildHeadline(overview.parameters, bandedParams);
        const nLocations = overview.n_locations ?? overview.n_sites ?? locations.length;

        const mapLocations = locations.map((loc) => ({
          w3w: loc.w3w,
          latitude: loc.latitude,
          longitude: loc.longitude,
          bands: Object.fromEntries(bandedParams.map((p) => [p.key, loc.latest_bands?.[p.key]?.band ?? null])),
        }));

        return (
          <>
            <section className="card headline-card">
              <p className="headline-card__sentence">{headline}</p>
              <p className="headline-card__meta">
                Last sampled{' '}
                {overview.most_recent_sample_date ? formatRelativeDate(overview.most_recent_sample_date) : 'date unknown'}
                {' · '}
                {nLocations} locations on the river
                {overview.n_usable !== undefined && (
                  <>
                    {' · '}
                    <UsableCount nUsable={overview.n_usable} nExcluded={overview.n_excluded} /> counted in these figures
                  </>
                )}
              </p>
            </section>

            <section>
              <h2>Each measure, right now</h2>
              <div className="grid grid--3">
                {bandedParams.map((p) => (
                  <ParameterCard
                    key={p.key}
                    parameter={p}
                    band={overview.parameters?.[p.key]?.catchment_band ?? null}
                    overview={overview.parameters?.[p.key]}
                    compact
                  />
                ))}
              </div>
            </section>

            <section>
              <h2>Where the readings come from</h2>
              <p className="text-secondary">
                Each pin is a what3words location a volunteer has sampled, coloured by its worst current reading.
              </p>
              <div className="map-layout">
                <LocationMap locations={mapLocations} onSelectLocation={goToLocation} />
                <LocationList locations={locations} onSelect={goToLocation} />
              </div>
            </section>
          </>
        );
      })()}
    </div>
  );
}
