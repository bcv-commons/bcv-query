#!/usr/bin/env python3
"""Phase 2+3 refinement — merge synonymous senses with LOCAL embeddings (no API).

The heuristic sense layer (build_lex_senses.py) collapses inflection but not synonymy: קדשׁ
hif still lists 'consecrate', 'set apart as holy', 'regard as holy' as separate senses. This
re-derives the inventory from the SAME stored per-occurrence glosses, merging senses WITHIN
each (lex, stem) whose gloss embeddings are close (single-linkage above a cosine threshold).
Local bge-m3 on the Mac — no Cloudflare/API quota touched.

  shoresh/.venv/bin/python bcv-RAG/scripts/merge_senses_embed.py [--thresh 0.72] [--model BAAI/bge-m3]

Reads/writes the same artifacts as build_lex_senses.py (sidecar sense column + hbo_lex.tsv);
run it AFTER build_lex_senses.py. Re-runnable — it re-derives, never re-aligns.
"""
from __future__ import annotations

import collections
import csv
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_lex_senses import OCC, OUT, _norm   # noqa: E402  reuse anchor path + normalizer


def _readable(raw: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[()\[\]{}]", "", (raw or "").replace(".", " "))).strip()


def _cluster(items: list[str], emb: dict, thresh: float) -> list[list[str]]:
    """Single-linkage union-find: merge items whose embeddings cosine ≥ thresh."""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        ei = emb[items[i]]
        for j in range(i + 1, n):
            if float(sum(a * b for a, b in zip(ei, emb[items[j]]))) >= thresh:
                parent[find(i)] = find(j)
    groups = collections.defaultdict(list)
    for i in range(n):
        groups[find(i)].append(items[i])
    return list(groups.values())


def main() -> None:
    argv = sys.argv[1:]
    thresh = float(argv[argv.index("--thresh") + 1]) if "--thresh" in argv else 0.72
    model_id = argv[argv.index("--model") + 1] if "--model" in argv else "BAAI/bge-m3"

    occ = sqlite3.connect(OCC)
    rows = occ.execute("SELECT node, lex, stem, gloss FROM occurrence WHERE gloss IS NOT NULL").fetchall()

    ls_norm_nodes: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    raw_form: dict = collections.defaultdict(collections.Counter)   # norm -> Counter(raw) (global, readable rep)
    lsnorm_raw: dict = collections.defaultdict(collections.Counter) # (lex,stem,norm) -> Counter(raw)
    for node, lex, stem, raw in rows:
        ng = _norm(raw)
        if not ng:
            continue
        ls_norm_nodes[(lex, stem)][ng].append(node)
        raw_form[ng][raw] += 1
        lsnorm_raw[(lex, stem, ng)][raw] += 1

    # representative readable gloss per normalized form → embed once
    norms = sorted(raw_form)
    reps = [_readable(min(raw_form[n].items(), key=lambda kv: (kv[0].count("."), -kv[1]))[0]) for n in norms]
    print(f"embedding {len(norms)} distinct senses with {model_id} (local) …", file=sys.stderr)
    from sentence_transformers import SentenceTransformer
    vecs = SentenceTransformer(model_id).encode(reps, normalize_embeddings=True, batch_size=128,
                                                show_progress_bar=True)
    emb = {n: v for n, v in zip(norms, vecs)}

    # re-derive: cluster synonyms within each (lex, stem)
    updates, inv_rows = [], []
    merged_from = merged_to = 0
    for (lex, stem), norm_nodes in ls_norm_nodes.items():
        ngs = list(norm_nodes)
        groups = _cluster(ngs, emb, thresh) if len(ngs) > 1 else [[ngs[0]]]
        merged_from += len(ngs)
        merged_to += len(groups)
        scored = []
        for g in groups:
            nodes = [n for ng in g for n in norm_nodes[ng]]
            scored.append((len(nodes), g, nodes))
        scored.sort(key=lambda s: -s[0])
        total = sum(s[0] for s in scored)
        for rank, (cnt, g, nodes) in enumerate(scored, 1):
            cc = collections.Counter()
            for ng in g:
                cc.update(lsnorm_raw[(lex, stem, ng)])
            canon = min(cc.items(), key=lambda kv: (kv[0].count("."), -kv[1]))[0]
            share = round(cnt / total, 3)
            inv_rows.append((lex, stem, rank, canon, cnt, share))
            for n in nodes:
                updates.append((str(rank), share, n))

    occ.executemany("UPDATE occurrence SET sense=?, sense_conf=?, sense_source='macula-embed' "
                    "WHERE node=?", updates)
    occ.commit()
    occ.close()

    inv_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["lex", "stem", "sense", "gloss", "count", "share"])
        w.writerows(inv_rows)
    print(f"merged senses {merged_from} → {merged_to} (thresh {thresh}); "
          f"wrote {OUT.relative_to(OCC.parent.parent.parent)}: {len(inv_rows)} senses", file=sys.stderr)


if __name__ == "__main__":
    main()
