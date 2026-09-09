"""v2 ASGI entrypoint: `uvicorn main_v2:app`.

Mounts the v2 data API onto the existing, untouched v1 `app` object. This
file makes zero changes to v1 — it only imports `app` from `main` and adds
routes to it.

Per V2_SPEC_ADDENDUM.md, v2 no longer shares v1's `dashboard.db` — it has
its own database, `backend/coln_v2.db`, populated by `v2/ingest.py` and
`v2/cleaning.py` (owned separately) from a fresh EpiCollect fetch.
`init_v2_db()` only ever runs `CREATE TABLE IF NOT EXISTS`, so calling it
here is safe and non-destructive whether `coln_v2.db` doesn't exist yet,
is mid-ingest, or is fully populated: the v2 API will simply return empty
results until the ingest has landed.

Note: `main.py`'s `/api/health` and admin-key endpoints call
`datetime.now(timezone.utc)` but the module only imports `datetime` and
`timedelta`, not `timezone` — that raises `NameError` if either endpoint
is actually hit. Importing `main` here is fine (the bug is inside the
function bodies, not at import time); this is v1 code and is intentionally
left as-is (documented as a known v1 bug in `V2.md`).
"""

from main import app  # v1 app, untouched
from v2.api import router as v2_router
from v2.db import init_v2_db

init_v2_db()
app.include_router(v2_router)

# Screen "photo not synced" placeholder images in the background (see
# v2/photos.py) so the gallery only shows real photos.
from v2.photos import start_validation_thread  # noqa: E402

start_validation_thread()

# The report endpoints (`v2/reports_api.py`) are owned by a separate
# in-progress piece of work. Guard the import so `main_v2` works before
# and after that module lands.
try:
    from v2.reports_api import router as v2_reports_router

    app.include_router(v2_reports_router)
except ImportError:
    pass
