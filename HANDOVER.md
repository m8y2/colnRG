# Coln River Guardians v2 — handover

Written 18 August 2026 for whoever picks this up next. Branch `v2` in
`github.com/m8y2/colnRG`. **Nothing has been deployed.** The live site at
`colnrg.app` still runs v1, untouched.

Read `V2.md` for how the system works. This file is the state of play: what was done,
what was found, what is unfinished, and where the traps are.

---

## 1. What was asked for

The owner (Matthew) asked for four things, in this order:

1. Rebuild the site so citizen scientists with no technical background can use it — the
   graphs and the writing were both aimed at someone who already understood the subject.
2. Build a real automatic reporting engine, "way over the website's current beta capability",
   LLM-driven.
3. Keep v1 and v2 separate.
4. No filler labels — his words: *"Don't leave silly notes all over the website, like
   'photo gallery — shows photos'."*

Then, during the work:

5. Build around **his Mistral key**, not Anthropic.
6. **Re-ingest and re-clean everything from EpiCollect** — he suspected his own cleaning
   had been inappropriate.
7. Build the site around **geolocated** data, using his location reference table.
8. Don't needlessly drop readings that can obviously be rectified.
9. Reports: **one per round of testing**, covering the whole river. Cut the
   parish-council and technical variants.
10. Rename the top grade from **High to Excellent**, and remove the explainers that
    existed only because "High" was confusing.

All ten are done. The gaps are in section 6.

---

## 2. What was found (the important part)

Three discoveries changed the shape of the work. If you only read one section, read this.

### 2.1 v1's "sites" are not places — they are people

EpiCollect field `1_What_are_your_What` holds `"<what3words> <INITIALS>"`, e.g.
`"grace.reprints.jigsaw MG"`. v1 keeps only the trailing token and treats it as the site.
Those are the **volunteer's initials**.

`MG` covers four genuinely different points on the river (river positions 11, 12, 15, 16),
averaged into one number and pinned to a single invented coordinate in `backend/coords.py`.
EP, PW, SJR, KH, SM, DD, JD, PIC, GED, OB and PT/M have the same problem.

**50 distinct places have ever been sampled. v1 reports 24.** The site has been
under-reporting coverage by half and averaging unrelated stretches of river together.

`backend/w3w_sites.py` compounds it by assigning unrecognised addresses to the nearest known
site by Haversine distance — inventing a location. v2 does not do this.

### 2.2 v1's cleaning corrupted the readings

- `backend/clean.py` **converts prose into numbers**: `"cloudy"` → 30 NTU, `"murky"` → 60,
  `"high"` → 50. Those fabricated figures then feed means and band classification.
- `backend/clean_data.py::clean_numeric_outliers` **divides values by 10** when they look
  high against a group median and **overwrites the stored value**. The original is gone. The
  median it compares against is per-initials, so it mixes different places.
- `backend/llm_cleanup/` asks a language model to "fix decimal-shift outliers" in the
  measurements.

### 2.3 An infinite refetch loop blanked every chart

Late in the work, every Recharts chart in v2 was rendering nothing — axes and gridlines but
no data, **exactly** the bug v1 has on its two bar-chart tabs.

Cause was not the charting library. `useApi` ran its effect on `[fn]`, and every call site
passes an inline arrow — a new function identity each render. Effect → setState → re-render →
new `fn` → effect, forever. The browser fired the same requests until it gave up with
`ERR_INSUFFICIENT_RESOURCES`; React never settled; no chart mounted. Every call site was
already passing a deps array that the hook silently ignored.

**This was nearly shipped**, because the pages screenshotted for verification (home, reports)
happen to contain no Recharts chart. If you change anything in `src/lib/useApi.js`, verify a
chart page in a **built** app, not just dev.

---

## 3. Architecture

```
Dashboard/                       branch v2
  frontend/                      v1 — untouched
  frontend-v2/                   v2 React 19 + Vite, base '/' (v2 is now the main site)
    scripts/build-demo.py        builds the single-file offline demo
  backend/
    main.py                      v1 — zero diff
    main_v2.py                   imports the v1 app, mounts /api/v2 on it
    coln_v2.db                   v2's own database (gitignored, rebuildable)
    v2/                          all v2 code — see V2.md for the file map
  deploy/v2-*.example            nginx + systemd, examples only, not applied
  V2.md                          how it works
  HANDOVER.md                    this file
```

v1 keeps `/` and `/api` and its own `dashboard.db`. v2 gets `/v2` and `/api/v2` and
`coln_v2.db`. One uvicorn process serves both once it runs `main_v2:app`.

### Data model

Two layers. `raw_entries` holds the exact EpiCollect payload, stored once, never modified.
Everything else is derived and can be thrown away and rebuilt:

