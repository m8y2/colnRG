import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState } from '../components/AsyncState.jsx';
import { BandLegend } from '../components/BandChip.jsx';

// The glossary page. Everything here comes from wfd.py via /parameters,
// so the words used on a chart, in a report and on this page cannot drift
// apart.

function BandTable({ parameter }) {
  const bands = parameter.bands;
  if (!bands) return null;
  const meanings = parameter.band_meanings || {};
  const order = ['High', 'Good', 'Moderate', 'Poor', 'Bad'];
  const present = order.filter((b) => bands[b] !== undefined || meanings[b]);
  if (present.length === 0) return null;

  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>
          What each band means for {parameter.label.toLowerCase()}
        </caption>
        <thead>
          <tr>
            <th scope="col">Band</th>
            <th scope="col">Reading ({parameter.unit})</th>
            <th scope="col">What that means for the river</th>
          </tr>
        </thead>
        <tbody>
          {present.map((band) => (
            <tr key={band}>
              <th scope="row">{band}</th>
              <td className="num">{bands[band] ?? '—'}</td>
              <td className="wrap">{meanings[band] || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ParameterSection({ parameter }) {
  const notMeasured = parameter.not_currently_measured;
  const ordinal = parameter.ordinal_scale;

  return (
    <section className="card stack" aria-labelledby={`param-${parameter.key}`}>
      <div className="param-heading">
        <h2 id={`param-${parameter.key}`}>{parameter.label}</h2>
        {notMeasured && (
          <span className="tag tag--muted">Not being measured at the moment</span>
        )}
      </div>

      <p className="lede">{parameter.one_liner}</p>

      {parameter.why_it_matters && (
        <>
          <h3>Why it matters</h3>
          <p>{parameter.why_it_matters}</p>
        </>
      )}

      {parameter.where_from && (
        <>
          <h3>Where it comes from</h3>
          <p>{parameter.where_from}</p>
        </>
      )}

      {notMeasured && (
        <p className="note">
          The group does not currently have the kit to measure this, so there are
          almost no readings for it. It is listed here so you know what is and
          is not being checked.
        </p>
      )}

      {ordinal && (
        <>
          <h3>How this one is recorded</h3>
          <p>
            Volunteers judge this by eye and write it down in words rather than
            reading it off a meter. Those words are kept as they were written
            and sorted from clearest to muddiest — they are never turned into a
            number, because a description is not a measurement.
          </p>
          <ol className="scale-list">
            {(ordinal.steps || []).map((step) => (
              <li key={step.category}>{step.label}</li>
            ))}
          </ol>
        </>
      )}

      {parameter.bands && (
        <>
          <h3>How readings are graded</h3>
          <BandTable parameter={parameter} />
          <BandLegend parameter={parameter.key} title={null} />
        </>
      )}
    </section>
  );
}

export default function WhatWeMeasure() {
  const { status, data, error, reload } = useApi(() => api.getParameters());

  if (status === 'loading') return <LoadingState label="Loading what we measure…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const parameters = data.parameters || [];
  const measured = parameters.filter((p) => !p.not_currently_measured);
  const unmeasured = parameters.filter((p) => p.not_currently_measured);

  return (
    <div className="stack">
      <div className="page-header">
        <h1>What we measure</h1>
        <p className="lede">
          Volunteers test the water with kits they carry to the riverbank. Each
          measurement below tells you something different about the river's
          health. The grades come from the Water Framework Directive, the
          standard the Environment Agency uses for rivers like the Coln.
        </p>
        <p className="note">
          One thing worth knowing before you read on: in these grades{' '}
          <strong>High is the best</strong> and <strong>Bad is the worst</strong>.
          "High phosphate" in everyday speech would mean bad news, but a High
          grade here means the river is doing well.
        </p>
      </div>

      {measured.map((p) => (
        <ParameterSection key={p.key} parameter={p} />
      ))}

      {unmeasured.length > 0 && (
        <>
          <h2 className="section-heading">Not currently measured</h2>
          {unmeasured.map((p) => (
            <ParameterSection key={p.key} parameter={p} />
          ))}
        </>
      )}
    </div>
  );
}
