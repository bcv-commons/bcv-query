#!/usr/bin/env python3
"""Discriminating spine ablation — word-study / original-language precision.

The easy thematic ablation (spine.ablation) saturated: the production model
already nails distinct-verse retrieval, incl. cross-lingual. This tests the
spine where it *might* matter — distinguishing original-language words that
English collapses (bara/yatsar/asah/banah all "create/make/form/build").

Arms: body / prefix (code+gloss) / gloss_only / hebrew_lemma / lemma_gloss.
The lemma arms (ARM A) anchor on the original word in its *own* distributional
space — the modern (naive-stripped) form the model actually knows — testing
whether a non-redundant original-language signal beats English glosses (which
merely duplicate the English body). Arm B (ktiv-male / monotonic normalization)
is the planned refinement if arm A shows signal — see common.to_modern_form.

Two measures, across all arms:

1. CLUSTERING (query-free, the purest test): do verses sharing a target
   Strong's cluster tighter? separation = mean(within-group sim) -
   mean(across-group sim). If the prefix raises separation, it groups
   same-original-word content better — exactly its design goal.

2. WORD-STUDY QUERIES: a sense-specific query should rank that word's verses
   top (precision@5 / MRR). English blurs these; the prefix's code+gloss may not.

Corpus verses come from spine.db (which carries each verse's Strong's);
English bodies are the ULT (alignment markup stripped).

Run (set the model to match production):
  BTMCP_EMBEDDING_MODEL=voyage-3-large VOYAGE_API_KEY=... \
    ../bcv-corpus/.venv/bin/python -m spine.ablation_wordstudy
"""
from __future__ import annotations

import math
import re
import sqlite3
import sys
from pathlib import Path

import httpx

# Historical reproduction only: this concluded ablation measured the spine
# prefix against bcv-RAG's production Voyage stack. To re-run, put bcv-RAG on
# PYTHONPATH so `indexer.embed` resolves (e.g. PYTHONPATH=.:../bcv-RAG).
from indexer.embed import EMBEDDING_MODEL, PROVIDER, embed_texts
from references import encode
from spine.common import FILENUM
from spine.prefix import PrefixBuilder

HERE = Path(__file__).resolve().parent
SPINE_DB = HERE / "spine.db"
ULT_URL = "https://git.door43.org/unfoldingWord/en_ult/raw/branch/master/{nn:02d}-{code}.usfm"

# Confusable Hebrew "make/create" family (English renders them overlapping)
TARGETS = {
    1254: "bara — create (esp. out of nothing, divine)",
    3335: "yatsar — form, fashion (like a potter)",
    1129: "banah — build (a structure)",
    6213: "asah — make, do (general)",
}
BOOKS = ["GEN", "ISA", "JER"]          # rich in these verbs
PER_WORD = 12                           # corpus cap per target word

# Sense-specific word-study queries -> the target Strong's whose verses are "relevant"
QUERIES = [
    ("to create something entirely new out of nothing", 1254),
    ("créer quelque chose de nouveau à partir de rien", 1254),   # cross-lingual
    ("to form and fashion like a potter shaping clay", 3335),
    ("to build a house or a structure", 1129),
    ("to make or do, to carry out an action", 6213),
]


def strip_ult(usfm: str) -> dict[tuple[int, int], str]:
    """ULT USFM -> {(ch,v): plain English text}."""
    usfm = re.sub(r"\\zaln-[se]\s?\|?[^\\]*?\\\*", "", usfm)    # alignment milestones
    usfm = re.sub(r"\\f\s.*?\\f\*", "", usfm, flags=re.DOTALL)  # footnotes
    usfm = re.sub(r"\\x\s.*?\\x\*", "", usfm, flags=re.DOTALL)  # xrefs
    usfm = re.sub(r"\\w ([^|\\]*)\|[^\\]*?\\w\*", r"\1", usfm)  # \w word|...\w* -> word
    out: dict[tuple[int, int], list[str]] = {}
    ch = 0
    cur: tuple[int, int] | None = None
    for m in re.finditer(r"\\c (\d+)|\\v (\d+)|\\[+a-z0-9-]+\*?|([^\\]+)", usfm):
        if m.group(1):
            ch = int(m.group(1)); cur = None
        elif m.group(2):
            cur = (ch, int(m.group(2))); out[cur] = []
        elif m.group(3) is not None and cur:
            out[cur].append(m.group(3))
    return {k: re.sub(r"\s+", " ", "".join(parts)).strip() for k, parts in out.items()}


