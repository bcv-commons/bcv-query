"""Per-occurrence renderings from the aligner's published `rend` channel (no edition texts needed).

The lexeme-aligner publishes, next to each compact-alignments file `<BOOK>_<hash>.json` (one "srcOrd:span"
string per verse), a meta sidecar `<BOOK>_<hash>.meta.json` (repo bcv-commons/compact-alignments-meta, same
path). Its `rend` channel holds one string per verse, one integer per `srcOrd:span` part in the same order:
the n-th distinct rendering of that Hebrew lexeme in that edition (a rendering = the aligned target words,
case-folded, joined by one space), numbered by first appearance in canonical order. Ids are comparable only
within one edition and one lexeme, which is all the sense split needs: which occurrences an edition renders
alike. Each occurrence gets the feature (r-<edition>, id) for build_rendering_senses --compact.

This replaces build_compact_renderings.py, which joined the compact strings to the editions' cached text and
the aligner's tokenizer.

  python -m macula.build_rend_renderings --read [--compact DIR] [--meta DIR] [--one-per-language]
      -> macula/data/rend_renderings.pkl

Before the channel is published, `--simulate` writes it from the cached texts, exactly as described, for N
languages, into a scratch meta tree, together with build_compact_renderings' word features for the same
editions (to compare the two):

  python -m macula.build_rend_renderings --simulate --languages 80 --meta-out DIR
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pickle
import random
import re
import sqlite3
import sys
from pathlib import Path

from macula.build_compact_renderings import (COMPACT, OT_BOOKS, SPINE, USJ_CACHE, _aligner_imports, content_keys,
                                             edition_features, editions)

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "rend_renderings.pkl"


def _book_file(ed: Path, book: str) -> Path | None:
    files = [f for f in ed.glob(f"{book}_*.json") if re.match(rf"{book}_[0-9a-f]+\.json$", f.name)]
    return files[0] if files else None


def _refs(compact_root: Path, book: str) -> list[str]:
    p = compact_root / "_index" / f"{book}_lexemes.json"
    return list(json.loads(p.read_text(encoding="utf-8")).keys()) if p.exists() else []


def _index(compact_root: Path, book: str) -> dict[str, list[str]]:
    """verse -> the aligner's lexeme per srcOrd (its `_index/<BOOK>_lexemes.json`)."""
    p = compact_root / "_index" / f"{book}_lexemes.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def map_entries(theirs: list[str], mine: list[str]) -> dict[int, list[int]]:
    """srcOrd -> positions in our content-token list of the verse, by aligning the two lexeme lists.

    The aligner's entry i is NOT always our content token i (found 2026-10-05 with the rend sample: 7% of verses,
    3.8% of entries): it counts a name written as two words (Beth + lehem, both lexeme 1035) once, and has a few
    entries fewer. Their list is a subsequence of ours, so match the lexeme digits; a token of ours that has no
    partner and repeats the lexeme of the entry before it is part of that entry (pooled name), any other extra
    token has no entry and gets no feature. Where the lists differ in kind (not seen), position decides."""
    from difflib import SequenceMatcher
    norm = lambda x: x.split(":")[-1].lstrip("0")
    out: dict[int, list[int]] = {}
    sm = SequenceMatcher(None, [norm(x) for x in theirs], [norm(x) for x in mine], autojunk=False)
    last = None
    for tag, a, b, c, d in sm.get_opcodes():
        if tag == "equal" or (tag == "replace" and b - a == d - c):
            for k in range(b - a):
                out[a + k] = [c + k]
                last = a + k
        elif tag == "insert" and last is not None:                        # extra tokens of ours
            for j in range(c, d):
                if norm(mine[j]) == norm(mine[out[last][-1]]):
                    out[last].append(j)
        elif tag == "replace":                                           # unequal blocks: pair from the start
            for k in range(min(b - a, d - c)):
                out[a + k] = [c + k]
                last = a + k
    return out


def read(compact_root: Path, meta_root: Path, one_per_language: bool, out: Path) -> None:
    keys = content_keys()
    spine_lex = {k: lx for k, lx in sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
                 .execute("SELECT key, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'")}
    index = {b: _index(compact_root, b) for b in OT_BOOKS}
    refs = {b: list(index[b]) for b in OT_BOOKS}
    mapped = {}                                                          # (ref) -> srcOrd -> positions, cached
    eds = []
    for iso_dir in sorted(compact_root.glob("?/*")):
        cands = []
        for ed in sorted(p for p in iso_dir.iterdir() if p.is_dir()):
            n = sum(1 for b in OT_BOOKS if (f := _book_file(ed, b)) and
                    (meta_root / f.relative_to(compact_root)).with_suffix(".meta.json").exists())
            if n:
                cands.append((n, ed))
        if cands:
            eds += [max(cands)[1]] if one_per_language else [ed for _n, ed in cands]
    feats: dict = collections.defaultdict(set)
    st = collections.Counter()
    for ed in eds:
        tag = f"r-{ed.parent.name}-{ed.name}"
        for book in OT_BOOKS:
            f = _book_file(ed, book)
            if not f:
                continue
            mp = (meta_root / f.relative_to(compact_root)).with_suffix(".meta.json")
            if not mp.exists():
                continue
            rend = json.loads(mp.read_text(encoding="utf-8")).get("rend")
            if not rend:
                st["files_without_rend"] += 1
                continue
            compact = json.loads(f.read_text(encoding="utf-8"))
            for ref, s, r in zip(refs[book], compact, rend):
                ks = keys.get(ref)
                if not s or not r or not ks:
                    continue
                parts, ids = s.split(), r.split()
                if len(parts) != len(ids):
                    st["verses_length_mismatch"] += 1
                    continue
                if ref not in mapped:
                    mapped[ref] = map_entries(index[book][ref], [spine_lex[k] for k in ks])
                    st["verses_realigned"] += mapped[ref] != {i: [i] for i in range(len(index[book][ref]))}
                for part, rid in zip(parts, ids):
                    for pos in mapped[ref].get(int(part.split(":", 1)[0]), []):
                        feats[ks[pos]].add((tag, rid))
                        st["occurrences"] += 1
        st["editions"] += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        pickle.dump({"editions": [str(e.relative_to(compact_root)) for e in eds], "features": dict(feats)}, fh)
    print(f"[rend] {dict(st)}; tokens with features {len(feats)} -> {out}", file=sys.stderr)


