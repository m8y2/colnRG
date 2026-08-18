"""v2 database access.

Reuses the same SQLite file as v1 (`backend/config.DB_PATH`) but only ever
creates and touches v2's own tables (`v2_reports`, `v2_report_jobs`). v1's
tables (`entries`, `sync_log`, `site_reports`, `round_reports`, `api_keys`)
are read-only as far as v2 is concerned — v2 never writes to them, and
`init_v2_db()` uses `CREATE TABLE IF NOT EXISTS` so it is always safe to
call, even against a database v1's `init_db()` already created.
"""

import sqlite3

from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Open a connection to the shared dashboard database.

    Mirrors `backend/database.py`'s `get_connection()` (WAL journal mode,
    row access by column name) so v2 behaves the same way under concurrent
    access from the v1 process/tables.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_v2_db() -> None:
    """Idempotently create the two v2 tables described in the build spec.

    Safe to call on every startup and safe to call against a database that
    already has v1's tables in it — this only ever adds `v2_reports` and
    `v2_report_jobs`, and only if they are not already there.
    """
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS v2_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,      -- site|round|catchment|comparison|trend|data_quality
                report_key  TEXT NOT NULL,      -- site code, round label, period label...
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
