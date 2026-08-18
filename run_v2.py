#!/usr/bin/env python3
"""Local dev orchestrator for v2: run the v2 API (uvicorn main_v2:app on
:8000 — this serves v1's routes too, since main_v2 mounts the v2 router
onto the same v1 `app`) and the v2 frontend (Vite dev server on :5174)
together.

Modelled on the existing Dashboard/run.py (v1), but deliberately simpler:
it does not sync EpiCollect5 data, does not install dependencies, and does
not open a browser tab. It assumes `backend/venv` and
`frontend-v2/node_modules` already exist — set them up once with:

    cd backend && python3 -m venv venv && venv/bin/python -m pip install -r requirements.txt
    cd frontend-v2 && npm install

v1's run.py is untouched; run this script instead when working on v2.
"""

import os
import shutil
import signal
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND_V2 = os.path.join(ROOT, "frontend-v2")

VENV_PY = os.path.join(BACKEND, "venv", "bin", "python")
BACKEND_PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable

NODE = shutil.which("node") or "/usr/local/opt/node@22/bin/node"
VITE_BIN = os.path.join(FRONTEND_V2, "node_modules", ".bin", "vite")

PROCS = []


def log(msg):
    print(f"\n>>> {msg}", flush=True)


def start_backend():
    log("Starting v2 API server (v1 + v2 routes) on http://localhost:8000 …")
    p = subprocess.Popen(
        [BACKEND_PY, "-m", "uvicorn", "main_v2:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=BACKEND,
    )
    PROCS.append(p)
    return p


def start_frontend():
    log("Starting v2 frontend dev server on http://localhost:5174 …")
    p = subprocess.Popen(
        [NODE, VITE_BIN, "--host", "127.0.0.1", "--port", "5174"],
        cwd=FRONTEND_V2,
    )
    PROCS.append(p)
    return p


def cleanup(sig=None, frame=None):
    log("Shutting down…")
    for p in PROCS:
        p.terminate()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if not os.path.exists(BACKEND_PY):
        log(f"No backend Python found at {BACKEND_PY}.\n"
            f"    Set up the backend venv first:\n"
            f"      cd backend && python3 -m venv venv && venv/bin/python -m pip install -r requirements.txt")
        sys.exit(1)
    if not os.path.exists(VITE_BIN):
        log(f"frontend-v2 dependencies not found ({VITE_BIN} missing).\n"
            f"    Run: cd frontend-v2 && npm install")
        sys.exit(1)

    start_backend()
    start_frontend()

    log("Both v2 dev servers are running.")
    print("  Backend (v1 + v2 API) → http://127.0.0.1:8000")
    print("  Frontend v2           → http://127.0.0.1:5174/v2/")
    print("  Press Ctrl+C to stop both.\n")

    try:
        for p in PROCS:
            p.wait()
    except KeyboardInterrupt:
        cleanup()
