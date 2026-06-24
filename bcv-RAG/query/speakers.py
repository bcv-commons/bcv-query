"""Speaker detection + lookup for speaker-scoped retrieval (roadmap S1).

Reads the shared resources/speaker_quotations/speaker_quotations.tsv (who speaks
which verse range) so a query like "what did Jesus say about faith" can be scoped
to the passages Jesus actually speaks, intersected with the topic ("faith").

$0, read-only, one-time load. English speech-framing for now (the speaker NAMES
are language-independent; multilingual frame patterns are a future refinement).
"""
from __future__ import annotations

import re
from functools import lru_cache

from resource_paths import resource_path

_TSV = resource_path("speaker_quotations") / "speaker_quotations.tsv"

# Speech-frame cues that signal a "who-said" query (vs. merely mentioning a name).
# Possessive ("Jesus's words") is handled separately.
_FRAME = re.compile(
    r"\b(say|says|said|saying|speak|spoke|spoken|teach|taught|teaches|"
    r"command|commanded|promis\w*|declare[ds]?|tell|told|word[s]?|preach\w*)\b",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, list[tuple[int, int]]], dict[str, bool]]:
    """({speaker_lower: [(start,end), ...]}, {speaker_lower: divine})."""
    ranges: dict[str, list[tuple[int, int]]] = {}
    divine: dict[str, bool] = {}
    if not _TSV.exists():
        return ranges, divine
    with _TSV.open(encoding="utf-8") as fh:
        cols = None
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if cols is None:
                cols = {c: i for i, c in enumerate(p)}
                continue
            try:
                name = p[cols["speaker"]].strip()
                key = name.lower()
                ranges.setdefault(key, []).append(
                    (int(p[cols["start_bbcccvvv"]]), int(p[cols["end_bbcccvvv"]])))
                divine[key] = p[cols["divine"]] == "Y"
            except (KeyError, ValueError, IndexError):
                continue
    return ranges, divine


@lru_cache(maxsize=1)
def _name_lookup() -> dict[str, str]:
    """Match key → canonical speaker_lower. Includes the bare first token of
    parenthetical names (e.g. 'abraham' → 'abraham (abram)') so a query naming
    'Abraham' resolves. Longer names win on overlap."""
    ranges, _ = _load()
    out: dict[str, str] = {}
    for key in ranges:
        out[key] = key
        base = re.sub(r"\s*\(.*?\)", "", key).strip()  # "abraham (abram)" → "abraham"
        if base and base not in out:
            out[base] = key
    return out


def speaker_passages(name: str) -> list[tuple[int, int]]:
    """Verse ranges a speaker speaks (empty if unknown)."""
    ranges, _ = _load()
    return ranges.get(name.strip().lower(), [])


def is_divine(name: str) -> bool:
    _, divine = _load()
    return divine.get(name.strip().lower(), False)


def detect_speaker(text: str) -> str | None:
    """Canonical speaker name if the query is asking what a speaker said.

    Requires BOTH a known speaker name AND a speech frame (said/words/promises…)
    or a possessive ("Jesus's ..."), so "the faith of Abraham" (about him) does
    NOT trigger but "what did Abraham say" / "God's promises" does. Returns the
    canonical name as stored in the table (e.g. 'God', 'Jesus'), or None.
    """
    low = text.lower()
    lookup = _name_lookup()
    # candidate names present in the query, longest first (prefer "holy spirit")
    hits = sorted((k for k in lookup if re.search(rf"\b{re.escape(k)}\b", low)),
                  key=len, reverse=True)
    # 1) a possessive speaker wins outright ("God's promises" → God, even with
    #    other names like Abraham present)
    for k in hits:
        if re.search(rf"\b{re.escape(k)}['’]s\b", low):
            return _canonical_name(lookup[k])
    # 2) otherwise a speech frame + a named speaker ("what did Jesus say")
    if _FRAME.search(low) and hits:
        return _canonical_name(lookup[hits[0]])
    return None


@lru_cache(maxsize=1)
def _canonical_display() -> dict[str, str]:
    """speaker_lower → the as-stored display name."""
    out: dict[str, str] = {}
    if not _TSV.exists():
        return out
    with _TSV.open(encoding="utf-8") as fh:
        cols = None
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if cols is None:
                cols = {c: i for i, c in enumerate(p)}
                continue
            try:
                name = p[cols["speaker"]].strip()
                out.setdefault(name.lower(), name)
            except (KeyError, IndexError):
                continue
    return out


def _canonical_name(key: str) -> str:
    return _canonical_display().get(key, key)