```
raw_entries        the API payload verbatim
locations          a place on the river: w3w PK, river_order (REAL), lat, lon, source
location_aliases   every spelling seen -> canonical w3w, with how it matched
observations       one row per sample visit
measurements       one row per parameter per visit
cleaning_log       every transformation, auditable
review_queue       readings needing a human decision
manual_corrections the owner's accepted decisions — survives a rebuild
v2_reports         generated reports + their facts pack + verification record
v2_report_jobs     the async generation queue (persisted, not in-memory)
```

**A location is a what3words point, not initials.** `river_order` (from `MY_ID` in
`LocationReferenceTable.xlsx`) orders every downstream view. Volunteer initials live in
`observations.recorder` — who collected it, never where.

---

## 4. Traps — read before changing anything

1. **`usable = 1` does NOT imply `value IS NOT NULL`.** Ordinal readings (turbidity in
   words) are usable but have `value` NULL and `category` set. Any query doing arithmetic
   needs `AND value IS NOT NULL` too, or ordinal rows poison the average. This is the
   easiest way to silently reintroduce the exact bug this rebuild exists to fix.

2. **`river_order` is a REAL, not an integer.** Four points found outside the owner's
   spreadsheet have fractional positions (15.98, 38.92, 43.50, 46.77) so they sort between
   the integer `MY_ID`s. Sort numerically; **never display it** — "point 38.92 on the river"
   is not something to show a reader. Use rank position instead.

3. **Never display a mean of ordinal ranks.** Averaging "clear" and "muddy" to 4.3 implies
   the gaps between categories are equal. Modal and median category are legitimate; a mean
   is not. Rank is a sort key only.

4. **Turbidity must never be graded against the WFD NTU bands.** 359 of its 369 usable
   readings are words. The thresholds are meter readings; the observations are not.

5. **Field-name mismatches between API and UI have bitten four times** (`bands` vs
   `latest_bands`, `points` vs `locations`, `value` vs `mean`, flat `location.*` vs
   `summary.*`). Each was silent — no error, just an empty or wrong page. When wiring a new
   view, `curl` the endpoint first.

6. **The v1 files must stay untouched.** `backend/main.py`, `sync.py`, `clean*.py`,
   `coords.py`, `w3w_sites.py`, `database.py`, everything under `frontend/`. There are also
   **7 uncommitted v1 working-tree changes** that predate this work
   (`frontend/index.html`, `frontend/src/App.jsx`, three components, `src/index.css`,
   `webstats.py`). **Never `git add -A`.** Stage explicit paths.

7. **Production CSS in v1 is the inline `<style>` in `frontend/index.html`**, not
   `src/index.css`. v2 does not have this problem — it uses normal Vite stylesheets — but
   don't carry the v1 habit across.

---

## 5. Results

### Ingest

```
489 entries    486 located    0 unlocated    3 test entries
resolution:    exact 457   documented_rename 16   fuzzy 13

                usable   numeric / words   set aside
phosphate         475      475 /    0         14
ammonia           462      462 /    0         27
nitrate           449      449 /    0         40
turbidity         369       10 /  359        120
water depth       484      448 /   36          5
dissolved oxygen    4        4 /    0        485
conductivity        2        2 /    0        487
TOTAL           2,245
```

Accepting only plain numbers would have given ~1,557. 2,070 cleaning actions logged, all
reversible. `--refresh` is idempotent.

### Cleaning principle

**Transform the representation, never the measurement.** `value_raw` is always kept, nothing
is rescaled, prose is never assigned a number, and implausible values are flagged rather than
"corrected". `10-25 (20)` uses the volunteer's own figure and keeps the band as bounds —
they were standing at the river and we were not.

### Review queue — 25 items awaiting the owner

Two possible-duplicate locations (6 m and 33 m from existing points); four dissolved-oxygen
zeros; four implausible chemical values with suggested decimal corrections
(`phosphate 47` → `0.47`); ~15 genuinely unreadable entries. **Suggestions are displayed,
never applied.** Accepting one writes `manual_corrections`, applied on the next rebuild.

### Reports

One kind: **one per round of testing, covering the whole river**, in one voice. 14 exist for
the current data; a second scheduler run generates nothing. Each report is built from a
deterministic facts pack (the LLM never does arithmetic), returned as structured JSON,
validated in Python, then **every number in the narrative is checked back against the facts
pack** before storage. Failures are surfaced in the UI, not hidden.

Round facts include the **downstream profile** (phosphate, ammonia, nitrate ordered source to
Thames) — the owner specifically called this out as important. Without it a report could say
"phosphate was Moderate at eleven places" but not "it gets worse towards the Thames".

### Grades

