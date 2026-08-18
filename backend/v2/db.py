"""v2 database access.

v2 gets its own SQLite file — `backend/coln_v2.db` — separate from v1's
`dashboard.db` (see V2_SPEC_ADDENDUM.md, Change 2: "v2 gets its own
SQLite file. Do not write into dashboard.db"). It holds a raw layer
(`raw_entries`), a derived layer (`locations`, `location_aliases`,
`observations`, `measurements`, `cleaning_log`) populated by
`v2/ingest.py` and `v2/cleaning.py` (owned separately), and v2's report
storage (`v2_reports`, `v2_report_jobs`).

`init_v2_db()` only ever does `CREATE TABLE IF NOT EXISTS` — it is always
safe to call, whether the database is empty, mid-ingest, or fully
populated, and never touches v1's `dashboard.db`.

The path can be overridden with the `V2_DB_PATH` environment variable,
which is how this module's own tests point at a scratch fixture database
instead of the real `backend/coln_v2.db` — useful while the ingest is
still landing, so `init_v2_db()` is never called against the real file
before it exists and has been populated.
"""

import os
import sqlite3

_DEFAULT_V2_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "coln_v2.db")
)
V2_DB_PATH = os.environ.get("V2_DB_PATH", _DEFAULT_V2_DB_PATH)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a connection to the v2 database (WAL journal mode, row access
    by column name — same conventions as v1's `database.get_connection()`
    and the original `v2/db.py`)."""
    conn = sqlite3.connect(db_path or V2_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_v2_db(db_path: str | None = None) -> None:
    """Idempotently create every v2 table. Safe to call on every startup.

    Table shapes for `raw_entries` / `locations` / `location_aliases` /
    `observations` / `measurements` / `cleaning_log` are copied verbatim
    from V2_SPEC_ADDENDUM.md — that schema is fixed and shared with
    `v2/ingest.py`, `v2/cleaning.py` and `v2/locations.py` (owned
    separately), so it is not this function's place to change it.
    `v2_reports` / `v2_report_jobs` are carried over from the original
    V2_SPEC.md, now living in this database instead of v1's.
    """
    conn = get_connection(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_entries (            -- exact API payload, NEVER mutated
                ec5_uuid TEXT PRIMARY KEY,
                created_at TEXT, uploaded_at TEXT,
                fetched_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS locations (               -- a place on the river
                w3w TEXT PRIMARY KEY,                            -- canonical, lowercase, dot-separated
                river_order INTEGER,                             -- MY_ID from LocationReferenceTable, 1 = furthest upstream
                latitude REAL, longitude REAL,
                source TEXT NOT NULL                             -- reference_table | unlocated
            );

            CREATE TABLE IF NOT EXISTS location_aliases (        -- every spelling seen in the data
                alias TEXT PRIMARY KEY,                          -- normalised form as submitted
                w3w TEXT NOT NULL,                               -- canonical location it resolves to
                match_type TEXT NOT NULL,                        -- exact | normalised | fuzzy | documented_rename
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS observations (            -- one row per sample visit
                ec5_uuid TEXT PRIMARY KEY,
                sample_date TEXT, sample_time TEXT,
                w3w TEXT,                                        -- canonical location; NULL if unresolved
                location_status TEXT NOT NULL,                   -- located | unlocated | test_entry
                recorder TEXT,                                   -- volunteer initials (NOT a place)
                landowner_raw TEXT, notes TEXT,
                photo_url TEXT, photo_2_url TEXT, photo_desc TEXT,
                excluded INTEGER NOT NULL DEFAULT 0, exclude_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS measurements (            -- one row per parameter per visit
                ec5_uuid TEXT NOT NULL,
                parameter TEXT NOT NULL,                         -- phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth
                value_raw TEXT,                                  -- EXACTLY as submitted, always kept
                value REAL,                                      -- NULL when not usable as a number
                qualifier TEXT NOT NULL,                         -- exact|range_midpoint|below_detection|zero_reported|non_numeric|absent
                usable INTEGER NOT NULL,                         -- 1 = safe to put in a statistic
                flags TEXT,                                      -- JSON array of strings
                PRIMARY KEY (ec5_uuid, parameter)
            );

            CREATE TABLE IF NOT EXISTS cleaning_log (            -- every single transformation, auditable
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ec5_uuid TEXT, parameter TEXT, action TEXT NOT NULL,
                value_before TEXT, value_after TEXT, reason TEXT, run_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_observations_date ON observations(sample_date);
            CREATE INDEX IF NOT EXISTS idx_observations_w3w ON observations(w3w);
            CREATE INDEX IF NOT EXISTS idx_measurements_parameter ON measurements(parameter);
            CREATE INDEX IF NOT EXISTS idx_location_aliases_w3w ON location_aliases(w3w);

            CREATE TABLE IF NOT EXISTS v2_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,      -- location|round|catchment|comparison|trend|data_quality
                report_key  TEXT NOT NULL,      -- w3w, round label, period label...
                audience    TEXT NOT NULL,
                version     INTEGER NOT NULL,
                status      TEXT NOT NULL,      -- ok|failed
                model       TEXT, provider TEXT,
                period_start TEXT, period_end TEXT,
                generated_at TEXT NOT NULL,
                report_json TEXT NOT NULL,      -- the structured report
                facts_json  TEXT NOT NULL,      -- the facts pack it was generated from
                verification_json TEXT NOT NULL,
                markdown    TEXT,
                trigger     TEXT                -- manual|scheduled|round_complete
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_reports_key
              ON v2_reports(report_type, report_key, audience, version);

            CREATE TABLE IF NOT EXISTS v2_report_jobs (
                id TEXT PRIMARY KEY,            -- uuid
                report_type TEXT, report_key TEXT, audience TEXT,
                state TEXT NOT NULL,            -- queued|running|done|failed
                progress INTEGER DEFAULT 0, message TEXT,
                created_at TEXT, started_at TEXT, finished_at TEXT,
                error TEXT, result_report_id INTEGER
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
