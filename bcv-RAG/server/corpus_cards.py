"""Resolve cfabric retriever hits into displayable search result cards.

Calls the local corpus engine for each corpus:BBCCCVVV hit and formats
the syntactic hierarchy into a human-readable excerpt.
"""
from __future__ import annotations

import logging

from indexer.references import decode, human
from query.retrieve import Hit, _usfm_to_corpus

logger = logging.getLogger(__name__)


def resolve_corpus_hits(hits: list[Hit]) -> dict[str, dict]:
    """Fetch syntactic data from the corpus engine for corpus:* hits."""
    if not hits:
        return {}

    results: dict[str, dict] = {}

    try:
        from corpus import engine
        for h in hits:
            bbcccvvv = int(h.chunk_id.split(":")[1])
            code, chapter, verse = decode(bbcccvvv)

            try:
                book_name, corpus = _usfm_to_corpus(code)
            except ValueError:
                continue

            data = engine.get_context(
                book=book_name, chapter=chapter, verse=verse, corpus=corpus,
            )
            if "error" in data:
                continue

            passage_str = human(bbcccvvv)
            excerpt = _format_context(data, corpus)

            results[h.chunk_id] = {
                "chunk_id": h.chunk_id,
                "title": f"Syntactic analysis: {passage_str}",
                "kind": "corpus-syntax",
                "passage": passage_str,
                "tags": [f"corpus:{corpus}", f"book:{code}"],
                "excerpt": excerpt,
                "primary_path": None,
                "permalink": None,
            }

    except Exception as e:
        logger.warning("corpus engine error during card resolution: %s", e)

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
