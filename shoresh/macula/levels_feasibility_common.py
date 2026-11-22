"""Shared helpers for the levels feasibility counts (stage 40). Reads build i1 of the source examples; writes nothing.

Run the counting scripts from the repository root with shoresh/.venv/bin/python -I.
"""
import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
MAC = ROOT / "shoresh" / "macula"
DATA = MAC / "data"
BUILD = DATA / "source-examples" / "i1"
OUT = ROOT / "internal-docs" / "source-examples-work" / "levels"
SCRATCH = Path("/tmp/claude-1000/source-examples/levels40")   # the 8 MB statement list (rebuilt in 6 s)
PARTS = ("hbo", "arc", "heb_mod", "heb_scg")
CONTENT = {"noun", "verb", "adj", "adv"}
BANDS = ((1, 1), (2, 4), (5, 19), (20, 99), (100, 499), (500, 10**9))
FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def band(n):
    for lo, hi in BANDS:
        if lo <= n <= hi:
            return f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
    return "0"


BAND_NAMES = [band(lo) for lo, _ in BANDS]


def consonants(s, fold_finals=False):
    """Research's consonants-only form: NFD, marks dropped, maqaf -> space, non-letters -> space, collapsed."""
    s = unicodedata.normalize("NFD", s or "").replace("־", " ")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = "".join(ch if ("א" <= ch <= "ת" or ch == " ") else " " for ch in s)
    s = " ".join(s.split())
    return s.translate(FINALS) if fold_finals else s


def pointed(s):
    """Research's pointed-without-accents form."""
    keep = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}
    s = unicodedata.normalize("NFD", s or "").replace("־", " ")
    out = []
    for ch in s:
        o = ord(ch)
        if 0x05D0 <= o <= 0x05EA or ch == " " or o in keep:
            out.append(ch)
        elif unicodedata.combining(ch):
            continue
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def key(s):
    return consonants(s, fold_finals=True).replace(" ", "")


@lru_cache(None)
def table(part, name, columns=None):
    return pq.read_table(BUILD / part / f"{name}.parquet", columns=list(columns) if columns else None).to_pydict()


@lru_cache(None)
def lexicon():
    """lexeme key -> row of lexicon/lexemes.tsv"""
    with open(BUILD / "lexicon" / "lexemes.tsv", encoding="utf-8") as fh:
        return {r["lexeme"]: r for r in csv.DictReader(fh, delimiter="\t")}


@lru_cache(None)
def part_lexemes(part):
    with open(BUILD / part / "lexemes.tsv", encoding="utf-8") as fh:
        return {r["lexeme"]: r for r in csv.DictReader(fh, delimiter="\t")}


def is_content(lex, cls):
    st = lexicon().get(lex, {}).get("state", "")
    return cls in CONTENT and st not in ("name", "function")


@lru_cache(None)
def content_tokens(part):
    """list of (t, n, lexeme) for content stem pieces of a part (derived and model alike)."""
    p = table(part, "pieces", ("t", "n", "kind", "class", "lexeme"))
    return [(t, n, lx) for t, n, k, c, lx in zip(p["t"], p["n"], p["kind"], p["class"], p["lexeme"])
            if k == "stem" and lx and is_content(lx, c)]


@lru_cache(None)
def stem_lexeme_by_word(part):
    """t -> lexeme of the word's first content stem piece (else its first stem piece)."""
    p = table(part, "pieces", ("t", "n", "kind", "class", "lexeme"))
    first, cont = {}, {}
    for t, k, c, lx in zip(p["t"], p["kind"], p["class"], p["lexeme"]):
        if k != "stem" or not lx:
            continue
        first.setdefault(t, lx)
        if c in CONTENT:
            cont.setdefault(t, lx)
    return {t: cont.get(t, first[t]) for t in first}


@lru_cache(None)
def verse_words(part="tanakh"):
    """(book, chapter, verse) -> list of (t, text, part) over hbo and arc."""
    out = defaultdict(list)
    for p in ("hbo", "arc"):
        w = table(p, "words", ("t", "book", "chapter", "verse", "text"))
        for t, b, c, v, x in zip(w["t"], w["book"], w["chapter"], w["verse"], w["text"]):
            out[(b, c, v)].append((t, x, p))
    return out


@lru_cache(None)
def form_index():
    """consonant key of a written Tanakh word -> Counter(stem lexeme)."""
    idx = defaultdict(Counter)
    for p in ("hbo", "arc"):
        w = table(p, "words", ("t", "text"))
        sl = stem_lexeme_by_word(p)
        for t, x in zip(w["t"], w["text"]):
            for piece in consonants(x).split():
                if t in sl:
                    idx[key(piece)][sl[t]] += 1
    return idx


@lru_cache(None)
def lemma_index():
    """consonant key of a lexicon lemma -> set of lexeme keys (Tanakh lexemes only)."""
    idx = defaultdict(set)
    for lx, r in lexicon().items():
        if int(r["tanakh"] or 0) > 0:
            idx[key(r["lemma"])].add(lx)
    return idx


PREFIXES = ("ו", "ה", "ב", "ל", "כ", "מ", "ש")


def resolve_word(tok):
    """A free word (no place) -> (lexeme or '', how). Rule Y of FEASIBILITY.md section 1."""
    k = key(tok)
    if len(k) < 2:
        return "", "short"
    cands = [k]
    if k[0] in PREFIXES and len(k) > 2:
        cands.append(k[1:])
        if k[1] in PREFIXES and len(k) > 3:
            cands.append(k[2:])
    for i, c in enumerate(cands):
        fi = form_index().get(c)
        if fi:
            lx, n = fi.most_common(1)[0]
            if n >= 0.9 * sum(fi.values()):
                return lx, "form" if i == 0 else "form_prefix"
            return "", "ambiguous"
        lem = lemma_index().get(c, set())
        if len(lem) == 1:
            return next(iter(lem)), "lemma" if i == 0 else "lemma_prefix"
        if len(lem) > 1:
            return "", "ambiguous"
    return "", "none"


def resolve_at(tok, book, chapter, verse):
    """A headword at a place -> (lexeme or '', how, t). Rule X: equal consonants with a word of that verse."""
    k = key(tok)
    hits = {}
    for t, x, p in verse_words().get((book, chapter, verse), []):
        if key(x) == k:
            hits[t] = stem_lexeme_by_word(p).get(t, "")
    lexes = {v for v in hits.values() if v}
    if len(lexes) == 1:
        t = min(hits)
        return hits[t], "verse", t
    if len(lexes) > 1:
        return "", "verse_ambiguous", 0
    return "", "verse_none", 0


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
