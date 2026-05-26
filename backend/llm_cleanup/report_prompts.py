SITE_REPORT_PROMPT = """You are a water quality analyst for the River Coln in Gloucestershire, UK.
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

Write in natural English prose (3-5 paragraphs). Include:
1. Brief description of the site location and sampling frequency
2. Overall water quality assessment — which WFD band each chemical falls in
3. Notable trends or patterns over time
4. Any specific dates or events worth flagging
5. Landowner information if available

Format as plain text with no markdown. Do not use bullet points or lists."""


ROUND_REPORT_PROMPT = """You are a water quality analyst for the River Coln in Gloucestershire, UK.
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

Write in natural English prose (4-6 paragraphs). Include:
1. Overview of this round — when sampling occurred and how many sites were visited
2. Overall water quality assessment — which WFD band each chemical falls in
3. Comparison with the previous round — improvement or decline for each chemical
4. Standout sites or readings worth highlighting
5. Summary assessment of river health in this period

Format as plain text with no markdown. Do not use bullet points or lists."""
