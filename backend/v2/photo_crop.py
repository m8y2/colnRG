"""Automatic photo cropping — trim letterbox bars as photos are processed.

Some volunteers' photos carry near-black bars baked into the image (a
wide shot saved into a 4:3 frame by the phone, for example). The bars are
not content, and they waste most of the frame: the tile shows a strip of
river squeezed between two slabs of black.

This module crops those bars off automatically whenever a photo is
processed. It is deliberately conservative — only a *uniform, near-black*
strip along an edge is ever cropped, and only when it is thick enough to
be a real bar rather than a dark bit of riverbank. A normal photo (dark
water, tree-line silhouettes) is left untouched, because its edges vary
and fail the uniformity test.

`process_photo` downloads an original, applies EXIF orientation, crops,
and saves a JPEG. It is called by `v2/photos.py`'s background scan (so
every currently-known photo is processed once at startup) and on demand
by the media endpoint for anything new.
"""

from __future__ import annotations

import hashlib
import io
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

CACHE_DIR = Path(__file__).resolve().parent.parent / "media_cache"

# Photos are fetched server-side from URLs that originate in EpiCollect
# submissions. Without a host allowlist a crafted submission could point a
# photo URL at an internal address (e.g. the cloud metadata service at
# 169.254.169.254 or the local API on 127.0.0.1:8000) and turn the media
# endpoint into an SSRF. Only EpiCollect's own host is ever legitimate.
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def is_allowed_photo_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host == "epicollect.net" or host.endswith(".epicollect.net")

# A strip is a letterbox bar when its sampled pixels are this uniform
# (std-dev of luminance, 0-255 scale) ...
UNIFORM_SD = 12
# ... and this dark (mean luminance). Dark bars are the overwhelmingly
# common case (photos/videos letterboxed by the device); a light strip is
# left alone, because a clear sky is also light and uniform but is
# content, not a bar.
DARK_LUM = 40
# The bar must be at least this thick (fraction of the image dimension)
# before cropping — a 3px dark rim at the top of a photo is vignette or
# shadow, not a bar.
MIN_BAR_FRACTION = 0.02

# Download headers: EpiCollect serves real photos with long cache times.
_DOWNLOAD_HEADERS = {"User-Agent": "RiverGuardiansDashboard/2.0"}

# One-off manual corrections, decided by the owner after looking at the
# photo. Each entry is a specific EpiCollect original URL -> the rotation
# to apply (degrees, clockwise) on top of any EXIF orientation, applied
# before the letterbox crop. Nothing here is guessed from image content;
# these are explicit human decisions, kept visible so they can be removed
# again if the original is ever corrected upstream.
#
#   5096fcac-...-1770569480.jpg (hippy.expect.iterative, 2026-02-08):
#   "lopsided" — the owner asked for 90 degrees clockwise.
MANUAL_ROTATIONS: dict[str, int] = {
    "https://five.epicollect.net/api/media/coln-river-guardians?type=photo"
    "&format=entry_original&name=5096fcac-0130-440f-9de6-01a67d5f82d1_1770569480.jpg": 90,
}

_download_lock = threading.Lock()
_processing_locks: dict[str, threading.Lock] = {}
_processing_locks_guard = threading.Lock()


def is_real_photo_head(url: str) -> bool:
    """The placeholder screen: EpiCollect serves a 512x512 "photo not
    synced" JPEG (with `Cache-Control: no-store`) until a photo has
    finished uploading. Real photos answer `max-age=..., public`. This
    checks that, with retries for EpiCollect's rate limiting."""
    if not is_allowed_photo_url(url):
        return False
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=20)
            cache_control = resp.headers.get("Cache-Control", "")
            content_type = resp.headers.get("Content-Type", "")
            return "no-store" not in cache_control and content_type.startswith("image/")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return False
        except Exception:
            return False
    return False


