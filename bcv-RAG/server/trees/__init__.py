"""Perspective-tree builders.

Every builder takes (db, lang, path: list[str]) and returns either:
  {'children': [...]}  — for intermediate nodes
  {'chunks':   [...]}  — for leaf nodes
plus a 'node' dict describing the current position in the tree.
"""
from __future__ import annotations

from typing import Callable, Protocol

from . import (
    scripture, source, kind, term, methodology, pericope, aquifer,
    bible, topic, entity, lexicon, morphology, transcript,
)


class TreeBuilder(Protocol):
    def root(self, db, *, lang: str) -> dict: ...
    def descend(self, db, path: list[str], *, lang: str) -> dict: ...


BUILDERS: dict[str, TreeBuilder] = {
    # "scripture" removed — BSB is the sole Bible source; use "bible" tree.
    "source":      source,        # type: ignore[dict-item]
    "kind":        kind,          # type: ignore[dict-item]
    "term":        term,          # type: ignore[dict-item]
    "methodology": methodology,   # type: ignore[dict-item]
    "pericope":    pericope,      # type: ignore[dict-item]
    "aquifer":     aquifer,       # type: ignore[dict-item]
    "bible":       bible,         # type: ignore[dict-item]
    "topic":       topic,         # type: ignore[dict-item]
    "entity":      entity,        # type: ignore[dict-item]
    "lexicon":     lexicon,       # type: ignore[dict-item]
    "morphology":  morphology,    # type: ignore[dict-item]
    "transcript":  transcript,    # type: ignore[dict-item]
}
