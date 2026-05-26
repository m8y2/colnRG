# Coln River Guardians Dashboard

## One command to run everything

```bash
python run.py
```

This runs: pip install → npm install → EpiCollect sync → data clean → backend (port 8000) → frontend proxy (port 5173) → opens Chrome.

## Architecture

```
backend/   FastAPI + SQLite, syncs from EpiCollect5 API
frontend/  React 19 + Vite + Recharts (JSX, no TS)
run.py     Orchestrator script (uses Node 22 at /usr/local/opt/node@22/bin/node)
```

- Frontend Vite proxy: `/api` → `http://127.0.0.1:8000` (vite.config.js:10)
- Backend CORS: wide open (main.py:11-14)
- No router/middleware — single-file FastAPI `main.py`

## Commands

| Action | Command | Notes |
|---|---|---|
| Dev both | `python run.py` | Installs deps, syncs, starts both servers |
| Frontend dev | `npm run dev` | From `frontend/` |
| Frontend build | `npm run build` | Outputs to `frontend/dist/` |
| Frontend lint | `npm run lint` | ESLint flat config |
| Backend dev | `uvicorn main:app --reload` | From `backend/` (uses venv python) |

## Data sync

- Syncs from EpiCollect5 public API (no auth required)
- Paginated with 12s rate limit between pages (`RATE_LIMIT_DELAY`)
- Incremental: filters by `uploaded_at` since last successful sync
- Upserts on `ec5_uuid` — re-runs update matching records
- API endpoints: `/api/sync` triggers sync, `/api/sync/log` shows history

## Data cleaning

- `backend/clean.py` — shared numeric parser (strips units, handles ranges/turbidity text, outlier detection)
- `backend/clean_data.py` — idempotent cleanup script run during pipeline
- Numeric values stored as strings in SQLite; float conversion at API layer

## Site codes

40+ site codes (e.g. EP, PW, MG) mapped to human names in `sync.py:13-40`. Site code extracted from the last token of the what3words answer field.

## Vite quirks

- `optimizeDeps.exclude` lists 10+ d3 packages and `victory-vendor` (vite.config.js:15-27) — pre-bundling breaks these
- Uses plain JSX with esbuild `jsx: 'automatic'` (no SWC/React compiler)

## Known issues

- **d3-shape "does not provide an export named 'default'"** — Stale Vite dep cache after `npm install` or version changes. Fix: `rm -rf frontend/node_modules/.vite`
- **Port 8000 "Address already in use"** — Stale uvicorn process from a prior run. Fix: `lsof -ti:8000 | xargs kill -9`

## Key files

| File | Role |
|---|---|
| `backend/config.py` | EpiCollect API settings, form ref, rate limit, DB path |
| `backend/database.py` | SQLite schema (entries + sync_log tables), WAL mode |
| `backend/sync.py` | Full EpiCollect fetch→parse→upsert pipeline |
| `backend/clean.py` | Numeric parsing utilities (used by both sync and clean_data) |
| `backend/clean_data.py` | Post-sync cleanup (outlier fixup, text→numeric) |
| `backend/sync_runner.py` | Oneshot script called by coln-sync.service (init_db + sync + clean) |
| `frontend/src/api.js` | All API call wrappers |

## Deploy

| | |
|---|---|
| **URL** | `http://161.35.168.168/` |
| **Droplet** | Ubuntu 24.04, 1vCPU/512MB, London |
| **SSH** | `ssh -i ~/.ssh/id_ed25519 root@161.35.168.168` |
| **Frontend** | Served by nginx from `/opt/coln-dashboard/frontend/dist/` |
| **Backend** | FastAPI behind nginx proxy `/api` → `127.0.0.1:8000`, 2 uvicorn workers |
| **Auto-start** | nginx + coln-api.service + coln-sync.timer (daily 06:00) all systemd-enabled |
| **Swap** | 1GB swapfile added for `npm run build` (512MB RAM is tight) |
| **Build locally, rsync** | `npm run build && rsync -e 'ssh -i ~/.ssh/id_ed25519' -avz dist/ root@161.35.168.168:/opt/coln-dashboard/frontend/dist/` |
| **Re-deploy after changes** | `git push` → `ssh root@161.35.168.168 'cd /opt/coln-dashboard && git pull && systemctl restart coln-api.service'` + rebuild/rsync frontend |

## No tests

No test framework or test files exist.
