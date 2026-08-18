"""Deterministic statistics for v2.

Every number the v2 API — and later the LLM report engine — uses is
computed here, in Python, from the raw `entries` table. The LLM never
does arithmetic (see the build spec's "LLM report engine" section): it is
only ever allowed to describe numbers this module already produced, which
is why every returned figure below carries a stable `id` string
(`verify.py`, owned by another agent, checks generated narrative against
these ids).

Numeric columns in `entries` are TEXT and may be '', 'None', or genuinely
unparseable junk — every parse in this module goes through `parse_value`,
which guards all of that. The site code '???' is junk data entry, not a
real site, and is excluded everywhere a site list is built.
"""

from __future__ import annotations

import statistics
from datetime import datetime

from coords import SITE_DOWNSTREAM_ORDER
from v2.db import get_connection
from v2.wfd import (
    PARAMETER_COLUMNS,
    PARAMETER_ORDER,
    PARAMETERS,
    band_width,
    classify_band,
)

JUNK_SITE_CODE = "???"

# v1's round-detection constants (backend/main.py:get_rounds) — kept as
# named constants here rather than magic numbers, but the values and the
# comparisons around them below must stay byte-for-byte equivalent to v1
# so round numbers agree between the two APIs.
ROUND_GAP_DAYS = 4
ROUND_MIN_ENTRIES = 10

# `downstream_profile`'s `round` parameter (named to match the build spec's
# `downstream_profile(parameter, round=None)` and the `?round=` query
# param) shadows the builtin `round()` within that function's scope, so it
# uses this alias for numeric rounding instead.
_round = round


def parse_value(raw) -> float | None:
    """Tolerant numeric parse for the TEXT-typed columns in `entries`.

    Returns None for None, '', the literal string 'None' (however it is
    cased or padded), and anything else that doesn't parse as a float —
    every failure mode actually seen in this data — rather than raising.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s == "" or s.lower() == "none":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def round_dp(parameter: str) -> int:
    """Rounding precision per the build spec: 3dp for mg/L parameters,
    1dp for NTU / µS/cm / cm."""
    unit = PARAMETERS[parameter]["unit"]
    return 3 if unit == "mg/L" else 1


def readings(
    site: str | None = None,
    parameter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Clean rows from `entries`, in ascending date/time order, always
    excluding the junk site code '???'.

    If `parameter` is given, one dict per entry with a parseable value for
    that parameter: `{"site", "date", "time", "value"}`.

    If `parameter` is omitted, one dict per entry (regardless of whether
    any value parses) with every parameter parsed into a nested dict:
    `{"site", "date", "time", "values": {param: float | None, ...}}`.
    """
    conn = get_connection()
    try:
        conditions = ["w3w_site_code IS NOT NULL", "w3w_site_code != ?", "sample_date IS NOT NULL"]
        params: list = [JUNK_SITE_CODE]
        if site:
            conditions.append("w3w_site_code = ?")
            params.append(site)
        if date_from:
            conditions.append("sample_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("sample_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        value_cols = list(PARAMETER_COLUMNS.values())
        select_cols = ["w3w_site_code", "sample_date", "sample_time"] + value_cols
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM entries WHERE {where} "
            "ORDER BY sample_date ASC, sample_time ASC",
            params,
        ).fetchall()
    finally:
        conn.close()

    out = []
    if parameter:
        col = PARAMETER_COLUMNS[parameter]
        for r in rows:
            value = parse_value(r[col])
            if value is None:
                continue
            out.append({"site": r["w3w_site_code"], "date": r["sample_date"], "time": r["sample_time"], "value": value})
    else:
        for r in rows:
            out.append({
                "site": r["w3w_site_code"],
                "date": r["sample_date"],
                "time": r["sample_time"],
                "values": {p: parse_value(r[c]) for p, c in PARAMETER_COLUMNS.items()},
            })
    return out


