#!/usr/bin/env python3
"""Embedding measurement spike — does an original-language model represent the
original-language text better than a multilingual baseline?

  Plan A (--config greek):  SPhilBERTa vs multilingual-E5 over LXX Greek (lxx.db)
  Plan C (--config hebrew): BEREL_3.0  vs multilingual-E5 over the Hebrew spine
                            (spine.db) — a config swap + a mean-pool wrapper.

Ground truth = Strong's, over confusable word-families that English collapses
but the original distinguishes (the create/make family: bara/asah/yatsar/banah
in Hebrew, poieō/ktizō/plassō/oikodomeō in Greek). Two metrics:

1. SEPARATION (primary, query-free): mean(within-sense cosine) −
   mean(across-sense cosine). Higher = same-original-word verses cluster
   tighter. Needs no query, so it is fair to monolingual models (BEREL).
2. WORD-STUDY RETRIEVAL (secondary): a sense query → P@5 / MRR for that sense's
   verses. Needs a query in a language the model accepts (English works for
   SPhilBERTa/E5; for the Hebrew/BEREL arm queries must be Hebrew or skipped).

Win condition: the original-language model shows materially higher separation
than E5 over the *same* original-language text → it earns its infra.

Runs locally on CPU (models are ~0.1–0.3B; corpus is small). Deps:
    pip install -r embed_eval/requirements.txt
    PYTHONPATH=. python -m embed_eval.spike --config greek
    PYTHONPATH=. python -m embed_eval.spike --config greek --corpus-only  # no models
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from spine.common import to_modern_form

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LXX_DB = ROOT / "lxx" / "lxx.db"
SPINE_DB = ROOT / "spine" / "spine.db"


# ───────────────────────── embedders (lazy imports) ─────────────────────────

class STEmbedder:
    """sentence-transformers model (drop-in: SPhilBERTa, E5)."""

    def __init__(self, model_id: str, query_prefix: str = "", doc_prefix: str = ""):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_id)
        self.qp, self.dp = query_prefix, doc_prefix

    def encode(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        pre = self.qp if kind == "query" else self.dp
        vecs = self.model.encode([pre + t for t in texts], normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]


class PooledEncoder:
    """Masked-LM encoder + mean pooling (for BEREL and other non-ST encoders)."""

    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id)
        self.model.eval()

    def encode(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        torch = self.torch
        out: list[list[float]] = []
        with torch.no_grad():
            for i in range(0, len(texts), 32):
                batch = texts[i:i + 32]
                enc = self.tok(batch, padding=True, truncation=True,
                               max_length=128, return_tensors="pt")
                hidden = self.model(**enc).last_hidden_state          # (B, T, H)
                mask = enc["attention_mask"].unsqueeze(-1).float()    # (B, T, 1)
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                pooled = torch.nn.functional.normalize(pooled, dim=1)
                out.extend(pooled.tolist())
        return out


# ─────────────────────────────── configs ───────────────────────────────────

CONFIGS = {
    "greek": {
        "db": LXX_DB,
        "table": "lxx_words",
        "word_text": lambda r: r["plain"],          # already monotonic/de-accented
        "targets": {
            4160: "poieō — make/do (general)",
            2936: "ktizō — create",
            4111: "plassō — form, mould",
            3618: "oikodomeō — build",
        },
        "queries": [
            ("to make or do, to carry out an action", 4160),
            ("to create something entirely new", 2936),
            ("to form and mould like a potter shaping clay", 4111),
            ("to build a house or a structure", 3618),
        ],
        "arms": {
            "sphilberta": lambda: STEmbedder("bowphs/SPhilBerta"),
            "e5": lambda: STEmbedder("intfloat/multilingual-e5-base",
                                     "query: ", "passage: "),
        },
    },
    "hebrew": {                                      # Plan C — config swap
        "db": SPINE_DB,
        "table": "spine_words",
        "word_text": lambda r: to_modern_form(r["surface"], "hbo"),  # unpointed
        "targets": {
            1254: "bara — create",
            6213: "asah — make/do",
            3335: "yatsar — form",
            1129: "banah — build",
        },
        "queries": [],                              # monolingual: rely on separation
        "arms": {
            "berel": lambda: PooledEncoder("dicta-il/BEREL_3.0"),
            "e5": lambda: STEmbedder("intfloat/multilingual-e5-base",
                                     "query: ", "passage: "),
        },
    },
}


# ─────────────────────────────── corpus ────────────────────────────────────

def build_corpus(db, cfg, per_word: int):
    """[(book, ch, v, target_strong, verse_text)] — verses with EXACTLY ONE
    target word (unambiguous sense), capped per word."""
    table, targets, word_text = cfg["table"], cfg["targets"], cfg["word_text"]
    db.row_factory = sqlite3.Row
    verse_targets: dict[tuple, set] = {}
    for strong in targets:
        for r in db.execute(
            f"SELECT DISTINCT book, chapter, verse FROM {table} "
            f"WHERE strong=? AND is_content=1", (strong,)):
            verse_targets.setdefault((r["book"], r["chapter"], r["verse"]), set()).add(strong)

    by_word: dict[int, list] = {s: [] for s in targets}
    for (book, ch, v), tgts in sorted(verse_targets.items()):
        if len(tgts) == 1:
            by_word[next(iter(tgts))].append((book, ch, v))

    corpus = []
    for strong, verses in by_word.items():
        for (book, ch, v) in verses[:per_word]:
            rows = db.execute(
                f"SELECT * FROM {table} WHERE book=? AND chapter=? AND verse=? ORDER BY idx",
                (book, ch, v)).fetchall()
            text = " ".join(word_text(r) for r in rows if word_text(r)).strip()
            if text:
                corpus.append((book, ch, v, strong, text))
    return corpus


# ─────────────────────────────── metrics ───────────────────────────────────

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def separation(vecs, groups):
    within = across = wn = an = 0.0
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            s = _dot(vecs[i], vecs[j])
            if groups[i] == groups[j]:
                within += s; wn += 1
            else:
                across += s; an += 1
    return (within / wn if wn else 0) - (across / an if an else 0)


def retrieval(arm, docs, groups, queries):
    if not queries:
        return None, None
    qvecs = arm.encode([q for q, _ in queries], kind="query")
    dvecs = arm.encode(docs, kind="document")
    p5s, mrrs = [], []
    for (q, tgt), qv in zip(queries, qvecs):
        order = sorted(range(len(dvecs)), key=lambda k: _dot(qv, dvecs[k]), reverse=True)
        p5s.append(sum(1 for k in order[:5] if groups[k] == tgt) / 5)
        first = next((rank for rank, k in enumerate(order, 1) if groups[k] == tgt), None)
        mrrs.append(1 / first if first else 0)
    return sum(p5s) / len(p5s), sum(mrrs) / len(mrrs)


# ──────────────────────────────── main ─────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Original-language embedding spike")
    ap.add_argument("--config", choices=list(CONFIGS), default="greek")
    ap.add_argument("--per-word", type=int, default=15)
    ap.add_argument("--arms", nargs="+", help="subset of arm names to run")
    ap.add_argument("--corpus-only", action="store_true",
                    help="build + print the corpus without loading any model")
    args = ap.parse_args()

    cfg = CONFIGS[args.config]
    if not cfg["db"].exists():
        sys.exit(f"missing {cfg['db']} — build it first "
                 f"(lxx.parse --all / spine.parse)")
    db = sqlite3.connect(f"file:{cfg['db']}?mode=ro", uri=True)
    corpus = build_corpus(db, cfg, args.per_word)
    groups = [s for *_, s, _ in corpus]
    docs = [t for *_, t in corpus]

    print(f"config: {args.config} · corpus: {len(corpus)} verses · "
          f"{len(cfg['targets'])} target words", file=sys.stderr)
    by = {}
    for *_, s, _ in corpus:
        by[s] = by.get(s, 0) + 1
    prefix = "G" if args.config == "greek" else "H"
    for s, g in cfg["targets"].items():
        print(f"  {prefix}{s:<5} {g:32} {by.get(s, 0):>3} verses", file=sys.stderr)
    if corpus:
        b, c, v, s, t = corpus[0]
        print(f"  sample [{b} {c}:{v} · target {s}]: {t[:80]}", file=sys.stderr)

    if args.corpus_only:
        return

    arm_names = args.arms or list(cfg["arms"])
    print(f"\n{'arm':14} {'separation':>11} {'P@5':>7} {'MRR':>7}   "
          f"(sep = within−across group cosine)")
    for name in arm_names:
        arm = cfg["arms"][name]()
        dvecs = arm.encode(docs, kind="document")
        sep = separation(dvecs, groups)
        p5, mrr = retrieval(arm, docs, groups, cfg["queries"])
        p5s = f"{p5:7.3f}" if p5 is not None else "   n/a "
        mrrs = f"{mrr:7.3f}" if mrr is not None else "   n/a "
        print(f"{name:14} {sep:11.4f} {p5s} {mrrs}")


if __name__ == "__main__":
    main()
