"""Deterministic statistics for v2.

Every number the v2 API — and later the LLM report engine — uses is
computed here, in Python, from `coln_v2.db`'s derived layer
(`observations` + `measurements` + `locations`). The LLM never does
arithmetic (see the build spec's "LLM report engine" section): it is only
ever allowed to describe numbers this module already produced, which is
why every returned figure below carries a stable `id` string
(`verify.py`, owned by another agent, checks generated narrative against
these ids).

Per V2_SPEC_ADDENDUM.md, this module does two things v1 never did:

- It reads *locations* (what3words points, keyed by `w3w`), never v1's
  "sites" — those were volunteer initials, not places, and several of
  them silently averaged together multiple distinct points on the river.
  There is no `coords.py` import here; river position and coordinates
  come from `coln_v2.db`'s `locations` table, populated separately by
  `v2/locations.py` from the owner's reference spreadsheet.
- It only ever computes over `usable=1` measurements on non-`excluded`
  observations. Numeric parsing, unit-stripping, and plausibility
  classification all happened once already, honestly and auditably, in
  `v2/cleaning.py` — this module does not re-parse `value_raw` or
  re-derive `usable`/`qualifier`; it reports `n_usable` / `n_excluded`
  and surfaces what a reading's qualifier means for the arithmetic (a
  `below_detection` reading means a mean is an upper-bound estimate).

Per V2_SPEC_ADDENDUM_2.md, `usable=1` no longer implies a numeric value:
turbidity and water depth are mostly recorded as a word ("Clear", "Low"),
stored as an **ordinal category** with `value` NULL — genuinely usable
data, just not a number. `readings()` (the numeric path, used for every
mean/median/trend/band classification in this file) explicitly requires
`value IS NOT NULL` in its SQL, on top of `usable=1`, so an ordinal row
can never silently enter an arithmetic result. `ordinal_readings()` /
`ordinal_summary()` are the separate, parallel path for those — see Rule
B: "never merge the two." Band-range readings (`qualifier='band_range'`,
a test-strip colour between two pads) DO have a numeric `value` (the
midpoint, or the volunteer's own figure inside the range) and flow
through the normal numeric path with a caveat attached.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime

from v2.db import get_connection
from v2.wfd import (
    ORDINAL_SCALES,
    PARAMETER_ORDER,
    PARAMETERS,
    band_width,
    classify_band,
)

# v1's sync.py field key for the what3words + initials answer — the only
# way to recover what a volunteer actually typed for an `unlocated`
# observation, since `observations` (per the addendum's own DDL) has no
# `w3w_raw` column despite the addendum's prose mentioning one. See the
# ambiguity noted when this module was reworked: the DDL is treated as
# authoritative over the prose.
RAW_W3W_FIELD_KEY = "1_What_are_your_What"

# v1's round-detection constants (backend/main.py:get_rounds) — the
# method is unchanged by the addendum, just repointed at `observations`.
ROUND_GAP_DAYS = 4
ROUND_MIN_ENTRIES = 10

# `downstream_profile`'s `round` parameter shadows the builtin `round()`
# within that function's scope, so numeric rounding there uses this alias.
_round = round


def round_dp(parameter: str) -> int:
    """Rounding precision per the build spec: 3dp for ppm parameters,
    1dp for NTU / µS/cm / cm."""
    unit = PARAMETERS[parameter]["unit"]
    return 3 if unit == "ppm" else 1


def readings(
    w3w: str | None = None,
    parameter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    recorder: str | None = None,
) -> list[dict]:
    """Usable, NUMERIC measurements joined with their observation context,
    in ascending date/time order. This is the path every mean, median,
    trend and band classification in this file is built on.

    Always excludes `excluded=1` observations (test/junk entries) and
    `usable=0` measurements. Since Addendum 2, `usable=1` no longer
    implies a numeric value — an ordinal reading ("Clear", "Low") is
    `usable=1` with `value` NULL — so this query filters `value IS NOT
    NULL` explicitly, in SQL, rather than relying on `usable=1` alone or
    on a post-hoc Python check. See `ordinal_readings()` for the parallel,
    never-merged path for category readings. Rows where `parameter` is
    left unset span every (numeric) parameter, one row per measurement,
    which is why almost every caller below loops `for p in PARAMETER_ORDER`.
    """
    conn = get_connection()
    try:
        conditions = ["o.excluded = 0", "m.usable = 1", "m.value IS NOT NULL", "o.sample_date IS NOT NULL"]
        params: list = []
        if parameter:
            conditions.append("m.parameter = ?")
            params.append(parameter)
        if w3w:
            conditions.append("o.w3w = ?")
            params.append(w3w)
        if recorder:
            conditions.append("o.recorder = ?")
            params.append(recorder)
        if date_from:
            conditions.append("o.sample_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("o.sample_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT o.ec5_uuid, o.sample_date, o.sample_time, o.w3w, o.recorder, o.location_status,
                   m.parameter, m.value, m.value_low, m.value_high, m.value_raw, m.qualifier, m.flags
            FROM measurements m JOIN observations o ON o.ec5_uuid = m.ec5_uuid
            WHERE {where}
            ORDER BY o.sample_date ASC, o.sample_time ASC
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        # Belt-and-suspenders: the SQL already requires this, but a NULL
        # value must never reach a mean, so check again in Python too.
        if r["value"] is None:
            continue
        out.append({
            "ec5_uuid": r["ec5_uuid"],
            "w3w": r["w3w"],
            "recorder": r["recorder"],
            "location_status": r["location_status"],
            "date": r["sample_date"],
            "time": r["sample_time"],
            "parameter": r["parameter"],
            "value": r["value"],
            "value_low": r["value_low"],
            "value_high": r["value_high"],
            "value_raw": r["value_raw"],
            "qualifier": r["qualifier"],
            "flags": json.loads(r["flags"]) if r["flags"] else [],
        })
    return out


def ordinal_readings(
    w3w: str | None = None,
    parameter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    recorder: str | None = None,
) -> list[dict]:
    """Usable ORDINAL (category-scale) readings — e.g. turbidity recorded
    as "Clear" rather than a number in NTU — in ascending date/time order.

    This is the deliberate parallel to `readings()`: it only ever returns
    `qualifier='ordinal'` rows with a non-NULL `category`, and never a
    numeric `value` (which is always NULL for these rows by construction).
    It also never returns `category='flow_note'` rows (e.g. "In spate"
    describes river flow, not water clarity) — those are stored with
    `usable=0` specifically so they cannot appear in any summary; the
    `m.usable = 1` filter below already excludes them.
    """
    conn = get_connection()
    try:
        conditions = [
            "o.excluded = 0", "m.usable = 1", "m.qualifier = 'ordinal'",
            "m.category IS NOT NULL", "o.sample_date IS NOT NULL",
        ]
        params: list = []
        if parameter:
            conditions.append("m.parameter = ?")
            params.append(parameter)
        if w3w:
            conditions.append("o.w3w = ?")
            params.append(w3w)
        if recorder:
            conditions.append("o.recorder = ?")
            params.append(recorder)
        if date_from:
            conditions.append("o.sample_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("o.sample_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT o.ec5_uuid, o.sample_date, o.sample_time, o.w3w, o.recorder,
                   m.parameter, m.category, m.category_rank, m.value_raw
            FROM measurements m JOIN observations o ON o.ec5_uuid = m.ec5_uuid
            WHERE {where}
            ORDER BY o.sample_date ASC, o.sample_time ASC
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "ec5_uuid": r["ec5_uuid"],
            "w3w": r["w3w"],
            "recorder": r["recorder"],
            "date": r["sample_date"],
            "time": r["sample_time"],
            "parameter": r["parameter"],
            "category": r["category"],
            "category_rank": r["category_rank"],
            "value_raw": r["value_raw"],
        }
        for r in rows
    ]


def ordinal_summary(parameter: str, w3w: str | None = None) -> dict | None:
    """Category counts, modal category, and distribution for an
    ordinal-scale parameter (turbidity, water depth) — the numeric-free
    summary Rule B requires. Returns None when `parameter` has no defined
    `ORDINAL_SCALES` entry (there is nothing to summarise; this is not the
    same as an empty distribution, which means the scale exists but no
    reading has landed in it yet)."""
    scale = ORDINAL_SCALES.get(parameter)
    if not scale:
        return None

    rows = ordinal_readings(w3w=w3w, parameter=parameter)
    scope = w3w or "catchment"
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
    total = len(rows)

    distribution = [
        {
            "category": step["category"],
            "label": step["label"],
            "rank": step["rank"],
            "count": counts.get(step["category"], 0),
            "pct": round(100 * counts.get(step["category"], 0) / total, 1) if total else 0.0,
        }
        for step in scale
    ]
    modal = max(distribution, key=lambda d: d["count"]) if total else None
    dates = [r["date"] for r in rows]

    return {
        "id": f"ordinal|{scope}|{parameter}",
        "n_usable": total,
        "modal_category": modal["category"] if modal and modal["count"] else None,
        "modal_label": modal["label"] if modal and modal["count"] else None,
        "modal_rank": modal["rank"] if modal and modal["count"] else None,
        "distribution": distribution,
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
    }


def _usage_counts(
    w3w: str | None = None,
    parameter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    recorder: str | None = None,
) -> dict[str, dict]:
    """Per-parameter `{usable, excluded, qualifiers}` counts, scoped the
    same way as `readings` but counting every measurement row (not just
    `usable=1`) on non-excluded observations — the basis for `n_usable` /
    `n_excluded` and the below-detection / range-midpoint caveats."""
    conn = get_connection()
    try:
        conditions = ["o.excluded = 0"]
        params: list = []
        if parameter:
            conditions.append("m.parameter = ?")
            params.append(parameter)
        if w3w:
            conditions.append("o.w3w = ?")
            params.append(w3w)
        if recorder:
            conditions.append("o.recorder = ?")
            params.append(recorder)
        if date_from:
            conditions.append("o.sample_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("o.sample_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"""
            SELECT m.parameter, m.usable, m.qualifier, COUNT(*) as c
            FROM measurements m JOIN observations o ON o.ec5_uuid = m.ec5_uuid
            WHERE {where}
            GROUP BY m.parameter, m.usable, m.qualifier
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["parameter"], {"usable": 0, "excluded": 0, "qualifiers": {}})
        if r["usable"]:
            d["usable"] += r["c"]
        else:
            d["excluded"] += r["c"]
        d["qualifiers"][r["qualifier"]] = d["qualifiers"].get(r["qualifier"], 0) + r["c"]
    return out


