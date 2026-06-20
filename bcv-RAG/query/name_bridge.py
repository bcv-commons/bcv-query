"""Strong's bridge — resolve a localized person/place name to its English entity.

The `entities` graph (Theographic) is English-only, so non-English genealogy /
entity queries ("отец Давида", "uban Dauda") never match by name. This bridges:

    localized surface  --aligned_lex/<lang>-->  Strong's  --(reverse)-->  English entity

The reverse map (Strong's -> English entity name) is derived once from
`entities` × `aligned_lex/en` — no per-language name lists to maintain. Works
for every language that has an `aligned_lex/<lang>.tsv`, including declined forms
that appear in the aligned text (e.g. ru genitive "давида" -> H1732).

Best-effort: returns [] when there's no aligned surface or no entity for the
Strong's, so callers fall back to their existing behavior.
"""
from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from resource_paths import resource_path
from lang import canon

_ALIGNED_DIR = resource_path("aligned_lex")


@lru_cache(maxsize=16)
def _surface_to_strong(lang: str) -> dict[str, str]:
    """Dominant Strong's per surface form, from aligned_lex/<lang>.tsv
    (columns: surface, strong, count, share). {} if the file is absent."""
    p = _ALIGNED_DIR / f"{canon(lang)}.tsv"
    if not p.exists():
        return {}
    best: dict[str, tuple[str, float]] = {}
    with p.open(encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            surface, strong, _count, share = parts[0], parts[1], parts[2], parts[3]
            try:
                sh = float(share)
            except ValueError:
                continue
            cur = best.get(surface)
            if cur is None or sh > cur[1]:
                best[surface] = (strong, sh)
    return {s: v[0] for s, v in best.items()}


# Strong's -> [English entity name]. Static per DB/process; built lazily once.
_strong_to_entities: dict[str, list[str]] | None = None


def _build_strong_to_entities(db: sqlite3.Connection) -> dict[str, list[str]]:
    en = _surface_to_strong("eng")
    if not en:
        return {}
    out: dict[str, list[str]] = {}
    try:
        rows = db.execute("SELECT name FROM entities").fetchall()
    except sqlite3.OperationalError:
        return {}
    for (name,) in rows:
        if not name:
            continue
        strong = en.get(name.lower())
        if strong:
            names = out.setdefault(strong, [])
            if name not in names:
                names.append(name)
    return out


def localized_to_english(db: sqlite3.Connection, name: str, lang: str) -> list[str]:
    """Candidate English entity name(s) for a localized name. [] if no bridge."""
    global _strong_to_entities
    if not name or not lang or canon(lang) == "eng":
        return []
    strong = _surface_to_strong(lang).get(name.lower())
    if not strong:
        return []
    if _strong_to_entities is None:
        _strong_to_entities = _build_strong_to_entities(db)
    return _strong_to_entities.get(strong, [])
