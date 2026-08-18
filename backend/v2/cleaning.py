"""raw EpiCollect payload -> measurements + cleaning_log (+ review_queue suggestions).

Implements the cleaning table in `V2_SPEC_ADDENDUM.md` ("Change 2"), as
revised and considerably expanded by `V2_SPEC_ADDENDUM_2.md` ("recover data,
don't discard it"). The second addendum overrides the first wherever they
disagree; the places that changed are called out below.

THE GOVERNING PRINCIPLE, unchanged by either addendum: transform the
*representation*, never the *measurement*. `value_raw` is always the exact
submitted text. Every transformation is logged. Nothing is ever silently
rescaled. Nothing is ever guessed into the database -- when a reading is
genuinely ambiguous it goes to the review queue for a human, never auto-
applied (`manual_corrections` is the only route by which a human judgement
changes a value, and every application of one is itself logged).

What addendum 2 changes in practice:

  * Rule A -- mechanical fixes (unit stripping, ppm<->mg/L equivalence,
    comma decimals, letter-O-for-zero, doubled/leading/trailing decimal
    points, unicode look-alikes, and unit *conversion* -- not just
    stripping -- for water depth) are now required, not merely permitted.
    Addendum 1 would have thrown many of these into `non_numeric`; addendum
    2 asks that anything mechanically recoverable be recovered and logged.
  * Rule B -- turbidity (and verbal water-depth readings) become an
    *ordinal category* (`category` + `category_rank`), never a fabricated
    number. This the single biggest change: 388 of 416 turbidity readings
    are words, and addendum 1's `non_numeric`/`usable=0` treatment would
    have thrown all of them out of every chart and statistic. They are
    real, honestly-recorded data; they are just not measured on a numeric
    scale.
  * Rule C -- ranges (`"10-25"`) get `value_low`/`value_high` plus a
    midpoint `value`, `qualifier='band_range'`. Where a volunteer wrote
    their own figure inside the range ("10-25 (20)"), that figure is used
    as `value` instead of the midpoint -- they were there, we were not.
  * Rule D -- genuinely ambiguous readings (a decimal typed as a space, two
    numbers in one field, an unexplained "3/10" scale, ...) are queued for
    the owner via `review_queue`, never guessed and never silently dropped.
  * Rule E -- implausible numeric values are still never rescaled, but are
    now also queued with a (never auto-applied) suggestion when there's an
    obvious mechanical explanation.

This module is pure: it has no database dependency. `clean_value()` takes a
raw string and a parameter name and returns a `Cleaned` result plus a list
of `LogEntry` objects; `backend/v2/ingest.py` is what actually writes rows.
Two things addendum 2 asks for that need visibility across the *whole*
dataset (a location's peer median, for implausible-value suggestions) are
therefore implemented as a second pass in `ingest.py`, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

PARAMETERS = [
    "phosphate",
    "ammonia",
    "nitrate",
    "turbidity",
    "dissolved_oxygen",
    "conductivity",
    "water_depth",
]

# Turbidity and water depth are read on a verbal/ordinal scale far more often
# than a numeric one (Addendum 2, Rule B) -- they get different treatment.
ORDINAL_PARAMS = {"turbidity", "water_depth"}

# (min, max) -- values outside this are physically impossible for the
# parameter, not merely unusual. Deciding `usable`, never rescaling.
PLAUSIBLE_RANGES = {
    "phosphate": (0.0, 10.0),
    "ammonia": (0.0, 10.0),
    "nitrate": (0.0, 200.0),
    "turbidity": (0.0, 1000.0),
    "dissolved_oxygen": (0.0, 20.0),
    "conductivity": (0.0, 5000.0),
    "water_depth": (0.0, 500.0),
}

# Trailing unit labels that match the column's own expected unit -- stripping
# them changes nothing about the measurement, only its written form.
SAFE_UNIT_LABELS = {
    "phosphate": {"mg/l", "mg", "mgl"},
    "ammonia": {"mg/l", "mg", "mgl"},
    "nitrate": {"mg/l", "mg", "mgl", "no3", "nitrates", "nitrate"},
    "dissolved_oxygen": {"mg/l", "mg", "mgl"},
    "turbidity": {"ntu"},
    "conductivity": {"µs/cm", "us/cm", "uscm", "uscm2", "us"},
}
# Water depth is handled separately below (DEPTH_UNIT_FACTORS) because some
# of its units need converting, not just stripping.

# ppm is chemically close enough to mg/L in a dilute freshwater sample that
# the addendum treats them as equivalent -- logged every time, not silently
# assumed (Addendum 2, Rule A).
PPM_EQUIVALENT_PARAMS = {"phosphate", "ammonia", "nitrate", "dissolved_oxygen"}

# Depth unit -> multiply-by-this-to-get-cm. This is a defined, reversible
# unit conversion the volunteer spelled out themselves (they wrote "1m" or
# "2.6ft"), not a guess -- categorically different from v1's "value looked
# high so divide by 10". Required by Addendum 2, Rule A ("Depth unit
# conversion -> cm").
DEPTH_UNIT_FACTORS = {
    "mm": 0.1,
    "cm": 1.0,
    "cms": 1.0,
    "m": 100.0,
    "inch": 2.54,
    "inches": 2.54,
    "in": 2.54,
    "ft": 30.48,
    "foot": 30.48,
    "feet": 30.48,
}

# Words meaning "no measurement was taken", as opposed to a description of
# what was observed. Addendum 1 named N/A, N/K, x, "not measured", "" as
# examples, not an exhaustive list; the real data has clear synonyms of the
# same thing (see the counted breakdown in the ingest report).
ABSENT_WORDS = {
    "",
    "n/a",
    "n/k",
    "nk",
    "na",
    "x",
    "-",
    "?",
    "not measured",
    "no data",
    "no test done",
    "not known",
    "unknown",
    "invalid",
    "insufficient kit to test",
    "insufficient supplies to test",
}

# Word forms of zero. "zero" added per Addendum 2, Rule A. Deliberately not
# applied to the ordinal parameters (turbidity/water_depth) -- see
# `clean_value`: a word there should land on the ordinal scale, or the
# review queue, never silently become a fabricated "0" on a scale v2 no
# longer emits numbers on.
NIL_WORDS = {"nil", "none", "zero"}

# Unicode look-alikes seen in the data (Addendum 2, Rule A).
_UNICODE_MAP = {
    "﹤": "<",  # SMALL LESS-THAN SIGN, e.g. "﹤25"
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH
    "−": "-",  # MINUS SIGN
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LogEntry:
    action: str
    value_before: str | None
    value_after: str | None
    reason: str


@dataclass
class ReviewItem:
    issue: str  # ambiguous_decimal | unparseable | implausible | ambiguous_location | multi_value
    suggestion: str | None
    suggestion_reason: str | None


@dataclass
class Cleaned:
    parameter: str
    value_raw: str
    value: float | None = None
    value_low: float | None = None
    value_high: float | None = None
    category: str | None = None
    category_rank: int | None = None
    qualifier: str = "absent"
    usable: int = 0
    flags: list[str] = field(default_factory=list)
    logs: list[LogEntry] = field(default_factory=list)
    review: ReviewItem | None = None


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------


def _normalize_unicode(s: str) -> tuple[str, bool]:
    out = s
    changed = False
    for bad, good in _UNICODE_MAP.items():
        if bad in out:
            out = out.replace(bad, good)
            changed = True
    return out, changed


def _split_parenthetical(s: str) -> tuple[str, str | None]:
    """Split off a trailing "(...)" annotation. Returns (core, annotation-or-None).

    Handles an unclosed paren too (e.g. "hers.steered.beakers (formerly
    ...)" style free text elsewhere in the data) -- everything from the
    first "(" onward is the annotation.
    """
    idx = s.find("(")
    if idx == -1:
        return s.strip(), None
    core = s[:idx].strip()
    annot = s[idx:].strip()
    return core, (annot or None)


_BELOW_RE = re.compile(r"(?i)^(?:<\s*|less\s+than\s+)([\d.,]+)")
_RANGE_RE = re.compile(r"^(-?[\d.,]+)\s*[-–]\s*(-?[\d.,]+)")
_O_FIX_RE = re.compile(r"^([Oo])([.,])([Oo0-9]+)")
_NUM_RE = re.compile(r"^(-?[0-9.,]+)")
_UNIT_TAIL_RE = re.compile(r"^\s*([A-Za-zµ/]*)")
_SCALE_OUT_OF_TEN_RE = re.compile(r"(?i)(\d+)\s*(?:/|from)\s*10\b")
_WHITESPACE_DECIMAL_RE = re.compile(r"^\d+\s+\d+$")


def _try_below_detection(s: str) -> dict | None:
    """`"<0.02"`, `"less than 0.02"` -> the bound itself, never halved."""
    m = _BELOW_RE.match(s)
    if not m:
        return None
    try:
        bound = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    logs = [LogEntry(
        "below_detection", s, str(bound),
        f"'{s}' recorded as an upper bound; value stored as the detection "
        f"limit itself, not halved",
    )]
    return {
        "value": bound, "value_low": 0.0, "value_high": bound,
        "qualifier": "below_detection", "flags": ["below_detection"], "logs": logs,
    }


def _try_range(s: str, parameter: str) -> dict | None:
    """`"10-25"` -> value_low/value_high + midpoint (Addendum 2, Rule C).

    If a volunteer wrote their own figure inside a trailing parenthetical
    ("10-25 (20)", "10-25 (approx 15 )"), that figure is used as `value`
    instead of the midpoint -- they were there, we were not -- and the band
    is still kept as value_low/value_high.
    """
    core, annot = _split_parenthetical(s)
    m = _RANGE_RE.match(core) or _RANGE_RE.match(s)
    if not m:
        return None
    try:
        lo = float(m.group(1).replace(",", "."))
        hi = float(m.group(2).replace(",", "."))
    except ValueError:
        return None
    if lo > hi:
        lo, hi = hi, lo
    value = round((lo + hi) / 2, 3)
    flags = ["band_range"]
    if parameter == "nitrate":
        flags.append("test_strip_band")
    logs = [LogEntry(
        "band_range", s, str(value),
        f"midpoint of reported range '{core}' ({lo}-{hi})",
    )]
    if annot:
        num_m = re.search(r"(-?[\d.,]+)", annot)
        if num_m:
            try:
                own = float(num_m.group(1).replace(",", "."))
            except ValueError:
                own = None
            if own is not None and lo <= own <= hi:
                value = own
                flags.append("volunteer_figure_used")
                logs.append(LogEntry(
                    "volunteer_figure_used", core, str(own),
                    f"used the volunteer's own figure from '{annot}' "
                    f"instead of the range midpoint",
                ))
    return {
        "value": value, "value_low": lo, "value_high": hi,
        "qualifier": "band_range", "flags": flags, "logs": logs,
    }


def _try_leading_number(s: str, parameter: str) -> tuple[str, dict | None]:
    """Read a leading number off the front of `s`, with mechanical fixes.

    Returns:
      ("ok", {"value":..., "logs":[...], "trailing": str|None})
      ("unrecognized_unit", {"value":..., "unit": str})  -- number found,
          but the trailing unit isn't one we know is safe to strip or
          convert for this parameter. Caller should queue it, not guess.
      ("not_numeric", None) -- doesn't start with a number at all.
    """
    logs: list[LogEntry] = []
    o_match = _O_FIX_RE.match(s)
    if o_match:
        frac = re.sub("[Oo]", "0", o_match.group(3))
        num_text = "0." + frac
        matched = s[: o_match.end()]
        logs.append(LogEntry(
            "letter_o_to_zero", matched, num_text,
            f"letter O read as digit 0 ('{matched}' -> '{num_text}')",
        ))
        after = s[o_match.end():]
    else:
        m = _NUM_RE.match(s)
        if not m or not m.group(1):
            return "not_numeric", None
        num_text = m.group(1)
        after = s[m.end():]
        if ".." in num_text:
            fixed = re.sub(r"\.{2,}", ".", num_text)
            logs.append(LogEntry(
                "doubled_decimal_point", num_text, fixed,
                f"doubled decimal point collapsed ('{num_text}' -> '{fixed}')",
            ))
            num_text = fixed
        if "," in num_text:
            fixed = num_text.replace(",", ".")
            logs.append(LogEntry(
                "comma_decimal", num_text, fixed,
                "decimal comma converted to a decimal point",
            ))
            num_text = fixed
        if num_text.startswith("."):
            fixed = "0" + num_text
            logs.append(LogEntry(
                "leading_decimal_point", num_text, fixed,
                "leading decimal point given a leading 0",
            ))
            num_text = fixed
        if num_text.endswith(".") and num_text.count(".") == 1:
            logs.append(LogEntry(
                "trailing_decimal_point", num_text, num_text.rstrip("."),
                "trailing decimal point noted (value unaffected)",
            ))

    try:
        num = float(num_text)
    except ValueError:
        return "not_numeric", None

    unit_m = _UNIT_TAIL_RE.match(after)
    unit_text = (unit_m.group(1) if unit_m else "").strip()
    remainder = after[unit_m.end():] if unit_m else after
    unit_low = unit_text.lower().rstrip(".")

    if unit_low:
        if parameter == "water_depth":
            factor = DEPTH_UNIT_FACTORS.get(unit_low) or DEPTH_UNIT_FACTORS.get(unit_low.rstrip("s"))
            if factor is None:
                return "unrecognized_unit", {"value": num, "unit": unit_text}
            if factor != 1.0:
                before = num
                num = round(num * factor, 3)
                logs.append(LogEntry(
                    "unit_conversion", f"{before}{unit_text}", str(num),
                    f"'{unit_text}' converted to cm (x{factor})",
                ))
            else:
                logs.append(LogEntry(
                    "strip_unit", unit_text, None, f"stripped unit '{unit_text}' (already cm)",
                ))
        elif unit_low == "ppm" and parameter in PPM_EQUIVALENT_PARAMS:
            logs.append(LogEntry(
                "unit_equivalence", unit_text, None,
                "ppm treated as equivalent to mg/L for a dilute freshwater sample",
            ))
        elif unit_low in SAFE_UNIT_LABELS.get(parameter, set()):
            logs.append(LogEntry("strip_unit", unit_text, None, f"stripped unit '{unit_text}'"))
        else:
            return "unrecognized_unit", {"value": num, "unit": unit_text}

    trailing = remainder.strip(" .,;:()") or None
    return "ok", {"value": num, "logs": logs, "trailing": trailing}


# ---------------------------------------------------------------------------
# Rule B: ordinal scales
# ---------------------------------------------------------------------------

# (phrase, category, rank). Checked as a substring anywhere in the text,
# left-most match wins, longest phrase breaks ties. These are all
# multi-word or otherwise distinctive enough that a substring match is safe.
_TURBIDITY_STRONG: list[tuple[str, str, int]] = [
    ("crystal clear", "crystal_clear", 1),
    ("very clear", "very_clear", 2),
    ("water very clear", "very_clear", 2),
    ("water clear", "clear", 3),
    ("fairly clear", "fairly_clear", 4),
    ("almost clear", "fairly_clear", 4),
    ("pretty clear", "fairly_clear", 4),
    ("quite clear", "fairly_clear", 4),
    ("clearer than last month", "fairly_clear", 4),
    ("very slightly cloudy", "slightly_cloudy", 5),
    ("slightly cloudy", "slightly_cloudy", 5),
    ("slight cloudiness", "slightly_cloudy", 5),
    ("slightly clouded", "slightly_cloudy", 5),
    ("slightly turbid", "slightly_cloudy", 5),
    ("slightly opaque", "slightly_cloudy", 5),
    ("slightly murky", "slightly_cloudy", 5),
    ("a little cloudy", "slightly_cloudy", 5),
    ("hazy", "slightly_cloudy", 5),
    ("fairly cloudy", "cloudy", 6),
    ("somewhat cloudy", "cloudy", 6),
    ("medium turbity", "cloudy", 6),
    ("so cloudy", "very_cloudy", 7),
    ("quite cloudy", "very_cloudy", 7),
    ("very dark", "very_cloudy", 7),
    ("fairly murky", "murky", 8),
]

# Single generic words -- only trusted as the FIRST word of the text (after
# splitting on whitespace/basic punctuation), to avoid false positives like
# "a slight amount of foam" (about foam, not clarity) matching "slight".
_TURBIDITY_WEAK: list[tuple[str, str, int]] = [
    ("clear", "clear", 3),
    ("clesr", "clear", 3),  # one observed typo, unambiguous
    ("cloudy", "cloudy", 6),
    ("medium", "cloudy", 6),
    ("turbid", "cloudy", 6),
    ("murky", "murky", 8),
    ("muddy", "muddy", 9),
    ("slight", "slightly_cloudy", 5),
]

# "Low"/"Very low"/"In spate"/"High" in the turbidity field describe flow,
# not clarity (Addendum 2, Rule B, explicit trap) -- matched only as the
# WHOLE text, never a substring, so they can't shadow a real clarity word.
_TURBIDITY_FLOW_WORDS = {"low", "very low", "in spate", "high"}

_DEPTH_STRONG: list[tuple[str, str, int]] = [
    ("very, very low", "very_low", 2),
    ("very low. small trickle", "very_low", 2),
    ("very low", "very_low", 2),
    ("tributary dry", "dry", 1),
    ("no water", "dry", 1),
]
_DEPTH_WEAK: list[tuple[str, str, int]] = [
    ("dry", "dry", 1),
    ("low", "low", 3),
    ("normal", "normal", 4),
    ("high", "high", 5),
]


def _first_word(low: str) -> str:
    parts = re.split(r"[\s,.;:]+", low.strip())
    return parts[0] if parts else ""


def _classify_ordinal(s: str, parameter: str) -> tuple[str, int | None, bool] | None:
    """Returns (category, rank, is_flow_note) or None if nothing matched."""
    if parameter == "turbidity":
        strong, weak, flow_words = _TURBIDITY_STRONG, _TURBIDITY_WEAK, _TURBIDITY_FLOW_WORDS
    elif parameter == "water_depth":
        strong, weak, flow_words = _DEPTH_STRONG, _DEPTH_WEAK, set()
    else:
        return None

    low = s.lower()
    best: tuple[tuple[int, int], str, int] | None = None
    for phrase, category, rank in strong:
        idx = low.find(phrase)
        if idx != -1:
            key = (idx, -len(phrase))
            if best is None or key < best[0]:
                best = (key, category, rank)
    if best:
        return best[1], best[2], False

    first = _first_word(low)
    for phrase, category, rank in weak:
        if first == phrase:
            return category, rank, False

    whole = re.sub(r"[.,;:]+$", "", low.strip())
    if whole in flow_words:
        return "flow_note", None, True
    return None


# ---------------------------------------------------------------------------
# Rule D: ambiguous-numeric detection (things that go to the review queue)
# ---------------------------------------------------------------------------


def _detect_ambiguous(s: str) -> dict | None:
    if _WHITESPACE_DECIMAL_RE.match(s):
        a, b = s.split()
        return {
            "issue": "ambiguous_decimal",
            "suggestion": f"{a}.{b}",
            "reason": f"'{s}' looks like a decimal point typed as a space; "
                      f"possible reading {a}.{b}, not applied automatically",
        }
    scale_m = _SCALE_OUT_OF_TEN_RE.search(s)
    if scale_m:
        return {
            "issue": "unparseable",
            "suggestion": None,
            "reason": f"'{s}' appears to use an unexplained 0-10 clarity scale "
                      f"(not NTU, not on the addendum's ordinal scale); not converted",
        }
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if len(nums) >= 2 and re.search(r"[A-Za-z]", s):
        return {
            "issue": "multi_value",
            "suggestion": None,
            "reason": f"'{s}' contains more than one number; not auto-resolved",
        }
    if "/" in s and re.search(r"\d", s):
        return {
            "issue": "unparseable",
            "suggestion": None,
            "reason": f"'{s}' does not match a recognised format",
        }
    return None


# ---------------------------------------------------------------------------
# Plausibility (Rule E) -- flagged and queued, never rescaled
# ---------------------------------------------------------------------------


def _finalize_numeric(result: Cleaned, parameter: str) -> Cleaned:
    if result.value is None:
        return result
    lo, hi = PLAUSIBLE_RANGES[parameter]
    if not (lo <= result.value <= hi):
        result.usable = 0
        result.flags = list(result.flags) + ["implausible"]
        result.logs.append(LogEntry(
            "implausible", str(result.value), str(result.value),
            f"{result.value} is outside the plausible range for {parameter} "
            f"({lo}-{hi}); kept exactly as submitted, never rescaled",
        ))
        result.review = ReviewItem(
            issue="implausible", suggestion=None,
            suggestion_reason=f"value outside the plausible range ({lo}-{hi} for {parameter})",
        )
    if parameter == "dissolved_oxygen" and result.value == 0.0:
        result.flags = list(result.flags) + ["suspect_zero"]
        result.logs.append(LogEntry(
            "suspect_zero", "0.0", "0.0",
            "0 mg/L dissolved oxygen would mean the river is dead here; "
            "near-certainly means 'not measured' -- queued rather than charted",
        ))
        if result.review is None:
            result.review = ReviewItem(
                issue="implausible", suggestion=None,
                suggestion_reason="0 mg/L dissolved oxygen is physically extreme "
                                   "for a flowing river; likely 'not measured'",
            )
    return result


# ---------------------------------------------------------------------------
# The main entry point
# ---------------------------------------------------------------------------


def clean_value(raw: str | None, parameter: str) -> Cleaned:
    """Clean one submitted value for one parameter. Pure function, no I/O.

    `value_raw` on the result is always exactly `raw` (or `""` for a missing
    field) -- never trimmed, never altered -- so the original submission is
    always recoverable regardless of what qualifier/value ends up stored.
    """
    assert parameter in PARAMETERS, f"unknown parameter {parameter!r}"
    value_raw = raw if raw is not None else ""
    s = value_raw.strip()

    if s == "":
        return Cleaned(
            parameter, value_raw, qualifier="absent", usable=0,
            logs=[LogEntry("absent", s, None, "field left blank")],
        )

    s2, unicode_changed = _normalize_unicode(s)
    logs: list[LogEntry] = []
    if unicode_changed:
        logs.append(LogEntry(
            "unicode_normalised", s, s2,
            "look-alike character normalised (e.g. ﹤ -> <, en/em dash -> -)",
        ))
    low = s2.lower().strip()

    if low in ABSENT_WORDS:
        logs.append(LogEntry("absent", s2, None, f"'{s2}' recorded as no measurement taken"))
        return Cleaned(parameter, value_raw, qualifier="absent", usable=0, logs=logs)

    if parameter not in ORDINAL_PARAMS:
        if low in NIL_WORDS:
            logs.append(LogEntry("reported_as_nil", s2, "0.0", f"word form '{s2}' recorded as zero"))
            result = Cleaned(
                parameter, value_raw, value=0.0, qualifier="zero_reported", usable=1,
                flags=["reported_as_nil"], logs=logs,
            )
            return _finalize_numeric(result, parameter)
        if s2 == "0":
            logs.append(LogEntry("zero_reported", s2, "0.0", "literal zero"))
            result = Cleaned(parameter, value_raw, value=0.0, qualifier="zero_reported", usable=1, logs=logs)
            return _finalize_numeric(result, parameter)

    below = _try_below_detection(s2)
    if below:
        logs.extend(below.pop("logs"))
        result = Cleaned(
            parameter, value_raw, qualifier=below["qualifier"], usable=1,
            value=below["value"], value_low=below["value_low"], value_high=below["value_high"],
            flags=below["flags"], logs=logs,
        )
        return _finalize_numeric(result, parameter)

    rng = _try_range(s2, parameter)
    if rng:
        logs.extend(rng.pop("logs"))
        result = Cleaned(
            parameter, value_raw, qualifier=rng["qualifier"], usable=1,
            value=rng["value"], value_low=rng["value_low"], value_high=rng["value_high"],
            flags=rng["flags"], logs=logs,
        )
        return _finalize_numeric(result, parameter)

    core, annot = _split_parenthetical(s2)
    kind, payload = _try_leading_number(core, parameter)
    if kind == "ok":
        logs.extend(payload["logs"])
        flags: list[str] = []
        if annot or payload.get("trailing"):
            flags.append("trailing_text_noted")
        result = Cleaned(
            parameter, value_raw, value=payload["value"], qualifier="exact", usable=1,
            flags=flags, logs=logs,
        )
        return _finalize_numeric(result, parameter)
    if kind == "unrecognized_unit":
        logs.append(LogEntry(
            "queued_for_review", s2, None,
            f"parsed as {payload['value']} but unit '{payload['unit']}' is not "
            f"recognised for {parameter}; not applied automatically",
        ))
        review = ReviewItem(
            issue="unparseable", suggestion=str(payload["value"]),
            suggestion_reason=f"parsed as {payload['value']} but the unit "
                               f"'{payload['unit']}' is not recognised for {parameter}",
        )
        return Cleaned(parameter, value_raw, qualifier="non_numeric", usable=0,
                        flags=["unit_unrecognized"], logs=logs, review=review)

    if parameter in ORDINAL_PARAMS:
        classified = _classify_ordinal(s2, parameter)
        if classified:
            category, rank, is_flow = classified
            has_digit = any(ch.isdigit() for ch in s2)
            if is_flow:
                logs.append(LogEntry(
                    "flow_note", s2, None,
                    "describes flow/water level, not clarity -- kept as a written "
                    "observation, not scored on the clarity scale",
                ))
                return Cleaned(parameter, value_raw, category="flow_note", qualifier="ordinal",
                                usable=0, flags=["flow_note"], logs=logs)
            if has_digit:
                logs.append(LogEntry(
                    "queued_for_review", s2, None,
                    f"contains both a qualitative judgement ('{category}') and a "
                    f"number; not auto-resolved",
                ))
                num_hint = re.search(r"-?\d+(?:\.\d+)?", s2)
                suggestion = f"category='{category}'"
                if num_hint:
                    suggestion += f" OR the number {num_hint.group(0)} in the text"
                review = ReviewItem(
                    issue="multi_value", suggestion=suggestion,
                    suggestion_reason=f"'{s2}' contains both a qualitative judgement "
                                       f"and a number",
                )
                return Cleaned(parameter, value_raw, qualifier="non_numeric", usable=0,
                                flags=["ambiguous"], logs=logs, review=review)
            logs.append(LogEntry(
                "ordinal", s2, category,
                f"classified as '{category}' on the {parameter} ordinal scale "
                f"(rank {rank}); no numeric value invented",
            ))
            return Cleaned(parameter, value_raw, category=category, category_rank=rank,
                            qualifier="ordinal", usable=1, logs=logs)
        num_hint = re.search(r"-?\d+(?:\.\d+)?", s2)
        suggestion = f"contains the number {num_hint.group(0)}" if num_hint else None
        logs.append(LogEntry("queued_for_review", s2, None,
                              "unrecognised text; queued rather than guessed"))
        review = ReviewItem(
            issue="unparseable", suggestion=suggestion,
            suggestion_reason="does not match a recognised word on the ordinal scale, "
                               "and is not a parseable number",
        )
        return Cleaned(parameter, value_raw, qualifier="non_numeric", usable=0,
                        logs=logs, review=review)

    ambiguous = _detect_ambiguous(s2)
    if ambiguous:
        logs.append(LogEntry("queued_for_review", s2, None, ambiguous["reason"]))
        review = ReviewItem(
            issue=ambiguous["issue"], suggestion=ambiguous.get("suggestion"),
            suggestion_reason=ambiguous["reason"],
        )
        return Cleaned(parameter, value_raw, qualifier="non_numeric", usable=0,
                        logs=logs, review=review)

    logs.append(LogEntry("non_numeric", s2, None,
                          "descriptive text kept as written, not converted to a number"))
    return Cleaned(parameter, value_raw, qualifier="non_numeric", usable=0, logs=logs)
