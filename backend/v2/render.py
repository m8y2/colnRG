"""Rendering a structured report into a markdown document and a
self-contained printable HTML page.

Both take the same two arguments: the report JSON (matching
`schemas.REPORT_SCHEMA`) and a `meta` dict describing how it was produced.
`engine.py` builds that dict; this module only ever reads it, using
`.get(...)` throughout so a report can still be rendered even if a caller
leaves a field out. Keys used: `report_type`, `report_key`, `audience`,
`generated_at`, `provider`, `model`, `version`, `period_start`,
`period_end`, `trigger`, `verification` (the dict `verify.verify_report`
returns, with `status` possibly promoted from "unverified" to "repaired"
by `engine.py` after a successful corrective retry).
"""

from __future__ import annotations

import html as html_lib

REPORT_TYPE_LABELS = {
    "location": "Location report",
    "round": "Round report",
    "catchment": "Catchment report",
    "comparison": "Comparison report",
    "trend": "Trend report",
    "data_quality": "Data quality report",
}

AUDIENCE_LABELS = {
    "volunteer": "Volunteers and neighbours",
    "public": "Parish council / press",
    "technical": "Technical / Environment Agency",
}

SEVERITY_LABELS = {"good": "Good", "watch": "Watch", "concern": "Concern"}



def _band_display(band):
    """The band name as written to a reader."""
    return band or "Not banded"


