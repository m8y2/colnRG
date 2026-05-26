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

## LLM-based data cleaning pipeline

New entries are cleaned by an LLM running on an ephemeral DigitalOcean GPU droplet.

### Architecture

```
Main droplet ($6/mo)                     GPU droplet ($2.19/hr, ephemeral)
┌──────────────────────┐                 ┌──────────────────────────┐
│  gpu_poller.py        │──DO API spin──→│  Ollama + llama3.1:8b   │
│  (runs as systemd     │──SCP raw JSON──→│  gpu_worker.py          │
│   timer, e.g. hourly) │←──SCP cleaned──│                          │
│                       │──DO API kill──→│  (destroyed after use)   │
└──────────────────────┘                 └──────────────────────────┘
```

1. `gpu_poller.py` checks EpiCollect for entries uploaded since last sync
2. If new entries found, calls DO API to spin up a GPU droplet from a pre-built snapshot
3. SCPs raw entry data + worker script to the droplet
4. SSH runs `gpu_worker.py` which sends each entry through Ollama (llama3.1:8b)
5. LLM returns cleaned JSON for each entry
6. Cleaned data SCP'd back, inserted into SQLite
7. GPU droplet destroyed

### Files

| File | Role | Runs on |
|---|---|---|
| `backend/llm_cleanup/gpu_poller.py` | Orchestrator — polls EpiCollect, spins droplets, copies data | Main droplet (systemd timer) |
| `backend/llm_cleanup/gpu_worker.py` | Sends each entry to Ollama, parses LLM response | GPU droplet (ephemeral) |
| `backend/llm_cleanup/prompt_template.py` | The cleaning prompt sent to the LLM | Included in gpu_worker.py |
| `backend/llm_cleanup/setup_gpu.sh` | One-time setup for the GPU droplet (install Ollama + model) | GPU droplet (one-time) |

### Custom LLM Prompt

The prompt (`prompt_template.py`) instructs the LLM to:
- Fix decimal-shift outliers (e.g. 2.5→0.25 for phosphate, 3.0→0.3 for ammonia) using site-relative context
- Standardise landowner names (Whittington, Rupert Lowe, Rose Vestey, etc.)
- Strip non-landowner values (N/A, Yes, Public, site codes)
- Convert turbidity text ("clear", "cloudy") to numeric
- Fix typographic errors (letter O→zero, commas→periods)
- Clean titles (w3w address + date → just date)
- Strip "Nil"/"N/A" from comments
- Preserve all valid data unchanged

### DigitalOcean Setup Steps

1. **Request GPU droplet access** — Submit a ticket at cloud.digitalocean.com requesting GPU Droplet access. Mention you need a single `gpu-h100x1-80gb` for inference. This takes ~1-2 business days.

2. **Create a personal access token** — DO control panel → API → Tokens → Generate. Save as `DO_API_TOKEN`.

3. **Add SSH key** — DO control panel → Settings → Security → Add the public key from `~/.ssh/id_ed25519.pub`. Copy the fingerprint (run `ssh-keygen -lf ~/.ssh/id_ed25519.pub`).

4. **Provision a one-time GPU droplet** to set up the golden image:
   ```bash
   # Spin up manually from DO control panel:
   #   Name: coln-llm-setup
   #   Region: London (lon1)
   #   Size: GPU H100x1 (gpu-h100x1-80gb)
   #   Image: Ubuntu 24.04
   #   SSH key: your key from step 3
   
   # SSH in and run the setup script:
   ssh root@<temp-ip>
   # Install curl first:
   apt-get update && apt-get install -y curl
   # Download and run setup:
   curl -sL https://raw.githubusercontent.com/m8y2/colnRG/main/backend/llm_cleanup/setup_gpu.sh | bash
   ```

5. **Create a snapshot** — DO control panel → Droplets → coln-llm-setup → Snapshots → "Take Snapshot". Name it `coln-llm-cleanup-v1`. Wait for completion (~5 min). Note the snapshot ID (from the URL when viewing it). Destroy the temporary droplet.

6. **Set environment variables** on the main droplet:
   ```bash
   # Add to /etc/environment or the systemd service file:
   DO_API_TOKEN=<your-token>
   GPU_SNAPSHOT_ID=<snapshot-id>
   SSH_KEY_FINGERPRINT=<your-ssh-key-fingerprint>
   ```

7. **Install the systemd timer** for the poller:
   ```bash
   # Create /etc/systemd/system/coln-llm-poller.service:
   cat > /etc/systemd/system/coln-llm-poller.service << 'EOF'
   [Unit]
   Description=LLM data cleaning poller
   After=network-online.target
   
   [Service]
   Type=oneshot
   Environment="DO_API_TOKEN=<your-token>"
   Environment="GPU_SNAPSHOT_ID=<snapshot-id>"
   Environment="SSH_KEY_FINGERPRINT=<fingerprint>"
   WorkingDirectory=/opt/coln-dashboard/backend
   ExecStart=/opt/coln-dashboard/backend/llm_cleanup/gpu_poller.py
   EOF
   
   # Create /etc/systemd/system/coln-llm-poller.timer:
   cat > /etc/systemd/system/coln-llm-poller.timer << 'EOF'
   [Unit]
   Description=Run LLM poller every 2 hours
   
   [Timer]
   OnCalendar=*-*-* *:00:00
   Persistent=true
   
   [Install]
   WantedBy=timers.target
   EOF
   
   systemctl daemon-reload
   systemctl enable --now coln-llm-poller.timer
   ```

### Cost Estimate

| Item | Cost |
|---|---|
| GPU droplet runtime: ~5 min every 2 hours | ~$0.09/day, ~$2.70/month |
| Snapshot storage (10 GB) | ~$0.05/month |
| **Total** | **~$2.75/month** |

The poller checks every 2 hours but only spins up the GPU droplet when new entries actually exist. If no new data, cost is $0.

## No tests

No test framework or test files exist.
