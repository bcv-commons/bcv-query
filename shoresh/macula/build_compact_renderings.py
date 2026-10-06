"""Per-occurrence renderings for many languages from the lexeme-aligner's positional alignments.

The aligner publishes, per edition and book, which Hebrew content word aligned to which target-token positions
(bcv-commons/compact-alignments, CC0: "srcOrd:span" strings, positions in the edition's own tokenization of
its unmodified verse text). Joined with the edition's text (the aligner's ingest cache of USJ files) and the
aligner's own tokenizer, that gives the words each occurrence was rendered with, in ~1,800 languages, not
only the ~20 with manual alignments. srcOrd i is the i-th content token (strong and is_content) of the verse in
lexeme-spine-macula.db, the spine the aligner runs on, so it maps straight onto our token keys.

KNOWN FLAW (found 2026-10-05, superseded by build_rend_renderings.py): srcOrd is mapped to a spine token by
POSITION in content_keys(), but the aligner's `_index/<BOOK>_lexemes.json` is the authority and differs in ~7% of
verses (a name written as two words, e.g. Beth + lehem, counts once; a few entries fewer): ~3.8% of entries were
attached to a neighbouring token. build_rend_renderings.map_entries() aligns the two lists instead.

Used as extra features for the sense split (build_rendering_senses.py --compact FILE). Reads the aligner's
repository and caches; changes nothing there.

  python -m macula.build_compact_renderings --languages 80        # -> macula/data/compact_renderings_80.pkl
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

HERE = Path(__file__).resolve().parent
ALIGNER = Path(os.environ.get("LEXEME_ALIGNER", str(Path.home() / "dev/bcv-commons/lexeme-aligner")))
COMPACT = ALIGNER / "publish" / "compact-alignments"
USJ_CACHE = ALIGNER / "pipeline" / "work" / "ingest-cache"
STOPWORDS = ALIGNER / "publish" / "target-stopwords"
SPINE = HERE / "lexeme-spine-macula.db"
OT_BOOKS = ["GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI", "1CH", "2CH",
            "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL",
            "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL"]


def _aligner_imports():
    sys.path.insert(0, str(ALIGNER / "pipeline"))
    from lexeme_aligner.run_pilot import _BOOK_FILE_NUM
    from lexeme_aligner.usj_source import read_verse_ranges, tokenize
    return _BOOK_FILE_NUM, read_verse_ranges, tokenize


def editions() -> dict[str, Path]:
    """iso -> the edition folder with the most Old Testament books that also has its text cached."""
    best: dict = {}
    usj = {d.name[4:].lower(): d for d in USJ_CACHE.glob("usj-*")}   # DBT ids differ in case (SEAWBT/seawbt)
    for iso_dir in COMPACT.glob("?/*"):
        for ed in iso_dir.iterdir():
            if not ed.is_dir() or ed.name.lower() not in usj:
                continue
            n = sum(1 for b in OT_BOOKS if any(ed.glob(f"{b}_*[0-9a-f].json")))
            if n >= 30 and (iso_dir.name not in best or n > best[iso_dir.name][0]):
                best[iso_dir.name] = (n, ed)
    return {iso: ed for iso, (_n, ed) in best.items()}


def content_keys() -> dict[str, list[str]]:
    """"BOOK c:v" -> the verse's content tokens' keys in order (the aligner's anchor_content)."""
    db = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    out = collections.defaultdict(list)
    for b, c, v, key in db.execute("SELECT book, chapter, verse, key FROM spine_words WHERE lexeme LIKE 'hbo:%' "
                                   "AND strong IS NOT NULL AND is_content=1 ORDER BY book, chapter, verse, idx"):
        out[f"{b} {c}:{v}"].append(key)
    return out


def edition_features(iso: str, ed: Path, keys: dict, book_num, read_verse_ranges, tokenize) -> dict:
    stop = set()
    sw = STOPWORDS / f"{iso}.txt"
    if sw.exists():
        stop = {w.strip().lower() for w in sw.read_text(encoding="utf-8").splitlines() if w.strip()}
    feats: dict = collections.defaultdict(set)
    usj_dir = next((d for d in USJ_CACHE.glob("usj-*") if d.name[4:].lower() == ed.name.lower()), None)
    if usj_dir is None:
        return feats
    for book in OT_BOOKS:
        files = [f for f in ed.glob(f"{book}_*.json") if re.match(rf"{book}_[0-9a-f]+\.json$", f.name)]
        idx_path = COMPACT / "_index" / f"{book}_lexemes.json"
        usj = usj_dir / f"{book_num[book]}-{book}.json"
        if not files or not idx_path.exists() or not usj.exists():
            continue
        refs = list(json.loads(idx_path.read_text(encoding="utf-8")).keys())
        compact = json.loads(files[0].read_text(encoding="utf-8"))
        ranges = read_verse_ranges(usj, rules={}, warn=open(os.devnull, "w"))
        for ref, s in zip(refs, compact):
            if not s:
                continue
            c, v = (int(x) for x in ref.split()[1].split(":"))
            info = ranges.get((c, v))
            ks = keys.get(ref)
            if not info or not ks:
                continue
            toks = tokenize(info["text"])
            for part in s.split():
                o, span = part.split(":")
                o = int(o)
                if o >= len(ks):
                    continue
                idxs = []
                for seg in span.split(","):
                    a, _, b = seg.partition("-")
                    idxs += list(range(int(a), int(b or a) + 1))
                for i in idxs:
                    if i < len(toks):
                        w = toks[i].lower()
                        if len(w) >= 3 and w not in stop and not w.isdigit():
                            feats[ks[o]].add((f"x-{iso}", w[:5]))
    return feats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--languages", type=int, default=80)
    ap.add_argument("--seed", type=int, default=13)
    a = ap.parse_args()
    book_num, read_verse_ranges, tokenize = _aligner_imports()
    eds = editions()
    isos = sorted(eds)
    random.Random(a.seed).shuffle(isos)
    pick = sorted(isos[:a.languages])
    print(f"[compact-renderings] {len(eds)} languages with an OT edition and cached text; using {len(pick)}",
          file=sys.stderr)
    keys = content_keys()
    feats: dict = collections.defaultdict(set)
    for n, iso in enumerate(pick, 1):
        f = edition_features(iso, eds[iso], keys, book_num, read_verse_ranges, tokenize)
        for k, fs in f.items():
            feats[k] |= fs
        if n % 10 == 0:
            print(f"  {n}/{len(pick)} languages; tokens with features {len(feats)}", file=sys.stderr)
    out = HERE / "data" / f"compact_renderings_{a.languages}.pkl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as fh:
        pickle.dump({"languages": pick, "editions": {i: eds[i].name for i in pick}, "features": dict(feats)}, fh)
    print(f"[compact-renderings] -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
