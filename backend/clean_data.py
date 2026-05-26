#!/usr/bin/env python3
"""Thorough data cleaning for the River Guardians dashboard.

Fixes:
- Decimal-shift outliers in numeric fields (by site-specific distribution)
- Landowner name standardisation
- Typos in text fields (Wittington → Whittington)
- Strips non-landowner values (N/A, Yes, site codes, etc.)
- Strips Nil/N/A from comment fields
"""

import sqlite3
import os
from statistics import median
from clean import clean_numeric

DB_PATH = os.path.join(os.path.dirname(__file__), "dashboard.db")

# ── Landowner standardisation ──────────────────────────────────────────

LANDOWNER_CLEAN = {
    # Whittington Estate variations
    "Whittington Estate": "Whittington Estate",
    "Wittington Eastates": "Whittington Estate",
    "Wittington Estate": "Whittington Estate",
    "Wittington Estates": "Whittington Estate",
    "Wittington estate": "Whittington Estate",

    # Rupert Lowe variations
    "Rupert Lowe": "Rupert Lowe",
    "N Lowe": "Rupert Lowe",
    "N.Lowe": "Rupert Lowe",
    "Ravenswell Farm Rupert Lowe": "Rupert Lowe",
    "Ravenswell Lowe": "Rupert Lowe",
    "Ravenswell Rupert Lowe": "Rupert Lowe",
    "Rupert Lowe Ravenswell Farm": "Rupert Lowe",

    # Rose Vestey variations
    "Rose Vestey": "Rose Vestey",
    "Rosie Vestey": "Rose Vestey",
    "Vestey": "Rose Vestey",
    "Vestey estate": "Rose Vestey",
    "Vestry Estate": "Rose Vestey",
    "Vesty": "Rose Vestey",

    # Chris Daniels variations
    "Chris Daniels": "Chris Daniels",
    "Chris Daniels Rectory": "Chris Daniels",
    "Chris Daniels The Old Rectory": "Chris Daniels",
    "Chis Daniels": "Chris Daniels",
    "C.Daniels": "Chris Daniels",
    "Chris.Daniels": "Chris Daniels",
    "Daniels": "Chris Daniels",

    # Stowell Park variations
    "Stowell Park": "Stowell Park",
    "Stowell Park Estate": "Stowell Park",

    # National Trust
    "National Trust": "National Trust",
    "National trust": "National Trust",

    # Chris Wright
    "Chris Wright": "Chris Wright",
    "Mr Chris Wright": "Chris Wright",

    # Bruno / Blackwell — keep as-is
}

# Values that are NOT landowner names — set to None
NON_LANDOWNERS = {
    "MH", "OB", "Mixed", "Public", "Public access", "Public bridal path",
    "Various as runs through the village and peoples gardens",
    "n/a Shipton Village", "n/a Shipton village",
}

NON_LANDOWNER_NA = {"N/A", "N/A ", "N.A", "N/a", "n/a", "N/K", "Yes", "not known"}

# ── Numeric outlier detection ──────────────────────────────────────────

REALISTIC_MAX = {
    "phosphate_level": 1.5,
    "ammonia_level": 2.5,
    "nitrate_level": 150,
    "turbidity": 200,
    "conductivity": 3000,
    "dissolved_oxygen": 30,
    "water_depth_cm": 500,
}


def get_site_stats(conn, col):
    """Compute median per site for a numeric column."""
    rows = conn.execute(f"""
        SELECT w3w_site_code, CAST({col} AS REAL) as val
        FROM entries
        WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
          AND w3w_site_code IS NOT NULL AND w3w_site_code != ''
          AND w3w_site_code != '???'
    """).fetchall()

    site_vals = {}
    for r in rows:
        site = r["w3w_site_code"]
        try:
            v = float(r["val"])
        except (ValueError, TypeError):
            continue
        site_vals.setdefault(site, []).append(v)

    site_medians = {}
    for site, vals in site_vals.items():
        site_medians[site] = median(vals)
    return site_medians


