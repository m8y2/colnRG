"""Populate lat/lng from LocationReferenceTable.xlsx on the droplet."""
import sqlite3

coords = {
    "traffic.reclaimed.ringers": (51.903124, -1.952983),
    "props.showcases.warbler": (51.902881, -1.952459),
    "craftsman.mysteries.bluffs": (51.891238, -1.952808),
    "village.damage.wonderful": (51.885363, -1.955342),
    "keener.washed.expensive": (51.882183, -1.959884),
    "conquests.camper.advanced": (51.878005, -1.964557),
    "arching.probably.stickler": (51.877197, -1.965081),
    "widget.applied.woodstove": (51.875148, -1.967440),
    "volcano.connected.tags": (51.874906, -1.966042),
    "warned.watched.bigger": (51.875067, -1.966042),
    "grace.reprints.jigsaw": (51.865850, -1.962111),
    "doubt.bridge.leopard": (51.865823, -1.962548),
    "publisher.chief.moderated": (51.866874, -1.942850),
    "blitz.dries.cleansed": (51.864044, -1.949227),
    "aimed.boarded.roofs": (51.862454, -1.978752),
    "luring.tram.dolphins": (51.859436, -1.964863),
    "reset.spires.supply": (51.857037, -1.958748),
    "mornings.dentistry.toenail": (51.854908, -1.952983),
    "unions.foggy.trendy": (51.844505, -1.958180),
    "title.rafters.cyber": (51.844343, -1.946257),
    "marmalade.stove.remission": (51.840462, -1.949926),
    "scrub.indicated.toast": (51.839007, -1.949664),
    "ritual.cyber.weeks": (51.838063, -1.950799),
    "spenders.promotion.claps": (51.837713, -1.952022),
    "cobble.zoos.bypassed": (51.837093, -1.955516),
    "hippy.expect.iterative": (51.831164, -1.939420),
    "laminated.wrenching.plankton": (51.831918, -1.932701),
    "channel.riskiest.goofy": (51.835072, -1.928132),
    "breezes.went.squirted": (51.817877, -1.908442),
    "mango.batches.duke": (51.813160, -1.880868),
    "covenants.corrupted.betrayed": (51.815128, -1.881261),
    "compound.catchers.fishnet": (51.799739, -1.885188),
    "meaning.verb.chainsaw": (51.806153, -1.889594),
    "electric.rosier.soggy": (51.788015, -1.873758),
    "lightbulb.recitals.replaces": (51.782382, -1.876765),
    "villager.reduce.nibbles": (51.773704, -1.866349),
    "tasters.storming.avocado": (51.766373, -1.847520),
    "amicably.admits.teacher": (51.767235, -1.852925),
    "gobblers.printers.secure": (51.767208, -1.853142),
    "dummy.gravitate.invest": (51.758665, -1.833704),
    "defected.herring.stage": (51.748262, -1.816288),
    "stopped.curbed.weeds": (51.743330, -1.794823),
    "divisible.branch.gullible": (51.741659, -1.793038),
    "windmill.poetry.costly": (51.729935, -1.788292),
    "touched.immune.solve": (51.710395, -1.784635),
    "pram.rebel.hurt": (51.706595, -1.783120),
    "hindered.handlebar.button": (51.702903, -1.770464),
    "badly.boarding.rephrase": (51.688268, -1.705745),
}

conn = sqlite3.connect("backend/dashboard.db")
rows = conn.execute("SELECT DISTINCT w3w FROM entries WHERE w3w IS NOT NULL AND w3w != ''").fetchall()

updates = []
for (w3w_db,) in rows:
    if w3w_db.lower() in coords:
        lat, lng = coords[w3w_db.lower()]
        updates.append((lat, lng, w3w_db))
    else:
        print(f"No match: [{w3w_db}]")

print(f"Matched {len(updates)}/{len(rows)}")

conn.execute("BEGIN")
for lat, lng, w3w in updates:
    conn.execute("UPDATE entries SET latitude = ?, longitude = ? WHERE w3w = ?", (lat, lng, w3w))
conn.execute("COMMIT")
conn.close()
print("Done.")
