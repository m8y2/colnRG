"""v2 ASGI entrypoint: `uvicorn main_v2:app`.

Mounts the v2 data API onto the existing, untouched v1 `app` object. This
file makes zero changes to v1 — it only imports `app` from `main` and adds
routes to it, exactly as the build spec asks.

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

# The report endpoints (`v2/reports_api.py`) are owned by a separate
# in-progress piece of work. Guard the import so `main_v2` works before
# and after that module lands.
try:
    from v2.reports_api import router as v2_reports_router

    app.include_router(v2_reports_router)
except ImportError:
    pass
