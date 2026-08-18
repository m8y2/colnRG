#!/usr/bin/env python3
"""Re-ingest the Coln River Guardians data from EpiCollect5, from source.

Two layers, per `V2_SPEC_ADDENDUM.md`:

  raw_entries    the exact API payload, stored once and never mutated
  everything else  derived, and rebuildable from raw_entries at any time

That split is the whole point. v1 cleaned in place and lost the original
readings; here the raw layer is the record and the derived layer is an
opinion about it that can be thrown away and recomputed.

    python -m v2.ingest --fetch      # re-fetch from the API, then rebuild
    python -m v2.ingest --refresh    # rebuild from stored raw only (no network)

`--refresh` is idempotent: derived tables are truncated and rebuilt, so
running it twice leaves the database in the same state.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from v2.cleaning import PARAMETERS, clean_value
from v2.db import get_connection, init_v2_db
from v2.locations import load_all_locations, load_supplement, resolve_w3w

EXPORT_URL = "https://five.epicollect.net/api/export/entries/coln-river-guardians"
PER_PAGE = 500
USER_AGENT = "RiverGuardiansDashboard/2.0"

# EpiCollect field keys. Same names as v1's sync.py FIELD_KEYS -- reused
# rather than re-derived, so the two agree about what a column means.
F_W3W = "1_What_are_your_What"
F_W3W_OTHER = "3_Please_type_your_W"
F_LANDOWNER = "4_Landowner_if_known"
F_DATE = "5_What_is_the_date"
F_TIME = "6_What_is_the_time"
F_PHOTO = "17_Add_a_photo_of_is"
F_PHOTO_DESC = "18_Photo_Description"
F_PHOTO_2 = "19_Add_additional_ph"
F_NOTES = ("16_Additional_Commen", "21_Additional_Commen", "22_Additional_Commen")

PARAM_FIELDS = {
    "water_depth": "7_Estimate_the_water",
    "phosphate": "8_What_is_the_phosph",
    "ammonia": "9_What_is_the_ammoni",
    "nitrate": "10_What_is_the_nitra",
    "turbidity": "11_What_is_the_turbi",
    "dissolved_oxygen": "12_Dissolved_oxygen",
    "conductivity": "13_What_is_the_condu",
}

# Submissions that are plainly not samples. Matched case-insensitively
# against the whole location text. They are kept in the database and shown
# on the data-quality view -- excluded from statistics, not deleted.
JUNK_LOCATION_TEXT = {
    "anothertest",
    "testingitout",
    "end of round three",
}


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_entries(url: str | None = None) -> list[dict]:
    """Pull every entry from the public EpiCollect export (no auth needed)."""
    entries: list[dict] = []
    next_url = url or f"{EXPORT_URL}?per_page={PER_PAGE}"
    while next_url:
        req = urllib.request.Request(next_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
        entries.extend(payload.get("data", {}).get("entries", []))
        next_url = (payload.get("links") or {}).get("next")
    return entries


def store_raw(conn, entries: list[dict]) -> int:
    """Upsert the raw payloads. Never edits a stored payload's meaning --
    a re-fetch of the same uuid simply refreshes the snapshot."""
    now = datetime.now(timezone.utc).isoformat()
    for e in entries:
        conn.execute(
            "INSERT INTO raw_entries (ec5_uuid, created_at, uploaded_at, fetched_at, payload_json) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(ec5_uuid) DO UPDATE SET "
            "  created_at=excluded.created_at, uploaded_at=excluded.uploaded_at, "
            "  fetched_at=excluded.fetched_at, payload_json=excluded.payload_json",
            (e.get("ec5_uuid"), e.get("created_at"), e.get("uploaded_at"), now,
             json.dumps(e, sort_keys=True)),
        )
    conn.commit()
    return len(entries)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def iso_date(raw: str | None) -> str | None:
    """EpiCollect submits DD/MM/YYYY. Store ISO so dates sort as strings."""
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_recorder(text: str | None) -> str | None:
    """The trailing token of the location field is the volunteer's initials.

    This is metadata about *who sampled*, never about *where* -- the whole
    reason v1's data model went wrong (see `V2_SPEC_ADDENDUM.md`, Change 3).
    """
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None
    tail = parts[-1].strip(".,;:()")
    if not tail or "." in tail:
        return None
    if tail.upper() == tail and 1 <= len(tail) <= 6:
        return tail
    return None


def location_text(payload: dict) -> str:
    """Both location fields, joined -- field 1 is a picklist that can read
    'Other', in which case the address is typed into field 3."""
    primary = (payload.get(F_W3W) or "").strip()
    other = (payload.get(F_W3W_OTHER) or "").strip()
    if primary.lower() in ("", "other"):
        return other or primary
    return primary


def collect_notes(payload: dict) -> str | None:
    bits = [(payload.get(k) or "").strip() for k in F_NOTES]
    joined = " | ".join(b for b in bits if b)
    return joined or None


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

DERIVED_TABLES = (
    "measurements",
    "observations",
    "cleaning_log",
    "review_queue",
    "location_aliases",
    "locations",
)


def rebuild(conn) -> dict:
    """Rebuild every derived table from raw_entries. Idempotent."""
    run_at = datetime.now(timezone.utc).isoformat()

    # manual_corrections deliberately survives -- it is the owner's
    # accumulated human judgement and must outlive any rebuild.
    for table in DERIVED_TABLES:
        conn.execute(f"DELETE FROM {table}")

    reference = load_all_locations()
    for w3w, meta in sorted(reference.items(), key=lambda kv: kv[1]["river_order"]):
        conn.execute(
            "INSERT INTO locations (w3w, river_order, latitude, longitude, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (w3w, meta["river_order"], meta["latitude"], meta["longitude"],
             meta.get("source", "reference_table")),
        )

    stats = {
        "entries": 0, "located": 0, "unlocated": 0, "test_entries": 0,
        "match_types": {}, "per_parameter": {}, "logged": 0, "queued": 0,
    }
    for p in PARAMETERS:
        stats["per_parameter"][p] = {"usable": 0, "unusable": 0, "ordinal": 0, "numeric": 0}

    aliases_seen: dict[str, tuple[str, str, str | None]] = {}
    rows = conn.execute(
        "SELECT ec5_uuid, payload_json FROM raw_entries ORDER BY ec5_uuid"
    ).fetchall()

    for row in rows:
        uuid = row["ec5_uuid"]
        payload = json.loads(row["payload_json"])
        stats["entries"] += 1

        raw_loc = location_text(payload)
        res = resolve_w3w(raw_loc, reference)
        sample_date = iso_date(payload.get(F_DATE))

        cleaned = {p: clean_value(payload.get(PARAM_FIELDS[p]), p) for p in PARAMETERS}
        any_measurement = any(c.usable for c in cleaned.values())

        # A junk submission, or an entry carrying neither a date nor a single
        # usable reading, is not a sample. Kept, flagged, excluded.
        is_junk = raw_loc.strip().lower() in JUNK_LOCATION_TEXT
        if is_junk or (sample_date is None and not any_measurement):
            status, excluded = "test_entry", 1
            reason = ("recognised as a test or marker submission, not a sample"
                      if is_junk else "no sample date and no usable readings")
            stats["test_entries"] += 1
        else:
            status = res.status
            excluded, reason = 0, None
            if res.status == "located":
                stats["located"] += 1
            else:
                stats["unlocated"] += 1

        if status != "test_entry" and res.match_type:
            stats["match_types"][res.match_type] = stats["match_types"].get(res.match_type, 0) + 1
            if res.normalized and res.normalized not in aliases_seen:
                aliases_seen[res.normalized] = (res.w3w, res.match_type, res.note)

        conn.execute(
            "INSERT INTO observations (ec5_uuid, sample_date, sample_time, w3w, w3w_raw, "
            "location_status, recorder, landowner_raw, notes, photo_url, photo_2_url, "
            "photo_desc, excluded, exclude_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uuid, sample_date, (payload.get(F_TIME) or "").strip() or None,
             res.w3w, raw_loc or None, status,
             extract_recorder(payload.get(F_W3W)),
             (payload.get(F_LANDOWNER) or "").strip() or None,
             collect_notes(payload),
             (payload.get(F_PHOTO) or "").strip() or None,
             (payload.get(F_PHOTO_2) or "").strip() or None,
             (payload.get(F_PHOTO_DESC) or "").strip() or None,
             excluded, reason),
        )

        for parameter, c in cleaned.items():
            conn.execute(
                "INSERT INTO measurements (ec5_uuid, parameter, value_raw, value, value_low, "
                "value_high, category, category_rank, qualifier, usable, flags) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uuid, parameter, c.value_raw, c.value, c.value_low, c.value_high,
                 c.category, c.category_rank, c.qualifier, c.usable,
                 json.dumps(c.flags) if c.flags else None),
            )
            bucket = stats["per_parameter"][parameter]
            bucket["usable" if c.usable else "unusable"] += 1
            if c.usable:
                bucket["ordinal" if c.qualifier == "ordinal" else "numeric"] += 1

            for log in c.logs:
                conn.execute(
                    "INSERT INTO cleaning_log (ec5_uuid, parameter, action, value_before, "
                    "value_after, reason, run_at) VALUES (?,?,?,?,?,?,?)",
                    (uuid, parameter, log.action, log.value_before, log.value_after,
                     log.reason, run_at),
                )
                stats["logged"] += 1

            if c.review is not None:
                conn.execute(
                    "INSERT INTO review_queue (ec5_uuid, parameter, value_raw, issue, "
                    "suggestion, suggestion_reason) VALUES (?,?,?,?,?,?)",
                    (uuid, parameter, c.value_raw, c.review.issue,
                     c.review.suggestion, c.review.suggestion_reason),
                )
                stats["queued"] += 1

    for alias, (w3w, match_type, note) in aliases_seen.items():
        if w3w:
            conn.execute(
                "INSERT OR REPLACE INTO location_aliases (alias, w3w, match_type, note) "
                "VALUES (?,?,?,?)",
                (alias, w3w, match_type, note),
            )

    stats["queued"] += queue_possible_duplicates(conn)
    suggest_decimal_shifts(conn)
    stats["manual_applied"] = apply_manual_corrections(conn, run_at)
    conn.commit()
    return stats


def suggest_decimal_shifts(conn) -> int:
    """Propose a reading for implausible values, without applying it.

    A phosphate of 47 mg/L is not a real river reading; it is almost
    certainly 0.47 with the decimal point lost. v1 acted on that hunch
    silently and overwrote the data. Here the hunch is written down, shown
    to the owner, and applied only if they accept it -- and only when the
    shifted value is both physically plausible and close to what this
    location normally reads, so the suggestion has evidence behind it.
    """
    from v2.cleaning import PLAUSIBLE_RANGES

    suggested = 0
    rows = conn.execute(
        "SELECT r.id, r.ec5_uuid, r.parameter, r.value_raw, m.value, o.w3w "
        "FROM review_queue r "
        "JOIN measurements m ON m.ec5_uuid = r.ec5_uuid AND m.parameter = r.parameter "
        "JOIN observations o ON o.ec5_uuid = r.ec5_uuid "
        "WHERE r.issue = 'implausible' AND r.suggestion IS NULL AND m.value IS NOT NULL"
    ).fetchall()

    for row in rows:
        lo, hi = PLAUSIBLE_RANGES.get(row["parameter"], (None, None))
        if hi is None:
            continue
        peers = [
            r[0] for r in conn.execute(
                "SELECT m.value FROM measurements m JOIN observations o USING (ec5_uuid) "
                "WHERE o.w3w = ? AND m.parameter = ? AND m.usable = 1 AND m.value IS NOT NULL",
                (row["w3w"], row["parameter"]),
            ).fetchall()
        ]
        if len(peers) < 3:
            continue
        peers.sort()
        median = peers[len(peers) // 2]

        for divisor in (10, 100):
            shifted = row["value"] / divisor
            if not (lo <= shifted <= hi):
                continue
            # "Close to normal for here" -- within an order of magnitude of
            # the location's median. Loose on purpose: this is a prompt for
            # a human, not a decision.
            if median > 0 and not (median / 10 <= shifted <= median * 10):
                continue
            conn.execute(
                "UPDATE review_queue SET suggestion = ?, suggestion_reason = ? WHERE id = ?",
                (f"{shifted:g}",
                 f"{row['value']:g} is outside the plausible range for {row['parameter']} "
                 f"({lo:g}-{hi:g}). Reading it as {shifted:g} — a decimal point {divisor} "
                 f"places out — is plausible and close to this location's usual "
                 f"{median:g}. Accept only if that matches the record sheet.",
                 row["id"]),
            )
            suggested += 1
            break
    return suggested


def queue_possible_duplicates(conn) -> int:
    """Two supplement points sit within riverbank-width of an existing
    reference point. They might be the same sampling spot recorded on a
    different 3m square -- but that is the owner's call, not ours, so they
    stay separate and the question goes in the queue."""
    queued = 0
    for w3w, meta in load_supplement().items():
        if not meta.get("needs_owner_review"):
            continue
        row = conn.execute(
            "SELECT ec5_uuid FROM observations WHERE w3w = ? ORDER BY sample_date LIMIT 1",
            (w3w,),
        ).fetchone()
        if row is None:
            continue
        n = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE w3w = ?", (w3w,)
        ).fetchone()[0]
        near = meta.get("nearest_reference")
        dist = meta.get("distance_to_nearest_m")
        conn.execute(
            "INSERT INTO review_queue (ec5_uuid, parameter, value_raw, issue, suggestion, "
            "suggestion_reason) VALUES (?,?,?,?,?,?)",
            (row["ec5_uuid"], None, w3w, "ambiguous_location",
             f"possibly the same location as {near}",
             f"{w3w} ({n} reading(s)) is {dist:.0f} m from {near}. That is about the width "
             f"of a riverbank, so they may be one sampling point recorded on two different "
             f"what3words squares. Accepting merges them; rejecting keeps them separate."),
        )
        queued += 1
    return queued


def apply_manual_corrections(conn, run_at: str) -> int:
    """The only route by which a human judgement enters the data. Applied
    after automatic cleaning, logged, and reversible by deleting the row."""
    applied = 0
    for row in conn.execute(
        "SELECT ec5_uuid, parameter, value, note FROM manual_corrections"
    ).fetchall():
        before = conn.execute(
            "SELECT value FROM measurements WHERE ec5_uuid = ? AND parameter = ?",
            (row["ec5_uuid"], row["parameter"]),
        ).fetchone()
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        conn.execute(
            "UPDATE measurements SET value = ?, qualifier = 'manual_correction', usable = 1 "
            "WHERE ec5_uuid = ? AND parameter = ?",
            (value, row["ec5_uuid"], row["parameter"]),
        )
        conn.execute(
            "INSERT INTO cleaning_log (ec5_uuid, parameter, action, value_before, value_after, "
            "reason, run_at) VALUES (?,?,?,?,?,?,?)",
            (row["ec5_uuid"], row["parameter"], "manual_correction",
             str(before["value"]) if before and before["value"] is not None else None,
             str(value), row["note"] or "accepted by the project owner", run_at),
        )
        applied += 1
    return applied


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def report(stats: dict) -> None:
    print(f"\nEntries ingested       {stats['entries']}")
    print(f"  located              {stats['located']}")
    print(f"  unlocated            {stats['unlocated']}")
    print(f"  test entries         {stats['test_entries']}")
    if stats["match_types"]:
        print("\nHow locations resolved")
        for k, v in sorted(stats["match_types"].items(), key=lambda kv: -kv[1]):
            print(f"  {k:20s} {v}")
    print("\nReadings by parameter        usable   (numeric / ordinal)   unusable")
    total_usable = 0
    for p in PARAMETERS:
        b = stats["per_parameter"][p]
        total_usable += b["usable"]
        print(f"  {p:22s} {b['usable']:6d}   ({b['numeric']:5d} / {b['ordinal']:5d})   {b['unusable']:6d}")
    print(f"  {'TOTAL USABLE':22s} {total_usable:6d}")
    print(f"\nCleaning actions logged  {stats['logged']}")
    print(f"Manual corrections       {stats.get('manual_applied', 0)}")
    print(f"Awaiting owner review    {stats['queued']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="re-fetch from EpiCollect first")
    ap.add_argument("--refresh", action="store_true", help="rebuild derived tables from stored raw")
    ap.add_argument("--from-file", help="load raw entries from a cached JSON file instead of the API")
    args = ap.parse_args()

    if not (args.fetch or args.refresh or args.from_file):
        ap.error("choose --fetch, --refresh, or --from-file")

    init_v2_db()
    conn = get_connection()

    if args.from_file:
        entries = json.loads(Path(args.from_file).read_text())
        print(f"Loaded {store_raw(conn, entries)} raw entries from {args.from_file}")
    elif args.fetch:
        entries = fetch_entries()
        print(f"Fetched {store_raw(conn, entries)} raw entries from EpiCollect")

    report(rebuild(conn))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
