"""System and user prompt templates for the v2 LLM report engine.

Six report types x three audiences share one JSON schema (`schemas.py`)
and one set of hard rules; only the *voice* and the *brief* change per
audience/type, never the numbers. See `verify.py` for how those numbers
get checked afterwards.

The system prompt is built once per (report_type, audience) pair and
carries no per-request data (no timestamps, ids, or facts pack) — the
addendum drops the Anthropic prompt-caching guidance from the base spec,
but keeping the system prompt free of volatile content is still good
practice on its own and costs nothing.
"""

from __future__ import annotations

import json
import re

from v2 import schemas
from v2.wfd import PARAMETER_ORDER, PARAMETERS

# ---------------------------------------------------------------------------
# Facts pack delimiters — shared with `llm.py`'s stub provider, which
# parses the facts pack back out of the user prompt so it can cite real
# figures without calling a real model.
# ---------------------------------------------------------------------------

FACTS_PACK_BEGIN = "===FACTS_PACK_JSON==="
FACTS_PACK_END = "===END_FACTS_PACK_JSON==="


def extract_facts_pack(user_prompt: str) -> dict | None:
    """Pull the facts pack back out of a user prompt built by
    `build_user_prompt`. Returns None if the markers aren't found or the
    content between them isn't valid JSON."""
    start = user_prompt.find(FACTS_PACK_BEGIN)
    end = user_prompt.find(FACTS_PACK_END)
    if start == -1 or end == -1 or end <= start:
        return None
    blob = user_prompt[start + len(FACTS_PACK_BEGIN):end].strip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


_META_LINE_RE = re.compile(r"^(Audience|Report type|Report key):\s*(.*)$", re.MULTILINE)


def extract_prompt_meta(user_prompt: str) -> dict:
    """Pull the `Audience: ...` / `Report type: ...` / `Report key: ...`
    header lines back out of a user prompt built by `build_user_prompt`.
    Used by the stub provider; real providers ignore this."""
    meta = {"audience": "", "report_type": "", "report_key": ""}
    key_map = {"Audience": "audience", "Report type": "report_type", "Report key": "report_key"}
    for label, value in _META_LINE_RE.findall(user_prompt):
        meta[key_map[label]] = value.strip()
    return meta


# ---------------------------------------------------------------------------
# Audience voice
# ---------------------------------------------------------------------------

AUDIENCE_GUIDANCE = {
    "volunteer": (
        "Write for the volunteers who collect these samples and their neighbours along the "
        "river — people with no scientific background. Aim for a reading age of about 12: "
        "short sentences, one idea per sentence, and a plain-English gloss the first time any "
        "technical term appears (including WFD band names — see below). Avoid jargon from "
        "water science unless it is glossed."
    ),
    "public": (
        "Write for a parish newsletter or local press: still plain English with every "
        "technical term glossed on first use, but a slightly more formal, impersonal register "
        "than the volunteer version — suitable for printing in a newsletter without further "
        "editing."
    ),
    "technical": (
        "Write for an Environment Agency officer or a council officer who already knows WFD "
        "terminology. Full figures and standard terms (band names, units, statistical terms) "
        "can be used without glossing them, and more precision is expected. The content rules "
        "below still apply in full — a technical audience does not change what the data can "
        "support."
    ),
}

# ---------------------------------------------------------------------------
# Report type briefs
# ---------------------------------------------------------------------------

