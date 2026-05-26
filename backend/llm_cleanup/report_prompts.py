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


SITE_REPORT_PROMPT = """You are a water quality analyst for the River Coln in Gloucestershire, UK.

{factfile}

{site_order}

Write a clear, concise summary report for sampling site {site_code} ({site_name}).

## Site data (all entries, newest first)
{entries}

## WFD (Water Framework Directive) thresholds (Lowland High Alkalinity)
- Phosphate: High=0.1, Good=0.2, Moderate=0.4, Poor=0.7 (mg/L)
- Ammonia: High=0.3, Good=0.6, Moderate=1.1, Poor=2.5 (mg/L)
- Nitrate: High=5.6, Good=11.3, Moderate=16.9, Poor=22.6 (mg/L)
- Dissolved oxygen: High≥7, Good≥5, Moderate≥4, Poor<4 (mg/L)
- Turbidity: High<5, Good<10, Moderate<20, Poor≥20 (NTU)
- Conductivity: typical range 300-1200 µS/cm

## CRITICAL RULES — YOU MUST FOLLOW THESE
1. BASE ALL STATEMENTS STRICTLY ON THE DATA PROVIDED ABOVE. Do NOT invent trends, causes, or explanations not directly evidenced in the data.
2. Do NOT speculate about causes of water quality (e.g. do not say "agricultural activities may be contributing" unless the data literally says so).
3. Do NOT mention landowners. Do not reference landowner information at all.
4. Do NOT reference the River Avon. The Coln joins the Thames, not the Avon.
5. The only time period you may reference is the data shown above. Do not claim trends over "years" unless the data spans multiple years.
6. Observations about trends must be grounded in specific data points shown (e.g. "phosphate was 0.25 on Apr 1 and 0.31 on Jun 1" rather than "phosphate has been increasing").
7. The factfile above contains confirmed facts about the River Coln. You may use these as context but do not invent additional facts not listed there.
8. Do not use markdown formatting. Output plain text only. Do not use bullet points or numbered lists.

Write a report in natural English prose (3-5 paragraphs). Include:
1. Brief description of the site location and sampling frequency (based on data dates)
2. Overall water quality assessment — which WFD band each measured chemical falls in
3. Notable patterns or changes visible in the data, citing specific dates and values
4. Any specific dates or events worth flagging from the data"""


ROUND_REPORT_PROMPT = """You are a water quality analyst for the River Coln in Gloucestershire, UK.

{factfile}

{site_order}

Write a clear, concise summary report for sampling round {round_label} ({round_start} to {round_end}).

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

## CRITICAL RULES — YOU MUST FOLLOW THESE
1. BASE ALL STATEMENTS STRICTLY ON THE DATA PROVIDED ABOVE. Do NOT invent trends, causes, or explanations not directly evidenced in the data.
2. Do NOT speculate about causes of water quality (e.g. do not say "agricultural activities may be contributing").
3. Do NOT reference the River Avon. The Coln joins the Thames, not the Avon.
4. Comparisons between rounds must be grounded in the averages provided. State the actual numbers.
5. The factfile above contains confirmed facts about the River Coln. You may use these as context but do not invent additional facts not listed there.
6. Do not use markdown formatting. Output plain text only. Do not use bullet points or numbered lists.

Write a report in natural English prose (4-6 paragraphs). Include:
1. Overview of this round — when sampling occurred and how many sites were visited
2. Overall water quality assessment — which WFD band each chemical falls in
3. Comparison with the previous round — improvement or decline for each chemical, citing the actual average values
4. Standout sites or readings worth highlighting from the data
5. Summary assessment of river health in this period"""
