"""Context-Fabric corpus engine (BHSA Hebrew + Nestle 1904 Greek).

Absorbed from the former bcv-corpus service. Provides morphological
annotations, syntactic structure, vocabulary, and lexeme data via a
local CFEngine instance — no network hop needed.

The engine is created lazily on first access to avoid import errors
when cfabric is not installed (e.g. local dev without corpus data).
"""
from __future__ import annotations

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from corpus_engine.cf_engine import CFEngine
        _engine = CFEngine()
    return _engine


def __getattr__(name: str):
    if name == "engine":
        return _get_engine()
    raise AttributeError(f"module 'corpus' has no attribute {name!r}")
