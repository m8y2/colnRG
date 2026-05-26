#!/usr/bin/env python3
"""Assign site codes to entries that have missing site codes, using
the w3w_sites lookup table derived from LocationReferenceTable.xlsx.

Also cleans test/non-location entries (marked as unverified).
"""

import os
import sqlite3
from w3w_sites import lookup_w3w_site

DB_PATH = os.path.join(os.path.dirname(__file__), "dashboard.db")


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, w3w, w3w_other, title, landowner, sample_date "
        "FROM entries WHERE w3w_site_code IS NULL OR w3w_site_code = '???'"
    ).fetchall()

    assigned = 0
    unverified = 0

    for r in rows:
        site_code = None

        w3w_other = r["w3w_other"]
        w3w = r["w3w"]
        landowner = r["landowner"]
        title = r["title"]

        if w3w_other:
            site_code = lookup_w3w_site(w3w_other)

        if site_code:
            conn.execute(
                "UPDATE entries SET w3w_site_code = ? WHERE id = ?",
                (site_code, r["id"])
            )
            assigned += 1
            print(f"  id={r['id']:>3} {r['sample_date']} → {site_code:6s} ({w3w_other})")
        else:
            conn.execute(
                "UPDATE entries SET w3w_site_code = '???' WHERE id = ?",
                (r["id"],)
            )
            unverified += 1
            print(f"  id={r['id']:>3} {r['sample_date']} → ??? (unverified: w3w={w3w!r} other={w3w_other!r})")

    conn.commit()
    conn.close()
    print(f"\nAssigned: {assigned}, Unverified: {unverified}")


if __name__ == "__main__":
    main()
