"""v2 data API — read-only GET endpoints under `/api/v2`.

This module only implements the "Data:" endpoints from the build spec, as
revised by V2_SPEC_ADDENDUM.md: locations (what3words points), not v1's
volunteer-initials "sites". The "Reports:" endpoints (report generation,
jobs, downloads) belong to `v2/reports_api.py`, owned separately —
`main_v2.py` includes that router too, if present.

All of these are unauthenticated GETs, same as v1 — the spec only asks
for auth on `POST /reports/generate`, which lives in reports_api.py.
"""

from __future__ import annotations

import csv
import io
import statistics

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query, Response
from pydantic import BaseModel

from v2.reports_api import require_admin

from v2.db import get_connection
from v2.insights import (
    ordinal_readings,
    data_quality,
    detect_rounds,
    downstream_profile,
    location_neighbours,
    location_row,
    location_summary,
    ordered_locations,
    readings,
    round_dp,
    trend,
)
from v2.wfd import (
    BAND_GLOSS,
    BAND_NAMES,
    PARAMETER_ORDER,
    PARAMETERS,
    all_parameters,
    classify_band,
)

router = APIRouter(prefix="/api/v2", tags=["v2"])

PARAMETER_PATTERN = "^(" + "|".join(PARAMETER_ORDER) + ")$"


# ── /parameters ────────────────────────────────────────────────────────

@router.get("/parameters")
def get_parameters():
    """Plain-English parameter metadata + WFD bands — the single source
    the frontend's glossary page ('What we measure') and every chart's
    band legend are built from."""
    return {
        "parameters": all_parameters(),
        "band_names": BAND_NAMES,
        "band_gloss": BAND_GLOSS,
    }


# ── /overview ─────────────────────────────────────────────────────────

# Below this many usable numeric readings, a catchment-wide grade says
# more about the sample size than about the river.
MIN_READINGS_FOR_CATCHMENT_BAND = 20


@router.get("/overview")
def get_overview():
    """Headline state of the river: latest round, per-parameter catchment
    band, count of locations in each band, sampling coverage, most recent
    sample date."""
    rounds = detect_rounds()
    latest_round = rounds[-1] if rounds else None

    all_rows = readings()
    locations_with_data = sorted({r["w3w"] for r in all_rows if r["w3w"] is not None})
    all_dates = [r["date"] for r in all_rows]
    most_recent_sample_date = max(all_dates) if all_dates else None

    parameters = {}
    for p in PARAMETER_ORDER:
        rows = readings(parameter=p)
        # Latest reading per location (rows are date/time ascending, so
        # the last occurrence per location is the most recent one).
        latest_per_location: dict[str, float] = {}
        for r in rows:
            if r["w3w"] is None:
                continue
            latest_per_location[r["w3w"]] = r["value"]

        locations_in_band: dict[str, int] = {}
        for value in latest_per_location.values():
            band = classify_band(p, value)
            if band:
                locations_in_band[band] = locations_in_band.get(band, 0) + 1

        catchment_mean = statistics.mean([r["value"] for r in rows]) if rows else None

        # Two parameters must not carry a headline band, for different
        # reasons, and both would otherwise mislead badly:
        #
        #  - dissolved oxygen and conductivity have a handful of readings
        #    each out of 489. Grading the whole river from 4 numbers --
        #    several of which the cleaner flagged as implausible -- would
        #    state something the data cannot support.
        #  - turbidity is recorded in words far more often than with a
        #    meter. Banding it from the ~10 numeric readings ignores the
        #    ~359 written observations and reports a minority as if it
        #    were the whole picture.
        n_ordinal = len(ordinal_readings(parameter=p))
        mostly_words = n_ordinal > len(rows)
        thin = len(rows) < MIN_READINGS_FOR_CATCHMENT_BAND
        band = None
        if catchment_mean is not None and not thin and not mostly_words:
            band = classify_band(p, catchment_mean)

        parameters[p] = {
            "id": f"overview|{p}",
            "unit": PARAMETERS[p]["unit"],
            "n_readings": len(rows),
            "n_ordinal_readings": n_ordinal,
            "n_locations_with_data": len(latest_per_location),
            "catchment_band": band,
            "band_withheld_reason": (
                "too few readings to grade the whole river" if thin and catchment_mean is not None
                else "recorded in words far more often than with a meter" if mostly_words
                else None
            ),
            "not_currently_measured": thin,
            "mostly_written_observations": mostly_words,
            "locations_in_band": locations_in_band,
        }

    return {
        "latest_round": latest_round,
        "n_rounds": len(rounds),
        "most_recent_sample_date": most_recent_sample_date,
        "n_locations": len(locations_with_data),
        "parameters": parameters,
    }


