"""what3words normalisation and the 4-rung location resolution ladder.

v1's mistake (see `backend/w3w_sites.py`) was pinning an unrecognised what3words
address to the *nearest* known site by Haversine distance -- inventing a
location. v2 never does that. A what3words address either resolves to one of
the 48 points in the owner's reference table via one of three documented,
auditable rungs, or it is honestly `unlocated`.

This module is pure and has no database or EpiCollect-payload dependency, so
it can be unit tested directly: give it a raw string and a reference table,
get back a `Resolution`.

The ladder, in order (first match wins):

1. **exact**            -- normalised string equals a reference w3w.
2. **documented_rename** -- one of two renames the owner has confirmed in the
   reference spreadsheet / volunteers' own free text (see
   `DOCUMENTED_RENAMES`).
3. **fuzzy**             -- each of the three dot-separated words is within
   Levenshtein distance <= 2 of the corresponding word in a *single* reference
   w3w. If more than one reference row qualifies, it is not attempted --
   ambiguous fuzzy matches are refused, not guessed.
4. **unlocated**         -- everything else. The original text is preserved
   (callers should store it verbatim as `observations.w3w_raw`); no
   coordinates are ever invented for it.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
REFERENCE_CSV = DATA_DIR / "location_reference.csv"

# Four what3words addresses appear in the data but are missing from the
# owner's own LocationReferenceTable.xlsx. The owner had them looked up from
# the public what3words coordinate service instead (see that file's header
# comments for full provenance) -- a separate file, owned and written by
# another agent, so it never collides with `location_reference.csv` above.
# Loaded and merged in here so resolution treats all 52 points uniformly;
# `locations.source` in the database keeps the two provenances distinguishable
# ('reference_table' vs 'supplement').
SUPPLEMENT_CSV = DATA_DIR / "location_reference_supplement.csv"

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# Matches the first `word.word.word` token in a string, after normalisation.
# Words are plain lowercase letters -- what3words never uses digits or
# punctuation inside a word.
_W3W_TOKEN_RE = re.compile(r"[a-z]+\.[a-z]+\.[a-z]+")

# Collapses whitespace that sits around a literal dot, e.g. "channel. riskiest"
# -> "channel.riskiest", "reset.spires.supply.       NL" -> ...supply.NL
# (harmless -- the token regex above still stops at the next dot either way).
_DOT_WHITESPACE_RE = re.compile(r"\s*\.\s*")


def normalize_w3w(raw: str | None) -> str | None:
    """Normalise a raw what3words-ish string per the addendum's rule:

    lowercase, strip ``///``, commas -> dots, collapse whitespace around
    dots, then extract the first ``word.word.word`` token found anywhere in
    the string. Returns ``None`` if no such token exists (e.g. the field was
    blank, or held only free-text / initials with no what3words shape).

    Deliberately tolerant of trailing junk (volunteer initials, a
    parenthetical aside like "(formerly ...)") because those sit *after* the
    genuine token and `re.search` finds the left-most match -- exactly the
    "first token" the addendum asks for.
    """
    if not raw:
        return None
    s = raw.lower()
    s = s.replace("///", "")
    s = s.replace(",", ".")
    s = _DOT_WHITESPACE_RE.sub(".", s)
    m = _W3W_TOKEN_RE.search(s)
    return m.group(0) if m else None


# ---------------------------------------------------------------------------
# Rung 2: documented renames
# ---------------------------------------------------------------------------

# Both confirmed by the owner (V2_SPEC_ADDENDUM.md, Change 3):
#   - the reference spreadsheet's own note against `good.examples.bulldozer`
#     reads "Change to title rafters cyber (roughly 20)".
#   - volunteers wrote "hers.steered.beakers (formerly mango.batches.duke)"
#     in the free-text field.
DOCUMENTED_RENAMES: dict[str, str] = {
    "good.examples.bulldozer": "title.rafters.cyber",
    "hers.steered.beakers": "mango.batches.duke",
}

# ---------------------------------------------------------------------------
# Rung 3: fuzzy (per-word Levenshtein <= 2, unique match only)
# ---------------------------------------------------------------------------

_FUZZY_MAX_DISTANCE = 2


def levenshtein(a: str, b: str) -> int:
    """Standard edit distance (insertions/deletions/substitutions), O(len(a)*len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(
                prev[j] + 1,       # deletion
                cur[j - 1] + 1,    # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = cur
    return prev[-1]


def fuzzy_match(normalized: str, reference: dict[str, dict]) -> str | None:
    """Return the unique reference w3w within per-word edit distance <= 2, or None.

    `normalized` must already be a `word.word.word` string (as produced by
    `normalize_w3w`). Compares word-for-word by position against every
    reference address; a candidate reference row qualifies only if *all
    three* of its words are within distance 2 of the corresponding word in
    `normalized`. If zero or more than one reference row qualifies, returns
    None -- an ambiguous fuzzy match is refused, never guessed.
    """
    words = normalized.split(".")
    if len(words) != 3:
        return None

    matches = []
    for ref_w3w in reference:
        ref_words = ref_w3w.split(".")
        if len(ref_words) != 3:
            continue
        if all(
            levenshtein(w, rw) <= _FUZZY_MAX_DISTANCE
            for w, rw in zip(words, ref_words)
        ):
            matches.append(ref_w3w)

    if len(matches) == 1:
        return matches[0]
    return None


# ---------------------------------------------------------------------------
# Reference table
# ---------------------------------------------------------------------------


def load_reference(path: Path | str = REFERENCE_CSV) -> dict[str, dict]:
    """Load the 48-row reference table into {w3w: {river_order, latitude, longitude}}.

    `river_order` is a float even though this file's own values are all
    whole numbers -- the supplement file's positions are fractional (a point
    between two reference MY_IDs), and the two must sort together on one
    numeric column.
    """
    reference: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w3w = row["w3w"].strip().lower()
            reference[w3w] = {
                "river_order": float(row["river_order"]),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
    return reference


def load_supplement(path: Path | str = SUPPLEMENT_CSV) -> dict[str, dict]:
    """Load the owner-sourced supplement of points missing from the reference
    spreadsheet. Lines starting with '#' are provenance notes, not data.

    Each entry carries the same `river_order`/`latitude`/`longitude` shape as
    `load_reference`, plus `source='supplement'` and, where present,
    `nearest_reference` / `distance_to_nearest_m` / `needs_owner_review` /
    `note` -- used to raise the "possible duplicate" review_queue rows for
    the two points that sit within riverbank-width of an existing reference
    point (see `V2_SPEC_ADDENDUM_2.md` follow-up and the CSV's own header).
    """
    supplement: dict[str, dict] = {}
    if not Path(path).exists():
        return supplement
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f if not line.lstrip().startswith("#")]
    for row in csv.DictReader(lines):
        w3w = row["w3w"].strip().lower()
        supplement[w3w] = {
            "river_order": float(row["river_order"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "source": "supplement",
            "nearest_reference": (row.get("nearest_reference") or "").strip() or None,
            "distance_to_nearest_m": (
                float(row["distance_to_nearest_m"])
                if (row.get("distance_to_nearest_m") or "").strip()
                else None
            ),
            "needs_owner_review": (row.get("needs_owner_review") or "").strip().lower() == "yes",
            "note": (row.get("note") or "").strip() or None,
        }
    return supplement


def load_all_locations(
    reference_path: Path | str = REFERENCE_CSV,
    supplement_path: Path | str = SUPPLEMENT_CSV,
) -> dict[str, dict]:
    """The reference table and the supplement, merged into one resolution table.

    Every entry carries `river_order`, `latitude`, `longitude`, `source`
    ('reference_table' or 'supplement'). This is what should be passed as
    `reference` to `resolve_w3w` / `fuzzy_match` so a what3words address in
    the supplement resolves exactly like one in the owner's own spreadsheet
    (both are rung-1 exact matches) -- the *only* difference is provenance,
    tracked via `source`, never behaviour.
    """
    combined: dict[str, dict] = {}
    for w3w, row in load_reference(reference_path).items():
        combined[w3w] = {**row, "source": "reference_table"}
    combined.update(load_supplement(supplement_path))
    return combined


# ---------------------------------------------------------------------------
# The ladder itself
# ---------------------------------------------------------------------------


@dataclass
class Resolution:
    raw: str                       # verbatim input text (-> observations.w3w_raw)
    normalized: str | None         # post rung-1 normalisation, or None if no token found
    w3w: str | None                # canonical resolved location, or None
    status: str                    # 'located' | 'unlocated'
    match_type: str | None         # 'exact' | 'documented_rename' | 'fuzzy' | None
    note: str | None = None
    flags: list[str] = field(default_factory=list)


def resolve_w3w(raw_text: str | None, reference: dict[str, dict]) -> Resolution:
    """Run the 4-rung resolution ladder against one raw location string.

    Never invents a location: if nothing on the ladder matches, the result
    is `status='unlocated'`, `w3w=None` -- the raw text is preserved on the
    `Resolution` for the caller to store as `w3w_raw`.
    """
    raw = (raw_text or "").strip()
    normalized = normalize_w3w(raw)

    if normalized is None:
        return Resolution(
            raw=raw, normalized=None, w3w=None, status="unlocated",
            match_type=None, note="no what3words-shaped token found in the text",
        )

    # Rung 1: exact (normalisation already applied above).
    if normalized in reference:
        return Resolution(
            raw=raw, normalized=normalized, w3w=normalized, status="located",
            match_type="exact", note=None,
        )

    # Rung 2: documented rename.
    if normalized in DOCUMENTED_RENAMES:
        target = DOCUMENTED_RENAMES[normalized]
        if target in reference:
            return Resolution(
                raw=raw, normalized=normalized, w3w=target, status="located",
                match_type="documented_rename",
                note=f"documented rename: '{normalized}' -> '{target}'",
            )

    # Rung 3: fuzzy (unique per-word match only).
    fuzzy_target = fuzzy_match(normalized, reference)
    if fuzzy_target is not None:
        return Resolution(
            raw=raw, normalized=normalized, w3w=fuzzy_target, status="located",
            match_type="fuzzy",
            note=f"fuzzy match (per-word edit distance <= {_FUZZY_MAX_DISTANCE}): "
                 f"'{normalized}' -> '{fuzzy_target}'",
        )

    # Rung 4: unlocated. Never guess.
    return Resolution(
        raw=raw, normalized=normalized, w3w=None, status="unlocated",
        match_type=None,
        note="not found in the reference table (exact / documented_rename / fuzzy all failed)",
    )
