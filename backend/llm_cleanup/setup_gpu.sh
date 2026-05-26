#!/usr/bin/env bash
# Run ONCE on the GPU droplet to set it up for LLM data cleaning.
# After this completes, create a DigitalOcean snapshot of the droplet.
# Then use that snapshot ID as GPU_SNAPSHOT_ID in gpu_poller.py.

set -euo pipefail

echo "=== Updating system ==="
apt-get update -qq
apt-get install -y -qq python3 python3-pip curl

echo "=== Installing Ollama ==="
curl -fsSL https://ollama.com/install.sh | sh

echo "=== Pulling model ==="
ollama pull llama3.1:8b

echo "=== Verifying Ollama serves queries ==="
sleep 3
ollama run llama3.1:8b "Respond with just: OK" 2>/dev/null | head -5

echo "=== Installing Python dependencies ==="
pip3 install requests -q

echo "=== Copying worker script ==="
mkdir -p /root
# gpu_worker.py and prompt_template.py should be SCP'd here
# by gpu_poller.py at runtime, so they don't need to be in the snapshot.

echo ""
echo "Setup complete. Create a snapshot of this droplet from the DO control panel."
echo "Snapshot name suggestion: coln-llm-cleanup-v1"
echo ""
echo "Then set these env vars on the main droplet:"
echo "  DO_API_TOKEN=<your-do-api-token>"
echo "  GPU_SNAPSHOT_ID=<snapshot-id-from-above>"
echo "  SSH_KEY_FINGERPRINT=<your-ssh-key-fingerprint>"
