"""Local corpus engine access (BHSA Hebrew + Nestle1904 Greek).

The Context-Fabric engine now runs **in-process** in shoresh (relocated from
bcv-RAG — see corpus_engine/). It reads the precompiled text-fabric corpus from a
mounted volume at $HOME/text-fabric-data (provisioned at /opt/corpus-data on the
host; see Dockerfile + compose). No network hop. Two views:

  passage(book, ch, v)            -> verse words + morphology
  context(book, ch, v, word_idx)  -> clause/phrase/sentence hierarchy for one word

Book mapping: the engine returns its own book names per corpus ("hebrew" = BHSA,
"greek" = Nestle1904); each name is mapped to its USFM code BY NAME (Hebrew via the
explicit table below — BHSA follows the Hebrew-canon order, so a positional zip against
Christian versification would misalign everything after Ruth; Greek names are USFM already).
"""
from __future__ import annotations

from functools import lru_cache


def _eng():
    # Lazy: import cfabric (and load the corpus) only when actually used, so the
    # service still boots if the corpus volume is absent.
    from corpus_engine import engine
    return engine


# BHSA (Hebrew) book name -> USFM code. BHSA follows the HEBREW canon order (Ruth,
# Chronicles, etc. sit in the Writings), which differs from the Christian versification —
# so this is an explicit name map, NOT a positional zip (that misaligns after Ruth). Greek
# (Nestle1904) book names are already USFM codes, so they map to themselves.
_HEBREW_NAME_TO_USFM = {
    "Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM",
    "Deuteronomy": "DEU", "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT",
    "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI", "2_Kings": "2KI",
    "1_Chronicles": "1CH", "2_Chronicles": "2CH", "Ezra": "EZR",
    "Nehemiah": "NEH", "Esther": "EST", "Job": "JOB", "Psalms": "PSA",
    "Proverbs": "PRO", "Ecclesiastes": "ECC", "Song_of_songs": "SNG",
    "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM",
    "Ezekiel": "EZK", "Daniel": "DAN", "Hosea": "HOS", "Joel": "JOL",
    "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON", "Micah": "MIC",
    "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG",
    "Zechariah": "ZEC", "Malachi": "MAL",
}


@lru_cache(maxsize=1)
def _book_map() -> dict[str, tuple[str, str]]:
    """USFM code -> (corpus_book_name, corpus_id). Order-independent: each corpus book name
    maps to its USFM by name (Hebrew via _HEBREW_NAME_TO_USFM; Greek names are already USFM)."""
    mapping: dict[str, tuple[str, str]] = {}
    eng = _eng()
    for corpus_id in ("hebrew", "greek"):
        for b in eng.list_books(corpus_id):
            usfm = _HEBREW_NAME_TO_USFM.get(b.name, b.name) if corpus_id == "hebrew" else b.name
            mapping[usfm.upper()] = (b.name, corpus_id)
    return mapping


def configured() -> bool:
    """The engine is in-process now — always 'configured'. Missing corpus DATA
    surfaces as an error from passage()/context() rather than a 503."""
    return True


def _resolve(book: str) -> tuple[str, str] | None:
    return _book_map().get(book.upper())


@lru_cache(maxsize=2)
def name_to_usfm(corpus_id: str) -> dict[str, str]:
    """{corpus book name -> USFM code} for one corpus ('hebrew' | 'greek') — the inverse of
    `_book_map`, so build scripts read the mapping from here instead of re-hardcoding it."""
    return {name: usfm for usfm, (name, cid) in _book_map().items() if cid == corpus_id}


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


def syntax(book: str, chapter: int, verse: int) -> dict:
    """Whole-verse clause→phrase syntax tree (in-process engine)."""
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    result = _eng().get_verse_syntax(name, chapter, verse, corpus_id)
    return {"corpus": corpus_id, "corpus_book": name, "data": result}


def tree(book: str, chapter: int, verse: int) -> dict:
    """Full sentence→clause→phrase→word syntactic tree of a verse (in-process engine)."""
    resolved = _resolve(book)
    if not resolved:
        return {"error": f"no corpus mapping for book '{book}'"}
    name, corpus_id = resolved
    result = _eng().get_verse_tree(name, chapter, verse, corpus_id)
    return {"corpus": corpus_id, "corpus_book": name, "data": result}


def syntax_search(function: str | None = None, strong: str | None = None,
                  lex: str | None = None, book: str | None = None,
                  corpus: str | None = None, limit: int = 50) -> dict:
    """Who-did-what search: clauses where a lexeme (`strong` or `lex`) fills a phrase
    `function`. The corpus is pinned by `book` if given, else inferred from the Strong's
    prefix (H→hebrew, G→greek), else `corpus` (default hebrew)."""
    corpus_book = None
    if book:
        resolved = _resolve(book)
        if not resolved:
            return {"error": f"no corpus mapping for book '{book}'"}
        corpus_book, corpus = resolved
    elif corpus is None:
        if strong and strong.strip().upper().startswith("G"):
            corpus = "greek"
        else:
            corpus = "hebrew"
    result = _eng().syntax_search(function=function, lex=lex, strong=strong,
                                  corpus=corpus, book=corpus_book, limit=limit)
    return {"corpus": corpus, "corpus_book": corpus_book, "data": result}
