#!/usr/bin/env python3
"""Spine ablation — does the original-language prefix improve retrieval?

Embeds a small curated verse corpus three ways and measures how well each
query retrieves its target verse:

  body            the verse text only (baseline)
  prefix          spine prefix (code+gloss) + body
  gloss_only      spine prefix (gloss only) + body

Some corpus verses carry FOREIGN-LANGUAGE bodies (fr/es) so that an English
query can only reach them through the spine's shared Strong's+English-gloss
anchors — the cross-lingual test (the headline goal).

Uses the project's configured embedding model (set it to match production):
    BTMCP_EMBEDDING_MODEL=voyage-3-large VOYAGE_API_KEY=... python -m spine.ablation

Requires: spine/spine.db (build with `python -m spine.parse`).
"""
from __future__ import annotations

import os
import sys

# Historical reproduction only: this concluded ablation measured the spine
# prefix against bcv-RAG's production Voyage stack. To re-run, put bcv-RAG on
# PYTHONPATH so `indexer.embed` resolves (e.g. PYTHONPATH=.:../bcv-RAG).
from indexer.embed import EMBEDDING_MODEL, PROVIDER, embed_texts
from references import encode
from spine.prefix import PrefixBuilder

# (code, ch, v, body_lang, body)  — one language per verse (unambiguous targets)
CORPUS = [
    ("GEN", 1, 1, "fr", "Au commencement, Dieu créa les cieux et la terre."),
    ("GEN", 1, 3, "en", "And God said, Let there be light, and there was light."),
    ("GEN", 22, 8, "en", "Abraham said, God himself will provide the lamb for the burnt offering, my son."),
    ("EXO", 20, 3, "en", "You shall have no other gods before me."),
    ("PSA", 23, 1, "en", "The LORD is my shepherd; I shall not want."),
    ("PSA", 119, 105, "en", "Your word is a lamp to my feet and a light to my path."),
    ("PRO", 3, 5, "en", "Trust in the LORD with all your heart, and do not lean on your own understanding."),
    ("ISA", 53, 5, "en", "But he was pierced for our transgressions; he was crushed for our iniquities."),
    ("RUT", 1, 16, "en", "Where you go I will go; your people shall be my people, and your God my God."),
    ("JON", 1, 17, "en", "And the LORD appointed a great fish to swallow up Jonah."),
    ("JHN", 1, 1, "en", "In the beginning was the Word, and the Word was with God, and the Word was God."),
    ("JHN", 3, 16, "es", "Porque de tal manera amó Dios al mundo, que dio a su Hijo unigénito."),
    ("ROM", 3, 23, "en", "for all have sinned and fall short of the glory of God,"),
    ("ROM", 6, 23, "en", "For the wages of sin is death, but the free gift of God is eternal life."),
    ("ROM", 8, 28, "en", "And we know that for those who love God all things work together for good."),
    ("1CO", 13, 4, "fr", "L'amour est patient, il est plein de bonté; l'amour n'est point envieux."),
    ("1CO", 13, 13, "en", "So now faith, hope, and love abide, these three; but the greatest of these is love."),
    ("EPH", 2, 8, "en", "For by grace you have been saved through faith."),
    ("PHP", 4, 13, "en", "I can do all things through him who strengthens me."),
    ("MAT", 5, 9, "en", "Blessed are the peacemakers, for they shall be called sons of God."),
    ("HEB", 11, 1, "en", "Now faith is the assurance of things hoped for, the conviction of things not seen."),
    ("REV", 21, 4, "en", "He will wipe away every tear from their eyes, and death shall be no more."),
]

