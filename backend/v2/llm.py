"""Provider-agnostic LLM client for the v2 report engine.

`generate_json(system_prompt, user_prompt, schema) -> dict` is the only
thing the rest of the pipeline calls. Which provider actually runs is
chosen by the `REPORT_LLM_PROVIDER` env var:

- `mistral` (default — V2_SPEC_ADDENDUM.md, Change 1: the owner's existing
  key, raw HTTPS, no SDK dependency).
- `anthropic` (kept per the base spec so the owner can switch later
  without a rewrite; not exercised by this build — see that function's
  docstring).
- `stub` — no network call at all; returns schema-valid JSON built out of
  whatever facts pack is embedded in the user prompt, so the whole
  pipeline (`engine.py`, `verify.py`, `render.py`, the API) can be
  exercised with no API key and no cost.

Two independent retry loops exist, and they are not the same thing:

1. **Transient network/API errors** (timeouts, 429/5xx) are retried
   inside each provider's call function, up to `MAX_ATTEMPTS` attempts
   total, with exponential backoff.
2. **Schema-invalid JSON** (Mistral does not enforce the schema
   server-side — V2_SPEC_ADDENDUM.md, Change 1) is retried exactly once
   here in `generate_json`, with the specific validation errors appended
   to the prompt, before raising `LLMError`.

A *third* retry loop — re-generating because the numbers in the narrative
don't match the facts pack — belongs to `engine.py`, not here. This
module only ever knows about JSON-shape validity, never about facts-pack
content.

Never logs or includes `MISTRAL_API_KEY` / `ANTHROPIC_API_KEY` in any
error message, exception, or log line.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from v2 import schemas
from v2.prompts import extract_facts_pack, extract_prompt_meta

logger = logging.getLogger("v2.llm")

MAX_ATTEMPTS = 3  # 1 initial try + 2 retries, per the build spec
BASE_DELAY_SECONDS = 1.0
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


class LLMError(Exception):
    """Raised for anything the caller should treat as a failed generation
    attempt: no key configured, an unrecoverable API error, or JSON that
    still doesn't validate after one repair attempt."""


def _sleep_backoff(attempt: int) -> None:
    time.sleep(BASE_DELAY_SECONDS * (2 ** attempt))


def _resolve_provider() -> str:
    return os.environ.get("REPORT_LLM_PROVIDER", "mistral").strip().lower()


def _append_validation_errors(user_prompt: str, errors: list[str]) -> str:
    bullets = "\n".join(f"- {e}" for e in errors)
    return (
        f"{user_prompt}\n\n"
        "The previous reply did not match the required JSON schema. Send the full corrected "
        "JSON object again, fixing these specific problems and changing nothing else that was "
        "already correct:\n"
        f"{bullets}"
    )