REPORT_TYPE_GUIDANCE = {
    "location": (
        "This report covers one sampling location — a what3words address — across its whole "
        "sampling history. Describe where it sits on the river using its position between "
        "neighbouring locations, never using a volunteer's initials to describe a place. If the "
        "facts pack has no river position for this location (a handful of real locations are not "
        "yet in the group's reference table), say the position on the river isn't known yet "
        "rather than guessing one. Cover each parameter that has readings, its latest value or "
        "category and band where it has one, and how it compares with the location's own "
        "history."
    ),
    "round": (
        "This report covers one sampling round: a single burst of sampling across the "
        "catchment. Describe the overall picture for that round, which locations or "
        "parameters stood out, and how the round compares with the round before it where that "
        "comparison is in the facts pack."
    ),
    "catchment": (
        "This report covers the whole river over a stated period. Describe the overall state "
        "of the catchment, per-parameter patterns across locations, and anything notable about "
        "coverage. State plainly if dissolved oxygen or conductivity are not currently being "
        "measured, rather than drawing a conclusion from the handful of readings that exist for "
        "them. This is the broadest report type — keep the headline about the river as a whole, "
        "not one location."
    ),
    "comparison": (
        "This report compares two rounds or two periods side by side. Describe what changed "
        "between the two, per parameter, using the deltas and band changes in the facts pack. "
        "Do not speculate about why a figure changed beyond what the facts pack states."
    ),
    "trend": (
        "This report covers the long-term direction of one measurement across the river. Use "
        "only the trend classifications already computed in the facts pack ('improving', "
        "'worsening', 'no clear change', or 'insufficient_data') — never describe a trend more "
        "confidently than the facts pack does."
    ),
    "data_quality": (
        "This report is for the volunteer coordinators, not the general public: it covers how "
        "complete and reliable the data collection has been, not river chemistry itself. Cover "
        "coverage gaps, sampling frequency, readings that could not be used and why, locations "
        "with no coordinates yet, and state plainly which parameters (dissolved oxygen, "
        "conductivity) are not currently being measured. Do not present this as a report on "
        "river health."
    ),
}

# ---------------------------------------------------------------------------
# Hard rules — stated once, plainly, with a reason each; no stacked
# CRITICAL/MUST/NEVER emphasis (that degrades instruction-following on
# current models and makes the prompt brittle — see the build spec).
# ---------------------------------------------------------------------------

_RULES = [
    (
        "Every figure in this report has to come from the facts pack below, which is computed "
        "directly from the volunteers' data — there is no other measurement available, and "
        "doing arithmetic by hand here is how errors get introduced."
    ),
    (
        "Cite the matching id from the facts pack in `evidence_ids` for every finding or "
        "section that relies on a number, so each figure can be checked automatically against "
        "the facts pack after this report is generated."
    ),
    (
        "Do not name or imply blame for a landowner, farm, business or water company. A "
        "handful of water samples cannot support that kind of claim — they measure the "
        "river's chemistry at a place and moment, not its cause."
    ),
    (
        "Do not speculate about why a reading is what it is beyond what the facts pack "
        "itself says. Describe what was measured, not a guessed explanation."
    ),
    (
        "Do not give health or bathing-safety advice, such as whether it is safe to swim or "
        "drink the water. This scheme measures river chemistry, not bathing safety, so it "
        "cannot support that judgement — say so if it feels relevant."
    ),
    (
        "Write in the third person about the volunteers and the river; avoid \"we\", \"I\" or "
        "\"our\", since this report is a record of the data, not a personal account."
    ),
    (
        "Only describe a trend as improving or worsening where the facts pack itself "
        "classifies it that way. Where it says 'no clear change' or 'insufficient_data', say "
        "that plainly instead — a few noisy readings are not evidence of a real trend."
    ),
    (
        "Describe a location by its what3words address, never by the initials of the "
        "volunteer who sampled it. Initials identify a person, not a place, and mixing the "
        "two misleads the reader about who took a sample versus where it was taken."
    ),
    (
        "Where a figure in the facts pack is marked as a below-detection bound, a test-strip "
        "range, or a range midpoint, say so rather than presenting it as an exact reading — the "
        "facts pack marks which figures carry this caveat."
    ),
    (
        "Some turbidity (and a few water-depth) readings were recorded by volunteers as words "
        "describing what they saw — 'clear', 'cloudy', 'murky' and similar — rather than a "
        "meter reading. Report these as words, using the category the facts pack gives, and "
        "never turn them into a number or match them against the WFD turbidity bands, which are "
        "meter readings in NTU that a word-only observation was never measured in."
    ),
    (
        "Where the facts pack marks a parameter as not currently measured at this location or "
        "in this period, say so rather than drawing a conclusion from the few or zero readings "
        "that exist."
    ),
    (
        "Write for the stated audience, glossing every technical term the first time it is "
        "used, and use British English and DD/MM/YYYY dates. Never refer to the reader as a "
        "\"user\"."
    ),
]


def _rules_block() -> str:
    lines = [f"{i}. {rule}" for i, rule in enumerate(_RULES, start=1)]
    return "## Rules\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# WFD reference + parameter glossary — rendered once from `wfd.py`, the
# single source of truth for bands and plain-English metadata, so this
# text can never drift from what the API and frontend show a reader.
# ---------------------------------------------------------------------------

