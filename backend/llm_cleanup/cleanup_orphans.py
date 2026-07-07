#!/usr/bin/env python3
"""Standalone orphan droplet cleanup — safe to run every 5 min via cron/systemd.

Lists droplets tagged 'llm-cleanup' and destroys any older than 5 minutes.
Does NOT touch droplets that may still be in use (created <5 min ago).

Does NOT exit on failure — this is a best-effort safety net.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

DO_API_TOKEN = os.environ.get("DO_API_TOKEN", "")
DO_API = "https://api.digitalocean.com/v2"

MAX_AGE_MINUTES = 5


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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def list_tagged_droplets(tag="llm-cleanup"):
    try:
        result = call_do("GET", f"/droplets?tag_name={tag}")
        return result.get("droplets", [])
    except Exception as e:
        print(f"(could not list droplets: {e})", file=sys.stderr)
        return []


def destroy_droplet(droplet_id):
    assert isinstance(droplet_id, int) and droplet_id > 0, f"Bad droplet_id: {droplet_id!r}"
    for attempt in range(3):
        try:
            call_do("DELETE", f"/droplets/{droplet_id}")
            print(f"  Droplet {droplet_id} destroyed.")
            return True
        except Exception as e:
            if attempt < 2:
                time.sleep(10)
            else:
                print(f"  Droplet {droplet_id} could not be destroyed: {e}", file=sys.stderr)
    return False


def main():
    if not DO_API_TOKEN:
        print("DO_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print(f"[{datetime.now(timezone.utc).isoformat()}] cleanup_orphans: checking...")
    now = time.time()
    droplets = list_tagged_droplets()
    if not droplets:
        print("  No tagged droplets found.")
        return

    for d in droplets:
        created = d.get("created_at", "")
        if not created:
            continue
        try:
            created_ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        age_minutes = (now - created_ts) / 60
        if age_minutes > MAX_AGE_MINUTES:
            print(f"  Orphan: droplet {d['id']} ({age_minutes:.0f}m old), destroying...")
            destroy_droplet(d["id"])
        else:
            print(f"  Droplet {d['id']} is {age_minutes:.0f}m old (within limit, keeping).")


if __name__ == "__main__":
    main()
