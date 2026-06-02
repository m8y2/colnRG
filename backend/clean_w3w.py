"""Strip site-code suffixes from w3w column — run from /opt/coln-dashboard/"""

import sqlite3

VALID_CODES = {
    "EP", "PW", "SJR", "MG", "KH", "NL", "ST/LAT", "CS", "WMW",
    "GED", "DFG", "GDR", "CAK", "JD", "SM", "HB", "DD", "MH",
    "TJ", "RW", "PIC", "DC", "DK", "OB", "PT/M", "PT",
}

DB = "backend/dashboard.db"

conn = sqlite3.connect(DB)
rows = conn.execute("SELECT DISTINCT w3w FROM entries WHERE w3w IS NOT NULL AND w3w != ''").fetchall()

to_update = {}
for (w3w,) in rows:
    parts = w3w.strip().split()
    if len(parts) >= 2 and parts[-1] in VALID_CODES:
        clean = " ".join(parts[:-1])
        if clean != w3w:
            to_update[w3w] = clean

if to_update:
    for old, new in sorted(to_update.items()):
        print(f"  [{old}] -> [{new}]")
    conn.execute("BEGIN")
    for old, new in to_update.items():
        conn.execute("UPDATE entries SET w3w = ? WHERE w3w = ?", (new, old))
    conn.execute("COMMIT")
    print(f"\nCleaned {len(to_update)} values.")
else:
    print("Nothing to clean.")
conn.close()
