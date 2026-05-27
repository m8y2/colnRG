#!/usr/bin/env python3
"""Runs on the LLM droplet. Reads a JSON request from stdin and writes
the generated report text to stdout.

Input JSON format:
{
  "type": "site" or "round",
  "system": "..."  # rules and instructions (sent as Ollama system message)
  "prompt": "..."  # data and context (sent as Ollama prompt)
}

Output: plain text report to stdout.
"""

import json
import sys
import urllib.request

MODEL = "llama3.2:1b"
OLLAMA_URL = "http://localhost:11434/api/generate"


def query_ollama(prompt, system=None):
    body = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 1024},
    }
    if system:
        body["system"] = system
    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        result = json.loads(resp.read().decode())
        return result.get("response", "").strip()


def main():
    raw = sys.stdin.read()
    request = json.loads(raw)

    prompt = request["prompt"]
    system = request.get("system", "")
    report_type = request.get("type", "unknown")

    print(f"Generating {report_type} report...", file=sys.stderr)

    response = query_ollama(prompt, system=system)

    if not response:
        print("LLM returned empty response", file=sys.stderr)
        sys.exit(1)

    print(response)


if __name__ == "__main__":
    main()
