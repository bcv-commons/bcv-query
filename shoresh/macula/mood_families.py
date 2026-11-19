"""Mood families named by the Bible's own feeling words, and which Hebrew and Greek words mark them.

    from macula import mood_families as mf
    mf.FAMILIES                    # id -> {"head_hbo", "head_grc", "side", "note", ...}   (resources/passage_facts/mood_families.tsv)
    mf.word_marks(book)            # word index in pf.Book(book) -> [(family id, why)]
    mf.source_family(label)        # a source's mood word (Scriptura, or a Glyssen delivery mapped by the builder) -> family id or None

A family is defined in the original languages only: its SDBH domains (Hebrew, UBS, the meaning a word has in its place) less
some lemmas, plus lemmas by Strong's number; its Louw-Nida subdomains (Greek, UBS) less some lemmas, plus lemma overrides; and (Hebrew, from v0.3.3) the words Metzudat Zion explains with one of the family's
commentary terms (ענין כעס, ענין שמחה …: mood_families.tsv commentary_terms). Function words (pronouns,
articles, prepositions, conjunctions, particles, numerals) never mark a family. A
negator up to three words before a word drops it ("he refused to be comforted"). The id is the transliterated Hebrew head word
(md.samach = שָׂמַח); English stands only in the note, as documentation. The source words map a source's English mood words to a
family for comparison and lookup; they are never published as values.
"""
from __future__ import annotations

import collections
import functools
import sqlite3
from pathlib import Path

from macula import build_passage_facts as pf, ubs

TABLE = Path(__file__).resolve().parents[2] / "resources" / "passage_facts" / "mood_families.tsv"
NEGATORS = {"3808", "0408", "0369", "1077", "3756", "3361", "3762", "3367"}   # לֹא אַל אַיִן בַּל, οὐ μή οὐδείς μηδείς


def _split(x: str) -> list[str]:
    return [y for y in x.split("|") if y]


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    lines = TABLE.read_text(encoding="utf-8").splitlines()
    head = lines[0].split("\t")
    out = {}
    for line in lines[1:]:
        r = dict(zip(head, line.split("\t")))
        out[r["id"]] = r
    return out


FAMILIES = _load()
COMMENTARY_TERM: dict[str, str] = {}      # a commentator's sense term (Hebrew, as written) -> family; filled by _maps()


@functools.lru_cache(maxsize=1)
def commentary_marks() -> dict[str, list[tuple[str, str]]]:
    """MACULA part key -> [(family, "mz:<term>")]: the words Metzudat Zion explains with a family's feeling term (sense,
    expression, from_word or gloss; anchored by rule only), from macula/build_commentary_terms.py over the cached text."""
    from macula import build_commentary_terms as ct
    _maps()
    rows, _ = ct.metzudat_zion()
    sp = sqlite3.connect(pf.SPINE)
    out: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for r in rows:
        f = COMMENTARY_TERM.get(r["term"])
        if not f or r["anchor"] != "rule":
            continue
        for (k,) in sp.execute("SELECT key FROM macula_words WHERE key BETWEEN ? AND ?", (r["subject_first"], r["subject_last"])):
            if (f, "mz:" + r["term"]) not in out[k]:
                out[k].append((f, "mz:" + r["term"]))
    return out


@functools.lru_cache(maxsize=1)
def _maps():
    sdbh, minus, strong, ln, gminus, glemma, words = {}, collections.defaultdict(set), {}, {}, collections.defaultdict(set), {}, {}
    cterm = COMMENTARY_TERM
    for fid, r in FAMILIES.items():
        for d in _split(r["sdbh"]):
            sdbh[d] = fid
        for s in _split(r["sdbh_minus"]):
            minus[fid].add(s)
        for s in _split(r["hbo_strong"]):
            strong[s] = fid
        for c in _split(r["ln"]):
            ln[c] = fid
        for l in _split(r["grc_minus"]):
            gminus[fid].add(l)
        for x in _split(r["grc_lemma"]):
            l, f = x.split(":")
            glemma[l] = f
        for t in _split(r.get("commentary_terms", "")):
            cterm[t] = fid
        for w in _split(r["source_words"]):
            words[w.replace("-", "_").replace(" ", "_")] = fid
    return sdbh, minus, strong, ln, gminus, glemma, words


