"""Resolve cfabric retriever hits into displayable search result cards.

The corpus engine now lives in **shoresh** (migration PR-2). For each
corpus:BBCCCVVV hit we call shoresh's word-context endpoint over private
networking (SHORESH_URL) and format the syntactic hierarchy into a readable
excerpt. Hits shoresh can't resolve (or when SHORESH_URL is unset) are dropped.
"""
from __future__ import annotations

import logging
import os

import httpx

from indexer.references import decode, human
from query.retrieve import Hit

logger = logging.getLogger(__name__)

SHORESH_URL = os.environ.get("SHORESH_URL", "").rstrip("/")
_TIMEOUT = 5.0


def resolve_corpus_hits(hits: list[Hit]) -> dict[str, dict]:
    """Fetch syntactic data from shoresh for corpus:* hits — one batch call, not N."""
    if not hits or not SHORESH_URL:
        return {}

    # Build the ref list once; keep a ref-key -> hit map to reattach the responses.
    by_ref: dict[str, tuple[Hit, int, str]] = {}
    for h in hits:
        bbcccvvv = int(h.chunk_id.split(":")[1])
        code, chapter, verse = decode(bbcccvvv)
        by_ref[f"{code}/{chapter}/{verse}"] = (h, bbcccvvv, code)

    try:
        with httpx.Client(base_url=SHORESH_URL, timeout=_TIMEOUT) as client:
            # ONE call resolves every verse in-process on shoresh (no per-verse round-trip).
            resp = client.get("/structure/context/batch", params={"refs": ",".join(by_ref)})
            if resp.status_code != 200:
                return {}
            batch = (resp.json() or {}).get("results", {})
    except Exception as e:
        logger.warning("shoresh corpus batch call failed: %s", e)
        return {}

    results: dict[str, dict] = {}
    for ref, (h, bbcccvvv, code) in by_ref.items():
        payload = batch.get(ref) or {}
        data = payload.get("data", {})
        corpus = payload.get("corpus", "")
        if not data:
            continue
        passage_str = human(bbcccvvv)
        results[h.chunk_id] = {
            "chunk_id": h.chunk_id,
            "title": f"Syntactic analysis: {passage_str}",
            "kind": "corpus-syntax",
            "passage": passage_str,
            "tags": [f"corpus:{corpus}", f"book:{code}"],
            "excerpt": _format_context(data, corpus),
            "primary_path": None,
            "permalink": None,
        }
    return results


def _format_context(data: dict, corpus: str) -> str:
    """Format a context response into a readable excerpt."""
    parts: list[str] = []

    word = data.get("word", {})
    text = word.get("text", "")
    gloss = word.get("gloss", "")
    pos = word.get("part_of_speech", "")
    if text:
        label = f"{text}"
        if gloss:
            label += f" ({gloss})"
        if pos:
            label += f" [{pos}]"
        parts.append(label)

    for key, info in data.items():
        if key == "word":
            continue
        if not isinstance(info, dict):
            continue
        features = info.get("features", {})
        node_text = info.get("text", "")
        typ = features.get("typ", features.get("kind", ""))
        function = features.get("function", features.get("rela", ""))

        line = key
        if typ:
            line += f" [{typ}]"
        if function:
            line += f" ({function})"
        if node_text and len(node_text) < 200:
            line += f": {node_text}"
        parts.append(line)

    return " | ".join(parts) if parts else "(no syntactic data)"