def _verification_summary(verification: dict | None) -> dict:
    verification = verification or {}
    status = verification.get("status", "unverified")
    problems = (
        len(verification.get("unmatched_numbers", []))
        + len(verification.get("invalid_evidence_ids", []))
        + len(verification.get("banned_terms", []))
    )
    if status in ("verified", "repaired") and problems == 0:
        ok = True
        headline = "Every figure checked against the data"
        if status == "repaired":
            headline += " (one automatic correction was applied)"
    else:
        ok = False
        headline = "Some figures could not be checked automatically"
    return {"ok": ok, "headline": headline, "verification": verification}


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def to_markdown(report: dict, meta: dict) -> str:
    meta = meta or {}
    lines = []
    type_label = REPORT_TYPE_LABELS.get(meta.get("report_type"), meta.get("report_type", "Report"))
    audience_label = AUDIENCE_LABELS.get(meta.get("audience"), meta.get("audience", ""))

    lines.append(f"# {report.get('headline', '')}")
    lines.append("")
    lines.append(
        f"*{type_label} — {meta.get('report_key', '')} — for {audience_label} — "
        f"generated {meta.get('generated_at', '')}*"
    )
    lines.append("")

    verif = _verification_summary(meta.get("verification"))
    badge = "[verified]" if verif["ok"] else "[unverified]"
    lines.append(f"> {badge} **{verif['headline']}**")
    lines.append("")

    lines.append(report.get("summary_plain", ""))
    lines.append("")

    oa = report.get("overall_assessment") or {}
    lines.append(f"**Overall: {_band_display(oa.get('band'))}** (confidence: {oa.get('confidence', '')})  ")
    lines.append(oa.get("one_line_reason", ""))
    lines.append("")

    lines.append("## Key findings")
    for finding in report.get("key_findings", []):
        sev = SEVERITY_LABELS.get(finding.get("severity"), finding.get("severity", ""))
        lines.append(f"- **[{sev}] {finding.get('title', '')}** — {finding.get('detail', '')}")
    lines.append("")

    for section in report.get("sections", []):
        lines.append(f"## {section.get('heading', '')}")
        lines.append(section.get("body", ""))
        lines.append("")

    lines.append("## What this means")
    lines.append(report.get("what_this_means", ""))
    lines.append("")

    lines.append("## What to watch next round")
    for item in report.get("what_to_watch", []):
        lines.append(f"- {item}")
    lines.append("")

    lines.append("## Caveats")
    for item in report.get("caveats", []):
        lines.append(f"- {item}")
    lines.append("")

    glossary = report.get("glossary", [])
    if glossary:
        lines.append("## Glossary")
        for entry in glossary:
            lines.append(f"- **{entry.get('term', '')}** — {entry.get('plain_meaning', '')}")
        lines.append("")

    if not verif["ok"]:
        lines.append("## Verification notes")
        v = verif["verification"]
        for item in v.get("unmatched_numbers", []):
            lines.append(
                f"- Figure \"{item.get('value')}\" could not be matched to the facts pack "
                f"(near: \"{item.get('context')}\")."
            )
        for item in v.get("invalid_evidence_ids", []):
            lines.append(
                f"- Evidence id \"{item.get('id')}\" referenced in {item.get('path')} does not "
                "exist in the facts pack."
            )
        for item in v.get("banned_terms", []):
            lines.append(f"- Disallowed wording \"{item.get('term')}\" was found in the text.")
        lines.append("")

    lines.append("---")
    lines.append(
        f"Generated automatically by the Coln River Guardians reporting engine "
        f"({meta.get('provider', '')} {meta.get('model', '')}), version {meta.get('version', '')}."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Printable HTML
# ---------------------------------------------------------------------------

def _esc(value) -> str:
    return html_lib.escape(str(value if value is not None else ""))


def to_printable_html(report: dict, meta: dict) -> str:
    meta = meta or {}
    type_label = REPORT_TYPE_LABELS.get(meta.get("report_type"), meta.get("report_type", "Report"))
    audience_label = AUDIENCE_LABELS.get(meta.get("audience"), meta.get("audience", ""))
    verif = _verification_summary(meta.get("verification"))
    oa = report.get("overall_assessment") or {}

    findings_html = "".join(
        f"""
        <li class="finding finding--{_esc(f.get('severity', ''))}">
          <span class="finding-severity">{_esc(SEVERITY_LABELS.get(f.get('severity'), f.get('severity', '')))}</span>
          <strong>{_esc(f.get('title', ''))}</strong>
          <p>{_esc(f.get('detail', ''))}</p>
        </li>"""
        for f in report.get("key_findings", [])
    )

    sections_html = "".join(
        f"""
        <section>
          <h2>{_esc(s.get('heading', ''))}</h2>
          <p>{_esc(s.get('body', ''))}</p>
        </section>"""
        for s in report.get("sections", [])
    )

    watch_html = "".join(f"<li>{_esc(item)}</li>" for item in report.get("what_to_watch", []))
    caveats_html = "".join(f"<li>{_esc(item)}</li>" for item in report.get("caveats", []))

    glossary_items = report.get("glossary", [])
    glossary_html = ""
    if glossary_items:
        entries = "".join(
            f"<dt>{_esc(g.get('term', ''))}</dt><dd>{_esc(g.get('plain_meaning', ''))}</dd>"
            for g in glossary_items
        )
        glossary_html = f"<section><h2>Glossary</h2><dl>{entries}</dl></section>"

    verification_notes_html = ""
    if not verif["ok"]:
        v = verif["verification"]
        items = []
        for item in v.get("unmatched_numbers", []):
            items.append(
                f"<li>Figure “{_esc(item.get('value'))}” could not be matched to the "
                f"facts pack (near: “{_esc(item.get('context'))}”).</li>"
            )
        for item in v.get("invalid_evidence_ids", []):
            items.append(
                f"<li>Evidence id “{_esc(item.get('id'))}” referenced in "
                f"{_esc(item.get('path'))} does not exist in the facts pack.</li>"
            )
        for item in v.get("banned_terms", []):
            items.append(f"<li>Disallowed wording “{_esc(item.get('term'))}” was found in the text.</li>")
        verification_notes_html = (
            f"<section class='verification-detail'><h2>Verification notes</h2><ul>{''.join(items)}</ul></section>"
        )

    badge_class = "badge--ok" if verif["ok"] else "badge--warn"

    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(report.get('headline', 'River Coln report'))}</title>
