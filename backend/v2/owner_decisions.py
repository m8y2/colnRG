"""The project owner's decisions on the review queue, in order.

The review queue holds readings (and locations) the cleaning pipeline could
not interpret with confidence. The owner reviewed all 25 and made these
decisions on 29 August 2026. Each one is written to `review_decisions` and
applied by the next `python -m v2.ingest --refresh`, with a cleaning_log row
per application -- so this file is both the record of what was decided and
the way to re-apply it if the database is ever rebuilt from scratch.

Run it after a fresh ingest (the queue item ids are regenerated on every
rebuild, so decisions are keyed on the reading itself, not on an id):

    python -m v2.owner_decisions
    python -m v2.ingest --refresh

Decision kinds (see `review_decisions.kind` in v2/db.py):
    value        -- numeric reading applied to measurements
    not_measured -- reading marked absent (usable=0)
    category     -- ordinal category applied (value stays NULL)
    remove       -- the measurements row is deleted
    merge        -- observations for the address move to the canonical one
"""

from __future__ import annotations

import datetime as _dt

from v2.db import get_connection

# (issue, value_raw, parameter, kind, resolved_value, note)
#
# Ordered exactly as the owner reviewed them (the review queue lists items
# by issue, then id). `parameter` is None for location merges. The note
# records the owner's reasoning in their words where they gave one.
DECISIONS: list[tuple] = [
    # 1-2: the two possible-duplicate locations
    ("ambiguous_location", "suitably.dustbin.glossed", None, "merge",
     "gobblers.printers.secure", "merged: same sampling point, 6 m apart"),
    ("ambiguous_location", "yacht.pounding.found", None, "merge",
     "luring.tram.dolphins", "merged: same sampling point, 33 m apart"),

    # 3, 7, 8, 10: dissolved oxygen recorded as 0 -- the owner says those
    # were fields left as 0 when no oxygen test was actually done.
    ("implausible", "0", "dissolved_oxygen", "not_measured", None,
     "owner: 'Make not measured' -- a 0 here means no oxygen test was done"),
    ("implausible", "0", "dissolved_oxygen", "not_measured", None,
     "owner: not measured"),
    ("implausible", "0", "dissolved_oxygen", "not_measured", None,
     "owner: not measured"),
    ("implausible", "0", "dissolved_oxygen", "not_measured", None,
     "owner: not measured"),

    # 4-6: phosphate with a lost decimal point
    ("implausible", "23", "phosphate", "value", "0.23",
     "owner: 'Accept 0.23'"),
    ("implausible", "47", "phosphate", "value", "0.47",
     "owner: 'Accept 0.47'"),
    ("implausible", "35", "phosphate", "value", "0.35",
     "owner: 'Accept 0.35'"),

    # 9: nitrate 250 -> 25
    ("implausible", "250", "nitrate", "value", "25",
     "owner: 'Accept 25'"),

    # 11: two numbers in the nitrate field -- owner says it was not a
    # nitrate measurement at all.
    ("multi_value", "/1.0/0.5ppm", "nitrate", "not_measured", None,
     "owner: 'Make not measured'"),

    # 12: depth "Low. 20cm" -- keep the word, not the number.
    ("multi_value", "Low. 20cm", "water_depth", "category", "low",
     "owner: 'Use category low'"),

    # 13: "Nitrate 0.00 Nitrite 10" -- the scheme only measures nitrate,
    # so only the nitrate value is recorded.
    ("multi_value", "Nitrate 0.00 Nitrite 10", "nitrate", "value", "0",
     "owner: only nitrate is measured, so record the given nitrate value (0.00)"),

    # 14: nitrate "50 and 100 on the 7th when retested" -- take the 50,
    # ignore the retest figure.
    ("unparseable", "50 and 100 on the 7th when retested", "nitrate", "value", "50",
     "owner: 'For the 50 and 100 location, set 50 for that entry, ignore 100 on the 7th'"),

    # 15-16: unexplained 0-10 clarity scale readings, both 3.
    ("unparseable", "3/10", "turbidity", "value", "3",
     "owner: 'For the 3/10 or 3 from 10 readings, accept 3.0 for both'"),
    ("unparseable", "3 from 10 quite clear", "turbidity", "value", "3",
     "owner: 'For the 3/10 or 3 from 10 readings, accept 3.0 for both'"),

    # 17: nitrate "50 and 100 when tested on the 7th"
    ("unparseable", "50 and 100 when tested on the 7th", "nitrate", "value", "50",
     "owner: 'Accept 50'"),

    # 18-20: three prose turbidity descriptions -- the owner asked for the
    # most appropriate classification for each.
    ("unparseable", "Centre of the river is cloudy and fast flowing, sides are clearer. Water very high.",
     "turbidity", "category", "cloudy",
     "owner: classify from the description -- centre of the river was cloudy"),
    ("unparseable", "River slightly dull sample clear", "turbidity", "category", "clear",
     "owner: classify from the description -- the sample itself was clear"),
    ("unparseable", "Dull,a slight amount of foam in eddies", "turbidity", "category",
     "slightly_cloudy",
     "owner: classify from the description -- 'dull' is the nearest scale word"),

    # 21: the third "3 from 10" reading
    ("unparseable", "3 from 10 quite clear", "turbidity", "value", "3",
     "owner: 'Accept as 3'"),

    # 22: depth "Over 85cm and flooding"
    ("unparseable", "Over 85cm and flooding", "water_depth", "value", "85",
     "owner: 'Take the 85cm depth'"),

    # 23: ammonia "0.02 ph" -- keep the 0.02, ignore the stray 'ph'.
    ("unparseable", "0.02 ph", "ammonia", "value", "0.02",
     "owner: 'Use just the value 0.02'"),

    # 24-25: two turbidity entries the owner says should not stand as
    # readings for their sites.
    ("unparseable", "Fresh", "turbidity", "remove", None,
     "owner: 'Ignore (remove reading for this site)'"),
    ("unparseable", "Nil", "turbidity", "remove", None,
     "owner: 'Remove reading for this site'"),
]


