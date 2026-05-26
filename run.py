#!/usr/bin/env python3
"""One command to run the full Coln River Guardians pipeline:
   sync from EpiCollect → start API server → start frontend"""

import subprocess, sys, os, time, webbrowser, signal

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")
VENV_PY = os.path.join(BACKEND, "venv", "bin", "python")
NODE22 = "/usr/local/opt/node@22/bin/node"
PROCS = []

def log(msg):
    print(f"\n>>> {msg}", flush=True)

def pip_install():
    log("Installing Python dependencies…")
    subprocess.run([VENV_PY, "-m", "pip", "install", "-q",
                    "-r", os.path.join(BACKEND, "requirements.txt")],
                   cwd=BACKEND, check=True)

def npm_install():
    log("Installing frontend dependencies…")
    subprocess.run(["/usr/local/opt/node@22/bin/npm", "install", "--silent"],
                   cwd=FRONTEND, check=True)

def do_sync():
    log("Syncing data from EpiCollect5…")
    subprocess.run([VENV_PY, "-c", """
import sys; sys.path.insert(0, ".")
from database import init_db
from sync import run_sync
init_db()
result = run_sync()
print(f"  → {result}")
"""], cwd=BACKEND, check=True)

def clean_data():
    log("Cleaning data…")
    subprocess.run([VENV_PY, "-c", """
import sys; sys.path.insert(0, ".")
from clean_data import main; main()
"""], cwd=BACKEND)

def start_backend():
    log("Starting API server on http://localhost:8000 …")
    p = subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "main:app",
         "--host", "0.0.0.0", "--port", "8000", "--reload"],
        cwd=BACKEND)
    PROCS.append(p)
    return p

def start_frontend():
    log("Starting frontend dev server…")
    p = subprocess.Popen(
        [NODE22, os.path.join(FRONTEND, "node_modules", ".bin", "vite"),
         "--host", "127.0.0.1"],
        cwd=FRONTEND)
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

    pip_install()
    npm_install()
    do_sync()
    clean_data()
    start_backend()
    time.sleep(2)
    start_frontend()
    log("Opening Chrome…")
    subprocess.Popen(["open", "-a", "Google Chrome", "http://127.0.0.1:5173"])

    log("Both servers are running.")
    print("  Backend  → http://127.0.0.1:8000")
    print("  Frontend → http://127.0.0.1:5173")
    print("  Press Ctrl+C to stop both.\n")

    try:
        for p in PROCS:
            p.wait()
    except KeyboardInterrupt:
        cleanup()
