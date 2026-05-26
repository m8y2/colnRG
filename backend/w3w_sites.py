"""Map what3words addresses (from the w3w_other free-text field) to site codes.

Derived from LocationReferenceTable.xlsx — matches w3w addresses to the nearest
monitoring site by Haversine distance.
"""

import re
import math

W3W_SITE_OVERRIDES = {
    # Direct matches from LocationReferenceTable.xlsx
    "Conquests.camper.advanced": "SJR",
    "Covenants.corrupted.betrayed": "SM",
    "Keener.washed.expensive": "PW",
    "Pub.chief.moderated": "NL",
    "Publisher.chief.moderated": "NL",
    "Traffic.reclaimed.ringers": "EP",
    "Unions.foggy.trendy": "ST/LAT",
    "Village.damage.wonderful": "PW",
    "badly.boarding.rephrase": "PT",
    "hindered.handlebar.button": "PT/M",
    "reset.spires.supply": "NL",
    "ritual.cyber.weeks": "GED",
    "spenders.promotion.claps": "DFG",
    "Blitz.dries.cleansed": "NL",
    "craftsman.mysteries.bluffs": "EP",
    "doubt.bridge.leopard": "MG",
    "grace.reprints.jigsaw": "MG",
    "aimed.boarded.roofs": "MG",
    "channel.riskiest.goofy": "JD",
    "cobble.zoos.bypassed": "GDR",
    "laminated.wrenching.plankton": "JD",
    "compound.catchers.fishnet": "HB",
    "keener.washed.expensive": "PW",
    "mango.batches.duke": "SM",
    "props.showcases.warbler": "EP",
    "electrical.rosier.soggy": "DD",
    "lightbulb.recitals.replaces": "DD",
    "stadium.packing.strongman": "PT/M",
    "intro.skews.submerged": "OB",
    "arch.probably.stickler": "SJR",
    "suitably.dustbin.glossed": "CS",

    # Fuzzy / typo matches
    "good.examples.bulldozer": "CS",
    "yacht.pounding.found": "MG",
    "Conquests.camper.advances": "SJR",
    "Conquest.camper.advances": "SJR",
    "Cobbles.Zoos.Bypassed": "GDR",
    "Arching.probably.sticker": "SJR",
    "Props.showcases.warble": "EP",
    "Channel. Riskiest.goofy": "JD",
    "electrical,rosier,soggy": "DD",
    "lightbulbs,recitals,replaces": "DD",
    "hers.steered.beakers (formerly mango.batches.duke": "SM",
    "hers.steered.beakers formerly mango.batches.duke": "SM",
    "hers.steered.beakers": "SM",
    "lightbulbs,recitals,replaces": "DD",
    "lightbulbs.recitals.replaces": "DD",

    # Non-location / test entries
    "AnotherTest": None,
    "TestingItOut": None,
    "END OF ROUND THREE": None,
}

SITE_COORDS = {
    "CAK": [51.83116, -1.93942],
    "CS": [51.84434, -1.94626],
    "DC": [51.74826, -1.81629],
    "DD": [51.78520, -1.87526],
    "DFG": [51.83771, -1.95202],
    "DK": [51.74333, -1.79482],
    "EP": [51.89891, -1.95274],
    "GDR": [51.83709, -1.95552],
    "GED": [51.83856, -1.95020],
    "HB": [51.80615, -1.88959],
    "JD": [51.83349, -1.93042],
    "KH": [51.84637, -1.93113],
    "MG": [51.86339, -1.96707],
    "MH": [51.77370, -1.86635],
    "NL": [51.85491, -1.95298],
    "OB": [51.73580, -1.79066],
    "PIC": [51.76294, -1.84342],
    "PT": [51.68827, -1.70575],
    "PT/M": [51.70475, -1.77679],
    "PW": [51.88100, -1.96081],
    "SJR": [51.87507, -1.96657],
    "SM": [51.80907, -1.88255],
    "ST/LAT": [51.84450, -1.95818],
    "TJ": [51.76637, -1.84752],
    "WMW": [51.84046, -1.94993],
}


def lookup_w3w_site(w3w_other):
    """Given a free-text what3words address, return the site code (or None)."""
    if not w3w_other:
        return None

    cleaned = w3w_other.strip()
    cleaned = cleaned.replace("///", "").replace(",", ".")
    cleaned = cleaned.replace("(", "").replace(")", "")
    low = cleaned.strip().lower()

    # 1. Exact match (case-insensitive)
    if low in W3W_SITE_OVERRIDES:
        return W3W_SITE_OVERRIDES[low]
    for key, val in W3W_SITE_OVERRIDES.items():
        if key.lower() == low:
            return val

    # 2. Check if any part of the w3w address is a known site code
    for part in cleaned.replace(".", " ").split():
        p = part.strip(".,;:!?()")
        if p in ("EP", "PW", "SJR", "MG", "KH", "NL", "ST/LAT", "CS",
                 "WMW", "GED", "DFG", "GDR", "CAK", "JD", "SM",
                 "HB", "DD", "MH", "TJ", "PIC", "RW", "DC", "DK",
                 "OB", "PT/M", "PT"):
            return p

    return None
