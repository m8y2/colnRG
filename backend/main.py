import json
import os
import secrets
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from database import get_connection, init_db, get_last_sync
from sync import run_sync, SITE_CODE_MAP
from coords import SITE_COORDS, SITE_DOWNSTREAM_ORDER
from llm_cleanup.report_generator import generate_site_report, generate_round_report, call_do

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


@app.get("/api/photos")
def get_photos():
    conn = get_connection()
    rows = conn.execute(
        "SELECT ec5_uuid, sample_date, w3w_site_code, w3w, photo_url, photo_desc, photo_2_url "
        "FROM entries WHERE (photo_url IS NOT NULL AND photo_url != '') "
        "OR (photo_2_url IS NOT NULL AND photo_2_url != '') "
        "ORDER BY sample_date DESC"
    ).fetchall()
    conn.close()
    return {"photos": [dict(r) for r in rows]}


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


# ── Report endpoints ──────────────────────────────────────────────

_report_queue = []  # list of task dicts: {id, type, identifier, ..., fn}
_report_queue_lock = threading.Lock()
_report_droplet = {"id": None, "ip": None}
_report_droplet_ready = False
_report_worker_busy = False
_task_progress = {}  # {task_id: {progress, message, type, identifier}}


def _set_progress(task_id, pct, msg):
    with _report_queue_lock:
        if task_id in _task_progress:
            _task_progress[task_id]["progress"] = pct
            _task_progress[task_id]["message"] = msg


def _destroy_droplet():
    global _report_droplet_ready
    did = _report_droplet.get("id")
    if did:
        print(f"  Destroying droplet {did}...")
        try:
            call_do("DELETE", f"/droplets/{did}")
        except Exception as e:
            print(f"  WARNING: failed to destroy droplet {did}: {e}")
    _report_droplet["id"] = None
    _report_droplet["ip"] = None
    _report_droplet_ready = False


def _worker_loop():
    global _report_worker_busy, _report_droplet_ready
    from llm_cleanup.report_generator import spin_up_droplet, wait_for_ssh, ensure_ollama

    while True:
        with _report_queue_lock:
            if not _report_queue:
                _report_worker_busy = False
                break
            task = _report_queue[0]

        # Spin up shared droplet on first task
        if not _report_droplet["id"]:
            try:
                _set_progress(task["id"], 10, "Spinning up droplet")
                did, ip = spin_up_droplet()
                _report_droplet["id"] = did
                _report_droplet["ip"] = ip
                _set_progress(task["id"], 20, "Droplet ready")
            except Exception as e:
                _set_progress(task["id"], -1, f"Droplet failed: {e}")
                with _report_queue_lock:
                    _report_queue.pop(0)
                    _task_progress.pop(task["id"], None)
                import traceback
                traceback.print_exc()
                continue

        ip = _report_droplet["ip"]

        # Ensure SSH + Ollama ready (once per droplet lifetime)
        if not _report_droplet_ready:
            try:
                _set_progress(task["id"], 25, "Waiting for SSH")
                if not wait_for_ssh(ip):
                    raise RuntimeError("SSH timeout")
                _set_progress(task["id"], 35, "Starting Ollama")
                if not ensure_ollama(ip):
                    raise RuntimeError("Ollama not ready")
                _report_droplet_ready = True
            except Exception as e:
                _set_progress(task["id"], -1, f"Setup failed: {e}")
                _destroy_droplet()
                with _report_queue_lock:
                    _report_queue.pop(0)
                    _task_progress.pop(task["id"], None)
                import traceback
                traceback.print_exc()
                continue

        # Run the task
        try:
            task_fn = task["fn"]
            task_fn(ip, task["id"])
            with _report_queue_lock:
                if task["id"] in _task_progress:
                    _task_progress[task["id"]]["progress"] = 100
                    _task_progress[task["id"]]["message"] = "Complete"
                    _task_progress.pop(task["id"], None)
                _report_queue.pop(0)
        except Exception as e:
            _set_progress(task["id"], -1, str(e))
            with _report_queue_lock:
                _report_queue.pop(0)
                _task_progress.pop(task["id"], None)
            import traceback
            traceback.print_exc()

    # Queue empty — keep droplet alive for 30s to handle new requests
    _report_worker_busy = False
    if _report_droplet["id"]:
        print(f"  Queue empty, keeping droplet alive for 30s...")
        for _ in range(6):
            time.sleep(5)
            with _report_queue_lock:
                if _report_queue:
                    break
        else:
            _destroy_droplet()
            print("  Droplet destroyed after 30s idle")