def detect_rounds() -> list[dict]:
    """v1-compatible round detection — see `backend/main.py:get_rounds`.

    A "round" is a run of sample dates where consecutive dates are no more
    than `ROUND_GAP_DAYS` apart, kept only if the run totals more than
    `ROUND_MIN_ENTRIES` entries. Round numbers are 1-indexed in the order
    the runs occur. This must stay algorithmically identical to v1 so
    round numbers agree between `/api/rounds` and `/api/v2/rounds` — it is
    deliberately not "improved" or refactored beyond being reshaped into a
    plain function.
    """
    conn = get_connection()
    try:
        dates = conn.execute(
            "SELECT sample_date, COUNT(*) as c FROM entries "
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


def _band_percentages(parameter: str, values: list[float]) -> dict:
    counts: dict[str, int] = {}
    for v in values:
        b = classify_band(parameter, v)
        if b:
            counts[b] = counts.get(b, 0) + 1
    return {b: round(100 * c / len(values), 1) for b, c in counts.items()}


def site_summary(site: str) -> dict:
    """Per-parameter statistics for one site: n, mean, median, min, max,
    latest value + date, band of latest, band of mean, % of readings in
    each band, plus the site's first/last sampled dates overall."""
    parameters: dict[str, dict] = {}
    first_dates: list[str] = []
    last_dates: list[str] = []

    for p in PARAMETER_ORDER:
        rows = readings(site=site, parameter=p)
        values = [r["value"] for r in rows]
        dp = round_dp(p)
        entry: dict = {"id": f"site.{site}.{p}", "n": len(values)}

        if values:
            mean_v = statistics.mean(values)
            latest = rows[-1]
            entry.update({
                "mean": {"id": f"site.{site}.{p}.mean", "value": round(mean_v, dp)},
                "median": {"id": f"site.{site}.{p}.median", "value": round(statistics.median(values), dp)},
                "min": {"id": f"site.{site}.{p}.min", "value": round(min(values), dp)},
                "max": {"id": f"site.{site}.{p}.max", "value": round(max(values), dp)},
                "latest": {
                    "id": f"site.{site}.{p}.latest",
                    "value": round(latest["value"], dp),
                    "date": latest["date"],
                    "band": classify_band(p, latest["value"]),
                },
                "band_of_mean": {"id": f"site.{site}.{p}.band_of_mean", "value": classify_band(p, mean_v)},
                "band_percentages": {"id": f"site.{site}.{p}.band_percentages", "value": _band_percentages(p, values)},
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
        "id": f"site.{site}",
        "site": site,
        "first_sampled": min(first_dates) if first_dates else None,
        "last_sampled": max(last_dates) if last_dates else None,
        "parameters": parameters,
    }


def catchment_summary(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Same per-parameter shape as `site_summary`, aggregated across every
    site, plus a per-site rollup (each site's latest value/band per
    parameter) within the same window."""
    parameters: dict[str, dict] = {}
    for p in PARAMETER_ORDER:
        rows = readings(parameter=p, date_from=date_from, date_to=date_to)
        values = [r["value"] for r in rows]
        dp = round_dp(p)
        entry: dict = {"id": f"catchment.{p}", "n": len(values)}
        if values:
            mean_v = statistics.mean(values)
            entry.update({
                "mean": {"id": f"catchment.{p}.mean", "value": round(mean_v, dp)},
                "median": {"id": f"catchment.{p}.median", "value": round(statistics.median(values), dp)},
                "min": {"id": f"catchment.{p}.min", "value": round(min(values), dp)},
                "max": {"id": f"catchment.{p}.max", "value": round(max(values), dp)},
                "band_of_mean": {"id": f"catchment.{p}.band_of_mean", "value": classify_band(p, mean_v)},
                "band_percentages": {"id": f"catchment.{p}.band_percentages", "value": _band_percentages(p, values)},
            })
        else:
            entry.update({
                "mean": None, "median": None, "min": None, "max": None,
                "band_of_mean": None, "band_percentages": None,
            })
        parameters[p] = entry

    all_rows = readings(date_from=date_from, date_to=date_to)
    sites = sorted({r["site"] for r in all_rows})
    site_rollup: dict[str, dict] = {}
    for site in sites:
        per_param = {}
        for p in PARAMETER_ORDER:
            rows = readings(site=site, parameter=p, date_from=date_from, date_to=date_to)
            if not rows:
                per_param[p] = None
                continue
            latest = rows[-1]
            dp = round_dp(p)
            per_param[p] = {
                "value": round(latest["value"], dp),
                "date": latest["date"],
                "band": classify_band(p, latest["value"]),
            }
        site_rollup[site] = per_param

    return {
        "id": "catchment",
        "date_from": date_from,
        "date_to": date_to,
        "parameters": parameters,
        "site_rollup": site_rollup,
    }


def trend(site: str | None, parameter: str) -> dict:
    """Ordinary least-squares slope of `parameter` over time, at `site`
    (or across the whole catchment if `site` is None), plus a plain-English
    direction.

    Requires >= 5 points; below that returns status "insufficient_data".
    Direction is "no clear change" unless the total change implied by the
    slope over the observed period exceeds 10% of the parameter's WFD band
    width, so a handful of noisy points cannot be reported as a real trend.
    """
    rows = readings(site=site, parameter=parameter)
    scope = site or "catchment"
    result_id = f"trend.{scope}.{parameter}"

    if len(rows) < 5:
        return {"id": result_id, "status": "insufficient_data", "n": len(rows), "site": site, "parameter": parameter, "direction": None}

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
        return {"id": result_id, "status": "insufficient_data", "n": n, "site": site, "parameter": parameter, "direction": None}

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
        "site": site,
        "parameter": parameter,
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
        "slope_per_day": round(slope_per_day, 6),
        "total_change_over_period": round(total_change, dp),
        "direction": direction_word,
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
            "id": f"roundcmp.{label}.{p}",
            "round_a": {"round": round_a, "n": len(vals_a), "mean": mean_a, "band": band_a},
            "round_b": {"round": round_b, "n": len(vals_b), "mean": mean_b, "band": band_b},
            "mean_delta": delta,
            "band_changed": (band_a != band_b) if (band_a and band_b) else None,
        }

    return {"id": f"roundcmp.{label}", "round_a": ra, "round_b": rb, "parameters": parameters}


def downstream_profile(parameter: str, round: int | None = None) -> dict:
    """Per-site values for `parameter`, ordered upstream -> downstream by
    `SITE_DOWNSTREAM_ORDER`, optionally restricted to one detected round's
    date span."""
    date_from = date_to = None
    round_info = None
    if round is not None:
        round_info = round_by_number(round)
        if round_info is None:
            raise ValueError(f"round not found: {round}")
        date_from, date_to = round_info["start"], round_info["end"]

    rows = readings(parameter=parameter, date_from=date_from, date_to=date_to)
    by_site: dict[str, list[float]] = {}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r["value"])

    dp = round_dp(parameter)
    scope = f"round{round}" if round is not None else "alltime"
    sites = []
    for site, order in sorted(SITE_DOWNSTREAM_ORDER.items(), key=lambda kv: kv[1]):
        values = by_site.get(site)
        mean_v = _round(statistics.mean(values), dp) if values else None
        sites.append({
            "id": f"downstream.{parameter}.{scope}.{site}",
            "site": site,
            "downstream_order": order,
            "n": len(values) if values else 0,
            "mean": mean_v,
            "band": classify_band(parameter, mean_v) if mean_v is not None else None,
        })

    return {
        "id": f"downstream.{parameter}.{scope}",
        "parameter": parameter,
        "round": round,
        "round_info": round_info,
        "sites": sites,
    }


def outliers(parameter: str) -> list[dict]:
    """Readings more than 3 median-absolute-deviations (MAD) from their
    own site's median for this parameter.

    Sites where every reading is identical (MAD == 0) are skipped: with no
    spread to measure, "3 MAD" is not a meaningful yardstick and would
    flag perfectly ordinary repeated readings as outliers.
    """
    rows = readings(parameter=parameter)
    by_site: dict[str, list[dict]] = {}
    for r in rows:
        by_site.setdefault(r["site"], []).append(r)

    dp = round_dp(parameter)
    out = []
    for site, site_rows in by_site.items():
        values = [r["value"] for r in site_rows]
        if len(values) < 2:
            continue
        median_v = statistics.median(values)
        mad = statistics.median([abs(v - median_v) for v in values])
        if mad == 0:
            continue
        for r in site_rows:
            deviation = abs(r["value"] - median_v)
            if deviation > 3 * mad:
                out.append({
                    "id": f"outlier.{site}.{parameter}.{r['date']}",
                    "site": site,
                    "parameter": parameter,
                    "date": r["date"],
                    "value": round(r["value"], dp),
                    "site_median": round(median_v, dp),
                    "deviation_in_mads": round(deviation / mad, 2),
                })
    return out


# Physically-plausible ranges used only for the `data_quality` sanity
# check below — these are NOT WFD bands (see wfd.py for those) and the
# build spec does not specify exact numbers, so they are deliberately set
# wide, from general knowledge of UK chalk-stream chemistry and the
# colorimetric test kits volunteers use, so no genuine (if extreme)
# reading in this dataset is flagged. The exception is dissolved oxygen
# and conductivity, where an exact 0.0 reading is flagged deliberately:
# natural flowing water essentially never has zero dissolved oxygen or
# zero conductivity, so 0.0 there is a strong sign the measurement was not
# actually taken (this dataset's only dissolved_oxygen and conductivity
# readings are, in fact, all exactly 0.0 — see data_quality()'s output).
PLAUSIBLE_RANGES = {
    "phosphate": (0.0, 5.0),
    "ammonia": (0.0, 10.0),
    "nitrate": (0.0, 250.0),
    "turbidity": (0.0, 1000.0),
    "dissolved_oxygen": (0.1, 20.0),
    "conductivity": (10.0, 3000.0),
    "water_depth": (0.0, 300.0),
}


def data_quality() -> dict:
    """Coverage report: per site/parameter completeness, sampling gaps
    over 60 days, suspiciously repeated values, and readings outside a
    physically plausible range."""
    conn = get_connection()
    try:
        total_entries = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE w3w_site_code IS NOT NULL AND w3w_site_code != ?",
            (JUNK_SITE_CODE,),
        ).fetchone()[0]
        site_count_rows = conn.execute(
            "SELECT w3w_site_code, COUNT(*) as c FROM entries "
            "WHERE w3w_site_code IS NOT NULL AND w3w_site_code != ? GROUP BY w3w_site_code",
            (JUNK_SITE_CODE,),
        ).fetchall()
        junk_site_entries = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE w3w_site_code = ?", (JUNK_SITE_CODE,)
        ).fetchone()[0]
    finally:
        conn.close()

    site_counts = {r["w3w_site_code"]: r["c"] for r in site_count_rows}
    sites = sorted(site_counts)

    all_dates = [r["date"] for r in readings()]
    latest_overall = max(all_dates) if all_dates else None

    completeness: dict[str, dict] = {}
    gaps: dict[str, dict] = {}
    repeats: list[dict] = []
    implausible: list[dict] = []

    for site in sites:
        n_entries = site_counts[site]
        completeness[site] = {"id": f"dataquality.{site}.completeness", "n_entries": n_entries, "parameters": {}}

        site_dates = sorted({r["date"] for r in readings(site=site)})
        site_gaps = []
        for prev, nxt in zip(site_dates, site_dates[1:]):
            gap_days = (datetime.strptime(nxt, "%Y-%m-%d") - datetime.strptime(prev, "%Y-%m-%d")).days
            if gap_days > 60:
                site_gaps.append({"from": prev, "to": nxt, "days": gap_days})
        if site_dates and latest_overall:
            days_since_last = (
                datetime.strptime(latest_overall, "%Y-%m-%d") - datetime.strptime(site_dates[-1], "%Y-%m-%d")
            ).days
            if days_since_last > 60:
                site_gaps.append({"from": site_dates[-1], "to": latest_overall, "days": days_since_last, "ongoing": True})
        if site_gaps:
            gaps[site] = {"id": f"dataquality.{site}.gaps", "value": site_gaps}

        for p in PARAMETER_ORDER:
            rows = readings(site=site, parameter=p)
            pct = round(100 * len(rows) / n_entries, 1) if n_entries else 0.0
            completeness[site]["parameters"][p] = {
                "id": f"dataquality.{site}.{p}.completeness",
                "n": len(rows),
                "of": n_entries,
                "pct": pct,
            }

            # Suspicious repeats: the same value four or more times running,
            # in chronological order.
            run_value, run_len, run_start, prev_date = None, 0, None, None
            for r in rows:
                if run_len and r["value"] == run_value:
                    run_len += 1
                else:
                    if run_len >= 4:
                        repeats.append({
                            "id": f"dataquality.{site}.{p}.repeat.{run_start}",
                            "site": site, "parameter": p, "value": run_value,
                            "count": run_len, "from": run_start, "to": prev_date,
                        })
                    run_value, run_len, run_start = r["value"], 1, r["date"]
                prev_date = r["date"]
            if run_len >= 4:
                repeats.append({
                    "id": f"dataquality.{site}.{p}.repeat.{run_start}",
                    "site": site, "parameter": p, "value": run_value,
                    "count": run_len, "from": run_start, "to": prev_date,
                })

            lo, hi = PLAUSIBLE_RANGES[p]
            for r in rows:
                if r["value"] < lo or r["value"] > hi:
                    implausible.append({
                        "id": f"dataquality.{site}.{p}.implausible.{r['date']}",
                        "site": site, "parameter": p, "value": r["value"],
                        "date": r["date"], "plausible_range": [lo, hi],
                    })

    return {
        "id": "dataquality",
        "total_entries": total_entries,
        "junk_site_code_entries": junk_site_entries,
        "n_sites": len(sites),
        "latest_sample_date": latest_overall,
        "completeness": completeness,
        "gaps_over_60_days": gaps,
        "suspicious_repeats": repeats,
        "implausible_values": implausible,
    }