**Excellent, Good, Moderate, Poor, Bad.** Renamed from WFD's "High" because "high phosphate"
in ordinary English means bad news. The glosses and warning paragraph that existed to explain
that trap were removed with it. Per-parameter `band_meanings` were kept — those are
information, not a workaround.

---

## 6. What is NOT done

1. **No real Mistral call has ever been made.** There is no `MISTRAL_API_KEY` in the
   development environment; it lives on the droplet. Everything was exercised with
   `REPORT_LLM_PROVIDER=stub`, which returns schema-valid JSON with no network call. **The
   prompts are unproven against the actual model.** This is the largest remaining risk.
   First real task: set the key, generate one round report, read it critically, and expect to
   tune `v2/prompts.py`. Mistral does not enforce JSON Schema server-side, so the Python-side
   validation in `v2/schemas.py` is load-bearing.

2. **Nothing is deployed.** `deploy/v2-nginx.conf.example` and
   `coln-v2-reports.{service,timer}.example` are examples to merge into the live config.
   `MIGRATION.md` supersedes everything on infrastructure; the repo's `deploy/nginx.conf` is
   HTTP-only and will not reproduce HTTPS. Deploying is the owner's call, not an assumption
   to make.

3. **`ADMIN_API_KEY` must be set in production.** `POST /api/v2/reports/generate` and
   `POST /api/v2/review-queue/{id}` are open when it is unset (so local dev works). In
   production that would let anonymous traffic spend the project's Mistral credit.

4. **Accessibility has not been audited by a tool or a screen reader.** It was built to the
   WCAG 2.1 AA requirements in the spec — semantic HTML, keyboard operation, visible focus,
   16px base, band names never conveyed by colour alone, a text list beside every map, a
   "view as table" toggle on every chart — but that is a build-time claim, not a test result.

5. **Only some pages verified at mobile width and in dark mode.** Both are implemented;
   neither was swept systematically.

6. **The two possible-duplicate locations are unresolved** pending the owner's decision.
   If both merge, the distinct-place count goes from 50 to 48.

7. **Report wording has not been reviewed by a human for tone.** The stub output cannot tell
   you whether the real thing reads well to a volunteer.

---

## 7. Running it

```bash
# backend (v1 + v2 in one process)
cd Dashboard/backend
./venv/bin/python -m uvicorn main_v2:app --port 8000

# frontend
cd Dashboard/frontend-v2
npm install && npm run dev            # :5174
npm run build && npm run preview      # :5175 — verify charts HERE, not just dev

# data
cd Dashboard/backend
python -m v2.ingest --fetch           # re-fetch from EpiCollect, rebuild
python -m v2.ingest --refresh         # rebuild from stored raw, no network

# reports
REPORT_LLM_PROVIDER=stub python -m v2.scheduler --dry-run
python -m v2.scheduler                # real, needs MISTRAL_API_KEY

# single-file offline demo (backend must be running, dist must be built)
cd Dashboard/frontend-v2 && python3 scripts/build-demo.py
```

`python run_v2.py` from `Dashboard/` starts both servers.

---

## 8. Commits on `v2`

```
5c7fe8b  Rename the top band High -> Excellent, drop the explainers it needed
e3f0d1a  Fix location detail reading a shape the API never returned
01f8a32  Fix infinite refetch that stopped every chart rendering
bbc0ce7  Generate one report per round of testing, covering the whole river
69331d2  Simplify the location precision note
1a7b4d5  Remove self-describing filler copy
f82a4e6  Finish v2 UI, add review-queue endpoints, stop misleading headline bands
d89efd5  Complete v2 reporting engine: HTTP surface and automatic scheduling
2738fd8  WIP: v2 report engine and frontend, unverified
4b9c427  Add v2 ingest: re-read EpiCollect from source, clean non-destructively
ad527ec  Rework v2 backend onto the addendum's location-based schema
a40d57a  Add v2 backend data layer: db, WFD bands, deterministic insights, data API
         (+ two commits untracking frontend-v2/node_modules)
```

---

## 9. Known v1 bugs, deliberately not fixed

- **Both bar charts on the live site render axes and no bars** — "Long-term Site Averages"
  and "Round by round results". Two of seven tabs currently show nothing to visitors. Given
  §2.3, check `useApi`-style refetch loops in v1 before blaming Recharts.
- `backend/main.py` uses `datetime.now(timezone.utc)` in `/api/health` and the admin-key
  endpoint but never imports `timezone` — a `NameError` waiting to fire.
- `backend/AGENTS.md` still documents Ollama-on-a-droplet report generation; that moved to
  the Mistral API in commit `5902e0e`.
- v1's `dashboard.db` has drifted from source (376 rows locally, 475 live, 489 in
  EpiCollect) and is partly overwritten by the old cleaning. Do not treat it as a reference.
