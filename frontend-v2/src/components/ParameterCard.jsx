import { BandChip, BandLegend } from './BandChip.jsx';
import { isBanded } from '../lib/bands.js';
import { unitLabel } from '../lib/format.js';

/**
 * A parameter explained in plain English. `compact` is used for the "river
 * right now" band strip (name + current band + one-liner); the full form
 * (What We Measure) adds why it matters, where it comes from, and what
 * every band this parameter can actually reach means (see BandLegend —
 * not every parameter reaches all five).
 */
export default function ParameterCard({ parameter, band, compact = false, overview }) {
  const banded = isBanded(parameter);
  // A parameter can have plenty of readings and still have no band --
  // turbidity is written down in words far more often than it is metered.
  // Saying "no reading yet" there would be false, and would look like the
  // rebuild had lost data. Say what was actually recorded instead.
  const words = overview?.n_ordinal_readings || 0;
  const numeric = overview?.n_readings || 0;
  const total = words + numeric;
  const showWordsInstead = !band && words > 0;
  return (
    <div className="card parameter-card">
      <div className="parameter-card__head">
        <h3 style={{ margin: 0 }}>{parameter.label}</h3>
        <span className="parameter-card__unit">{unitLabel(parameter.unit)}</span>
      </div>
      {banded && band && !showWordsInstead && <BandChip band={band} parameter={parameter} />}
      {showWordsInstead && (
        <p className="text-sm mt-0">
          <strong>{total} written observations</strong>
        </p>
      )}
      {!band && !showWordsInstead && overview && (
        <p className="text-sm text-muted mt-0">
          {numeric === 0
            ? 'Not being measured at the moment.'
            : `Only ${numeric} reading${numeric === 1 ? '' : 's'} so far, ${
                overview.band_withheld_reason || 'not enough to grade the river'
              }.`}
        </p>
      )}
      {!banded && (
        <p className="text-sm text-muted mt-0">
          {parameter.typical_range
            ? `There is no WFD band for ${parameter.label.toLowerCase()}. Readings are compared against the typical range for this river, ${parameter.typical_range.low} to ${parameter.typical_range.high} ${parameter.unit}.`
            : 'No WFD band; this is context for the other readings, not a pass or fail measure.'}
        </p>
      )}
      <p>{parameter.one_liner}</p>
      {!compact && (
        <>
          <h4 className="parameter-card__section-title">Why it matters</h4>
          <p>{parameter.why_it_matters}</p>
          <h4 className="parameter-card__section-title">Where it comes from</h4>
          <p>{parameter.where_from}</p>
          {banded && <BandLegend parameter={parameter} />}
        </>
      )}
    </div>
  );
}
