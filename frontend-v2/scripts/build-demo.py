#!/usr/bin/env python3
"""Build a single-file, offline demo of the v2 site.

Snapshots the real API into one HTML file with the CSS and JS inlined and
`fetch` intercepted, so the whole site can be sent to somebody as an
attachment and opened with no server, no Python and no npm.

    cd Dashboard/backend && ./venv/bin/python -m uvicorn main_v2:app --port 8000 &
    cd Dashboard/frontend-v2 && npm run build
    python3 scripts/build-demo.py

Writes to ~/Desktop by default; pass --out to change that. The data is
real — whatever the running backend returns — but anything that would
write is inert, because there is nothing behind it to write to.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

BANNER = (
    '<div style="background:#123c4a;color:#fff;padding:10px 18px;'
    "font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif\">"
    "<strong>Offline demo.</strong> Real data from the rebuilt database, snapshotted so "
    "this one file runs with no server. Anything that would write — asking for a report, "
    "accepting a review item — is inert here. Map tiles need internet."
    "</div>"
)

# The shim answers from the snapshot instead of the network. Keyed on the
# path plus query string, which is exactly how src/lib/api.js builds a URL.
SHIM = """
<script>
(function () {
  var SNAP = __SNAPSHOT__;
  var origFetch = window.fetch;
  function key(url) {
    var u = new URL(url, window.location.href);
    return u.pathname.replace(/^.*\\/api\\/v2/, '') + (u.search || '');
  }
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.indexOf('/api/v2') === -1) return origFetch.apply(this, arguments);
    if (((init && init.method) || 'GET') !== 'GET') {
      return Promise.resolve(new Response(JSON.stringify({ demo: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    var k = key(url);
    if (Object.prototype.hasOwnProperty.call(SNAP, k)) {
      return Promise.resolve(new Response(JSON.stringify(SNAP[k]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return Promise.resolve(new Response(JSON.stringify(
      { detail: 'Not included in this offline snapshot. Works against the live backend.' }),
      { status: 404, headers: { 'Content-Type': 'application/json' } }));
  };
})();
</script>
"""

PARAMETERS = [
    "phosphate", "ammonia", "nitrate", "turbidity",
    "dissolved_oxygen", "conductivity", "water_depth",
]


def snapshot(base: str) -> dict:
    """Every endpoint the app can ask for, given the current data."""
    snap: dict = {}

    def get(path: str):
        with urllib.request.urlopen(base + path, timeout=90) as resp:
            return json.loads(resp.read().decode())

    def cap(path: str):
        try:
            snap[path] = get(path)
            return snap[path]
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"  skipped {path} ({exc})")
            return None

    for path in ("/parameters", "/overview", "/locations", "/rounds",
                 "/data-quality", "/review-queue", "/reports", "/reports/types"):
        cap(path)

    for p in PARAMETERS:
        cap(f"/series?parameter={p}")
        cap(f"/downstream?parameter={p}")

    for loc in (snap.get("/locations") or {}).get("locations", []):
        w3w = urllib.parse.quote(loc["w3w"], safe="")
        cap(f"/locations/{w3w}")
        for p in ("phosphate", "turbidity"):
            cap(f"/series?parameter={p}&w3w={w3w}")

    for n in range(1, len((snap.get("/rounds") or {}).get("rounds", [])) + 1):
        cap(f"/rounds/{n}")

    for report in (snap.get("/reports") or {}).get("reports", []):
        cap(f"/reports/{report['id']}")

    return snap


def build(snap: dict) -> str:
    html = (DIST / "index.html").read_text()
    js = sorted((DIST / "assets").glob("*.js"))[0].read_text()
    css = sorted((DIST / "assets").glob("*.css"))[0].read_text()

    shim = SHIM.replace("__SNAPSHOT__", json.dumps(snap))
    out = re.sub(r'<script type="module"[^>]*src="[^"]*"></script>', "", html)
    out = re.sub(r'<link rel="stylesheet"[^>]*href="[^"]*"[^>]*>', "", out)
    out = out.replace("</head>", f"<style>{css}</style>\n{shim}\n</head>")
    out = out.replace("<body>", f"<body>{BANNER}")
    return out.replace("</body>", f'<script type="module">{js}</script>\n</body>')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://127.0.0.1:8000/api/v2")
    ap.add_argument("--out", default="~/Desktop/coln-river-guardians-v2-demo.html")
    args = ap.parse_args()

    if not DIST.exists():
        print("No dist/ — run `npm run build` first.")
        return 1

    print(f"Snapshotting {args.api} …")
    snap = snapshot(args.api)
    if "/overview" not in snap:
        print("The backend did not answer. Is uvicorn running on that port?")
        return 1

    dest = Path(os.path.expanduser(args.out))
    dest.write_text(build(snap))
    print(f"{len(snap)} endpoints -> {dest} ({dest.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
