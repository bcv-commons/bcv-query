"""Chat-completion wrapper: Groq (primary) → OpenAI (fallback).

Both providers expose OpenAI-compatible APIs, so we use the `openai` SDK
with two configured clients. Fallback triggers: rate-limit (429),
connection errors, and 5xx responses from Groq. 4xx errors other than 429
are NOT swallowed — they indicate a client-side bug, not a provider outage.
"""
from __future__ import annotations

import os
from typing import Literal

def _model_setting(name: str) -> str:
    """Resolve a model setting from the env (clean NAME, or legacy BTMCP_NAME). '' if unset."""
    return (os.environ.get(name) or os.environ.get(f"BTMCP_{name}") or "").strip()


def _require_model(name: str) -> str:
    """The model MUST be set in the env — NO hardcoded fallback. A stale default silently
    serving the wrong model is a footgun (and drifts from what the .env intends). Validated
    at call time so the error points at the actual missing config."""
    v = _model_setting(name)
    if not v:
        raise RuntimeError(f"{name} is not set — set it in the .env (no hardcoded model default)")
    return v


# Infra / behaviour settings (NOT stale-prone model choices), so a sensible default is fine:
#   GROQ_BASE_URL         — the Groq endpoint (the API contract, same for everyone).
#   GROQ_REASONING_EFFORT — 'none' disables chain-of-thought on reasoning models so the answer
#                           fits the token budget; set low|medium|high to re-enable, '' to omit.
GROQ_BASE_URL = _model_setting("GROQ_BASE_URL") or "https://api.groq.com/openai/v1"
GROQ_REASONING_EFFORT = os.environ.get(
    "GROQ_REASONING_EFFORT", os.environ.get("BTMCP_GROQ_REASONING_EFFORT", "none"))
_REASONING_FAMILIES = ("qwen3", "gpt-oss", "deepseek-r1")


def _is_reasoning_model(model: str) -> bool:
    return any(fam in model.lower() for fam in _REASONING_FAMILIES)


def _strip_think(text: str) -> str:
    """Drop any leaked <think>…</think> chain-of-thought; keep the rest."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _clean_key(name: str, value: str | None) -> str | None:
    """Strip whitespace and reject non-ASCII keys before they hit httpx headers."""
    if not value:
        return None
    cleaned = value.strip()
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError as e:
        bad = cleaned[e.start:e.end]
        raise RuntimeError(
            f"{name} contains a non-ASCII character {bad!r} at position {e.start}. "
            f"This is almost always a copy-paste artifact (smart quote, non-breaking "
            f"space, German ß, etc.). Re-copy the key from a plain-text source."
        ) from None
    return cleaned


def _build_clients():
    """Lazy-import openai so the module is importable without the SDK installed."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

    groq_key = _clean_key("GROQ_API_KEY", os.environ.get("GROQ_API_KEY"))
    openai_key = _clean_key("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY"))
    if not groq_key and not openai_key:
        raise RuntimeError("set GROQ_API_KEY and/or OPENAI_API_KEY")

    groq = OpenAI(base_url=GROQ_BASE_URL, api_key=groq_key) if groq_key else None
    oai = OpenAI(api_key=openai_key) if openai_key else None
    return groq, oai, (APIConnectionError, APIStatusError, RateLimitError)


def chat_completion(
    *,
    system: str,
    user: str,
    response_format: Literal["json", "text"] = "text",
    max_tokens: int = 800,
    temperature: float = 0.2,
) -> str:
    """Return the assistant content string. Falls back from Groq → OpenAI on transient errors."""
    groq, oai, transient_errors = _build_clients()
    from openai import APIConnectionError, APIStatusError, RateLimitError

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    extras: dict = {"max_tokens": max_tokens, "temperature": temperature}
    if response_format == "json":
        extras["response_format"] = {"type": "json_object"}

    last_err: Exception | None = None
    if groq is not None:
        groq_model = _require_model("GROQ_MODEL")
        try:
            groq_extras = dict(extras)
            # disable/limit thinking on reasoning models so the answer fits the token budget
            if GROQ_REASONING_EFFORT and _is_reasoning_model(groq_model):
                groq_extras["extra_body"] = {"reasoning_effort": GROQ_REASONING_EFFORT}
            resp = groq.chat.completions.create(model=groq_model, messages=messages, **groq_extras)
            return _strip_think(resp.choices[0].message.content or "")
        except transient_errors as e:
            last_err = e
            should_fallback = (
                isinstance(e, (RateLimitError, APIConnectionError))
                or (isinstance(e, APIStatusError) and (e.status_code >= 500 or e.status_code == 429))
            )
            if not should_fallback:
                raise

    if oai is not None:
        resp = oai.chat.completions.create(model=_require_model("OPENAI_MODEL"),
                                           messages=messages, **extras)
        return resp.choices[0].message.content or ""

    raise RuntimeError(f"groq failed and no OpenAI fallback configured: {last_err!r}")
