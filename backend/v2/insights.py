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
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime

from v2.db import get_connection
from v2.wfd import (
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
    """Rounding precision per the build spec: 3dp for mg/L parameters,
    1dp for NTU / µS/cm / cm."""
    unit = PARAMETERS[parameter]["unit"]
    return 3 if unit == "mg/L" else 1


def readings(
    w3w: str | None = None,
    parameter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    recorder: str | None = None,
) -> list[dict]:
    """Usable measurements joined with their observation context, in
    ascending date/time order.

    Always excludes `excluded=1` observations (test/junk entries) and
    `usable=0` measurements — this is the one function nearly everything
    else in this module is built on, so every statistic automatically
    only ever sees data `v2/cleaning.py` judged safe to use. Rows where
    `parameter` is left unset span every parameter (one row per
    measurement, tagged with its own `parameter` key), which is why
    almost every caller below still loops `for p in PARAMETER_ORDER`.
    """
    conn = get_connection()
    try:
        conditions = ["o.excluded = 0", "m.usable = 1", "o.sample_date IS NOT NULL"]
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
                   m.parameter, m.value, m.value_raw, m.qualifier, m.flags
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
            "value_raw": r["value_raw"],
            "qualifier": r["qualifier"],
            "flags": json.loads(r["flags"]) if r["flags"] else [],
        })
    return out


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
    return caveats


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
    Locations with no `river_order` have no rank and no neighbours."""
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


def location_summary(w3w: str) -> dict:
    """Per-parameter statistics for one location: n_usable, n_excluded,
    mean, median, min, max, latest value + date, band of latest, band of
    mean, % of readings in each band, caveats, plus the location's
    first/last sampled dates overall."""
    usage = _usage_counts(w3w=w3w)
    parameters: dict[str, dict] = {}
    first_dates: list[str] = []
    last_dates: list[str] = []

    for p in PARAMETER_ORDER:
        rows = readings(w3w=w3w, parameter=p)
        values = [r["value"] for r in rows]
        dp = round_dp(p)
        u = usage.get(p, {"usable": 0, "excluded": 0, "qualifiers": {}})
        entry: dict = {
            "id": f"location|{w3w}|{p}",
            "n_usable": u["usable"],
            "n_excluded": u["excluded"],
            "caveats": _build_caveats(u["qualifiers"]),
        }

        if values:
            mean_v = statistics.mean(values)
            latest = rows[-1]
            entry.update({
                "mean": {"id": f"location|{w3w}|{p}|mean", "value": round(mean_v, dp)},
                "median": {"id": f"location|{w3w}|{p}|median", "value": round(statistics.median(values), dp)},
                "min": {"id": f"location|{w3w}|{p}|min", "value": round(min(values), dp)},
                "max": {"id": f"location|{w3w}|{p}|max", "value": round(max(values), dp)},
                "latest": {
                    "id": f"location|{w3w}|{p}|latest",
                    "value": round(latest["value"], dp),
                    "date": latest["date"],
                    "band": classify_band(p, latest["value"]),
                    "qualifier": latest["qualifier"],
                },
                "band_of_mean": {"id": f"location|{w3w}|{p}|band_of_mean", "value": classify_band(p, mean_v)},
                "band_percentages": {"id": f"location|{w3w}|{p}|band_percentages", "value": _band_percentages(p, values)},
            })
            first_dates.append(rows[0]["date"])
            last_dates.append(rows[-1]["date"])
        else:
            entry.update({
                "mean": None, "median": None, "min": None, "max": None,
                "latest": None, "band_of_mean": None, "band_percentages": None,
            })
        parameters[p] = entry

    return {
        "id": f"location|{w3w}",
        "w3w": w3w,
        "location": location_row(w3w),
        "first_sampled": min(first_dates) if first_dates else None,
        "last_sampled": max(last_dates) if last_dates else None,
        "parameters": parameters,
    }


def catchment_summary(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Same per-parameter shape as `location_summary`, aggregated across
    every location (plus any `unlocated` readings, since a catchment-wide
    figure is not location-based — see the addendum), plus a per-location
    rollup of each location's latest value/band per parameter within the
    same window."""
    parameters: dict[str, dict] = {}
    for p in PARAMETER_ORDER:
        rows = readings(parameter=p, date_from=date_from, date_to=date_to)
        values = [r["value"] for r in rows]
        dp = round_dp(p)
        u = _usage_counts(parameter=p, date_from=date_from, date_to=date_to).get(
            p, {"usable": 0, "excluded": 0, "qualifiers": {}}
        )
        entry: dict = {
            "id": f"catchment|{p}",
            "n_usable": u["usable"],
            "n_excluded": u["excluded"],
            "caveats": _build_caveats(u["qualifiers"]),
        }
        if values:
            mean_v = statistics.mean(values)
            entry.update({
                "mean": {"id": f"catchment|{p}|mean", "value": round(mean_v, dp)},
                "median": {"id": f"catchment|{p}|median", "value": round(statistics.median(values), dp)},
                "min": {"id": f"catchment|{p}|min", "value": round(min(values), dp)},
                "max": {"id": f"catchment|{p}|max", "value": round(max(values), dp)},
                "band_of_mean": {"id": f"catchment|{p}|band_of_mean", "value": classify_band(p, mean_v)},
                "band_percentages": {"id": f"catchment|{p}|band_percentages", "value": _band_percentages(p, values)},
            })
        else:
            entry.update({
                "mean": None, "median": None, "min": None, "max": None,
                "band_of_mean": None, "band_percentages": None,
            })
        parameters[p] = entry

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


def data_quality() -> dict:
    """Coverage and honesty report: how many observations exist, how many
    were excluded (test/junk) and why, how many could not be geolocated,
    how the cleaning step classified every measurement (usable vs not,
    and why), where location matching needed a fuzzy or documented
    rename, per-location sampling gaps over 60 days, and suspiciously
    repeated values.

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

    by_parameter: dict[str, dict] = {p: {"n_usable": 0, "n_excluded": 0, "qualifiers": {}} for p in PARAMETER_ORDER}
    for r in measurement_rows:
        p = r["parameter"]
        if p not in by_parameter:
            by_parameter[p] = {"n_usable": 0, "n_excluded": 0, "qualifiers": {}}
        if r["usable"]:
            by_parameter[p]["n_usable"] += r["c"]
        else:
            by_parameter[p]["n_excluded"] += r["c"]
        by_parameter[p]["qualifiers"][r["qualifier"]] = by_parameter[p]["qualifiers"].get(r["qualifier"], 0) + r["c"]

    unlocated = [
        {
            "ec5_uuid": r["ec5_uuid"],
            "date": r["sample_date"],
            "recorder": r["recorder"],
            "submitted_as": submitted_w3w_text(r["ec5_uuid"]),
        }
        for r in unlocated_rows
    ]

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
