import sqlite3
import os
from config import DB_PATH

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ec5_uuid TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            title TEXT,
            w3w TEXT,
            w3w_site_code TEXT,
            w3w_other TEXT,
            landowner TEXT,
            sample_date TEXT,
            sample_time TEXT,
            water_depth_cm REAL,
            phosphate_level TEXT,
            ammonia_level TEXT,
            nitrate_level TEXT,
            turbidity TEXT,
            dissolved_oxygen TEXT,
            conductivity TEXT,
            phosphate_high TEXT,
            nitrate_high TEXT,
            comments_1 TEXT,
            photo_url TEXT,
            photo_desc TEXT,
            photo_2_url TEXT,
            video_url TEXT,
            comments_2 TEXT,
            comments_3 TEXT,
            latitude REAL,
            longitude REAL
        );

        CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(sample_date);
        CREATE INDEX IF NOT EXISTS idx_entries_site ON entries(w3w_site_code);
        CREATE INDEX IF NOT EXISTS idx_entries_uploaded ON entries(uploaded_at);

        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            entries_fetched INTEGER DEFAULT 0,
            entries_added INTEGER DEFAULT 0,
            entries_updated INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        );

        CREATE TABLE IF NOT EXISTS site_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_code TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            report_text TEXT NOT NULL,
            version INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS round_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_label TEXT NOT NULL,
            round_start TEXT NOT NULL,
            round_end TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            report_text TEXT NOT NULL,
            version INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_site_reports ON site_reports(site_code, version);
        CREATE INDEX IF NOT EXISTS idx_round_reports ON round_reports(round_label, version);
    """)
    conn.commit()
    conn.close()

def get_last_sync():
    conn = get_connection()
    row = conn.execute(
        "SELECT completed_at FROM sync_log WHERE status = 'success' ORDER BY completed_at DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["completed_at"] if row else None