def build_corpus(db) -> list[tuple[str, int, int, int]]:
    """[(code, ch, v, target_strong)] — verses containing **exactly one** target word
    (unambiguous group membership), capped per word."""
    verse_targets: dict[tuple[str, int, int], set[int]] = {}
    for code in BOOKS:
        for strong in TARGETS:
            for ch, v in db.execute(
                "SELECT DISTINCT chapter, verse FROM spine_words "
                "WHERE book=? AND strong=? AND is_content=1",
                (code, strong),
            ):
                verse_targets.setdefault((code, ch, v), set()).add(strong)
    by_word: dict[int, list] = {s: [] for s in TARGETS}
    for (code, ch, v), tgts in sorted(verse_targets.items()):
        if len(tgts) == 1:
            s = next(iter(tgts))
            by_word[s].append((code, ch, v, s))
    corpus = []
    for s, lst in by_word.items():
        corpus.extend(lst[:PER_WORD])
    return corpus


def cosine(a, b):
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def main():
    print(f"embedding model: {EMBEDDING_MODEL} ({PROVIDER})\n", file=sys.stderr)
    db = sqlite3.connect(f"file:{SPINE_DB}?mode=ro", uri=True)
    pb = PrefixBuilder()

    corpus = build_corpus(db)
    # fetch ULT bodies
    bodies: dict[tuple[str, int, int], str] = {}
    for code in BOOKS:
        txt = httpx.get(ULT_URL.format(nn=FILENUM[code], code=code), timeout=120, follow_redirects=True).text
        for (ch, v), body in strip_ult(txt).items():
            bodies[(code, ch, v)] = body
    corpus = [c for c in corpus if bodies.get((c[0], c[1], c[2]))]
    print(f"corpus: {len(corpus)} verses across {len(TARGETS)} target words", file=sys.stderr)

    # input variants: body + four prefix styles (incl. the original-language arms)
    STYLE = {
        "prefix": "code_gloss",          # English code+gloss (already tested)
        "gloss_only": "gloss",           # English gloss only
        "hebrew_lemma": "lemma",         # ARM A: original-language lemma (modern form)
        "lemma_gloss": "lemma_gloss",    # hybrid: lemma + English handle
    }
    variants = {"body": []}
    for name in STYLE:
        variants[name] = []
    for code, ch, v, _s in corpus:
        e = encode(code, ch, v)
        body = bodies[(code, ch, v)]
        variants["body"].append(body)
        for name, style in STYLE.items():
            pfx = pb.build([(e, e)], style=style)
            variants[name].append(f"{pfx}\n{body}" if pfx else body)

    qvecs = embed_texts([q for q, _ in QUERIES], input_type="query")
    groups = [s for *_, s in corpus]

    print(f"{'variant':12s} {'separation':>11s}   {'query P@5':>9s} {'query MRR':>9s}  (sep = within−across group sim)")
    for name, docs in variants.items():
        dv = embed_texts(docs, input_type="document")
        # (1) clustering separation
        within = across = wn = an = 0.0
        for i in range(len(dv)):
            for j in range(i + 1, len(dv)):
                s = cosine(dv[i], dv[j])
                if groups[i] == groups[j]:
                    within += s; wn += 1
                else:
                    across += s; an += 1
        sep = (within / wn) - (across / an)
        # (2) word-study queries
        p5s, mrrs = [], []
        for (q, tgt), qv in zip(QUERIES, qvecs):
            order = sorted(range(len(dv)), key=lambda k: cosine(qv, dv[k]), reverse=True)
            rel = [k for k in order if groups[k] == tgt]
            top5 = order[:5]
            p5s.append(sum(1 for k in top5 if groups[k] == tgt) / 5)
            first = next((rank for rank, k in enumerate(order, 1) if groups[k] == tgt), None)
            mrrs.append(1 / first if first else 0)
        print(f"{name:12s} {sep:11.4f}   {sum(p5s)/len(p5s):9.3f} {sum(mrrs)/len(mrrs):9.3f}")


if __name__ == "__main__":
    main()
