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
Serve it with VERSE_SENSES_DB=macula/verse-senses-stem.db (or ship it as verse-senses.db). The BHSA comparison that justified it (compare_lexeme_bases) is in internal-docs/binyan-fair-comparison.md.
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
    by_sense = collections.defaultdict(list)
    for k, s in a.items():
        by_sense[s].append(k)
    labels = {s: bs._label(eng[s], _ENG, by_sense[s]) for s in set(a.values())}
    raw = {s: {f: bs.token_surface(f, by_sense[s]) for f in eng[s]} for s in by_sense}            # per sense: the surface its own tokens carry
    return lexeme, stem, a, labels, {s: dict(c) for s, c in eng.items()}, raw


def pick_languages(editions: list[str], n: int, seed: int) -> set[str]:
    """editions: 'x/iso/edition' paths from the pickle -> the tags (r-iso-edition) of one edition per language, for a seeded sample of n languages."""
    by_lang = collections.defaultdict(list)
    for e in editions:
        p = Path(e)
        by_lang[p.parent.name].append(f"r-{p.parent.name}-{p.name}")
    langs = sorted(by_lang)
    random.Random(seed).shuffle(langs)
    return {by_lang[l][0] for l in langs[:n]}


def split_all(a):
    bs.USE_GBT = a.gbt
    t0 = time.time()
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
    for lexeme, stem, assign, labels, eng, raw in results:
        per_lexeme[lexeme][stem] = (assign, labels, eng, raw)
    base = sqlite3.connect(f"file:{a.base}?mode=ro", uri=True)
    toks = collections.defaultdict(list)
    for key, lexeme, sense in base.execute("SELECT key, lexeme, sense FROM occ"):
        toks[(lexeme, sense)].append(key)
    # The published label of a sense keeps its form; only the surface is re-read from the sense's own tokens (the published build wrote the corpus-wide most
    # common surface of the form: "sanctuary" for the verb sanctify). Labels whose form no token carries are left as published.
    import re
    base_labels = {}
    for lexeme, sense, label in base.execute("SELECT lexeme, sense, label FROM senses"):
        m = re.match(r"^(.*?)( \(\d+\))?$", label or "")
        surf = bs.token_surface(bs.norm("eng", m.group(1)), toks.get((lexeme, sense), ())) if m and m.group(1) else ""
        if surf and surf != m.group(1):
            base_labels[(lexeme, sense)] = surf + (m.group(2) or "")
    return dict(per_lexeme), tags, set(multi), base_labels


PASSIVE = {"niphal", "pual", "hophal", "hithpael", "hothpael", "hithpolel", "nithpael"}
# English words that are never a sense label on their own (auxiliaries and light words that translations of many different Hebrew verbs share)
LABEL_STOP = {"be", "been", "being", "am", "is", "are", "was", "were", "have", "has", "had", "having", "do", "does", "did", "done", "will", "shall", "would", "should", "may", "might",
              "can", "could", "must", "get", "got", "let", "not", "nor", "yet", "also", "then", "thus", "who", "whom", "which", "that", "this", "these", "those", "they", "them", "him",
              "her", "his", "its", "our", "you", "your", "their", "there", "here", "come", "came", "go", "went"}
FLOOR = 0.4                                          # a candidate label must be at least this fraction as frequent in the group as its commonest rendering


def _participle(label: str) -> bool:
    return label.endswith(("ed", "en")) and " " not in label


def make_idf(per_lexeme: dict) -> dict:
    """form -> log(N / (1 + number of verb lexemes it is a real rendering of, at least 5% of that lexeme's English evidence)): generic words (made, thing, cause)
    are renderings of many verbs and make poor labels."""
    import math
    df = collections.Counter()
    for stems in per_lexeme.values():
        tot = collections.Counter()
        for _a, _l, eng, _r in stems.values():
            for c in eng.values():
                tot.update(c)
        n = sum(tot.values()) or 1
        df.update(f for f, v in tot.items() if v / n >= 0.05)
    N = len(per_lexeme)
    return {f: math.log(N / (1 + d)) for f, d in df.items()}


