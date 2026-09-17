#!/usr/bin/env python3
"""Hourly refresh: re-fetch both EpiCollect sources, rebuild, re-merge.

Runs `v2.ingest --fetch` (original data) then a fresh `v2.crg_georef`
fetch + merge (the owner's georeferenced/QAed backup, which wins
per-sample where it has a match -- see V2.md "The georeferenced
backup"). Both together are what `python -m v2.ingest --fetch` alone
does not cover: it only re-applies whatever backup was already stored,
not a fresh fetch of it.

Guards against exactly the failure this caught once already: EpiCollect
regenerates a question's field key when it's edited in the form builder
(happened 2026-07-28), which makes the parser silently misread every
entry as unlocated/unmeasured. `ingest.rebuild()` commits internally, so
a bad rebuild is already on disk by the time its counts can be checked
-- caught here by restoring the pre-refresh copy over it, rather than
leaving a broken database live. Exits non-zero so the timer's failure
shows in `systemctl status`.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from v2 import crg_georef, ingest
from v2.db import V2_DB_PATH, get_connection, init_v2_db

MIN_LOCATED_FRACTION = 0.9  # refuse a rebuild that locates fewer than 90% of entries


def _restore(db_path: Path, backup_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    shutil.copy2(backup_path, db_path)


def main() -> int:
    db_path = Path(V2_DB_PATH)
    backup_path = db_path.with_suffix(".db.pre-refresh")
    had_existing = db_path.exists()
    if had_existing:
        shutil.copy2(db_path, backup_path)

    init_v2_db()
    conn = get_connection()
    entries = ingest.fetch_entries()
    ingest.store_raw(conn, entries)
    stats = ingest.rebuild(conn)  # commits internally

    total, located = stats["entries"], stats["located"]
    if total and located / total < MIN_LOCATED_FRACTION:
        conn.close()
        if had_existing:
            _restore(db_path, backup_path)
        print(
            f"REFUSED: only {located}/{total} entries located "
            f"(<{MIN_LOCATED_FRACTION:.0%}) -- likely an EpiCollect form field "
            "key change (see v2/ingest.py's F_* / PARAM_FIELDS comment). "
            "Previous database restored.",
            file=sys.stderr,
        )
        return 1

    crg_backup = crg_georef.fetch_crg()
    crg_georef.store_crg_raw(conn, crg_backup)
    crg_georef.report(crg_georef.merge(conn))  # commits internally
    conn.close()

    ingest.report(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
