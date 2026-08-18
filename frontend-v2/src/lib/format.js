// Formatting helpers. British English, DD/MM/YYYY dates, spelled-out units.

// The owner's LocationReferenceTable.xlsx gives coordinates and river
// order for 48 points; only ~44 have ever actually been sampled (see
// V2_SPEC_ADDENDUM.md Change 3). Used as a fallback denominator for "point
// N on the river, of 48 mapped" when an API response doesn't state its own
// total — never say "of 48 sampled", which the data doesn't support.
export const TOTAL_MAPPED_LOCATIONS = 48;

// Decimal places per parameter, matching the backend's rounding rules
// (3dp for mg/L parameters, 1dp for NTU / µS/cm / cm).
const DECIMALS_BY_UNIT = {
  'mg/L': 3,
  NTU: 1,
  'µS/cm': 1,
  cm: 1,
};

export function decimalsForUnit(unit) {
  return DECIMALS_BY_UNIT[unit] ?? 2;
}

export function formatValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const dp = decimalsForUnit(unit);
  return Number(value).toFixed(dp);
}

// Full unit name spelled out once, for axis labels and first mentions.
const UNIT_NAMES = {
  'mg/L': 'milligrams per litre',
  NTU: 'nephelometric turbidity units',
  'µS/cm': 'microsiemens per centimetre',
  cm: 'centimetres',
};

export function unitLongName(unit) {
  return UNIT_NAMES[unit] || unit;
}

// "Phosphate (mg/L — milligrams per litre)"
export function spelledOutUnit(unit) {
  if (!unit) return '';
  const long = UNIT_NAMES[unit];
  return long ? `${unit} — ${long}` : unit;
}

export function formatValueWithUnit(value, unit) {
  const v = formatValue(value, unit);
  if (v === '—') return v;
  return `${v} ${unit}`;
}

// A measurement can be more than a plain number — see the addendum's
// cleaning rules. `qualifier` says which case this is; these helpers turn
// that into honest, plain-English wording rather than presenting every
// number as an equally-precise exact reading.
const QUALIFIER_NOTE = {
  below_detection: 'upper bound — the test kit could only say "less than this"',
  range_midpoint: 'the midpoint of a range the test kit gave',
  band_range: 'an estimate — the test strip only gave a range',
  zero_reported: 'recorded as none/nil',
};

export function qualifierNote(qualifier) {
  return QUALIFIER_NOTE[qualifier] || null;
}

// The reading formatted with its qualifier made honest rather than hidden,
// e.g. "< 0.02 mg/L" for a below-detection reading, "~0.150 mg/L" for a
// range midpoint, "10–25 mg/L (est. 17.5)" for a test-strip band. Returns
// null when there is no numeric value at all (an ordinal or free-text
// observation — see `isWrittenObservation` / CategoryChart.jsx).
export function formatReading(point, unit) {
  if (!point || point.value === null || point.value === undefined) return null;
  const v = formatValue(point.value, unit);
  if (point.qualifier === 'below_detection') return `< ${v} ${unit}`;
  if (point.qualifier === 'range_midpoint') return `~${v} ${unit}`;
  if (point.qualifier === 'band_range' && point.value_low != null && point.value_high != null) {
    return `${formatValue(point.value_low, unit)}–${formatValue(point.value_high, unit)} ${unit} (est. ${v})`;
  }
  return `${v} ${unit}`;
}

// True when a reading was recorded as free-text prose ("in spate", a
// flow note) rather than a number OR a recognised category — the cleaning
// pipeline deliberately never invents a number or forces an uncertain
// category for these (see V2_SPEC_ADDENDUM_2.md Rule B).
export function isWrittenObservation(point) {
  if (!point || point.value !== null && point.value !== undefined) return false;
  if (point.qualifier === 'ordinal' && point.category && point.category !== 'flow_note') return false;
  return !!point.value_raw;
}

// True for a reading classified onto a word scale (Clear/Cloudy/Muddy…) —
// never a number, never WFD-band-classified. See lib/categories.js.
export function isOrdinalReading(point) {
  return !!point && point.qualifier === 'ordinal' && !!point.category && point.category !== 'flow_note';
}

// True for a reading given as a range by a test strip (e.g. nitrate
// "10-25") rather than a single confident point.
export function isRangeReading(point) {
  return !!point && point.qualifier === 'band_range' && point.value_low != null && point.value_high != null;
}

// Splits a mixed points/readings array into the three kinds a v2 chart may
// need to show — see V2_SPEC_ADDENDUM_2.md. Numeric includes exact,
// below_detection, range_midpoint and band_range readings (all have a
// `value`); ordinal is the word-scale readings (Clear/Cloudy/…); written
// is genuine free-text with no number and no confident category. Charts
// must show numeric and ordinal separately, never merged into one figure.
export function partitionPoints(points) {
  const numeric = [];
  const ordinal = [];
  const written = [];
  for (const p of points || []) {
    if (isOrdinalReading(p)) ordinal.push(p);
    else if (p.value !== null && p.value !== undefined) numeric.push(p);
    else if (p.value_raw) written.push(p);
  }
  return { numeric, ordinal, written };
}

// Dates: DD/MM/YYYY, from a 'YYYY-MM-DD' string or Date.
export function formatDate(input) {
  if (!input) return '—';
  const d = input instanceof Date ? input : new Date(`${input}T00:00:00`);
  if (Number.isNaN(d.getTime())) return String(input);
  const dd = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const yyyy = d.getFullYear();
  return `${dd}/${mm}/${yyyy}`;
}

// "3 June 2026" — used in prose where a numeric date reads awkwardly.
export function formatDateLong(input) {
  if (!input) return '—';
  const d = input instanceof Date ? input : new Date(`${input}T00:00:00`);
  if (Number.isNaN(d.getTime())) return String(input);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}

export function daysAgo(input) {
  if (!input) return null;
  const d = input instanceof Date ? input : new Date(`${input}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  const ms = Date.now() - d.getTime();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

// "3 days ago" / "today" / "12 weeks ago" — for "last sampled" style copy.
export function formatRelativeDate(input) {
  const days = daysAgo(input);
  if (days === null) return '—';
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 14) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  if (days < 730) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}

const ORDINAL_SUFFIXES = { one: 'st', two: 'nd', few: 'rd', other: 'th' };
const pr = typeof Intl !== 'undefined' ? new Intl.PluralRules('en-GB', { type: 'ordinal' }) : null;

// 1 -> "1st", 2 -> "2nd", 26 -> "26th"
export function ordinal(n) {
  if (n === null || n === undefined) return '';
  const rule = pr ? pr.select(n) : 'other';
  return `${n}${ORDINAL_SUFFIXES[rule] || 'th'}`;
}

export function pluralise(n, singular, plural = `${singular}s`) {
  return n === 1 ? singular : plural;
}

export function formatCount(n, singular, plural) {
  return `${n} ${pluralise(n, singular, plural)}`;
}