def _build_caveats(qualifiers: dict) -> list[str]:
    """Plain-English caveats for the qualifiers present in a set of
    usable readings — required by the addendum: 'A mean computed over any
    below_detection value must be labelled as an upper-bound estimate.'"""
    caveats = []
    n = qualifiers.get("below_detection", 0)
    if n:
        caveats.append(
            f"{n} reading(s) were recorded as below the test's detection limit (a 'less than' "
            f"value). Any average here may be higher than the true figure, since the real value "
            f"could be lower than what is shown."
        )
    n = qualifiers.get("range_midpoint", 0)
    if n:
        caveats.append(
            f"{n} reading(s) were recorded as a range and the midpoint was used as an estimate."
        )
    n = qualifiers.get("band_range", 0)
    if n:
        caveats.append(
            f"{n} reading(s) came from a test-strip colour band rather than a precise reading: "
            f"the figure shown is an estimate within that band, not an exact measurement."
        )
    return caveats


def usable_counts_by_parameter() -> dict[str, int]:
    """Total usable measurement count per parameter — numeric AND ordinal
    combined — on non-excluded observations. This is the basis for
    Rule G's `not_currently_measured` flag (see `wfd.all_parameters`):
    turbidity has only ~10 numeric NTU readings but ~388 ordinal ones, so
    counting numeric readings alone would wrongly suggest turbidity is
    barely measured, when in fact it is measured constantly, just mostly
    in words."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT m.parameter, COUNT(*) as c FROM measurements m "
            "JOIN observations o ON o.ec5_uuid = m.ec5_uuid "
            "WHERE o.excluded = 0 AND m.usable = 1 "
            "GROUP BY m.parameter"
        ).fetchall()
    finally:
        conn.close()
    return {r["parameter"]: r["c"] for r in rows}


def detect_rounds() -> list[dict]:
    """v1-compatible round detection (see `backend/main.py:get_rounds`),
    now run over `observations.sample_date` instead of v1's `entries`.

    A "round" is a run of sample dates where consecutive dates are no
    more than `ROUND_GAP_DAYS` apart, kept only if the run totals more
    than `ROUND_MIN_ENTRIES` entries. Round numbers are 1-indexed in the
    order the runs occur. The method is unchanged from v1 — including
    that it counts every dated observation regardless of `excluded` or
    `location_status`, exactly as v1 never filtered by site validity
    either — only the table it reads from has changed.
    """
    conn = get_connection()
    try:
        dates = conn.execute(
            "SELECT sample_date, COUNT(*) as c FROM observations "
            "WHERE sample_date IS NOT NULL GROUP BY sample_date ORDER BY sample_date"
        ).fetchall()
    finally:
        conn.close()

    runs: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    for r in dates:
        d = r["sample_date"]
        if not current:
            current = [(d, r["c"])]
        else:
            last = current[-1][0]
            gap = (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days
            if gap <= ROUND_GAP_DAYS:
                current.append((d, r["c"]))
            else:
                if sum(c for _, c in current) > ROUND_MIN_ENTRIES:
                    runs.append(current)
                current = [(d, r["c"])]
    if current and sum(c for _, c in current) > ROUND_MIN_ENTRIES:
        runs.append(current)

    return [
        {"round": i + 1, "start": run[0][0], "end": run[-1][0], "entries": sum(c for _, c in run)}
        for i, run in enumerate(runs)
    ]


def round_by_number(n: int) -> dict | None:
    """Look up one detected round by its 1-indexed round number."""
    return next((r for r in detect_rounds() if r["round"] == n), None)


# ── Locations ─────────────────────────────────────────────────────────

def location_row(w3w: str) -> dict | None:
    """One row from `locations`, or None if `w3w` is not a known point."""
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT w3w, river_order, latitude, longitude, source FROM locations WHERE w3w = ?",
            (w3w,),
        ).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def ordered_locations() -> list[dict]:
    """Every known location, upstream -> downstream by `river_order`.
    Locations without a `river_order` (should not normally happen once
    the reference table is fully loaded, but the schema allows it — see
    the addendum's `source` column) sort last rather than being dropped
    silently."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT w3w, river_order, latitude, longitude, source FROM locations "
            "ORDER BY (river_order IS NULL), river_order"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def location_neighbours(w3w: str) -> dict:
    """Where `w3w` sits in the upstream->downstream order: its rank, the
    total number of ordered locations, and its immediate neighbours.
    Locations with no `river_order` have no rank and no neighbours.

    `river_order` itself is a REAL, not an integer: some locations were
    placed by projecting onto the reference polyline and take fractional
    values between existing points (e.g. 15.98). `rank` here is the
    location's 1-indexed *position* in the sorted sequence, not the raw
    `river_order` value — this is deliberate, and is what any "point N of
    M from the source" phrasing should use, so it never renders something
    like "point 38.92"."""
    ordered = [loc for loc in ordered_locations() if loc["river_order"] is not None]
    idx = next((i for i, loc in enumerate(ordered) if loc["w3w"] == w3w), None)
    neighbours = {"upstream": None, "downstream": None}
    rank = None
    if idx is not None:
        rank = idx + 1
        if idx > 0:
            neighbours["upstream"] = ordered[idx - 1]["w3w"]
        if idx < len(ordered) - 1:
            neighbours["downstream"] = ordered[idx + 1]["w3w"]
    return {"rank": rank, "n_locations": len(ordered), "neighbours": neighbours}


def location_provenance() -> dict:
    """Where each location's coordinates came from: the owner's reference
    table (`reference_table`), coordinates derived separately rather than
    supplied by the owner (`supplement`), or none at all (`unlocated`).
    Surfaced on the data-quality page so a reader can tell which positions
    are authoritative and which are a best-effort addition."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT w3w, river_order, latitude, longitude, source FROM locations "
            "ORDER BY source, (river_order IS NULL), river_order"
        ).fetchall()
    finally:
        conn.close()
    by_source: dict[str, list[dict]] = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append({
            "w3w": r["w3w"], "river_order": r["river_order"],
            "latitude": r["latitude"], "longitude": r["longitude"],
        })
    return {
        "counts": {src: len(v) for src, v in by_source.items()},
        "reference_table": by_source.get("reference_table", []),
        "supplement": by_source.get("supplement", []),
        "unlocated": by_source.get("unlocated", []),
    }


def missing_coordinates() -> list[dict]:
    """What3words addresses seen in the data with no known coordinates —
    Rule F (Addendum 2): a real, distinct grouping key with its own
    statistics is not a loss just because it has no position yet; it is
    an action the owner can take (add it to the reference table).

    Expected to be empty once every sampling point has coordinates —
    combines two sources defensively (any `locations` row lacking
    lat/lon, and any `w3w` that appears in `observations` with no
    `locations` row at all), since either shape is compatible with the
    fixed schema."""
    conn = get_connection()
    try:
        loc_rows = conn.execute(
            "SELECT w3w FROM locations WHERE latitude IS NULL OR longitude IS NULL"
        ).fetchall()
        obs_w3w_rows = conn.execute(
            "SELECT DISTINCT o.w3w FROM observations o "
            "LEFT JOIN locations l ON l.w3w = o.w3w "
            "WHERE o.w3w IS NOT NULL AND o.excluded = 0 "
            "AND (l.w3w IS NULL OR l.latitude IS NULL OR l.longitude IS NULL)"
        ).fetchall()
    finally:
        conn.close()

    all_missing = {r["w3w"] for r in loc_rows} | {r["w3w"] for r in obs_w3w_rows}
    out = []
    for w3w in sorted(all_missing):
        rows = readings(w3w=w3w) + ordinal_readings(w3w=w3w)
        dates = [r["date"] for r in rows]
        out.append({
            "w3w": w3w,
            "n_readings": len(rows),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
        })
    return out


def submitted_w3w_text(ec5_uuid: str) -> str | None:
    """Best-effort recovery of what a volunteer actually typed for the
    what3words field, for an `unlocated` observation — read straight from
    the untouched `raw_entries.payload_json`, since `observations` has no
    `w3w_raw` column in the fixed schema (see the module docstring)."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT payload_json FROM raw_entries WHERE ec5_uuid = ?", (ec5_uuid,)
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["payload_json"]:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (ValueError, TypeError):
        return None
    return payload.get(RAW_W3W_FIELD_KEY) or None


def _band_percentages(parameter: str, values: list[float]) -> dict:
    counts: dict[str, int] = {}
    for v in values:
        b = classify_band(parameter, v)
        if b:
            counts[b] = counts.get(b, 0) + 1
    return {b: round(100 * c / len(values), 1) for b, c in counts.items()}


def _numeric_entry(scope_id: str, dp: int, parameter: str, rows: list[dict], u: dict) -> dict:
    """The numeric half of a parameter summary — mean/median/min/max/
    latest/band, built only from rows `readings()` already guaranteed
    have a non-NULL `value`. `n_usable` here is the numeric-usable count
    (`len(rows)`), deliberately NOT the same as `u['usable']`, which for
    an ordinal-scale parameter also counts category readings that will
    never appear here — see `_ordinal_entry` for those."""
    entry: dict = {
        "n_usable": len(rows),
        "caveats": _build_caveats(u["qualifiers"]),
    }
    if not rows:
        entry.update({
            "mean": None, "median": None, "min": None, "max": None,
            "latest": None, "band_of_mean": None, "band_percentages": None,
        })
        return entry

    values = [r["value"] for r in rows]
    mean_v = statistics.mean(values)
    latest = rows[-1]
    entry.update({
        "mean": {"id": f"{scope_id}|mean", "value": round(mean_v, dp)},
        "median": {"id": f"{scope_id}|median", "value": round(statistics.median(values), dp)},
        "min": {"id": f"{scope_id}|min", "value": round(min(values), dp)},
        "max": {"id": f"{scope_id}|max", "value": round(max(values), dp)},
        "latest": {
            "id": f"{scope_id}|latest",
            "value": round(latest["value"], dp),
            "value_low": latest["value_low"],
            "value_high": latest["value_high"],
            "date": latest["date"],
            "band": classify_band(parameter, latest["value"]),
            "qualifier": latest["qualifier"],
        },
        "band_of_mean": {"id": f"{scope_id}|band_of_mean", "value": classify_band(parameter, mean_v)},
        "band_percentages": {"id": f"{scope_id}|band_percentages", "value": _band_percentages(parameter, values)},
    })
    return entry


def location_summary(w3w: str) -> dict:
    """Per-parameter statistics for one location. Every parameter carries
    a `numeric` summary (mean/median/min/max/latest/band/caveats — built
    only from readings with an actual number) and, for turbidity and
    water depth, a separate `ordinal` summary (category distribution and
    modal category). Rule B: report both, never merge them — a location
    where every turbidity reading was a word has `numeric.n_usable == 0`
    and a fully populated `ordinal` block, not a blank chart.

    `n_excluded` counts measurements `v2/cleaning.py` marked `usable=0`
    for that parameter at this location (implausible values, unparseable
    text, absent readings) — regardless of whether the parameter is
    numeric or ordinal. Plus the location's first/last sampled dates
    overall (across numeric and ordinal readings alike).
    """
    usage = _usage_counts(w3w=w3w)
    parameters: dict[str, dict] = {}
    first_dates: list[str] = []
    last_dates: list[str] = []

    for p in PARAMETER_ORDER:
        scope_id = f"location|{w3w}|{p}"
        rows = readings(w3w=w3w, parameter=p)
        u = usage.get(p, {"usable": 0, "excluded": 0, "qualifiers": {}})

        entry: dict = {
            "id": scope_id,
            "n_excluded": u["excluded"],
            "numeric": _numeric_entry(scope_id, round_dp(p), p, rows, u),
            "ordinal": ordinal_summary(p, w3w=w3w),
        }
        parameters[p] = entry

        if rows:
            first_dates.append(rows[0]["date"])
            last_dates.append(rows[-1]["date"])
        if entry["ordinal"]:
            if entry["ordinal"]["first_date"]:
                first_dates.append(entry["ordinal"]["first_date"])
            if entry["ordinal"]["last_date"]:
                last_dates.append(entry["ordinal"]["last_date"])

    return {
        "id": f"location|{w3w}",
        "w3w": w3w,
        "location": location_row(w3w),
        "first_sampled": min(first_dates) if first_dates else None,
        "last_sampled": max(last_dates) if last_dates else None,
        "parameters": parameters,
    }


def catchment_summary(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Same per-parameter shape as `location_summary` (`numeric` +
    `ordinal`, never merged — see Rule B), aggregated across every
    location plus any reading whose observation has no `w3w` at all
    (a catchment-wide figure is not location-based, so it is not excluded
    the way it would be from a map or downstream profile — see Rule F),
    plus a per-location rollup of each location's latest value/band per
    parameter within the same window."""
    parameters: dict[str, dict] = {}
    for p in PARAMETER_ORDER:
        scope_id = f"catchment|{p}"
        rows = readings(parameter=p, date_from=date_from, date_to=date_to)
        u = _usage_counts(parameter=p, date_from=date_from, date_to=date_to).get(
            p, {"usable": 0, "excluded": 0, "qualifiers": {}}
        )
        parameters[p] = {
            "id": scope_id,
            "n_excluded": u["excluded"],
            "numeric": _numeric_entry(scope_id, round_dp(p), p, rows, u),
            "ordinal": ordinal_summary(p),
        }

    all_rows = readings(date_from=date_from, date_to=date_to)
    n_unlocated_readings = sum(1 for r in all_rows if r["w3w"] is None)
    by_location_param: dict[tuple[str, str], list[dict]] = {}
    for r in all_rows:
        if r["w3w"] is None:
            continue
        by_location_param.setdefault((r["w3w"], r["parameter"]), []).append(r)

    locations_present = sorted({w for (w, _p) in by_location_param})
    location_rollup: dict[str, dict] = {}
    for w in locations_present:
        per_param = {}
        for p in PARAMETER_ORDER:
            rows_wp = by_location_param.get((w, p))
            if not rows_wp:
                per_param[p] = None
                continue
            latest = rows_wp[-1]  # already ascending date/time from readings()
            dp = round_dp(p)
            per_param[p] = {
                "value": round(latest["value"], dp),
                "date": latest["date"],
                "band": classify_band(p, latest["value"]),
            }
        location_rollup[w] = per_param

    return {
        "id": "catchment",
        "date_from": date_from,
        "date_to": date_to,
        "parameters": parameters,
        "location_rollup": location_rollup,
        "n_unlocated_readings": n_unlocated_readings,
    }


def trend(w3w: str | None, parameter: str) -> dict:
    """Ordinary least-squares slope of `parameter` over time, at `w3w`
    (or across the whole catchment if `w3w` is None), plus a plain-English
    direction.

    Requires >= 5 usable points; below that returns status
    "insufficient_data". Direction is "no clear change" unless the total
    change implied by the slope over the observed period exceeds 10% of
    the parameter's WFD band width, so a handful of noisy points cannot
    be reported as a real trend.
    """
    rows = readings(w3w=w3w, parameter=parameter)
    scope = w3w or "catchment"
    result_id = f"trend|{scope}|{parameter}"

    qualifiers = {}
    for r in rows:
        qualifiers[r["qualifier"]] = qualifiers.get(r["qualifier"], 0) + 1
    caveats = _build_caveats(qualifiers)

    if len(rows) < 5:
        return {
            "id": result_id, "status": "insufficient_data", "n": len(rows),
            "w3w": w3w, "parameter": parameter, "direction": None, "caveats": caveats,
        }

    first_date = datetime.strptime(rows[0]["date"], "%Y-%m-%d")
    xs = [(datetime.strptime(r["date"], "%Y-%m-%d") - first_date).days for r in rows]
    ys = [r["value"] for r in rows]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)

    if ss_xx == 0:
        # Every reading falls on the same calendar day — nothing to fit a
        # slope against.
        return {
            "id": result_id, "status": "insufficient_data", "n": n,
            "w3w": w3w, "parameter": parameter, "direction": None, "caveats": caveats,
        }

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope_per_day = ss_xy / ss_xx

    span_days = max(xs) - min(xs)
    total_change = slope_per_day * span_days

    direction_word = "no clear change"
    width = band_width(parameter)
    if width:
        if abs(total_change) > 0.10 * width:
            higher_is_better = PARAMETERS[parameter]["direction"] == "higher_better"
            improving = (total_change > 0) if higher_is_better else (total_change < 0)
            direction_word = "improving" if improving else "worsening"

    dp = round_dp(parameter)
    return {
        "id": result_id,
        "status": "ok",
        "n": n,
        "w3w": w3w,
        "parameter": parameter,
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "slope_per_day": round(slope_per_day, 6),
        "total_change_over_period": round(total_change, dp),
        "direction": direction_word,
        "caveats": caveats,
    }


def round_comparison(round_a: int, round_b: int) -> dict:
    """Per-parameter mean deltas and band changes between two detected
    rounds, identified by their 1-indexed round numbers."""
    ra = round_by_number(round_a)
    rb = round_by_number(round_b)
    if ra is None:
        raise ValueError(f"round not found: {round_a}")
    if rb is None:
        raise ValueError(f"round not found: {round_b}")

    label = f"round{round_a}_vs_round{round_b}"
    parameters: dict[str, dict] = {}
    for p in PARAMETER_ORDER:
        dp = round_dp(p)
        vals_a = [r["value"] for r in readings(parameter=p, date_from=ra["start"], date_to=ra["end"])]
        vals_b = [r["value"] for r in readings(parameter=p, date_from=rb["start"], date_to=rb["end"])]
        mean_a = round(statistics.mean(vals_a), dp) if vals_a else None
        mean_b = round(statistics.mean(vals_b), dp) if vals_b else None
        band_a = classify_band(p, mean_a) if mean_a is not None else None
        band_b = classify_band(p, mean_b) if mean_b is not None else None
        delta = round(mean_b - mean_a, dp) if (mean_a is not None and mean_b is not None) else None
        parameters[p] = {
            "id": f"roundcmp|{label}|{p}",
            "round_a": {"round": round_a, "n": len(vals_a), "mean": mean_a, "band": band_a},
            "round_b": {"round": round_b, "n": len(vals_b), "mean": mean_b, "band": band_b},
            "mean_delta": delta,
            "band_changed": (band_a != band_b) if (band_a and band_b) else None,
        }

    return {"id": f"roundcmp|{label}", "round_a": ra, "round_b": rb, "parameters": parameters}


def downstream_profile(parameter: str, round: int | None = None) -> dict:
    """Per-location values for `parameter`, ordered upstream -> downstream
    by `locations.river_order`, optionally restricted to one detected
    round's date span. Locations with no `river_order` are omitted from
    this view — see the addendum: "along the river" must read as a
    journey from source to Thames, which an unordered point cannot join."""
    date_from = date_to = None
    round_info = None
    if round is not None:
        round_info = round_by_number(round)
        if round_info is None:
            raise ValueError(f"round not found: {round}")
        date_from, date_to = round_info["start"], round_info["end"]

    rows = readings(parameter=parameter, date_from=date_from, date_to=date_to)
    by_location: dict[str, list[float]] = {}
    for r in rows:
        if r["w3w"] is None:
            continue
        by_location.setdefault(r["w3w"], []).append(r["value"])

    dp = round_dp(parameter)
    scope = f"round{round}" if round is not None else "alltime"
    locations = []
    for loc in ordered_locations():
        if loc["river_order"] is None:
            continue
        values = by_location.get(loc["w3w"])
        mean_v = _round(statistics.mean(values), dp) if values else None
        locations.append({
            "id": f"downstream|{parameter}|{scope}|{loc['w3w']}",
            "w3w": loc["w3w"],
            "river_order": loc["river_order"],
            "latitude": loc["latitude"],
            "longitude": loc["longitude"],
            "n": len(values) if values else 0,
            "mean": mean_v,
            "band": classify_band(parameter, mean_v) if mean_v is not None else None,
        })

    return {
        "id": f"downstream|{parameter}|{scope}",
        "parameter": parameter,
        "round": round,
        "round_info": round_info,
        "locations": locations,
    }


def outliers(parameter: str) -> list[dict]:
    """Usable readings more than 3 median-absolute-deviations (MAD) from
    their own location's median for this parameter.

    Locations where every reading is identical (MAD == 0) are skipped:
    with no spread to measure, "3 MAD" is not a meaningful yardstick and
    would flag perfectly ordinary repeated readings as outliers.
    """
    rows = readings(parameter=parameter)
    by_location: dict[str, list[dict]] = {}
    for r in rows:
        if r["w3w"] is None:
            continue
        by_location.setdefault(r["w3w"], []).append(r)

    dp = round_dp(parameter)
    out = []
    for w3w, loc_rows in by_location.items():
        values = [r["value"] for r in loc_rows]
        if len(values) < 2:
            continue
        median_v = statistics.median(values)
        mad = statistics.median([abs(v - median_v) for v in values])
        if mad == 0:
            continue
        for r in loc_rows:
            deviation = abs(r["value"] - median_v)
            if deviation > 3 * mad:
                out.append({
                    "id": f"outlier|{w3w}|{parameter}|{r['date']}",
                    "w3w": w3w,
                    "parameter": parameter,
                    "date": r["date"],
                    "value": round(r["value"], dp),
                    "location_median": round(median_v, dp),
                    "deviation_in_mads": round(deviation / mad, 2),
                })
    return out


# ── Review queue (Addendum 2, Rule D) ────────────────────────────────
# Nothing ambiguous is silently dropped or silently guessed — it goes
# here for the owner. `resolve_review_item` is the only function in this
# module that writes anything; per Rule D it only ever writes
# `review_queue` and `manual_corrections`, and it NEVER touches
# `measurements` — an accepted correction is picked up from
# `manual_corrections` the next time `v2/cleaning.py` runs `--refresh`,
# fully attributed and reversible, rather than being applied here.

def review_queue(status: str | None = None, issue: str | None = None) -> list[dict]:
    """List review-queue items, optionally filtered by `status`
    (open|accepted|rejected) and/or `issue` type."""
    conn = get_connection()
    try:
        conditions = []
        params: list = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if issue:
            conditions.append("issue = ?")
            params.append(issue)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM review_queue {where} ORDER BY status, id", params
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def review_queue_item(item_id: int) -> dict | None:
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,)).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def resolve_review_item(
    item_id: int,
    status: str,
    resolved_value: str | None = None,
    kind: str | None = None,
    note: str | None = None,
    resolved_by: str | None = None,
) -> dict:
    """Resolve one `review_queue` item as `accepted` or `rejected`.

    On `accepted`, writes a `review_decisions` row for that reading —
    `resolved_value` if given, otherwise the queue item's own `suggestion`
    (accepting IS choosing the suggestion, unless the caller explicitly
    overrides it). `kind` is one of value|not_measured|category|remove|
    merge; it defaults to 'merge' for ambiguous_location items and 'value'
    otherwise. Raises `ValueError` if the item doesn't exist, and
    `LookupError` if a value-like acceptance is requested with nothing to
    apply (`resolved_value` and `suggestion` both empty) — never applies
    a guess.

    This never writes to `measurements`. The correction takes effect the
    next time `v2/ingest.py` runs `--refresh` (owned separately), logging
    a `cleaning_log` row with the matching action.
    """
    if status not in ("accepted", "rejected"):
        raise ValueError(f"invalid status: {status!r} (must be 'accepted' or 'rejected')")

    item = review_queue_item(item_id)
    if item is None:
        raise ValueError(f"review_queue item not found: {item_id}")

    now = datetime.utcnow().isoformat() + "Z"
    conn = get_connection()
    try:
        if status == "accepted":
            value_to_apply = resolved_value if resolved_value is not None else item["suggestion"]
            decision_kind = kind or ("merge" if item["issue"] == "ambiguous_location" else "value")
            if decision_kind == "value" and not value_to_apply:
                raise LookupError(
                    "cannot accept: no resolved_value was given and this item has no suggestion "
                    "to fall back on"
                )
            conn.execute(
                "INSERT INTO review_decisions (ec5_uuid, parameter, value_raw, issue, kind, "
                "resolved_value, note, resolved_at, resolved_by) VALUES (?,?,?,?,?,?,?,?,?)",
                (item["ec5_uuid"], item["parameter"], item["value_raw"], item["issue"],
                 decision_kind, value_to_apply,
                 note or f"accepted from review queue ({item['issue']})", now, resolved_by),
            )
            conn.execute(
                "UPDATE review_queue SET status=?, resolved_value=?, resolved_at=?, resolved_by=? WHERE id=?",
                ("accepted", value_to_apply, now, resolved_by, item_id),
            )
        else:
            conn.execute(
                "UPDATE review_queue SET status=?, resolved_value=?, resolved_at=?, resolved_by=? WHERE id=?",
                ("rejected", resolved_value, now, resolved_by, item_id),
            )
        conn.commit()
    finally:
        conn.close()

    return review_queue_item(item_id)


def data_quality() -> dict:
    """Coverage and honesty report: how many observations exist, how many
    were excluded (test/junk) and why, how many could not be geolocated
    (expected to be zero — see `missing_coordinates`), where each
    location's coordinates came from, how the cleaning step classified
    every measurement (usable-numeric vs usable-ordinal vs excluded, and
    why), where location matching needed a fuzzy or documented rename,
    open review-queue items (including ambiguous_location duplicates
    kept deliberately separate — an open question, not an error),
    per-location sampling gaps over 60 days, and suspiciously repeated
    values.

    Unlike the original insights.py, this does not re-derive plausibility
    itself — `v2/cleaning.py` already decided `usable`/`qualifier`/`flags`
    for every measurement using the addendum's plausible ranges, so this
    function reports what cleaning found rather than recomputing it.
    """
    conn = get_connection()
    try:
        total_observations = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        excluded_rows = conn.execute(
            "SELECT exclude_reason, COUNT(*) as c FROM observations WHERE excluded = 1 GROUP BY exclude_reason"
        ).fetchall()
        status_rows = conn.execute(
            "SELECT location_status, COUNT(*) as c FROM observations GROUP BY location_status"
        ).fetchall()
        unlocated_rows = conn.execute(
            "SELECT ec5_uuid, sample_date, recorder FROM observations "
            "WHERE location_status = 'unlocated' AND excluded = 0 ORDER BY sample_date"
        ).fetchall()
        alias_rows = conn.execute(
            "SELECT match_type, COUNT(*) as c FROM location_aliases GROUP BY match_type"
        ).fetchall()
        measurement_rows = conn.execute(
            "SELECT parameter, qualifier, usable, COUNT(*) as c FROM measurements "
            "JOIN observations o ON o.ec5_uuid = measurements.ec5_uuid "
            "WHERE o.excluded = 0 GROUP BY parameter, qualifier, usable"
        ).fetchall()
        cleaning_action_rows = conn.execute(
            "SELECT action, COUNT(*) as c FROM cleaning_log GROUP BY action"
        ).fetchall()
    finally:
        conn.close()

    # Numeric and ordinal usable readings are counted separately — a
    # parameter's "usable" total on its own no longer tells a reader
    # whether they are looking at numbers or words (Rule B: never merge).
    by_parameter: dict[str, dict] = {
        p: {"n_usable_numeric": 0, "n_usable_ordinal": 0, "n_excluded": 0, "qualifiers": {}}
        for p in PARAMETER_ORDER
    }
    for r in measurement_rows:
        p = r["parameter"]
        if p not in by_parameter:
            by_parameter[p] = {"n_usable_numeric": 0, "n_usable_ordinal": 0, "n_excluded": 0, "qualifiers": {}}
        if r["usable"]:
            if r["qualifier"] == "ordinal":
                by_parameter[p]["n_usable_ordinal"] += r["c"]
            else:
                by_parameter[p]["n_usable_numeric"] += r["c"]
        else:
            by_parameter[p]["n_excluded"] += r["c"]
        by_parameter[p]["qualifiers"][r["qualifier"]] = by_parameter[p]["qualifiers"].get(r["qualifier"], 0) + r["c"]

    # Observations still flagged location_status='unlocated' — after the
    # coordinate supplement work, this is expected to be empty (every
    # sampling point now has coordinates via reference_table or
    # supplement). A non-empty list here is a discrepancy worth
    # investigating, not an expected steady-state category.
    unlocated = [
        {
            "ec5_uuid": r["ec5_uuid"],
            "date": r["sample_date"],
            "recorder": r["recorder"],
            "submitted_as": submitted_w3w_text(r["ec5_uuid"]),
        }
        for r in unlocated_rows
    ]

    open_review_items = review_queue(status="open")
    review_queue_by_issue: dict[str, int] = {}
    for item in open_review_items:
        review_queue_by_issue[item["issue"]] = review_queue_by_issue.get(item["issue"], 0) + 1
    ambiguous_locations = [item for item in open_review_items if item["issue"] == "ambiguous_location"]

    # Per-location gaps over 60 days and suspicious repeats (>=4 identical
    # usable values running, in date order), computed over located,
    # non-excluded, usable readings.
    all_dates = sorted({r["date"] for r in readings()})
    latest_overall = all_dates[-1] if all_dates else None

    locations_seen = sorted({loc["w3w"] for loc in ordered_locations()})
    gaps: dict[str, dict] = {}
    repeats: list[dict] = []
    for w3w in locations_seen:
        loc_dates = sorted({r["date"] for r in readings(w3w=w3w)})
        loc_gaps = []
        for prev, nxt in zip(loc_dates, loc_dates[1:]):
            gap_days = (datetime.strptime(nxt, "%Y-%m-%d") - datetime.strptime(prev, "%Y-%m-%d")).days
            if gap_days > 60:
                loc_gaps.append({"from": prev, "to": nxt, "days": gap_days})
        if loc_dates and latest_overall:
            days_since_last = (
                datetime.strptime(latest_overall, "%Y-%m-%d") - datetime.strptime(loc_dates[-1], "%Y-%m-%d")
            ).days
            if days_since_last > 60:
                loc_gaps.append({"from": loc_dates[-1], "to": latest_overall, "days": days_since_last, "ongoing": True})
        if loc_gaps:
            gaps[w3w] = {"id": f"dataquality|{w3w}|gaps", "value": loc_gaps}

        for p in PARAMETER_ORDER:
            rows = readings(w3w=w3w, parameter=p)
            run_value, run_len, run_start, prev_date = None, 0, None, None
            for r in rows:
                if run_len and r["value"] == run_value:
                    run_len += 1
                else:
                    if run_len >= 4:
                        repeats.append({
                            "id": f"dataquality|{w3w}|{p}|repeat|{run_start}",
                            "w3w": w3w, "parameter": p, "value": run_value,
                            "count": run_len, "from": run_start, "to": prev_date,
                        })
                    run_value, run_len, run_start = r["value"], 1, r["date"]
                prev_date = r["date"]
            if run_len >= 4:
                repeats.append({
                    "id": f"dataquality|{w3w}|{p}|repeat|{run_start}",
                    "w3w": w3w, "parameter": p, "value": run_value,
                    "count": run_len, "from": run_start, "to": prev_date,
                })

    return {
        "id": "dataquality",
        "total_observations": total_observations,
        "by_location_status": {r["location_status"]: r["c"] for r in status_rows},
        "excluded_reasons": {(r["exclude_reason"] or "unspecified"): r["c"] for r in excluded_rows},
        "unlocated": unlocated,
        "location_alias_match_types": {r["match_type"]: r["c"] for r in alias_rows},
        "cleaning_actions": {r["action"]: r["c"] for r in cleaning_action_rows},
        "latest_sample_date": latest_overall,
        "parameters": by_parameter,
        "gaps_over_60_days": gaps,
        "suspicious_repeats": repeats,
    }
