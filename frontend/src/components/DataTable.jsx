import { useState, useEffect, useMemo } from "react";
import { getEntries } from "../api";
import { fmtDate } from "../utils";

const COLS = [
  { key: "sample_date", label: "Date" },
  { key: "sample_time", label: "Time" },
  { key: "w3w_site_code", label: "Site" },
  { key: "w3w", label: "What3Words" },
  { key: "water_depth_cm", label: "Depth (cm)" },
  { key: "phosphate_level", label: "Phosphate" },
  { key: "ammonia_level", label: "Ammonia" },
  { key: "nitrate_level", label: "Nitrate" },
  { key: "turbidity", label: "Turbidity" },
  { key: "dissolved_oxygen", label: "DO" },
  { key: "conductivity", label: "Conductivity" },
  { key: "landowner", label: "Landowner" },
];

const NUMERIC_KEYS = new Set([
  "water_depth_cm", "phosphate_level", "ammonia_level",
  "nitrate_level", "turbidity", "dissolved_oxygen", "conductivity",
]);

export default function DataTable({ siteFilter, dateFrom, dateTo }) {
  const [data, setData] = useState({ entries: [], total: 0, total_pages: 1 });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState("asc");

  useEffect(() => {
    setPage(1);
  }, [siteFilter, dateFrom, dateTo]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getEntries({
      site: siteFilter || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      page,
      per_page: 50,
    }).then((result) => {
      if (cancelled) return;
      setData(result);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [page, siteFilter, dateFrom, dateTo]);

  const sorted = useMemo(() => {
    if (!sortKey) return data.entries;
    const copy = [...data.entries];
    copy.sort((a, b) => {
      const aVal = a[sortKey];
      const bVal = b[sortKey];
      const aNum = NUMERIC_KEYS.has(sortKey) ? parseFloat(aVal) : NaN;
      const bNum = NUMERIC_KEYS.has(sortKey) ? parseFloat(bVal) : NaN;
      let cmp;
      if (!isNaN(aNum) && !isNaN(bNum)) {
        cmp = aNum - bNum;
      } else {
        cmp = String(aVal ?? "").localeCompare(String(bVal ?? ""));
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [data.entries, sortKey, sortDir]);

  function handleSort(key) {
    if (sortKey === key) {
      if (sortDir === "asc") setSortDir("desc");
      else { setSortKey(null); setSortDir("asc"); }
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  if (loading) return <div className="loading">Loading data...</div>;

  return (
    <div className="table-section">
      <h2 className="chart-section-heading">Entries ({data.total} total)</h2>
      <table className="data-table">
        <thead>
          <tr>
            {COLS.map((col) => (
              <th
                key={col.key}
                className={`sortable ${sortKey === col.key ? "sorted-" + sortDir : ""}`}
                onClick={() => handleSort(col.key)}
              >
                {col.label}
                {sortKey === col.key && (
                  <span className="sort-arrow">{sortDir === "asc" ? " ▲" : " ▼"}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody key={`${page}-${sortKey || "none"}-${sortDir}`}>
          {sorted.map((row) => (
            <tr key={row.ec5_uuid}>
              {COLS.map((col) => (
                <td key={col.key}>{formatCell(row[col.key], col.key)}</td>
              ))}
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={COLS.length} style={{ textAlign: "center", padding: 24, color: "#4b5563" }}>
                No entries found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {data.total_pages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span>
            Page {page} of {data.total_pages}
          </span>
          <button disabled={page >= data.total_pages} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function formatCell(val, key) {
  if (val === null || val === undefined || val === "") return "—";
  if (key === "sample_date") return fmtDate(val);
  if (key === "water_depth_cm") {
    const n = parseFloat(val);
    return isNaN(n) ? val : n.toFixed(1);
  }
  return String(val);
}
