import time
import json
import re
import urllib.request
from datetime import datetime, timezone
from database import get_connection, get_last_sync
from clean import clean_numeric
from w3w_sites import lookup_w3w_site
from config import (
    EPICOLLECT_EXPORT, EPICOLLECT_PROJECT, FORM_REF,
    PER_PAGE, RATE_LIMIT_DELAY
)

SITE_CODE_MAP = {
    "EP": "",
    "PW": "",
    "SJR": "",
    "MG": "",
    "KH": "",
    "NL": "",
    "ST/LAT": "",
    "CS": "",
    "WMW": "",
    "GED": "",
    "DFG": "",
    "GDR": "",
    "CAK": "",
    "JD": "",
    "SM": "",
    "HB": "",
    "DD": "",
    "MH": "",
    "TJ": "",
    "RW": "",
    "PIC": "",
    "DC": "",
    "DK": "",
    "OB": "",
    "PT/M": "",
    "PT": "",
}

def extract_site_code(w3w_answer):
    if not w3w_answer:
        return None
    parts = w3w_answer.strip().split()
    if len(parts) >= 1:
        code = parts[-1]
        if code in SITE_CODE_MAP:
            return code
    return None


def strip_initials_from_w3w(w3w_answer):
    if not w3w_answer:
        return w3w_answer
    parts = w3w_answer.strip().split()
    if len(parts) >= 2 and parts[-1] in SITE_CODE_MAP:
        return " ".join(parts[:-1])
    return w3w_answer
    return None

def extract_site_code_other(w3w_other):
    if not w3w_other:
        return None
    cleaned = w3w_other.strip()
    cleaned = cleaned.replace("///", "").replace(",", ".")
    cleaned = cleaned.replace("(", "").replace(")", "")
    parts = cleaned.split()
    for part in parts:
        part_clean = part.strip(".,;:!?()").replace("/", "")
        if part_clean in SITE_CODE_MAP:
            return part_clean
    for part in parts:
        sub = part.rsplit(".", 1)
        if len(sub) > 1 and sub[-1] in SITE_CODE_MAP:
            return sub[-1]
    return lookup_w3w_site(w3w_other)

def build_headers():
    return {"User-Agent": "RiverGuardiansDashboard/1.0"}

