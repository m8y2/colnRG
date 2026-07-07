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

## Lessons learnt — CSS architecture

**The inline `<style>` block in `frontend/index.html` is the production CSS, NOT `src/index.css`.**

The build (`npm run build`) copies `index.html` as-is into `dist/` — it does NOT generate the inline CSS from `src/index.css`. Changes to `src/index.css` only affect `npm run dev`, not the deployed site. Always edit the inline CSS in `index.html` for production changes, then rebuild.

When working on the beta-group tabs:
- `.tab.active` applies the blue `border-bottom-color: var(--primary)` underline
- To avoid the underline on beta tabs, use a separate class (e.g. `beta-active`) instead of `active`, so `.tab.active` doesn't match
- The beta-group box styling (border, badge) is defined in the inline CSS in `index.html` — edit there, not just `src/index.css`

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
| `frontend/index.html` | Inline CSS (no separate CSS request) to avoid render-blocking |
| `frontend/public/robots.txt` | Points to sitemap |
| `frontend/public/sitemap.xml` | Single-URL sitemap for SEO |
| `frontend/src/components/OverviewChart.jsx` | Lazy-loaded overview chart wrapper (code-splits recharts) |

## PageSpeed / Performance notes

- CSS is inlined in `index.html` (not imported via JS) to eliminate render-blocking CSS requests
- `OverviewChart.jsx` is a separate lazy-loaded chunk that defers recharts (350KB) until the overview tab renders
- `robots.txt` + `sitemap.xml` exist in `public/` for SEO
- All components use `React.lazy()` + `Suspense` for code splitting
- Build output is deployed to `/opt/coln-dashboard/frontend/dist/` on the droplet

## Deploy

> Verified against the live droplet 2026-06-18. `MIGRATION.md` (in the parent folder) is the source of truth for infra and supersedes this section.

| | |
|---|---|
| **URL** | `https://www.colnrg.app` (canonical). `http://161.35.168.168/` 301-redirects here. |
| **Droplet** | Ubuntu 24.04, 1vCPU/512MB, London; IP `161.35.168.168` |
| **SSH** | `ssh -i ~/.ssh/id_ed25519 root@161.35.168.168` |
| **SSL** | Sectigo cert on :443. `:80` → 301 to `https://www.colnrg.app`. |
| **Frontend** | Served by nginx from `/opt/coln-dashboard/frontend/dist/` |
| **Backend** | FastAPI behind nginx proxy `/api` → `127.0.0.1:8000`, 1 uvicorn worker (required for in-memory report queue) |
| **Auto-start** | nginx + coln-api.service + coln-sync.timer (daily 06:00) all systemd-enabled |
| **Swap** | 1GB swapfile added for `npm run build` (512MB RAM is tight) |
| **Build locally, rsync** | `npm run build && rsync -e 'ssh -i ~/.ssh/id_ed25519' -avz dist/ root@161.35.168.168:/opt/coln-dashboard/frontend/dist/` (run from `frontend/`) |
| **Re-deploy after changes** | `ssh root@161.35.168.168 'cd /opt/coln-dashboard && git pull && systemctl restart coln-api.service'` + rebuild/rsync frontend |

**The repo's `deploy/nginx.conf` is HTTP-only and will NOT reproduce HTTPS.** The live `/etc/nginx/sites-enabled/coln-dashboard` differs (Sectigo cert, :80→:443 redirect, security/injection headers). See `MIGRATION.md` "Live nginx config" for the real config and cert-restore steps.

## LLM-based data cleaning pipeline

New entries are cleaned by an LLM running on an ephemeral DigitalOcean CPU droplet (s-2vcpu-4gb, llama3.2:1b).

### Architecture

```
Main droplet ($6/mo)                     LLM droplet ($32/mo, ~$0.05/hr, ephemeral)
┌──────────────────────┐                 ┌──────────────────────────────┐
│  gpu_poller.py        │──DO API spin──→│  Ollama + llama3.2:1b       │
│  (runs as systemd     │──SCP raw JSON──→│  gpu_worker.py              │
│   timer, e.g. hourly) │←──SCP cleaned──│                             │
│                       │──DO API kill──→│  (destroyed after use)       │
└──────────────────────┘                 └──────────────────────────────┘
```

