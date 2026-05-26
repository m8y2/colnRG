#!/usr/bin/env python3
"""Clean existing data in the dashboard database:
   - strip units (ppm, mg/L etc.)
   - fix typos (O→0, comma→period)
   - handle ranges (take midpoint)
   - map turbidity text to numeric
   - drop truly unparseable values
   - flag obvious decimal-shift outliers"""

import sqlite3, os
from clean import clean_numeric

DB_PATH = os.path.join(os.path.dirname(__file__), "dashboard.db")

OUTLIER_THRESHOLDS = {
    "phosphate_level": 10,
    "ammonia_level": 5,
    "nitrate_level": 200,
    "conductivity": 5000,
    "dissolved_oxygen": 30,
    "turbidity": 200,
    "water_depth_cm": 500,
}


def is_outlier(col, val):
    if val is None:
        return False
    return val > OUTLIER_THRESHOLDS.get(col, 1e9)


def fix_outlier(col, val):
    if val is None or val == 0:
        return None
    fixed = val / 100
    if not is_outlier(col, fixed):
        return round(fixed, 4)
    fixed = val / 10
    if not is_outlier(col, fixed):
        return round(fixed, 4)
    return None


def clean_table(conn, col):
    rows = conn.execute(
        f"SELECT id, {col} FROM entries WHERE {col} IS NOT NULL AND {col} != ''"
    ).fetchall()

    changed = 0
    for row in rows:
        raw = row[col]
        cleaned = clean_numeric(raw)

        if cleaned is None:
            if raw is not None and raw != "":
                conn.execute(f"UPDATE entries SET {col} = NULL WHERE id = ?", (row["id"],))
                changed += 1
        else:
            try:
                old_num = float(str(raw).strip())
            except ValueError:
                old_num = None

            if old_num is not None and is_outlier(col, old_num):
                fixed = fix_outlier(col, old_num)
                if fixed is not None and not is_outlier(col, fixed):
                    conn.execute(f"UPDATE entries SET {col} = ? WHERE id = ?", (str(fixed), row["id"]))
                    changed += 1
                    continue

            if old_num != cleaned:
                conn.execute(f"UPDATE entries SET {col} = ? WHERE id = ?", (str(cleaned), row["id"]))
                changed += 1

    return changed


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cols = list(OUTLIER_THRESHOLDS)
    total = 0
    for col in cols:
        n = clean_table(conn, col)
        if n:
            print(f"  {col}: {n} cleaned")
        total += n

    conn.commit()
    conn.close()
    print(f"\nDone — {total} values updated.")


if __name__ == "__main__":
    main()
