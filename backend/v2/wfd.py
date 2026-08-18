"""Water Framework Directive (WFD) bands and plain-English parameter metadata.

This is the one place v2 defines "what good and bad look like" for each
measurement the Coln River Guardians take, and the one place it explains
each measurement in plain English. Every other v2 module — `insights.py`
for the maths, `api.py` for `GET /parameters`, and (eventually) the report
prompts — reads from here rather than repeating any of it.

The five thresholds are the Environment Agency's WFD bands for a Lowland
High Alkalinity river, as already used by this project (see the build
spec). Conductivity and water depth are not banded — conductivity has no
WFD standard and is only useful as a rough sanity check, and water depth
is context (it affects dilution) rather than a measure of pollution.

A note on the two open-ended rows in the source table (dissolved oxygen
and turbidity): every other parameter's "Poor" band has a closed upper
bound, so a reading beyond it falls into "Bad". Dissolved oxygen's Poor
band ("<4") and turbidity's Poor band ("≥20") are already open-ended in
the spec's own reference table — there is no further number beyond which
a reading becomes "Bad". Rather than invent a threshold the spec does not
give, `classify_band` treats those two parameters as having four reachable
bands (High/Good/Moderate/Poor), with Poor absorbing everything beyond
Moderate. This is called out again next to `classify_band` below.

Per V2_SPEC_ADDENDUM_2.md (Rule B), turbidity and water depth are also
recorded as an **ordinal scale** — most volunteers write a word ("Clear",
"Low"), not a number. `ORDINAL_SCALES` below is the plain-English label
and rank for each category. These readings never get a WFD band (the
bands are NTU thresholds; a word is not a measurement in NTU) and never
enter a mean — `insights.py` keeps them in a completely separate summary.
Per Rule G, `all_parameters()` can also flag a parameter as
`not_currently_measured` when actual reading counts (supplied by
`insights.py`, which owns the database) fall below a threshold owned here.
"""

from __future__ import annotations

# ── Band names, in order from best to worst ──────────────────────────────

BAND_NAMES = ["High", "Good", "Moderate", "Poor", "Bad"]

# A short, consistent plain-English gloss for each band name, independent
# of which parameter it is describing. The UI/report copy should always
# show the band name paired with this gloss on first use — "High" meaning
# *best* is not obvious to a first-time reader.
BAND_GLOSS = {
    "High": "the best band",
    "Good": "a healthy band",
    "Moderate": "a middle band — an early sign of a problem",
    "Poor": "a low band — a clear sign of a problem",
    "Bad": "the worst band",
}


def band_display(band: str | None) -> str | None:
    """'High' -> 'High — the best band'. Used anywhere a band name is
    first shown to a reader."""
    if band is None:
        return None
    gloss = BAND_GLOSS.get(band)
    return f"{band} — {gloss}" if gloss else band


# ── Parameter metadata ────────────────────────────────────────────────────
# Order matches the order these measurements are usually written up on the
# volunteers' record sheet, so the UI can iterate PARAMETER_ORDER directly.

PARAMETER_ORDER = [
    "phosphate",
    "ammonia",
    "nitrate",
    "dissolved_oxygen",
    "turbidity",
    "conductivity",
    "water_depth",
]

# Maps a v2 parameter key to the (TEXT, unguarded) column in `entries` that
# holds it. water_depth_cm is the one column that is already REAL in the
# schema, but the data still needs the same tolerant parsing as the rest.
PARAMETER_COLUMNS = {
    "phosphate": "phosphate_level",
    "ammonia": "ammonia_level",
    "nitrate": "nitrate_level",
    "dissolved_oxygen": "dissolved_oxygen",
    "turbidity": "turbidity",
    "conductivity": "conductivity",
    "water_depth": "water_depth_cm",
}

