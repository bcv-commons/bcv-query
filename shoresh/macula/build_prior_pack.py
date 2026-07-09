#!/usr/bin/env python3
"""Build the language-independent prior pack — internal-docs/prior-pack.md.

One row per ORIGINAL lexeme, bundling the shoresh-owned signals the aligner's gloss/neural runs consume
as priors: keyness (function-word filter), LXX cross-testament bridge, sense inventory, and the
semantic-neighbors pack. Keyed on the MACULA lexeme → one build serves every target language.

  python -m macula.build_prior_pack        # -> resources/prior_pack/prior_pack.parquet + manifest.json
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
KEYNESS = ROOT / "resources" / "strongs_keyness.tsv"
LXX = ROOT / "resources" / "lxx_bridge.tsv"
NEIGHBORS = ROOT / "resources" / "semantic_neighbors" / "neighbors.parquet"
OUT_DIR = ROOT / "resources" / "prior_pack"


def build():
    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)

    # 1. distinct lexemes (representative strong/lemma/is_content); testament from the lang prefix
    info = {}
    for lexeme, strong, lemma, isc in sp.execute(
            "SELECT lexeme, strong, lemma, is_content FROM spine_words "
            "WHERE lexeme IS NOT NULL GROUP BY lexeme"):
        t = "NT" if lexeme.startswith("grc:") else "OT"
        hstrong = (f"{'G' if t=='NT' else 'H'}{int(strong):04d}") if strong is not None else None
        info[lexeme] = {"strong": hstrong, "lemma": lemma or "", "is_content": bool(isc), "testament": t}

    # 2. sense inventory per lexeme: [(stem, sense, share)] over sensed occurrences
    sense_ct = collections.defaultdict(collections.Counter)
    for lexeme, stem, sense in sp.execute(
            "SELECT lexeme, stem, sense FROM spine_words WHERE sense IS NOT NULL AND sense != ''"):
        sense_ct[lexeme][(stem or "", sense)] += 1

    # 3. keyness: strong -> weight
    keyness = {}
    if KEYNESS.exists():
        for ln in KEYNESS.read_text(encoding="utf-8").splitlines()[1:]:
            p = ln.split("\t")
            if len(p) >= 2:
                try:
                    keyness[p[0]] = float(p[1])
                except ValueError:
                    pass

    # 4. LXX bridge: H->[G] and G->[H], frequency-ordered
    h2g, g2h = collections.defaultdict(list), collections.defaultdict(list)
    if LXX.exists():
        for ln in LXX.read_text(encoding="utf-8").splitlines()[1:]:
            p = ln.split("\t")
            if len(p) >= 3:
                c = int(p[2]) if p[2].isdigit() else 1
                h2g[p[0].strip()].append((p[1].strip(), c))
                g2h[p[1].strip()].append((p[0].strip(), c))
    order = lambda pairs: [s for s, _ in sorted(pairs, key=lambda x: -x[1])]

    # 5. neighbors: lexeme -> [{lexeme, score, relation, confidence}]
    nb = collections.defaultdict(list)
    if NEIGHBORS.exists():
        for r in pq.read_table(NEIGHBORS).to_pylist():
            nb[r["lexeme"]].append({"lexeme": r["neighbor_lexeme"], "score": float(r["score"]),
                                    "relation": r["relation"], "confidence": r["confidence"]})

    # 6. assemble
    rows = []
    for lexeme, d in info.items():
        s = d["strong"]
        senses = []
        tot = sum(sense_ct[lexeme].values())
        for (stem, sense), c in sense_ct[lexeme].most_common():
            senses.append({"stem": stem, "sense": sense, "share": round(c / tot, 4)})
        rows.append({
            "lexeme": lexeme, "strong": s, "testament": d["testament"],
            "is_content": d["is_content"], "lemma": d["lemma"],
            "keyness": keyness.get(s),
            "lxx_greek": order(h2g.get(s, [])) if d["testament"] == "OT" else [],
            "lxx_hebrew": order(g2h.get(s, [])) if d["testament"] == "NT" else [],
            "senses": senses,
            "neighbors": sorted(nb.get(lexeme, []), key=lambda x: -x["score"]),
        })

    sense_struct = pa.list_(pa.struct([("stem", pa.string()), ("sense", pa.string()),
                                       ("share", pa.float32())]))
    nb_struct = pa.list_(pa.struct([("lexeme", pa.string()), ("score", pa.float32()),
                                    ("relation", pa.string()), ("confidence", pa.string())]))
    table = pa.table({
        "lexeme": pa.array([r["lexeme"] for r in rows], pa.string()),
        "strong": pa.array([r["strong"] for r in rows], pa.string()),
        "testament": pa.array([r["testament"] for r in rows], pa.string()),
        "is_content": pa.array([r["is_content"] for r in rows], pa.bool_()),
        "lemma": pa.array([r["lemma"] for r in rows], pa.string()),
        "keyness": pa.array([r["keyness"] for r in rows], pa.float32()),
        "lxx_greek": pa.array([r["lxx_greek"] for r in rows], pa.list_(pa.string())),
        "lxx_hebrew": pa.array([r["lxx_hebrew"] for r in rows], pa.list_(pa.string())),
        "senses": pa.array([r["senses"] for r in rows], sense_struct),
        "neighbors": pa.array([r["neighbors"] for r in rows], nb_struct),
    })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / "prior_pack.parquet"
    pq.write_table(table, dest, compression="zstd")

    def _sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    manifest = {
        "dataset": "prior_pack", "anchor": "MACULA lexeme (CC-BY)", "license": "CC-BY-4.0",
        "rows": len(rows),
        "with_keyness": sum(1 for r in rows if r["keyness"] is not None),
        "with_lxx": sum(1 for r in rows if r["lxx_greek"] or r["lxx_hebrew"]),
        "with_senses": sum(1 for r in rows if r["senses"]),
        "with_neighbors": sum(1 for r in rows if r["neighbors"]),
        "components": {
            "keyness_sha256": _sha(KEYNESS), "lxx_bridge_sha256": _sha(LXX),
            "neighbors_sha256": _sha(NEIGHBORS), "spine_sha256": _sha(SPINE),
        },
        "content_sha256": _sha(dest),
        "note": "language-independent; CC-BY (MACULA lexeme + lxx_bridge); label-free (no MARBLE).",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"prior_pack: {len(rows)} lexemes -> {dest}")
    print(f"  keyness {manifest['with_keyness']} · lxx {manifest['with_lxx']} · "
          f"senses {manifest['with_senses']} · neighbors {manifest['with_neighbors']}")
    return manifest


if __name__ == "__main__":
    build()