def _fetch_json(url):
    req = urllib.request.Request(url, headers=build_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def fetch_project_definition():
    return _fetch_json(EPICOLLECT_PROJECT)

def fetch_entries_page(url):
    return _fetch_json(url)

FIELD_KEYS = {
    1: "1_What_are_your_What",
    2: "2_Placeholder",
    3: "3_Please_type_your_W",
    4: "4_Landowner_if_known",
    5: "5_What_is_the_date",
    6: "6_What_is_the_time",
    7: "7_Estimate_the_water",
    8: "8_What_is_the_phosph",
    9: "9_What_is_the_ammoni",
    10: "10_What_is_the_nitra",
    11: "11_What_is_the_turbi",
    12: "12_Dissolved_oxygen",
    13: "13_What_is_the_condu",
    14: "14_Is_the_phosphate_",
    15: "15_Is_the_nitrate_le",
    16: "16_Additional_Commen",
    17: "17_Add_a_photo_of_is",
    18: "18_Photo_Description",
    19: "19_Add_additional_ph",
    20: "20_Add_video_optiona",
    21: "21_Additional_Commen",
    22: "22_Additional_Commen",
}

def parse_entries(json_data):
    entries = json_data.get("data", {}).get("entries", [])

    parsed = []
    for entry in entries:
        w3w_answer = entry.get(FIELD_KEYS[1], "")
        site_code = extract_site_code(w3w_answer)

        w3w_other = entry.get(FIELD_KEYS[3], "")
        if not site_code and w3w_other:
            site_code = extract_site_code_other(w3w_other)

        parsed.append({
            "ec5_uuid": entry.get("ec5_uuid", ""),
            "created_at": entry.get("created_at", ""),
            "uploaded_at": entry.get("uploaded_at", ""),
            "title": entry.get("title", ""),
            "w3w": strip_initials_from_w3w(w3w_answer),
            "w3w_site_code": site_code,
            "w3w_other": w3w_other,
            "landowner": entry.get(FIELD_KEYS[4], ""),
            "sample_date": convert_date(entry.get(FIELD_KEYS[5], "")),
            "sample_time": entry.get(FIELD_KEYS[6], ""),
            "water_depth_cm": clean_numeric(entry.get(FIELD_KEYS[7], "")),
            "phosphate_level": clean_numeric(entry.get(FIELD_KEYS[8], "")),
            "ammonia_level": clean_numeric(entry.get(FIELD_KEYS[9], "")),
            "nitrate_level": clean_numeric(entry.get(FIELD_KEYS[10], "")),
            "turbidity": clean_numeric(entry.get(FIELD_KEYS[11], "")),
            "dissolved_oxygen": clean_numeric(entry.get(FIELD_KEYS[12], "")),
            "conductivity": clean_numeric(entry.get(FIELD_KEYS[13], "")),
            "phosphate_high": entry.get(FIELD_KEYS[14], ""),
            "nitrate_high": entry.get(FIELD_KEYS[15], ""),
            "comments_1": entry.get(FIELD_KEYS[16], ""),
            "photo_url": entry.get(FIELD_KEYS[17], ""),
            "photo_desc": entry.get(FIELD_KEYS[18], ""),
            "photo_2_url": entry.get(FIELD_KEYS[19], ""),
            "video_url": entry.get(FIELD_KEYS[20], ""),
            "comments_2": entry.get(FIELD_KEYS[21], ""),
            "comments_3": entry.get(FIELD_KEYS[22], ""),
            "latitude": None,
            "longitude": None,
        })
    return parsed

def convert_date(ddmmyyyy):
    if not ddmmyyyy:
        return ""
    parts = ddmmyyyy.strip().split("/")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return ddmmyyyy

def upsert_entries(parsed_entries):
    conn = get_connection()
    added = 0
    updated = 0

    for e in parsed_entries:
        existing = conn.execute(
            "SELECT id FROM entries WHERE ec5_uuid = ?", (e["ec5_uuid"],)
        ).fetchone()

        if existing:
            updated += 1
        else:
            conn.execute("""
                INSERT INTO entries (
                    ec5_uuid, created_at, uploaded_at, title, w3w, w3w_site_code,
                    w3w_other, landowner, sample_date, sample_time, water_depth_cm,
                    phosphate_level, ammonia_level, nitrate_level, turbidity,
                    dissolved_oxygen, conductivity, phosphate_high, nitrate_high,
                    comments_1, photo_url, photo_desc, photo_2_url, video_url,
                    comments_2, comments_3, latitude, longitude
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                e["ec5_uuid"], e["created_at"], e["uploaded_at"], e["title"],
                e["w3w"], e["w3w_site_code"], e["w3w_other"], e["landowner"],
                e["sample_date"], e["sample_time"], e["water_depth_cm"],
                e["phosphate_level"], e["ammonia_level"], e["nitrate_level"],
                e["turbidity"], e["dissolved_oxygen"], e["conductivity"],
                e["phosphate_high"], e["nitrate_high"], e["comments_1"],
                e["photo_url"], e["photo_desc"], e["photo_2_url"], e["video_url"],
                e["comments_2"], e["comments_3"], e["latitude"], e["longitude"]
            ))
            added += 1

    conn.commit()
    conn.close()
    return added, updated

def run_sync():
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO sync_log (started_at, status) VALUES (?, 'running')", (now,))
    sync_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    total_fetched = 0
    total_added = 0
    total_updated = 0

    try:
        last_sync = get_last_sync()
        page = 1

        while True:
            url = f"{EPICOLLECT_EXPORT}?form_ref={FORM_REF}&per_page={PER_PAGE}&page={page}"
            if last_sync:
                from_ = last_sync[:10]
                url += f"&filter_by=uploaded_at&filter_from={from_}&sort_order=ASC"

            data = fetch_entries_page(url)
            entries_data = data.get("data", {}).get("entries", [])
            if not entries_data:
                break

            total_fetched += len(entries_data)
            parsed = parse_entries({"data": {"entries": entries_data}})
            added, updated = upsert_entries(parsed)
            total_added += added
            total_updated += updated

            links = data.get("links", {})
            if not links.get("next"):
                break

            page += 1
            time.sleep(RATE_LIMIT_DELAY)

        conn = get_connection()
        conn.execute(
            """UPDATE sync_log SET
                completed_at = ?, entries_fetched = ?, entries_added = ?,
                entries_updated = ?, status = 'success'
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), total_fetched, total_added, total_updated, sync_id)
        )
        conn.commit()
        conn.close()

    except Exception as e:
        conn = get_connection()
        conn.execute(
            "UPDATE sync_log SET completed_at = ?, status = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), f"error: {str(e)}", sync_id)
        )
        conn.commit()
        conn.close()
        raise

    return {"entries_fetched": total_fetched, "entries_added": total_added, "entries_updated": total_updated}