1. `gpu_poller.py` checks EpiCollect for entries uploaded since last sync
2. If new entries found, calls DO API to spin up a CPU droplet from a pre-built snapshot
3. SCPs raw entry data + worker script to the droplet
4. SSH runs `gpu_worker.py` which sends each entry through Ollama (llama3.2:1b)
5. LLM returns cleaned JSON for each entry
6. Cleaned data SCP'd back, inserted into SQLite
7. Droplet destroyed

### Files

| File | Role | Runs on |
|---|---|---|
| `backend/llm_cleanup/gpu_poller.py` | Orchestrator — polls EpiCollect, spins droplets, copies data | Main droplet (systemd timer) |
| `backend/llm_cleanup/gpu_worker.py` | Sends each entry to Ollama, parses LLM response | LLM droplet (ephemeral) |
| `backend/llm_cleanup/prompt_template.py` | The cleaning prompt sent to the LLM | Included in gpu_worker.py |
| `backend/llm_cleanup/setup_llm_droplet.sh` | Startup script for the LLM droplet (install Ollama + pull model) | LLM droplet (one-time) |

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

1. **Create a personal access token** — DO control panel → API → Tokens → Generate. Save as `DO_API_TOKEN`.

2. **Add SSH key** — DO control panel → Settings → Security → Add the public key from `~/.ssh/id_ed25519.pub`. Copy the fingerprint (run `ssh-keygen -lf ~/.ssh/id_ed25519.pub`).

3. **Provision a one-time droplet** to set up the golden image:
   - Create a droplet from DO control panel with these settings:
     - Name: `coln-llm-setup`
     - Region: London (lon1)
     - Size: Basic → Premium Intel → s-2vcpu-4gb-120gb-intel ($32/mo)
     - Image: Ubuntu 24.04
     - SSH key: your key from step 2
     - Startup script: paste the contents of `backend/llm_cleanup/setup_llm_droplet.sh` into the "Add startup script" field
   - Boot it. The startup script installs Ollama and pulls `llama3.2:1b`. Run `tail -f /var/log/llm-setup.log` to check progress.
   - Once done, verify: `ollama list` should show `llama3.2:1b`.

4. **Create a snapshot** — DO control panel → Droplets → coln-llm-setup → Snapshots → "Take Snapshot". Name it `coln-llm-cleanup-v1`. Wait for completion (~5 min). Note the snapshot ID (from the URL when viewing it). Destroy the temporary droplet.

5. **Set environment variables** on the main droplet:
   ```bash
   # Add to /etc/environment or the systemd service file:
   DO_API_TOKEN=<your-token>
   DROPLET_SNAPSHOT_ID=<snapshot-id>
   SSH_KEY_FINGERPRINT=<your-ssh-key-fingerprint>
   ```

6. **Install the systemd timer** for the poller:
   ```bash
   # Create /etc/systemd/system/coln-llm-poller.service:
   cat > /etc/systemd/system/coln-llm-poller.service << 'EOF'
   [Unit]
   Description=LLM data cleaning poller
   After=network-online.target
   
   [Service]
   Type=oneshot
   Environment="DO_API_TOKEN=<your-token>"
   Environment="DROPLET_SNAPSHOT_ID=<snapshot-id>"
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
| Droplet runtime: ~5 min every 2 hours | ~$0.05/day, ~$1.50/month |
| Snapshot storage (10 GB) | ~$0.05/month |
| **Total** | **~$1.55/month** |

The poller checks every 2 hours but only spins up the droplet when new entries actually exist. If no new data, cost is $0.

## LLM report generation

On-demand site and round reports are generated by the same LLM droplet infrastructure.

### How it works

User clicks "Generate" in the Site Report or Round Report tab → `POST /api/reports/site/generate?site=XXX` → `report_generator.py` spins up a droplet, copies worker + data, runs `report_worker.py` against Ollama, stores result in SQLite, destroys droplet. The frontend polls until the report appears.

### Files

| File | Role |
|---|---|
| `backend/llm_cleanup/report_prompts.py` | Two prompt templates: `SITE_REPORT_PROMPT` + `ROUND_REPORT_PROMPT` |
| `backend/llm_cleanup/report_worker.py` | Droplet-side script: reads JSON request from stdin, queries Ollama, prints report to stdout |
| `backend/llm_cleanup/report_generator.py` | Orchestrator — spins droplet, copies worker, builds data context, stores report in DB, destroys droplet |
| `frontend/src/components/ReportViewer.jsx` | Reusable report viewer with version history dropdown + generate button |
| `frontend/src/components/SiteReport.jsx` | Tab: site selector + ReportViewer for site reports |
| `frontend/src/components/RoundReport.jsx` | Tab: round selector + ReportViewer for round reports |

### API endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/reports/site?site=XXX` | GET | Latest site report (add `&version=N` for specific) |
| `/api/reports/site/versions?site=XXX` | GET | List all versions for a site |
| `/api/reports/site/generate?site=XXX` | POST | Trigger site report generation (async) |
| `/api/reports/round?round_label=Round%20N` | GET | Latest round report |
| `/api/reports/round/versions?round_label=Round%20N` | GET | List all versions for a round |
| `/api/reports/round/generate?round_label=Round%20N&round_start=YYYY-MM-DD&round_end=YYYY-MM-DD` | POST | Trigger round report generation (async) |

