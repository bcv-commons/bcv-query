"""Correct resources/word_freq/hbo_strong.tsv (BHSA lex -> Strong's) by aligning BHSA words to MACULA tokens.

The table came from corpus_engine/build_lex_strong.py, whose first rule matched a BHSA lexeme to a Strong's
number by identical pointed lemma. Homographs share a pointed lemma, so that rule could pick the wrong word:
R<H/ "evil" (H7451) was mapped to H7462 "shepherd", >L/ "God" to H0413 "towards", >TM "you" to Etham.
The BHSA-MACULA bridge cannot catch this: most of its links were made by matching these same Strong's
numbers.

Here every BHSA word is aligned to MACULA's tokens in its verse by consonants alone (both split prefixes
alike; difflib on the token sequences), and each BHSA lexeme takes the Strong's number most of its
aligned MACULA tokens carry, voted per language (BHSA reuses some lex ids for Hebrew and Aramaic words:
>LH/ is Hebrew "oak", Aramaic "god"). A vote replaces or adds a row when it has at least MIN_VOTES tokens
and MIN_SHARE agreement, Hebrew first; other rows are kept as they were.

  python -m macula.build_lex_strong_macula            # rewrites resources/word_freq/hbo_strong.tsv
"""
from __future__ import annotations

import collections
import difflib
import os
import sqlite3
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TABLE = ROOT / "resources" / "word_freq" / "hbo_strong.tsv"
SPINE = HERE / "lexeme-spine-macula.db"
BHSA = os.path.expanduser("~/text-fabric-data/github/ETCBC/bhsa/tf/2021")
MIN_VOTES, MIN_SHARE = 2, 0.6
BOOKS = {"Genesis": "GEN", "Exodus": "EXO", "Leviticus": "LEV", "Numbers": "NUM", "Deuteronomy": "DEU",
         "Joshua": "JOS", "Judges": "JDG", "Ruth": "RUT", "1_Samuel": "1SA", "2_Samuel": "2SA", "1_Kings": "1KI",
         "2_Kings": "2KI", "1_Chronicles": "1CH", "2_Chronicles": "2CH", "Ezra": "EZR", "Nehemiah": "NEH",
         "Esther": "EST", "Job": "JOB", "Psalms": "PSA", "Proverbs": "PRO", "Ecclesiastes": "ECC",
         "Song_of_songs": "SNG", "Isaiah": "ISA", "Jeremiah": "JER", "Lamentations": "LAM", "Ezekiel": "EZK",
         "Daniel": "DAN", "Hosea": "HOS", "Joel": "JOL", "Amos": "AMO", "Obadiah": "OBA", "Jonah": "JON",
         "Micah": "MIC", "Nahum": "NAM", "Habakkuk": "HAB", "Zephaniah": "ZEP", "Haggai": "HAG",
         "Zechariah": "ZEC", "Malachi": "MAL"}


def _cons(s: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if "א" <= c <= "ת")


def votes() -> dict:
    import cfabric
    api = cfabric.Fabric(locations=BHSA, silent="deep").loadAll(silent="deep")
    F, L, T = api.F, api.L, api.T
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    mac = collections.defaultdict(list)
    for b, c, v, surf, s in sp.execute("SELECT book, chapter, verse, surface, strong FROM spine_words "
                                       "WHERE lexeme LIKE 'hbo:%' ORDER BY book, chapter, verse, idx"):
        mac[(b, c, v)].append((_cons(surf), f"H{int(s):04d}" if s is not None else ""))
    out: dict = collections.defaultdict(collections.Counter)
    for vnode in F.otype.s("verse"):
        bk, ch, vs = T.sectionFromNode(vnode)
        mw = mac.get((BOOKS.get(bk), ch, vs))
        if not mw:
            continue
        ws = L.d(vnode, otype="word")
        bw = [_cons(F.g_cons_utf8.v(w) or F.g_word_utf8.v(w)) for w in ws]
        sm = difflib.SequenceMatcher(None, bw, [x[0] for x in mw], autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for i in range(size):
                if mw[b + i][1] and bw[a + i]:
                    out[(F.lex.v(ws[a + i]), F.language.v(ws[a + i]))][mw[b + i][1]] += 1
    return out


def main() -> int:
    v = votes()
    header, *lines = TABLE.read_text(encoding="utf-8").splitlines()
    table = dict(l.split("\t") for l in lines if "\t" in l)
    order = [l.split("\t")[0] for l in lines if "\t" in l]
    st = collections.Counter()
    for lex in sorted({lx for (lx, _l) in v}):
        pick = None
        for lang in ("Hebrew", "Aramaic"):
            c = v.get((lex, lang))
            if c:
                top, n = c.most_common(1)[0]
                if n >= MIN_VOTES and n / sum(c.values()) >= MIN_SHARE:
                    pick = top
                    break
        if not pick:
            continue
        if lex not in table:
            table[lex] = pick
            order.append(lex)
            st["added"] += 1
        elif table[lex] != pick:
            table[lex] = pick
            st["corrected"] += 1
        else:
            st["confirmed"] += 1
    TABLE.write_text(header + "\n" + "".join(f"{lx}\t{table[lx]}\n" for lx in order), encoding="utf-8")
    print(f"[lex-strong] {dict(st)}; rows {len(order)} -> {TABLE}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
