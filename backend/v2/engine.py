"""Report generation orchestration: facts pack -> LLM -> schema validation
(inside `llm.py`) -> content verification -> one corrective retry ->
store, plus the read helpers `reports_api.py` needs to serve stored
reports back out.

Two retries already happened, if needed, before this module sees a
result:

1. `llm.generate_json` retries transient network/API errors internally.
2. `llm.generate_json` retries once, internally, if the JSON doesn't
   match `schemas.REPORT_SCHEMA` — Mistral doesn't enforce that
   server-side (V2_SPEC_ADDENDUM.md, Change 1).

This module adds the *third*, content-level retry the build spec asks
for: if `verify.verify_report` finds unmatched numbers, invalid evidence
ids, or banned content, the specific failures are appended to the user
prompt and generation is retried exactly once more. Whatever comes back
from that retry is stored — verified or not — with its own verification
record. A report that still fails verification after the retry is never
discarded; the "unverified" badge is the honest outcome, not an error.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable

from v2 import facts as facts_module
from v2 import prompts
from v2 import render
from v2 import schemas
from v2 import verify
from v2.db import get_connection
from v2.llm import LLMError, generate_json

logger = logging.getLogger("v2.engine")

ProgressCallback = Callable[[int, str], None]


class ReportGenerationError(Exception):
    """A report could not be produced at all — the facts pack couldn't be
    built (unknown key), or the LLM never returned valid JSON even after
    its own schema-repair attempt. Distinct from a *verification* failure,
    which is not an error: that report is still stored, with an honest
    'unverified' badge — see the module docstring."""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_report(
    report_type: str,
    report_key: str,
    audience: str,
    period_start: str | None = None,
    period_end: str | None = None,
    trigger: str = "manual",
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Run the full pipeline for one report and store the result.

    Returns the stored report as a dict: `{id, report_type, report_key,
    audience, version, status, provider, model, generated_at,
    verification, report_json, markdown}`.

    Raises `ReportGenerationError` only when nothing could be produced at
    all — see the module docstring for why a verification failure isn't
    one of those cases.
    """
    def progress(pct: int, msg: str) -> None:
        logger.info("generate_report %s/%s/%s: %d%% %s", report_type, report_key, audience, pct, msg)
        if progress_callback:
            progress_callback(pct, msg)

    progress(5, "Building facts pack")
    try:
        pack = facts_module.build_facts_pack(report_type, report_key, audience, period_start, period_end)
    except ValueError as e:
        raise ReportGenerationError(f"could not build facts pack: {e}") from e

    progress(20, "Facts pack ready")
    system_prompt = prompts.build_system_prompt(report_type, audience)
    user_prompt = prompts.build_user_prompt(report_type, audience, report_key, pack)

    progress(30, "Generating report")
    try:
        report_json = generate_json(system_prompt, user_prompt, schemas.REPORT_SCHEMA)
    except LLMError as e:
        raise ReportGenerationError(f"LLM generation failed: {e}") from e

    progress(60, "Checking figures against the data")
    verification = verify.verify_report(report_json, pack)

    if verification["status"] != "verified":
        progress(70, f"Retrying with {_problem_count(verification)} correction(s)")
        report_json, verification = _retry_with_corrections(
            system_prompt, user_prompt, pack, report_json, verification
        )

    progress(85, "Rendering")
    generated_at = datetime.now(timezone.utc).isoformat()
    version = _next_version(report_type, report_key, audience)
    provider = _resolve_provider()
    model = _model_name(provider)

    meta = {
        "report_type": report_type,
        "report_key": str(report_key),
        "audience": audience,
        "generated_at": generated_at,
        "provider": provider,
        "model": model,
        "version": version,
        "period_start": period_start,
        "period_end": period_end,
        "trigger": trigger,
        "verification": verification,
    }
    markdown = render.to_markdown(report_json, meta)

    progress(95, "Saving to database")
    row_id = _store_report(
        report_type, report_key, audience, version, "ok", provider, model,
        period_start, period_end, generated_at, report_json, pack, verification, markdown, trigger,
    )

    progress(100, "Complete")
    return {
        "id": row_id,
        "report_type": report_type,
        "report_key": str(report_key),
        "audience": audience,
        "version": version,
        "status": "ok",
        "provider": provider,
        "model": model,
        "generated_at": generated_at,
        "verification": verification,
        "report_json": report_json,
        "markdown": markdown,
    }


def _problem_count(verification: dict) -> int:
    return (
        len(verification.get("unmatched_numbers", []))
        + len(verification.get("invalid_evidence_ids", []))
        + len(verification.get("banned_terms", []))
    )


