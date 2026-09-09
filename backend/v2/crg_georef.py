"""Cross-reference the readings against the owner's georeferenced backup.

The original EpiCollect project (`coln-river-guardians`) asks volunteers to
type a what3words address, so a sample's position is only ever as good as
that typing. The owner later published a second project, "CRG backup data
with georef" (`crg-backup-data-with-georef`), holding the same fieldwork
with a real lat/long on every entry and the readings tidied into numbers.

Where the two disagree, this dataset wins. That is the owner's instruction
and it is also the better source: a coordinate cannot be misspelled, and the
tidying was done by the people who hold the paper records.

It is not a replacement, though, because it does not carry everything:

  * no dissolved oxygen, no conductivity  -- only the original has these
  * no volunteer initials, photos or landowner
  * 17 samples that the original has are missing from it
  * 40 of its 512 rows are duplicates of a sibling row

So this runs as a pass over the derived tables after `ingest.rebuild()`:
the original supplies the record set and the columns the backup lacks, and
the backup overwrites position and readings wherever it has them.

The one thing it is not allowed to overwrite
--------------------------------------------
The backup stores a plain 0 where a volunteer wrote that no reading was
taken -- "No water", "Tributary dry", "Insufficient kit to test", "NA",
"Invalid" -- and where the original field was simply left empty. Sixty-odd
of those exist. Adopting them would put false zeros into phosphate,
ammonia and nitrate and pull every average down, which is the same fault
that made the v1 numbers untrustworthy.

So a zero from the backup is taken as a real zero only when the original
reading also reads as a zero, or was a number, or the original is a
plain-language nil ("Nil", "0.00 ppm", "O.00"). Otherwise the reading is
recorded as not taken, both texts are kept, and the decision is written to
`cleaning_log` under `crg_zero_withheld` so it can be listed and reversed.
Set CRG_TRUST_ZEROS=1 to adopt them anyway.

Usage
-----
    python -m backend.v2.crg_georef --fetch      # re-fetch, then merge
    python -m backend.v2.crg_georef --merge      # merge from stored raw
    python -m backend.v2.crg_georef --report     # what the merge changed
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from v2.cleaning import clean_value
from v2.db import get_connection, init_v2_db

CRG_SLUG = "crg-backup-data-with-georef"
CRG_URL = f"https://five.epicollect.net/api/export/entries/{CRG_SLUG}?per_page=500"

F_DATE = "1_When_did_you_do_th"
F_TIME = "2_What_time_was_the_"
F_GEO = "3_lat_long"
F_COMMENTS = "9_Comments"

# The five parameters the backup carries, mapped to the original's field names
# so a pair can be compared text against text.
CRG_FIELDS = {
    "water_depth": ("4_Water_depth_in_cen", "7_Estimate_the_water"),
    "phosphate": ("5_Phosphate_mgl", "8_What_is_the_phosph"),
    "ammonia": ("6_Ammonia_mgl", "9_What_is_the_ammoni"),
    "nitrate": ("7_Nitrate_ppm", "10_What_is_the_nitra"),
    "turbidity": ("8_Turbidity", "11_What_is_the_turbi"),
}

# Not in the backup at all; whatever the original produced is left alone.
CARRIED_FROM_ORIGINAL = ("dissolved_oxygen", "conductivity")

LOCATIONS_CSV = Path(__file__).resolve().parent / "data" / "crg_locations.csv"

# A coordinate this far from a known point is the same sampling place.
SAME_PLACE_M = 25.0

# Original text that means "there is no reading here", as opposed to a
# reading of zero. Matched only when the backup says 0.
NO_READING = re.compile(
    r"(no water|dry\b|not?\s*test|no\s*test|n/?a\b|n/?k\b|invalid|insufficient"
    r"|unable|no access|not measured|no sample|no kit|not done|tbc|missing)",
    re.I,
)
# Original text that means a genuine zero even though it is not a bare number.
REAL_ZERO = re.compile(r"^\s*(nil|none|zero|[o0][.,][o0]+\s*(ppm|mg/?l|ph)?)\s*$", re.I)


# ---------------------------------------------------------------------------
# Fetching and storing
# ---------------------------------------------------------------------------

def fetch_crg(url: str | None = None) -> list[dict]:
    """Every entry in the backup project, following pagination."""
    entries: list[dict] = []
    next_url = url or CRG_URL
    while next_url:
        with urllib.request.urlopen(next_url, timeout=60) as response:
            payload = json.load(response)
        entries.extend(payload["data"]["entries"])
        meta = payload.get("meta") or {}
        page, last = meta.get("current_page"), meta.get("last_page")
        base = (url or CRG_URL).split("&page=")[0]
        next_url = f"{base}&page={page + 1}" if page and last and page < last else None
    return entries


def store_crg_raw(conn, entries: list[dict]) -> int:
    """Keep the backup payloads exactly as served, same contract as raw_entries."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        conn.execute(
            "INSERT OR REPLACE INTO crg_raw_entries "
            "(ec5_uuid, created_at, uploaded_at, fetched_at, payload_json) "
            "VALUES (?,?,?,?,?)",
            (entry["ec5_uuid"], entry.get("created_at"), entry.get("uploaded_at"),
             fetched_at, json.dumps(entry, sort_keys=True)),
        )
    conn.commit()
    return len(entries)


