"""Build the embedding prefix (Location + Lexical lines) for a chunk.

Given a chunk's passage_refs (BBCCCVVV ranges), produces the language-neutral
prefix prepended to the chunk body before embedding:

    Genesis 1:1 | GEN 1:1
    H7225 first H1254 create H430 God H8064 heaven H776 land

- Lexical line: content-word Strong's + gloss, in reading order, **no dedup**
  (repetition preserved — see docs/embedding-enrichment.md).
- Broad ranges (> BROAD_RANGE_VERSES) get the Location line only, to avoid a
  runaway prefix that dilutes the body.
- UHB/UGNT and bcv-RAG chunks share standard (English-ish) versification, so
  attachment is a direct BBCCCVVV → spine lookup. (The 019 Hebrew↔English map
  is for the Layer-4 BHSA join, not here.)

The Structural line (Layer 4) is added later, once the bcv-corpus structural
endpoint exists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from references import BOOK_NAMES, decode, human
from spine.common import FILENUM, lang_of, to_modern_form

# Lexical-line token styles (ablation arms):
#   code_gloss   "H7225 first"        Strong's code + English gloss (default)
#   gloss        "first"              English gloss only
#   lemma        "ראשית"             original-language lemma, modern form (arm A)
#   lemma_gloss  "ראשית first"       original lemma + English handle (hybrid)
STYLES = ("code_gloss", "gloss", "lemma", "lemma_gloss")

HERE = Path(__file__).resolve().parent
SPINE_DB = HERE / "spine.db"
GLOSS_TSV = HERE / "spine_glosses.tsv"
BROAD_RANGE_VERSES = 5


def _load_gloss(path: Path) -> dict[str, str]:
    g = {}
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 2:
            g[p[0]] = p[1]
    return g


def _paratext(start: int, end: int) -> str:
    sc, sch, sv = decode(start)
    if end == start:
        return f"{sc} {sch}:{sv}"
    ec, ech, ev = decode(end)
    if sc != ec:
        return f"{sc} {sch}:{sv} – {ec} {ech}:{ev}"
    if sch == ech:
        return f"{sc} {sch}:{sv}-{ev}"
    return f"{sc} {sch}:{sv}-{ech}:{ev}"


class PrefixBuilder:
    def __init__(self, spine_db: Path = SPINE_DB, gloss_tsv: Path = GLOSS_TSV):
        self.db = sqlite3.connect(f"file:{spine_db}?mode=ro", uri=True)
        self.gloss = _load_gloss(Path(gloss_tsv))

    def _verses_in(self, start: int, end: int) -> list[tuple[str, int, int]]:
        """Expand a BBCCCVVV range to (code, ch, v). Cross-book ranges return []
        (they hit the broad-range cap; only the count/Location matter there)."""
        sc, sch, sv = decode(start)
        ec, ech, ev = decode(end)
        if sc != ec:
            return []  # broad cross-book range
        rows = self.db.execute(
            "SELECT DISTINCT chapter, verse FROM spine_words "
            "WHERE book=? AND (chapter*1000+verse) BETWEEN ? AND ? "
            "ORDER BY chapter, verse",
            (sc, sch * 1000 + sv, ech * 1000 + ev),
        ).fetchall()
        return [(sc, ch, v) for ch, v in rows]

    def _lexical_tokens(self, code: str, ch: int, v: int, style: str) -> list[str]:
        letter = "H" if FILENUM.get(code, 99) <= 39 else "G"
        lang = lang_of(code)
        toks = []
        for strong, lemma in self.db.execute(
            "SELECT strong, lemma FROM spine_words "
            "WHERE book=? AND chapter=? AND verse=? AND is_content=1 "
            "ORDER BY idx",
            (code, ch, v),
        ):
            gloss = self.gloss.get(f"{letter}{strong}") if strong else None
            mlemma = to_modern_form(lemma, lang) if lemma else ""
            if style == "code_gloss":
                if strong and gloss:
                    toks.append(f"{letter}{strong} {gloss}")
            elif style == "gloss":
                if gloss:
                    toks.append(gloss)
            elif style == "lemma":
                if mlemma:
                    toks.append(mlemma)
            elif style == "lemma_gloss":
                if mlemma and gloss:
                    toks.append(f"{mlemma} {gloss}")
                elif mlemma:
                    toks.append(mlemma)
        return toks

    def build(self, passage_refs: list[tuple[int, int]], *, style: str = "code_gloss") -> str:
        """Return the prefix string for a chunk's passage_refs, or '' if none."""
        if not passage_refs:
            return ""
        lo = min(s for s, _ in passage_refs)
        hi = max(e for _, e in passage_refs)
        location = f"{human(lo, hi)} | {_paratext(lo, hi)}"

        verses: list[tuple[str, int, int]] = []
        broad = False
        for s, e in passage_refs:
            vs = self._verses_in(s, e)
            if not vs and decode(s)[0] != decode(e)[0]:
                broad = True
            verses.extend(vs)

        if broad or len(verses) > BROAD_RANGE_VERSES or not verses:
            return location  # Location-only for broad ranges / passage-less

        lex: list[str] = []
        for code, ch, v in verses:
            lex.extend(self._lexical_tokens(code, ch, v, style))
        return location + ("\n" + " ".join(lex) if lex else "")
