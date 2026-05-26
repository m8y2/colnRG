#!/usr/bin/env bash
# Paste this into the DigitalOcean "Startup Scripts" field when creating
# the droplet. Runs once on first boot: installs Ollama, pulls a tiny
# model, and starts the service.
#
# Uses llama3.2:1b — a 1.2B param model (~800MB) that comfortably fits in
# 4 GB RAM and runs reasonably fast on CPU.

set -euo pipefail

exec > /var/log/llm-setup.log 2>&1

echo "=== Installing Ollama ==="
apt-get update -qq
apt-get install -y -qq curl

curl -fsSL https://ollama.com/install.sh | sh

echo "=== Pulling model llama3.2:1b ==="
ollama pull llama3.2:1b

echo "=== Ensuring Ollama is running ==="
systemctl enable ollama
systemctl start ollama

echo "=== Setup complete ==="
