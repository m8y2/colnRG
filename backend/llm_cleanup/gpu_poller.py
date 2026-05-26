#!/usr/bin/env python3
"""Polling orchestrator — runs on the main $6 droplet.

Workflow:
1. Fetch new entries from EpiCollect5 API
2. If new entries exist, spin up a GPU droplet via DigitalOcean API
3. Copy raw data + worker script to GPU droplet
4. SSH in and run gpu_worker.py
5. Copy cleaned results back
6. Insert cleaned entries into SQLite
7. Destroy GPU droplet

Requires: pip install requests

Environment variables:
  DO_API_TOKEN=xxx          DigitalOcean personal access token
  GPU_SNAPSHOT_ID=xxx       Snapshot ID with Ollama + model pre-installed
  GPU_DROPLET_SIZE=gpu-h100x1-80gb   GPU droplet size slug
  GPU_REGION=lon1            Droplet region
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

DO_API_TOKEN = os.environ.get("DO_API_TOKEN", "")
GPU_SNAPSHOT_ID = os.environ.get("GPU_SNAPSHOT_ID", "")
GPU_DROPLET_SIZE = os.environ.get("GPU_DROPLET_SIZE", "gpu-h100x1-80gb")
GPU_REGION = os.environ.get("GPU_REGION", "lon1")
SSH_KEY_FINGERPRINT = os.environ.get("SSH_KEY_FINGERPRINT", "")

EPICOLLECT_EXPORT = os.environ.get(
    "EPICOLLECT_EXPORT",
    "https://five.epicollect.net/api/export/entries"
)
FORM_REF = os.environ.get("FORM_REF", "river-guardians")

DO_API = "https://api.digitalocean.com/v2"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import PER_PAGE, RATE_LIMIT_DELAY
from database import get_connection, get_last_sync
from sync import fetch_entries_page, parse_entries, upsert_entries


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


def spin_up_gpu():
    print("Spinning up GPU droplet...")
    config = {
        "name": f"llm-cleanup-{int(time.time())}",
        "region": GPU_REGION,
        "size": GPU_DROPLET_SIZE,
        "image": GPU_SNAPSHOT_ID,
        "ssh_keys": [SSH_KEY_FINGERPRINT] if SSH_KEY_FINGERPRINT else [],
        "tags": ["llm-cleanup", "ephemeral"],
        "monitoring": False,
    }
    result = call_do("POST", "/droplets", config)
    droplet = result["droplet"]
    droplet_id = droplet["id"]
    ip = droplet["networks"]["v4"][0]["ip_address"]
    print(f"  Droplet {droplet_id} created at {ip}")
    return droplet_id, ip


def wait_for_ssh(ip, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
             f"root@{ip}", "echo ready"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"  SSH ready after {time.time() - start:.0f}s")
            return True
        print(f"  Waiting for SSH... ({time.time() - start:.0f}s)")
        time.sleep(10)
    return False


def wait_for_ollama(ip, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}",
             "curl -s http://localhost:11434/api/tags | head -c 100"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and "models" in result.stdout:
            print(f"  Ollama ready after {time.time() - start:.0f}s")
            return True
        time.sleep(5)
    return False


def copy_to_droplet(ip, local_path, remote_path):
    subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", local_path, f"root@{ip}:{remote_path}"],
        check=True
    )


def copy_from_droplet(ip, remote_path, local_path):
    subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", f"root@{ip}:{remote_path}", local_path],
        check=True
    )


def run_on_droplet(ip, command):
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{ip}", command],
        capture_output=True, text=True, timeout=300
    )
    print(result.stdout, file=sys.stderr)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode


def destroy_droplet(droplet_id):
    print(f"Destroying GPU droplet {droplet_id}...")
    call_do("DELETE", f"/droplets/{droplet_id}")


def fetch_new_entries():
    conn = get_connection()
    last_sync = get_last_sync()
    conn.close()

    if not last_sync:
        return None

    from_ = last_sync[:10]
    page = 1
    all_entries = []

    while True:
        url = (
            f"{EPICOLLECT_EXPORT}?form_ref={FORM_REF}&per_page={PER_PAGE}"
            f"&page={page}&filter_by=uploaded_at&filter_from={from_}&sort_order=ASC"
        )
        data = fetch_entries_page(url)
        entries = data.get("data", {}).get("entries", [])
        if not entries:
            break
        all_entries.extend(entries)
        if not data.get("links", {}).get("next"):
            break
        page += 1
        time.sleep(RATE_LIMIT_DELAY)

    if not all_entries:
        return None

    parsed = parse_entries({"data": {"entries": all_entries}})

    conn = get_connection()
    new_entries = []
    for e in parsed:
        existing = conn.execute(
            "SELECT id FROM entries WHERE ec5_uuid = ?", (e["ec5_uuid"],)
        ).fetchone()
        if not existing:
            new_entries.append(e)
    conn.close()

    return new_entries if new_entries else None


def main():
    if not DO_API_TOKEN:
        print("DO_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Checking for new entries...")

    new_entries = fetch_new_entries()
    if not new_entries:
        print("  No new entries found.")
        return

    print(f"  {len(new_entries)} new entries found, spinning up GPU droplet...")

    raw_path = "/tmp/llm_raw_entries.json"
    cleaned_path = "/tmp/llm_cleaned_entries.json"
    remote_raw = "/root/raw_entries.json"
    remote_cleaned = "/root/cleaned_entries.json"
    worker_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "gpu_worker.py"
    )

    with open(raw_path, "w") as f:
        json.dump(new_entries, f, indent=2)

    droplet_id, ip = spin_up_gpu()

    try:
        if not wait_for_ssh(ip):
            raise RuntimeError("SSH timeout")

        if not wait_for_ollama(ip):
            print("  Ollama not ready, but continuing...")

        copy_to_droplet(ip, raw_path, remote_raw)
        copy_to_droplet(ip, worker_script, "/root/gpu_worker.py")

        ret = run_on_droplet(ip, f"cd /root && python3 gpu_worker.py < {remote_raw} > {remote_cleaned}")
        if ret != 0:
            raise RuntimeError(f"Worker exited with code {ret}")

        copy_from_droplet(ip, remote_cleaned, cleaned_path)

        with open(cleaned_path) as f:
            cleaned_entries = json.load(f)

        conn = get_connection()
        added, _ = upsert_entries(cleaned_entries)
        conn.close()
        print(f"  Inserted {added} cleaned entries into database.")

    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
    finally:
        destroy_droplet(droplet_id)

    os.remove(raw_path)
    if os.path.exists(cleaned_path):
        os.remove(cleaned_path)


if __name__ == "__main__":
    main()
