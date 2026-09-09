// A generic, accessible table: <caption>, scope'd headers (col on the
// header row, row on the first cell of each row), and its own horizontal
// scroll box so a wide table never forces the page itself to scroll
// sideways. This is the "View as table" twin of every chart in the app.
//
// Columns marked `sortable: true` render as buttons with aria-sort on the
// header cell; `sort` is `{key, dir}` and `onSort(key)` toggles the sort.
export default function DataTable({ caption, columns, rows, getRowKey, sort, onSort }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => {
              const sorted = sort && sort.key === col.key;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={col.numeric ? 'num' : undefined}
                  aria-sort={sorted ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                >
                  {col.sortable && onSort ? (
                    <button type="button" className="sortable-header" onClick={() => onSort(col.key)}>
                      {col.label}
                      {sorted ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length}>No rows to show.</td>
            </tr>
          )}
          {rows.map((row, i) => (
            <tr key={getRowKey ? getRowKey(row, i) : i}>
              {columns.map((col, ci) => {
                const content = col.render ? col.render(row) : row[col.key];
                const className = col.numeric ? 'num' : col.wrap ? 'wrap' : undefined;
                return ci === 0 ? (
                  <th key={col.key} scope="row" className={className}>
                    {content}
                  </th>
                ) : (
                  <td key={col.key} className={className}>
                    {content}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