<style>
  :root {{
    --ink: #1a2b22; --paper: #ffffff; --muted: #55645c; --line: #d8ded9;
    --good: #1c7a3c; --watch: #9a6a00; --concern: #a3271f;
    --band-bg: #eef3ef; --accent: #1f6f4a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: Georgia, 'Times New Roman', serif;
    color: var(--ink); background: var(--paper);
    max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 4rem;
    line-height: 1.5; font-size: 17px;
  }}
  h1 {{ font-size: 1.6rem; line-height: 1.25; margin: 0 0 0.25rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid var(--line); padding-bottom: 0.25rem; }}
  .meta {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 1rem; }}
  .badge {{ display: inline-block; padding: 0.35rem 0.75rem; border-radius: 999px; font-size: 0.85rem; font-weight: bold; margin: 0.5rem 0 1.25rem; }}
  .badge--ok {{ background: #e3f3e8; color: var(--good); border: 1px solid var(--good); }}
  .badge--warn {{ background: #fbf1de; color: var(--watch); border: 1px solid var(--watch); }}
  .summary {{ font-size: 1.05rem; }}
  .assessment {{ background: var(--band-bg); border-radius: 0.5rem; padding: 1rem 1.25rem; margin: 1.25rem 0; }}
  .assessment .band {{ font-weight: bold; }}
  ul.findings {{ list-style: none; padding: 0; margin: 0; }}
  .finding {{ border-left: 4px solid var(--line); padding: 0.5rem 0 0.5rem 0.9rem; margin-bottom: 0.9rem; }}
  .finding--good {{ border-color: var(--good); }}
  .finding--watch {{ border-color: var(--watch); }}
  .finding--concern {{ border-color: var(--concern); }}
  .finding-severity {{ display: block; font-size: 0.75rem; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }}
  .finding p {{ margin: 0.25rem 0 0; }}
  dl {{ margin: 0; }}
  dt {{ font-weight: bold; margin-top: 0.75rem; }}
  dd {{ margin: 0.15rem 0 0; color: var(--ink); }}
  .verification-detail ul {{ font-size: 0.9rem; color: var(--muted); }}
  footer {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line); color: var(--muted); font-size: 0.8rem; }}
  .print-button {{ margin: 1rem 0; }}
  button {{ font: inherit; padding: 0.5rem 1rem; border-radius: 0.4rem; border: 1px solid var(--accent); background: var(--accent); color: white; cursor: pointer; }}
  @media print {{
    .print-button {{ display: none; }}
    body {{ max-width: none; padding: 0; font-size: 12pt; }}
    @page {{ size: A4; margin: 20mm 16mm; }}
  }}
</style>
</head>
<body>
  <div class="print-button"><button onclick="window.print()">Print / save as PDF</button></div>
  <h1>{_esc(report.get('headline', ''))}</h1>
  <p class="meta">{_esc(type_label)} &middot; {_esc(meta.get('report_key', ''))} &middot; for {_esc(audience_label)} &middot; generated {_esc(meta.get('generated_at', ''))}</p>
  <div class="badge {badge_class}">{_esc(verif['headline'])}</div>
  <p class="summary">{_esc(report.get('summary_plain', ''))}</p>

  <div class="assessment">
    <div class="band">Overall: {_esc(_band_display(oa.get('band')))}</div>
    <div>Confidence: {_esc(oa.get('confidence', ''))}</div>
    <p>{_esc(oa.get('one_line_reason', ''))}</p>
  </div>

  <h2>Key findings</h2>
  <ul class="findings">{findings_html}</ul>

  {sections_html}

  <h2>What this means</h2>
  <p>{_esc(report.get('what_this_means', ''))}</p>

  <h2>What to watch next round</h2>
  <ul>{watch_html}</ul>

  <h2>Caveats</h2>
  <ul>{caveats_html}</ul>

  {glossary_html}
  {verification_notes_html}

  <footer>
    Generated automatically by the Coln River Guardians reporting engine
    ({_esc(meta.get('provider', ''))} {_esc(meta.get('model', ''))}), version {_esc(meta.get('version', ''))}.
    Water quality here is measured against Water Framework Directive bands for a lowland,
    high-alkalinity river; it is not a bathing-water safety assessment.
  </footer>
</body>
</html>"""
