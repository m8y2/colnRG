#!/usr/bin/env bash
# Paste this into the DigitalOcean "Startup Scripts" field when creating
# the droplet. Runs once on first boot: installs Ollama, pulls a tiny
# model, and starts the service.
#
# Uses llama3.2:1b — a 1.2B param model (~800MB) that comfortably fits in
# 4 GB RAM and runs reasonably fast on CPU.

set -euo pipefail

exec > /var/log/llm-setup.log 2>&1

export HOME=/root

echo "=== Installing Ollama ==="
apt-get update -qq
apt-get install -y -qq curl

curl -fsSL https://ollama.com/install.sh | sh

# Start Ollama manually since systemd isn't ready during cloud-init
echo "=== Starting Ollama server ==="
nohup ollama serve > /var/log/ollama.log 2>&1 &
sleep 3

echo "=== Pulling model llama3.2:1b ==="
ollama pull llama3.2:1b

# Manually enable the service for future boots (systemctl not available in cloud-init)
echo "=== Enabling Ollama for future boots ==="
ln -sf /etc/systemd/system/ollama.service /etc/systemd/system/default.target.wants/ollama.service 2>/dev/null || true

echo "=== Setup complete ==="