def _retry_with_corrections(system_prompt: str, user_prompt: str, pack: dict, first_report: dict, first_verification: dict) -> tuple[dict, dict]:
    """The one corrective retry the build spec asks for. Whatever this
    returns is what gets stored — the first attempt is only kept if the
    retry itself couldn't be run at all (an LLM error, not a verification
    failure)."""
    # report_type/audience/report_key/facts_pack aren't separately available
    # here (only the already-built `user_prompt` string is), but the retry
    # only needs the correction appended to that same content — which is
    # exactly what `build_user_prompt`'s own `correction` parameter does —
    # so append directly rather than rebuilding the prompt from parts.
    correction = verify.format_verification_failures(first_verification)
    retry_prompt = f"{user_prompt}\n\n{correction}"
    try:
        retry_report = generate_json(system_prompt, retry_prompt, schemas.REPORT_SCHEMA)
    except LLMError as e:
        logger.warning("corrective retry failed to generate at all, keeping first attempt: %s", e)
        return first_report, first_verification

    retry_verification = verify.verify_report(retry_report, pack)
    if retry_verification["status"] == "verified":
        return retry_report, {**retry_verification, "status": "repaired"}
    # The retry ran but still isn't clean — store it anyway (it is the
    # best available attempt) with its own honest verification record.
    return retry_report, retry_verification


def _resolve_provider() -> str:
    return os.environ.get("REPORT_LLM_PROVIDER", "mistral").strip().lower()


def _model_name(provider: str) -> str:
    if provider == "mistral":
        return os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
    return provider


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _next_version(report_type: str, report_key: str, audience: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM v2_reports WHERE report_type=? AND report_key=? AND audience=?",
            (report_type, str(report_key), audience),
        ).fetchone()
    finally:
        conn.close()
    return (row["v"] or 0) + 1


def _store_report(
    report_type, report_key, audience, version, status, provider, model,
    period_start, period_end, generated_at, report_json, facts_pack, verification, markdown, trigger,
) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO v2_reports (
                report_type, report_key, audience, version, status, model, provider,
                period_start, period_end, generated_at, report_json, facts_json,
                verification_json, markdown, trigger
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_type, str(report_key), audience, version, status, model, provider,
                period_start, period_end, generated_at,
                json.dumps(report_json, ensure_ascii=False),
                json.dumps(facts_pack, ensure_ascii=False),
                json.dumps(verification, ensure_ascii=False),
                markdown, trigger,
            ),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()
    return row_id


# ---------------------------------------------------------------------------
# Reads — the shapes `reports_api.py`'s GET endpoints serve back out
# ---------------------------------------------------------------------------

def _row_to_report(row) -> dict:
    d = dict(row)
    d["report_json"] = json.loads(d["report_json"])
    d["facts_json"] = json.loads(d["facts_json"])
    d["verification_json"] = json.loads(d["verification_json"])
    return d


def get_report(report_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM v2_reports WHERE id = ?", (report_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_report(row) if row else None


def list_reports(report_type: str | None = None, report_key: str | None = None, audience: str | None = None) -> list[dict]:
    """The latest version of every (report_type, report_key, audience)
    group, optionally filtered — `GET /api/v2/reports`."""
    conn = get_connection()
    try:
        conditions = []
        params: list = []
        if report_type:
            conditions.append("report_type = ?")
            params.append(report_type)
        if report_key:
            conditions.append("report_key = ?")
            params.append(str(report_key))
        if audience:
            conditions.append("audience = ?")
            params.append(audience)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"""
            SELECT r.* FROM v2_reports r
            INNER JOIN (
                SELECT report_type, report_key, audience, MAX(version) AS max_version
                FROM v2_reports {where}
                GROUP BY report_type, report_key, audience
            ) latest
            ON r.report_type = latest.report_type AND r.report_key = latest.report_key
               AND r.audience = latest.audience AND r.version = latest.max_version
            ORDER BY r.generated_at DESC
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_report(r) for r in rows]


def list_versions(report_type: str, report_key: str, audience: str) -> list[dict]:
    """Every stored version of one (report_type, report_key, audience)
    group, newest first — `GET /api/v2/reports/versions`."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, version, status, generated_at, provider, model, trigger, verification_json "
            "FROM v2_reports WHERE report_type=? AND report_key=? AND audience=? ORDER BY version DESC",
            (report_type, str(report_key), audience),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["verification_json"] = json.loads(d["verification_json"])
        out.append(d)
    return out