def _parse_and_validate(raw: str, schema: dict) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [f"Response was not valid JSON: {e}"]
    if not isinstance(data, dict):
        return None, ["Response JSON must be an object at the top level, not a list or scalar."]
    return data, schemas.validate_report(data, schema)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_json(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Generate JSON matching `schema` from `system_prompt` + `user_prompt`.

    Raises `LLMError` if the configured provider can't produce valid JSON
    within its retry budget, or if `REPORT_LLM_PROVIDER` names a provider
    that doesn't exist.
    """
    provider = _resolve_provider()
    logger.info("generate_json: provider=%s", provider)

    if provider == "stub":
        return _stub_call(user_prompt)

    if provider == "anthropic":
        return _generate_via_anthropic(system_prompt, user_prompt, schema)

    if provider == "mistral":
        return _generate_via_mistral(system_prompt, user_prompt, schema)

    raise LLMError(
        f"Unknown REPORT_LLM_PROVIDER {provider!r}: expected 'mistral', 'anthropic', or 'stub'."
    )


def _generate_via_mistral(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    raw = _mistral_call(system_prompt, user_prompt)
    data, errors = _parse_and_validate(raw, schema)
    if errors:
        logger.warning("mistral response failed schema validation (%d issue(s)); retrying once", len(errors))
        corrected_prompt = _append_validation_errors(user_prompt, errors)
        raw2 = _mistral_call(system_prompt, corrected_prompt)
        data, errors = _parse_and_validate(raw2, schema)
        if errors:
            raise LLMError(
                "Mistral response failed schema validation after one repair attempt: "
                + "; ".join(errors)
            )
    return data


def _generate_via_anthropic(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    data = _anthropic_call(system_prompt, user_prompt, schema)
    errors = schemas.validate_report(data, schema)
    if errors:
        logger.warning("anthropic response failed schema validation (%d issue(s)); retrying once", len(errors))
        corrected_prompt = _append_validation_errors(user_prompt, errors)
        data = _anthropic_call(system_prompt, corrected_prompt, schema)
        errors = schemas.validate_report(data, schema)
        if errors:
            raise LLMError(
                "Anthropic response failed schema validation after one repair attempt: "
                + "; ".join(errors)
            )
    return data


# ---------------------------------------------------------------------------
# Mistral — raw HTTPS, no SDK dependency (V2_SPEC_ADDENDUM.md, Change 1)
# ---------------------------------------------------------------------------

def _mistral_call(system_prompt: str, user_prompt: str) -> str:
    """One full generation call to the Mistral chat-completions endpoint,
    with its own transient-error retry loop. Returns the raw assistant
    message content (a JSON string, since `response_format` is
    `json_object`) — the caller parses and validates it."""
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise LLMError(
            "MISTRAL_API_KEY is not set. Set it, or use REPORT_LLM_PROVIDER=stub for local "
            "testing without an API key."
        )
    model = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,  # repeatability; fine on Mistral, unlike the Anthropic models
        "response_format": {"type": "json_object"},
        "max_tokens": 4096,
    }).encode("utf-8")

    last_error: LLMError | None = None
    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(
            MISTRAL_API_URL,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            logger.info("mistral call: model=%s attempt=%d/%d", model, attempt + 1, MAX_ATTEMPTS)
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                usage = result.get("usage", {})
                logger.info(
                    "mistral call ok: prompt_tokens=%s completion_tokens=%s",
                    usage.get("prompt_tokens"), usage.get("completion_tokens"),
                )
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            error_body = _safe_read(e)
            if e.code in TRANSIENT_HTTP_CODES and attempt < MAX_ATTEMPTS - 1:
                logger.warning("mistral transient error %d; backing off and retrying", e.code)
                last_error = LLMError(f"Mistral API error {e.code} (after retries): {error_body}")
                _sleep_backoff(attempt)
                continue
            raise LLMError(f"Mistral API error {e.code}: {error_body}") from None
        except urllib.error.URLError as e:
            if attempt < MAX_ATTEMPTS - 1:
                logger.warning("mistral connection error %s; backing off and retrying", e.reason)
                last_error = LLMError(f"Mistral connection error (after retries): {e.reason}")
                _sleep_backoff(attempt)
                continue
            raise LLMError(f"Mistral connection error: {e.reason}") from None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise LLMError(f"Mistral API returned an unexpected response shape: {e}") from None
    raise last_error or LLMError("Mistral API call failed for an unknown reason")


def _safe_read(http_error: urllib.error.HTTPError) -> str:
    try:
        return http_error.read().decode("utf-8", errors="replace")
    except Exception:
        return "<no response body>"


# ---------------------------------------------------------------------------
# Anthropic — kept per the base spec for a future switch; NOT exercised by
# this build (V2_SPEC_ADDENDUM.md, Change 1: "does not need to be
# exercised"). The `anthropic` package is imported lazily so its absence
# never breaks the mistral/stub paths or `import main_v2`.
# ---------------------------------------------------------------------------

def _anthropic_call(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise LLMError(
            "REPORT_LLM_PROVIDER=anthropic requires the 'anthropic' package, which is not "
            "installed. Run `pip install anthropic`, or use REPORT_LLM_PROVIDER=mistral or "
            "=stub instead."
        ) from e

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
    client = anthropic.Anthropic(api_key=api_key)

    last_error: LLMError | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            logger.info("anthropic call: model=%s attempt=%d/%d", model, attempt + 1, MAX_ATTEMPTS)
            # Per V2_SPEC.md: no temperature/top_p/top_k/budget_tokens (400s on
            # this model), structured output + high effort + adaptive thinking
            # live inside `output_config`, and max_tokens=16000 non-streaming.
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "format": {"type": "json_schema", "schema": schema},
                    "effort": "high",
                },
                thinking={"type": "adaptive"},
            )
            if getattr(response, "stop_reason", None) == "refusal":
                raise LLMError("Anthropic model refused to generate this report.")
            return json.loads(_extract_anthropic_text(response))
        except anthropic.NotFoundError as e:
            raise LLMError(f"Anthropic model {model!r} not found: {e}") from None
        except anthropic.RateLimitError as e:
            if attempt < MAX_ATTEMPTS - 1:
                _sleep_backoff(attempt)
                last_error = LLMError(f"Anthropic rate limited (after retries): {e}")
                continue
            raise LLMError(f"Anthropic rate limited: {e}") from None
        except anthropic.APIStatusError as e:
            status = getattr(e, "status_code", None)
            if status in TRANSIENT_HTTP_CODES and attempt < MAX_ATTEMPTS - 1:
                _sleep_backoff(attempt)
                last_error = LLMError(f"Anthropic API error {status} (after retries): {e}")
                continue
            raise LLMError(f"Anthropic API error {status}: {e}") from None
        except anthropic.APIConnectionError as e:
            if attempt < MAX_ATTEMPTS - 1:
                _sleep_backoff(attempt)
                last_error = LLMError(f"Anthropic connection error (after retries): {e}")
                continue
            raise LLMError(f"Anthropic connection error: {e}") from None
    raise last_error or LLMError("Anthropic API call failed for an unknown reason")


def _extract_anthropic_text(response) -> str:
    """Best-effort extraction of the JSON text from an Anthropic Messages
    response's content blocks. Unexercised (see module docstring) — kept
    deliberately simple rather than tuned against a real response."""
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            return text
    raise LLMError("Anthropic response had no text content block to parse as JSON.")


# ---------------------------------------------------------------------------
# Stub — no network call, no cost, no API key. Builds a schema-valid
# report by citing real ids/values pulled back out of the facts pack
# embedded in the user prompt, so the verification step downstream has
# something real to check rather than an empty pass.
# ---------------------------------------------------------------------------

def _stub_call(user_prompt: str) -> dict:
    facts = extract_facts_pack(user_prompt) or {}
    meta = extract_prompt_meta(user_prompt)
    return _build_stub_report(facts, meta.get("report_type", ""), meta.get("audience", ""))


def _collect_numeric_facts(node, out: list[tuple[str, float]]) -> None:
    if isinstance(node, dict):
        fid, value = node.get("id"), node.get("value")
        if isinstance(fid, str) and isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append((fid, value))
        for v in node.values():
            _collect_numeric_facts(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_numeric_facts(item, out)


def _fmt(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def _build_stub_report(facts: dict, report_type: str, audience: str) -> dict:
    numeric_facts: list[tuple[str, float]] = []
    _collect_numeric_facts(facts, numeric_facts)
    sample = numeric_facts[:6]

    if sample:
        key_findings = [
            {
                "title": f"Stub finding citing {fid}",
                "detail": (
                    f"This is placeholder text from the stub LLM provider (no real model was "
                    f"called). The facts pack records {fid} as {_fmt(val)}."
                ),
                "severity": "watch",
                "evidence_ids": [fid],
            }
            for fid, val in sample[:3]
        ]
    else:
        key_findings = []
    while len(key_findings) < 3:
        key_findings.append({
            "title": "Placeholder finding",
            "detail": (
                "This is placeholder text from the stub LLM provider, used to exercise the "
                "reporting pipeline without an API key or cost."
            ),
            "severity": "watch",
            "evidence_ids": [],
        })

    cited = ", ".join(f"{fid} = {_fmt(val)}" for fid, val in sample[:4]) if sample else (
        "No numeric figures were available in the facts pack for this report."
    )

    return {
        "headline": (f"Stub {report_type or 'test'} report for the {audience or 'volunteer'} audience")[:90],
        "summary_plain": (
            "This is a placeholder report generated by the stub LLM provider so the reporting "
            "pipeline can be tested without an API key or cost. It is not written by a language "
            "model."
        ),
        "overall_assessment": {
            "band": None,
            "confidence": "low",
            "one_line_reason": "Stub provider output; no real assessment was made.",
        },
        "key_findings": key_findings[:6],
        "sections": [
            {
                "heading": "About this stub report",
                "body": (
                    "This report was produced by the stub LLM provider (REPORT_LLM_PROVIDER="
                    "stub). No real language model was called; the text here cites real figures "
                    "from the facts pack so the verification step can be exercised end to end."
                ),
                "evidence_ids": [fid for fid, _ in sample[:2]],
            },
            {
                "heading": "Figures on record",
                "body": f"Figures cited in this stub report: {cited}",
                "evidence_ids": [fid for fid, _ in sample[:4]],
            },
        ],
        "what_this_means": "No real interpretation is offered; this is stub output for pipeline testing.",
        "what_to_watch": [
            "Set REPORT_LLM_PROVIDER=mistral (with MISTRAL_API_KEY set) for a real report.",
            "Check that the facts pack contains the figures expected for this report type.",
        ],
        "caveats": [
            "This report was generated by the stub provider and contains no real analysis.",
        ],
        "glossary": [],
    }
