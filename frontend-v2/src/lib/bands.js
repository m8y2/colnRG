// WFD band names, colours, shape glyphs and generic plain-English glosses.
//
// Deliberately does NOT hardcode the numeric thresholds (0.1ppm phosphate,
// etc.) — those are the backend's job (`v2/wfd.py`) and come from
// `GET /api/v2/parameters` as each parameter's `bands` + `direction`
// ("lower_better" | "higher_better" | null). Baking a second copy of that
// table into the frontend would risk it drifting out of sync with the one
// the backend actually classifies with.
//
// Not every parameter reaches all five bands: dissolved oxygen and
// turbidity's own reference table leaves "Poor" open-ended (there is no
// further number that makes a reading "Bad" — see wfd.py's module
// docstring), and conductivity/water depth aren't banded at all. Rather
// than guess which bands exist from the numbers, `reachableBands()` reads
// it straight off `parameter.band_meanings`, which only ever has a key for
// a band that parameter can actually land in — that is the one place this
// is authoritatively recorded, so every per-parameter legend in the app is
// driven from it instead of assuming all five bands apply everywhere.
//
// Band names are shown with what they mean for the river where there is
// room for it — see
// `bandGloss()` and the `BandChip` component.

export const BAND_ORDER = ['Excellent', 'Good', 'Moderate', 'Poor', 'Bad'];

// A distinct shape per band so meaning survives colour-blindness and
// greyscale printing — never rely on colour alone.
export const BAND_GLYPH = {
  Excellent: '▲',   // ▲ triangle up
  Good: '●',        // ● filled circle
  Moderate: '◆',    // ◆ diamond
  Poor: '▼',        // ▼ triangle down
  Bad: '✕',         // ✕ cross
};

export const BAND_CSS_VAR = {
  Excellent: '--band-excellent',
  Good: '--band-good',
  Moderate: '--band-moderate',
  Poor: '--band-poor',
  Bad: '--band-bad',
};


// Text colour to put ON a solid band-colour fill (band-pill) so it always
// clears large-text contrast, chosen per band rather than assumed white.
export const BAND_TEXT_ON_FILL = {
  Excellent: '#ffffff',
  Good: '#1a2b22',
  Moderate: '#3a2600',
  Poor: '#3a1400',
  Bad: '#ffffff',
};

// Higher = worse, for picking the single worst band across several
// parameters (e.g. colouring a map marker).
const SEVERITY = { Excellent: 0, Good: 1, Moderate: 2, Poor: 3, Bad: 4 };

export function bandColorVar(band) {
  return `var(${BAND_CSS_VAR[band] || '--text-muted'})`;
}

export function bandGlyph(band) {
  return BAND_GLYPH[band] || '?';
}

export function bandGloss(band, parameter) {
  return parameter?.band_meanings?.[band] ?? '';
}

export function bandSeverity(band) {
  return band in SEVERITY ? SEVERITY[band] : -1;
}

// Picks the most severe (worst) band from a list, ignoring nulls.
export function worstBand(bands) {
  let worst = null;
  for (const b of bands) {
    if (!b) continue;
    if (worst === null || bandSeverity(b) > bandSeverity(worst)) worst = b;
  }
  return worst;
}

// The bands a parameter can actually be classified into, in best-to-worst
// order — read off `band_meanings` (see module note above) rather than
// assumed. Returns [] for an unbanded parameter (conductivity, water depth).
export function reachableBands(parameter) {
  const meanings = parameter?.band_meanings;
  if (!meanings) return [];
  return BAND_ORDER.filter((b) => b in meanings);
}

export function isBanded(parameter) {
  return !!parameter?.bands && !!parameter?.band_meanings;
}

// Classify a numeric value using a parameter object from GET
// /api/v2/parameters ({ bands, band_meanings, direction }). Mirrors
// v2/wfd.py's classify_band exactly, including the fact that a parameter
// whose reachable bands stop at "Poor" (no Bad) never returns "Bad".
export function classifyBand(value, parameter) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const bounds = parameter?.bands;
  if (!bounds) return null;
  const reachable = reachableBands(parameter);
  const hasBad = reachable.includes('Bad');
  const higher = parameter.direction === 'higher_better';
  const meets = higher ? (v, b) => v >= b : (v, b) => v <= b;

  if (bounds.Excellent !== undefined && bounds.Excellent !== null && meets(value, bounds.Excellent)) return 'Excellent';
  if (bounds.Good !== undefined && bounds.Good !== null && meets(value, bounds.Good)) return 'Good';
  if (bounds.Moderate !== undefined && bounds.Moderate !== null && meets(value, bounds.Moderate)) return 'Moderate';
  if (hasBad && bounds.Poor !== undefined && bounds.Poor !== null && meets(value, bounds.Poor)) return 'Poor';
  return hasBad ? 'Bad' : 'Poor';
}

// Ordered plot-ready zones for chart shading, given a parameter object and
// a sensible max for the open top/bottom zone. Returns zones in the order
// they should be drawn, each as { band, from, to } in data units. Only
// includes the bands the parameter can actually reach.
export function bandZones(parameter, domainMax) {
  const bounds = parameter?.bands;
  if (!bounds) return [];
  const reachable = reachableBands(parameter);
  if (!reachable.length) return [];
  const hasBad = reachable.includes('Bad');
  const higher = parameter.direction === 'higher_better';

  if (higher) {
    const ordered = hasBad ? ['Bad', 'Poor', 'Moderate', 'Good', 'Excellent'] : ['Poor', 'Moderate', 'Good', 'Excellent'];
    const upper = hasBad
      ? { Bad: bounds.Poor, Poor: bounds.Moderate, Moderate: bounds.Good, Good: bounds.Excellent, Excellent: domainMax }
      : { Poor: bounds.Moderate, Moderate: bounds.Good, Good: bounds.Excellent, Excellent: domainMax };
    let prev = 0;
    const zones = [];
    for (const band of ordered) {
      const to = band === 'Excellent' ? Math.max(domainMax, upper[band] ?? domainMax) : upper[band];
      if (to === undefined || to === null) continue;
      zones.push({ band, from: prev, to });
      prev = to;
    }
    return zones;
  }

  // lower_better: Excellent is the lowest zone, the worst reachable band is
  // the open-ended top.
  const steps = ['Excellent', 'Good', 'Moderate'];
  const zones = [];
  let prev = 0;
  for (const band of steps) {
    const to = bounds[band];
    if (to === undefined || to === null) continue;
    zones.push({ band, from: prev, to });
    prev = to;
  }
  if (hasBad) {
    zones.push({ band: 'Poor', from: prev, to: bounds.Poor });
    prev = bounds.Poor;
    zones.push({ band: 'Bad', from: prev, to: Math.max(domainMax, prev * 1.15, prev + 1) });
  } else {
    zones.push({ band: 'Poor', from: prev, to: Math.max(domainMax, prev * 1.15, prev + 1) });
  }
  return zones;
}


/**
 * The band names from a location's `latest_bands`, which the API returns
 * as `{parameter: {value, date, band, qualifier}}` rather than as plain
 * strings. Parameters with no numeric reading come back null and are
 * dropped, so a location whose only recent readings are written
 * observations shows no band rather than a misleading one.
 */
export function latestBandNames(location) {
  const latest = location?.latest_bands || {};
  return Object.values(latest)
    .map((entry) => (entry && typeof entry === 'object' ? entry.band : entry))
    .filter(Boolean);
}
