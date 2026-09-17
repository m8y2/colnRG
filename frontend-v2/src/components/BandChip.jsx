import { bandColorVar, bandGlyph, bandGloss, reachableBands, BAND_TEXT_ON_FILL } from '../lib/bands.js';

/**
 * The band identity chip used everywhere a WFD band is shown: a shape
 * glyph (never colour alone) in the band colour, the band word, and —
 * with what the band means for this parameter where there is room —
 * plain gloss on first appearance. Pass `parameter` so the gloss can be
 * the parameter-specific meaning (e.g. what "Moderate phosphate" means)
 * rather than the generic one.
 */
export function BandChip({ band, parameter, gloss, showGloss = true, size = 'base' }) {
  if (!band) {
    return <span className="band-chip text-muted">No reading yet</span>;
  }
  const text = gloss ?? bandGloss(band, parameter);
  const hasGloss = showGloss && !!text;
  // Where a gloss follows, it is its own line, not a continuation of the
  // band name joined by a colon: at narrow widths a colon-joined line
  // used to wrap on its own, leaving an orphaned ": Phosphate is high
  // enough…" underneath. `.band-chip--with-gloss` is scoped to this
  // component; the bare `.band-chip` class is also used standalone (no
  // gloss) elsewhere, see bands.css, and must stay a plain row there.
  return (
    <div className={`band-chip${hasGloss ? ' band-chip--with-gloss' : ''}${size === 'lg' ? ' band-chip--lg' : ''}`}>
      <span className="band-chip__name">
        <span className="band-chip__glyph" style={{ color: bandColorVar(band) }} aria-hidden="true">
          {bandGlyph(band)}
        </span>
        {band}
      </span>
      {hasGloss && <p className="band-chip__gloss">{text}</p>}
    </div>
  );
}

// A solid-fill pill, used where a compact, high-visibility marker is
// wanted (map popups). Text colour is picked per band so it always clears
// large-text contrast against the fill.
export function BandPill({ band }) {
  if (!band) return null;
  return (
    <span
      className="band-pill"
      style={{ background: bandColorVar(band), color: BAND_TEXT_ON_FILL[band] || '#ffffff' }}
    >
      <span aria-hidden="true">{bandGlyph(band)}</span>
      {band}
    </span>
  );
}

// Lists the bands THIS parameter can actually reach, with glyph, colour
// and meaning — the "legend that names each band in words" every band
// chart needs. Per-parameter, not a fixed five: dissolved oxygen and
// turbidity's own reference table never reaches "Bad" (see lib/bands.js),
// so a global five-band legend would show an impossible band.
export function BandLegend({ parameter, title }) {
  const bands = reachableBands(parameter);
  if (!bands.length) return null;
  return (
    <div>
      <p className="text-sm text-secondary mt-0" style={{ marginBottom: 4 }}>
        {title || `What the ${parameter?.label ? parameter.label.toLowerCase() : ''} bands mean`}
      </p>
      <ul className="band-legend" aria-label={title || 'What each band means'}>
        {bands.map((band) => (
          <li key={band} className="band-legend__item">
            <span className="band-glyph" style={{ color: bandColorVar(band) }} aria-hidden="true">
              {bandGlyph(band)}
            </span>
            <span className="band-legend__name">{band}</span>
            <span className="band-legend__gloss">: {bandGloss(band, parameter)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
