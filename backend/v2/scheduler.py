#!/usr/bin/env python3
"""Write the round report for any round of testing that has finished.

This is what makes reporting automatic rather than a button. v1 only ever
generated a report when somebody clicked; a round could finish and nobody
would notice for weeks.

One round of testing produces one report, covering the state of the whole
river during that round: every location sampled, how each measure sat
against its bands, how it compares with the previous round, and whether
things change going downstream.

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


def collect_due() -> list[dict]:
    """One report per round of testing, covering the whole river.

    Deliberately the only automatic rule. Earlier versions also wrote a
    monthly digest and refreshed a report per location, which produced 63
    reports off one dataset -- most of them nobody asked for, each costing
    an API call. Sampling happens in rounds, so a round is the natural
    unit: one report per round, summarising every location sampled in it.
    Location, trend and comparison reports remain available on demand.
    """
    return due_round_reports()


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