# (query, query_lang, target_code, target_ch, target_v).  X = cross-lingual (query lang != body lang)
QUERIES = [
    ("God created the heavens and the earth", "en", "GEN", 1, 1),          # X -> fr body
    ("création des cieux et de la terre par Dieu", "fr", "GEN", 1, 1),
    ("creación de los cielos y la tierra", "es", "GEN", 1, 1),             # X -> fr body
    ("let there be light", "en", "GEN", 1, 3),
    ("you shall have no other gods", "en", "EXO", 20, 3),
    ("the LORD is my shepherd", "en", "PSA", 23, 1),
    ("el Señor es mi pastor", "es", "PSA", 23, 1),                         # X -> en body
    ("the wages of sin is death", "en", "ROM", 6, 23),
    ("le salaire du péché est la mort", "fr", "ROM", 6, 23),              # X -> en body
    ("God so loved the world he gave his Son", "en", "JHN", 3, 16),       # X -> es body
    ("love is patient and kind", "en", "1CO", 13, 4),                     # X -> fr body
    ("faith hope and love the greatest is love", "en", "1CO", 13, 13),
    ("saved by grace through faith", "en", "EPH", 2, 8),
    ("foi espérance amour", "fr", "1CO", 13, 13),                         # X -> en body
    ("your people my people your God my God loyalty", "en", "RUT", 1, 16),
    ("a great fish swallowed the prophet", "en", "JON", 1, 17),
]


def cosine_ranks(qvecs, dvecs):
    import math
    def norm(v):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    dn = [norm(v) for v in dvecs]
    out = []
    for q in qvecs:
        qn = norm(q)
        sims = [sum(a * b for a, b in zip(qn, d)) for d in dn]
        out.append(sims)
    return out


def variants(pb: PrefixBuilder):
    inputs = {"body": [], "prefix": [], "gloss_only": []}
    for code, ch, v, _lang, body in CORPUS:
        e = encode(code, ch, v)
        pfx = pb.build([(e, e)], style="code_gloss")
        pfx_g = pb.build([(e, e)], style="gloss")
        inputs["body"].append(body)
        inputs["prefix"].append(f"{pfx}\n{body}" if pfx else body)
        inputs["gloss_only"].append(f"{pfx_g}\n{body}" if pfx_g else body)
    return inputs


def main():
    print(f"embedding model: {EMBEDDING_MODEL} (provider {PROVIDER})\n", file=sys.stderr)
    pb = PrefixBuilder()
    targets = [(c, ch, v) for c, ch, v, *_ in CORPUS]
    tgt_index = {t: i for i, t in enumerate(targets)}

    qvecs = embed_texts([q for q, *_ in QUERIES], input_type="query")
    inputs = variants(pb)

    results = {}
    for name, docs in inputs.items():
        dvecs = embed_texts(docs, input_type="document")
        sims = cosine_ranks(qvecs, dvecs)
        ranks = []
        for (q, qlang, tc, tch, tv), srow in zip(QUERIES, sims):
            ti = tgt_index[(tc, tch, tv)]
            order = sorted(range(len(srow)), key=lambda i: srow[i], reverse=True)
            rank = order.index(ti) + 1
            xling = qlang != CORPUS[ti][3]
            ranks.append((rank, xling))
        results[name] = ranks

    def summarize(ranks):
        mrr = sum(1 / r for r, _ in ranks) / len(ranks)
        r1 = sum(1 for r, _ in ranks if r == 1) / len(ranks)
        r3 = sum(1 for r, _ in ranks if r <= 3) / len(ranks)
        return mrr, r1, r3

    print(f"{'variant':12s} {'MRR':>6s} {'R@1':>6s} {'R@3':>6s}   (cross-lingual subset)")
    for name, ranks in results.items():
        mrr, r1, r3 = summarize(ranks)
        xl = [(r, x) for r, x in ranks if x]
        xmrr, xr1, xr3 = summarize(xl) if xl else (0, 0, 0)
        print(f"{name:12s} {mrr:6.3f} {r1:6.2f} {r3:6.2f}   X: MRR {xmrr:.3f} R@1 {xr1:.2f} R@3 {xr3:.2f}")

    print("\nper-query target rank (body / prefix / gloss_only):")
    for i, (q, qlang, tc, tch, tv) in enumerate(QUERIES):
        b = results["body"][i][0]; p = results["prefix"][i][0]; g = results["gloss_only"][i][0]
        x = "X" if results["body"][i][1] else " "
        flag = "  <-- prefix helps" if p < b else ("  <-- prefix hurts" if p > b else "")
        print(f"  [{x}] {qlang} {tc} {tch}:{tv:<3d} {q[:38]:38s} {b:2d}/{p:2d}/{g:2d}{flag}")


if __name__ == "__main__":
    main()
