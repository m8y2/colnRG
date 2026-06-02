import { lazy } from "react";

const TimeSeriesChart = lazy(() => import("./TimeSeriesChart"));

export default function OverviewChart({ chemical, onSwitch }) {
  const CHEMICALS = ["phosphate", "ammonia", "nitrate", "turbidity", "dissolved_oxygen", "conductivity", "water_depth"];
  const idx = CHEMICALS.indexOf(chemical);
  const cycle = () => {
    const next = (idx + 1) % CHEMICALS.length;
    onSwitch(CHEMICALS[next]);
  };

  return (
    <div className="chart-section" style={{ cursor: "pointer" }} onClick={cycle} title="Click to cycle chemicals">
      <TimeSeriesChart chemical={chemical} height={250} />
      <p style={{ fontSize: "0.7rem", color: "#6b7280", textAlign: "center", marginTop: 4 }}>
        Click to cycle through chemicals
      </p>
    </div>
  );
}
