"""v2 data API — read-only GET endpoints under `/api/v2`.

This module only implements the "Data:" endpoints from the build spec.
The "Reports:" endpoints (report generation, jobs, downloads) belong to
`v2/reports_api.py`, owned separately — `main_v2.py` includes that
router too, if present.

All of these are unauthenticated GETs, same as v1 — the spec only asks
for auth on `POST /reports/generate`, which lives in reports_api.py.
"""

from __future__ import annotations

import csv
import io
import statistics

from fastapi import APIRouter, HTTPException, Query, Response

from coords import SITE_COORDS, SITE_DOWNSTREAM_ORDER
from v2.db import get_connection
from v2.insights import (
    JUNK_SITE_CODE,
    data_quality,
    detect_rounds,
    downstream_profile,
    readings,
    round_dp,
    site_summary,
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

@router.get("/overview")
def get_overview():
    """Headline state of the river: latest round, per-parameter catchment
    band, count of sites in each band, sampling coverage, most recent
    sample date."""
    rounds = detect_rounds()
    latest_round = rounds[-1] if rounds else None

    all_rows = readings()
    sites = sorted({r["site"] for r in all_rows})
    all_dates = [r["date"] for r in all_rows]
    most_recent_sample_date = max(all_dates) if all_dates else None

    parameters = {}
    for p in PARAMETER_ORDER:
        rows = readings(parameter=p)
        # Latest reading per site (rows are date/time ascending, so the
        # last occurrence per site is the most recent one).
        latest_per_site: dict[str, float] = {}
        for r in rows:
            latest_per_site[r["site"]] = r["value"]

        sites_in_band: dict[str, int] = {}
        for value in latest_per_site.values():
            band = classify_band(p, value)
            if band:
                sites_in_band[band] = sites_in_band.get(band, 0) + 1

        catchment_mean = statistics.mean([r["value"] for r in rows]) if rows else None
        parameters[p] = {
            "id": f"overview.{p}",
            "unit": PARAMETERS[p]["unit"],
            "n_readings": len(rows),
            "n_sites_with_data": len(latest_per_site),
            "catchment_band": classify_band(p, catchment_mean) if catchment_mean is not None else None,
            "sites_in_band": sites_in_band,
        }

    return {
        "latest_round": latest_round,
        "n_rounds": len(rounds),
        "most_recent_sample_date": most_recent_sample_date,
        "n_sites": len(sites),
        "parameters": parameters,
    }


# ── /sites, /sites/{code} ────────────────────────────────────────────

@router.get("/sites")
def list_sites():
    """Sites with position, coordinates, sample count, and the latest
    reading + band per parameter."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT w3w_site_code, COUNT(*) as c, MIN(sample_date) as first_seen, MAX(sample_date) as last_seen "
            "FROM entries WHERE w3w_site_code IS NOT NULL AND w3w_site_code != ? "
            "GROUP BY w3w_site_code",
            (JUNK_SITE_CODE,),
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        code = r["w3w_site_code"]
        latest_bands = {}
        for p in PARAMETER_ORDER:
            p_rows = readings(site=code, parameter=p)
            if p_rows:
                latest = p_rows[-1]
                latest_bands[p] = {
                    "value": latest["value"],
                    "date": latest["date"],
                    "band": classify_band(p, latest["value"]),
                }
            else:
                latest_bands[p] = None
        out.append({
            "code": code,
            "coordinates": SITE_COORDS.get(code),
            "downstream_order": SITE_DOWNSTREAM_ORDER.get(code),
            "count": r["c"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "latest_bands": latest_bands,
        })

    out.sort(key=lambda s: (s["downstream_order"] is None, s["downstream_order"] or 0))
    return {"sites": out}


def _downstream_neighbours(code: str):
    ordered = sorted(SITE_DOWNSTREAM_ORDER.items(), key=lambda kv: kv[1])
    rank = next((i + 1 for i, (c, _) in enumerate(ordered) if c == code), None)
    neighbours = {"upstream": None, "downstream": None}
    if rank is not None:
        idx = rank - 1
        if idx > 0:
            neighbours["upstream"] = ordered[idx - 1][0]
        if idx < len(ordered) - 1:
            neighbours["downstream"] = ordered[idx + 1][0]
    return rank, len(ordered), neighbours


def _site_photos(code: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT sample_date, photo_url, photo_desc, photo_2_url FROM entries "
            "WHERE w3w_site_code = ? AND ("
            "  (photo_url IS NOT NULL AND photo_url != '') OR "
            "  (photo_2_url IS NOT NULL AND photo_2_url != '')"
            ") ORDER BY sample_date DESC",
            (code,),
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


@router.get("/sites/{code}")
def get_site(code: str):
    """Full site summary: per-parameter stats, trends, latest readings,
    position on the river relative to its neighbours, and photos."""
    if code == JUNK_SITE_CODE:
        raise HTTPException(404, "Unknown site")

    summary = site_summary(code)
    if summary["first_sampled"] is None:
        raise HTTPException(404, f"No data for site {code}")

    rank, n_sites_total, neighbours = _downstream_neighbours(code)
    trends = {p: trend(code, p) for p in PARAMETER_ORDER}

    return {
        "code": code,
        "coordinates": SITE_COORDS.get(code),
        "downstream_order": SITE_DOWNSTREAM_ORDER.get(code),
        "downstream_rank": rank,
        "n_sites_total": n_sites_total,
        "neighbours": neighbours,
        "summary": summary,
        "trends": trends,
        "photos": _site_photos(code),
    }


# ── /series ───────────────────────────────────────────────────────────

@router.get("/series")
def get_series(
    parameter: str = Query(..., pattern=PARAMETER_PATTERN),
    site: str | None = Query(None),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """Time series for one parameter, with WFD band thresholds attached so
    the frontend can shade the chart into bands rather than drawing bare
    reference lines."""
    dp = round_dp(parameter)
    rows = readings(site=site, parameter=parameter, date_from=date_from, date_to=date_to)
    points = [
        {
            "site": r["site"],
            "date": r["date"],
            "time": r["time"],
            "value": round(r["value"], dp),
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
        "site": site,
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
    """Upstream -> downstream profile for one parameter, optionally
    restricted to a single detected round."""
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
    bands (same round-detection algorithm as v1, so round numbers agree)."""
    rounds = detect_rounds()
    out = [{**r, "parameters": _round_parameter_summary(r["start"], r["end"])} for r in rounds]
    return {"rounds": out}


@router.get("/rounds/{n}")
def get_round(n: int):
    """One round, broken out by site."""
    r = next((x for x in detect_rounds() if x["round"] == n), None)
    if r is None:
        raise HTTPException(404, f"Round {n} not found")

    sites_data = {}
    for site in sorted(SITE_DOWNSTREAM_ORDER):
        per_param = {}
        has_any = False
        for p in PARAMETER_ORDER:
            vals = [row["value"] for row in readings(site=site, parameter=p, date_from=r["start"], date_to=r["end"])]
            if vals:
                has_any = True
                dp = round_dp(p)
                mean_v = round(statistics.mean(vals), dp)
                per_param[p] = {"n": len(vals), "mean": mean_v, "band": classify_band(p, mean_v)}
            else:
                per_param[p] = {"n": 0, "mean": None, "band": None}
        if has_any:
            sites_data[site] = per_param

    return {"round": r, "parameters": _round_parameter_summary(r["start"], r["end"]), "sites": sites_data}


# ── /data-quality ─────────────────────────────────────────────────────

@router.get("/data-quality")
def get_data_quality():
    """Coverage report: completeness, sampling gaps, suspicious repeats,
    and implausible values, per site and parameter."""
    return data_quality()


# ── /export.csv ───────────────────────────────────────────────────────

@router.get("/export.csv")
def export_csv(
    site: str | None = Query(None),
    parameter: str | None = Query(None, pattern=PARAMETER_PATTERN),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """Tidy CSV of readings — one row per reading — for the minority of
    readers who want the raw numbers rather than a chart."""
    parameters_to_export = [parameter] if parameter else PARAMETER_ORDER

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["site", "date", "time", "parameter", "value", "unit", "band"])
    for p in parameters_to_export:
        unit = PARAMETERS[p]["unit"]
        for r in readings(site=site, parameter=p, date_from=date_from, date_to=date_to):
            writer.writerow([r["site"], r["date"], r["time"], p, r["value"], unit, classify_band(p, r["value"]) or ""])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=coln-readings.csv"},
    )
