"""Resolve a Bible chunk's edition (resource:<id>) to display metadata.

A displayed Bible for a language can be a COMPOSITE — e.g. an aligned NT from one
edition + a plain-text OT from another (different translation/source/revision).
Each kind:bible chunk carries resource:<edition_id>; this module looks that id up
in bible_editions.json so citations show the correct version per testament
(honest provenance) instead of a raw id like "lsg-ot".

See internal-docs/multilingual-unlock-plan.md.
"""
from __future__ import annotations

import json
from functools import lru_cache

from resource_paths import resource_path

_EDITIONS = resource_path("bible_editions.json")  # resources/ (dev) | /app/resources (image)


@lru_cache(maxsize=1)
def _registry() -> dict:
    if _EDITIONS.exists():
        return json.loads(_EDITIONS.read_text(encoding="utf-8"))
    return {"editions": {}, "bibles": {}}


def edition_info(edition_id: str) -> dict | None:
    """Structured metadata for an edition id, or None if unknown."""
    return _registry().get("editions", {}).get(edition_id)


def edition_label(edition_id: str) -> str:
    """Human label, e.g. 'Louis Segond 1910' or 'Louis Segond 1910 (OT)' for an
    OT-only edition in a composite Bible. Falls back to the raw id if unknown."""
    e = edition_info(edition_id)
    if not e:
        return edition_id
    label = e.get("name", edition_id)
    if e.get("books") == "ot":
        label += " (OT)"
    elif e.get("books") == "nt":
        label += " (NT)"
    return label


def edition_citation(edition_id: str) -> dict | None:
    """Compact edition block for an API citation, or None if unknown."""
    e = edition_info(edition_id)
    if not e:
        return None
    return {
        "id": edition_id,
        "name": e.get("name"),
        "abbrev": e.get("abbrev"),
        "source": e.get("source"),
        "license": e.get("license"),
        "aligned": e.get("aligned"),
        "books": e.get("books"),
    }