def clean_numeric_outliers(conn, col):
    """Find decimal-shift outliers using site-relative thresholds."""
    site_medians = get_site_stats(conn, col)

    rows = conn.execute(f"""
        SELECT id, {col}, w3w_site_code
        FROM entries
        WHERE {col} IS NOT NULL AND {col} != '' AND {col} != 'None'
    """).fetchall()

    changed = 0
    for r in rows:
        raw = r[col]
        try:
            val = float(str(raw).strip())
        except (ValueError, TypeError):
            continue

        if val == 0:
            continue

        site = r["w3w_site_code"]
        if site and site in site_medians:
            site_mid = site_medians[site]
        else:
            site_mid = 0.1

        if site_mid == 0:
            site_mid = 0.1

        realistic = REALISTIC_MAX.get(col, 100)
        if val < realistic:
            continue

        ratio = val / site_mid if site_mid > 0 else 999

        # Check if dividing by 10 produces a reasonable value
        fixed = val / 10

        # Fix if: value is far above site median, OR globally excessive
        if ratio >= 5 or (fixed < realistic and fixed < site_mid * 3):
            conn.execute(
                f"UPDATE entries SET {col} = ? WHERE id = ?",
                (str(round(fixed, 4)), r["id"])
            )
            print(f"    id={r['id']:>4} {site:6s} {col}: {val} → {round(fixed, 4)}")
            changed += 1

    return changed


# ── Landowner cleaning ────────────────────────────────────────────────

def clean_landowners(conn):
    rows = conn.execute(
        "SELECT id, landowner FROM entries WHERE landowner IS NOT NULL AND landowner != ''"
    ).fetchall()

    changed = 0
    for r in rows:
        raw = r["landowner"].strip()
        cleaned = None

        low = raw.lower()

        # Non-landowner values
        if raw in NON_LANDOWNERS or low in {x.lower() for x in NON_LANDOWNERS}:
            cleaned = None
        elif raw in NON_LANDOWNER_NA or low in {x.lower() for x in NON_LANDOWNER_NA}:
            cleaned = None
        elif raw in LANDOWNER_CLEAN:
            cleaned = LANDOWNER_CLEAN[raw]
        elif raw not in LANDOWNER_CLEAN:
            # Try case-insensitive match
            matched = False
            for key, val in LANDOWNER_CLEAN.items():
                if key.lower() == low:
                    cleaned = val
                    matched = True
                    break
            if not matched:
                continue

        if cleaned != raw:
            conn.execute(
                "UPDATE entries SET landowner = ? WHERE id = ?",
                (cleaned, r["id"])
            )
            if cleaned is None:
                print(f"    id={r['id']:>4} landowner: {raw!r} → NULL")
            else:
                print(f"    id={r['id']:>4} landowner: {raw!r} → {cleaned!r}")
            changed += 1

    return changed


# ── Text / comment typos ──────────────────────────────────────────────

def fix_text_typos(conn):
    """Fix known typos across all text columns."""
    replacements = [
        ("Wittington", "Whittington"),
        ("Wittington Eastates", "Whittington Estate"),
        ("w3w_site_code = '???' AND w3w_other LIKE '%Wittington%'", None),
    ]

    for col in ["comments_1", "comments_2", "comments_3", "title",
                 "w3w_other", "landowner", "photo_desc"]:
        rows = conn.execute(
            f"SELECT id, {col} FROM entries WHERE {col} LIKE '%Wittington%'"
        ).fetchall()
        for r in rows:
            fixed = r[col].replace("Wittington", "Whittington")
            conn.execute(f"UPDATE entries SET {col} = ? WHERE id = ?", (fixed, r["id"]))
            print(f"    id={r['id']:>4} {col}: Wittington → Whittington")


def strip_nil_na(conn):
    """Set 'Nil' / 'N/A' comment fields to NULL."""
    for col in ["comments_1", "comments_2", "comments_3"]:
        rows = conn.execute(
            f"SELECT id, {col} FROM entries WHERE {col} IN ('Nil', 'N/A', 'n/a', 'N/A ', 'None')"
        ).fetchall()
        for r in rows:
            conn.execute(f"UPDATE entries SET {col} = NULL WHERE id = ?", (r["id"],))
            print(f"    id={r['id']:>4} {col}: {r[col]!r} → NULL")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print("=== Numeric outlier cleanup ===")
    for col in ["phosphate_level", "ammonia_level", "nitrate_level",
                "turbidity", "conductivity", "dissolved_oxygen"]:
        n = clean_numeric_outliers(conn, col)
        if n:
            print(f"  {col}: {n} fixed")

    print("\n=== Landowner cleanup ===")
    n = clean_landowners(conn)
    print(f"  {n} landowner values updated")

    print("\n=== Text typo fixes ===")
    fix_text_typos(conn)

    print("\n=== Stripping Nil/N/A from comment fields ===")
    strip_nil_na(conn)

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