def source_family(label: str) -> str | None:
    return _maps()[6].get(label.replace("-", "_").replace(" ", "_"))


CUE_FAMILY = {"rg.woe": "md.bakah", "rg.lament_named": "md.bakah", "rg.lament_open": "md.bakah", "rg.blessing": "md.samach",
              "rg.hallelujah": "md.samach"}


def word_marks(book: str, bk=None, cues: dict[int, str] | None = None) -> dict[int, list[tuple[str, str]]]:
    """Word index (pf.Book order) -> [(family, why)]; why is "sdbh:<domain>", "strong:<number>", "ln:<code>", "lemma:<lemma>" or a
    cue code (`cues`: word index -> rg.* code; woe and lament mark md.bakah, blessing and hallelujah md.samach)."""
    sdbh, minus, strong_fam, ln, gminus, glemma, _ = _maps()
    bk = bk or pf.Book(book)
    keys, pos = bk.keys, bk.pos
    sp = sqlite3.connect(pf.SPINE)
    rows = {k: (s, l) for k, s, l in sp.execute("SELECT key, strong, lemma FROM macula_words WHERE book=?", (book,))}
    function = {k for (k,) in sp.execute("SELECT key FROM macula_words WHERE book=? AND class IN ('pron', 'prep', 'cj', 'conj', "
                                         "'art', 'det', 'rel', 'om', 'num', 'ptcl')", (book,))}
    negated = {i for i in range(len(keys)) if any((rows.get(keys[j]) or ("", ""))[0] in NEGATORS for j in range(max(0, i - 3), i))}
    out: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
    if bk.hebrew:
        doms = ubs.hebrew(book)
        for i, k in enumerate(keys):
            if i in negated or k in function:
                continue
            s = (rows.get(k) or ("", ""))[0] or ""
            if s in strong_fam:
                out[i].append((strong_fam[s], f"strong:{s}"))
                continue
            for d in (doms.get(k) or "").split("|"):
                f = sdbh.get(d.strip())
                if f and s not in minus[f]:
                    out[i].append((f, f"sdbh:{d.strip()}"))
                    break
    else:
        g = ubs.greek()
        for i, k in enumerate(keys):
            if i in negated or k in function:
                continue
            lemma = (rows.get(k) or ("", ""))[1] or ""
            if lemma in glemma:
                out[i].append((glemma[lemma], f"lemma:{lemma}"))
                continue
            code = (g.get(k) or ("", ""))[1]
            f = ln.get(code)
            if f and lemma not in gminus[f]:
                out[i].append((f, f"ln:{code}"))
    if bk.hebrew:
        cm = commentary_marks()
        for i, k in enumerate(keys):
            if i in negated or k in function or k not in cm:
                continue
            for f, why in cm[k]:
                if all(f != g for g, _ in out.get(i, [])):
                    out[i].append((f, why))
    for i, c in (cues or {}).items():
        if c in CUE_FAMILY and i not in negated:
            out[i].append((CUE_FAMILY[c], c))
    return out


def head(fid: str, hebrew: bool) -> str:
    return FAMILIES[fid]["head_hbo" if hebrew else "head_grc"]


def heads() -> dict[str, tuple[str, str]]:
    """The head word each family would get by rule: the most frequent lemma among the words it marks, Hebrew and Greek."""
    sp = sqlite3.connect(pf.SPINE)
    books = [b for (b,) in sp.execute("SELECT DISTINCT book FROM macula_words")]
    cnt = {"h": collections.defaultdict(collections.Counter), "g": collections.defaultdict(collections.Counter)}
    for b in books:
        bk = pf.Book(b)
        lem = dict(sp.execute("SELECT key, lemma FROM macula_words WHERE book=?", (b,)))
        for i, ms in word_marks(b).items():
            for f, _ in ms:
                cnt["h" if bk.hebrew else "g"][f][lem.get(bk.keys[i])] += 1
    return {f: (cnt["h"][f].most_common(1)[0][0] if cnt["h"][f] else "", cnt["g"][f].most_common(1)[0][0] if cnt["g"][f] else "")
            for f in FAMILIES}


if __name__ == "__main__":
    for f, (h, g) in heads().items():
        print(f, FAMILIES[f]["head_hbo"], FAMILIES[f]["head_grc"], "| by rule:", h, g)
