"""Numeric verification of a generated report narrative against the facts
pack it was generated from.

The LLM is told never to do arithmetic and never to cite a number that
isn't in the facts pack (`prompts.py`'s rules) — this module is what
actually checks that happened, rather than trusting the instruction. Every
narrative string in the report is scanned for numbers; each one has to
match something in the facts pack (within a small tolerance for
rounding), every `evidence_ids` entry has to be an id that actually
exists in the facts pack, and a short list of banned phrases must not
appear — including, per V2_SPEC_ADDENDUM_2.md, a model asserting a
numeric turbidity (or other word-only parameter) reading where the facts
pack only has ordinal (word) observations for it. That specific
fabrication — "cloudy" silently becoming "30 NTU" — is the reason this
whole rebuild exists, so it gets its own check rather than relying on the
generic number check to catch it indirectly.

`engine.py` calls `verify_report` once, and — if it fails — again after
one corrective retry. This module only ever reports a single pass; the
"repaired" vs "unverified" distinction between two passes is `engine.py`'s
job, not this module's.
"""

from __future__ import annotations

import re

from v2.wfd import PARAMETERS

# ---------------------------------------------------------------------------
# 1. Extracting numbers from narrative text
# ---------------------------------------------------------------------------

_DATE_DMY_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_DATE_ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ORDINAL_RE = re.compile(r"\b\d{1,3}(?:st|nd|rd|th)\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _strip_dates_and_ordinals(text: str) -> str:
    text = _DATE_DMY_RE.sub(" ", text)
    text = _DATE_ISO_RE.sub(" ", text)
    text = _ORDINAL_RE.sub(" ", text)
    return text


def _decimal_places(raw: str) -> int:
    return len(raw.split(".", 1)[1]) if "." in raw else 0


def extract_numbers_with_precision(text: str) -> list[tuple[float, int]]:
    """Every plain number in `text` as `(value, decimal_places)`:
    integers and decimals, with a trailing unit or `%` ignored and commas
    as thousands separators handled. Dates (DD/MM/YYYY and YYYY-MM-DD),
    ordinals (1st, 22nd) and bare years 1900-2100 are excluded — none of
    those are measurements. Decimal-place count is kept so a fact can be
    rounded to the same precision before comparing (a report saying
    "0.17" should match a facts-pack value of 0.172, not fail because of
    the extra digit)."""
    cleaned = _strip_dates_and_ordinals(text)
    out = []
    for match in _NUMBER_RE.finditer(cleaned):
        raw = match.group(0)
        if _YEAR_RE.fullmatch(raw):
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        out.append((value, _decimal_places(raw)))
    return out


# ---------------------------------------------------------------------------
# 2. Collecting narrative strings, ids, and numeric facts out of the
#    report and facts pack shapes
# ---------------------------------------------------------------------------

def _iter_strings(node):
    """Yield every string value found anywhere inside `node` (a report or
    a fragment of one), recursively."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _iter_strings(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_strings(item)


def _iter_evidence_ids(node, path="report"):
    """Yield (path, evidence_id) for every entry in an `evidence_ids`
    array anywhere inside `node`."""
    if isinstance(node, dict):
        for key, v in node.items():
            if key == "evidence_ids" and isinstance(v, list):
                for eid in v:
                    if isinstance(eid, str):
                        yield f"{path}.{key}", eid
            else:
                yield from _iter_evidence_ids(v, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _iter_evidence_ids(item, f"{path}[{i}]")


def collect_facts_numbers(facts_pack) -> list[float]:
    """Every numeric leaf value anywhere in the facts pack — this is the
    universe of figures a report is allowed to cite. This deliberately
    covers everything: statistics, counts (`n`, `n_usable`, `n_excluded`),
    category counts and `category_rank` for ordinal data, `value_low` /
    `value_high` for test-strip ranges, river positions, WFD thresholds —
    anything that is a plain number in the pack is fair game to mention,
    so nothing here needs special-casing by field name (per
    V2_SPEC_ADDENDUM_2.md: category counts and rank numbers must not be
    flagged as unmatched, and a range like "10 to 25" must match a
    `value_low`/`value_high` pair — both fall out of treating every
    numeric leaf as a valid citation)."""
    out: list[float] = []

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(facts_pack)
    return out


def collect_facts_ids(facts_pack) -> set[str]:
    """Every string found under an `"id"` key anywhere in the facts pack —
    the universe of ids a report's `evidence_ids` are allowed to cite."""
    out: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("id"), str):
                out.add(node["id"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(facts_pack)
    return out


# ---------------------------------------------------------------------------
# 3. Banned content
# ---------------------------------------------------------------------------

_BANNED_PHRASES = ("safe to swim", "drinking water")
_BANNED_WORD_PATTERNS = {
    "we": re.compile(r"\bwe\b", re.IGNORECASE),
    "I": re.compile(r"\bI\b"),
    "our": re.compile(r"\bour\b", re.IGNORECASE),
}

# How far, at most, a number is allowed to sit after a connector word like
# "was"/"of"/"measured" following a word-only parameter's name before it
# counts as a plausible invented reading rather than an unrelated digit
# elsewhere in the sentence (e.g. a category count).
_NUMERIC_CLAIM_WINDOW = 25


def _find_invented_numeric_claims(full_text: str, facts_pack: dict) -> list[dict]:
    """Per V2_SPEC_ADDENDUM_2.md: flag the narrative asserting a numeric
    reading for a parameter that, in this report's scope, was only ever
    recorded as words (turbidity described as "clear"/"cloudy" etc, not a
    meter reading). `facts_pack["words_only_parameters"]` is the list of
    such parameters for this report — see `facts.py`.

    Heuristic, not exact: requires either the unit immediately after a
    number (e.g. "6 NTU"), or the parameter's label followed within a
    short window by a connector word and then a number (e.g. "turbidity
    was 6"). A bare parameter name near an unrelated number (e.g.
    "Turbidity: 28 of 34 samples were Clear") should not match either
    pattern. False negatives are safer than false positives here: a
    missed case still has a chance to be caught as an unmatched number if
    the invented figure isn't in the facts pack; the point of this check
    is to name the specific mistake when it does show up.
    """
    words_only = facts_pack.get("words_only_parameters") if isinstance(facts_pack, dict) else None
    if not words_only:
        return []

    hits = []
    for param in words_only:
        meta = PARAMETERS.get(param, {})
        label = meta.get("label", param.replace("_", " "))
        unit = meta.get("unit", "")
        found = None

        if unit:
            unit_pattern = re.compile(rf"\d+(?:\.\d+)?\s?{re.escape(unit)}\b")
            m = unit_pattern.search(full_text)
            if m:
                found = m.group(0).strip()

        if not found:
            name_pattern = re.compile(
                rf"\b{re.escape(label)}\b[^.\n]{{0,15}}?\b(?:was|is|of|at|reading|measured|"
                rf"recorded)\b[^.\n]{{0,{_NUMERIC_CLAIM_WINDOW}}}?\d+(?:\.\d+)?",
                re.IGNORECASE,
            )
            m = name_pattern.search(full_text)
            if m:
                found = m.group(0).strip()

        if found:
            hits.append({
                "term": found,
                "reason": (
                    f"{label} was only recorded in words for this report (no meter reading is "
                    f"available here), so it must be described in words, never as a number or "
                    f"matched against the WFD {label.lower()} bands, which are meter readings."
                ),
            })
    return hits


def find_banned_terms(report: dict, facts_pack: dict | None = None) -> list[dict]:
    """Every banned phrase found in the report's narrative text: the
    fixed list from the build spec (landowner names, bathing/drinking-
    water advice, first person), any landowner name supplied via
    `facts_pack["banned_terms"]` for this report's scope, and — per
    V2_SPEC_ADDENDUM_2.md — an invented numeric reading for a parameter
    this report's facts pack marks as word-only."""
    facts_pack = facts_pack or {}
    hits: list[dict] = []
    full_text = "\n".join(_iter_strings(report))
    lower_text = full_text.lower()

    for phrase in _BANNED_PHRASES:
        if phrase in lower_text:
            hits.append({"term": phrase, "reason": "not something this scheme can responsibly claim"})

    for label, pattern in _BANNED_WORD_PATTERNS.items():
        if pattern.search(full_text):
            hits.append({"term": label, "reason": 'reports must not use "we", "I" or "our"'})

    for name in facts_pack.get("banned_terms", []) or []:
        name = (name or "").strip()
        if name and name.lower() in lower_text:
            hits.append({"term": name, "reason": "landowner names must never appear in a report"})

    hits.extend(_find_invented_numeric_claims(full_text, facts_pack))

    return hits


# ---------------------------------------------------------------------------
# 4. Putting it together
# ---------------------------------------------------------------------------

def verify_report(report: dict, facts_pack: dict) -> dict:
    """Check a generated report against the facts pack it was supposedly
    built from. Returns
    `{"status": "verified"|"unverified", "unmatched_numbers": [...],
      "invalid_evidence_ids": [...], "banned_terms": [...]}`.

    `status` here only ever reflects this one pass — `engine.py` is
    responsible for turning a first-pass failure followed by a
    second-pass success into "repaired" when it stores the result.
    """
    facts_numbers = collect_facts_numbers(facts_pack)
    facts_ids = collect_facts_ids(facts_pack)

    unmatched_numbers = []
    for text in _iter_strings(report):
        for value, dp in extract_numbers_with_precision(text):
            if not _number_in_facts(value, dp, facts_numbers):
                unmatched_numbers.append({
                    "value": _format_number(value, dp),
                    "context": _snippet(text),
                })

    invalid_evidence_ids = []
    for path, eid in _iter_evidence_ids(report):
        if eid not in facts_ids:
            invalid_evidence_ids.append({"id": eid, "path": path})

    banned_terms = find_banned_terms(report, facts_pack)

    status = "verified" if not (unmatched_numbers or invalid_evidence_ids or banned_terms) else "unverified"
    return {
        "status": status,
        "unmatched_numbers": unmatched_numbers,
        "invalid_evidence_ids": invalid_evidence_ids,
        "banned_terms": banned_terms,
    }


def _number_in_facts(value: float, dp: int, facts_numbers: list[float]) -> bool:
    for fv in facts_numbers:
        if round(fv, dp) == round(value, dp):
            return True
        # ±1% relative tolerance for derived figures (percentages, deltas,
        # anything rounded slightly differently than the facts pack).
        denom = max(abs(fv), 1e-9)
        if abs(fv - value) / denom <= 0.01:
            return True
    return False


def _format_number(value: float, dp: int) -> str:
    return f"{value:.{dp}f}"


def _snippet(text: str, width: int = 80) -> str:
    stripped = " ".join(text.split())
    return stripped[:width] + ("…" if len(stripped) > width else "")


# ---------------------------------------------------------------------------
# Formatting a failed verification back into a correction instruction
# ---------------------------------------------------------------------------

def format_verification_failures(verification: dict) -> str:
    """Turn a failed `verify_report` result into plain-English correction
    instructions, appended to the user prompt for the one allowed retry
    (see `engine.py`)."""
    lines = [
        "The previous draft failed an automatic check against the facts pack. Send the full "
        "corrected JSON object again, fixing these specific problems and changing nothing else "
        "that was already correct:",
    ]
    for item in verification.get("unmatched_numbers", []):
        lines.append(
            f'- The number "{item["value"]}" (near: "{item["context"]}") does not match any '
            "figure in the facts pack. Remove it, or replace it with a figure that is actually "
            "there."
        )
    for item in verification.get("invalid_evidence_ids", []):
        lines.append(
            f'- The evidence id "{item["id"]}" (in {item["path"]}) does not exist in the facts '
            "pack. Use an id that is actually listed there, or remove it."
        )
    for item in verification.get("banned_terms", []):
        reason = item["reason"].rstrip(".")
        lines.append(f'- The text uses "{item["term"]}" — {reason}. Remove or reword it.')
    return "\n".join(lines)