def sha1(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _bar_thicknesses(image: Image.Image) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) dark-bar thicknesses in pixels."""
    width, height = image.size
    px = image.load()
    min_thick = max(8, int(MIN_BAR_FRACTION * height))
    min_thick_h = max(8, int(MIN_BAR_FRACTION * width))

    def lum_stats_row(y):
        vals = [px[x, y] for x in range(0, width, 4)]
        lum = [0.30 * r + 0.59 * g + 0.11 * b for r, g, b in vals]
        return _pstdev(lum), sum(lum) / len(lum)

    def lum_stats_col(x):
        vals = [px[x, y] for y in range(0, height, 4)]
        lum = [0.30 * r + 0.59 * g + 0.11 * b for r, g, b in vals]
        return _pstdev(lum), sum(lum) / len(lum)

    def is_bar(sd, mean):
        return sd < UNIFORM_SD and mean < DARK_LUM

    top = 0
    while top < height:
        sd, mean = lum_stats_row(top)
        if not is_bar(sd, mean):
            break
        top += 4

    bottom = height
    while bottom > 0:
        sd, mean = lum_stats_row(bottom - 1)
        if not is_bar(sd, mean):
            break
        bottom -= 4

    left = 0
    while left < width:
        sd, mean = lum_stats_col(left)
        if not is_bar(sd, mean):
            break
        left += 4

    right = width
    while right > 0:
        sd, mean = lum_stats_col(right - 1)
        if not is_bar(sd, mean):
            break
        right -= 4

    return (top if top >= min_thick else 0,
            height - bottom if height - bottom >= min_thick else 0,
            left if left >= min_thick_h else 0,
            width - right if width - right >= min_thick_h else 0)


def _pstdev(values) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    return (sum((v - mean) ** 2 for v in values) / n) ** 0.5


def auto_crop(image: Image.Image) -> tuple[Image.Image, tuple | None]:
    """Crop near-black letterbox bars off `image`. Returns (image, box)
    where box is the crop rectangle used, or None if nothing was
    cropped."""
    top, bottom, left, right = _bar_thicknesses(image)
    if not (top or bottom or left or right):
        return image, None
    width, height = image.size
    box = (left, top, width - right, height - bottom)
    return image.crop(box), box


def _download(url: str) -> bytes:
    if not is_allowed_photo_url(url):
        raise ValueError("refusing to fetch a photo from a non-EpiCollect host")
    req = urllib.request.Request(url, headers=_DOWNLOAD_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        if not is_allowed_photo_url(resp.geturl()):
            raise ValueError("refusing a photo redirect to a non-EpiCollect host")
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("photo exceeds the maximum download size")
    return data


def _record_modified(key: str, modified: bool) -> None:
    from v2.db import get_connection

    conn = get_connection()
    try:
        conn.execute(
            "UPDATE photo_cache SET modified = ? WHERE sha = ?",
            (1 if modified else 0, key),
        )
        conn.commit()
    finally:
        conn.close()


def process_photo(original_url: str) -> Path | None:
    """Download, crop and cache one photo. Returns the cached file path,
    or None if the photo could not be fetched or processed (including
    "photo not synced" placeholders, which are never cached)."""
    key = sha1(original_url)
    dest = CACHE_DIR / f"{key}.jpg"
    if dest.exists():
        return dest

    with _processing_locks_guard:
        lock = _processing_locks.setdefault(key, threading.Lock())
    with lock:
        if dest.exists():
            return dest
        try:
            if not is_real_photo_head(original_url):
                return None
            data = _download(original_url)
            image = Image.open(io.BytesIO(data))
            image = ImageOps.exif_transpose(image)
            manual = MANUAL_ROTATIONS.get(original_url)
            rotated = False
            if manual:
                rotations = {90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}
                image = image.transpose(rotations[manual])
                rotated = True
            image, box = auto_crop(image)
            modified = rotated or box is not None
            if image.mode != "RGB":
                image = image.convert("RGB")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            image.save(tmp, "JPEG", quality=88, optimize=True)
            tmp.replace(dest)
            _record_modified(key, modified)
            return dest
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
            return None