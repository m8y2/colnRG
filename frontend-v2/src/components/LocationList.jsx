import { worstBand, bandColorVar, bandGlyph } from '../lib/bands.js';

/**
 * The accessible twin of `LocationMap` — the same locations, as a
 * keyboard- and screen-reader-usable list, always rendered beside the map
 * rather than as a fallback. A pin on a map conveys nothing to someone who
 * can't see or point at it; this list carries the same information
 * (position on the river, worst current band) in a form that does.
 *
 * `locations` must already be sorted source-to-Thames (by `river_order`,
 * which the caller sorts numerically). The number shown here is the
 * position in that sequence (1, 2, 3…), never the raw `river_order` value
 * itself — that's a fractional sort key (e.g. 15.98), not something to
 * put in front of a reader.
 */
export default function LocationList({ locations, onSelect, selected, title = 'All locations, source to Thames' }) {
  return (
    <div>
      <h3 style={{ fontSize: 'var(--fs-base)', marginBottom: 8 }}>{title}</h3>
      <ul className="location-list" aria-label={title}>
        {(locations || []).map((loc, i) => {
          const worst = worstBand(Object.values(loc.bands || {}));
          const isSelected = selected === loc.w3w;
          return (
            <li key={loc.w3w} className="location-list__item">
              <button
                type="button"
                className="location-list__button"
                aria-current={isSelected ? 'true' : undefined}
                onClick={() => onSelect(loc.w3w)}
              >
                <span className="location-list__order">#{i + 1}</span>
                <span className="location-list__label">{loc.w3w}</span>
                {worst ? (
                  <span className="band-chip" style={{ gap: 4 }}>
                    <span className="band-chip__glyph" style={{ color: bandColorVar(worst) }} aria-hidden="true">
                      {bandGlyph(worst)}
                    </span>
                    {worst}
                  </span>
                ) : (
                  <span className="text-muted text-sm">No readings yet</span>
                )}
              </button>
            </li>
          );
        })}
        {(!locations || locations.length === 0) && (
          <li className="location-list__item">
            <span style={{ display: 'block', padding: 'var(--space-3)' }} className="text-muted">
              No locations to show.
            </span>
          </li>
        )}
      </ul>
    </div>
  );
}