### Database tables

- `site_reports(id, site_code, generated_at, report_text, version)` — indexed on `(site_code, version)`
- `round_reports(id, round_label, round_start, round_end, generated_at, report_text, version)` — indexed on `(round_label, version)`

### Report prompts

**Site report**: LLM receives all entries for a site (date, chemical levels, landowner, notes) plus WFD thresholds. Produces 3-5 paragraph prose summary covering location, WFD band assessment, trends, notable dates, landowner.

**Round report**: LLM receives all entries across all sites for a round plus averages and previous-round comparison data. Produces 4-6 paragraph prose covering round overview, WFD bands, round-to-round changes, standout sites.

### Caveats

- The `chemical` param on `/api/rounds` is optional — omit it to list rounds without chemical data
- Report generation takes 2-5 min (droplet spin-up + Ollama inference)
- The droplet is destroyed after each generation (ephemeral)
- Uses the same snapshot (`coln-llm-cleanup-v1`) as the data cleaning pipeline

## Private API (key-authenticated)

External sites can request and retrieve reports via a key-authenticated API. Keys are generated by the admin only.

### Authentication

All requests require an `X-Api-Key` header:

```
X-Api-Key: YOUR_API_KEY
```

### Admin keys

Set the `ADMIN_API_KEY` environment variable on the droplet to authorize key management.

### Managing API keys

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/admin/keys/generate?admin_key=ADMIN_KEY&label=NAME` | Generate a new API key |
| GET | `/api/v1/admin/keys/list?admin_key=ADMIN_KEY` | List all keys |
| POST | `/api/v1/admin/keys/revoke?admin_key=ADMIN_KEY&key_id=ID` | Revoke a key (disable) |

### Using the API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/reports/site?site=XXX` | Get latest site report |
| GET | `/api/v1/reports/round?round_label=Round%20N` | Get latest round report |
| POST | `/api/v1/reports/site/generate?site=XXX` | Trigger site report generation |
| POST | `/api/v1/reports/round/generate?round_label=Round%20N&round_start=YYYY-MM-DD&round_end=YYYY-MM-DD` | Trigger round report generation |

### Example usage

```bash
# Generate a new API key
curl -X POST "https://161.35.168.168/api/v1/admin/keys/generate?admin_key=ADMIN_KEY&label=my-app"

# Get the latest PW site report
curl -H "X-Api-Key: YOUR_KEY" "https://161.35.168.168/api/v1/reports/site?site=PW"

# Trigger PW report generation  
curl -X POST -H "X-Api-Key: YOUR_KEY" "https://161.35.168.168/api/v1/reports/site/generate?site=PW"

# Get Round 6 report
curl -H "X-Api-Key: YOUR_KEY" "https://161.35.168.168/api/v1/reports/round?round_label=Round%206"

# List all API keys (admin only)
curl "https://161.35.168.168/api/v1/admin/keys/list?admin_key=ADMIN_KEY"
```