def _enqueue_task(task_id, task_type, identifier, task_fn):
    global _report_worker_busy
    with _report_queue_lock:
        _report_queue.append({
            "id": task_id, "type": task_type, "identifier": identifier, "fn": task_fn,
        })
        _task_progress[task_id] = {"progress": 0, "message": "Queued", "type": task_type, "identifier": identifier}
        if not _report_worker_busy:
            _report_worker_busy = True
            thread = threading.Thread(target=_worker_loop, daemon=True)
            thread.start()


@app.get("/api/reports/status")
def get_report_status():
    with _report_queue_lock:
        return {
            "running": [
                {**v, "id": k}
                for k, v in _task_progress.items()
            ] + ([
                {"id": "droplet", "progress": 100, "message": "Droplet active, queue empty",
                 "type": "infra", "identifier": "droplet"}
            ] if _report_droplet["id"] and not _report_queue else []),
            "queue_size": len(_report_queue),
        }


@app.get("/api/reports/site")
def get_site_report(site: str = Query(...), version: int = Query(None)):
    conn = get_connection()
    if version:
        row = conn.execute(
            "SELECT * FROM site_reports WHERE site_code = ? AND version = ? ORDER BY generated_at DESC LIMIT 1",
            (site, version)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM site_reports WHERE site_code = ? ORDER BY version DESC LIMIT 1",
            (site,)
        ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"No report for site {site}")
    return dict(row)


@app.get("/api/reports/site/versions")
def list_site_report_versions(site: str = Query(...)):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, version, generated_at FROM site_reports WHERE site_code = ? ORDER BY version DESC",
        (site,)
    ).fetchall()
    conn.close()
    return {"versions": [dict(r) for r in rows]}


@app.get("/api/reports/site/all")
def list_all_site_reports():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, site_code, version, generated_at, substr(report_text, 1, 200) as preview "
        "FROM site_reports ORDER BY generated_at DESC"
    ).fetchall()
    conn.close()
    return {"reports": [dict(r) for r in rows]}


@app.post("/api/reports/site/generate")
def trigger_site_report(site: str = Query(...)):
    from llm_cleanup.report_generator import generate_site_report as _gen_site
    task_id = f"site_{site}"

    with _report_queue_lock:
        if any(t["id"] == task_id for t in _report_queue):
            raise HTTPException(409, "A report for this site is already queued or running")

    def task_fn(ip, tid):
        _set_progress(tid, 40, "Building data context")
        generate_site_report(site, progress_callback=lambda p, m: _set_progress(tid, 40 + int(p * 0.55), m), ip=ip)

    _enqueue_task(task_id, "site", site, task_fn)
    return {"status": "queued", "site": site, "task_id": task_id}


@app.get("/api/reports/round")
def get_round_report(round_label: str = Query(...), version: int = Query(None)):
    conn = get_connection()
    if version:
        row = conn.execute(
            "SELECT * FROM round_reports WHERE round_label = ? AND version = ? ORDER BY generated_at DESC LIMIT 1",
            (round_label, version)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM round_reports WHERE round_label = ? ORDER BY version DESC LIMIT 1",
            (round_label,)
        ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"No report for round {round_label}")
    return dict(row)


@app.get("/api/reports/round/versions")
def list_round_report_versions(round_label: str = Query(...)):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, version, generated_at FROM round_reports WHERE round_label = ? ORDER BY version DESC",
        (round_label,)
    ).fetchall()
    conn.close()
    return {"versions": [dict(r) for r in rows]}


@app.get("/api/reports/round/all")
def list_all_round_reports():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, round_label, round_start, round_end, version, generated_at, "
        "substr(report_text, 1, 200) as preview "
        "FROM round_reports ORDER BY generated_at DESC"
    ).fetchall()
    conn.close()
    return {"reports": [dict(r) for r in rows]}