def relabel(stems: dict, mode: str, idf: dict | None = None) -> dict:
    """{stem: {sense: label}} for one lexeme. freq = the most frequent English rendering of the group (the published way).
    distinct = among the group's frequent renderings (at least FLOOR of the top one, no auxiliaries), the one most specific to the group against the lexeme's other
    stems: p / (p + p_other). No label is forced to differ, so it differs only where the translations do.
    voice = distinct, and a participle label of a passive/reflexive stem (niphal, pual, hophal, hithpael ...: the stem comes from the Hebrew morphology) is written
    "be gathered" instead of "gathered", the way a dictionary glosses the passive."""
    if mode == "freq":
        return {st: v[1] for st, v in stems.items()}
    stem_tot = {st: collections.Counter() for st in stems}
    for st, (_a, _l, eng, _r) in stems.items():
        for c in eng.values():
            stem_tot[st].update(c)
    out = {}
    for st, (assign, freq_labels, eng, raw) in stems.items():
        other = collections.Counter()
        for o, c in stem_tot.items():
            if o != st:
                other.update(c)
        n_other = sum(other.values()) or 1
        labels = dict(freq_labels)                   # senses without English evidence keep their frequency label
        for sense, c in eng.items():
            n = sum(c.values()) or 1
            rw = raw.get(sense, {})
            ok = {f: v for f, v in c.items() if (rw.get(f) or f).lower() not in LABEL_STOP and len(rw.get(f) or f) >= 3}
            if not ok:
                continue
            top = max(ok.values())
            cand = [f for f, v in ok.items() if v >= FLOOR * top]
            best = max(cand, key=lambda f: (ok[f] / n) ** 2 / ((ok[f] / n) + other.get(f, 0) / n_other) * max((idf or {}).get(f, 3.0), 0.1))
            lab = rw.get(best) or best
            if mode == "voice" and st in PASSIVE and _participle(lab):
                lab = "be " + lab
            labels[sense] = lab
        out[st] = labels
    return out


MODES = {"freq", "distinct", "voice"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, default=BASE)
    ap.add_argument("--rend", type=Path, default=REND)
    ap.add_argument("--languages", type=int, default=60)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", type=Path, default=HERE / "verse-senses-stem.db")
    ap.add_argument("--gbt", action="store_true", help="add Global Bible Tools glosses to the evidence, as the published build does")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cache", type=Path, default=HERE / "data" / "stem_senses_cache.pkl", help="split results (assignments + English forms per sense); written after a split, read by --from-cache")
    ap.add_argument("--from-cache", action="store_true", help="skip the split: relabel the cached groups (seconds), for label experiments")
    ap.add_argument("--label", default="voice", choices=sorted(MODES), help="how a group is labelled (see relabel)")
    a = ap.parse_args()
    t0 = time.time()
    multi: set = set()
    if a.from_cache:
        with a.cache.open("rb") as fh:
            ck = pickle.load(fh)
        per_lexeme, tags, multi, base_labels = ck["per_lexeme"], ck["tags"], set(ck["per_lexeme"]), ck["base_labels"]
    else:
        per_lexeme, tags, multi, base_labels = split_all(a)
        a.cache.parent.mkdir(parents=True, exist_ok=True)
        with a.cache.open("wb") as fh:
            pickle.dump({"per_lexeme": per_lexeme, "tags": tags, "base_labels": base_labels}, fh)
    idf = make_idf(per_lexeme)
    for lexeme, stems in per_lexeme.items():
        labs = relabel(stems, a.label, idf)
        for stem, (assign, _l, eng, raw) in stems.items():
            stems[stem] = (assign, labs[stem], eng, raw)

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
    out.executemany("INSERT INTO senses VALUES (?,?,?,?,?)", [(r[0], r[1], base_labels.get((r[0], r[1]), r[2]), r[3], r[4])
                                                              for r in base.execute("SELECT lexeme, sense, label, n, share FROM senses") if r[0] not in replaced])
    n_senses = 0
    for lexeme, stems in per_lexeme.items():
        nxt = 0
        total = sum(len(v[0]) for v in stems.values())
        for stem, (assign, labels, _e, _r) in sorted(stems.items(), key=lambda kv: -len(kv[1][0])):
            local = collections.Counter(assign.values())
            for s, n in local.most_common():
                nxt += 1
                out.execute("INSERT INTO senses VALUES (?,?,?,?,?)", (lexeme, nxt, labels.get(s, ""), n, round(n / max(total, 1), 3)))
                out.execute("INSERT INTO sense_stem VALUES (?,?,?)", (lexeme, nxt, stem))
                out.executemany("INSERT INTO occ VALUES (?,?,?)", [(k, lexeme, nxt) for k, v in assign.items() if v == s])
                n_senses += 1
    out.executemany("INSERT INTO meta VALUES (?,?)", [
        ("base", str(a.base.name)), ("rend_editions", str(len(tags))), ("seed", str(a.seed)), ("label_mode", a.label), ("verb_lexemes_resplit", str(len(multi))),
        ("note", "verb lexemes with 2+ stems re-split per (lexeme, stem) from rend + attestation evidence; everything else is the published hebrew-word-senses"),
        ("license", "CC BY 4.0 (keys and sense numbers); evidence: aligner rend ids (CC0) and Clear-Bible attestations")])
    out.commit()
    print(f"wrote {a.out}: {len(multi)} lexemes re-split into {n_senses} stem-bound senses in {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
