#!/usr/bin/env python3
"""Report generator — calls Mistral API to generate site/round reports
and stores them in the database.

Called by the FastAPI backend when a report needs generating.

Usage:
  python3 report_generator.py --type site --site PW
  python3 report_generator.py --type round --round "Round 6"
"""

import argparse
import json
import os
import re
import smtplib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage

BP = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BP)

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

from database import get_connection
from llm_cleanup.report_prompts import SITE_ORDER_TEXT, SITE_ORDER_UPSTREAM_TO_DOWNSTREAM, SITE_REPORT_PROMPT, ROUND_REPORT_PROMPT, MONITORING_CONTEXT


def _strip_markdown(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[\*\-\+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\|", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _send_alert(subject, body):
    to = os.environ.get("ALERT_EMAIL_TO", "")
    host = os.environ.get("SMTP_HOST", "")
    user = os.environ.get("SMTP_USER", "")
    pw = os.environ.get("SMTP_PASS", "")
    if not (to and host and user and pw):
        return
    try:
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
    except Exception:
        pass


def query_mistral(system_prompt, user_prompt):
    if not MISTRAL_API_KEY:
        raise RuntimeError("MISTRAL_API_KEY environment variable not set")
    body = {
        "model": MISTRAL_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
    }
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        MISTRAL_API_URL, data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MISTRAL_API_KEY}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        if e.code in (402, 429):
            _send_alert(
                f"Mistral API error {e.code}",
                f"Mistral API returned status {e.code}.\n\nResponse: {error_body}\n\nTimestamp: {datetime.now(timezone.utc).isoformat()}",
            )
        raise RuntimeError(f"Mistral API error {e.code}: {error_body}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Mistral API unexpected response: {e}")


ALL_WFD = {
    "phosphate": "- Phosphate: High band ≤0.1, Good ≤0.2, Moderate ≤0.4, Poor ≤0.7 (mg/L)",
    "ammonia": "- Ammonia: High band ≤0.3, Good ≤0.6, Moderate ≤1.1, Poor ≤2.5 (mg/L)",
    "nitrate": "- Nitrate: High band ≤5.6, Good ≤11.3, Moderate ≤16.9, Poor ≤22.6 (mg/L)",
    "dissolved_oxygen": "- Dissolved oxygen: High band ≥7, Good ≥5, Moderate ≥4, Poor <4 (mg/L)",
    "turbidity": "- Turbidity: High band <5, Good <10, Moderate <20, Poor ≥20 (NTU)",
    "conductivity": "- Conductivity: typical range 300-1200 µS/cm",
}

def _present_chemicals(site_code):
    conn = get_connection()
    fields = ["phosphate_level", "ammonia_level", "nitrate_level",
              "dissolved_oxygen", "turbidity", "conductivity"]
    present = []
    for col in fields:
        row = conn.execute(
            f"SELECT 1 FROM entries WHERE w3w_site_code = ? AND {col} IS NOT NULL AND {col} != '' AND {col} != 'None' LIMIT 1",
            (site_code,)
        ).fetchone()
        if row:
            present.append(col)
    conn.close()
    return present

CHEM_KEY_MAP = {
    "phosphate_level": "phosphate", "ammonia_level": "ammonia",
    "nitrate_level": "nitrate", "dissolved_oxygen": "dissolved_oxygen",
    "turbidity": "turbidity", "conductivity": "conductivity",
}

def build_wfd_thresholds(site_code):
    present = _present_chemicals(site_code)
    keys = [CHEM_KEY_MAP[c] for c in present if c in CHEM_KEY_MAP]
    lines = [ALL_WFD[k] for k in keys if k in ALL_WFD]
    return "\n".join(lines)

def build_site_data(site_code):
    conn = get_connection()
    rows = conn.execute(
        "SELECT sample_date, phosphate_level, ammonia_level, nitrate_level, "
        "turbidity, dissolved_oxygen, conductivity, water_depth_cm, landowner, "
        "comments_1, comments_2, comments_3 "
        "FROM entries WHERE w3w_site_code = ? "
        "ORDER BY sample_date DESC",
        (site_code,)
    ).fetchall()
    conn.close()
    lines = []
    for r in rows:
        parts = [f"Date: {r[0]}"]
        if r[1]: parts.append(f"Phosphate: {r[1]}")
        if r[2]: parts.append(f"Ammonia: {r[2]}")
        if r[3]: parts.append(f"Nitrate: {r[3]}")
        if r[4]: parts.append(f"Turbidity: {r[4]}")
        if r[5]: parts.append(f"DO: {r[5]}")
        if r[6]: parts.append(f"Conductivity: {r[6]}")
        if r[7]: parts.append(f"Depth: {r[7]}")
        if r[8]: parts.append(f"Landowner: {r[8]}")
        if r[9]: parts.append(f"Notes: {r[9]}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def build_round_data(round_label, round_start, round_end):
    conn = get_connection()
    rows = conn.execute(
        "SELECT w3w_site_code, sample_date, phosphate_level, ammonia_level, "
        "nitrate_level, turbidity, dissolved_oxygen, conductivity "
        "FROM entries WHERE sample_date >= ? AND sample_date <= ? "
        "ORDER BY w3w_site_code, sample_date",
        (round_start, round_end)
    ).fetchall()

    chems = {"phosphate_level": [], "ammonia_level": [], "nitrate_level": [],
             "turbidity": [], "dissolved_oxygen": [], "conductivity": []}
    lines = []
    for r in rows:
        parts = [f"Site: {r[0]}", f"Date: {r[1]}"]
        for i, key in enumerate(["phosphate_level", "ammonia_level", "nitrate_level",
                                  "turbidity", "dissolved_oxygen", "conductivity"]):
            val = r[i + 2]
            if val:
                parts.append(f"{key}: {val}")
                try:
                    chems[key].append(float(val))
                except ValueError:
                    pass
        lines.append(" | ".join(parts))

    prev_rows = conn.execute(
        "SELECT sample_date FROM entries ORDER BY sample_date ASC LIMIT 1"
    ).fetchone()
    prev_start = prev_rows[0] if prev_rows else round_start
    prev_end = round_start

    prev_avg_rows = conn.execute(
        "SELECT AVG(CASE WHEN phosphate_level != '' THEN CAST(phosphate_level AS REAL) END), "
        "AVG(CASE WHEN ammonia_level != '' THEN CAST(ammonia_level AS REAL) END), "
        "AVG(CASE WHEN nitrate_level != '' THEN CAST(nitrate_level AS REAL) END), "
        "AVG(CASE WHEN turbidity != '' THEN CAST(turbidity AS REAL) END), "
        "AVG(CASE WHEN dissolved_oxygen != '' THEN CAST(dissolved_oxygen AS REAL) END), "
        "AVG(CASE WHEN conductivity != '' THEN CAST(conductivity AS REAL) END) "
        "FROM entries WHERE sample_date >= ? AND sample_date < ?",
        (prev_start, round_start)
    ).fetchone()

    conn.close()

    avg_line = ", ".join(f"{k}: {sum(v)/len(v):.3f}" if v else f"{k}: N/A"
                         for k, v in chems.items() if v)
    prev_line = (f"Previous period ({prev_start} to {prev_end}): "
                 f"Phosphate: {prev_avg_rows[0]:.3f}" if prev_avg_rows[0] else "N/A") + ", " + \
                (f"Ammonia: {prev_avg_rows[1]:.3f}" if prev_avg_rows[1] else "N/A") + ", " + \
                (f"Nitrate: {prev_avg_rows[2]:.3f}" if prev_avg_rows[2] else "N/A") + ", " + \
                (f"Turbidity: {prev_avg_rows[3]:.3f}" if prev_avg_rows[3] else "N/A") + ", " + \
                (f"DO: {prev_avg_rows[4]:.3f}" if prev_avg_rows[4] else "N/A") + ", " + \
                (f"Conductivity: {prev_avg_rows[5]:.3f}" if prev_avg_rows[5] else "N/A")

    return "\n".join(lines), avg_line, prev_line


def get_site_location_context(site_code):
    try:
        idx = SITE_ORDER_UPSTREAM_TO_DOWNSTREAM.index(site_code)
    except ValueError:
        return ""
    dirs = []
    if idx > 0:
        up_code = SITE_ORDER_UPSTREAM_TO_DOWNSTREAM[idx - 1]
        dirs.append(f"downstream of {up_code}")
    if idx < len(SITE_ORDER_UPSTREAM_TO_DOWNSTREAM) - 1:
        down_code = SITE_ORDER_UPSTREAM_TO_DOWNSTREAM[idx + 1]
        dirs.append(f"upstream of {down_code}")
    if dirs:
        return f"On the River Coln, this site is located {' and '.join(dirs)}."
    return ""


def _split_prompt(full_prompt):
    idx = full_prompt.find("## RULES")
    if idx != -1:
        return full_prompt[:idx], full_prompt[idx:]
    return full_prompt, ""


def _store_report(report_type, identifier, report_text, round_start=None, round_end=None):
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    version = None
    if report_type == "site":
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM site_reports WHERE site_code = ?",
            (identifier,)
        ).fetchone()
        version = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO site_reports (site_code, generated_at, report_text, version) VALUES (?, ?, ?, ?)",
            (identifier, now, report_text.strip(), version)
        )
    else:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM round_reports WHERE round_label = ?",
            (identifier,)
        ).fetchone()
        version = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO round_reports (round_label, round_start, round_end, generated_at, report_text, version) VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, round_start, round_end, now, report_text.strip(), version)
        )
    conn.commit()
    conn.close()
    return version


