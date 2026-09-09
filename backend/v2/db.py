"""v2 database access.

v2 gets its own SQLite file — `backend/coln_v2.db` — separate from v1's
`dashboard.db` (see V2_SPEC_ADDENDUM.md, Change 2: "v2 gets its own
SQLite file. Do not write into dashboard.db"). It holds a raw layer
(`raw_entries`), a derived layer (`locations`, `location_aliases`,
`observations`, `measurements`, `cleaning_log`, `review_queue`,
`manual_corrections` — the last two added by V2_SPEC_ADDENDUM_2.md)
populated by `v2/ingest.py` and `v2/cleaning.py` (owned separately), and
v2's report storage (`v2_reports`, `v2_report_jobs`).

`init_v2_db()` only ever does `CREATE TABLE IF NOT EXISTS`, plus a
defensive `ALTER TABLE ... ADD COLUMN` for any column Addendum 2 added to
`measurements` on a database that already existed under the Addendum-1
shape — it is always safe to call, whether the database is empty,
mid-ingest, or fully populated, and never touches v1's `dashboard.db` or
drops/rewrites existing data.

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


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add any of `columns` (name -> SQL type) that don't already exist on
    `table`, via `ALTER TABLE ... ADD COLUMN`. Lets `init_v2_db()` stay
    idempotent even against a database created under an earlier schema
    version (e.g. before Addendum 2 added `measurements.category` etc.),
    without ever touching a row of existing data."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def init_v2_db(db_path: str | None = None) -> None:
    """Idempotently create every v2 table. Safe to call on every startup.

    Table shapes for `raw_entries` / `locations` / `location_aliases` /
    `observations` / `measurements` / `cleaning_log` / `review_queue` /
    `manual_corrections` are copied verbatim from V2_SPEC_ADDENDUM.md and
    V2_SPEC_ADDENDUM_2.md — that schema is fixed and shared with
    `v2/ingest.py`, `v2/cleaning.py` and `v2/locations.py` (owned
    separately), so it is not this function's place to change it.
    `v2_reports` / `v2_report_jobs` are carried over from the original
    V2_SPEC.md, now living in this database instead of v1's.
    """
    conn = get_connection(db_path)
    try:
        # photo_cache gained a `modified` column after the table first
        # shipped; older databases need it added, fresh ones have it in
        # the CREATE below.
        try:
            conn.execute(
                "ALTER TABLE photo_cache ADD COLUMN modified INTEGER NOT NULL DEFAULT 0"
            )
        except Exception:
            pass  # already present
        try:
            conn.execute(
                "ALTER TABLE photo_cache ADD COLUMN valid INTEGER NOT NULL DEFAULT 1"
            )
        except Exception:
            pass  # already present
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
                river_order REAL,                                -- MY_ID from LocationReferenceTable, 1 = furthest upstream;
                                                                  -- REAL, not INTEGER — 4 supplement points were placed by
                                                                  -- projecting onto the reference polyline and take
                                                                  -- fractional values between existing MY_IDs (e.g. 15.98).
                                                                  -- Never cast this to int for display; use rank position
                                                                  -- in the ordered sequence for "point N" phrasing instead.
                latitude REAL, longitude REAL,
                source TEXT NOT NULL                             -- reference_table | supplement | unlocated
                                                                  -- supplement = coordinates not supplied by the owner;
                                                                  -- looked up separately (e.g. public what3words lookup)
                                                                  -- for a real address missing from the reference table.
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

            -- value_low/value_high (band_range readings) and
            -- category/category_rank (ordinal readings) added by
            -- V2_SPEC_ADDENDUM_2.md. usable=1 no longer implies value IS
            -- NOT NULL: an ordinal row has value=NULL and category set.
            CREATE TABLE IF NOT EXISTS measurements (            -- one row per parameter per visit
                ec5_uuid TEXT NOT NULL,
                parameter TEXT NOT NULL,                         -- phosphate|ammonia|nitrate|turbidity|dissolved_oxygen|conductivity|water_depth
                value_raw TEXT,                                  -- EXACTLY as submitted, always kept
                value REAL,                                      -- NULL when not usable as a number (incl. ordinal rows)
                value_low REAL,                                  -- band_range: lower bound
                value_high REAL,                                 -- band_range: upper bound
                category TEXT,                                   -- ordinal: e.g. 'clear'
                category_rank INTEGER,                           -- ordinal: position on the scale
                qualifier TEXT NOT NULL,                         -- exact|range_midpoint|below_detection|zero_reported|non_numeric|absent|ordinal|band_range
                usable INTEGER NOT NULL,                         -- 1 = safe to put in a statistic (numeric OR ordinal)
                flags TEXT,                                      -- JSON array of strings
                PRIMARY KEY (ec5_uuid, parameter)
            );

            CREATE TABLE IF NOT EXISTS cleaning_log (            -- every single transformation, auditable
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ec5_uuid TEXT, parameter TEXT, action TEXT NOT NULL,
                value_before TEXT, value_after TEXT, reason TEXT, run_at TEXT NOT NULL
            );

            -- Added by V2_SPEC_ADDENDUM_2.md Rule D: nothing ambiguous is
            -- silently dropped or silently guessed. `suggestion` is
            -- displayed to the owner, never auto-applied.
            CREATE TABLE IF NOT EXISTS review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ec5_uuid TEXT NOT NULL, parameter TEXT,
                value_raw TEXT NOT NULL,
                issue TEXT NOT NULL,            -- ambiguous_decimal | unparseable | implausible | ambiguous_location | multi_value
                suggestion TEXT,                -- proposed interpretation, NEVER auto-applied
                suggestion_reason TEXT,
                status TEXT NOT NULL DEFAULT 'open',   -- open | accepted | rejected
                resolved_value TEXT, resolved_at TEXT, resolved_by TEXT
            );

            -- The only route by which a human judgement enters the data:
            -- applied during `--refresh`, after automatic cleaning, and
            -- every application writes a cleaning_log row. Never written
            -- to directly by the API except via POST /review-queue/{id}.
            CREATE TABLE IF NOT EXISTS manual_corrections (
                ec5_uuid TEXT NOT NULL, parameter TEXT NOT NULL,
                value TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL,
                PRIMARY KEY (ec5_uuid, parameter)
            );

            -- The owner's decisions on review_queue items. Survives every
            -- rebuild (unlike review_queue itself), and each kind is
            -- applied during the rebuild with a cleaning_log row:
            --   value        -> numeric reading applied to measurements
            --   not_measured -> reading marked absent (usable=0)
            --   category     -> ordinal category applied (value=NULL)
            --   remove       -> the measurements row is deleted
            --   merge        -> observations for `value_raw` (a what3words
            --                   address) are moved to `resolved_value`
            --                   (the canonical address) and the duplicate
            --                   location row is dropped
            -- Resolved items are NOT re-queued on rebuild.
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ec5_uuid TEXT NOT NULL,
                parameter TEXT,                 -- NULL for location merges
                value_raw TEXT NOT NULL,
                issue TEXT NOT NULL,
                kind TEXT NOT NULL,             -- value|not_measured|category|remove|merge
                resolved_value TEXT,
                note TEXT,
                resolved_at TEXT NOT NULL,
                resolved_by TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_review_decisions_lookup
                ON review_decisions(ec5_uuid, parameter);

            -- Photo processing cache (see v2/photo_crop.py): which
            -- original EpiCollect URL each processed photo came from, so
            -- the media endpoint can process on demand. `modified` says
            -- whether processing changed the photo (cropped or manually
            -- rotated) — the demo build embeds those as data URIs so the
            -- offline copy shows the corrected image too. `valid` says
            -- the photo passed placeholder screening (0 = "photo not
            -- synced" placeholder, never served). Both survive rebuilds
            -- and are loaded at startup so a restart does not briefly
            -- re-show known placeholders.
            CREATE TABLE IF NOT EXISTS photo_cache (
                sha TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                modified INTEGER NOT NULL DEFAULT 0,
                valid INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_observations_date ON observations(sample_date);
            CREATE INDEX IF NOT EXISTS idx_observations_w3w ON observations(w3w);
            CREATE INDEX IF NOT EXISTS idx_measurements_parameter ON measurements(parameter);
            CREATE INDEX IF NOT EXISTS idx_location_aliases_w3w ON location_aliases(w3w);
            CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);

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
        # Defensive migration for a database created before Addendum 2:
        # a no-op on any database created fresh from the script above,
        # since those columns are already there.
        _ensure_columns(conn, "measurements", {
            "value_low": "REAL",
            "value_high": "REAL",
            "category": "TEXT",
            "category_rank": "INTEGER",
        })
        # The what3words exactly as submitted. Kept alongside the resolved
        # `w3w` so a reader can always see what the volunteer actually wrote
        # -- and so an unresolved address is still visible rather than lost.
        _ensure_columns(conn, "observations", {
            "w3w_raw": "TEXT",
        })
        conn.commit()
    finally:
        conn.close()