PARAMETERS = {
    "phosphate": {
        "key": "phosphate",
        "label": "Phosphate",
        "unit": "mg/L",
        "direction": "lower_better",
        "one_liner": "A nutrient. Too much feeds extra plant and algae growth.",
        "why_it_matters": (
            "Phosphate occurs naturally in small amounts, but extra phosphate "
            "acts like a fertiliser for the river. Too much lets algae and "
            "weeds grow far faster than usual, which can crowd out other "
            "plants and use up oxygen as the extra growth dies and rots."
        ),
        "where_from": (
            "Treated sewage, farm fertiliser and manure washed off fields, "
            "and some household cleaning products."
        ),
        "unit_equivalence_note": (
            "A few readings were written in parts per million (ppm) rather than milligrams "
            "per litre (mg/L). In water this dilute the two are the same number, so they are "
            "treated as equal."
        ),
        "bands": {"High": 0.1, "Good": 0.2, "Moderate": 0.4, "Poor": 0.7},
        "band_meanings": {
            "High": "Phosphate is naturally low, so it is not feeding extra algae growth.",
            "Good": "Phosphate is a little higher, but still low enough that algae growth is unlikely to be a problem.",
            "Moderate": "Phosphate is high enough that it could start feeding more algae and weed growth than the river can easily cope with.",
            "Poor": "Phosphate is high enough to regularly feed unwanted algae and weed growth.",
            "Bad": "Phosphate is very high. It can feed heavy algae growth, which uses up oxygen other river life needs.",
        },
    },
    "ammonia": {
        "key": "ammonia",
        "label": "Ammonia",
        "unit": "mg/L",
        "direction": "lower_better",
        "one_liner": "A waste chemical. High levels are harmful to fish and insects.",
        "why_it_matters": (
            "Ammonia is a waste product that is toxic to fish and river "
            "insects at high concentrations, and it uses up oxygen in the "
            "water as it breaks down."
        ),
        "where_from": (
            "Sewage effluent, and manure or slurry washed off farmland, "
            "especially after rain."
        ),
        "unit_equivalence_note": (
            "A few readings were written in parts per million (ppm) rather than milligrams "
            "per litre (mg/L). In water this dilute the two are the same number, so they are "
            "treated as equal."
        ),
        "bands": {"High": 0.3, "Good": 0.6, "Moderate": 1.1, "Poor": 2.5},
        "band_meanings": {
            "High": "Ammonia is naturally low and not a concern for fish or insect life.",
            "Good": "Ammonia is a little higher, but still at a level fish and insects can tolerate.",
            "Moderate": "Ammonia is high enough to start putting stress on the most sensitive river life.",
            "Poor": "Ammonia is high enough that it is likely harming sensitive fish and insects.",
            "Bad": "Ammonia is very high, at a level that can harm fish and insects directly.",
        },
    },
    "nitrate": {
        "key": "nitrate",
        "label": "Nitrate",
        "unit": "mg/L",
        "direction": "lower_better",
        "one_liner": "Another nutrient. Like phosphate, too much overfeeds plant growth.",
        "why_it_matters": (
            "Nitrate is a nutrient plants need in small amounts, but — like "
            "phosphate — too much overfeeds algae and weeds. It is usually "
            "less immediately harmful to river animals than ammonia, but "
            "still tips the balance towards excess plant growth."
        ),
        "where_from": (
            "Fertiliser and manure washed off farmland, and treated sewage."
        ),
        "unit_equivalence_note": (
            "A few readings were written in parts per million (ppm) rather than milligrams "
            "per litre (mg/L). In water this dilute the two are the same number, so they are "
            "treated as equal."
        ),
        "bands": {"High": 5.6, "Good": 11.3, "Moderate": 16.9, "Poor": 22.6},
        "band_meanings": {
            "High": "Nitrate is naturally low and not overfeeding plant growth.",
            "Good": "Nitrate is a little higher, but still at a level the river can absorb.",
            "Moderate": "Nitrate is high enough that it could start overfeeding algae and weed growth.",
            "Poor": "Nitrate is high enough to regularly overfeed algae and weed growth.",
            "Bad": "Nitrate is very high, at a level that strongly favours excess plant and algae growth.",
        },
    },
    "dissolved_oxygen": {
        "key": "dissolved_oxygen",
        "label": "Dissolved oxygen",
        "unit": "mg/L",
        "direction": "higher_better",
        "one_liner": "Oxygen dissolved in the water. Fish and insects breathe it.",
        "why_it_matters": (
            "Fish and river insects breathe oxygen that is dissolved in the "
            "water, not air. It is topped up by plants and by water tumbling "
            "over riffles and weirs, and used up by anything rotting in the "
            "river, so low readings can mean life is struggling to breathe."
        ),
        "where_from": (
            "Not a pollutant itself — low readings are usually a knock-on "
            "effect of warm weather, still water, or something else in the "
            "river using up oxygen as it decomposes."
        ),
        # Poor ("<4") is already open-ended in the source reference table,
        # so there is no further "Bad" band for this parameter — see the
        # module docstring.
        "bands": {"High": 7, "Good": 5, "Moderate": 4, "Poor": 4},
        "band_meanings": {
            "High": "Plenty of oxygen for fish and insects.",
            "Good": "A healthy amount of oxygen for fish and insects.",
            "Moderate": "Oxygen is starting to run low; sensitive species may struggle.",
            "Poor": "Oxygen is low enough that fish and insects are likely to be under stress.",
        },
    },
    "turbidity": {
        "key": "turbidity",
        "label": "Turbidity",
        "unit": "NTU",
        "direction": "lower_better",
        "one_liner": "How cloudy the water is, from mud, silt or algae.",
        "why_it_matters": (
            "Cloudy water blocks the light plants need, and fine silt can "
            "clog fish gills and smother the gravel fish lay eggs in. It "
            "usually rises sharply after heavy rain washes soil into the "
            "river."
        ),
        "where_from": (
            "Soil erosion, road run-off, and livestock disturbing riverbanks, "
            "especially after rain."
        ),
        "recorded_as_note": (
            "Most volunteers judge this by eye rather than with a meter, so most readings are "
            "a word like 'Clear' or 'Cloudy' rather than a number in NTU. Both are shown, kept "
            "separate: words are never turned into a number, and numbers are never turned into "
            "words."
        ),
        # Poor ("≥20") is already open-ended in the source reference table,
        # so there is no further "Bad" band for this parameter — see the
        # module docstring.
        "bands": {"High": 5, "Good": 10, "Moderate": 20, "Poor": 20},
        "band_meanings": {
            "High": "The water is close to clear.",
            "Good": "The water is a little cloudy, but light and gills are not badly affected.",
            "Moderate": "The water is cloudy enough to start blocking light plants need.",
            "Poor": "The water is cloudy enough to block light and to risk clogging fish gills and gravel.",
        },
    },
    "conductivity": {
        "key": "conductivity",
        "label": "Conductivity",
        "unit": "µS/cm",
        "direction": None,
        "one_liner": "How well the water conducts electricity — a proxy for dissolved minerals and salts.",
        "why_it_matters": (
            "Conductivity rises with the amount of dissolved minerals and "
            "salts in the water. It has no WFD band because there is no "
            "single 'good' number — it naturally varies with the geology "
            "the water has passed through — but a reading well outside the "
            "usual range for this river can be a useful early clue that "
            "something has changed."
        ),
        "where_from": (
            "Mostly the chalk and limestone the river runs over. Sudden "
            "changes can also point to road salt run-off or a discharge."
        ),
        "bands": None,
        "band_meanings": None,
        "typical_range": {"low": 300, "high": 1200},
    },
    "water_depth": {
        "key": "water_depth",
        "label": "Water depth",
        "unit": "cm",
        "direction": None,
        "one_liner": "How deep the water is at the sampling point, in centimetres.",
        "why_it_matters": (
            "Depth is not a measure of pollution — it is context for the "
            "other readings. A shallower river dilutes pollution less and "
            "reacts faster to rain, so depth helps explain why a reading "
            "might look different from one visit to the next."
        ),
        "where_from": "Rainfall, the season, and how far downstream the site is.",
        "recorded_as_note": (
            "Many readings are a word like 'Low' or 'Normal' rather than a number in "
            "centimetres. Both are shown, kept separate."
        ),
        "bands": None,
        "band_meanings": None,
    },
}


