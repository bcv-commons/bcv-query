#!/usr/bin/env python3
"""BHSA-free sense split for the semantic-neighbors pack: decide, per Hebrew word and stem, which of its
occurrences share a sense, from Hebrew usage alone.

Same method as bcv-RAG/scripts/cluster_senses_hebrew.py (the production sense layer), with BHSA-free
inputs: occurrences, stems and glosses from MACULA (lexeme-spine.db, CC BY) and BEREL embeddings of
word-centred windows (build_bhsa_free_contexts). Within each (lexeme, stem), occurrences are grouped by
their MACULA gloss; groups whose mean-centred embedding centroids have cosine >= THRESH are merged
(single linkage). Each resulting cluster is one sense; the English gloss only labels it.

THRESH is calibrated on structure, never on the usability scores: --calibrate picks the threshold at
which the share of (lexeme, stem) units with two or more senses matches production's (resources/
occurrences/hbo.db: 2,211 of 8,015 = 27.6%).

Writes a `sense` column into data/bhsa_free/occurrence.db ("<stem>.<n>", n = 1 for the most frequent).

  cd shoresh && .venv/bin/python3 -m macula.build_bhsa_free_senses --calibrate
  cd shoresh && .venv/bin/python3 -m macula.build_bhsa_free_senses --thresh 0.xx
"""
from __future__ import annotations

import argparse
import collections
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OCC = HERE / "data" / "bhsa_free" / "occurrence.db"
EMB = HERE / "data" / "bhsa_free" / "context_emb_berel.npz"
SPINE = HERE / "lexeme-spine.db"
TARGET_SPLIT_SHARE = 2211 / 8015


def _clean(g: str) -> str:
    g = re.sub(r"\[[^\]]*\]", "", g or "").replace(".", " ")
    return re.sub(r"\s+", " ", g).strip().lower()


def load_groups() -> dict[tuple[str, str], dict[str, tuple[np.ndarray, list[str]]]]:
    """(lexeme, stem) -> {gloss: (unit centroid, [occurrence keys])}, on mean-centred vectors."""
    z = np.load(EMB, allow_pickle=True)
    V = z["vectors"].astype(np.float32)
    V = V - V.mean(axis=0, keepdims=True)
    V /= np.linalg.norm(V, axis=1, keepdims=True) + 1e-9
    ctx_idx = {c: i for i, c in enumerate(z["contexts"])}
    stem_of = dict(sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True).execute(
        "SELECT key, COALESCE(stem, '') FROM spine_words WHERE lexeme LIKE 'hbo:%'"))
    acc: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, lexeme, gloss, context in sqlite3.connect(f"file:{OCC}?mode=ro", uri=True).execute(
            "SELECT key, lexeme, gloss, context FROM occurrence"):
        i = ctx_idx.get(context)
        if i is None or not lexeme:
            continue
        acc[(lexeme, stem_of.get(key, "") or "-")][_clean(gloss) or "?"].append((key, i))
    out = {}
    for unit, by_gloss in acc.items():
        out[unit] = {}
        for g, occ in by_gloss.items():
            c = V[[i for _k, i in occ]].mean(axis=0)
            out[unit][g] = (c / (np.linalg.norm(c) + 1e-9), [k for k, _i in occ])
    return out


def cluster(groups: dict[str, tuple[np.ndarray, list[str]]], thresh: float) -> list[list[str]]:
    """Single-linkage union-find over gloss groups (cosine >= thresh)."""
    names = list(groups)
    if len(names) == 1:
        return [names]
    M = np.vstack([groups[n][0] for n in names])
    S = M @ M.T
    parent = list(range(len(names)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if S[i, j] >= thresh:
                parent[find(i)] = find(j)
    out = collections.defaultdict(list)
    for i, n in enumerate(names):
        out[find(i)].append(n)
    return list(out.values())


def split_share(data, thresh: float) -> float:
    multi = sum(1 for groups in data.values() if len(cluster(groups, thresh)) >= 2)
    return multi / len(data)


def calibrate(data) -> float:
    lo, hi = -0.5, 1.0
    for _ in range(18):
        mid = (lo + hi) / 2
        if split_share(data, mid) > TARGET_SPLIT_SHARE:
            hi = mid
        else:
            lo = mid
    t = (lo + hi) / 2
    print(f"[bhsa-free-senses] threshold {t:.4f} -> split share {split_share(data, t):.3f} "
          f"(target {TARGET_SPLIT_SHARE:.3f})", file=sys.stderr)
    return t


def write(data, thresh: float) -> None:
    sense_of: dict[str, str] = {}
    n_units = n_multi = 0
    for (lexeme, stem), groups in data.items():
        clusters = cluster(groups, thresh)
        clusters.sort(key=lambda c: -sum(len(groups[g][1]) for g in c))
        n_units += 1
        n_multi += len(clusters) >= 2
        for k, c in enumerate(clusters, start=1):
            for g in c:
                for key in groups[g][1]:
                    sense_of[key] = f"{stem}.{k}"
    db = sqlite3.connect(OCC)
    cols = [r[1] for r in db.execute("PRAGMA table_info(occurrence)")]
    if "sense" not in cols:
        db.execute("ALTER TABLE occurrence ADD COLUMN sense TEXT")
    db.executemany("UPDATE occurrence SET sense=? WHERE key=?", [(s, k) for k, s in sense_of.items()])
    db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('sense_threshold', ?)", (f"{thresh:.4f}",))
    db.commit()
    print(f"[bhsa-free-senses] {n_units} (lexeme, stem) units, {n_multi} split into >=2 senses; "
          f"{len(sense_of)} occurrences labelled -> {OCC}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrate", action="store_true", help="pick the threshold by structure, then write")
    ap.add_argument("--thresh", type=float, default=None)
    args = ap.parse_args()
    data = load_groups()
    thresh = calibrate(data) if args.calibrate or args.thresh is None else args.thresh
    write(data, thresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
