"""Markdown-with-YAML-frontmatter adapter (default).

Frontmatter conventions consumed:
    title:       used as document title (falls back to filename stem)
    tags:        list of strings, or single string
    passages:    list of pre-encoded [start_bbcccvvv, end_bbcccvvv] pairs
                 (natural-language reference parsing is intentionally NOT
                 done here yet — defer until the corpus reference style is
                 known)

Everything else in frontmatter is preserved into Document.metadata.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .base import Document

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end():]
    try:
        import yaml  # pyyaml — dependency declared in indexer/requirements.txt
    except ImportError as e:
        raise RuntimeError("pyyaml required: pip install -r indexer/requirements.txt") from e
    meta = yaml.safe_load(raw) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def _coerce_tags(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(t) for t in value if t]
    return []


def _coerce_passages(value) -> list[tuple[int, int]]:
    """Accept a list of [start, end] integer pairs; ignore anything else."""
    if not isinstance(value, list):
        return []
    out: list[tuple[int, int]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                s, e = int(item[0]), int(item[1])
                out.append((s, e) if s <= e else (e, s))
            except (TypeError, ValueError):
                continue
    return out


class MarkdownAdapter:
    def parse(self, path: Path, root: Path) -> Document | None:
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)

        title = meta.pop("title", None) or path.stem
        tags = _coerce_tags(meta.pop("tags", None))
        passages = _coerce_passages(meta.pop("passages", None))

        rel = path.relative_to(root).as_posix()
        doc_id = hashlib.sha256(rel.encode()).hexdigest()[:16]

        return Document(
            id=doc_id,
            source_path=rel,
            title=str(title),
            chunks=[body.strip()] if body.strip() else [],
            metadata=meta,
            passage_refs=passages,
            tags=tags,
        )