def stored_crg(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT payload_json FROM crg_raw_entries ORDER BY ec5_uuid"
    ).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def owner_merges(conn) -> dict[str, str]:
    """Sampling points the owner has decided are one place, source -> target.

    Two what3words squares a few metres apart can be one spot on the bank, and
    only the owner knows which. Those decisions live in `review_decisions` and
    outlive every rebuild, so the backup's coordinates are not allowed to undo
    them: a merged-away square never becomes a location again, and its samples
    land on the square the owner kept.
    """
    merges = {
        row["value_raw"]: row["resolved_value"]
        for row in conn.execute(
            "SELECT value_raw, resolved_value FROM review_decisions "
            "WHERE kind = 'merge' AND resolved_value IS NOT NULL"
        )
    }
    # Follow a chain (a merged into b, b merged into c) to its end.
    resolved = {}
    for source in merges:
        target, seen = source, {source}
        while target in merges and merges[target] not in seen:
            target = merges[target]
            seen.add(target)
        if target != source:
            resolved[source] = target
    return resolved


def owner_decided(conn) -> set[tuple[str, str]]:
    """Readings the owner has personally ruled on, as (sample, parameter).

    The backup wins over the original data, but not over the owner. Someone
    who has looked at a reading and said "that 23 is a mistyped 0.23", "that
    one was never measured", or "drop it" has better information than any
    bulk dataset, and `review_decisions` exists precisely so that judgement
    survives every rebuild. The merge leaves these alone.
    """
    return {
        (row["ec5_uuid"], row["parameter"])
        for row in conn.execute(
            "SELECT ec5_uuid, parameter FROM review_decisions WHERE parameter IS NOT NULL"
        )
    } | {
        (row["ec5_uuid"], row["parameter"])
        for row in conn.execute("SELECT ec5_uuid, parameter FROM manual_corrections")
    }


def load_crg_locations(path: Path | str = LOCATIONS_CSV) -> dict[str, dict]:
    """The generated table of sampling points, keyed by canonical w3w."""
    text = Path(path).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    out: dict[str, dict] = {}
    for row in csv.DictReader(lines):
        out[row["w3w"]] = {
            "w3w": row["w3w"],
            "river_order": float(row["river_order"]),
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "w3w_verified": row["w3w_verified"],
            "name_basis": row["name_basis"],
        }
    return out


