#!/usr/bin/env python3
"""Report generator — spins up an LLM droplet, generates a report,
stores it in the database, and destroys the droplet.

Called by the FastAPI backend when a report needs generating.

Usage:
  python3 report_generator.py --type site --site PW
  python3 report_generator.py --type round --round "Round 6"
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

BP = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, BP)

DO_API_TOKEN = os.environ.get("DO_API_TOKEN", "")
DROPLET_SNAPSHOT_ID = os.environ.get("DROPLET_SNAPSHOT_ID", "")
DROPLET_SIZE = os.environ.get("DROPLET_SIZE", "s-2vcpu-4gb-120gb-intel")
DROPLET_REGION = os.environ.get("DROPLET_REGION", "lon1")
SSH_KEY_FINGERPRINT = os.environ.get("SSH_KEY_FINGERPRINT", "56617052")
DO_API = "https://api.digitalocean.com/v2"

from config import PER_PAGE, RATE_LIMIT_DELAY
from database import get_connection
from llm_cleanup.report_prompts import SITE_REPORT_PROMPT, ROUND_REPORT_PROMPT


def do_headers():
    return {
        "Authorization": f"Bearer {DO_API_TOKEN}",
        "Content-Type": "application/json",
    }


def call_do(method, path, data=None):
    url = f"{DO_API}{path}"
    req = urllib.request.Request(url, headers=do_headers(), method=method)
    if data:
        req.data = json.dumps(data).encode()
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def spin_up_droplet():
    print("Spinning up LLM droplet for report generation...")
    config = {
        "name": f"report-llm-{int(time.time())}",
        "region": DROPLET_REGION,
        "size": DROPLET_SIZE,
        "image": DROPLET_SNAPSHOT_ID,
        "ssh_keys": [int(SSH_KEY_FINGERPRINT)] if SSH_KEY_FINGERPRINT and SSH_KEY_FINGERPRINT.isdigit() else [],
        "tags": ["report-llm", "ephemeral"],
        "monitoring": False,
    }
    result = call_do("POST", "/droplets", config)
    droplet_id = result["droplet"]["id"]
    print(f"  Droplet {droplet_id} created, waiting for IP...")
    try:
        start = time.time()
        while time.time() - start < 120:
            info = call_do("GET", f"/droplets/{droplet_id}")
            networks = info["droplet"].get("networks", {}).get("v4", [])
            for net in networks:
                if net.get("type") == "public":
                    ip = net["ip_address"]
                    print(f"  Droplet {droplet_id} ready at {ip} ({time.time() - start:.0f}s)")
                    return droplet_id, ip
            time.sleep(5)
        raise RuntimeError(f"Droplet {droplet_id} did not get an IP within 120s")
    except Exception:
        print(f"  Cleaning up droplet {droplet_id}...")
        try:
            call_do("DELETE", f"/droplets/{droplet_id}")
        except Exception:
            pass
        raise


def wait_for_ssh(ip, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             f"root@{ip}", "echo ready"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            print(f"  SSH ready after {time.time() - start:.0f}s")
            return True
        print(f"  Waiting for SSH... ({time.time() - start:.0f}s)")
        time.sleep(10)
    return False


def ensure_ollama(ip, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        r1 = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
             "systemctl is-active ollama 2>/dev/null || nohup ollama serve > /var/log/ollama-serve.log 2>&1 & echo started"],
            capture_output=True, text=True, timeout=30
        )
        for _ in range(15):
            time.sleep(2)
            r2 = subprocess.run(
                ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
                 "curl -s -o /dev/null -w '%{http_code}' http://localhost:11434/api/tags 2>/dev/null || echo 000"],
                capture_output=True, text=True, timeout=15
            )
            resp = r2.stdout.strip()
            if resp == "200":
                print(f"  Ollama ready after {time.time() - start:.0f}s")
                r3 = subprocess.run(
                    ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
                     "ollama list 2>/dev/null | grep -q llama3.2 || ollama pull llama3.2:1b"],
                    capture_output=True, text=True, timeout=300
                )
                print(f"  Model check done at {time.time() - start:.0f}s")
                return True
            print(f"  Waiting for Ollama... ({resp}, {time.time() - start:.0f}s)")
        print(f"  Ollama still not ready after {time.time() - start:.0f}s, retrying...")
    return False


def run_on_droplet(ip, command):
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}", command],
        capture_output=True, text=True, timeout=600
    )
    if r.stderr:
        print(r.stderr, file=sys.stderr)
    return r.returncode, r.stdout


def copy_to_droplet(ip, content, remote_path):
    p = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
         f"cat > {remote_path}"],
        input=content, text=True, timeout=30
    )
    return p.returncode


def copy_from_droplet(ip, remote_path):
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
         f"cat {remote_path}"],
        capture_output=True, text=True, timeout=30
    )
    return r.stdout


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

    # Calculate averages
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

    # Previous round averages
    prev_rows = conn.execute(
        "SELECT sample_date FROM entries ORDER BY sample_date ASC LIMIT 1"
    ).fetchone()
    prev_start = prev_rows[0] if prev_rows else round_start
    prev_end = round_start  # day before this round starts

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


def get_site_name(site_code):
    conn = get_connection()
    r = conn.execute(
        "SELECT DISTINCT w3w FROM entries WHERE w3w_site_code = ? AND w3w IS NOT NULL AND w3w != '' LIMIT 1",
        (site_code,)
    ).fetchone()
    conn.close()
    return r[0] if r else site_code


def generate_site_report(site_code, progress_callback=None, ip=None):
    if progress_callback:
        progress_callback(5, "Building site data context")
    site_name = get_site_name(site_code)
    entries_text = build_site_data(site_code)
    prompt = SITE_REPORT_PROMPT.format(site_code=site_code, site_name=site_name, entries=entries_text)
    if progress_callback:
        progress_callback(10, "Data context ready")
    if ip:
        return run_task_on_droplet(ip, "site", prompt, site_code, progress_callback=progress_callback)['report_text']
    return generate_report("site", prompt, site_code, progress_callback=progress_callback)['report_text']


def generate_round_report(round_label, round_start, round_end, progress_callback=None, ip=None):
    if progress_callback:
        progress_callback(5, "Building round data context")
    entries_text, avg_line, prev_line = build_round_data(round_label, round_start, round_end)
    prompt = ROUND_REPORT_PROMPT.format(
        round_label=round_label, round_start=round_start, round_end=round_end,
        entries=entries_text, averages=avg_line, previous_averages=prev_line,
    )
    if progress_callback:
        progress_callback(10, "Data context ready")
    if ip:
        return run_task_on_droplet(ip, "round", prompt, f"{round_label}|{round_start}|{round_end}", progress_callback=progress_callback)['report_text']
    return generate_report("round", prompt, round_label, progress_callback=progress_callback)['report_text']


def run_task_on_droplet(ip, report_type, prompt, identifier, progress_callback=None):
    """Run a single report generation task on an already-set-up droplet (no SSH/Ollama checks)."""
    worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_worker.py")
    request = json.dumps({"type": report_type, "prompt": prompt})

    if progress_callback:
        progress_callback(45, "Copying data to droplet")

    copy_to_droplet(ip, open(worker_script).read(), "/root/report_worker.py")
    copy_to_droplet(ip, request, "/root/request.json")

    if progress_callback:
        progress_callback(55, "Generating report via LLM")

    ret, stdout = run_on_droplet(ip, "cd /root && python3 report_worker.py < request.json > report.txt")
    if ret != 0:
        raise RuntimeError(f"Worker exited with code {ret}")

    if progress_callback:
        progress_callback(85, "Retrieving results")

    report_text = copy_from_droplet(ip, "/root/report.txt")
    if not report_text.strip():
        raise RuntimeError("Empty report generated")

    if progress_callback:
        progress_callback(92, "Saving to database")

    # Store in database
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
        parts = identifier.split("|")
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM round_reports WHERE round_label = ?",
            (parts[0],)
        ).fetchone()
        version = (row[0] or 0) + 1
        conn.execute(
            "INSERT INTO round_reports (round_label, round_start, round_end, generated_at, report_text, version) VALUES (?, ?, ?, ?, ?, ?)",
            (parts[0], parts[1], parts[2], now, report_text.strip(), version)
        )
    conn.commit()
    conn.close()

    print(f"  Stored version {version} for {report_type} report '{identifier}'")
    return {"report_text": report_text.strip(), "version": version}


def generate_report(report_type, prompt, identifier, progress_callback=None):
    """Standalone: spin droplet, run task, destroy droplet. Used by CLI."""
    worker_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_worker.py")
    request = json.dumps({"type": report_type, "prompt": prompt})

    if progress_callback:
        progress_callback(12, "Spinning up droplet")

    droplet_id, ip = spin_up_droplet()
    try:
        if progress_callback:
            progress_callback(25, "Droplet ready, waiting for SSH")
        if not wait_for_ssh(ip):
            raise RuntimeError("SSH timeout")
        if progress_callback:
            progress_callback(35, "SSH connected, waiting for Ollama")
        if not ensure_ollama(ip):
            raise RuntimeError("Ollama not ready")

        result = run_task_on_droplet(ip, report_type, prompt, identifier, progress_callback=progress_callback)

        if progress_callback:
            progress_callback(97, "Destroying droplet")
        print(f"Destroying droplet {droplet_id}...")
        try:
            call_do("DELETE", f"/droplets/{droplet_id}")
        except Exception:
            pass

        return result

    except Exception:
        print(f"Destroying droplet {droplet_id} after error...")
        try:
            call_do("DELETE", f"/droplets/{droplet_id}")
        except Exception:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True, choices=["site", "round"])
    parser.add_argument("--site", help="Site code (for site reports)")
    parser.add_argument("--round-label", help="Round label")
    parser.add_argument("--round-start", help="Round start date")
    parser.add_argument("--round-end", help="Round end date")
    args = parser.parse_args()

    if not DO_API_TOKEN:
        print("DO_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if args.type == "site":
        if not args.site:
            print("--site required for site reports", file=sys.stderr)
            sys.exit(1)
        report = generate_site_report(args.site)
        print(report)
    else:
        if not all([args.round_label, args.round_start, args.round_end]):
            print("--round-label, --round-start, --round-end required", file=sys.stderr)
            sys.exit(1)
        report = generate_round_report(args.round_label, args.round_start, args.round_end)
        print(report)


if __name__ == "__main__":
    main()
