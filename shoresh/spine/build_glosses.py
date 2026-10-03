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


# Reviewed exceptions where MACULA's token glosses are too thin or blank to choose the right TBESH entry
# (H905's common "alone" sense has 121 tokens with empty glosses, so the rarer "pole" would win).
OVERRIDES = {"H905": "alone", "H2764": "devoted thing", "H6049": "practice soothsaying"}


def macula_usage() -> dict[str, "collections.Counter"]:
    """H#### (unpadded) -> Counter of frozenset(stemmed content words) per MACULA token gloss, weighted by
    token count. Scoring is per token (a token matches once, however many of its words match), so a
    two-word gloss like "the holy place" is not counted twice."""
    import collections
    import sqlite3
    out: dict = collections.defaultdict(collections.Counter)
    if not MACULA.exists():
        return out
    db = sqlite3.connect(f"file:{MACULA}?mode=ro", uri=True)
    for strong, gloss, n in db.execute(
            "SELECT strong, gloss, COUNT(*) FROM spine_words WHERE lexeme LIKE 'hbo:%' AND strong IS NOT NULL "
            "AND gloss IS NOT NULL GROUP BY strong, gloss"):
        ws = frozenset(_words(gloss.replace(".", " ")))
        if ws:
            out[f"H{int(strong)}"][ws] += n
    return out


def _namelike(c) -> bool:
    return c[3].startswith("N:") or c[0][:1].isupper()


def _specific(raw: str) -> str:
    """The rendering after the colon in a TBESH gloss ("to boast: praise" -> "praise"), or ""."""
    if ":" not in raw:
        return ""
    spec = raw.split(":", 1)[1].split("/", 1)[0]
    return re.sub(r"^\([^)]*\)\s*", "", spec).strip().strip("-").strip()


def pick(cands: list[tuple], usage) -> tuple[str, str]:
    """cands: [(gloss, definition, translit, grammar, raw_gloss)] in TBESH order -> (gloss, translit).

    Each MACULA token counts once: 2 if its words meet the entry's gloss words (headword plus the
    rendering after the colon), else 1 if they meet the start of the entry's definition (common-word
    entries only; a name's etymology, "Lebo: means to go in", must not outscore the verb). Ties go to
    common-word entries. The first entry is replaced only when another scores higher with support from at
    least 20% (and 5) of the word's glossed tokens. When the chosen entry's headword itself has under 20%
    support but its specific rendering has at least 20% ("to boast: praise" for halal, glossed "praise"
    64 times), the rendering is used as the gloss."""
    first = cands[0]
    if not usage:
        return first[0], first[2]
    total = sum(usage.values())

    def wsets(c):
        g = set(_words(c[0])) | set(_words(_specific(c[4])))
        d = set() if _namelike(c) else set(_words(" ".join(c[1].split()[:12]))) - g
        return g, d

    def score(c):
        g, d = wsets(c)
        return sum(n * (2 if ws & g else 1 if ws & d else 0) for ws, n in usage.items())

    def support(words):
        return sum(n for ws, n in usage.items() if ws & words)

    order = {id(c): i for i, c in enumerate(cands)}
    best = max(cands, key=lambda c: (score(c), not _namelike(c), -order[id(c)]))
    g, d = wsets(best)
    better = score(best) > score(first) or (score(best) == score(first) and _namelike(first)
                                             and not _namelike(best))
    chosen = best if (best is not first and better and support(g | d) >= max(5, 0.2 * total)) else first
    spec = _specific(chosen[4])
    if spec and support(set(_words(chosen[0]))) < 0.2 * total <= support(set(_words(spec))):
        return spec, chosen[2]
    return chosen[0], chosen[2]


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
                                                     c[5] if len(c) > 5 else "", c[6]))
        for strong, cs in cands.items():
            if prefix == "H" and strong in OVERRIDES:
                gloss, xlit = OVERRIDES[strong], cs[0][2]
            elif prefix == "H":
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