# ── Ordinal (word-scale) parameters ──────────────────────────────────────
# Per V2_SPEC_ADDENDUM_2.md Rule B: turbidity and water depth are mostly
# recorded as an observed word, not a meter reading. These scales are the
# plain-English label and rank for each category `v2/cleaning.py` (owned
# separately) classifies raw text into. `insights.py` reads this to order
# and label a distribution — it does not reclassify any text itself.
# Deliberately NOT in PARAMETERS' `bands`: an ordinal reading is never
# WFD-classified, so it must never be mistaken for a numeric threshold.

ORDINAL_SCALES = {
    "turbidity": [
        {"rank": 1, "category": "crystal_clear", "label": "Crystal clear"},
        {"rank": 2, "category": "very_clear", "label": "Very clear"},
        {"rank": 3, "category": "clear", "label": "Clear"},
        {"rank": 4, "category": "fairly_clear", "label": "Fairly clear"},
        {"rank": 5, "category": "slightly_cloudy", "label": "Slightly cloudy"},
        {"rank": 6, "category": "cloudy", "label": "Cloudy"},
        {"rank": 7, "category": "very_cloudy", "label": "Very cloudy"},
        {"rank": 8, "category": "murky", "label": "Murky"},
        {"rank": 9, "category": "muddy", "label": "Muddy"},
    ],
    "water_depth": [
        {"rank": 1, "category": "dry", "label": "Dry"},
        {"rank": 2, "category": "very_low", "label": "Very low"},
        {"rank": 3, "category": "low", "label": "Low"},
        {"rank": 4, "category": "normal", "label": "Normal"},
        {"rank": 5, "category": "high", "label": "High"},
    ],
}


