#!/usr/bin/env python3
"""Cards-on vs cards-off A/B — does the synthesis reference card improve answers?

For each concept-relevant eval query: retrieve ONCE, then synthesize TWICE over the SAME
sources — with the concept card in the prompt vs without — and have a NEUTRAL judge (OpenAI,
a different provider from the Groq generator) pick the better-grounded answer, BLIND (A/B order
randomized per query to kill position bias). Reports wins / ties / losses.

Run where shoresh + index + the keys are wired (the bcv-rag container / a throwaway from the
new image):  python -m eval.cards_ab
Env: SHORESH_URL, GROQ_API_KEY+GROQ_MODEL (generator), OPENAI_API_KEY+OPENAI_MODEL (judge),
     INDEX_DB (default /data/index.db).
"""
from __future__ import annotations

import os
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETS = [REPO / "eval/set/v1.yaml", REPO / "eval/set/v2-expansion.yaml", REPO / "eval/set/denoise.yaml"]


def _queries() -> list[str]:
    out = []
    for f in SETS:
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r'\s*(?:query|question):\s*"(.+)"\s*$', line)
                if m:
                    out.append(m.group(1))
    return out


def _judge(question: str, a: str, b: str) -> str:
    """Return 'A' | 'B' | 'TIE' — which answer is better grounded in the original-language facts."""
    from openai import OpenAI
    cli = OpenAI(api_key=os.environ["OPENAI_API_KEY"].strip())
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    prompt = (
        f"You are grading two answers to a Bible-study question for ACCURACY and for being "
        f"GROUNDED IN THE ORIGINAL-LANGUAGE (Hebrew/Greek) lexical facts (correct sense of the "
        f"key word, right gloss/domain). Ignore length and style.\n\n"
        f"QUESTION: {question}\n\nANSWER A:\n{a}\n\nANSWER B:\n{b}\n\n"
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

    wins = ties = losses = skipped = 0
    rng = random.Random(12345)
    rows = []
    for q in _queries():
        lang = "en"
        analysis = analyze(q, lang=lang)
        if canon(lang) != "eng":
            analysis.fts_query = filter_biblical_words(q, lang=lang)
        concept_tags = expand_concepts(analysis.fts_query, analysis.tags, lang=lang)
        analysis.tags.extend(concept_tags)
        analysis.concept_tags = concept_tags
        ref = render_synthesis(assemble(analysis, db, q, lang), analysis)
        if not ref:                                  # only queries the card actually fires on
            skipped += 1
            continue

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
        on_is_a = rng.random() < 0.5                 # blind: randomize position
        verdict = _judge(q, on if on_is_a else off, off if on_is_a else on)
        won = (verdict == "A" and on_is_a) or (verdict == "B" and not on_is_a)
        lost = (verdict == "A" and not on_is_a) or (verdict == "B" and on_is_a)
        wins += won; losses += lost; ties += (verdict == "TIE")
        rows.append((("CARD" if won else "off" if lost else "tie"), q[:64]))
        print(f"  [{'CARD' if won else 'off ' if lost else 'tie '}] {q[:70]}", flush=True)

    n = wins + ties + losses
    print(f"\n=== cards-on vs off: {n} judged ({skipped} skipped: no concept/sources) ===")
    print(f"  card WINS: {wins}  ties: {ties}  card LOSES: {losses}")
    if n:
        print(f"  net lift: {(wins - losses)} ({(wins - losses) / n:+.0%})  "
              f"win-rate (excl. ties): {wins}/{wins + losses}")


if __name__ == "__main__":
    main()