# ── /locations, /locations/{w3w} ───────────────────────────────────────

@router.get("/locations")
def list_locations():
    """What3words locations with position, coordinates, sample count, and
    the latest reading + band per parameter. A location's human label is
    its what3words address itself — never a volunteer's initials (those
    are recorders, not places; see `recorder` on `/locations/{w3w}`)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT o.w3w, COUNT(*) as c, MIN(o.sample_date) as first_seen, MAX(o.sample_date) as last_seen "
            "FROM observations o WHERE o.w3w IS NOT NULL AND o.excluded = 0 "
            "GROUP BY o.w3w"
        ).fetchall()
    finally:
        conn.close()

    loc_meta = {loc["w3w"]: loc for loc in ordered_locations()}

    out = []
    for r in rows:
        w3w = r["w3w"]
        meta = loc_meta.get(w3w)
        latest_bands = {}
        for p in PARAMETER_ORDER:
            p_rows = readings(w3w=w3w, parameter=p)
            if p_rows:
                latest = p_rows[-1]
                latest_bands[p] = {
                    "value": latest["value"],
                    "date": latest["date"],
                    "band": classify_band(p, latest["value"]),
                    "qualifier": latest["qualifier"],
                }
            else:
                latest_bands[p] = None
        out.append({
            "w3w": w3w,
            "label": w3w,
            "river_order": meta["river_order"] if meta else None,
            "latitude": meta["latitude"] if meta else None,
            "longitude": meta["longitude"] if meta else None,
            "count": r["c"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "latest_bands": latest_bands,
        })

    out.sort(key=lambda loc: (loc["river_order"] is None, loc["river_order"] or 0))
    return {
        "locations": out,
        "precision_note": (
            "What3words addresses are 3m squares recorded by volunteers, and reference "
            "coordinates were supplied by the group. Positions are accurate to roughly the "
            "riverbank they were taken from, not survey-grade."
        ),
    }


def _location_photos(w3w: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT sample_date, photo_url, photo_2_url, photo_desc FROM observations "
            "WHERE w3w = ? AND excluded = 0 AND ("
            "  (photo_url IS NOT NULL AND photo_url != '') OR "
            "  (photo_2_url IS NOT NULL AND photo_2_url != '')"
            ") ORDER BY sample_date DESC",
            (w3w,),
        ).fetchall()
    finally:
        conn.close()

    photos = []
    for r in rows:
        if r["photo_url"]:
            photos.append({"url": r["photo_url"], "description": r["photo_desc"], "date": r["sample_date"]})
        if r["photo_2_url"]:
            photos.append({"url": r["photo_2_url"], "description": None, "date": r["sample_date"]})
    return photos


@router.get("/locations/{w3w}")
def get_location(w3w: str):
    """Full location summary: per-parameter stats, trends, latest
    readings, position on the river relative to its neighbours, and
    photos. Keyed by the what3words address, never by a volunteer's
    initials."""
    summary = location_summary(w3w)
    if summary["first_sampled"] is None:
        raise HTTPException(404, f"No data for location {w3w}")

    nb = location_neighbours(w3w)
    trends = {p: trend(w3w, p) for p in PARAMETER_ORDER}
    loc = location_row(w3w)

    return {
        "w3w": w3w,
        "label": w3w,
        "location": loc,
        "downstream_rank": nb["rank"],
        "n_locations_total": nb["n_locations"],
        "neighbours": nb["neighbours"],
        "summary": summary,
        "trends": trends,
        "photos": _location_photos(w3w),
        "precision_note": (
            "This position is accurate to roughly the riverbank it was taken from, not "
            "survey-grade."
        ),
    }


# ── /series ───────────────────────────────────────────────────────────

@router.get("/series")
def get_series(
    parameter: str = Query(..., pattern=PARAMETER_PATTERN),
    w3w: str | None = Query(None),
    recorder: str | None = Query(None, description="Filter by the volunteer who took the sample (metadata, not a place)"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """Time series for one parameter, with WFD band thresholds attached so
    the frontend can shade the chart into bands rather than drawing bare
    reference lines."""
    dp = round_dp(parameter)
    rows = readings(w3w=w3w, parameter=parameter, date_from=date_from, date_to=date_to, recorder=recorder)
    points = [
        {
            "w3w": r["w3w"],
            "recorder": r["recorder"],
            "date": r["date"],
            "time": r["time"],
            "value": round(r["value"], dp),
            "qualifier": r["qualifier"],
            "band": classify_band(parameter, r["value"]),
        }
        for r in rows
    ]
    meta = PARAMETERS[parameter]
    return {
        "parameter": parameter,
        "label": meta["label"],
        "unit": meta["unit"],
        "direction": meta["direction"],
        "w3w": w3w,
        "recorder": recorder,
        "date_from": date_from,
        "date_to": date_to,
        "bands": meta["bands"],
        "n": len(points),
        "points": points,
    }


# ── /downstream ───────────────────────────────────────────────────────

@router.get("/downstream")
def get_downstream(
    parameter: str = Query(..., pattern=PARAMETER_PATTERN),
    round: int | None = Query(None),
):
    """Upstream -> downstream profile for one parameter, ordered by the
    reference table's true river position, optionally restricted to a
    single detected round."""
    try:
        return downstream_profile(parameter, round)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ── /rounds, /rounds/{n} ─────────────────────────────────────────────

def _round_parameter_summary(start: str, end: str) -> dict:
    parameters = {}
    for p in PARAMETER_ORDER:
        vals = [r["value"] for r in readings(parameter=p, date_from=start, date_to=end)]
        if vals:
            dp = round_dp(p)
            mean_v = round(statistics.mean(vals), dp)
            parameters[p] = {"n": len(vals), "mean": mean_v, "band": classify_band(p, mean_v)}
        else:
            parameters[p] = {"n": 0, "mean": None, "band": None}
    return parameters


@router.get("/rounds")
def list_rounds():
    """Detected sampling rounds with per-parameter catchment means and
    bands (same round-detection algorithm as v1, now run over v2's
    `observations`, so round numbers agree with v1's)."""
    rounds = detect_rounds()
    out = [{**r, "parameters": _round_parameter_summary(r["start"], r["end"])} for r in rounds]
    return {"rounds": out}


@router.get("/rounds/{n}")
def get_round(n: int):
    """One round, broken out by location."""
    r = next((x for x in detect_rounds() if x["round"] == n), None)
    if r is None:
        raise HTTPException(404, f"Round {n} not found")

    locations_data = {}
    for loc in ordered_locations():
        w3w = loc["w3w"]
        per_param = {}
        has_any = False
        for p in PARAMETER_ORDER:
            vals = [row["value"] for row in readings(w3w=w3w, parameter=p, date_from=r["start"], date_to=r["end"])]
            if vals:
                has_any = True
                dp = round_dp(p)
                mean_v = round(statistics.mean(vals), dp)
                per_param[p] = {"n": len(vals), "mean": mean_v, "band": classify_band(p, mean_v)}
            else:
                per_param[p] = {"n": 0, "mean": None, "band": None}
        if has_any:
            locations_data[w3w] = per_param

    return {"round": r, "parameters": _round_parameter_summary(r["start"], r["end"]), "locations": locations_data}


# ── /data-quality ─────────────────────────────────────────────────────

@router.get("/data-quality")
def get_data_quality():
    """Coverage and honesty report: exclusions, unresolved locations,
    cleaning actions, per-parameter usable/excluded counts, sampling
    gaps, and suspicious repeats."""
    return data_quality()


# ── /export.csv ───────────────────────────────────────────────────────

@router.get("/export.csv")
def export_csv(
    w3w: str | None = Query(None),
    parameter: str | None = Query(None, pattern=PARAMETER_PATTERN),
    recorder: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """Tidy CSV of usable readings — one row per reading — for the
    minority of readers who want the raw numbers rather than a chart."""
    parameters_to_export = [parameter] if parameter else PARAMETER_ORDER

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["w3w", "recorder", "date", "time", "parameter", "value", "qualifier", "unit", "band"])
    for p in parameters_to_export:
        unit = PARAMETERS[p]["unit"]
        for r in readings(w3w=w3w, parameter=p, date_from=date_from, date_to=date_to, recorder=recorder):
            writer.writerow([
                r["w3w"] or "", r["recorder"] or "", r["date"], r["time"], p,
                r["value"], r["qualifier"], unit, classify_band(p, r["value"]) or "",
            ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=coln-readings.csv"},
    )


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------
#
# Readings the cleaning pipeline could not interpret with confidence, and
# locations that may be duplicates. Nothing here has been applied to the
# data: a decision writes a `manual_corrections` row, which the next
# ingest rebuild picks up. That keeps human judgement out of the derived
# tables until somebody actually makes it, and reversible afterwards.


@router.get("/review-queue")
def get_review_queue(status: str = Query("open", pattern="^(open|accepted|rejected|all)$")):
    conn = get_connection()
    try:
        if status == "all":
            rows = conn.execute("SELECT * FROM review_queue ORDER BY issue, id").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM review_queue WHERE status = ? ORDER BY issue, id", (status,)
            ).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


class ReviewDecision(BaseModel):
    status: str
    resolved_value: str | None = None
    resolved_by: str | None = None


@router.post("/review-queue/{item_id}")
def decide_review_item(
    item_id: int,
    decision: ReviewDecision,
    authorization: str | None = Header(default=None),
):
    require_admin(authorization)
    if decision.status not in ("accepted", "rejected"):
        raise HTTPException(400, "status must be 'accepted' or 'rejected'")

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM review_queue WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "No such review item.")

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE review_queue SET status = ?, resolved_value = ?, resolved_at = ?, "
            "resolved_by = ? WHERE id = ?",
            (decision.status, decision.resolved_value, now,
             decision.resolved_by or "owner", item_id),
        )

        # Only an accepted value-correction changes a reading, and even
        # then only via manual_corrections -- never by editing
        # `measurements` here. An accepted location merge is recorded but
        # left for the ingest step, which owns the locations table.
        if (decision.status == "accepted" and decision.resolved_value
                and row["parameter"] and row["issue"] != "ambiguous_location"):
            conn.execute(
                "INSERT INTO manual_corrections (ec5_uuid, parameter, value, note, created_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(ec5_uuid, parameter) DO UPDATE SET "
                "value=excluded.value, note=excluded.note, created_at=excluded.created_at",
                (row["ec5_uuid"], row["parameter"], decision.resolved_value,
                 f"accepted from review queue: {row['issue']}", now),
            )
        conn.commit()
    finally:
        conn.close()
    return {"id": item_id, "status": decision.status}