def _wfd_reference_block() -> str:
    lines = [
        "## WFD reference bands",
        "Five bands, best to worst: High, Good, Moderate, Poor, Bad. Always pair a band name "
        "with its plain meaning on first use in a report — \"High\" meaning *best* is a genuine "
        "trap for a reader who has not seen this scale before. Bands are meter readings only — "
        "never apply them to a word-only (ordinal) observation.",
        "",
    ]
    for key in PARAMETER_ORDER:
        p = PARAMETERS[key]
        if not p.get("bands"):
            continue
        bounds = ", ".join(f"{band} {value}" for band, value in p["bands"].items())
        lines.append(f"- {p['label']} ({p['unit']}, {p['direction']}): {bounds}")
    lines.append("")
    lines.append(
        "Conductivity and water depth have no WFD band — conductivity only has a typical "
        "range, and water depth is context, not a pollution measure."
    )
    return "\n".join(lines)


def _parameter_glossary_block() -> str:
    lines = ["## What each parameter means (for glossing on first use)"]
    for key in PARAMETER_ORDER:
        p = PARAMETERS[key]
        note = ""
        if p.get("not_currently_measured"):
            note = " The group does not currently have the kit to measure this, so there is very little data for it."
        lines.append(f"- **{p['label']}** ({p['unit']}): {p['one_liner']} {p['why_it_matters']}{note}")
    return "\n".join(lines)


_WFD_REFERENCE_BLOCK = _wfd_reference_block()
_PARAMETER_GLOSSARY_BLOCK = _parameter_glossary_block()
_RULES_BLOCK = _rules_block()

_ROLE_AND_CONTEXT = (
    "You write water-quality reports for the Coln River Guardians, a volunteer citizen-science "
    "group monitoring the River Coln in Gloucestershire, UK. You are given a facts pack: a set "
    "of figures and category counts already computed from the volunteers' readings, each with a "
    "stable id. You turn those figures into a structured report. You never calculate a figure "
    "yourself, and you never invent a number for something that was only ever recorded in "
    "words — every number you write down must already be in the facts pack."
)


def _output_format_block() -> str:
    example = json.dumps(schemas.EXAMPLE_REPORT, indent=2, ensure_ascii=False)
    return (
        "## Output format\n"
        "Reply with a single JSON object and nothing else — no markdown fence, no commentary "
        "before or after it. The object must have exactly these fields:\n\n"
        f"{schemas.describe_schema()}\n\n"
        "Worked example (the wording and figures below are illustrative only — use the real "
        "figures from the facts pack you are given, not these ones):\n\n"
        f"```json\n{example}\n```"
    )


_OUTPUT_FORMAT_BLOCK = _output_format_block()


def build_system_prompt(report_type: str, audience: str) -> str:
    """The stable system prompt for one (report_type, audience) pair —
    role, audience voice, report brief, rules, WFD reference, parameter
    glossary, and output format. Contains no per-request data (no
    timestamps, ids, or facts pack), so it is identical across every call
    for the same pair."""
    audience_guidance = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["volunteer"])
    type_guidance = REPORT_TYPE_GUIDANCE.get(report_type, "")
    return "\n\n".join([
        _ROLE_AND_CONTEXT,
        f"## Audience for this report\n{audience_guidance}",
        f"## What this report covers\n{type_guidance}",
        _RULES_BLOCK,
        _WFD_REFERENCE_BLOCK,
        _PARAMETER_GLOSSARY_BLOCK,
        _OUTPUT_FORMAT_BLOCK,
    ])


def build_user_prompt(
    report_type: str,
    audience: str,
    report_key: str,
    facts_pack: dict,
    correction: str | None = None,
) -> str:
    """The per-request user prompt: which report this is, then the facts
    pack it must be built from, and nothing else — unless `correction` is
    given, in which case it is appended as a further instruction (used for
    both the schema-validation repair pass in `llm.py` and the
    content-verification repair pass in `engine.py`)."""
    parts = [
        f"Audience: {audience}",
        f"Report type: {report_type}",
        f"Report key: {report_key}",
        "",
        "Write the report as a single JSON object matching the schema and worked example given "
        "in the system prompt. Use only the figures and categories in the facts pack below; "
        "cite their ids in `evidence_ids` wherever a finding or section relies on one.",
        "",
        FACTS_PACK_BEGIN,
        json.dumps(facts_pack, ensure_ascii=False, indent=2),
        FACTS_PACK_END,
    ]
    if correction:
        parts.extend(["", correction])
    return "\n".join(parts)
