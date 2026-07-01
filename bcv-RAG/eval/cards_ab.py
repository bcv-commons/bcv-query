#!/usr/bin/env python3
"""Per-kind cards-on/off A/B — does each card KIND improve answers, judged by ITS OWN rubric?

Per the per-kind-strategy principle (internal-docs/roadmap.md), each kind is validated on its
own terms — concept by lexical grounding, speaker by attribution, entity by who/relation accuracy.
For each query: assemble the family, synthesize ONCE with the gated reference block and ONCE
without (same sources), and judge with the rubric of the kind that fired. Reports W/T/L per kind,
BLIND (A/B order randomized), neutral judge (OpenAI — a different provider from the Groq generator).

Run where shoresh + index + keys are wired:  python -m eval.cards_ab
Env: SHORESH_URL, GROQ_API_KEY+GROQ_MODEL (gen), OPENAI_API_KEY+OPENAI_MODEL (judge), INDEX_DB.
"""
from __future__ import annotations

import os
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETS = [REPO / "eval/set/v1.yaml", REPO / "eval/set/v2-expansion.yaml", REPO / "eval/set/denoise.yaml"]

# Each kind's judge rubric — what "better" MEANS for that kind (its own terms).
RUBRICS = {
    "concept": "grounded in the original-language (Hebrew/Greek) lexical facts — the correct sense "
               "of the key word, the right gloss / semantic domain",
    "speaker": "correctly attributes the words to the NAMED speaker, draws on their ACTUAL quoted "
               "words, and flags divine / red-letter speech where applicable",
    "entity":  "gets the ENTITY facts right — correct identity (who / what) and correct relations "
               "(parentage / genealogy: the right father, mother, spouse, child)",
    "passage": "grounded in the cited verse's ORIGINAL-LANGUAGE words — the actual Hebrew/Greek "
               "terms behind the verse and what they mean",
    "xref":    "draws on the right CROSS-REFERENCED verses — related passages that genuinely "
               "illuminate the cited verse",
}
# Curated queries to give the thinner kinds enough samples (the yaml sets are concept-heavy).
CURATED = {
    "speaker": ["what did Jesus say about faith", "what did Paul teach about love",
                "God's promises to Abraham", "what did Moses command the people",
                "what did Jesus teach about prayer", "the words of Paul on grace"],
    "entity": ["father of David", "Who was Boaz?", "the wife of Boaz", "Who was Ruth?",
               "Who was the mother of Solomon?", "What is Babylon?", "who was the father of Solomon",
               "Who was Jesse?"],
    "passage": ["What does John 3:16 say?", "Explain Genesis 1:1", "What does Romans 8:28 mean?",
                "Explain John 1:1", "What does Philippians 4:13 say?", "What does Psalm 23:1 mean?",
                "Explain Matthew 5:9", "What does Ephesians 2:8 say?"],
    "xref": ["cross references for John 3:16", "verses related to Romans 8:28",
             "cross references for Genesis 1:1", "what verses connect to John 1:1",
             "cross references for Isaiah 53:5", "verses related to Psalm 23:1"],
}


def _queries() -> list[str]:
    out: list[str] = []
    for f in SETS:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r'\s*(?:query|question):\s*"(.+)"\s*$', line)
                if m:
                    out.append(m.group(1))
    for qs in CURATED.values():
        out.extend(qs)
    return list(dict.fromkeys(out))


def _judge(question: str, a: str, b: str, rubric: str) -> str:
    """'A' | 'B' | 'TIE' — which answer is better by this kind's rubric. Ignore length/style."""
    from openai import OpenAI
    cli = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip())
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    prompt = (
        f"Grade two answers to a Bible-study question. The better answer is the one more {rubric}. "
        f"Ignore length and style.\n\nQUESTION: {question}\n\nANSWER A:\n{a}\n\nANSWER B:\n{b}\n\n"
        f"Reply with exactly one token: A, B, or TIE."
    )
    r = cli.chat.completions.create(model=model, max_tokens=4, temperature=0,
                                    messages=[{"role": "user", "content": prompt}])
    v = (r.choices[0].message.content or "").strip().upper()
    return "A" if v.startswith("A") else "B" if v.startswith("B") else "TIE"


def main() -> None:
    sys.path.insert(0, str(REPO))
    import sqlite3
    from indexer import citations as citations_mod
    from indexer.db import has_vec
    from query.analyzer import analyze
    from query.concept_expand import expand_concepts, filter_biblical_words
    from query.retrieve import retrieve
    from query.synthesize import synthesize
    from server.cards import assemble, render_synthesis
    from lang import canon

    try:
        from indexer.db import connect
        db = connect(os.environ.get("INDEX_DB", "/data/index.db"))
    except Exception:
        db = sqlite3.connect(os.environ.get("INDEX_DB", "/data/index.db"))

    buckets = {k: {"w": 0, "t": 0, "l": 0} for k in RUBRICS}
    skipped = 0
    rng = random.Random(12345)
    for q in _queries():
        lang = "en"
        analysis = analyze(q, lang=lang)
        if canon(lang) != "eng":
            analysis.fts_query = filter_biblical_words(q, lang=lang)
        concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=lang)
        analysis.tags.extend(concept_tags)
        analysis.concept_tags = concept_tags

        built = assemble(analysis, db, q, lang)
        # which kind actually fires in the SYNTHESIS projection (gated)?
        syn_kinds = [b.kind for b in built if b.strategy.to_synthesis(b.data, analysis)]
        ref = render_synthesis(built, analysis)
        if not syn_kinds or not ref:
            skipped += 1
            continue
        kind = syn_kinds[0]                              # highest-confidence firing kind

        query_vec = None
        if has_vec(db):
            try:
                from indexer.embed import embed_texts
                query_vec = embed_texts([q], input_type="query")[0]
            except Exception:
                pass
        hits = retrieve(db, analysis, top_k=10, query_vec=query_vec, lang=lang)
        cards = citations_mod.resolve_many(db, [h.chunk_id for h in hits
                                                if not h.chunk_id.startswith("corpus:")])
        if not cards:
            skipped += 1
            continue

        on = synthesize(q, cards, db=db, analysis=analysis, lang=lang, reference_block=ref)["answer"]
        off = synthesize(q, cards, db=db, analysis=analysis, lang=lang, reference_block=None)["answer"]
        on_is_a = rng.random() < 0.5
        verdict = _judge(q, on if on_is_a else off, off if on_is_a else on, RUBRICS[kind])
        won = (verdict == "A" and on_is_a) or (verdict == "B" and not on_is_a)
        lost = (verdict == "A" and not on_is_a) or (verdict == "B" and on_is_a)
        buckets[kind]["w"] += won; buckets[kind]["l"] += lost; buckets[kind]["t"] += (verdict == "TIE")
        print(f"  [{kind:<7}] {'CARD' if won else 'off ' if lost else 'tie '} {q[:60]}", flush=True)

    print(f"\n=== per-kind cards-on vs off ({skipped} skipped: no synthesis card / no sources) ===")
    for kind, b in buckets.items():
        n = b["w"] + b["t"] + b["l"]
        if not n:
            print(f"  {kind:<7}: (no samples)")
            continue
        net = b["w"] - b["l"]
        print(f"  {kind:<7}: {n:2} judged  W {b['w']}  T {b['t']}  L {b['l']}  "
              f"net {net:+d} ({net/n:+.0%})  win-rate {b['w']}/{b['w']+b['l']}")


if __name__ == "__main__":
    main()
