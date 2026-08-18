// A generic, accessible table: <caption>, scope'd headers (col on the
// header row, row on the first cell of each row), and its own horizontal
// scroll box so a wide table never forces the page itself to scroll
// sideways. This is the "View as table" twin of every chart in the app.
export default function DataTable({ caption, columns, rows, getRowKey }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} scope="col" className={col.numeric ? 'num' : undefined}>
                {col.label}
              </th>
            ))}
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
