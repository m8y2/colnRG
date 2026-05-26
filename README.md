# Coln River Guardians Dashboard

Water quality monitoring dashboard for the River Coln. Data synced from EpiCollect5, served by a FastAPI backend, rendered in React.

## What's here

- `backend/` — FastAPI + SQLite. Syncs from EpiCollect5 (public API, no auth needed), detects testing rounds from date clusters, serves stats/rounds/sites/chemical data.
- `frontend/` — React 19 + Vite + Recharts + Leaflet. JSX, no TypeScript. Code-split by tab so chart libraries only load when needed.
- `deploy/` — systemd service files, nginx config, and a setup script for provisioning a VPS.
- `run.py` — runs everything locally (installs deps, syncs, starts both servers, opens Chrome).

## Quick start (local)

```bash
python run.py
```

## Deploy (VPS)

```bash
git clone https://github.com/m8y2/colnRG.git /opt/coln-dashboard
cd /opt/coln-dashboard && bash deploy/setup.sh
```

See `deploy/` for the individual config files.

## Data

- 25 sites along the River Coln (Gloucestershire), sampled monthly since June 2025
- 7 chemicals measured: phosphate, ammonia, nitrate, turbidity, dissolved oxygen, conductivity, water depth
- Reference levels from WFD Lowland High Alkalinity standards
- Testing rounds detected as date clusters with >10 entries within 4 days
