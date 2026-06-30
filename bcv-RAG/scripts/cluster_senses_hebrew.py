#!/usr/bin/env python3
"""Phase 2+3 (Hebrew-anchored) — derive senses by clustering on HEBREW context, not English.

The sense-identity decision is made in the ORIGINAL: within each (lex, stem), group
occurrences by gloss, then MERGE groups whose Hebrew-clause embedding CENTROIDS are close
(single-linkage above a cosine threshold). So "are these the same sense?" is answered by how
the word is used in Hebrew; the English gloss is only the human-readable LABEL. Re-derives
from the stored anchor (occurrence.context + occurrence.gloss) + context_emb.npz — light and
re-tunable; the heavy embedding is embed_context.py.

  python3 bcv-RAG/scripts/cluster_senses_hebrew.py [--thresh 0.86]

Writes the same artifacts as build_lex_senses.py (sidecar sense column, source='hebrew-context';
hbo_lex.tsv), overwriting the English-gloss-derived placeholder.
"""
from __future__ import annotations

import collections
import csv
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_lex_senses import OCC, OUT, _norm   # noqa: E402
from merge_senses_embed import _cluster         # noqa: E402  single-linkage union-find

EMB = OCC.parent / "context_emb.npz"
ENGLISH = OCC.parent.parent.parent / "resources/word_glosses/hbo/English.csv"


def _clean(g: str) -> str:
    """Scrub MACULA interlinear formatting → a readable label: drop supplied [...] words,
    join dotted multi-word glosses with spaces."""
    g = re.sub(r"\[[^\]]*\]", "", g or "").replace(".", " ")
    return re.sub(r"\s+", " ", g).strip()


def _eng_perstem() -> dict:
    """{lex: {stem|'default': curated English gloss}} from the per-stem word_glosses CSV —
    the clean, curated label for the DOMINANT sense of each (lex, stem)."""
    out: dict = {}
    if not ENGLISH.exists():
        return out
    with ENGLISH.open(encoding="utf-8-sig", newline="") as fh:
        r = csv.reader(fh)
        cols = next(r)
        li = cols.index("lex")
        for row in r:
            if li < len(row) and row[li].strip():
                out[row[li].strip()] = {cols[i]: row[i].strip() for i in range(len(cols))
                                        if i < len(row) and cols[i] and row[i].strip()}
    return out


def main() -> None:
    argv = sys.argv[1:]
    thresh = float(argv[argv.index("--thresh") + 1]) if "--thresh" in argv else 0.88
    if not EMB.exists():
        sys.exit(f"no embeddings: {EMB} (run embed_context.py — the long batch — first)")

    d = np.load(EMB, allow_pickle=True)
    ctx_row = {c: i for i, c in enumerate(d["contexts"])}
    V = d["vectors"]

    occ = sqlite3.connect(OCC)
    rows = occ.execute("SELECT node, lex, stem, gloss, context FROM occurrence "
                       "WHERE gloss IS NOT NULL AND context != ''").fetchall()

    # per (lex,stem): gloss-bucket → occurrences (node + context row); plus raw gloss forms
    buckets: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    raw_form: dict = collections.defaultdict(collections.Counter)
    for node, lex, stem, gloss, ctx in rows:
        ng = _norm(gloss)
        ci = ctx_row.get(ctx)
        if ng and ci is not None:
            buckets[(lex, stem)][ng].append((node, ci))
            raw_form[(lex, stem, ng)][gloss] += 1

    eng = _eng_perstem()
    updates, inv_rows = [], []
    merged_from = merged_to = 0
    for (lex, stem), bg in buckets.items():
        names = list(bg)
        # Hebrew-context centroid per gloss-bucket (re-normalized mean of clause vectors)
        cent = {}
        for ng, occs in bg.items():
            m = V[[ci for _n, ci in occs]].mean(axis=0)
            nrm = np.linalg.norm(m)
            cent[ng] = m / nrm if nrm else m
        groups = _cluster(names, cent, thresh) if len(names) > 1 else [[names[0]]]
        merged_from += len(names)
        merged_to += len(groups)

        scored = []
        for g in groups:
            nodes = [n for ng in g for (n, _ci) in bg[ng]]
            scored.append((len(nodes), g, nodes))
        scored.sort(key=lambda s: -s[0])
        total = sum(s[0] for s in scored)
        for rank, (cnt, g, nodes) in enumerate(scored, 1):
            cc = collections.Counter()
            for ng in g:
                cc.update(raw_form[(lex, stem, ng)])
            canon = min(cc.items(), key=lambda kv: (kv[0].count("."), -kv[1]))[0]
            share = round(cnt / total, 3)
            # dominant sense → the curated per-stem gloss (clean, multilingual-ready);
            # sub-senses → scrubbed MACULA gloss.
            curated = eng.get(lex, {}).get(stem or "default")
            label = curated if (rank == 1 and curated) else _clean(canon)
            inv_rows.append((lex, stem, rank, label, cnt, share))
            for n in nodes:
                updates.append((str(rank), share, n))

    occ.executemany("UPDATE occurrence SET sense=?, sense_conf=?, sense_source='hebrew-context' "
                    "WHERE node=?", updates)
    occ.commit()
    occ.close()

    inv_rows.sort(key=lambda r: (r[0], r[1], r[2]))
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["lex", "stem", "sense", "gloss", "count", "share"])
        w.writerows(inv_rows)
    print(f"Hebrew-context merge: gloss-buckets {merged_from} → {merged_to} senses "
          f"(thresh {thresh}); wrote {OUT.relative_to(OCC.parent.parent.parent)}: {len(inv_rows)}")


if __name__ == "__main__":
    main()
