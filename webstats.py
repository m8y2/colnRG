"""Parse nginx access logs from the droplet to count unique visitors.

Usage:
    python webstats.py                    # show all stats
    python webstats.py --days 7           # stats from last 7 days only
    python webstats.py --exclude 1.2.3.4  # exclude your own IP
    python webstats.py --live             # follow new log lines (tail -f)
    python webstats.py --ssh-key ~/.ssh/id_ed25519

Requirements: nothing beyond stdlib. Requires SSH access to the droplet.
"""

import argparse
import csv
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

DROPLET = "root@161.35.168.168"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
LOG_PATH = "/var/log/nginx/access.log"

BOT_AGENTS = re.compile(
    r"(bot|crawl|spider|scrape|scan|checker|monitor|uptime|ping|health|"
    r"google|bing|yahoo|baidu|yandex|duckduck|facebook|slack|"
    r"curl|wget|python-requests|java/|ruby|go-http-client|httpie|"
    r"lighthouse|pagespeed|validator|httpx|nikto|nmap|masscan)",
    re.IGNORECASE,
)

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

LOG_PATTERN = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<day>\d+)/(?P<mon>\w+)/(?P<year>\d+):'
    r'(?P<hour>\d+):(?P<min>\d+):(?P<sec>\d+) [^\]]+\] '
    r'"(?P<method>\S+) (?P<path>\S+) [^"]*" '
    r'(?P<status>\d+) (?P<bytes>\d+) "[^"]*" '
    r'"(?P<agent>[^"]*)"'
)


def fetch_logs(lines=0):
    """Return raw log lines from the droplet via SSH."""
    cmd = ["ssh", "-i", SSH_KEY, DROPLET]
    if lines:
        cmd += ["tail", f"-{lines}", LOG_PATH]
    else:
        cmd += ["cat", LOG_PATH]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode:
        print(f"SSH error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip().splitlines()


def parse_line(line):
    m = LOG_PATTERN.match(line)
    if not m:
        return None
    g = m.groupdict()
    try:
        ts = datetime(
            int(g["year"]), MONTHS[g["mon"]], int(g["day"]),
            int(g["hour"]), int(g["min"]), int(g["sec"]),
            tzinfo=timezone.utc,
        )
    except (ValueError, KeyError):
        return None
    return {
        "ip": g["ip"],
        "ts": ts,
        "path": g["path"],
        "status": int(g["status"]),
        "agent": g["agent"],
    }


def is_bot(agent):
    return bool(BOT_AGENTS.search(agent))


def run(args):
    print(f"Fetching logs from {DROPLET} …", file=sys.stderr)
    raw = fetch_logs(args.tail)
    print(f"  {len(raw)} log entries\n", file=sys.stderr)

    entries = []
    for line in raw:
        e = parse_line(line)
        if e:
            entries.append(e)

    # Filter by days
    if args.days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
        entries = [e for e in entries if e["ts"] >= cutoff]

    if not entries:
        print("No log entries found.")
        return

    exclude_ips = set(args.exclude or [])

    # Human vs bot classification
    humans = [e for e in entries if not is_bot(e["agent"]) and e["ip"] not in exclude_ips]
    bots = [e for e in entries if is_bot(e["agent"]) and e["ip"] not in exclude_ips]

    human_ips = set(e["ip"] for e in humans)
    bot_ips = set(e["ip"] for e in bots)
    all_unique = human_ips | bot_ips

    # Per-day unique humans
    day_counts = Counter()
    for e in humans:
        day_counts[e["ts"].date()] += 1
    day_unique = defaultdict(set)
    for e in humans:
        day_unique[e["ts"].date()].add(e["ip"])

    # Top pages (human)
    page_hits = Counter()
    page_unique = defaultdict(set)
    for e in humans:
        path = e["path"]
        page_hits[path] += 1
        page_unique[path].add(e["ip"])

    # Top user agents (human)
    agent_counts = Counter()
    for e in humans:
        agent_counts[e["agent"]] += 1

    # ===== Output =====
    total_human = len(humans)
    total_bot = len(bots)
    total_all = len(entries)

    print(f"{'='*50}")
    print(f"  Web Stats — {DROPLET}")
    print(f"{'='*50}")
    print(f"  Logs spanned:  {entries[0]['ts'].strftime('%d %b %Y')} – {entries[-1]['ts'].strftime('%d %b %Y')}")
    print(f"  Total requests: {total_all}")
    print()
    print(f"  {'Human':>10}  {'Bot':>10}  {'All':>10}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*10}")
    print(f"  {'Requests':>10}  {total_human:>10}  {total_bot:>10}  {total_all:>10}")
    print(f"  {'Unique IPs':>10}  {len(human_ips):>10}  {len(bot_ips):>10}  {len(all_unique):>10}")
    print()

    # Per-day
    if day_unique:
        print(f"  Unique human visitors per day:")
        print(f"  {'Date':>14}  {'Visitors':>10}  {'Requests':>10}")
        print(f"  {'-'*14}  {'-'*10}  {'-'*10}")
        for day in sorted(day_unique):
            if day in day_counts:
                print(f"  {day.isoformat():>14}  {len(day_unique[day]):>10}  {day_counts[day]:>10}")
        print()

    # Top pages
    if page_hits:
        print(f"  Top pages (human):")
        print(f"  {'Page':<40}  {'Visitors':>10}  {'Hits':>8}")
        print(f"  {'-'*40}  {'-'*10}  {'-'*8}")
        for path, hits in page_hits.most_common(10):
            visitors = len(page_unique[path])
            print(f"  {path:<40}  {visitors:>10}  {hits:>8}")
        print()

    # Top user agents
    if agent_counts:
        print(f"  Top user agents (human):")
        for agent, count in agent_counts.most_common(8):
            label = agent[:60] + "…" if len(agent) > 60 else agent
            print(f"    {count:>5}x  {label}")

    # CSV export
    if args.csv:
        path = args.csv
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["date", "ip", "path", "status", "agent", "type"])
            for e in entries:
                typ = "bot" if is_bot(e["agent"]) else "human"
                w.writerow([e["ts"].date(), e["ip"], e["path"], e["status"], e["agent"], typ])
        print(f"\n  Exported {len(entries)} rows → {path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Count unique visitors from nginx logs.")
    p.add_argument("--days", type=int, default=0, help="Only show last N days")
    p.add_argument("--exclude", nargs="*", default=[], help="IPs to exclude (e.g. your own)")
    p.add_argument("--tail", type=int, default=0, help="Only read last N log lines")
    p.add_argument("--csv", help="Export all entries to a CSV file")
    args = p.parse_args()
    run(args)
