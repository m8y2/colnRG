"""Shared data-cleaning utilities for EpiCollect import."""

import re

TURBIDITY_MAP = {
    "crystal clear": 0, "very clear": 1, "water very clear": 1,
    "clear": 2, "clear water": 2, "almost clear": 3,
    "pretty clear": 4, "fairly clear": 5, "quite clear": 6,
    "clearer than last month": 3,
    "fresh": 5, "low": 5,
    "slight": 10, "slightly cloudy": 15, "slight cloudiness": 15,
    "slightly turbid": 15, "slightly opaque": 15, "slightly murky": 15,
    "hazy": 15,
    "a little cloudy": 20, "fairly cloudy": 25,
    "cloudy": 30, "quite cloudy": 35, "medium": 30,
    "somewhat cloudy": 30,
    "so cloudy": 50, "very cloudy": 50, "very dark": 55,
    "murky": 60, "muddy": 70,
    "high": 50, "in spate": 50,
    "nil": 0, "n/a": None, "n/k": None, "nk": None, "x": None,
    "not measured": None, "": None,
}

UNIT_RE = re.compile(r"(?i)\s*(ppm|mg/l|mg|no3|nitrates|µs/cm|us/cm|ntu|cm)\s*$")
RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[–-]\s*(\d+(?:[.,]\d+)?)")


def clean_numeric(val):
    if val is None or val == "":
        return None
    val = str(val).strip()

    low = val.lower().strip()
    if low in TURBIDITY_MAP:
        return TURBIDITY_MAP[low]

    if any(word in low for word in
           ["clear", "cloud", "murky", "muddy", "turbid", "opaque",
            "spate", "foam", "hazy"]):
        for key, num in sorted(TURBIDITY_MAP.items(), key=lambda x: -len(x[0])):
            if key in low:
                return num
        return None

    val = UNIT_RE.sub("", val).strip()
    val = re.sub(r"(?<!\w)O(?!\w)", "0", val)
    val = val.replace("O.", "0.").replace("O,", "0,")
    val = val.replace(",", ".")
    val = re.sub(r"(\d)\s+(\d)", r"\1\2", val)

    m = RANGE_RE.search(val)
    if m:
        try:
            lo = float(m.group(1).replace(",", "."))
            hi = float(m.group(2).replace(",", "."))
            return round((lo + hi) / 2, 2)
        except ValueError:
            pass

    less = re.search(r"(?i)(?:less than|<)\s*(\d+(?:[.,]\d+)?)", val)
    if less:
        try:
            return float(less.group(1).replace(",", ".")) / 2
        except ValueError:
            pass

    try:
        return float(val)
    except ValueError:
        return None
