import { useMemo, useState } from 'react';
import { useApi } from '../lib/useApi.js';
import * as api from '../lib/api.js';
import { LoadingState, ErrorState } from '../components/AsyncState.jsx';
import DataTable from '../components/DataTable.jsx';
import NativeSelect from '../components/NativeSelect.jsx';
import { formatDate, formatReadingText } from '../lib/format.js';

const PER_PAGE = 50;

function sortRows(rows, columns, sort) {
  if (!sort) return rows;
  const { key, dir } = sort;
  const col = columns.find((c) => c.key === key);
  if (!col) return rows;
  const sign = dir === 'asc' ? 1 : -1;
  const valueOf = (row) => (col.sortValue ? col.sortValue(row) : row[key]);
  return [...rows].sort((a, b) => {
    const va = valueOf(a);
    const vb = valueOf(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') return sign * (va - vb);
    return sign * String(va).localeCompare(String(vb));
  });
}

function Pager({ page, totalPages, total, onPage }) {
  return (
    <div className="pager">
      <button
        type="button"
        className="btn btn-secondary"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        Previous
      </button>
      <span className="pager__status">
        Page {page} of {totalPages}, {total} visit{total === 1 ? '' : 's'}
      </span>
      <button
        type="button"
        className="btn btn-secondary"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
      >
        Next
      </button>
    </div>
  );
}

export default function AllData() {
  const [place, setPlace] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(null);

  const locsCall = useApi(() => api.getLocations());
  const paramsCall = useApi(() => api.getParameters());

  const filters = useMemo(() => ({ w3w: place, from: from || undefined, to: to || undefined, page, per_page: PER_PAGE }),
    [place, from, to, page]);

  const call = useApi(() => api.getObservations(filters), [place, from, to, page]);

  const setFilter = (key, value) => {
    if (key === 'place') setPlace(value);
    if (key === 'from') setFrom(value);
    if (key === 'to') setTo(value);
    setPage(1);
  };

  const locations = useMemo(() => {
    const list = locsCall.data?.locations || [];
    return [...list].sort((a, b) => (a.river_order ?? 9999) - (b.river_order ?? 9999));
  }, [locsCall.data]);

  const columns = useMemo(() => {
    const params = paramsCall.data?.parameters || [];
    return [
      { key: 'date', label: 'Date', sortable: true, render: (r) => (r.date ? formatDate(r.date) : '—') },
      { key: 'time', label: 'Time', sortable: false, render: (r) => r.time || '—' },
      { key: 'w3w', label: 'Place', wrap: true, sortable: true },
      {
        key: 'recorder',
        label: 'Collected by',
        sortable: true,
        render: (r) => r.recorder || '—',
      },
      ...params.map((meta) => {
        const paramKey = meta.key;
        return {
          key: `m-${paramKey}`,
          label: `${meta.label} (${meta.unit})`,
          sortable: true,
          sortValue: (r) => {
            const m = r.measurements?.[paramKey];
            if (!m) return null;
            return m.value ?? m.category_rank ?? null;
          },
          render: (r) => {
            const m = r.measurements?.[paramKey];
            if (!m) return null;
            return formatReadingText(m, meta);
          },
        };
      }),
    ];
  }, [paramsCall.data]);

  const toggleSort = (key) => {
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: 'asc' };
      if (s.dir === 'asc') return { key, dir: 'desc' };
      return null;
    });
  };

  const rows = useMemo(
    () => sortRows(call.data?.rows || [], columns, sort),
    [call.data, columns, sort]
  );

  return (
    <div className="stack">
      <div className="page-header">
        <h1>All the data</h1>
        <p className="lede">
          Every reading as it was submitted, one row per visit, newest first.
        </p>
      </div>

      <section className="card stack">
        <div className="filter-row">
          <NativeSelect
            id="alldata-place"
            label="Which place"
            value={place}
            onChange={(e) => setFilter('place', e.target.value)}
            options={[
              { value: '', label: 'All places' },
              ...locations.map((l, i) => ({ value: l.w3w, label: `#${i + 1} ${l.w3w}` })),
            ]}
          />
          <label className="field">
            <span className="field__label">From</span>
            <input type="date" value={from} onChange={(e) => setFilter('from', e.target.value)} />
          </label>
          <label className="field">
            <span className="field__label">To</span>
            <input type="date" value={to} onChange={(e) => setFilter('to', e.target.value)} />
          </label>
          <span className="toolbar-spacer" />
          <a className="btn" href={api.exportCsvUrl({})} download>
            Download all readings (spreadsheet)
          </a>
        </div>

        {call.status === 'loading' && <LoadingState label="Loading readings…" />}
        {(paramsCall.status === 'error' || locsCall.status === 'error') && (
          <ErrorState
            message={paramsCall.error || locsCall.error}
            onRetry={() => {
              paramsCall.reload();
              locsCall.reload();
            }}
          />
        )}
        {call.status === 'error' && (
          <ErrorState message={call.error} onRetry={call.reload} />
        )}
        {call.status === 'ready' && (
          <>
            <DataTable
              caption="Every reading on record"
              columns={columns}
              rows={rows}
              getRowKey={(r) => r.ec5_uuid}
              sort={sort}
              onSort={toggleSort}
            />
            <Pager
              page={call.data.page}
              totalPages={call.data.total_pages}
              total={call.data.total}
              onPage={setPage}
            />
          </>
        )}
      </section>
    </div>
  );
}
