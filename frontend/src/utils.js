export function fmtDate(d) {
  if (!d || d.length < 10) return d;
  return d.slice(8, 10) + "/" + d.slice(5, 7) + "/" + d.slice(0, 4);
}

export function fmtShortDate(d) {
  if (!d || d.length < 10) return d;
  return d.slice(8, 10) + "/" + d.slice(5, 7);
}

export const CHEMICALS = [
  { value: "phosphate", label: "Phosphate" },
  { value: "ammonia", label: "Ammonia" },
  { value: "nitrate", label: "Nitrate" },
  { value: "turbidity", label: "Turbidity" },
  { value: "dissolved_oxygen", label: "Dissolved Oxygen" },
  { value: "conductivity", label: "Conductivity" },
  { value: "water_depth", label: "Water Depth" },
];

export const OVERVIEW_CHEMICALS = CHEMICALS;
