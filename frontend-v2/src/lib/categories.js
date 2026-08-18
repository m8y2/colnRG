// Ordinal (word-scale) categories for parameters volunteers observe by eye
// rather than measure with a meter — see V2_SPEC_ADDENDUM_2.md Rule B.
// Turbidity is mostly this: 388 of 416 turbidity readings are words like
// "Clear", not a number, and the addendum is explicit that classifying
// words into an ordered category is honest, while inventing an NTU number
// for them is not. These labels are the addendum's own fixed vocabulary
// (not derived from WFD thresholds), so — unlike wfd.js's bands — they are
// safe to keep here rather than fetched, in the same way BAND_GLYPH is.
//
// These are NEVER WFD bands: no colour here is a band colour, and nothing
// here is compared against the WFD NTU thresholds — a verbal "Clear"
// observation and a meter reading are different instruments and must
// never be presented as the same kind of number.

export const TURBIDITY_CATEGORIES = [
  { key: 'crystal_clear', rank: 1, label: 'Crystal clear' },
  { key: 'very_clear', rank: 2, label: 'Very clear' },
  { key: 'clear', rank: 3, label: 'Clear' },
  { key: 'fairly_clear', rank: 4, label: 'Fairly clear' },
  { key: 'slightly_cloudy', rank: 5, label: 'Slightly cloudy' },
  { key: 'cloudy', rank: 6, label: 'Cloudy' },
  { key: 'very_cloudy', rank: 7, label: 'Very cloudy' },
  { key: 'murky', rank: 8, label: 'Murky' },
  { key: 'muddy', rank: 9, label: 'Muddy' },
];

export const WATER_DEPTH_CATEGORIES = [
  { key: 'dry', rank: 1, label: 'Dry' },
  { key: 'very_low', rank: 2, label: 'Very low' },
  { key: 'low', rank: 3, label: 'Low' },
  { key: 'normal', rank: 4, label: 'Normal' },
  { key: 'high', rank: 5, label: 'High' },
];

export const CATEGORY_SCALES = {
  turbidity: TURBIDITY_CATEGORIES,
  water_depth: WATER_DEPTH_CATEGORIES,
};

// A single ordinal hue (blue), light-to-dark by rank — never the WFD band
// colours, since this is a position-in-a-sequence encoding, not a pass/fail
// one. Kept within the range the dataviz skill's ordinal check calls safe
// on both a light and a dark chart surface (no lighter than step 250, no
// darker than step 650). Falls back to repeating the ramp if a scale ever
// has more than nine steps.
const ORDINAL_RAMP = ['#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281'];

export function categoryScaleFor(parameterKey, fallbackPoints) {
  if (CATEGORY_SCALES[parameterKey]) return CATEGORY_SCALES[parameterKey];
  // Fall back to whatever categories are actually present in the data, so
  // a parameter this module doesn't know about yet still renders honestly
  // rather than being silently dropped.
  const seen = new Map();
  for (const p of fallbackPoints || []) {
    if (p.category && !seen.has(p.category)) {
      seen.set(p.category, { key: p.category, rank: p.category_rank ?? 0, label: p.category });
    }
  }
  return [...seen.values()].sort((a, b) => a.rank - b.rank);
}

export function categoryColor(index) {
  return ORDINAL_RAMP[index % ORDINAL_RAMP.length];
}
