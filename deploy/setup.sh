#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/coln-dashboard"
REPO_URL="${1:-}"  # pass git repo URL as first arg, or run from local copy

echo "=== Coln River Guardians — VPS Setup ==="

# --- System dependencies ---
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx nodejs npm curl

# --- Create app user ---
id -u www-data &>/dev/null || useradd -r -s /bin/false www-data

# --- Clone or copy code ---
if [ -n "$REPO_URL" ]; then
    apt-get install -y git
    git clone "$REPO_URL" "$APP_DIR"
else
    # script expects to be run from the repo root (or files already at APP_DIR)
    mkdir -p "$APP_DIR"
    cp -r "$(dirname "$0")/.." "$APP_DIR"
fi

cd "$APP_DIR"

# --- Permissions ---
chown -R www-data:www-data backend
chmod 755 backend

# --- Backend ---
echo "Setting up Python virtual environment..."
python3 -m venv backend/venv
backend/venv/bin/pip install --upgrade pip
backend/venv/bin/pip install -r backend/requirements.txt

# --- Frontend ---
echo "Building frontend..."
cd frontend
npm ci
npm run build
cd "$APP_DIR"

# --- Install systemd services ---
echo "Installing systemd services..."
cp deploy/coln-api.service /etc/systemd/system/coln-api.service
cp deploy/coln-sync.service /etc/systemd/system/coln-sync.service
cp deploy/coln-sync.timer /etc/systemd/system/coln-sync.timer
systemctl daemon-reload

# --- Initial sync ---
echo "Running initial sync..."
systemctl start coln-sync.service
# wait for sync to finish
while systemctl is-active --quiet coln-sync.service; do sleep 2; done

# --- Enable services ---
systemctl enable coln-api.service
systemctl start coln-api.service
systemctl enable coln-sync.timer
systemctl start coln-sync.timer

# --- Nginx ---
echo "Configuring nginx..."
rm -f /etc/nginx/sites-enabled/default
cp deploy/nginx.conf /etc/nginx/sites-available/coln-dashboard
ln -sf /etc/nginx/sites-available/coln-dashboard /etc/nginx/sites-enabled/
nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "=== Setup complete ==="
echo "  Backend:  http://$(curl -s ifconfig.me)/api/health"
echo "  Frontend: http://$(curl -s ifconfig.me)/"
