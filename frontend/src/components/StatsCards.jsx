import { fmtDate } from "../utils";

export default function StatsCards({ stats }) {
  if (!stats) {
    return (
      <div className="stats-grid">
        {[1, 2, 3].map((i) => (
          <div key={i} className="stat-card">
            <div className="label">Loading...</div>
            <div className="value">—</div>
          </div>
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Total Entries", value: stats.total_entries.toLocaleString() },
    { label: "Monitoring Sites", value: stats.total_sites },
    {
      label: "Date Range",
      value: stats.date_from
        ? `${fmtDate(stats.date_from)} – ${fmtDate(stats.date_to)}`
        : "No data",
    },
  ];

  return (
    <div className="stats-grid">
      {cards.map((c) => (
        <div key={c.label} className="stat-card">
          <div className="label">{c.label}</div>
          <div className="value">{c.value}</div>
        </div>
      ))}
    </div>
  );
}
