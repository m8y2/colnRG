"""Photo validation cache — "photo not synced" screening.

EpiCollect returns a real photo URL as soon as a volunteer submits an
entry, but the photo itself only appears once the phone has finished
uploading it. Until then the media endpoint serves a placeholder JPEG
(a 512x512 image saying the photo is not synced yet).

That placeholder is indistinguishable from a real photo by URL, so the
server HEAD-checks every photo URL and keeps the results in a cache:

  * real photos answer `Cache-Control: max-age=86400, public`
  * unsynced placeholders answer `Cache-Control: no-store, private`

The results are persisted in `photo_cache.valid`, so a restart starts
with the last scan's verdicts instead of briefly re-showing every
placeholder while the scan runs again. The scan runs in a background
thread at server start and repeats every few hours, so a photo that
eventually syncs appears in the gallery without a restart, and a
placeholder never does.

`photo_is_real` returns True for anything not yet checked (a genuinely
new photo uploads, or a fresh database) — fail-open by design, so the
gallery shows photos rather than nothing.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from v2.db import get_connection
from v2.photo_crop import CACHE_DIR, is_real_photo_head, process_photo, sha1

REFRESH_INTERVAL_SECONDS = 6 * 60 * 60
_REQUEST_DELAY = 0.6  # EpiCollect rate-limits bursts; stay gentle

_lock = threading.Lock()
_cached: dict[str, bool] = {}
_ready = False
_stop = threading.Event()


def _photo_urls() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT photo_url, photo_2_url FROM observations WHERE excluded = 0"
        ).fetchall()
    finally:
        conn.close()
    urls = set()
    for r in rows:
        if r["photo_url"]:
            urls.add(r["photo_url"])
        if r["photo_2_url"]:
            urls.add(r["photo_2_url"])
    return sorted(urls)


def _load_persisted() -> None:
    """Start from the last scan's verdicts (see module docstring)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT original_url, valid FROM photo_cache"
        ).fetchall()
    finally:
        conn.close()
    with _lock:
        global _ready
        _cached.update({r["original_url"]: bool(r["valid"]) for r in rows})
        _ready = bool(rows)


def _set_valid(url: str, ok: bool) -> None:
    key = sha1(url)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO photo_cache (sha, original_url, processed_at, valid) "
            "VALUES (?,?,?,?) ON CONFLICT(sha) DO UPDATE SET valid=excluded.valid",
            (key, url, datetime.now(timezone.utc).isoformat(), 1 if ok else 0),
        )
        conn.commit()
    finally:
        conn.close()
    with _lock:
        _cached[url] = ok


def _record_and_warm(url: str) -> None:
    """Remember this photo in photo_cache and process it into the crop
    cache now if it is not there yet. Only a new or previously-failed
    photo is downloaded."""
    key = sha1(url)
    if not (CACHE_DIR / f"{key}.jpg").exists():
        process_photo(url)


def _scan() -> None:
    urls = _photo_urls()
    fresh: dict[str, bool] = {}
    for i, url in enumerate(urls):
        if _stop.is_set():
            break
        ok = is_real_photo_head(url)
        fresh[url] = ok
        _set_valid(url, ok)
        if ok:
            _record_and_warm(url)
        else:
            # A known placeholder must never be served; drop any stale
            # processed copy of it too.
            cached = CACHE_DIR / f"{sha1(url)}.jpg"
            if cached.exists():
                cached.unlink()
        if i % 20 == 0:
            # let a 429 quota breathe even mid-scan
            time.sleep(1)
        time.sleep(_REQUEST_DELAY)
    with _lock:
        _cached.clear()
        _cached.update(fresh)
    global _ready
    _ready = True


def _loop() -> None:
    while not _stop.is_set():
        try:
            _scan()
        except Exception:
            pass
        _stop.wait(REFRESH_INTERVAL_SECONDS)


def start_validation_thread() -> threading.Thread:
    """Start the background scan/refresh loop. Daemon: never blocks exit."""
    _load_persisted()
    thread = threading.Thread(target=_loop, daemon=True, name="photo-validation")
    thread.start()
    return thread


def photo_is_real(url: str) -> bool:
    """Whether a photo URL currently serves a real image. Fail-open: any
    URL not yet checked (server just started with an empty cache, or a
    photo too new for the last scan) is treated as real until the next
    scan decides."""
    with _lock:
        if not _ready:
            return True
        return _cached.get(url, True)


def mark_invalid(url: str) -> None:
    """Record that a photo is a placeholder and drop any processed copy —
    used when the media endpoint discovers one while processing on
    demand, so it is excluded from the next list refresh immediately."""
    _set_valid(url, False)
    cached = CACHE_DIR / f"{sha1(url)}.jpg"
    if cached.exists():
        cached.unlink()


def screening_ready() -> bool:
    with _lock:
        return _ready