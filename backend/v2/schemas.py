"""Report JSON schema and hand-rolled validator.

Mistral's `response_format={"type":"json_object"}` only guarantees the
reply is *some* JSON object — it does not enforce a schema server-side the
way the Anthropic Messages API's structured-output mode does (see
V2_SPEC_ADDENDUM.md, Change 1). So the validation here is load-bearing,
not a safety net: every report, from every provider (including the
stub), passes through `validate_report` before `llm.py` will hand it back
to `engine.py`.

Deliberately hand-rolled rather than a dependency on the `jsonschema`
package — the addendum explicitly allows this ("hand-rolled is fine and
avoids a dependency"). It supports the small subset of JSON Schema this
project actually needs: object/array/string/number/integer/boolean/null
types (a list of types for nullable fields, e.g. `["string", "null"]`),
`enum`, `required`, `additionalProperties: false`, `items`, `min_items` /
`max_items`, and `max_length` / `min_length`. It is not a general-purpose
JSON Schema implementation.

This module has no imports from the rest of the v2 package on purpose —
`llm.py`, `prompts.py`, `verify.py` and `engine.py` all depend on it, so
it stays a leaf module.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared enums — the canonical list other v2 modules import rather than
# retype (report_type/audience values, band names, etc).
# ---------------------------------------------------------------------------

REPORT_TYPES = ("location", "round", "catchment", "comparison", "trend", "data_quality")
AUDIENCES = ("volunteer", "public", "technical")

BAND_NAMES = ("Excellent", "Good", "Moderate", "Poor", "Bad")
# A report's *overall* assessment may legitimately span more than one
# band (e.g. a catchment report where different locations sit in
# different bands) or not apply at all (e.g. a data_quality report is not
# a chemistry judgement) — "Mixed" and JSON null cover those two cases
# respectively; see `overall_assessment.band` below.
OVERALL_BAND_VALUES = BAND_NAMES + ("Mixed",)
CONFIDENCE_LEVELS = ("high", "medium", "low")
SEVERITY_LEVELS = ("good", "watch", "concern")


def _finding_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "detail", "severity", "evidence_ids"],
        "properties": {
            "title": {"type": "string", "max_length": 120},
            "detail": {"type": "string", "max_length": 800},
            "severity": {"type": "string", "enum": list(SEVERITY_LEVELS)},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _section_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["heading", "body", "evidence_ids"],
        "properties": {
            "heading": {"type": "string", "max_length": 120},
            "body": {"type": "string", "max_length": 4000},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
        },
    }


def _glossary_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["term", "plain_meaning"],
        "properties": {
            "term": {"type": "string", "max_length": 80},
            "plain_meaning": {"type": "string", "max_length": 400},
        },
    }


# The report JSON schema, per V2_SPEC.md's "LLM report engine > Structured
# output" section. `additionalProperties: false` everywhere and every
# property listed in `required`, per that section's instruction — nothing
# here is silently optional; fields that don't apply to a given report
# type still have to be present (using JSON null where the schema allows
# it, e.g. `overall_assessment.band` for a data_quality report).
REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "headline", "summary_plain", "overall_assessment", "key_findings",
        "sections", "what_this_means", "what_to_watch", "caveats", "glossary",
    ],
    "properties": {
        "headline": {"type": "string", "max_length": 90},
        "summary_plain": {"type": "string", "max_length": 600},
        "overall_assessment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["band", "confidence", "one_line_reason"],
            "properties": {
                "band": {"type": ["string", "null"], "enum": list(OVERALL_BAND_VALUES)},
                "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                "one_line_reason": {"type": "string", "max_length": 200},
            },
        },
        "key_findings": {
            "type": "array", "min_items": 3, "max_items": 6,
            "items": _finding_schema(),
        },
        "sections": {
            "type": "array", "min_items": 2, "max_items": 5,
            "items": _section_schema(),
        },
        "what_this_means": {"type": "string", "max_length": 800},
        "what_to_watch": {
            "type": "array", "min_items": 2, "max_items": 4,
            "items": {"type": "string", "max_length": 200},
        },
        "caveats": {
            "type": "array", "min_items": 1, "max_items": 8,
            "items": {"type": "string", "max_length": 300},
        },
        "glossary": {
            "type": "array", "min_items": 0, "max_items": 6,
            "items": _glossary_schema(),
        },
    },
}


# A worked example of the shape above, embedded in the system prompt
# (`prompts.py`) so Mistral — which cannot be handed the schema itself the
# way the Anthropic API can — has a concrete instance to copy the shape
# of. The wording and figures are illustrative only; a real report must
# use the real facts pack it was given, never these numbers.
EXAMPLE_REPORT = {
    "headline": "Phosphate has improved to the Good band at grace.reprints.jigsaw",
    "summary_plain": (
        "The most recent sample at this location scored in the Good band for phosphate, "
        "an improvement on the Moderate band recorded a year ago. Other measurements stayed "
        "within their usual range for this location."
    ),
    "overall_assessment": {
        "band": "Good",
        "confidence": "medium",
        "one_line_reason": "Based on 14 usable readings spanning 18 months, with no gaps over 60 days.",
    },
    "key_findings": [
        {
            "title": "Phosphate has moved from Moderate to Good",
            "detail": (
                "The latest phosphate reading was 0.18 mg/L, in the Good band, down from a mean "
                "of 0.34 mg/L (Moderate band) across all readings at this location."
            ),
            "severity": "good",
            "evidence_ids": [
                "location|grace.reprints.jigsaw|phosphate|latest",
                "location|grace.reprints.jigsaw|phosphate|mean",
            ],
        },
        {
            "title": "Ammonia has stayed in the High band throughout",
            "detail": (
                "Every usable ammonia reading at this location has stayed in the High band, the "
                "best band, across the full sampling history."
            ),
            "severity": "good",
            "evidence_ids": ["location|grace.reprints.jigsaw|ammonia|band_percentages"],
        },
        {
            "title": "Most turbidity readings here were recorded as clear",
            "detail": (
                "Volunteers described how the water looked rather than taking a meter reading at "
                "most visits: 11 of 14 visits recorded the water as Clear or Very clear, with no "
                "cloudier description than Slightly cloudy at any visit."
            ),
            "severity": "good",
            "evidence_ids": ["location|grace.reprints.jigsaw|turbidity|category_counts"],
        },
    ],
    "sections": [
        {
            "heading": "What was measured here",
            "body": (
                "This location has been sampled 14 times between March 2024 and August 2025. "
                "Phosphate, ammonia and nitrate were recorded at most visits; two phosphate "
                "readings were below the test kit's detection limit and are shown as upper-bound "
                "estimates rather than exact figures, and one nitrate reading was a test-strip "
                "band rather than a single figure. Turbidity was mostly recorded in words "
                "describing how clear the water looked, not as a number. Dissolved oxygen and "
                "conductivity are not currently measured at this location, so this report does "
                "not draw any conclusion about them."
            ),
            "evidence_ids": ["location|grace.reprints.jigsaw|n_usable"],
        },
        {
            "heading": "Where this location sits on the river",
            "body": (
                "This is point 12 of 48 sampling locations from the source, downstream of "
                "doubt.bridge.leopard and upstream of luring.tram.dolphins."
            ),
            "evidence_ids": ["location|grace.reprints.jigsaw|river_order"],
        },
    ],
    "what_this_means": (
        "The phosphate improvement is a positive sign for plant and algae growth at this "
        "location, though one round of sampling is not enough on its own to say the change will "
        "continue."
    ),
    "what_to_watch": [
        "Whether the next few rounds confirm phosphate staying in the Good band or better.",
        "Turbidity after heavy rain, since no clear trend has appeared yet either way.",
    ],
    "caveats": [
        "Readings come from volunteer test kits, which are less precise than laboratory equipment.",
        "Two readings were below the test kit's detection limit and are recorded as upper-bound "
        "estimates, not exact figures.",
        "One nitrate reading was a test-strip colour band rather than a single figure, and is "
        "shown as a range rather than an exact number.",
        "Dissolved oxygen and conductivity are not currently measured at this location.",
    ],
    "glossary": [
        {
            "term": "Good band",
            "plain_meaning": "The second-best of five bands used to judge a river reading; not "
            "perfect, but low risk.",
        },
        {
            "term": "detection limit",
            "plain_meaning": "The smallest amount a test kit can reliably measure; anything below "
            "it is reported as 'less than' that amount.",
        },
    ],
}


# ---------------------------------------------------------------------------
# Hand-rolled validator
# ---------------------------------------------------------------------------

def validate_report(data, schema: dict | None = None) -> list[str]:
    """Validate `data` against `schema` (default `REPORT_SCHEMA`).

    Returns a list of human-readable error strings; an empty list means
    `data` is valid. Never raises on malformed `data` — a wrong type at
    any point becomes an error string, not an exception, so callers can
    always turn the result straight into a correction prompt.
    """
    schema = REPORT_SCHEMA if schema is None else schema
    return _validate_node(data, schema, "$")


def _type_ok(value, type_spec) -> bool:
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    for t in types:
        if t == "string" and isinstance(value, str):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "object" and isinstance(value, dict):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "null" and value is None:
            return True
    return False


def _validate_node(value, node: dict, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = node.get("type")
    if expected_type is not None and not _type_ok(value, expected_type):
        errors.append(f"{path}: expected type {expected_type!r}, got {type(value).__name__}")
        return errors  # further checks would be meaningless against the wrong type

    if value is None:
        return errors  # null already satisfied the type check above; nothing else applies

    enum = node.get("enum")
    if enum is not None and value not in enum:
        errors.append(f"{path}: value {value!r} is not one of {enum!r}")

    if isinstance(value, str):
        max_len = node.get("max_length")
        if max_len is not None and len(value) > max_len:
            errors.append(f"{path}: string is {len(value)} characters, longer than the {max_len} limit")
        min_len = node.get("min_length")
        if min_len is not None and len(value) < min_len:
            errors.append(f"{path}: string is empty or shorter than the {min_len}-character minimum")

    if isinstance(value, dict) and node.get("type") == "object":
        properties = node.get("properties", {})
        required = node.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required field {key!r}")
        if node.get("additionalProperties") is False:
            extra = set(value.keys()) - set(properties.keys())
            if extra:
                errors.append(
                    f"{path}: unexpected field(s) {sorted(extra)!r} — only "
                    f"{sorted(properties.keys())!r} are allowed"
                )
        for key, sub_schema in properties.items():
            if key in value:
                errors.extend(_validate_node(value[key], sub_schema, f"{path}.{key}"))

    if isinstance(value, list) and node.get("type") == "array":
        min_items = node.get("min_items")
        max_items = node.get("max_items")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: has {len(value)} item(s), fewer than the required minimum of {min_items}")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: has {len(value)} item(s), more than the allowed maximum of {max_items}")
        item_schema = node.get("items")
        if item_schema:
            for i, item in enumerate(value):
                errors.extend(_validate_node(item, item_schema, f"{path}[{i}]"))

    return errors


def describe_schema(schema: dict | None = None) -> str:
    """Render `schema` as a compact bullet-point description for the
    system prompt. `REPORT_SCHEMA` itself drives `validate_report`; this
    text is what shows the model the shape it needs to produce, since
    Mistral (unlike the Anthropic API) cannot be handed a machine-readable
    schema directly — see V2_SPEC_ADDENDUM.md, Change 1."""
    schema = REPORT_SCHEMA if schema is None else schema
    return "\n".join(_describe_node(schema, "the report object", 0))


def _describe_node(node: dict, name: str, indent: int) -> list[str]:
    pad = "  " * indent
    lines = []
    node_type = node.get("type")
    if node_type == "object":
        required = set(node.get("required", []))
        field_names = ", ".join(node.get("properties", {}).keys())
        lines.append(f"{pad}- {name}: object with exactly these fields: {field_names}")
        for key, sub in node.get("properties", {}).items():
            req_word = "required" if key in required else "optional"
            lines.extend(_describe_node(sub, f'"{key}" ({req_word})', indent + 1))
    elif node_type == "array":
        bounds = []
        if "min_items" in node:
            bounds.append(f"min {node['min_items']}")
        if "max_items" in node:
            bounds.append(f"max {node['max_items']}")
        bound_text = f" ({', '.join(bounds)} items)" if bounds else ""
        lines.append(f"{pad}- {name}: array{bound_text}, each item:")
        items = node.get("items")
        if items:
            lines.extend(_describe_node(items, "item", indent + 1))
    else:
        extras = []
        if node.get("enum"):
            extras.append(f"one of {node['enum']}")
        if node.get("max_length"):
            extras.append(f"max {node['max_length']} characters")
        extra_text = f" — {'; '.join(extras)}" if extras else ""
        lines.append(f"{pad}- {name}: {node_type}{extra_text}")
    return lines
