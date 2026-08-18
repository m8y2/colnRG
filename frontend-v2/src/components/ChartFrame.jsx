import { useId, useState } from 'react';
import { LoadingState, ErrorState, EmptyState } from './AsyncState.jsx';

/**
 * The wrapper every chart in the app is built inside: a finding-style
 * title (not an axis restatement), an optional explanation that adds
 * information the title didn't already give, a "View as table" toggle,
 * and built-in loading/error/empty handling so no chart ever silently
 * renders a blank plot area.
 *
 * `status`: 'loading' | 'error' | 'empty' | 'ready'
 * `table`: a <DataTable .../> element shown when the toggle is switched on
 */
export default function ChartFrame({
  title,
  explain,
  status = 'ready',
  errorMessage,
  emptyMessage,
  onRetry,
  table,
  footnote,
  children,
}) {
  const [showTable, setShowTable] = useState(false);
  const titleId = useId();

  return (
    <div className="chart-frame">
      <div className="chart-frame__head">
        <div>
          <h3 className="chart-frame__title" id={titleId}>{title}</h3>
          {explain && <p className="chart-frame__explain">{explain}</p>}
        </div>
        {status === 'ready' && table && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            aria-pressed={showTable}
            onClick={() => setShowTable((s) => !s)}
          >
            {showTable ? 'View as chart' : 'View as table'}
          </button>
        )}
      </div>
      <div className="chart-frame__body" aria-labelledby={titleId}>
        {status === 'loading' && <LoadingState label="Loading chart data…" />}
        {status === 'error' && <ErrorState message={errorMessage} onRetry={onRetry} />}
        {status === 'empty' && <EmptyState message={emptyMessage} />}
        {status === 'ready' && (showTable ? table : children)}
      </div>
      {status === 'ready' && footnote && <p className="chart-frame__axis-note">{footnote}</p>}
    </div>
  );
}
