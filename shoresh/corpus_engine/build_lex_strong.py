"""Bridge the TF corpus lexeme → Strong's number → resources/word_freq/{hbo,grc}_strong.tsv.

/words is built on the TF corpora (BHSA + Nestle1904) for their rich morphology and
clause structure, but the keyness ("how distinctively biblical") signal is keyed on
Strong's numbers. This builds the missing `lex → strong` bridge so /words can attach
keyness per word. Keyness is a LEXEME property, so one strong per lexeme suffices.

  Greek (Nestle1904): clean — the corpus ships a `strong` feature. Majority-vote
    strong per lemma (handles the rare disagreement).

  Hebrew/Aramaic (BHSA): no Strong's feature; the mapping lives in spine.db, which
    tokenizes differently (BHSA splits ב/ה/ל as separate words). A three-tier
    resolver, in priority order:
      1. exact pointed lexeme  == spine pointed lemma     (authoritative, unambiguous)
      2. occurrence vote: per verse, match BHSA word to spine word by consonantal
         surface containment; majority-vote lex→strong corpus-wide (disambiguates
         homographs using real occurrences — a consistent strong wins)
      3. consonantal lexeme maps to a SINGLE spine strong  (covers rare words)
    else: no mapping (rare hapax → keyness simply absent; graceful).
    Measured coverage: ~85% of content lexemes, ~96% frequency-weighted.

Output columns: lex, strong  (lex = BHSA `lex` / Nestle1904 `lemma`, the same key
as word_freq/{hbo,grc}.tsv). Build-time only; the server reads the committed TSV.

Run where the TF corpus + spine.db are available (dev box or host):
  python -m corpus_engine.build_lex_strong
"""
from __future__ import annotations

import collections
import os
import sqlite3
import unicodedata
from pathlib import Path

from corpus_engine import engine
from corpus_engine.cf_engine import WORD_FEATURES, WORD_TYPE

SPINE_DB = Path(__file__).resolve().parents[1] / "spine" / "spine.db"
CONTENT_SP = {"subs", "nmpr", "verb", "adjv", "advb"}  # BHSA content parts-of-speech


def _resources_dir() -> Path:
    env = os.environ.get("BCV_RESOURCES_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "resources"


def _strip(s: str | None) -> str:
    """Consonantal skeleton: drop vowel points + cantillation (combining marks)."""
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if not unicodedata.combining(c))


def greek_lex_strong(api) -> dict[str, str]:
    """lemma → dominant Strong's, straight from Nestle1904's `strong` feature."""
    lemma = api.Fs("lemma")
    strong = api.Fs("strong")
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for w in api.F.otype.s("w"):
        lm, st = lemma.v(w), strong.v(w)
        if lm and st:
            votes[str(lm)][f"G{int(st):04d}"] += 1
    return {lm: c.most_common(1)[0][0] for lm, c in votes.items()}


def hebrew_lex_strong(api) -> dict[str, str]:
    """BHSA lex → Strong's via the three-tier resolver (see module docstring)."""
    from corpus import _book_map
    F, L, T = api.F, api.L, api.T
    lex, voc, cons = api.Fs("lex"), api.Fs("voc_lex_utf8"), api.Fs("g_cons_utf8")
    con = sqlite3.connect(SPINE_DB)
    name2usfm = {n: u for u, (n, cid) in _book_map().items() if cid == "hebrew"}

    pointed: dict[str, str] = {}                       # spine pointed lemma → strong
    uniq: dict[str, set] = collections.defaultdict(set)  # consonantal lemma → {strong}
    for lemma, st in con.execute(
            "SELECT DISTINCT lemma, strong FROM spine_words WHERE strong IS NOT NULL"):
        if lemma:
            code = f"H{int(st):04d}"
            pointed.setdefault(lemma, code)
            uniq[_strip(lemma)].add(code)

    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for vnode in F.otype.s("verse"):
        bk, ch, vs = T.sectionFromNode(vnode)
        usfm = name2usfm.get(bk)
        if not usfm:
            continue
        sp_list = [(_strip(s), f"H{int(st):04d}")
                   for s, st in con.execute(
                       "SELECT surface, strong FROM spine_words "
                       "WHERE book=? AND chapter=? AND verse=?", (usfm, ch, vs)) if st]
        for w in L.d(vnode, otype="word"):
            wc = _strip(cons.v(w))
            if not wc:
                continue
            for surf, code in sp_list:
                if wc in surf or surf in wc:
                    votes[lex.v(w)][code] += 1
    con.close()

    # One representative voc per lex.
    lex_voc: dict[str, str] = {}
    for w in F.otype.s("word"):
        l = lex.v(w)
        if l and l not in lex_voc:
            lex_voc[l] = voc.v(w)

    out: dict[str, str] = {}
    for l, v in lex_voc.items():
        if v in pointed:                              # tier 1: exact pointed
            out[l] = pointed[v]
            continue
        vt = votes.get(l)                             # tier 2: occurrence vote
        if vt:
            top, n = vt.most_common(1)[0]
            if n / sum(vt.values()) >= 0.7:
                out[l] = top
                continue
        s = uniq.get(_strip(v))                       # tier 3: unique consonantal
        if s and len(s) == 1:
            out[l] = next(iter(s))
    return out


def build() -> None:
    out_dir = _resources_dir() / "word_freq"
    out_dir.mkdir(parents=True, exist_ok=True)
    for corpus, stem, fn in [("greek", "grc", greek_lex_strong),
                             ("hebrew", "hbo", hebrew_lex_strong)]:
        api = engine._ensure_loaded(corpus)
        mapping = fn(api)
        path = out_dir / f"{stem}_strong.tsv"
        with path.open("w", encoding="utf-8") as fh:
            fh.write("lex\tstrong\n")
            for lex in sorted(mapping):
                fh.write(f"{lex}\t{mapping[lex]}\n")
        print(f"  {corpus:7s} -> {path.relative_to(_resources_dir().parent)} "
              f"({len(mapping)} lexemes mapped)")


if __name__ == "__main__":
    print("building lex→strong bridge ...")
    build()
    print("done.")
