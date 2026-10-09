"""Verse structure, trees, clause context and syntax search, from MACULA's lowfat trees (trees_macula.py; CC BY 4.0).

Since NC exit step 6 this is the only structure source: the BHSA / Nestle1904 text-fabric engine is no longer part of the service
(its code is kept, dev-only, in corpus_engine/legacy_corpus.py for the offline build scripts).

  passage(book, ch, v)            -> verse words + morphology
  context(book, ch, v, word_idx)  -> clause/phrase/sentence hierarchy for one word
"""
from __future__ import annotations

import trees_macula


def configured() -> bool:
    return trees_macula.available()


def passage(book: str, chapter: int, verse: int) -> dict:
    return trees_macula.passage(book, chapter, verse)


def context(book: str, chapter: int, verse: int, word_index: int = 0) -> dict:
    return trees_macula.context(book, chapter, verse, word_index)


def context_batch(refs: list[tuple[str, int, int]], word_index: int = 0) -> dict:
    """Many context() lookups in one pass; `refs` = [(book, chapter, verse)]; returns {"BOOK/ch/v": <context() result>} (errors kept per ref, never raised)."""
    out: dict = {}
    for book, chapter, verse in refs:
        key = f"{book}/{chapter}/{verse}"
        try:
            out[key] = context(book, chapter, verse, word_index)
        except Exception as e:                       # keep one bad ref from sinking the batch
            out[key] = {"error": str(e)}
    return out


def syntax(book: str, chapter: int, verse: int) -> dict:
    return trees_macula.syntax(book, chapter, verse)


def tree(book: str, chapter: int, verse: int) -> dict:
    return trees_macula.tree(book, chapter, verse)


def syntax_search(function: str | None = None, strong: str | None = None, lex: str | None = None, book: str | None = None,
                  corpus: str | None = None, limit: int = 50, head_only: bool = False) -> dict:
    """Who-did-what search: clauses where a lexeme (`strong` or `lex`) fills a phrase `function`. The corpus is pinned by `book`, else inferred from the Strong's prefix."""
    return trees_macula.syntax_search(function=function, strong=strong, lex=lex, book=book, corpus=corpus, limit=limit, head_only=head_only)
