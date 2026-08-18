#!/usr/bin/env python3
"""Decide which reports should exist, and write the ones that don't.

This is what makes reporting automatic rather than a button. v1 only ever
generated a report when somebody clicked; a round could finish and nobody
would notice for weeks.

Run it daily from a timer:

    python -m v2.scheduler            # generate what is due
    python -m v2.scheduler --dry-run  # say what would be generated

Idempotent by construction: every rule asks "does this report already
exist for this state of the data?" and does nothing if it does. Running
it twice in a row generates nothing the second time.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from v2.db import get_connection
from v2.engine import generate_report
from v2.insights import detect_rounds

logger = logging.getLogger(__name__)

# A round is treated as finished once no new sample has arrived for this
# long. Volunteers submit over several days, so reporting immediately
# would describe a half-collected round.
ROUND_SETTLE_DAYS = 5

# How many new samples a location needs before its report is stale enough
# to be worth the cost of rewriting.
LOCATION_REFRESH_SAMPLES = 3

DEFAULT_AUDIENCE = "volunteer"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _existing(report_type: str, report_key: str, audience: str = DEFAULT_AUDIENCE) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, generated_at FROM v2_reports WHERE report_type = ? AND report_key = ? "
            "AND audience = ? AND status = 'ok' ORDER BY version DESC LIMIT 1",
            (report_type, report_key, audience),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def due_round_reports() -> list[dict]:
    """A round that has settled and has never been written up."""
    due = []
    cutoff = _today() - timedelta(days=ROUND_SETTLE_DAYS)
    for r in detect_rounds():
        try:
            end = datetime.strptime(r["end"], "%Y-%m-%d").date()
        except (KeyError, TypeError, ValueError):
            continue
        if end > cutoff:
            continue  # still collecting
        key = str(r["round"])
        if _existing("round", key) is None:
            due.append({"type": "round", "key": key,
                        "why": f"round {key} finished on {r['end']} and has no report"})
    return due


def due_catchment_reports() -> list[dict]:
    """A digest for last month, once last month is over."""
    today = _today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    key = last_month_end.strftime("%Y-%m")
    if _existing("catchment", key) is not None:
        return []
    return [{
        "type": "catchment", "key": key,
        "period_start": last_month_end.replace(day=1).isoformat(),
        "period_end": last_month_end.isoformat(),
        "why": f"no monthly digest for {key}",
    }]


def due_location_reports() -> list[dict]:
    """A location whose report has fallen behind its readings."""
    due = []
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT w3w, COUNT(*) AS n, MAX(sample_date) AS latest FROM observations "
            "WHERE excluded = 0 AND w3w IS NOT NULL GROUP BY w3w"
        ).fetchall()
        for row in rows:
            existing = _existing("location", row["w3w"])
            if existing is None:
                due.append({"type": "location", "key": row["w3w"],
                            "why": "no report for this location yet"})
                continue
            newer = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE w3w = ? AND excluded = 0 "
                "AND sample_date > date(?)",
                (row["w3w"], existing["generated_at"][:10]),
            ).fetchone()[0]
            if newer >= LOCATION_REFRESH_SAMPLES:
                due.append({"type": "location", "key": row["w3w"],
                            "why": f"{newer} new samples since the last report"})
    finally:
        conn.close()
    return due


def collect_due() -> list[dict]:
    return due_round_reports() + due_catchment_reports() + due_location_reports()


def run_due_jobs(dry_run: bool = False, limit: int | None = None) -> dict:
    """Generate everything that is due. Failures are logged and skipped so
    one bad report cannot stop the rest of the run."""
    due = collect_due()
    if limit is not None:
        due = due[:limit]

    result = {"due": len(due), "generated": 0, "failed": 0, "items": []}
    for item in due:
        line = f"{item['type']}/{item['key']} — {item['why']}"
        if dry_run:
            logger.info("would generate %s", line)
            result["items"].append({**item, "state": "would-generate"})
            continue
        try:
            report = generate_report(
                item["type"], item["key"], DEFAULT_AUDIENCE,
                period_start=item.get("period_start"), period_end=item.get("period_end"),
                trigger="scheduled",
            )
            result["generated"] += 1
            result["items"].append({**item, "state": "generated", "report_id": report["id"],
                                    "verification": report["verification"].get("status")})
            logger.info("generated %s", line)
        except Exception as exc:  # noqa: BLE001 — one failure must not stop the run
            result["failed"] += 1
            result["items"].append({**item, "state": "failed", "error": str(exc)})
            logger.exception("failed to generate %s", line)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list what is due without generating")
    ap.add_argument("--limit", type=int, help="generate at most this many (useful for a first run)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )

    result = run_due_jobs(dry_run=args.dry_run, limit=args.limit)
    verb = "would generate" if args.dry_run else "generated"
    print(f"{result['due']} report(s) due, {verb} {result['generated']}, {result['failed']} failed")
    for item in result["items"]:
        marker = {"generated": "+", "failed": "!", "would-generate": "-"}.get(item["state"], "?")
        print(f"  {marker} {item['type']}/{item['key']}: {item['why']}")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