def metres(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius = 6371000.0
    p1, p2 = math.radians(lat_a), math.radians(lat_b)
    dp, dl = math.radians(lat_b - lat_a), math.radians(lon_b - lon_a)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def locate(entry: dict, locations: dict[str, dict]) -> tuple[str | None, float]:
    """Which sampling point an entry's coordinate belongs to."""
    geo = entry.get(F_GEO) or {}
    lat, lon = geo.get("latitude"), geo.get("longitude")
    if lat is None or lon is None:
        return None, float("inf")
    key = (round(lat, 6), round(lon, 6))
    for w3w, loc in locations.items():
        if (round(loc["latitude"], 6), round(loc["longitude"], 6)) == key:
            return w3w, 0.0
    best, best_d = None, float("inf")
    for w3w, loc in locations.items():
        d = metres(lat, lon, loc["latitude"], loc["longitude"])
        if d < best_d:
            best, best_d = w3w, d
    return (best, best_d) if best_d <= SAME_PLACE_M else (None, best_d)


# ---------------------------------------------------------------------------
# Preparing the backup rows
# ---------------------------------------------------------------------------

def iso_date(raw: str | None) -> str | None:
    """The backup writes dates as dd/mm/yyyy."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def prepare(entries: list[dict], locations: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Tag each backup row with date, time and place, and drop duplicate rows.

    40 of the 512 rows repeat a sibling exactly. They are dropped here rather
    than counted as extra samples, and returned so the count can be reported.
    """
    prepared: list[dict] = []
    for entry in entries:
        w3w, distance = locate(entry, locations)
        prepared.append({
            "uuid": entry["ec5_uuid"],
            "date": iso_date(entry.get(F_DATE)),
            "time": _text(entry.get(F_TIME)),
            "w3w": w3w,
            "distance_m": distance,
            "comments": _text(entry.get(F_COMMENTS)),
            "values": {p: _text(entry.get(crg_f)) for p, (crg_f, _) in CRG_FIELDS.items()},
            "payload": entry,
        })

    seen: dict[tuple, dict] = {}
    kept, dropped = [], []
    for row in prepared:
        signature = (row["date"], row["time"], row["w3w"], row["comments"],
                     tuple(sorted(row["values"].items())))
        if signature in seen:
            dropped.append(row)
            continue
        seen[signature] = row
        kept.append(row)
    return kept, dropped


# ---------------------------------------------------------------------------
# Matching backup rows to the samples already loaded
# ---------------------------------------------------------------------------

def _agreement(row: dict, payload: dict) -> int:
    """How strongly a backup row and an original entry look like the same sample.

    Used only to break ties inside a group -- several volunteers do submit at
    the same place and clock time, and one of them sometimes submits twice.
    """
    score = 0
    for parameter, (_, original_field) in CRG_FIELDS.items():
        crg_text = row["values"][parameter]
        original_text = _text(payload.get(original_field))
        if not crg_text and not original_text:
            continue
        crg_number, original_number = _as_number(crg_text), _as_number(original_text)
        if crg_number is not None and original_number is not None:
            score += 2 if crg_number == original_number else 0
        elif crg_text.lower() == original_text.lower():
            score += 2
        elif crg_text and original_text and (
            crg_text.lower() in original_text.lower()
            or original_text.lower() in crg_text.lower()
        ):
            score += 1
    comment = _text(payload.get("16_Additional_Commen"))
    if row["comments"] and comment:
        score += 3 if row["comments"] == comment else 0
    return score


def match(conn, rows: list[dict], originals: dict[str, dict]) -> tuple[dict[str, dict], list[dict], list[str]]:
    """Pair each backup row with the sample it describes.

    Three passes, narrowest key first. Within a key, rows are paired to
    samples in order of how well their readings agree, so a key that picks
    out two samples (two volunteers at one bridge, or one volunteer
    submitting twice) still pairs both rather than leaving four records
    where there should be two.

    Returns {observation uuid: backup row}, unmatched backup rows, and the
    uuids of samples the backup does not contain.
    """
    observations = conn.execute(
        "SELECT ec5_uuid, sample_date, sample_time, w3w, location_status FROM observations"
    ).fetchall()
    obs = [dict(o) for o in observations if o["location_status"] != "test_entry"]
    for o in obs:
        o["time"] = _text(o["sample_time"])

    paired: dict[str, dict] = {}
    claimed_rows: set[str] = set()
    claimed_obs: set[str] = set()

    def run(key_of_row, key_of_obs) -> None:
        by_row = defaultdict(list)
        for r in rows:
            if r["uuid"] not in claimed_rows:
                by_row[key_of_row(r)].append(r)
        by_obs = defaultdict(list)
        for o in obs:
            if o["ec5_uuid"] not in claimed_obs:
                by_obs[key_of_obs(o)].append(o)
        for key, candidates in by_row.items():
            targets = by_obs.get(key) or []
            if not targets:
                continue
            scored = sorted(
                ((_agreement(r, originals.get(o["ec5_uuid"], {})), r, o)
                 for r in candidates for o in targets),
                key=lambda t: (-t[0], t[1]["uuid"], t[2]["ec5_uuid"]),
            )
            for _, row, target in scored:
                if row["uuid"] in claimed_rows or target["ec5_uuid"] in claimed_obs:
                    continue
                paired[target["ec5_uuid"]] = row
                claimed_rows.add(row["uuid"])
                claimed_obs.add(target["ec5_uuid"])

    # Date, time and place agree: the safe case, and nearly all of them.
    run(lambda r: (r["date"], r["time"], r["w3w"]),
        lambda o: (o["sample_date"], o["time"], o["w3w"]))
    # Date and time agree but the place does not: exactly the disagreement
    # this whole pass exists to resolve, so pair it and let the backup win.
    run(lambda r: (r["date"], r["time"]),
        lambda o: (o["sample_date"], o["time"]))
    # Same place on the same day: a mistyped clock time.
    run(lambda r: (r["date"], r["w3w"]),
        lambda o: (o["sample_date"], o["w3w"]))

    unmatched_rows = [r for r in rows if r["uuid"] not in claimed_rows]
    original_only = [o["ec5_uuid"] for o in obs if o["ec5_uuid"] not in claimed_obs]
    return paired, unmatched_rows, original_only


# ---------------------------------------------------------------------------
# The zero rule
# ---------------------------------------------------------------------------

def _as_number(text: str) -> float | None:
    try:
        return float(_text(text).rstrip(".").replace(",", "."))
    except (TypeError, ValueError):
        return None


def zero_is_real(crg_text: str, original_text: str) -> bool:
    """Whether a 0 in the backup is a reading of zero or a missing reading."""
    if _as_number(crg_text) != 0:
        return True
    original = _text(original_text)
    if original == "":
        return False
    if _as_number(original) is not None:
        return True
    if REAL_ZERO.match(original):
        return True
    if NO_READING.search(original):
        return False
    return False


# ---------------------------------------------------------------------------
# Recording that no reading was taken
# ---------------------------------------------------------------------------

def write_not_measured(conn, uuid: str, parameter: str, value_raw: str | None,
                       flags: list[str]) -> None:
    """Record that a parameter was not measured on this visit.

    A missing reading is never a reading of zero. It is stored the same way
    the owner's own "not measured" decision stores one -- every value column
    NULL, `qualifier='absent'`, `usable=0` -- so there is one representation
    of "no reading" in the database rather than two. Everything that computes
    a figure filters on `usable=1`, so these can never reach a mean, a band, a
    chart or the CSV export; `value_raw` keeps what the volunteer actually
    wrote, so the reason stays visible on the data page.
    """
    conn.execute(
        "INSERT OR REPLACE INTO measurements (ec5_uuid, parameter, value_raw, value, "
        "value_low, value_high, category, category_rank, qualifier, usable, flags) "
        "VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,'absent',0,?)",
        (uuid, parameter, value_raw, json.dumps(sorted(set(flags)))),
    )


# ---------------------------------------------------------------------------
# One visit submitted twice
# ---------------------------------------------------------------------------

def exclude_re_records(conn, run_at: str) -> int:
    """Keep only the newest submission where one visit was recorded twice.

    A volunteer who spots a typo sometimes submits the whole visit again
    rather than editing it, leaving two records of one sample: same place,
    same clock time, same readings, minutes apart. Counted twice they weight
    that place double in every average.

    A pair only qualifies when the readings are identical, so two volunteers
    who genuinely sampled the same bridge at the same time are left alone.
    The older record is excluded rather than deleted -- the raw entry is
    never touched, and `excluded=1` keeps it out of every figure while it
    stays visible with its reason attached.
    """
    groups = conn.execute(
        """
        SELECT o.sample_date, o.sample_time, o.w3w,
               GROUP_CONCAT(o.ec5_uuid) AS uuids, COUNT(*) AS n
        FROM observations o
        WHERE o.location_status = 'located' AND o.excluded = 0
          AND o.sample_time IS NOT NULL
        GROUP BY o.sample_date, o.sample_time, o.w3w
        HAVING n > 1
        """
    ).fetchall()

    excluded = 0
    for group in groups:
        uuids = group["uuids"].split(",")
        readings, submitted = {}, {}
        for uuid in uuids:
            readings[uuid] = tuple(sorted(
                (r["parameter"], _text(r["value_raw"]))
                for r in conn.execute(
                    "SELECT parameter, value_raw FROM measurements WHERE ec5_uuid=?", (uuid,))
            ))
            row = conn.execute(
                "SELECT created_at FROM raw_entries WHERE ec5_uuid=?", (uuid,)
            ).fetchone()
            submitted[uuid] = (row["created_at"] if row else None) or ""
        if len({readings[u] for u in uuids}) != 1:
            continue  # different readings: two real samples, not a re-record
        newest = max(uuids, key=lambda u: (submitted[u], u))
        for uuid in uuids:
            if uuid == newest:
                continue
            conn.execute(
                "UPDATE observations SET excluded = 1, exclude_reason = ? WHERE ec5_uuid = ?",
                ("the same visit was submitted again a few minutes later, and that "
                 "later record is the one kept", uuid),
            )
            conn.execute(
                "INSERT INTO cleaning_log (ec5_uuid, parameter, action, value_before, "
                "value_after, reason, run_at) VALUES (?,?,?,?,?,?,?)",
                (uuid, None, "re_record_excluded", uuid, newest,
                 f"identical readings at {group['w3w']} on {group['sample_date']} "
                 f"{group['sample_time']}; the newer submission is kept", run_at),
            )
            excluded += 1
    return excluded


# ---------------------------------------------------------------------------
# Samples that may be one visit dated two ways
# ---------------------------------------------------------------------------

# Rounds run monthly, so two records of one visit can sit a round apart if one
# dataset carries the fieldwork date and the other the date it was written up.
DATE_CONFLICT_DAYS = 60


def queue_date_conflicts(conn) -> int:
    """Queue backup-only samples that look like an original-only sample redated."""
    added = 0
    crg_only = conn.execute(
        "SELECT ec5_uuid, sample_date, w3w FROM observations WHERE crg_status='crg_only'"
    ).fetchall()
    for row in crg_only:
        twin = conn.execute(
            "SELECT ec5_uuid, sample_date FROM observations "
            "WHERE crg_status='original_only' AND w3w=? "
            "ORDER BY ABS(JULIANDAY(sample_date) - JULIANDAY(?)) LIMIT 1",
            (row["w3w"], row["sample_date"]),
        ).fetchone()
        if twin is None:
            continue
        gap = conn.execute(
            "SELECT ABS(JULIANDAY(?) - JULIANDAY(?)) AS d", (twin["sample_date"], row["sample_date"])
        ).fetchone()["d"]
        if gap is None or gap > DATE_CONFLICT_DAYS:
            continue
        already = conn.execute(
            "SELECT 1 FROM review_queue WHERE ec5_uuid=? AND issue='conflicting_date'",
            (row["ec5_uuid"],),
        ).fetchone()
        if already:
            continue
        conn.execute(
            "INSERT INTO review_queue (ec5_uuid, parameter, value_raw, issue, suggestion, "
            "suggestion_reason) VALUES (?,?,?,?,?,?)",
            (row["ec5_uuid"], None, row["sample_date"], "conflicting_date",
             twin["sample_date"],
             f"The georeferenced backup has a sample at {row['w3w']} on "
             f"{row['sample_date']} that the original data does not, and the original "
             f"has one at the same place on {twin['sample_date']} that the backup does "
             f"not, {gap:.0f} days apart. That is probably one visit dated two ways "
             f"rather than two visits. Accepting treats them as the same visit and "
             f"keeps the backup's date; rejecting keeps both."),
        )
        added += 1
    return added


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------

def merge(conn, trust_zeros: bool | None = None) -> dict:
    """Apply the backup over the derived tables. Idempotent."""
    if trust_zeros is None:
        trust_zeros = os.environ.get("CRG_TRUST_ZEROS", "") == "1"
    run_at = datetime.now(timezone.utc).isoformat()
    merged_away = owner_merges(conn)
    decided = owner_decided(conn)
    locations = load_crg_locations()
    # `prepare` needs the merged-away squares present so a coordinate still
    # resolves; the samples are then moved onto the point the owner kept and
    # the squares themselves are dropped, never to be recreated as locations.
    rows, duplicates = prepare(stored_crg(conn), locations)
    for row in rows + duplicates:
        if row["w3w"] in merged_away:
            row["w3w_coordinate"] = row["w3w"]
            row["w3w"] = merged_away[row["w3w"]]
    locations = {w: loc for w, loc in locations.items() if w not in merged_away}

    stats = {
        "crg_rows": len(rows) + len(duplicates),
        "crg_duplicates_dropped": len(duplicates),
        "matched": 0, "crg_only_added": 0, "original_only_kept": 0,
        "owner_merges_respected": len(merged_away), "owner_decisions_kept": 0,
        "location_changed": 0, "coordinate_updated": 0, "locations_added": 0,
        "readings_replaced": 0, "readings_added": 0,
        "zeros_withheld": 0, "unlocated_rows": 0,
        "per_parameter": defaultdict(lambda: {"replaced": 0, "withheld": 0}),
    }

    def log(uuid, parameter, action, before, after, reason):
        conn.execute(
            "INSERT INTO cleaning_log (ec5_uuid, parameter, action, value_before, "
            "value_after, reason, run_at) VALUES (?,?,?,?,?,?,?)",
            (uuid, parameter, action, before, after, reason, run_at),
        )

    # --- locations -------------------------------------------------------
    existing = {r["w3w"] for r in conn.execute("SELECT w3w FROM locations")}
    for w3w, loc in sorted(locations.items(), key=lambda kv: kv[1]["river_order"]):
        if w3w in existing:
            before = conn.execute(
                "SELECT latitude, longitude FROM locations WHERE w3w=?", (w3w,)
            ).fetchone()
            moved = before and metres(before["latitude"], before["longitude"],
                                      loc["latitude"], loc["longitude"]) > 1
            conn.execute(
                "UPDATE locations SET latitude=?, longitude=?, river_order=?, source=? "
                "WHERE w3w=?",
                (loc["latitude"], loc["longitude"], loc["river_order"], "crg_georef", w3w),
            )
            if moved:
                stats["coordinate_updated"] += 1
                log(None, None, "crg_coordinate_updated",
                    f"{before['latitude']:.6f},{before['longitude']:.6f}",
                    f"{loc['latitude']:.6f},{loc['longitude']:.6f}",
                    f"{w3w} moved to its georeferenced position")
        else:
            conn.execute(
                "INSERT INTO locations (w3w, river_order, latitude, longitude, source) "
                "VALUES (?,?,?,?,?)",
                (w3w, loc["river_order"], loc["latitude"], loc["longitude"], "crg_georef"),
            )
            stats["locations_added"] += 1
            log(None, None, "crg_location_added", None, w3w,
                "sampling point present in the georeferenced backup only")
        # Either spelling of a point should resolve to it.
        for alias in {w3w, loc["w3w_verified"]}:
            if alias in merged_away:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO location_aliases (alias, w3w, match_type, note) "
                "VALUES (?,?,?,?)",
                (alias, w3w, "crg_georef",
                 "what3words address of the georeferenced coordinate"
                 if alias == loc["w3w_verified"] else "canonical name"),
            )

    # --- samples ---------------------------------------------------------
    originals = {
        r["ec5_uuid"]: json.loads(r["payload_json"])
        for r in conn.execute("SELECT ec5_uuid, payload_json FROM raw_entries")
    }
    paired, crg_only, original_only = match(conn, rows, originals)
    stats["matched"] = len(paired)
    stats["original_only_kept"] = len(original_only)
    stats["unlocated_rows"] = sum(1 for r in rows if r["w3w"] is None)

    for uuid, row in paired.items():
        observation = conn.execute(
            "SELECT w3w, sample_date, sample_time FROM observations WHERE ec5_uuid=?",
            (uuid,),
        ).fetchone()
        original = originals.get(uuid, {})

        if row["w3w"] and row["w3w"] != observation["w3w"]:
            conn.execute(
                "UPDATE observations SET w3w=?, location_status='located' WHERE ec5_uuid=?",
                (row["w3w"], uuid),
            )
            stats["location_changed"] += 1
            log(uuid, None, "crg_location_replaced", observation["w3w"], row["w3w"],
                "the georeferenced backup puts this sample somewhere else")

        conn.execute(
            "UPDATE observations SET crg_uuid=?, crg_status='matched' WHERE ec5_uuid=?",
            (row["uuid"], uuid),
        )

        for parameter, (_, original_field) in CRG_FIELDS.items():
            crg_text = row["values"][parameter]
            if crg_text == "":
                continue
            if (uuid, parameter) in decided:
                stats["owner_decisions_kept"] += 1
                continue
            original_text = _text(original.get(original_field))
            if not trust_zeros and not zero_is_real(crg_text, original_text):
                write_not_measured(conn, uuid, parameter, original_text or None,
                                   ["crg_zero_withheld"])
                stats["zeros_withheld"] += 1
                stats["per_parameter"][parameter]["withheld"] += 1
                log(uuid, parameter, "crg_zero_withheld", original_text or "(blank)", None,
                    "the backup records 0 here but the volunteer recorded no reading, "
                    "so it is kept as no reading rather than a measurement of zero")
                continue

            cleaned = clean_value(crg_text, parameter)
            before = conn.execute(
                "SELECT value_raw, value, category FROM measurements "
                "WHERE ec5_uuid=? AND parameter=?", (uuid, parameter),
            ).fetchone()
            conn.execute(
                "INSERT OR REPLACE INTO measurements (ec5_uuid, parameter, value_raw, value, "
                "value_low, value_high, category, category_rank, qualifier, usable, flags) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uuid, parameter, cleaned.value_raw, cleaned.value, cleaned.value_low,
                 cleaned.value_high, cleaned.category, cleaned.category_rank,
                 cleaned.qualifier, cleaned.usable,
                 json.dumps(sorted(set(cleaned.flags) | {"from_crg"}))),
            )
            if before is None:
                stats["readings_added"] += 1
            elif _text(before["value_raw"]) != crg_text:
                stats["readings_replaced"] += 1
                stats["per_parameter"][parameter]["replaced"] += 1
                log(uuid, parameter, "crg_value_replaced", before["value_raw"], crg_text,
                    "reading taken from the georeferenced backup")

    # --- samples only the backup has -------------------------------------
    for row in crg_only:
        if row["w3w"] is None or row["date"] is None:
            continue
        uuid = f"crg:{row['uuid']}"
        conn.execute(
            "INSERT OR REPLACE INTO observations (ec5_uuid, sample_date, sample_time, w3w, "
            "location_status, recorder, landowner_raw, notes, photo_url, photo_2_url, "
            "photo_desc, excluded, exclude_reason, w3w_raw, crg_uuid, crg_status) "
            "VALUES (?,?,?,?,'located',NULL,NULL,?,NULL,NULL,NULL,0,NULL,NULL,?,'crg_only')",
            (uuid, row["date"], row["time"] or None, row["w3w"],
             row["comments"] or None, row["uuid"]),
        )
        for parameter, _ in CRG_FIELDS.items():
            crg_text = row["values"][parameter]
            if crg_text == "":
                continue
            if not trust_zeros and _as_number(crg_text) == 0:
                # Nothing to corroborate a bare zero against, so it is recorded
                # as no reading rather than as a measurement of zero.
                write_not_measured(conn, uuid, parameter, None, ["crg_zero_withheld"])
                continue
            cleaned = clean_value(crg_text, parameter)
            conn.execute(
                "INSERT OR REPLACE INTO measurements (ec5_uuid, parameter, value_raw, value, "
                "value_low, value_high, category, category_rank, qualifier, usable, flags) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (uuid, parameter, cleaned.value_raw, cleaned.value, cleaned.value_low,
                 cleaned.value_high, cleaned.category, cleaned.category_rank,
                 cleaned.qualifier, cleaned.usable,
                 json.dumps(sorted(set(cleaned.flags) | {"from_crg"}))),
            )
        stats["crg_only_added"] += 1
        log(uuid, None, "crg_sample_added", None, row["w3w"],
            "sample present in the georeferenced backup but not in the original data")

    for uuid in original_only:
        conn.execute(
            "UPDATE observations SET crg_status='original_only' WHERE ec5_uuid=?", (uuid,)
        )

    # A sample the backup has and the original does not, at the same place and
    # within a round or two of a sample the original has and the backup does
    # not, is more likely one visit dated differently in the two datasets than
    # two visits. Which it is depends on paper records, so it is queued rather
    # than decided here -- the same contract as every other ambiguity.
    stats["date_conflicts_queued"] = queue_date_conflicts(conn)
    stats["re_records_excluded"] = exclude_re_records(conn, run_at)
    conn.execute(
        "UPDATE observations SET crg_status='test_entry' WHERE location_status='test_entry'"
    )

    conn.commit()
    stats["per_parameter"] = {k: dict(v) for k, v in stats["per_parameter"].items()}
    return stats


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report(stats: dict) -> None:
    print("Georeferenced backup merged")
    print(f"  backup rows                {stats['crg_rows']}")
    print(f"  duplicate rows dropped     {stats['crg_duplicates_dropped']}")
    print(f"  samples matched            {stats['matched']}")
    print(f"  samples added from backup  {stats['crg_only_added']}")
    print(f"  samples the backup lacks   {stats['original_only_kept']} (kept)")
    print(f"  locations added            {stats['locations_added']}")
    print(f"  coordinates corrected      {stats['coordinate_updated']}")
    print(f"  samples moved to a new place {stats['location_changed']}")
    print(f"  readings replaced          {stats['readings_replaced']}")
    print(f"  readings added             {stats['readings_added']}")
    print(f"  zeros withheld             {stats['zeros_withheld']}")
    if stats.get("owner_decisions_kept"):
        print(f"  owner decisions left alone {stats['owner_decisions_kept']}")
    if stats.get("re_records_excluded"):
        print(f"  re-records excluded        {stats['re_records_excluded']}")
    if stats.get("date_conflicts_queued"):
        print(f"  possible date conflicts queued {stats['date_conflicts_queued']}")
    if stats["unlocated_rows"]:
        print(f"  backup rows with no known point {stats['unlocated_rows']}")
    if stats["per_parameter"]:
        print("  by parameter (replaced / zeros withheld):")
        for parameter, counts in sorted(stats["per_parameter"].items()):
            print(f"    {parameter:18} {counts['replaced']:4} / {counts['withheld']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="re-fetch the backup, then merge")
    ap.add_argument("--merge", action="store_true", help="merge from the stored backup")
    ap.add_argument("--from-file", help="load the backup from a cached JSON file")
    ap.add_argument("--report", action="store_true", help="show what a merge changed")
    ap.add_argument("--trust-zeros", action="store_true",
                    help="adopt the backup's zeros even where no reading was taken")
    args = ap.parse_args()

    init_v2_db()
    conn = get_connection()

    if args.report:
        rows = conn.execute(
            "SELECT action, COUNT(*) n FROM cleaning_log WHERE action LIKE 'crg_%' "
            "GROUP BY action ORDER BY n DESC"
        ).fetchall()
        for row in rows:
            print(f"  {row['action']:26} {row['n']}")
        conn.close()
        return 0

    if args.from_file:
        entries = json.loads(Path(args.from_file).read_text())
        print(f"Loaded {store_crg_raw(conn, entries)} backup entries from {args.from_file}")
    elif args.fetch:
        entries = fetch_crg()
        print(f"Fetched {store_crg_raw(conn, entries)} backup entries from EpiCollect")

    if not (args.fetch or args.from_file or args.merge):
        ap.error("choose --fetch, --from-file, --merge or --report")

    report(merge(conn, trust_zeros=args.trust_zeros or None))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
