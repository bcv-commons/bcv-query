"""Local corpus engine access (BHSA Hebrew + Nestle1904 Greek).

The Context-Fabric engine now runs **in-process** in shoresh (relocated from
bcv-RAG — see corpus_engine/). It reads the precompiled text-fabric corpus from a
mounted volume at $HOME/text-fabric-data (provisioned at /opt/corpus-data on the
host; see Dockerfile + compose). No network hop. Two views:

  passage(book, ch, v)            -> verse words + morphology
  context(book, ch, v, word_idx)  -> clause/phrase/sentence hierarchy for one word

Book mapping: the engine returns its own book names per corpus ("hebrew" = BHSA,
"greek" = Nestle1904) in canonical order, zipped positionally against the USFM
codes in the same order.
"""
from __future__ import annotations

from functools import lru_cache

from references import BOOK_NUMBERS


def _eng():
    # Lazy: import cfabric (and load the corpus) only when actually used, so the
    # service still boots if the corpus volume is absent.
    from corpus_engine import engine
    return engine


@lru_cache(maxsize=1)
def _book_map() -> dict[str, tuple[str, str]]:
    """USFM code -> (corpus_book_name, corpus_id)."""
    mapping: dict[str, tuple[str, str]] = {}
    eng = _eng()
    for corpus_id, (lo, hi) in [("hebrew", (1, 40)), ("greek", (40, 100))]:
        names = [b.name for b in eng.list_books(corpus_id)]
        codes = sorted(
            [(u, n) for u, n in BOOK_NUMBERS.items() if lo <= n < hi],
            key=lambda x: x[1],
        )
        for (usfm, _num), name in zip(codes, names):
            mapping[usfm] = (name, corpus_id)
    return mapping


def configured() -> bool:
    """The engine is in-process now — always 'configured'. Missing corpus DATA
    surfaces as an error from passage()/context() rather than a 503."""
    return True


def _resolve(book: str) -> tuple[str, str] | None:
    return _book_map().get(book.upper())


def passage(book: str, chapter: int, verse: int) -> dict:
    """Verse words + morphology for one verse (in-process engine)."""
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    result = _eng().get_passage(name, chapter, verse, verse, corpus_id)
    return {"corpus": corpus_id, "corpus_book": name, "data": result.model_dump()}


def context(book: str, chapter: int, verse: int, word_index: int = 0) -> dict:
    """Clause/phrase/sentence hierarchy for one word (in-process engine)."""
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    result = _eng().get_context(name, chapter, verse, word_index, corpus_id)
    return {"corpus": corpus_id, "corpus_book": name, "data": result}  # get_context already returns a dict
