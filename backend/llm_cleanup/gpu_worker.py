#!/usr/bin/env python3
"""Runs on the GPU droplet. Reads raw entries from stdin (JSON array),
cleans each one via the LLM, and writes cleaned entries to stdout (JSON array).

Usage: cat raw_entries.json | python3 gpu_worker.py > cleaned_entries.json

The script:
1. Sends each entry to Ollama with a custom cleaning prompt
2. Parses the JSON response
3. Writes cleaned entries

Requires: pip install requests
"""

import json
import sys
import re
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"

FIELD_PROMPT = """
Rules for each field:

### phosphate_level (mg/L)
Typical range: 0.00-1.00. Values > 1.5 are suspect.
- If > 2.0, likely a decimal shift — divide by 10 (e.g. 2.5→0.25).
- Letter O is typo for zero: "O.23" → "0.23".
- Text like "clear", "cloudy" were entered in wrong field — set to null.

### ammonia_level (mg/L)
Typical range: 0.00-1.00. Values > 2.0 are suspect.
- If > 2.5 AND site's other readings are < 1.0, divide by 10 (e.g. 3.0→0.3).
- Text descriptions → null.

### nitrate_level (mg/L)
Typical range: 0-50. Max valid: 100 (test kit limit).
- Values > 100 are errors. "5ppm" → "5". Text → null.

### turbidity (NTU)
Numeric range: 0-100. Text map: crystal clear=0, very clear=1, clear=2,
almost clear=3, slightly cloudy=15, cloudy=30, very cloudy=50, murky=60.
"nil"=0, "n/a"=null.

### dissolved_oxygen (mg/L)
Range: 5-15 typical. Outside 0-30 → suspect. Text → null.
Almost never recorded — null is fine.

### conductivity (µS/cm)
Range: 300-1200 typical. Outside 0-3000 → suspect. Text → null.
Almost never recorded — null is fine.

### water_depth_cm
Range: 5-200 typical. Outside 0-500 → suspect.

### landowner
Canonical names only: Whittington Estate, Rupert Lowe, Rose Vestey,
Chris Daniels, Chris Wright, National Trust, Stowell Park, Talbot Rice,
Blackwell, Bruno, Charles Levinson, David Gibbs, Edwin Bailey,
Ernest Cook Trust.
Set to null if: N/A, n/a, Not known, Yes, Public, Mixed, MH, OB, or free text.

### w3w_site_code
If w3w field ends with a known code (e.g. "arching.probably.stickler PW"
ends with "PW"), use that code. Known codes:
EP, PW, SJR, MG, KH, NL, ST/LAT, CS, WMW, GED, DFG, GDR, CAK, JD, SM,
HB, DD, MH, TJ, PIC, DC, DK, OB, PT/M, PT

### comments_1 / comments_2 / comments_3
"Nil", "N/A", "n/a" → null. "Wittington" → "Whittington".
Preserve everything else verbatim.

### title
If it's a w3w address + date (e.g. "traffic.reclaimed.ringers 08/06/2025 19:10"),
extract just the date portion.
If it's already a date like "07/12/2025", keep it.

### phosphate_high / nitrate_high
Only "Yes" or "No" are valid. Anything else → null.
"""


def query_ollama(entry_text):
    system_msg = (
        "You are a water-quality data validator for the River Coln citizen-science "
        "project. Clean the submitted entry data. Return ONLY valid JSON."
    )

    prompt = (
        f"Clean this water-quality entry and return a JSON object with corrected fields. "
        f"Include ALL fields from the input, even if unchanged. "
        f"Add an 'explanation' field describing any changes made.\n\n"
        f"Input entry:\n```\n{entry_text}\n```\n\n"
        f"{FIELD_PROMPT}\n\n"
        f"Return ONLY the JSON object."
    )

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "system": system_msg,
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 2000,
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())

    text = result.get("response", "")
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return None


def format_entry(e):
    lines = [
        f"Date: {e.get('sample_date', '')}",
        f"Time: {e.get('sample_time', '')}",
        f"Site: {e.get('w3w_site_code', '')}",
        f"w3w: {e.get('w3w', '')}",
        f"w3w_other: {e.get('w3w_other', '')}",
        f"Landowner: {e.get('landowner', '')}",
        f"Title: {e.get('title', '')}",
        f"Water depth (cm): {e.get('water_depth_cm', '')}",
        f"Phosphate (mg/L): {e.get('phosphate_level', '')}",
        f"Ammonia (mg/L): {e.get('ammonia_level', '')}",
        f"Nitrate (mg/L): {e.get('nitrate_level', '')}",
        f"Turbidity: {e.get('turbidity', '')}",
        f"Dissolved oxygen: {e.get('dissolved_oxygen', '')}",
        f"Conductivity: {e.get('conductivity', '')}",
        f"Phosphate high: {e.get('phosphate_high', '')}",
        f"Nitrate high: {e.get('nitrate_high', '')}",
        f"Comments 1: {e.get('comments_1', '')}",
        f"Comments 2: {e.get('comments_2', '')}",
        f"Comments 3: {e.get('comments_3', '')}",
    ]
    return "\n".join(lines)


def main():
    raw_entries = json.load(sys.stdin)
    cleaned = []

    for i, entry in enumerate(raw_entries):
        entry_text = format_entry(entry)
        print(f"Processing entry {i + 1}/{len(raw_entries)}: {entry.get('ec5_uuid', '?')[:12]}...",
              file=sys.stderr)

        result = query_ollama(entry_text)
        if result:
            result["ec5_uuid"] = entry["ec5_uuid"]
            result["sample_date"] = entry["sample_date"]
            result["sample_time"] = entry["sample_time"]
            cleaned.append(result)
            print(f"  → {result.get('explanation', 'no changes')}", file=sys.stderr)
        else:
            print(f"  → LLM returned invalid JSON, keeping original", file=sys.stderr)
            cleaned.append(entry)

    json.dump(cleaned, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
