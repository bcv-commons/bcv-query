#!/usr/bin/env python3
"""Build the Strong's -> concise English gloss table for the Lexical prefix line.

Source: STEPBible Translators Brief lexicons (TBESH Hebrew, TBESG Greek),
CC BY — they carry a clean, primary-sense gloss per Strong's (unlike the
1890 Strong's defs, which lead with etymology/qualifiers). Output:
spine/spine_glosses.tsv  (strong, gloss, translit) — spine-scoped English
glosses of the original languages; distinct from bcv-RAG's multilingual
resources/strongs_gloss.tsv.

Choosing among a number's entries: TBESH lists several extended-Strong's entries per number (H0899A
"treachery", H0899B "garment"). Hebrew picks the entry whose gloss and short definition best match how
the word is actually glossed across its occurrences in MACULA (macula/lexeme-spine.db, CC BY): H5483's
137 tokens are glossed "horses", so "horse", not the first-listed "swallow". With no overlap (or no
MACULA db), the first entry is kept, as before. Greek keeps the first entry.

Usage:  python -m spine.build_glosses [--tbesh LOCAL_FILE]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
OUT = HERE / "spine_glosses.tsv"
BASE = "https://raw.githubusercontent.com/STEPBible/STEPBible-Data/master/Lexicons/"
SRC = {
    "H": BASE + "TBESH%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Hebrew%20-%20STEPBible.org%20CC%20BY.txt",
    "G": BASE + "TBESG%20-%20Translators%20Brief%20lexicon%20of%20Extended%20Strongs%20for%20Greek%20-%20STEPBible.org%20CC%20BY.txt",
}
_LEAD = re.compile(r"^(to be|to|a|an|the)\s+", re.I)


def clean_gloss(g: str) -> str:
    """'to go: went' -> 'go'; 'spirit/breath: spirit' -> 'spirit'; 'God' -> 'God'."""
    g = g.split(":", 1)[0]                 # headword sense, drop the specific rendering
    g = g.split("/", 1)[0]                 # first of alternatives
    g = re.sub(r"^\([^)]*\)\s*", "", g)    # leading (qualifier)
    g = _LEAD.sub("", g).strip().strip("-").strip()
    return g


MACULA = HERE.parent / "macula" / "lexeme-spine.db"
_STOP = frozenset("the a an of to in on at for by with and or his her their your my our its he she they we "
                  "you i it is be was were will shall not from as that this these those".split())


def _stem(w: str) -> str:
    w = w.lower()
    for suf in ("ies", "ing", "es", "s", "ed"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            w = w[: -len(suf)] + ("y" if suf == "ies" else "")
            break
    return w[:-1] if len(w) > 3 and w.endswith("e") else w      # struggle / struggled -> struggl


def _words(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>|\([^)]*\)", " ", text)
    return [_stem(w) for w in re.findall(r"[A-Za-z]{2,}", text) if w.lower() not in _STOP]


def macula_usage() -> dict[str, "collections.Counter"]:
    """H#### (unpadded) -> Counter of stemmed content words in MACULA's per-token English glosses."""
    import collections
    import sqlite3
    out: dict = collections.defaultdict(collections.Counter)
    if not MACULA.exists():
        return out
    db = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    for strong, gloss, n in db.execute(
            "SELECT strong, gloss, COUNT(*) FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL "
            "AND gloss IS NOT NULL GROUP BY strong, gloss"):
        for w in _words(gloss.replace(".", " ")):
            out[f"H{int(strong)}"][w] += n
    return out


def _namelike(c) -> bool:
    return c[3].startswith("N:") or c[0][:1].isupper()


def pick(cands: list[tuple[str, str, str, str]], usage) -> tuple[str, str]:
    """cands: [(gloss, definition, translit, grammar)] in TBESH order -> (gloss, translit).
    Each entry is scored by how many of the word's glossed tokens its own gloss matches (x2) plus, for
    common-word entries, its short definition; name-like entries (grammar "N:" or a capitalized gloss)
    are scored on their gloss only, so a name's etymology ("Lebo: means to go in") can't outscore the
    common verb. Ties go to common-word entries. The first entry is replaced only when another matches
    clearly better: score above the first's and support of at least 20% (and 5) of the glossed tokens.
    Weak evidence keeps the first entry (חֶסֶד: 2 tokens "shame" vs ~300 "loyalty", which no entry matches)."""
    first = cands[0]
    if not usage:
        return first[0], first[2]
    total = sum(usage.values())

    def words(c):
        g = set(_words(c[0]))
        d = set() if _namelike(c) else set(_words(" ".join(c[1].split()[:12]))) - g
        return g, d

    def score(c):
        g, d = words(c)
        return 2 * sum(usage[w] for w in g) + sum(usage[w] for w in d)

    order = {id(c): i for i, c in enumerate(cands)}
    best = max(cands, key=lambda c: (score(c), not _namelike(c), -order[id(c)]))
    g, d = words(best)
    support = sum(usage[w] for w in g | d)
    if best is not first and score(best) > score(first) and support >= max(5, 0.2 * total):
        return best[0], best[2]
    return first[0], first[2]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tbesh", default="", help="local copy of the TBESH file (skip the download)")
    args = ap.parse_args()
    usage = macula_usage()
    rows = []
    changed = 0
    for prefix in ("H", "G"):
        if prefix == "H" and args.tbesh:
            t = Path(args.tbesh).read_text(encoding="utf-8")
        else:
            t = httpx.get(SRC[prefix], timeout=180, follow_redirects=True).text
        cands: dict[str, list] = {}
        for line in t.splitlines():
            if not re.match(r"^[HG]\d", line):     # data lines only (skip preamble)
                continue
            c = line.split("\t")
            if len(c) < 7:
                continue
            m = re.match(r"([HG])0*(\d+)", c[0])
            if not m:
                continue
            strong = f"{m.group(1)}{int(m.group(2))}"   # H430, G2316 (unpadded)
            gloss = clean_gloss(c[6])
            if gloss:
                cands.setdefault(strong, []).append((gloss, c[7] if len(c) > 7 else "", c[4] if len(c) > 4 else "",
                                                     c[5] if len(c) > 5 else ""))
        for strong, cs in cands.items():
            if prefix == "H":
                gloss, xlit = pick(cs, usage.get(strong))
                changed += gloss != cs[0][0]
            else:
                gloss, xlit = cs[0][0], cs[0][2]
            rows.append((strong, gloss, xlit))
        print(f"  {prefix}: {sum(1 for r in rows if r[0][0]==prefix)} glosses", file=sys.stderr)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("strong\tgloss\ttranslit\n")
        for strong, gloss, xlit in rows:
            f.write(f"{strong}\t{gloss}\t{xlit}\n")
    print(f"{len(rows)} glosses ({changed} Hebrew picks differ from the first-listed entry) -> {OUT}")


if __name__ == "__main__":
    main()
