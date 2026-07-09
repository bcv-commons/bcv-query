#!/usr/bin/env python3
"""Build the CC0 semantic-neighbors pack — internal-docs/semantic-neighbors-pack.md.

Re-derives lexeme semantic proximity from CLEAN sources — a CC0 stand-in for the NC Louw-Nida/SDBH
domains, never touching the MARBLE taxonomy as an input. Hebrew/OT (the context embeddings are
Hebrew clauses). Anchor = MACULA `lexeme` (CC-BY, homograph-precise).

Signals (merged into a consensus):
  emb   — mean bge-m3 embedding of a lexeme's occurrence CLAUSES (distributional neighbors)   [primary]
  lxx   — two Hebrew lexemes the LXX renders into the SAME Greek Strong's (lxx_bridge.tsv)     [corroborate]
  gloss — lexemes whose English glosses share content words                                    [corroborate]

Output: resources/semantic_neighbors/neighbors.parquet (lexeme, neighbor_lexeme, score, sources) + a
manifest.json. CC0 (public texts + open model + CC-BY tables). The NC domains are used ONLY as an
internal yardstick (--validate), never as an input or an output.

  python -m macula.build_semantic_neighbors --validate
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE = HERE / "lexeme-spine.db"
BRIDGE = HERE / "bhsa-macula-bridge.db"
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
EMB = ROOT / "resources" / "occurrences" / "context_emb.npz"
LXX = ROOT / "resources" / "lxx_bridge.tsv"
DOMAINS = ROOT / "resources" / "semantic_domains" / "hbo.tsv"
OUT_DIR = ROOT / "resources" / "semantic_neighbors"
LLM_EDGES = OUT_DIR / "llm_edges.tsv"        # method=llm layer (bcv-RAG/scripts/build_llm_neighbors.py)

MIN_OCC = 3        # a lexeme needs this many clause vectors for a stable centroid
TOPK = 10          # neighbors kept per lexeme
MIN_COS = 0.30     # cosine floor (post mean-centering scale)
_STOP = set("the a an of to and in be is was were for from with his her its their this that "
            "he she it they them who which what will would shall not no".split())


def lexeme_vectors():
    """MACULA lexeme -> (unit centroid, strong, top gloss). Content lexemes with >= MIN_OCC clauses."""
    z = np.load(EMB, allow_pickle=True)
    V, C = z["vectors"], z["contexts"]                     # load each array ONCE (npz re-decompresses per access)
    clause_vec = {c: V[i] for i, c in enumerate(C)}        # clause text -> vector

    sp = sqlite3.connect(f"file:{SPINE}?mode=ro", uri=True)
    key2lex = {k: (lx, s) for k, lx, s, ic in sp.execute(
        "SELECT key, lexeme, strong, is_content FROM spine_words WHERE is_content=1 AND lexeme IS NOT NULL")}
    br = sqlite3.connect(f"file:{BRIDGE}?mode=ro", uri=True)
    node2lex = {}
    for node, key in br.execute("SELECT node, key FROM bridge"):
        if key in key2lex:
            node2lex[node] = key2lex[key]

    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    acc: dict = collections.defaultdict(lambda: [np.zeros(1024, np.float32), 0])
    strong_of, gloss_ct = {}, collections.defaultdict(collections.Counter)
    for node, context, gloss in hbo.execute("SELECT node, context, gloss FROM occurrence"):
        lx = node2lex.get(node)
        v = clause_vec.get(context)
        if lx is None or v is None:
            continue
        lexeme, strong = lx
        acc[lexeme][0] += v
        acc[lexeme][1] += 1
        strong_of[lexeme] = strong
        if gloss:
            gloss_ct[lexeme][gloss] += 1

    lexemes, mat, meta = [], [], {}
    for lexeme, (vsum, n) in acc.items():
        if n < MIN_OCC:
            continue
        c = vsum / n
        norm = np.linalg.norm(c)
        if norm == 0:
            continue
        lexemes.append(lexeme)
        mat.append(c / norm)
        top_gloss = gloss_ct[lexeme].most_common(1)[0][0] if gloss_ct[lexeme] else ""
        s = strong_of[lexeme]
        meta[lexeme] = (f"H{s:04d}" if s is not None else "", top_gloss)   # H#### to join lxx/domains
    return lexemes, np.vstack(mat).astype(np.float32), meta


def _gloss_tokens(g: str) -> set:
    return {w for w in re.findall(r"[a-z]+", (g or "").lower()) if w not in _STOP and len(w) > 2}


def build(validate: bool, llm_edges=None):
    lexemes, M, meta = lexeme_vectors()
    print(f"[neighbors] {len(lexemes)} content lexemes with >= {MIN_OCC} clauses", file=sys.stderr)
    # Mean-center to kill embedding anisotropy: clause centroids all lean toward one "generic biblical
    # clause" direction, which makes everything ~0.94 cosine. Subtracting the global mean removes that
    # shared component so the distinctive (word-meaning) directions dominate the kNN. Then re-normalize.
    M = M - M.mean(axis=0, keepdims=True)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)

    # LXX corroboration: Hebrew lexemes sharing a Greek Strong's (same-rendering) are near.
    greek_share: dict = collections.defaultdict(set)   # greek strong -> {hebrew lexeme}
    if LXX.exists():
        strong2lex = collections.defaultdict(list)
        for lx, (s, _) in meta.items():
            strong2lex[s].append(lx)
        for line in LXX.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 2:
                for lx in strong2lex.get(p[0].strip(), []):     # hebrew_strong is already "H####"
                    greek_share[p[1]].add(lx)
    lxx_pairs = set()
    for _, lxs in greek_share.items():
        lxs = list(lxs)
        for i in range(len(lxs)):
            for j in range(i + 1, len(lxs)):
                lxx_pairs.add(frozenset((lxs[i], lxs[j])))

    gloss_tok = {lx: _gloss_tokens(g) for lx, (_, g) in meta.items()}

    # method=llm layer (scholarly prior): strong-level syn/ant edges. Tier by AGREEMENT with the
    # empirical embedding signal — the LLM supplies synonymy the distributional signal can't, the
    # embedding grounds the LLM and catches hallucination. Keep them independent; agreement = trust.
    syn, ant = _load_llm_edges(llm_edges)
    strong2lex = collections.defaultdict(list)
    for lx, (s, _) in meta.items():
        strong2lex[s].append(lx)

    # embedding kNN (cosine = dot of unit vectors) — tiered against the LLM prior
    rows, emb_pairs = [], set()
    for i, lx in enumerate(lexemes):
        sims = M @ M[i]
        sims[i] = -1
        top = np.argpartition(-sims, TOPK)[:TOPK]
        for j in top[np.argsort(-sims[top])]:
            cos = float(sims[j])
            if cos < MIN_COS:
                continue
            nb = lexemes[j]
            sources, score = ["emb"], cos
            if frozenset((lx, nb)) in lxx_pairs:
                sources.append("lxx"); score = min(1.0, score + 0.1)
            if gloss_tok[lx] and gloss_tok[lx] & gloss_tok.get(nb, set()):
                sources.append("gloss"); score = min(1.0, score + 0.1)
            pair = frozenset((meta[lx][0], meta[nb][0]))         # strong-level
            relation, conf = "similar", "recall"
            if pair in ant:                                      # LLM says OPPOSITE — emb false positive
                relation = "antonym"
            elif pair in syn:                                    # LLM + embedding AGREE
                sources.append("llm"); conf = "high"; score = min(1.0, score + 0.15)
            rows.append((lx, nb, round(score, 4), "|".join(sources), conf, relation))
            emb_pairs.add(frozenset((lx, nb)))

    # LLM-only PRIOR edges — synonymy the LLM asserts but the embedding didn't surface (added coverage,
    # lower trust). Map strong->lexeme(s); skip pairs the embedding already produced.
    for pair in syn:
        a, b = tuple(pair) if len(pair) == 2 else (None, None)
        if not a:
            continue
        for lx in strong2lex.get(a, []):
            for nb in strong2lex.get(b, []):
                if lx != nb and frozenset((lx, nb)) not in emb_pairs:
                    rows.append((lx, nb, 0.5, "llm", "prior", "similar"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa, pyarrow.parquet as pq
    c = list(zip(*rows)) if rows else ([], [], [], [], [], [])
    dest = OUT_DIR / "neighbors.parquet"
    pq.write_table(pa.table({"lexeme": pa.array(c[0], pa.string()),
                             "neighbor_lexeme": pa.array(c[1], pa.string()),
                             "score": pa.array(c[2], pa.float32()),
                             "sources": pa.array(c[3], pa.string()),
                             "confidence": pa.array(c[4], pa.string()),   # high | recall | prior
                             "relation": pa.array(c[5], pa.string())}),   # similar | antonym
                   dest, compression="zstd")
    tier = collections.Counter(r[4] for r in rows)
    manifest = {
        "dataset": "semantic_neighbors", "anchor": "MACULA lexeme (CC-BY)", "testament": "OT/Hebrew",
        "license": "CC0-1.0",
        "signals": ["emb:bge-m3 clause centroids", "lxx:shared-greek", "gloss:overlap", "llm:scholarly-prior"],
        "confidence_tiers": {"high": tier["high"], "recall": tier["recall"], "prior": tier["prior"]},
        "lexemes": len(lexemes), "edges": len(rows), "topk": TOPK, "min_cos": MIN_COS, "min_occ": MIN_OCC,
        "content_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "note": "high = LLM prior + empirical embedding agree. NC domains used only as internal yardstick.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"[neighbors] {len(rows)} edges (high={tier['high']} recall={tier['recall']} "
          f"prior={tier['prior']}) -> {dest}", file=sys.stderr)

    if validate:
        _validate(rows, meta)
    return manifest


def _load_llm_edges(path):
    """(syn, ant): sets of frozenset({H_a, H_b}) — undirected strong-level relations from the LLM layer."""
    syn, ant = set(), set()
    if path and Path(path).exists():
        for ln in Path(path).read_text(encoding="utf-8").splitlines():
            if ln.startswith("#") or ln.startswith("target"):
                continue
            p = ln.split("\t")
            if len(p) >= 3 and p[0].strip() != p[2].strip():
                (syn if p[1].strip() == "syn" else ant).add(frozenset((p[0].strip(), p[2].strip())))
    return syn, ant


def _validate(rows, meta):
    """Internal yardstick ONLY: do derived neighbors land in the same NC domain? (never published)."""
    if not DOMAINS.exists():
        print("[validate] no domains table", file=sys.stderr); return
    dom = collections.defaultdict(set)
    for line in DOMAINS.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 3:
            dom[p[0]].add(p[2])           # strong -> {domain codes}
    def rate(pred):
        same = tot = 0
        for r in rows:
            lx, nb, relation = r[0], r[1], r[5]
            if relation == "antonym" or not pred(r):
                continue
            ds, dn = dom.get(meta[lx][0], set()), dom.get(meta.get(nb, ("", ""))[0], set())
            if ds and dn:
                tot += 1; same += bool(ds & dn)
        return same, tot
    for name, pred in (("all-similar", lambda r: True),
                       ("high-conf", lambda r: r[4] == "high"),
                       ("prior-only", lambda r: r[4] == "prior")):
        s, t = rate(pred)
        if t:
            print(f"[validate] {name}: {s}/{t} share >=1 NC domain = {100*s/t:.1f}%  (yardstick)",
                  file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Build the CC0 semantic-neighbors pack.")
    ap.add_argument("--validate", action="store_true", help="score vs NC domains (internal yardstick)")
    ap.add_argument("--llm-edges", type=Path, default=LLM_EDGES if LLM_EDGES.exists() else None,
                    help="method=llm syn/ant edges to tier against (default: semantic_neighbors/llm_edges.tsv)")
    a = ap.parse_args()
    build(a.validate, a.llm_edges)


if __name__ == "__main__":
    main()