def generate_site_report(site_code, progress_callback=None):
    if progress_callback:
        progress_callback(5, "Building site data context")
    site_location_context = get_site_location_context(site_code)
    entries_text = build_site_data(site_code)
    wfd_thresholds = build_wfd_thresholds(site_code)
    full_prompt = SITE_REPORT_PROMPT.format(
        site_code=site_code, site_location_context=site_location_context,
        entries=entries_text, wfd_thresholds=wfd_thresholds,
        site_order=SITE_ORDER_TEXT, monitoring_context=MONITORING_CONTEXT
    )
    if progress_callback:
        progress_callback(10, "Data context ready")

    user_prompt, system_prompt = _split_prompt(full_prompt)

    if progress_callback:
        progress_callback(15, "Generating report via Mistral API")

    report_text = query_mistral(system_prompt, user_prompt)
    if not report_text:
        raise RuntimeError("Empty report generated")
    report_text = _strip_markdown(report_text)

    if progress_callback:
        progress_callback(90, "Saving to database")

    version = _store_report("site", site_code, report_text)

    if progress_callback:
        progress_callback(100, "Complete")
    return {"report_text": report_text, "version": version}


def generate_round_report(round_label, round_start, round_end, progress_callback=None):
    if progress_callback:
        progress_callback(5, "Building round data context")
    entries_text, avg_line, prev_line = build_round_data(round_label, round_start, round_end)
    full_prompt = ROUND_REPORT_PROMPT.format(
        round_label=round_label, round_start=round_start, round_end=round_end,
        entries=entries_text, averages=avg_line, previous_averages=prev_line,
        site_order=SITE_ORDER_TEXT, monitoring_context=MONITORING_CONTEXT,
    )
    if progress_callback:
        progress_callback(10, "Data context ready")

    user_prompt, system_prompt = _split_prompt(full_prompt)

    if progress_callback:
        progress_callback(15, "Generating report via Mistral API")

    report_text = query_mistral(system_prompt, user_prompt)
    if not report_text:
        raise RuntimeError("Empty report generated")
    report_text = _strip_markdown(report_text)

    if progress_callback:
        progress_callback(90, "Saving to database")

    version = _store_report("round", round_label, report_text, round_start, round_end)

    if progress_callback:
        progress_callback(100, "Complete")
    return {"report_text": report_text, "version": version}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, choices=["site", "round"])
    parser.add_argument("--site", help="Site code (for site reports)")
    parser.add_argument("--round-label", help="Round label")
    parser.add_argument("--round-start", help="Round start date")
    parser.add_argument("--round-end", help="Round end date")
    args = parser.parse_args()

    if args.type == "site":
        if not args.site:
            print("--site required for site reports", file=sys.stderr)
            sys.exit(1)
        report = generate_site_report(args.site)
        print(report["report_text"])
    else:
        if not all([args.round_label, args.round_start, args.round_end]):
            print("--round-label, --round-start, --round-end required", file=sys.stderr)
            sys.exit(1)
        report = generate_round_report(args.round_label, args.round_start, args.round_end)
        print(report["report_text"])


if __name__ == "__main__":
    main()