def ordinal_label(parameter: str, category: str) -> str | None:
    """Plain-English label for one ordinal category, e.g.
    ('turbidity', 'very_cloudy') -> 'Very cloudy'."""
    for step in ORDINAL_SCALES.get(parameter, []):
        if step["category"] == category:
            return step["label"]
    return None


# A parameter this far below its total usable-reading count is being
# offered as a chart option backed by almost nothing (Rule G's worked
# examples: dissolved oxygen at 4 readings, conductivity at 2, out of 489
# entries). This counts usable readings of ANY kind — numeric or ordinal
# — so turbidity (~10 numeric + ~388 ordinal = very much being measured,
# just mostly in words) is correctly NOT flagged, while dissolved oxygen
# and conductivity (numeric only, and barely any of it) are.
NOT_CURRENTLY_MEASURED_THRESHOLD = 10


def classify_band(parameter: str, value: float | None) -> str | None:
    """Classify a single reading into a WFD band name, or None if the
    parameter is not banded (conductivity, water depth) or the value is
    missing.

    Thresholds and comparison operators (≤ vs <) follow the source
    reference table exactly — see the module docstring for why dissolved
    oxygen and turbidity never return "Bad".
    """
    if value is None:
        return None

    if parameter == "phosphate":
        if value <= 0.1:
            return "High"
        if value <= 0.2:
            return "Good"
        if value <= 0.4:
            return "Moderate"
        if value <= 0.7:
            return "Poor"
        return "Bad"

    if parameter == "ammonia":
        if value <= 0.3:
            return "High"
        if value <= 0.6:
            return "Good"
        if value <= 1.1:
            return "Moderate"
        if value <= 2.5:
            return "Poor"
        return "Bad"

    if parameter == "nitrate":
        if value <= 5.6:
            return "High"
        if value <= 11.3:
            return "Good"
        if value <= 16.9:
            return "Moderate"
        if value <= 22.6:
            return "Poor"
        return "Bad"

    if parameter == "dissolved_oxygen":
        if value >= 7:
            return "High"
        if value >= 5:
            return "Good"
        if value >= 4:
            return "Moderate"
        return "Poor"

    if parameter == "turbidity":
        if value < 5:
            return "High"
        if value < 10:
            return "Good"
        if value < 20:
            return "Moderate"
        return "Poor"

    return None


def band_width(parameter: str) -> float | None:
    """Span of the defined bands for a parameter (max threshold - min
    threshold). Used by `insights.trend` to judge whether a slope is big
    enough to call a real trend, rather than noise."""
    bands = PARAMETERS.get(parameter, {}).get("bands")
    if not bands:
        return None
    values = list(bands.values())
    return round(max(values) - min(values), 6)


def all_parameters(usable_counts: dict[str, int] | None = None) -> list[dict]:
    """Ordered list of full parameter metadata, for `GET /api/v2/parameters`.

    `usable_counts` (parameter -> total usable reading count, numeric +
    ordinal combined — `insights.usable_counts_by_parameter()`) is
    optional so this function still works with no database at all, but
    every real caller should pass it: without it, `not_currently_measured`
    can't be computed and comes back None rather than a real answer
    (Rule G — this must be based on actual counts, not asserted).
    """
    out = []
    for key in PARAMETER_ORDER:
        meta = dict(PARAMETERS[key])  # shallow copy — do not mutate the shared dict
        meta["ordinal_scale"] = ORDINAL_SCALES.get(key)
        if usable_counts is not None:
            n = usable_counts.get(key, 0)
            meta["n_usable_readings"] = n
            meta["not_currently_measured"] = n < NOT_CURRENTLY_MEASURED_THRESHOLD
        else:
            meta["n_usable_readings"] = None
            meta["not_currently_measured"] = None
        out.append(meta)
    return out
