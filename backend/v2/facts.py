"""The facts pack builder: deterministic JSON, computed entirely by
`v2/insights.py` (plus two small, deliberately narrow queries here — see
"Gaps in insights.py" below), that the LLM is given as its only source of
numbers. Every figure in it should trace back to a stable `id` string, per
the build spec, so `verify.py` can check a generated narrative against it
afterwards.

Built last, against `v2/insights.py`, `v2/wfd.py` and `v2/db.py` as they
exist on disk today (2026-08-18), per both addenda:

- Locations, not site codes (V2_SPEC_ADDENDUM.md, Change 3): every fact is
  keyed by what3words address (`w3w`), with river position coming from
  `insights.location_row()` / `location_neighbours()`, which already
  handle a location with no `river_order` gracefully (rank/neighbours
  come back `None` rather than an error or an invented position — see
  V2_SPEC_ADDENDUM_2.md Rule F / point 5 of the follow-up note).
- Ordinal (word-only) readings and test-strip ranges
  (V2_SPEC_ADDENDUM_2.md, Rules B/C): `insights.readings()` already
  excludes ordinal rows from every numeric statistic, and
  `insights.ordinal_readings()` / `ordinal_summary()` are the parallel
  path for category counts. This module never merges the two, and adds
  `words_only_parameters` to every facts pack — the list of parameters
  that, within this report's scope, have zero numeric readings, so
  `verify.py` can flag the model inventing a number for one of them (the
  specific fabrication this whole rebuild exists to stop).
- `not_currently_measured` parameters (dissolved oxygen, conductivity):
  surfaced via `parameters_meta` on every facts pack.

Gaps in insights.py at the time this was written (documented rather than
patched — see the top-level build report; `insights.py`/`wfd.py`/`db.py`
belong to other agents):

1. `wfd.all_parameters()` needs a `usable_counts` dict to compute
   `not_currently_measured`, and the natural helper its own docstring
   names (`insights.usable_counts_by_parameter()`) doesn't exist yet.
   Worked around here (`_parameters_meta()`) by deriving the same counts
   from `insights.data_quality()`'s existing per-parameter breakdown,
   which already carries `n_usable` for every parameter.
2. `insights.ordinal_summary()` doesn't accept `date_from`/`date_to`,
   even though the `ordinal_readings()` it wraps does — so a round- or
   period-scoped ordinal category summary (needed for `round` and
   `catchment` reports) can't be obtained through it. Worked around here
   (`_ordinal_summary_scoped()`) by calling `ordinal_readings()` directly
   and reproducing the same small aggregation `ordinal_summary()` does,
   rather than editing that function.
3. Locations with real observations but no entry in the owner's
   reference spreadsheet (V2_SPEC_ADDENDUM_2.md Rule F) aren't
   surfaced by any `insights.py` function. Read directly here
   (`_locations_missing_reference()`) via `v2.db.get_connection()` — a
   plain, read-only query against the documented `locations` /
   `observations` schema, not a modification to any owned module.
4. Landowner names to keep out of a report's narrative
   (`facts_pack["banned_terms"]`, which `verify.py` checks) come from
   `observations.landowner_raw`, which no `insights.py` function returns.
   Read directly here (`_landowner_names()`) for the same reason as (3).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from v2.db import get_connection
from v2.insights import (
    catchment_summary,
    data_quality,
    location_neighbours,
    location_row,
    location_summary,
    ordinal_readings,
    readings,
    round_by_number,
    round_comparison,
    trend,
)
from v2.wfd import ORDINAL_SCALES, PARAMETER_ORDER, PARAMETERS, all_parameters

MAX_FACTS_PACK_CHARS = 40_000


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_facts_pack(
    report_type: str,
    report_key: str,
    audience: str,
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict:
    """Build the facts pack for one report. Raises `ValueError` (caught by
    `engine.py` and turned into a clean generation failure) if `report_key`
    doesn't identify anything real for `report_type` — e.g. an unknown
    round number, or a comparison key that isn't in the `roundA_vs_roundB`
    form."""
    report_key = str(report_key)
    builders = {
        "location": lambda: _facts_location(report_key, audience),
        "round": lambda: _facts_round(report_key, audience),
        "catchment": lambda: _facts_catchment(report_key, audience, period_start, period_end),
        "comparison": lambda: _facts_comparison(report_key, audience),
        "trend": lambda: _facts_trend(report_key, audience),
        "data_quality": lambda: _facts_data_quality(report_key, audience, period_start, period_end),
    }
    if report_type not in builders:
        raise ValueError(f"unknown report_type: {report_type!r}")
    pack = builders[report_type]()
    return _truncate_for_budget(pack)


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

def _report_meta(report_type, key, audience, period_start=None, period_end=None) -> dict:
    return {
        "id": "report|meta",
        "type": report_type,
        "key": key,
        "audience": audience,
        "period_start": period_start,
        "period_end": period_end,
        "generated_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def _wfd_reference() -> dict:
    out = {}
    for p in PARAMETER_ORDER:
        meta = PARAMETERS[p]
        if meta.get("bands"):
            out[p] = {
                "id": f"wfdref|{p}",
                "unit": meta["unit"],
                "direction": meta["direction"],
                "bands": meta["bands"],
            }
    return out


_WFD_REFERENCE = _wfd_reference()  # static — built once, not per request


def _parameters_meta() -> list[dict]:
    """`not_currently_measured` / `ordinal_scale` per parameter, driven by
    real catchment-wide usable counts from `insights.data_quality()` — see
    gap (1) in the module docstring."""
    dq = data_quality()
    usable_counts = {p: dq["parameters"].get(p, {}).get("n_usable", 0) for p in PARAMETER_ORDER}
    return all_parameters(usable_counts=usable_counts)


def _ordinal_summary_scoped(
    parameter: str,
    w3w: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scope_label: str = "catchment",
) -> dict | None:
    """Category counts, modal category and distribution for an
    ordinal-scale parameter, scoped by date range as well as location —
    see gap (2) in the module docstring for why this isn't just a call to
    `insights.ordinal_summary()`. Mirrors that function's output shape and
    id scheme exactly (`ordinal|<scope>|<parameter>`) for consistency."""
    scale = ORDINAL_SCALES.get(parameter)
    if not scale:
        return None

    rows = ordinal_readings(w3w=w3w, parameter=parameter, date_from=date_from, date_to=date_to)
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
        "id": f"ordinal|{scope_label}|{parameter}",
        "n_usable": total,
        "modal_category": modal["category"] if modal and modal["count"] else None,
        "modal_label": modal["label"] if modal and modal["count"] else None,
        "modal_rank": modal["rank"] if modal and modal["count"] else None,
        "distribution": distribution,
        "first_date": min(dates) if dates else None,
        "last_date": max(dates) if dates else None,
    }


def _words_only_parameters(w3w: str | None = None, date_from: str | None = None, date_to: str | None = None) -> list[str]:
    """Ordinal-capable parameters (turbidity, water depth) with zero
    numeric readings in this scope — see `verify.find_banned_terms`, which
    uses this list to catch the model inventing a number for one of them."""
    return [p for p in ORDINAL_SCALES if not readings(w3w=w3w, parameter=p, date_from=date_from, date_to=date_to)]


def _landowner_names(w3w: str | None = None, date_from: str | None = None, date_to: str | None = None) -> list[str]:
    """Distinct, non-empty `landowner_raw` values in scope — see gap (4)
    in the module docstring. `verify.py` bans any of these appearing in a
    report's narrative, per the build spec: a handful of water samples
    cannot support naming or implying blame for a landowner."""
    conn = get_connection()
    try:
        conditions = ["excluded = 0", "landowner_raw IS NOT NULL", "landowner_raw != ''"]
        params: list = []
        if w3w:
            conditions.append("w3w = ?")
            params.append(w3w)
        if date_from:
            conditions.append("sample_date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("sample_date <= ?")
            params.append(date_to)
        where = " AND ".join(conditions)
        rows = conn.execute(f"SELECT DISTINCT landowner_raw FROM observations WHERE {where}", params).fetchall()
    finally:
        conn.close()
    return sorted({r["landowner_raw"].strip() for r in rows if r["landowner_raw"] and r["landowner_raw"].strip()})


def _locations_missing_reference() -> list[dict]:
    """Locations with real observations but no `river_order`/coordinates
    because they aren't in the owner's reference spreadsheet
    (V2_SPEC_ADDENDUM_2.md, Rule F) — see gap (3) in the module docstring."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT l.w3w AS w3w, COUNT(o.ec5_uuid) AS n
            FROM locations l
            JOIN observations o ON o.w3w = l.w3w AND o.excluded = 0
            WHERE l.source != 'reference_table'
            GROUP BY l.w3w
            ORDER BY l.w3w
            """
        ).fetchall()
    finally:
        conn.close()
    return [{"w3w": r["w3w"], "n_observations": r["n"]} for r in rows]


# ---------------------------------------------------------------------------
# Per report-type builders
# ---------------------------------------------------------------------------

def _facts_location(w3w: str, audience: str) -> dict:
    summary = location_summary(w3w)
    neighbours = location_neighbours(w3w)
    loc_row = summary.get("location") or {}

    position = {
        "id": f"location|{w3w}|position",
        "river_order": loc_row.get("river_order"),
        "rank": neighbours["rank"],
        "n_locations": neighbours["n_locations"],
        "upstream_neighbour": neighbours["neighbours"]["upstream"],
        "downstream_neighbour": neighbours["neighbours"]["downstream"],
        "latitude": loc_row.get("latitude"),
        "longitude": loc_row.get("longitude"),
        "position_known": loc_row.get("river_order") is not None,
    }

    trends = {p: trend(w3w, p) for p in PARAMETER_ORDER}
    ordinal_summaries = {}
    for p in ORDINAL_SCALES:
        s = _ordinal_summary_scoped(p, w3w=w3w, scope_label=w3w)
        if s and s["n_usable"]:
            ordinal_summaries[p] = s

    return {
        "report": _report_meta("location", w3w, audience),
        "location": summary,
        "position": position,
        "trends": trends,
        "ordinal_summaries": ordinal_summaries,
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": _words_only_parameters(w3w=w3w),
        "banned_terms": _landowner_names(w3w=w3w),
    }


_ROUND_KEY_RE = re.compile(r"(\d+)")


def _parse_round_key(key: str) -> int:
    m = _ROUND_KEY_RE.search(key)
    if not m:
        raise ValueError(f"round report key {key!r} does not contain a round number (expected e.g. '3' or 'round3')")
    return int(m.group(1))


def _facts_round(key: str, audience: str) -> dict:
    n = _parse_round_key(key)
    info = round_by_number(n)
    if info is None:
        raise ValueError(f"round not found: {key!r} (no detected round #{n})")
    prev_info = round_by_number(n - 1) if n > 1 else None

    summary = catchment_summary(date_from=info["start"], date_to=info["end"])
    comparison = None
    if prev_info:
        try:
            comparison = round_comparison(n - 1, n)
        except ValueError:
            comparison = None

    ordinal_summaries = {}
    for p in ORDINAL_SCALES:
        s = _ordinal_summary_scoped(p, date_from=info["start"], date_to=info["end"], scope_label=f"round{n}")
        if s and s["n_usable"]:
            ordinal_summaries[p] = s

    return {
        "report": _report_meta("round", str(n), audience, period_start=info["start"], period_end=info["end"]),
        "round": info,
        "previous_round": prev_info,
        "catchment": summary,
        "round_comparison": comparison,
        "ordinal_summaries": ordinal_summaries,
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": _words_only_parameters(date_from=info["start"], date_to=info["end"]),
        "banned_terms": _landowner_names(date_from=info["start"], date_to=info["end"]),
    }


def _facts_catchment(key: str, audience: str, period_start: str | None, period_end: str | None) -> dict:
    summary = catchment_summary(date_from=period_start, date_to=period_end)
    dq = data_quality()
    trends = {p: trend(None, p) for p in PARAMETER_ORDER}

    ordinal_summaries = {}
    for p in ORDINAL_SCALES:
        s = _ordinal_summary_scoped(p, date_from=period_start, date_to=period_end, scope_label="catchment")
        if s and s["n_usable"]:
            ordinal_summaries[p] = s

    return {
        "report": _report_meta("catchment", key, audience, period_start=period_start, period_end=period_end),
        "catchment": summary,
        "trends": trends,
        "ordinal_summaries": ordinal_summaries,
        "data_quality_summary": {
            "id": "dataquality|summary",
            "total_observations": dq["total_observations"],
            "by_location_status": dq["by_location_status"],
            "excluded_reasons": dq["excluded_reasons"],
            "n_unlocated": len(dq["unlocated"]),
            "latest_sample_date": dq["latest_sample_date"],
        },
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": _words_only_parameters(date_from=period_start, date_to=period_end),
        "banned_terms": _landowner_names(date_from=period_start, date_to=period_end),
    }


_COMPARISON_KEY_RE = re.compile(r"^(?:round)?(\d+)_vs_(?:round)?(\d+)$", re.IGNORECASE)


def _facts_comparison(key: str, audience: str) -> dict:
    m = _COMPARISON_KEY_RE.match(key.strip())
    if not m:
        raise ValueError(
            f"comparison report key {key!r} not understood; expected the form 'roundA_vs_roundB' "
            "(e.g. 'round3_vs_round5')"
        )
    round_a, round_b = int(m.group(1)), int(m.group(2))
    cmp_result = round_comparison(round_a, round_b)

    words_only = [
        p for p in ORDINAL_SCALES
        if not readings(parameter=p, date_from=cmp_result["round_a"]["start"], date_to=cmp_result["round_a"]["end"])
        and not readings(parameter=p, date_from=cmp_result["round_b"]["start"], date_to=cmp_result["round_b"]["end"])
    ]

    return {
        "report": _report_meta(
            "comparison", key, audience,
            period_start=cmp_result["round_a"]["start"], period_end=cmp_result["round_b"]["end"],
        ),
        "comparison": cmp_result,
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": words_only,
        "banned_terms": _landowner_names(
            date_from=cmp_result["round_a"]["start"], date_to=cmp_result["round_b"]["end"]
        ),
    }


def _facts_trend(parameter: str, audience: str) -> dict:
    if parameter not in PARAMETER_ORDER:
        raise ValueError(f"unknown parameter for trend report: {parameter!r}")

    catchment_trend = trend(None, parameter)
    per_location_trends = {}
    for loc in _located_w3ws():
        t = trend(loc, parameter)
        if t["status"] == "ok":
            per_location_trends[loc] = t

    ordinal_summary = None
    if parameter in ORDINAL_SCALES:
        s = _ordinal_summary_scoped(parameter, scope_label="catchment")
        if s and s["n_usable"]:
            ordinal_summary = s

    return {
        "report": _report_meta("trend", parameter, audience),
        "parameter": parameter,
        "catchment_trend": catchment_trend,
        "per_location_trends": per_location_trends,
        "ordinal_summary": ordinal_summary,
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": _words_only_parameters(),
        "banned_terms": _landowner_names(),
    }


def _facts_data_quality(key: str, audience: str, period_start: str | None, period_end: str | None) -> dict:
    dq = data_quality()
    return {
        "report": _report_meta("data_quality", key, audience, period_start=period_start, period_end=period_end),
        "data_quality": dq,
        "locations_missing_reference_table": _locations_missing_reference(),
        "parameters_meta": _parameters_meta(),
        "wfd_reference": _WFD_REFERENCE,
        "words_only_parameters": [],
        "banned_terms": _landowner_names(),
    }


def _located_w3ws() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT w3w FROM locations ORDER BY w3w").fetchall()
    finally:
        conn.close()
    return [r["w3w"] for r in rows]


# ---------------------------------------------------------------------------
# Size budget
# ---------------------------------------------------------------------------

def _pack_size(pack: dict) -> int:
    return len(json.dumps(pack, ensure_ascii=False))


def _trim_list(container: dict, key: str, keep: int = 15) -> None:
    items = container.get(key)
    if isinstance(items, list) and len(items) > keep:
        container[f"{key}_omitted_count"] = len(items) - keep
        container[key] = items[:keep]


def _trim_dict(container: dict, key: str, keep: int = 30) -> None:
    items = container.get(key)
    if isinstance(items, dict) and len(items) > keep:
        keep_keys = list(items)[:keep]
        container[f"{key}_omitted_count"] = len(items) - keep
        container[key] = {k: items[k] for k in keep_keys}


def _truncate_for_budget(pack: dict) -> dict:
    """Keep the facts pack under `MAX_FACTS_PACK_CHARS` by trimming the
    largest, lowest-value list/dict fields first — individual records,
    never summary statistics — per the build spec ('truncate lowest-value
    detail first: individual readings before summary statistics')."""
    if _pack_size(pack) <= MAX_FACTS_PACK_CHARS:
        return pack

    dq = pack.get("data_quality")
    if isinstance(dq, dict):
        _trim_list(dq, "unlocated")
        _trim_list(dq, "suspicious_repeats")
        _trim_dict(dq, "gaps_over_60_days")

    catchment = pack.get("catchment")
    if isinstance(catchment, dict):
        _trim_dict(catchment, "location_rollup")

    _trim_dict(pack, "per_location_trends")

    return pack