def apply() -> int:
    """Write every decision into `review_decisions`, keyed on the reading
    itself (issue + value_raw + parameter + the entry it belongs to), so
    this can be re-run safely after any rebuild.

    Several decisions share the same (issue, value_raw, parameter) key --
    four dissolved-oxygen zeros, two "3 from 10" readings -- so matching
    consumes the queue rows for a key in id order."""
    conn = get_connection()
    applied = 0
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    try:
        rows = conn.execute(
            "SELECT ec5_uuid, parameter, value_raw, issue FROM review_queue ORDER BY id"
        ).fetchall()
        entries: dict = {}
        for r in rows:
            entries.setdefault((r["issue"], r["value_raw"], r["parameter"]), []).append(
                r["ec5_uuid"]
            )

        for issue, value_raw, parameter, kind, resolved_value, note in DECISIONS:
            key = (issue, value_raw, parameter)
            uuids = entries.get(key) or []
            if not uuids:
                print(f"  skipped (not in queue): {issue} {value_raw!r} {parameter}")
                continue
            ec5_uuid = uuids.pop(0)
            # Idempotent: replace any earlier copy of this exact decision
            # (the table survives rebuilds, this script may be re-run).
            if parameter is None:
                conn.execute(
                    "DELETE FROM review_decisions WHERE ec5_uuid = ? AND parameter IS NULL",
                    (ec5_uuid,),
                )
            else:
                conn.execute(
                    "DELETE FROM review_decisions WHERE ec5_uuid = ? AND parameter = ?",
                    (ec5_uuid, parameter),
                )
            conn.execute(
                "INSERT INTO review_decisions (ec5_uuid, parameter, value_raw, "
                "issue, kind, resolved_value, note, resolved_at, resolved_by) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (ec5_uuid, parameter, value_raw, issue, kind, resolved_value, note,
                 now, "owner"),
            )
            applied += 1
    finally:
        conn.commit()
        conn.close()
    return applied


def main() -> int:
    n = apply()
    print(f"Recorded {n} of {len(DECISIONS)} owner decisions.")
    if n < len(DECISIONS):
        print("Some decisions did not match a queue item -- check the output above.")
        print("(If the queue is empty this is fine: decisions persist in review_decisions.)")
    print("Now run: python -m v2.ingest --refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
