"""Document model + adapter protocol shared by every source-format reader."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Document:
    """One indexable source unit. Built by an Adapter, consumed by build.py."""

    id: str                                       # stable, derived from source_path
    source_path: str                              # relative to the indexed root
    title: str
    chunks: list[str]                             # default: [whole body] — splitter is downstream
    metadata: dict = field(default_factory=dict)  # arbitrary JSON-serializable
    passage_refs: list[tuple[int, int]] = field(default_factory=list)  # (start, end) bbcccvvv pairs
    tags: list[str] = field(default_factory=list)
    source_sha: str = ""                          # populated by build.py


class Adapter(Protocol):
    """Parse one file into a Document, or None to skip."""

    def parse(self, path: Path, root: Path) -> Document | None: ...
