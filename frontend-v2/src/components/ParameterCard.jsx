import { BandChip, BandLegend } from './BandChip.jsx';
import { isBanded } from '../lib/bands.js';

/**
 * A parameter explained in plain English. `compact` is used for the "river
 * right now" band strip (name + current band + one-liner); the full form
 * (What We Measure) adds why it matters, where it comes from, and what
 * every band this parameter can actually reach means (see BandLegend —
 * not every parameter reaches all five).
 */
export default function ParameterCard({ parameter, band, compact = false }) {
  const banded = isBanded(parameter);
  return (
    <div className="card parameter-card">
      <div className="parameter-card__head">
        <h3 style={{ margin: 0 }}>{parameter.label}</h3>
        <span className="parameter-card__unit">{parameter.unit}</span>
      </div>
      {banded && band !== undefined && <BandChip band={band} parameter={parameter} />}
      {!banded && (
        <p className="text-sm text-muted mt-0">
          {parameter.typical_range
            ? `No WFD band — used as a sanity check. Typical range here is ${parameter.typical_range.low}–${parameter.typical_range.high} ${parameter.unit}.`
            : 'No WFD band — this is context for the other readings, not a pass or fail measure.'}
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
