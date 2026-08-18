import { useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState, EmptyState } from '../components/AsyncState.jsx';
import DataTable from '../components/DataTable.jsx';
import NativeSelect from '../components/NativeSelect.jsx';
import { formatDate } from '../lib/format.js';

// The raw detail, plus the honesty section: what was changed on the way in,
// what was left out, and what still needs a human decision. Linked to from
// every statistic that excluded readings, so people meet it in context
// rather than having to come looking.

function ReviewItem({ item, onDecide, busy }) {
  const isLocation = item.issue === 'ambiguous_location';
  return (
    <li className="review-item">
      <div className="review-item__head">
        <code className="review-item__raw">{item.value_raw}</code>
        {item.parameter && <span className="tag">{item.parameter.replace(/_/g, ' ')}</span>}
        <span className="tag tag--muted">{item.issue.replace(/_/g, ' ')}</span>
      </div>
      {item.suggestion_reason && <p className="review-item__reason">{item.suggestion_reason}</p>}
      <div className="review-item__actions">
        {item.suggestion ? (
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy}
            onClick={() => onDecide(item.id, 'accepted', item.suggestion)}
          >
            {isLocation ? 'Yes, same place' : `Accept ${item.suggestion}`}
          </button>
        ) : null}
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => onDecide(item.id, 'rejected', null)}
        >
          {isLocation ? 'No, keep separate' : 'Leave as it is'}
        </button>
      </div>
    </li>
  );
}

function ReviewQueue() {
  const { status, data, error, reload } = useApi(() => api.getReviewQueue());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const decide = async (id, decision, value) => {
    setBusy(true);
    setMessage('');
    try {
      await api.postReviewDecision(id, { status: decision, resolved_value: value });
      setMessage(
        decision === 'accepted'
          ? 'Saved. It will be applied the next time the data is rebuilt, and can be undone.'
          : 'Left as it is. The reading stays out of the averages.'
      );
      reload();
    } catch (e) {
      setMessage(`That did not save: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  if (status === 'loading') return <LoadingState label="Loading readings that need a decision…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const open = (data.items || []).filter((i) => i.status === 'open');

  return (
    <section className="card stack" id="needs-a-look" aria-labelledby="needs-a-look-h">
      <h2 id="needs-a-look-h">Readings that need a person to decide</h2>
      <p>
        These are readings we could not interpret with confidence. Nothing has
        been changed. Where there is an obvious explanation it is suggested
        below, but the suggestion is only applied if you accept it — and it can
        be undone afterwards.
      </p>
      {message && (
        <p className="note" role="status" aria-live="polite">
          {message}
        </p>
      )}
      {open.length === 0 ? (
        <EmptyState message="Nothing is waiting for a decision." />
      ) : (
        <ul className="review-list">
          {open.map((item) => (
            <ReviewItem key={item.id} item={item} onDecide={decide} busy={busy} />
          ))}
        </ul>
      )}
    </section>
  );
}

function HowWeHandled() {
  const { status, data, error, reload } = useApi(() => api.getDataQuality());

  if (status === 'loading') return <LoadingState label="Loading data quality…" />;
  if (status === 'error') return <ErrorState message={error} onRetry={reload} />;

  const params = data.parameters || {};
  const rows = Object.entries(params).map(([key, v]) => ({ key, ...v }));

  return (
    <section className="card stack" id="how-we-handled-it" aria-labelledby="how-we-handled-h">
      <h2 id="how-we-handled-h">How the readings were handled</h2>
      <p>
        Every reading volunteers submitted is kept exactly as it was written.
        Where a reading needed tidying to be usable — a unit written after the
        number, a comma instead of a decimal point, a depth given in inches —
        the change is recorded and can be traced back. Nothing is quietly
        rewritten, and a reading that looks wrong is set aside rather than
        adjusted to look right.
      </p>

      <DataTable
        caption="Readings used and set aside, by measurement"
        columns={[
          { key: 'key', label: 'Measurement', render: (r) => r.key.replace(/_/g, ' ') },
          { key: 'n_usable', label: 'Used', numeric: true },
          { key: 'n_excluded', label: 'Set aside', numeric: true },
          {
            key: 'why',
            label: 'Why any were set aside',
            wrap: true,
            render: (r) =>
              r.n_excluded
                ? 'No measurement was taken, or the reading could not be read as a number.'
                : '—',
          },
        ]}
        rows={rows}
        getRowKey={(r) => r.key}
      />

      {data.excluded_entries != null && (
        <p className="note">
          {data.excluded_entries} submission(s) were left out entirely because
          they were tests rather than samples.
        </p>
      )}
    </section>
  );
}

export default function AllData() {
  const [parameter, setParameter] = useState('phosphate');
  const paramsCall = useApi(() => api.getParameters());
  const seriesCall = useApi(() => api.getSeries({ parameter }), [parameter]);

  const parameters = paramsCall.data?.parameters || [];
  const points = seriesCall.data?.points || [];

  return (
    <div className="stack">
      <div className="page-header">
        <h1>All the data</h1>
        <p className="lede">
          Every reading, as it was submitted, alongside how it was
          interpreted.
        </p>
      </div>

      <section className="card stack">
        <div className="toolbar">
          <NativeSelect
            id="alldata-parameter"
            label="Measurement"
            value={parameter}
            onChange={setParameter}
            options={parameters.map((p) => ({ value: p.key, label: p.label }))}
          />
          <a className="btn" href={api.exportCsvUrl({ parameter })} download>
            Download as a spreadsheet (CSV)
          </a>
        </div>

        {seriesCall.status === 'loading' && <LoadingState label="Loading readings…" />}
        {seriesCall.status === 'error' && (
          <ErrorState message={seriesCall.error} onRetry={seriesCall.reload} />
        )}
        {seriesCall.status === 'ready' && (
          <DataTable
            caption={`Every ${parameter.replace(/_/g, ' ')} reading on record`}
            columns={[
              { key: 'date', label: 'Date', render: (r) => formatDate(r.date) },
              { key: 'w3w', label: 'Place', wrap: true },
              {
                key: 'reading',
                label: 'Reading',
                render: (r) =>
                  r.category_label
                    ? r.category_label
                    : r.value != null
                      ? `${r.value}`
                      : '—',
              },
              { key: 'value_raw', label: 'As written', wrap: true },
              {
                key: 'qualifier',
                label: 'Notes',
                wrap: true,
                render: (r) => (r.qualifier || '').replace(/_/g, ' '),
              },
              { key: 'recorder', label: 'Collected by' },
            ]}
            rows={points}
            getRowKey={(r, i) => `${r.date}-${r.w3w}-${i}`}
          />
        )}
      </section>

      <HowWeHandled />
      <ReviewQueue />
    </div>
  );
}