def _normalizer(mode: str, iso: str):
    """How a rendering is normalized before numbering: "none" (the aligner's stated rule: case-folded words
    joined by a space), "stop" (also drop the language's target-stopwords), "stop5" (and keep each word's
    first 5 letters, as build_compact_renderings' features do)."""
    from macula.build_compact_renderings import STOPWORDS
    stop = set()
    sw = STOPWORDS / f"{iso}.txt"
    if mode != "none" and sw.exists():
        stop = {w.strip().casefold() for w in sw.read_text(encoding="utf-8").splitlines() if w.strip()}

    def norm(words: list[str]) -> str:
        ws = [w.casefold() for w in words]
        if mode != "none":
            ws = [w for w in ws if w not in stop] or ws          # all function words: keep as is
        if mode == "stop5":
            ws = [w[:5] for w in ws]
        return " ".join(ws)
    return norm


def simulate(languages: int, seed: int, meta_out: Path, words_out: Path, mode: str = "none") -> None:
    """The `rend` channel as the aligner describes it, from the cached texts (same pairing as
    build_compact_renderings), plus that script's word features for the same editions."""
    book_num, read_verse_ranges, tokenize = _aligner_imports()
    eds = editions()
    isos = sorted(eds)
    random.Random(seed).shuffle(isos)
    pick = sorted(isos[:languages])
    keys = content_keys()
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    lex_of = {k: lx for k, lx in db.execute("SELECT key, lexeme FROM spine_words WHERE lexeme LIKE 'hbo:%'")}
    words: dict = collections.defaultdict(set)
    for n, iso in enumerate(pick, 1):
        ed = eds[iso]
        usj_dir = next((d for d in USJ_CACHE.glob("usj-*") if d.name[4:].lower() == ed.name.lower()), None)
        if usj_dir is None:
            continue
        for k, fs in edition_features(iso, ed, keys, book_num, read_verse_ranges, tokenize).items():
            words[k] |= fs
        ids: dict = collections.defaultdict(dict)              # lexeme -> rendering -> id, whole edition
        norm = _normalizer(mode, iso)
        for book in OT_BOOKS:                                  # canonical order
            f = _book_file(ed, book)
            usj = usj_dir / f"{book_num[book]}-{book}.json"
            if not f or not usj.exists():
                continue
            compact = json.loads(f.read_text(encoding="utf-8"))
            ranges = read_verse_ranges(usj, rules={}, warn=open(os.devnull, "w"))
            rend = []
            for ref, s in zip(_refs(COMPACT, book), compact):
                c, v = (int(x) for x in ref.split()[1].split(":"))
                info, ks = ranges.get((c, v)), keys.get(ref)
                toks = tokenize(info["text"]) if info else []
                out = []
                for part in (s or "").split():
                    o, span = part.split(":")
                    idxs = []
                    for seg in span.split(","):
                        a, _, b = seg.partition("-")
                        idxs += list(range(int(a), int(b or a) + 1))
                    rendering = norm([toks[i] for i in idxs if i < len(toks)])
                    lx = lex_of.get(ks[int(o)]) if ks and int(o) < len(ks) else None
                    table = ids[lx]
                    out.append(str(table.setdefault(rendering, len(table) + 1)))
                rend.append(" ".join(out))
            dst = (meta_out / f.relative_to(COMPACT)).with_suffix(".meta.json")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(json.dumps({"rend": rend}, ensure_ascii=False), encoding="utf-8")
        if n % 10 == 0:
            print(f"  {n}/{len(pick)} editions simulated", file=sys.stderr)
    with words_out.open("wb") as fh:
        pickle.dump({"languages": pick, "editions": {i: eds[i].name for i in pick}, "features": dict(words)}, fh)
    print(f"[rend] simulated {len(pick)} editions -> {meta_out}; word features -> {words_out}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--read", action="store_true")
    ap.add_argument("--compact", type=Path, default=COMPACT, help="compact-alignments root")
    ap.add_argument("--meta", type=Path, default=COMPACT,
                    help="compact-alignments-meta root (same paths; locally the meta files sit beside the main ones)")
    ap.add_argument("--one-per-language", action="store_true", help="the edition with most OT books per language")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--languages", type=int, default=80)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--meta-out", type=Path)
    ap.add_argument("--words-out", type=Path)
    ap.add_argument("--normalize", choices=["none", "stop", "stop5"], default="none",
                    help="--simulate: how renderings are normalized before numbering")
    a = ap.parse_args()
    if a.simulate:
        simulate(a.languages, a.seed, a.meta_out, a.words_out or a.meta_out / "words.pkl", a.normalize)
    if a.read:
        read(a.compact, a.meta, a.one_per_language, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