@app.post("/api/reports/round/generate")
def trigger_round_report(
    round_label: str = Query(...),
    round_start: str = Query(...),
    round_end: str = Query(...),
):
    from llm_cleanup.report_generator import generate_round_report as _gen_round
    task_id = f"round_{round_label}"

    with _report_queue_lock:
        if any(t["id"] == task_id for t in _report_queue):
            raise HTTPException(409, "A report for this round is already queued or running")

    def task_fn(ip, tid):
        _set_progress(tid, 40, "Building data context")
        generate_round_report(round_label, round_start, round_end,
                              progress_callback=lambda p, m: _set_progress(tid, 40 + int(p * 0.55), m),
                              ip=ip)

    _enqueue_task(task_id, "round", round_label, task_fn)
    return {"status": "queued", "round": round_label, "task_id": task_id}


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


# ── Private API (key-authenticated) ──────────────────────────

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

def require_api_key(api_key: str):
    if not api_key:
        raise HTTPException(401, "API key required")
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM api_keys WHERE key = ? AND enabled = 1", (api_key,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(403, "Invalid or disabled API key")


@app.post("/api/v1/admin/keys/generate")
def generate_api_key(admin_key: str = Query(...), label: str = Query("")):
    if not ADMIN_API_KEY or admin_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid admin key")
    new_key = secrets.token_urlsafe(32)
    conn = get_connection()
    conn.execute(
        "INSERT INTO api_keys (key, label, created_at) VALUES (?, ?, ?)",
        (new_key, label, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"api_key": new_key, "label": label}


@app.get("/api/v1/admin/keys/list")
def list_api_keys(admin_key: str = Query(...)):
    if not ADMIN_API_KEY or admin_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid admin key")
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, key, label, created_at, enabled FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return {"keys": [dict(r) for r in rows]}


@app.post("/api/v1/admin/keys/revoke")
def revoke_api_key(admin_key: str = Query(...), key_id: int = Query(...)):
    if not ADMIN_API_KEY or admin_key != ADMIN_API_KEY:
        raise HTTPException(403, "Invalid admin key")
    conn = get_connection()
    conn.execute("UPDATE api_keys SET enabled = 0 WHERE id = ?", (key_id,))
    conn.commit()
    conn.close()
    return {"status": "revoked"}


@app.get("/api/v1/reports/site")
def v1_get_site_report(site: str = Query(...), api_key: str = Query(...)):
    require_api_key(api_key)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM site_reports WHERE site_code = ? ORDER BY version DESC LIMIT 1",
        (site,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"No report for site {site}")
    return dict(row)


@app.get("/api/v1/reports/round")
def v1_get_round_report(round_label: str = Query(...), api_key: str = Query(...)):
    require_api_key(api_key)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM round_reports WHERE round_label = ? ORDER BY version DESC LIMIT 1",
        (round_label,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"No report for round {round_label}")
    return dict(row)


@app.post("/api/v1/reports/site/generate")
def v1_trigger_site_report(site: str = Query(...), api_key: str = Query(...)):
    require_api_key(api_key)
    task_id = f"site_{site}"
    with _report_queue_lock:
        if any(t["id"] == task_id for t in _report_queue):
            raise HTTPException(409, "A report for this site is already queued or running")
    def task_fn(ip, tid):
        _set_progress(tid, 40, "Building data context")
        generate_site_report(site, progress_callback=lambda p, m: _set_progress(tid, 40 + int(p * 0.55), m), ip=ip)
    _enqueue_task(task_id, "site", site, task_fn)
    return {"status": "queued", "site": site, "task_id": task_id}


@app.post("/api/v1/reports/round/generate")
def v1_trigger_round_report(
    round_label: str = Query(...),
    round_start: str = Query(...),
    round_end: str = Query(...),
    api_key: str = Query(...),
):
    require_api_key(api_key)
    task_id = f"round_{round_label}"
    with _report_queue_lock:
        if any(t["id"] == task_id for t in _report_queue):
            raise HTTPException(409, "A report for this round is already queued or running")
    def task_fn(ip, tid):
        _set_progress(tid, 40, "Building data context")
        generate_round_report(round_label, round_start, round_end,
                              progress_callback=lambda p, m: _set_progress(tid, 40 + int(p * 0.55), m),
                              ip=ip)
    _enqueue_task(task_id, "round", round_label, task_fn)
    return {"status": "queued", "round": round_label, "task_id": task_id}
