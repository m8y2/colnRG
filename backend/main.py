import json
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database import get_connection, init_db, get_last_sync
from sync import run_sync, SITE_CODE_MAP
from coords import SITE_COORDS, SITE_DOWNSTREAM_ORDER

app = FastAPI(title="Coln River Guardians Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    conn = get_connection()
    ok = False
    try:
        conn.execute("SELECT 1").fetchone()
        ok = True
    except Exception:
        pass
    conn.close()
    return {
        "status": "ok" if ok else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/stats")
def get_stats():
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    sites = conn.execute(
        "SELECT COUNT(DISTINCT w3w_site_code) FROM entries WHERE w3w_site_code IS NOT NULL"
    ).fetchone()[0]
    date_range = conn.execute(
        "SELECT MIN(sample_date), MAX(sample_date) FROM entries WHERE sample_date IS NOT NULL"
    ).fetchone()
    with_photos = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE photo_url IS NOT NULL AND photo_url != ''"
    ).fetchone()[0]
    conn.close()

    last_sync = get_last_sync()

    return {
        "total_entries": total,
        "total_sites": sites,
        "date_from": date_range[0] if date_range else None,
        "date_to": date_range[1] if date_range else None,
        "entries_with_photos": with_photos,
        "last_sync": last_sync,
    }


@app.get("/api/entries")
def get_entries(
    site: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    chemical: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
):
    conn = get_connection()
    conditions = []
    params = []

    if site:
        conditions.append("w3w_site_code = ?")
        params.append(site)
    if date_from:
        conditions.append("sample_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("sample_date <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    count = conn.execute(f"SELECT COUNT(*) FROM entries {where}", params).fetchone()[0]

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM entries {where} ORDER BY sample_date DESC, sample_time DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    conn.close()

    entries = [dict(r) for r in rows]

    return {
        "total": count,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (count + per_page - 1) // per_page),
        "entries": entries,
    }


@app.get("/api/sites")
def get_sites():
    conn = get_connection()
    rows = conn.execute("""
        SELECT w3w_site_code, COUNT(*) as count,
               MIN(sample_date) as first_seen, MAX(sample_date) as last_seen
        FROM entries
        WHERE w3w_site_code IS NOT NULL
        GROUP BY w3w_site_code
        ORDER BY count DESC
    """).fetchall()
    conn.close()

    sites = []
    for r in rows:
        code = r["w3w_site_code"]
        sites.append({
            "code": code,
            "name": SITE_CODE_MAP.get(code, code),
            "count": r["count"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "coordinates": SITE_COORDS.get(code),
        })
    return sites


@app.get("/api/chemicals")
def get_chemical_readings(
    chemical: str = Query(..., pattern="^(phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth)$"),
    site: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
):
    col_map = {
        "phosphate": "phosphate_level",
        "ammonia": "ammonia_level",
        "nitrate": "nitrate_level",
        "turbidity": "turbidity",
        "dissolved_oxygen": "dissolved_oxygen",
        "conductivity": "conductivity",
        "water_depth": "water_depth_cm",
    }
    col = col_map[chemical]

    conn = get_connection()
    conditions = [f"{col} IS NOT NULL AND {col} != ''"]
    params = []

    if site:
        conditions.append("w3w_site_code = ?")
        params.append(site)
    if date_from:
        conditions.append("sample_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("sample_date <= ?")
        params.append(date_to)

    where = "WHERE " + " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT sample_date, sample_time, w3w_site_code, {col} as value, w3w, title FROM entries {where} ORDER BY sample_date ASC, sample_time ASC",
        params,
    ).fetchall()
    conn.close()

    readings = []
    for r in rows:
        try:
            val = float(r["value"])
        except (ValueError, TypeError):
            continue
        readings.append({
            "date": r["sample_date"],
            "time": r["sample_time"],
            "site": r["w3w_site_code"],
            "value": val,
            "w3w": r["w3w"],
            "title": r["title"],
        })

    return {"chemical": chemical, "unit": get_unit(chemical), "readings": readings}


@app.get("/api/rounds")
def get_rounds(
    chemical: str = Query(None, pattern="^(phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth)$"),
    site: str = Query(None),
):
    conn = get_connection()
    dates = conn.execute(
        "SELECT sample_date, COUNT(*) as c FROM entries WHERE sample_date IS NOT NULL GROUP BY sample_date ORDER BY sample_date"
    ).fetchall()

    # Detect rounds: consecutive date runs >10 total entries within 4-day window
    rounds = []
    current = []
    for r in dates:
        d = r["sample_date"]
        if not current:
            current = [(d, r["c"])]
        else:
            last = current[-1][0]
            gap = (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days
            if gap <= 4:
                current.append((d, r["c"]))
            else:
                if sum(c for _, c in current) > 10:
                    rounds.append(current)
                current = [(d, r["c"])]
    if current and sum(c for _, c in current) > 10:
        rounds.append(current)

    result = []
    col_map = {
        "phosphate": "phosphate_level",
        "ammonia": "ammonia_level",
        "nitrate": "nitrate_level",
        "turbidity": "turbidity",
        "dissolved_oxygen": "dissolved_oxygen",
        "conductivity": "conductivity",
        "water_depth": "water_depth_cm",
    }

    for i, rdates in enumerate(rounds):
        start = rdates[0][0]
        end = rdates[-1][0]
        total = sum(c for _, c in rdates)

        round_info = {
            "round": i + 1,
            "start": start,
            "end": end,
            "total_entries": total,
            "date_count": len(rdates),
        }

        if chemical:
            col = col_map[chemical]
            readings = conn.execute(
                f"SELECT CAST({col} AS REAL) as val FROM entries WHERE sample_date >= ? AND sample_date <= ? AND {col} IS NOT NULL AND {col} != '' AND {col} != 'None'",
                (start, end),
            ).fetchall()
            vals = [r["val"] for r in readings if r["val"] is not None]
            if vals:
                round_info["mean"] = round(sum(vals) / len(vals), 4)
                round_info["min"] = round(min(vals), 4)
                round_info["max"] = round(max(vals), 4)
                round_info["count"] = len(vals)
            else:
                round_info["mean"] = None
                round_info["min"] = None
                round_info["max"] = None
                round_info["count"] = 0

            if site:
                site_readings = conn.execute(
                    f"SELECT sample_date, CAST({col} AS REAL) as val FROM entries WHERE sample_date >= ? AND sample_date <= ? AND w3w_site_code = ? AND {col} IS NOT NULL AND {col} != '' AND {col} != 'None' ORDER BY sample_date",
                    (start, end, site),
                ).fetchall()
                site_pts = [{"date": r["sample_date"], "value": round(r["val"], 4)} for r in site_readings if r["val"] is not None]
                round_info["site_readings"] = site_pts if site_pts else None
            else:
                round_info["site_readings"] = None

        result.append(round_info)

    conn.close()
    return {
        "rounds": result,
        "chemical": chemical,
        "reference_levels": REFERENCE_LEVELS.get(chemical) if chemical else None,
        "unit": get_unit(chemical) if chemical else None,
    }

@app.get("/api/sync")
def trigger_sync():
    result = run_sync()
    return result


@app.get("/api/sync/log")
def sync_log(limit: int = Query(10, ge=1, le=100)):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sync_log ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/location-series")
def get_location_series(
    chemical: str = Query(..., pattern="^(phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth)$"),
    site: str = Query(None),
    round_filter: int = Query(None, ge=1),
):
    col_map = {
        "phosphate": "phosphate_level",
        "ammonia": "ammonia_level",
        "nitrate": "nitrate_level",
        "turbidity": "turbidity",
        "dissolved_oxygen": "dissolved_oxygen",
        "conductivity": "conductivity",
        "water_depth": "water_depth_cm",
    }
    col = col_map[chemical]
    conn = get_connection()

    dates = conn.execute(
        "SELECT sample_date, COUNT(*) as c FROM entries WHERE sample_date IS NOT NULL GROUP BY sample_date ORDER BY sample_date"
    ).fetchall()

    rounds = []
    current = []
    for r in dates:
        d = r["sample_date"]
        if not current:
            current = [(d, r["c"])]
        else:
            last = current[-1][0]
            gap = (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days
            if gap <= 4:
                current.append((d, r["c"]))
            else:
                if sum(c for _, c in current) > 10:
                    rounds.append(current)
                current = [(d, r["c"])]
    if current and sum(c for _, c in current) > 10:
        rounds.append(current)

    result = []
    for i, rdates in enumerate(rounds):
        if round_filter and i + 1 != round_filter:
            continue
        start = rdates[0][0]
        end = rdates[-1][0]

        site_rows = conn.execute(f"""
            SELECT w3w_site_code,
                   CAST(AVG(CAST({col} AS REAL)) AS REAL) as mean,
                   COUNT(*) as cnt
            FROM entries
            WHERE sample_date >= ? AND sample_date <= ?
              AND {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
              AND w3w_site_code IS NOT NULL
            GROUP BY w3w_site_code
            ORDER BY w3w_site_code
        """, (start, end)).fetchall()

        sites_data = []
        for sr in site_rows:
            code = sr["w3w_site_code"]
            sites_data.append({
                "code": code,
                "name": SITE_CODE_MAP.get(code, code),
                "mean": round(sr["mean"], 4) if sr["mean"] is not None else None,
                "count": sr["cnt"],
                "_order": SITE_DOWNSTREAM_ORDER.get(code, 999),
            })
        sites_data.sort(key=lambda s: s["_order"])

        result.append({
            "round": i + 1,
            "start": start,
            "end": end,
            "sites": [{k: v for k, v in s.items() if k != "_order"} for s in sites_data],
        })

    conn.close()
    return {
        "rounds": result,
        "chemical": chemical,
        "unit": get_unit(chemical),
        "reference_levels": REFERENCE_LEVELS.get(chemical),
    }


@app.get("/api/site-averages")
def get_site_averages(
    chemical: str = Query(..., pattern="^(phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth)$"),
):
    col_map = {
        "phosphate": "phosphate_level",
        "ammonia": "ammonia_level",
        "nitrate": "nitrate_level",
        "turbidity": "turbidity",
        "dissolved_oxygen": "dissolved_oxygen",
        "conductivity": "conductivity",
        "water_depth": "water_depth_cm",
    }
    col = col_map[chemical]
    conn = get_connection()

    rows = conn.execute(f"""
        SELECT w3w_site_code,
               CAST(AVG(CAST({col} AS REAL)) AS REAL) as mean_val,
               CAST(MAX(CAST({col} AS REAL)) AS REAL) as max_val,
               CAST(MIN(CAST({col} AS REAL)) AS REAL) as min_val,
               COUNT(*) as cnt
        FROM entries
        WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
          AND w3w_site_code IS NOT NULL
        GROUP BY w3w_site_code
        ORDER BY w3w_site_code
    """).fetchall()
    conn.close()

    all_vals = [r["mean_val"] for r in rows if r["mean_val"] is not None]
    global_max = max(all_vals) if all_vals else 1
    global_min = min(all_vals) if all_vals else 0
    range_val = global_max - global_min or 1

    sites = []
    for r in rows:
        code = r["w3w_site_code"]
        mean_val = round(r["mean_val"], 4) if r["mean_val"] is not None else None
        sites.append({
            "code": code,
            "name": SITE_CODE_MAP.get(code, code),
            "mean": mean_val,
            "min": round(r["min_val"], 4) if r["min_val"] is not None else None,
            "max": round(r["max_val"], 4) if r["max_val"] is not None else None,
            "count": r["cnt"],
            "_order": SITE_DOWNSTREAM_ORDER.get(code, 999),
        })
    sites.sort(key=lambda s: s["_order"])

    return {
        "sites": [{k: v for k, v in s.items() if k != "_order"} for s in sites],
        "chemical": chemical,
        "unit": get_unit(chemical),
        "reference_levels": REFERENCE_LEVELS.get(chemical),
    }


@app.get("/api/site-summary")
def get_site_summary(site: str = Query(..., min_length=1)):
    col_map = {
        "phosphate": "phosphate_level",
        "ammonia": "ammonia_level",
        "nitrate": "nitrate_level",
    }
    conn = get_connection()
    results = {}
    for name, col in col_map.items():
        row = conn.execute(f"""
            SELECT COUNT(*) as cnt,
                   CAST(AVG(CAST({col} AS REAL)) AS REAL) as mean_val,
                   CAST(MAX(CAST({col} AS REAL)) AS REAL) as max_val
            FROM entries
            WHERE w3w_site_code = ?
              AND {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
        """, (site,)).fetchone()
        if row and row["cnt"] > 0:
            results[name] = {
                "mean": round(row["mean_val"], 4),
                "max": round(row["max_val"], 4),
                "count": row["cnt"],
                "unit": get_unit(name),
            }
    conn.close()
    return {"site": site, "name": SITE_CODE_MAP.get(site, site), "chemicals": results}


REFERENCE_LEVELS = {
    "phosphate": {"Good": 0.069, "Moderate": 0.173, "Poor": 1.003},
    "ammonia": {"Good": 0.6, "Moderate": 1.1, "Poor": 2.5},
}

def get_unit(chemical):
    units = {
        "phosphate": "mg/L",
        "ammonia": "mg/L",
        "nitrate": "mg/L",
        "turbidity": "NTU",
        "dissolved_oxygen": "mg/L",
        "conductivity": "µS/cm",
        "water_depth": "cm",
    }
    return units.get(chemical, "")
