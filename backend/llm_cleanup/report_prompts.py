COLN_FACTFILE = """## River Coln Factfile (verified facts only — do not invent additional facts)
- The River Coln rises at ~200m AOD near Sevenhampton/Brockhampton, east of Cheltenham, Gloucestershire
- It flows south/southeast through the Cotswold Hills to Lechlade where it joins the River Thames (~75m AOD)
- It does NOT join the River Avon. Its only confluence is with the River Thames.
- Length: ~51km total
- Underlying geology: limestone (Inferior Oolite, then Great Oolite), crossing Oxford Clay near the Thames
- Discharge increases downstream: Fossebridge 0.47, Bibury 1.33, Fairford 2.06 m³/s
- Villages along the river (upstream to downstream): Brockhampton, Andoversford, Withington, Fossebridge, Coln Rogers, Winson, Ablington, Bibury, Coln St Aldwyns, Quenington, Fairford, Lechlade
- Upper two-thirds of the catchment is within the Cotswold Area of Outstanding Natural Beauty (AONB)
- Area around Fairford designated as Nitrate-sensitive area
- Major sewage treatment works inputs at Andoversford, Withington, Bibury and Fairford
- Bibury Trout Farm is the largest discharge into the river
- The river has been modified with weirs and channels for mills
- Gravel pits between Fairford and Lechlade form the eastern component of the Cotswold Water Park
- Fish species present: brown trout, grayling
- EA water quality classification 2019: Upper section (Source to Coln Rogers) — Moderate ecological, Fail chemical. Lower section (Coln Rogers to Thames) — Poor ecological, Fail chemical.
- Invertebrate quality is rated High by the Environment Agency (2019–2022)
- Biological quality overall is considered good, supporting a trout fishery with good spawning beds
- The catchment is mostly rural with farming as the main industry (grazing in upper catchment, some arable)
- The river has no major tributaries
- Population of the Coln catchment: ~9,000
- Invasive non-native species present: American signal crayfish
- The river flows through the Cotswold Water Park area downstream of Fairford"""

SITE_ORDER_UPSTREAM_TO_DOWNSTREAM = [
    "EP", "PW", "SJR", "MG", "NL", "ST/LAT", "CS", "WMW", "GED", "DFG", "GDR",
    "CAK", "JD", "KH", "SM", "HB", "DD", "MH", "TJ", "PIC", "DC", "DK", "OB",
    "PT/M", "PT"
]

SITE_ORDER_TEXT = "Site order from upstream to downstream: " + " → ".join(SITE_ORDER_UPSTREAM_TO_DOWNSTREAM)


MONITORING_CONTEXT = """## Monitoring program context (accurate facts — do not contradict these)
- The Coln River Guardians monitoring program began on 6 June 2025
- As of the latest data there have been 61 unique sampling dates across the project
- 376 water quality samples have been collected across 26 sampling sites
- Each sample measures up to 7 parameters: phosphate, ammonia, nitrate, turbidity, dissolved oxygen, conductivity, water depth
- Sampling is conducted by volunteers on a roughly weekly rotation
- Individual sites average 8–9 sampling rounds each, spanning approximately 10–11 months"""


SITE_REPORT_PROMPT = """Write a clear, concise water quality summary for sampling site {site_code} on the River Coln.

{site_order}

{site_location_context}

{monitoring_context}

## Site data (all entries for this site, newest first)
{entries}

## WFD (Water Framework Directive) thresholds (Lowland High Alkalinity) — only for chemicals present in this site's data
{wfd_thresholds}

## RULES — YOU MUST FOLLOW THESE
1. This report is only about {site_code}. Do not describe the entire river or mention other sites.
2. Base all statements on the site data above. Never invent values, dates, or trends.
3. Never mention landowners. Do not reference landowner information.
4. Never reference the River Avon. The Coln joins the Thames, not the Avon.
5. Never mention sewage, STW, treatment works, or pollution sources unless the specific site's data explicitly contains such a mention.
6. Never mention fishing, trout, grayling, or wildlife. The project is a water quality monitoring scheme, not an ecological survey.
7. Never invent monitoring patterns. Do not say "sampled daily" or "sampled weekly for X weeks" unless the data explicitly shows that frequency.
8. Never speculate about causes or sources. Ban phrases like "may be due to", "suggests that", "could indicate", "might be related to", "possibly", "potentially", "likely caused by".
9. Never use first person (I, my, we, our). Write as a neutral third-party report.
10. Cite specific values with units (e.g. "0.25 mg/L"). Every claim about a chemical must include its exact measured value.
11. No markdown formatting — plain text only, no bullet points.
12. The Monitoring program context section above contains accurate facts about the project. Use it for project-level context. Do not contradict it.
13. All dates must be exact from the data. Do not invent or approximate dates.
14. The only valid identifier for this site is the code {site_code}. Never use any other name or label.
15. The River Coln has no tributaries. Do not mention any tributaries, confluences, or side streams.

Write a report in natural English prose (3-5 paragraphs). Include:
1. Brief description of the site location (relative to upstream/downstream neighbours) and its sampling dates
2. WFD band assessment for each chemical measured at this site
3. Notable patterns visible in this site's data, citing specific dates and values
4. Any specific dates worth flagging from this site's data"""


ROUND_REPORT_PROMPT = """Write a clear, concise water quality summary for sampling round {round_label} ({round_start} to {round_end}) on the River Coln.

{site_order}

{monitoring_context}

## Round data — all entries in this round across all sites
{entries}

## Averages per chemical for this round
{averages}

## Previous round averages for comparison
{previous_averages}

## WFD (Water Framework Directive) thresholds (Lowland High Alkalinity)
- Phosphate: High=0.1, Good=0.2, Moderate=0.4, Poor=0.7 (mg/L)
- Ammonia: High=0.3, Good=0.6, Moderate=1.1, Poor=2.5 (mg/L)
- Nitrate: High=5.6, Good=11.3, Moderate=16.9, Poor=22.6 (mg/L)
- Dissolved oxygen: High≥7, Good≥5, Moderate≥4, Poor<4 (mg/L)
- Turbidity: High<5, Good<10, Moderate<20, Poor≥20 (NTU)

## RULES — YOU MUST FOLLOW THESE
1. Base all statements on the round data above. Never invent values, dates, or trends.
2. Never mention sewage, STW, or treatment works unless the data explicitly mentions them.
3. Never mention fishing, trout, or wildlife. This is a water quality monitoring scheme.
4. Never speculate about causes or sources. Ban phrases like "may be due to", "suggests that", "could indicate", "might be related to", "possibly".
5. Never reference the River Avon. The Coln joins the Thames, not the Avon.
6. Comparisons between rounds must use the actual date ranges from the data provided.
7. Never use first person (I, my, we, our). Write as a neutral third-party report.
8. Cite specific values with units (e.g. "0.25 mg/L"). Every claim about a chemical must include its exact measured value.
9. No markdown formatting — plain text only, no bullet points.
10. Never include a chemical that has no readings in the round data. Never use WFD threshold values as actual measurements.
11. All dates must be exact from the data. Do not invent or approximate dates.

Write a report in natural English prose (4-6 paragraphs). Include:
1. Overview of this round — when sampling occurred and how many sites were visited
2. Overall water quality assessment — which WFD band each chemical falls in
3. Comparison with the previous round — citing the actual averages and date ranges
4. Standout sites or readings worth highlighting from the round data
5. Summary assessment of river health in this period"""
