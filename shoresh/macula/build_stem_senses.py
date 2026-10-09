#!/usr/bin/env python3
"""Per-stem senses for Hebrew verbs from the aligner's `rend` channel (the binyan trial of NC exit step 2a).

hebrew-word-senses splits each LEXEME into senses; a verb's binyanim (Piel / Hiphil of the same root) then share the lexeme's senses, which is why the MACULA lexeme base
loses the binyan-specific labels the BHSA inventory (per lexeme x stem) had. This script re-splits every verb lexeme that occurs in two or more stems PER (lexeme, stem),
from the same kind of evidence (which occurrences translators render alike), and keeps the published senses for everything else:

  1. start from verse-senses.db (the published hebrew-word-senses release);
  2. features per token: the `rend` ids of N languages (build_rend_renderings --read -> data/rend_renderings.pkl; one edition per language, seeded sample) plus the
     translation evidence build_rendering_senses uses (Clear-Bible attestations, optionally Global Bible Tools glosses);
  3. for each verb lexeme with 2+ stems, build_rendering_senses.split_lexeme runs on each stem's tokens separately; sense numbers are made unique per lexeme (stems in
     order of size, senses by size within a stem), so the reader needs no change: a sense belongs to exactly one stem (table sense_stem);
  4. the label of a sense is the most frequent English rendering among its tokens (as before).

  cd shoresh && .venv/bin/python3 -m macula.build_stem_senses [--rend macula/data/rend_renderings.pkl] [--languages 60] [--out macula/verse-senses-stem.db] [--gbt]
Use it with LEXEME_BASE=macula VERSE_SENSES_DB=macula/verse-senses-stem.db python -m macula.compare_lexeme_bases to measure the binyan lines against BHSA.
"""
from __future__ import annotations

import argparse
import collections
import multiprocessing as mp
import pickle
import random
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from macula import build_rendering_senses as bs                                   # noqa: E402

BASE = HERE / "verse-senses.db"
SPINE = HERE / "lexeme-spine-macula.db"
REND = HERE / "data" / "rend_renderings.pkl"

_FEATS: dict = {}
_ENG: dict = {}


def _work(item):
    lexeme, stem, keys = item
    a = bs.split_lexeme(keys, _FEATS)
    eng = collections.defaultdict(collections.Counter)
    for k, s in a.items():
        for lang, f in _FEATS.get(k, ()):
            if lang == "eng":
                eng[s][f] += 1
    labels = {s: bs._label(eng[s], _ENG) for s in set(a.values())}
    return lexeme, stem, a, labels


def pick_languages(editions: list[str], n: int, seed: int) -> set[str]:
    """editions: 'x/iso/edition' paths from the pickle -> the tags (r-iso-edition) of one edition per language, for a seeded sample of n languages."""
    by_lang = collections.defaultdict(list)
    for e in editions:
        p = Path(e)
        by_lang[p.parent.name].append(f"r-{p.parent.name}-{p.name}")
    langs = sorted(by_lang)
    random.Random(seed).shuffle(langs)
    return {by_lang[l][0] for l in langs[:n]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=BASE)
    ap.add_argument("--rend", type=Path, default=REND)
    ap.add_argument("--languages", type=int, default=60)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", type=Path, default=HERE / "verse-senses-stem.db")
    ap.add_argument("--gbt", action="store_true", help="add Global Bible Tools glosses to the evidence, as the published build does")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    bs.USE_GBT = a.gbt
    feats, eng_raw = bs.load_features()
    with a.rend.open("rb") as fh:
        pk = pickle.load(fh)
    tags = pick_languages(pk["editions"], a.languages, a.seed)
    n_rend = 0
    for k, fs in pk["features"].items():
        sel = {f for f in fs if f[0] in tags}
        if sel:
            feats[k] |= sel
            n_rend += 1
    del pk                                                       # ~1 GB pickle, several GB of sets: free it before the workers fork
    import gc; gc.collect()
    print(f"features: attestations + {len(tags)} rend editions on {n_rend} tokens ({time.time() - t0:.0f}s)", file=sys.stderr)
    global _FEATS, _ENG
    _FEATS, _ENG = feats, eng_raw

    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    groups: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, lexeme, stem in sp.execute("SELECT key, lexeme, stem FROM spine_words WHERE lexeme LIKE 'hbo:%' AND stem!='' AND stem IS NOT NULL"):
        groups[lexeme][stem].append(key)
    multi = {lx: st for lx, st in groups.items() if len(st) >= 2}
    items = [(lx, stem, keys) for lx, st in multi.items() for stem, keys in st.items()]
    print(f"{len(multi)} verb lexemes with 2+ stems, {len(items)} (lexeme, stem) groups", file=sys.stderr)
    with mp.get_context("fork").Pool(a.workers) as pool:
        results = pool.map(_work, items, chunksize=8)

    per_lexeme: dict = collections.defaultdict(dict)
    for lexeme, stem, assign, labels in results:
        per_lexeme[lexeme][stem] = (assign, labels)

    if a.out.exists():
        a.out.unlink()
    out = sqlite3.connect(a.out)
    out.executescript("""
        CREATE TABLE occ(key TEXT PRIMARY KEY, lexeme TEXT NOT NULL, sense INTEGER NOT NULL) WITHOUT ROWID;
        CREATE TABLE senses(lexeme TEXT NOT NULL, sense INTEGER NOT NULL, label TEXT NOT NULL, n INTEGER, share REAL, PRIMARY KEY(lexeme, sense)) WITHOUT ROWID;
        CREATE TABLE sense_stem(lexeme TEXT NOT NULL, sense INTEGER NOT NULL, stem TEXT NOT NULL, PRIMARY KEY(lexeme, sense)) WITHOUT ROWID;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    base = sqlite3.connect(f"file:{a.base}?mode=ro", uri=True)
    replaced = set(multi)
    out.executemany("INSERT INTO occ VALUES (?,?,?)", [r for r in base.execute("SELECT key, lexeme, sense FROM occ") if r[1] not in replaced])
    out.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", [r for r in base.execute("SELECT lexeme, sense, label, n, share FROM senses") if r[0] not in replaced])
    n_senses = 0
    for lexeme, stems in per_lexeme.items():
        nxt = 0
        total = sum(len(a_) for a_, _ in stems.values())
        for stem, (assign, labels) in sorted(stems.items(), key=lambda kv: -len(kv[1][0])):
            local = collections.Counter(assign.values())
            for s, n in local.most_common():
                nxt += 1
                out.execute("INSERT INTO senses VALUES (?,?,?,?,?)", (lexeme, nxt, labels.get(s, ""), n, round(n / max(total, 1), 3)))
                out.execute("INSERT INTO sense_stem VALUES (?,?,?)", (lexeme, nxt, stem))
                out.executemany("INSERT INTO occ VALUES (?,?,?)", [(k, lexeme, nxt) for k, v in assign.items() if v == s])
                n_senses += 1
    out.executemany("INSERT INTO meta VALUES (?,?)", [
        ("base", str(a.base.name)), ("rend_editions", str(len(tags))), ("seed", str(a.seed)), ("verb_lexemes_resplit", str(len(multi))),
        ("note", "verb lexemes with 2+ stems re-split per (lexeme, stem) from rend + attestation evidence; everything else is the published hebrew-word-senses"),
        ("license", "CC BY 4.0 (keys and sense numbers); evidence: aligner rend ids (CC0) and Clear-Bible attestations")])
    out.commit()
    print(f"wrote {a.out}: {len(multi)} lexemes re-split into {n_senses} stem-bound senses in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
