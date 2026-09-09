// "34 of 41 readings" — and when some were left out, the count says so in
// plain words. It used to link to a data-quality breakdown on All the
// data; that page section is gone now, so the count stands alone.
export default function UsableCount({ nUsable, nExcluded, singular = 'reading', plural }) {
  if (nUsable === null || nUsable === undefined) return null;
  const label = plural || `${singular}s`;
  const word = nUsable === 1 ? singular : label;
  if (!nExcluded) {
    return <span className="tabular">{nUsable} {word}</span>;
  }
  const total = nUsable + nExcluded;
  return <span className="tabular">{nUsable} of {total} {label}</span>;
}
