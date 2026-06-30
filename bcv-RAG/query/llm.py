"""Chat-completion wrapper: Groq (primary) → OpenAI (fallback).

Both providers expose OpenAI-compatible APIs, so we use the `openai` SDK
with two configured clients. Fallback triggers: rate-limit (429),
connection errors, and 5xx responses from Groq. 4xx errors other than 429
are NOT swallowed — they indicate a client-side bug, not a provider outage.
"""
from __future__ import annotations

import os
from typing import Literal

def _model_env(name: str, default: str) -> str:
    """Prefer the clean NAME (e.g. GROQ_MODEL, matching ANTHROPIC_MODEL style); fall back
    to the legacy BTMCP_-prefixed var so existing deployments keep working."""
    return os.environ.get(name) or os.environ.get(f"BTMCP_{name}") or default


# Default upgraded from llama-3.3-70b-versatile (verified live on Groq 2026-06).
# Override per deploy via GROQ_MODEL, e.g.
#   GROQ_MODEL=qwen/qwen3.6-27b      # stronger for synthesis quality (this default)
#   GROQ_MODEL=openai/gpt-oss-120b   # stronger for reasoning-heavy / tool-using tasks
GROQ_MODEL = _model_env("GROQ_MODEL", "qwen/qwen3.6-27b")
OPENAI_MODEL = _model_env("OPENAI_MODEL", "gpt-4o-mini")

# qwen3 / gpt-oss / deepseek-r1 are REASONING models: by default they emit a chain-of-thought
# that leaks into (and at our token budget, crowds out) the answer. For the synthesis path we
# want the answer, not the reasoning — so disable thinking on Groq reasoning models.
# Override with GROQ_REASONING_EFFORT=low|medium|high to re-enable (or "" to send nothing).
GROQ_REASONING_EFFORT = _model_env("GROQ_REASONING_EFFORT", "none")
_REASONING_FAMILIES = ("qwen3", "gpt-oss", "deepseek-r1")
GROQ_BASE_URL = _model_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


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
        try:
            groq_extras = dict(extras)
            # disable/limit thinking on reasoning models so the answer fits the token budget
            if GROQ_REASONING_EFFORT and _is_reasoning_model(GROQ_MODEL):
                groq_extras["extra_body"] = {"reasoning_effort": GROQ_REASONING_EFFORT}
            resp = groq.chat.completions.create(model=GROQ_MODEL, messages=messages, **groq_extras)
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
        resp = oai.chat.completions.create(model=OPENAI_MODEL, messages=messages, **extras)
        return resp.choices[0].message.content or ""

    raise RuntimeError(f"groq failed and no OpenAI fallback configured: {last_err!r}")
