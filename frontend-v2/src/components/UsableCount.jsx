// "34 of 41 readings" — and when some were left out, that count is a link
// to the data-quality section on All The Data, so anyone looking at any
// statistic in the app can see, in context, what was excluded and why.
// This is deliberately not a nav item of its own (see V2_SPEC_ADDENDUM.md
// discussion) — transparency about the cleaning is meant to surface where
// the numbers are, not wait to be found.
export default function UsableCount({ nUsable, nExcluded, singular = 'reading', plural }) {
  if (nUsable === null || nUsable === undefined) return null;
  const label = plural || `${singular}s`;
  const word = nUsable === 1 ? singular : label;
  if (!nExcluded) {
    return <span className="tabular">{nUsable} {word}</span>;
  }
  const total = nUsable + nExcluded;
  return (
    <a className="tabular" href="#/all-data/data-quality" title="See which readings were left out and why, on All the data">
      {nUsable} of {total} {label}
    </a>
  );
}
