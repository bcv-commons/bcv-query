"""Shared helpers of the Hebrew levels builders (SPEC-levels.md, stage 42 on). Reads build i1 of the source examples.

Writers are deterministic: fixed parquet options, no pandas metadata, sorted rows; a rerun gives the same bytes.
"""
import csv
import hashlib
import json
import os
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
MAC = ROOT / "shoresh" / "macula"
DATA = MAC / "data"
I1 = DATA / "source-examples" / "i1"
LEVELS = DATA / "hebrew-levels"
DOCS = ROOT / "internal-docs" / "source-examples-work" / "levels"
CONTENT = ("noun", "verb", "adj", "adv")
FINALS = str.maketrans("ךםןףץ", "כמנפצ")
BANDS = (("1", 1, 1), ("2_4", 2, 4), ("5_19", 5, 19), ("20_99", 20, 99), ("100_499", 100, 499), ("500", 500, 10**12))

SOURCE_FILES = {
    "mz": "metzudat_zion_chapters.jsonl",
    "rd": "sefer_hashorashim_entries.jsonl",
    "mn": "mahberet_menahem_letters.jsonl",
    "mb": "malbim_beur_hamilot_chapters.jsonl",
}


def band(n):
    if not n:
        return "0"
    for code, lo, hi in BANDS:
        if lo <= n <= hi:
            return code
    raise ValueError(n)


def level_by_count(n):
    """W3's cut points (D-2): >= 100 -> 1; 20-99 -> 2; 5-19 -> 3; 1-4 -> 4; 0 -> None."""
    if n >= 100:
        return 1
    if n >= 20:
        return 2
    if n >= 5:
        return 3
    if n >= 1:
        return 4
    return None


def consonants(s):
    """NFD, marks dropped, maqaf -> space, every non-letter -> space, spaces collapsed (stage 40's form)."""
    s = unicodedata.normalize("NFD", s or "").replace("־", " ")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = "".join(ch if ("א" <= ch <= "ת" or ch == " ") else " " for ch in s)
    return " ".join(s.split())


def ckey(s):
    """The consonant key (SPEC-levels 4.1): letters only, final letters folded."""
    return consonants(s).translate(FINALS).replace(" ", "")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(None)
def table(part, name, columns=None):
    return pq.read_table(I1 / part / f"{name}.parquet", columns=list(columns) if columns else None).to_pydict()


@lru_cache(None)
def lexicon():
    with open(I1 / "lexicon" / "lexemes.tsv", encoding="utf-8") as fh:
        return {r["lexeme"]: r for r in csv.DictReader(fh, delimiter="\t")}


@lru_cache(None)
def part_lexemes(part):
    with open(I1 / part / "lexemes.tsv", encoding="utf-8") as fh:
        return {r["lexeme"]: r for r in csv.DictReader(fh, delimiter="\t")}


def is_content_lexeme(lx):
    r = lexicon().get(lx)
    return bool(r) and r["class"] in CONTENT and r["state"] not in ("name", "function")


def strict_count(lx):
    r = lexicon()[lx]
    return int(r["tanakh"] or 0) + int(r["heb_mod"] or 0) + int(r["heb_scg"] or 0)


def model_count(lx):
    r = lexicon()[lx]
    return strict_count(lx) + int(r["heb_mod_model"] or 0) + int(r["heb_scg_model"] or 0)


@lru_cache(None)
def stem_lexeme_by_word(part):
    """t -> lexeme of the word's first content stem piece, else its first stem piece (stage 40's rule)."""
    p = table(part, "pieces", ("t", "kind", "class", "lexeme"))
    first, cont = {}, {}
    for t, k, c, lx in zip(p["t"], p["kind"], p["class"], p["lexeme"]):
        if k != "stem" or not lx:
            continue
        first.setdefault(t, lx)
        if c in CONTENT:
            cont.setdefault(t, lx)
    return {t: cont.get(t, first[t]) for t in first}


@lru_cache(None)
def verse_words():
    """(book, chapter, verse) -> [(t, text, part)] over the Tanakh (hbo and arc)."""
    out = defaultdict(list)
    for p in ("hbo", "arc"):
        w = table(p, "words", ("t", "book", "chapter", "verse", "text"))
        for t, b, c, v, x in zip(w["t"], w["book"], w["chapter"], w["verse"], w["text"]):
            out[(b, c, v)].append((t, x, p))
    return out


@lru_cache(None)
def form_index():
    """consonant key of a written Tanakh word (each maqaf part) -> Counter(stem lexeme of the word)."""
    idx = defaultdict(Counter)
    for p in ("hbo", "arc"):
        w = table(p, "words", ("t", "text"))
        sl = stem_lexeme_by_word(p)
        for t, x in zip(w["t"], w["text"]):
            if t not in sl:
                continue
            for piece in consonants(x).split():
                idx[ckey(piece)][sl[t]] += 1
    return idx


@lru_cache(None)
def lemma_index():
    idx = defaultdict(set)
    for lx, r in lexicon().items():
        if int(r["tanakh"] or 0) > 0:
            idx[ckey(r["lemma"])].add(lx)
    return idx


PREFIXES = ("ו", "ה", "ב", "ל", "כ", "מ", "ש")


def resolve_y(tok):
    """A Y word (no place) -> (lexeme or '', rule). W1's Y resolution (FEASIBILITY.md 1.1)."""
    k = ckey(tok)
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
            lx, n = max(fi.items(), key=lambda kv: (kv[1], [-ord(ch) for ch in kv[0]]))
            if n >= 0.9 * sum(fi.values()):
                return lx, "form" if i == 0 else "form_prefix"
            return "", "ambiguous"
        lem = lemma_index().get(c, set())
        if len(lem) == 1:
            return next(iter(lem)), "lemma" if i == 0 else "lemma_prefix"
        if len(lem) > 1:
            return "", "ambiguous"
    return "", "none"


def resolve_x(tok, book, chapter, verse):
    """X at its verse -> (lexeme or '', x_state): exactly one stem lexeme among the verse's words with X's key."""
    k = ckey(tok)
    lexes = set()
    for t, x, p in verse_words().get((book, chapter, verse), []):
        if ckey(x) == k:
            lx = stem_lexeme_by_word(p).get(t, "")
            if lx:
                lexes.add(lx)
    if len(lexes) == 1:
        return next(iter(lexes)), "resolved"
    if len(lexes) > 1:
        return "", "ambiguous"
    return "", "not_found"


# ---------- writers ----------

def write_parquet(path, columns, schema):
    arrays = [pa.array(columns[f.name], type=f.type) for f in schema]
    t = pa.Table.from_arrays(arrays, schema=schema)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    pq.write_table(t, tmp, compression="zstd", compression_level=9, row_group_size=1 << 20)
    os.replace(tmp, path)


def write_tsv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            vals = ["" if v is None else ("true" if v is True else "false" if v is False else str(v)) for v in r]
            for v in vals:
                if "\t" in v or "\n" in v:
                    raise ValueError(f"tab or newline in a TSV value: {v!r}")
            fh.write("\t".join(vals) + "\n")
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
