"""HTTP surface for the v2 reporting engine.

Generation is asynchronous because a report takes 30-90 seconds: the
client POSTs, gets a job id, and polls. Jobs are persisted in
`v2_report_jobs` rather than held in memory, so a backend restart mid-run
leaves a visible failed job instead of a request that hangs forever --
which is what v1's in-memory queue did.

`POST /reports/generate` costs money on every call, so it is gated behind
ADMIN_API_KEY whenever that variable is set. Read endpoints are open, as
in v1.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from v2 import engine
from v2.db import get_connection

logger = logging.getLogger(__name__)

REPORT_TYPES = ("location", "round", "catchment", "comparison", "trend", "data_quality")
AUDIENCES = ("volunteer", "public", "technical")

router = APIRouter(prefix="/api/v2", tags=["v2-reports"])

MAX_QUEUED = 3
_queue_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def require_admin(authorization: str | None) -> None:
    """Gate generation when an admin key is configured.

    Deliberately open when ADMIN_API_KEY is unset so local development
    works with no setup. In production the key is set, so anonymous
    traffic cannot spend the project's API credit.
    """
    admin_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_key:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "This endpoint needs an Authorization: Bearer <key> header.")
    if authorization.removeprefix("Bearer ").strip() != admin_key:
        raise HTTPException(403, "That admin key was not recognised.")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_row(row) -> dict:
    return {
        "job_id": row["id"],
        "report_type": row["report_type"],
        "report_key": row["report_key"],
        "audience": row["audience"],
        "state": row["state"],
        "progress": row["progress"],
        "message": row["message"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "report_id": row["result_report_id"],
    }


def _set_progress(job_id: str, pct: int, message: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE v2_report_jobs SET progress = ?, message = ? WHERE id = ?",
            (pct, message, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run_job(job_id: str, report_type: str, report_key: str, audience: str,
             period_start: str | None, period_end: str | None) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE v2_report_jobs SET state = 'running', started_at = ?, message = ? WHERE id = ?",
            (_now(), "Starting", job_id),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        report = engine.generate_report(
            report_type, report_key, audience,
            period_start=period_start, period_end=period_end,
            trigger="manual",
            progress_callback=lambda pct, msg: _set_progress(job_id, pct, msg),
        )
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE v2_report_jobs SET state = 'done', progress = 100, message = 'Finished', "
                "finished_at = ?, result_report_id = ? WHERE id = ?",
                (_now(), report["id"], job_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - the failure must reach the client
        logger.exception("report job %s failed", job_id)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE v2_report_jobs SET state = 'failed', message = 'Failed', "
                "finished_at = ?, error = ? WHERE id = ?",
                (_now(), str(exc), job_id),
            )
            conn.commit()
        finally:
            conn.close()


class GenerateRequest(BaseModel):
    type: str
    key: str
    audience: str = "volunteer"
    period_start: str | None = None
    period_end: str | None = None


@router.post("/reports/generate")
def trigger_report(body: GenerateRequest, authorization: str | None = Header(default=None)):
    require_admin(authorization)

    if body.type not in REPORT_TYPES:
        raise HTTPException(400, f"Unknown report type {body.type!r}. Expected one of {sorted(REPORT_TYPES)}.")
    if body.audience not in AUDIENCES:
        raise HTTPException(400, f"Unknown audience {body.audience!r}. Expected one of {sorted(AUDIENCES)}.")

    with _queue_lock:
        conn = get_connection()
        try:
            active = conn.execute(
                "SELECT COUNT(*) FROM v2_report_jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]
            if active >= MAX_QUEUED:
                raise HTTPException(
                    429,
                    f"{active} reports are already being written. Wait for one to finish "
                    "before asking for another.",
                )
            duplicate = conn.execute(
                "SELECT id FROM v2_report_jobs WHERE report_type = ? AND report_key = ? "
                "AND audience = ? AND state IN ('queued','running')",
                (body.type, body.key, body.audience),
            ).fetchone()
            if duplicate:
                raise HTTPException(409, "That report is already being written.")

            job_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO v2_report_jobs (id, report_type, report_key, audience, state, "
                "progress, message, created_at) VALUES (?,?,?,?, 'queued', 0, 'Queued', ?)",
                (job_id, body.type, body.key, body.audience, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    threading.Thread(
        target=_run_job,
        args=(job_id, body.type, body.key, body.audience, body.period_start, body.period_end),
        daemon=True,
    ).start()
    return {"job_id": job_id, "state": "queued"}


@router.get("/reports/jobs")
def list_jobs(limit: int = Query(20, ge=1, le=100)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM v2_report_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return {"jobs": [_job_row(r) for r in rows]}


@router.get("/reports/jobs/{job_id}")
def get_job(job_id: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM v2_report_jobs WHERE id = ?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "No such job.")
    return _job_row(row)


# ---------------------------------------------------------------------------
# Reading reports
# ---------------------------------------------------------------------------


@router.get("/reports")
def get_reports(
    type: str | None = Query(default=None),
    key: str | None = Query(default=None),
    audience: str | None = Query(default=None),
):
    return {"reports": engine.list_reports(type, key, audience)}


@router.get("/reports/types")
def get_report_types():
    """What can be asked for, in the words the interface uses."""
    return {
        "types": [
            {"key": "location", "label": "Tell me about a place",
             "help": "One sampling point, from its first reading to its latest."},
            {"key": "round", "label": "Tell me about a sampling round",
             "help": "One round of sampling, across the whole river."},
            {"key": "catchment", "label": "Tell me about the whole river",
             "help": "The state of the Coln over a period you choose."},
            {"key": "comparison", "label": "Compare two periods",
             "help": "What changed between one round or period and another."},
            {"key": "trend", "label": "How has one measure changed?",
             "help": "The long-term direction for a single measurement."},
            {"key": "data_quality", "label": "How reliable is the data?",
             "help": "Coverage, gaps and readings needing a second look."},
        ],
        "audiences": [
            {"key": "volunteer", "label": "Volunteers and neighbours",
             "help": "Plain English, no jargon."},
            {"key": "public", "label": "Parish council or press",
             "help": "Slightly more formal, still plain."},
            {"key": "technical", "label": "Technical",
             "help": "Water Framework Directive terms and full figures."},
        ],
    }


@router.get("/reports/versions")
def get_versions(type: str = Query(...), key: str = Query(...), audience: str = Query("volunteer")):
    return {"versions": engine.list_versions(type, key, audience)}


@router.get("/reports/{report_id}")
def get_single_report(report_id: int):
    report = engine.get_report(report_id)
    if report is None:
        raise HTTPException(404, "No such report.")
    return report


@router.get("/reports/{report_id}/download")
def download_report(report_id: int, format: str = Query("md", pattern="^(md|html)$")):
    report = engine.get_report(report_id)
    if report is None:
        raise HTTPException(404, "No such report.")

    stem = f"coln-{report['report_type']}-{report['report_key']}-v{report['version']}"
    stem = stem.replace("/", "-").replace(" ", "-")

    if format == "md":
        return PlainTextResponse(
            report["markdown"] or "",
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )

    from v2.render import to_printable_html

    html = to_printable_html(json.loads(report["report_json"])
                             if isinstance(report["report_json"], str)
                             else report["report_json"], report)
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.html"'},
    )
