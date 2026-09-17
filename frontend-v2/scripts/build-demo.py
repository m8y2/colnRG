#!/usr/bin/env python3
"""Build a single-file, offline demo of the v2 site.

Snapshots the real API into one HTML file with the CSS and JS inlined and
`fetch` intercepted, so the whole site can be sent to somebody as an
attachment and opened with no server, no Python and no npm.

    cd Dashboard/backend && ./venv/bin/python -m uvicorn main_v2:app --port 8000 &
    cd Dashboard/frontend-v2 && DEMO_BUILD=1 npm run build
    python3 scripts/build-demo.py

DEMO_BUILD=1 matters, not just `npm run build`: pages are React.lazy()
(see App.jsx), so a normal build is one small chunk per route and this
script can only inline a single JS file into its one-file HTML -- the
rest would 404 with no server behind them to fetch them from.
DEMO_BUILD=1 (see vite.config.js) folds every lazy chunk back into one
file for this build only; the real deployed site keeps the split build.

Writes to ~/Desktop by default; pass --out to change that. The data is
real — whatever the running backend returns — but anything that would
write is inert, because there is nothing behind it to write to.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# The shim answers from the snapshot instead of the network. Keyed on the
# path plus query string, which is exactly how src/lib/api.js builds a URL.
# Two endpoint groups get special treatment so they behave like the live
# backend rather than a fixed list of captured URLs:
#
#   /observations   the app paginates and filters it (place, dates, page),
#                   which an exact-key snapshot cannot answer. All captured
#                   pages are merged and the request is answered by
#                   filtering + paginating client-side.
#
#   raw endpoints   the CSV export and report downloads are captured as
#                   plain text; a click listener serves them through the
#                   shimmed fetch so downloads work on file://, where a
#                   plain <a download> cannot reach them.
SHIM = """
<script>
(function () {
  var SNAP = __SNAPSHOT__;
  var RAW = __RAW__;
  var origFetch = window.fetch;
  function key(url) {
    var u = new URL(url, window.location.href);
    return u.pathname.replace(/^.*\\/api\\/v2/, '') + (u.search || '');
  }

  var OBS_ROWS = null;
  function obsRows() {
    if (!OBS_ROWS) {
      OBS_ROWS = [];
      Object.keys(SNAP).forEach(function (k) {
        if (k.indexOf('/observations?') === 0) {
          OBS_ROWS = OBS_ROWS.concat((SNAP[k] && SNAP[k].rows) || []);
        }
      });
    }
    return OBS_ROWS;
  }

  function answerObservations(search) {
    var q = new URLSearchParams(search);
    var w3w = q.get('w3w') || '';
    var from = q.get('from') || '';
    var to = q.get('to') || '';
    var page = Math.max(1, parseInt(q.get('page') || '1', 10) || 1);
    var perPage = Math.min(100, Math.max(1, parseInt(q.get('per_page') || '50', 10) || 50));
    var filtered = obsRows().filter(function (r) {
      if (w3w && r.w3w !== w3w) return false;
      if (from && r.date && r.date < from) return false;
      if (to && r.date && r.date > to) return false;
      return true;
    });
    var total = filtered.length;
    var totalPages = Math.max(1, Math.ceil(total / perPage));
    var start = (page - 1) * perPage;
    return {
      page: page, per_page: perPage, total: total, total_pages: totalPages,
      rows: filtered.slice(start, start + perPage)
    };
  }

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url.indexOf('/api/v2') === -1) return origFetch.apply(this, arguments);
    if (((init && init.method) || 'GET') !== 'GET') {
      return Promise.resolve(new Response(JSON.stringify({ demo: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    var k = key(url);
    if (k.indexOf('/observations?') === 0) {
      return Promise.resolve(new Response(JSON.stringify(answerObservations(new URL(url, window.location.href).search)),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (Object.prototype.hasOwnProperty.call(RAW, k)) {
      return Promise.resolve(new Response(RAW[k],
        { status: 200, headers: { 'Content-Type': 'text/plain;charset=utf-8' } }));
    }
    if (Object.prototype.hasOwnProperty.call(SNAP, k)) {
      return Promise.resolve(new Response(JSON.stringify(SNAP[k]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return Promise.resolve(new Response(JSON.stringify(
      { detail: 'Not included in this copy. It works on the live website.' }),
      { status: 404, headers: { 'Content-Type': 'application/json' } }));
  };

  var RAW_NAMES = __RAW_NAMES__;
  document.addEventListener('click', function (e) {
    var el = e.target;
    while (el && el !== document && !(el.tagName === 'A')) el = el.parentNode;
    if (!el || el.tagName !== 'A') return;
    var href = el.getAttribute('href') || '';
    if (href.indexOf('/api/v2/') === -1) return;
    e.preventDefault();
    window.fetch(href).then(function (r) { return r.text(); }).then(function (text) {
      var k = key(href);
      var name = RAW_NAMES[k] || 'download.txt';
      var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
  }, true);
})();
</script>
"""

PARAMETERS = [
    "phosphate", "ammonia", "nitrate", "turbidity",
    "dissolved_oxygen", "conductivity", "water_depth",
]


def snapshot(base: str) -> tuple[dict, dict, dict]:
    """Every endpoint the app can ask for, given the current data.

    Returns (snap, raw, raw_names): JSON endpoints, raw-text endpoints,
    and the download filenames the backend advertises for them."""
    snap: dict = {}
    raw: dict = {}
    raw_names: dict = {}

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

    def cap_raw(path: str):
        """Capture a non-JSON endpoint (CSV, report downloads) as text,
        keeping the backend's advertised download filename."""
        try:
            with urllib.request.urlopen(base + path, timeout=90) as resp:
                raw[path] = resp.read().decode()
            disposition = resp.headers.get("Content-Disposition", "")
            match = re.search(r'filename="?([^";]+)"?', disposition)
            raw_names[path] = match.group(1) if match else path.rsplit("/", 1)[-1]
            return raw[path]
        except (urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"  skipped {path} ({exc})")
            return None

    for path in ("/parameters", "/overview", "/locations", "/rounds",
                 "/data-quality", "/review-queue", "/reports", "/reports/types",
                 "/photos"):
        cap(path)

    for p in PARAMETERS:
        cap(f"/series?parameter={p}")
        cap(f"/downstream?parameter={p}")

    for loc in (snap.get("/locations") or {}).get("locations", []):
        w3w = urllib.parse.quote(loc["w3w"], safe="")
        cap(f"/locations/{w3w}")
        for p in PARAMETERS:
            cap(f"/series?parameter={p}&w3w={w3w}")

    for n in range(1, len((snap.get("/rounds") or {}).get("rounds", [])) + 1):
        cap(f"/rounds/{n}")

    obs = cap("/observations?page=1&per_page=50")
    if obs:
        for page in range(2, obs.get("total_pages", 1) + 1):
            cap(f"/observations?page={page}&per_page=50")

    cap_raw("/export.csv")

    for report in (snap.get("/reports") or {}).get("reports", []):
        cap(f"/reports/{report['id']}")
        for fmt in ("md", "html"):
            cap_raw(f"/reports/{report['id']}/download?format={fmt}")

    return snap, raw, raw_names


def embed_processed_photos(snap: dict, base: str) -> None:
    """Make the demo show the same photos as the live site.

    The live backend processes photos (letterbox crop, the owner's manual
    rotation) and serves them from /api/v2/media/... — the demo has no
    backend, so for every photo that processing *changed*, the processed
    image is downloaded now and embedded as a data URI. Everything else
    points straight at the EpiCollect original, exactly as before.
    """
    def fix(photo: dict) -> None:
        if photo.get("modified"):
            media_path = photo["url"].replace("/api/v2/media/", "/media/", 1)
            with urllib.request.urlopen(base + media_path, timeout=90) as resp:
                photo["url"] = "data:image/jpeg;base64," + base64.b64encode(
                    resp.read()
                ).decode()
        else:
            photo["url"] = photo.get("original_url") or photo["url"]
        photo.pop("modified", None)

    for photo in (snap.get("/photos") or {}).get("photos", []):
        fix(photo)
    for loc in (snap.get("/locations") or {}).get("locations", []):
        w3w = urllib.parse.quote(loc["w3w"], safe="")
        loc_snap = snap.get(f"/locations/{w3w}")
        if loc_snap and loc_snap.get("photos"):
            for photo in loc_snap["photos"]:
                fix(photo)


MIME_BY_SUFFIX = {".pdf": "application/pdf"}


def embed_static_files(js: str) -> str:
    """Inline anything under public/ that the bundle references by a plain
    path string rather than fetching it (the Reports page's PDF, `data=`
    on an `<object>` and `href=` on a download link -- neither goes
    through `fetch`, so the shim below cannot intercept it, and a plain
    path is dead the moment there is no server behind it). Vite copies
    public/ into dist/ untouched, so the referenced file is sitting right
    there to read and re-embed as a data: URI, no network round-trip
    needed."""
    for suffix, mime in MIME_BY_SUFFIX.items():
        # Not anchored to a particular base path (the site has moved
        # between "/" and "/new/" already) -- any absolute path is a
        # candidate, and the disk check below is what actually decides
        # whether it is a real asset, so a stray match that isn't one is
        # harmless.
        for match in set(re.findall(rf"/[A-Za-z0-9_./-]+\{suffix}", js)):
            asset = DIST / match.lstrip("/")
            if not asset.is_file():
                continue
            data_uri = f"data:{mime};base64," + base64.b64encode(asset.read_bytes()).decode()
            js = js.replace(match, data_uri)
    return js


def build(snap: dict, raw: dict, raw_names: dict) -> str:
    html = (DIST / "index.html").read_text()
    js_files = sorted((DIST / "assets").glob("*.js"))
    if len(js_files) != 1:
        raise SystemExit(
            f"Expected one JS file in dist/assets/, found {len(js_files)}: "
            f"{[f.name for f in js_files]}. This build was not made with "
            "DEMO_BUILD=1 (see this file's docstring and vite.config.js) -- "
            "each of those is a separate lazy-loaded route chunk, and this "
            "script can only inline one file into the single-page demo."
        )
    js = embed_static_files(js_files[0].read_text())
    css = sorted((DIST / "assets").glob("*.css"))[0].read_text()

    shim = SHIM.replace("__RAW_NAMES__", json.dumps(raw_names))
    shim = shim.replace("__RAW__", json.dumps(raw))
    shim = shim.replace("__SNAPSHOT__", json.dumps(snap))

    # Edit the outer page FIRST, while it is still just index.html with a
    # single <body>. The shim (injected below) embeds the captured report
    # HTML downloads, which contain their own <body>/</body> — if those
    # were present when these replaces run, the whole app bundle would be
    # injected into the captured documents instead.
    out = re.sub(r'<script type="module"[^>]*src="[^"]*"></script>', "", html)
    out = re.sub(r'<link rel="stylesheet"[^>]*href="[^"]*"[^>]*>', "", out)
    out = out.replace("</body>", f'<script type="module">{js}</script>\n</body>', 1)

    # Then inject CSS + shim into the head, so their embedded content can
    # no longer be mistaken for the outer document's structure.
    return out.replace("</head>", f"<style>{css}</style>\n{shim}\n</head>", 1)


def wait_for_screening(base: str, timeout_seconds: int = 600) -> bool:
    """Wait until the backend's photo screening has finished its first
    scan. Before that the photo list includes "photo not synced"
    placeholders (fail-open), and the demo must not capture them."""
    import time as _time

    deadline = _time.time() + timeout_seconds
    while _time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/photos", timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            if payload.get("screening_ready"):
                return True
        except Exception:
            pass
        _time.sleep(5)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://127.0.0.1:8000/api/v2")
    ap.add_argument("--out", default="~/Desktop/coln-river-guardians-v2-demo.html")
    args = ap.parse_args()

    if not DIST.exists():
        print("No dist/ — run `npm run build` first.")
        return 1

    print(f"Snapshotting {args.api} …")
    if not wait_for_screening(args.api):
        print("The backend's photo screening never became ready; the demo may "
              "include 'photo not synced' placeholders. Aborting.")
        return 1
    snap, raw, raw_names = snapshot(args.api)
    if "/overview" not in snap:
        print("The backend did not answer. Is uvicorn running on that port?")
        return 1
    embed_processed_photos(snap, args.api)

    dest = Path(os.path.expanduser(args.out))
    dest.write_text(build(snap, raw, raw_names))
    print(f"{len(snap) + len(raw)} endpoints -> {dest} ({dest.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
