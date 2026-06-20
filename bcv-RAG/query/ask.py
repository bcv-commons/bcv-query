#!/usr/bin/env python3
"""Free-form Q&A CLI.

    python3 -m query.ask "what does Titus 1:1 say about being a servant of God?"
    python3 -m query.ask --no-llm "..."   # skip LLM, dump retrieved chunks
    python3 -m query.ask --json    "..."  # raw JSON output
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indexer import citations as citations_mod  # noqa: E402
from indexer.db import has_vec, open_db  # noqa: E402
from indexer.env import load_env  # noqa: E402
from query.analyzer import analyze  # noqa: E402
from query.retrieve import retrieve  # noqa: E402
from lang import canon  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parent.parent / "indexer" / "index.db"


def _render_inline(answer: dict, cards: list) -> str:
    # Map each cited chunk_id to a 1-based [N] in the order it appears.
    id_to_num: dict[str, int] = {}
    for cid in answer["citations"]:
        if cid not in id_to_num:
            id_to_num[cid] = len(id_to_num) + 1

    text = answer["answer"]
    for cid, n in id_to_num.items():
        text = text.replace(f"[{cid}]", f"[{n}]")

    out = [text, ""]
    if id_to_num:
        out.append("Sources:")
        for cid, n in id_to_num.items():
            card = next((c for c in cards if c.chunk_id == cid), None)
            if not card:
                continue
            passage = card.passage or "no passage"
            out.append(f"  [{n}] {card.document_title} — {passage}")
            out.append(f"      {card.source}")
            out.append(f"      \"{card.excerpt}\"")
    out.append("")
    out.append(f"(confidence: {answer['confidence']})")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question", help="free-form natural-language question")
    ap.add_argument("--db", default=DEFAULT_DB, type=Path)
    ap.add_argument("--top-k", type=int, default=10, help="how many chunks to retrieve")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of formatted text")
    ap.add_argument("--no-llm", action="store_true", help="dump retrieved chunks without calling the LLM")
    ap.add_argument("--no-vec", action="store_true", help="skip vector retrieval even if sqlite-vec is loaded")
    ap.add_argument("--source", choices=["all", "door43", "aquifer"], default="all",
                    help="restrict retrieval to one source (default: all)")
    ap.add_argument("--lang", default="eng",
                    help="query language, ISO 639-3 (spa/fra/por/rus/arb/hin/…); "
                         "legacy 2-letter (es/fr/…) also accepted")
    args = ap.parse_args()

    load_env()

    if not args.db.exists():
        print(f"db not found: {args.db}\nrun ingest + indexer.build first", file=sys.stderr)
        return 2

    analysis = analyze(args.question, lang=args.lang)
    if canon(args.lang) != "eng":
        from query.concept_expand import filter_biblical_words
        analysis.fts_query = filter_biblical_words(args.question, lang=args.lang)
    db = open_db(args.db)

    query_vec: list[float] | None = None
    if not args.no_vec and has_vec(db):
        try:
            db.execute("SELECT count(*) FROM chunks_vec LIMIT 1")
            from indexer.embed import embed_texts  # lazy import (requires openai SDK)
            query_vec = embed_texts([args.question], input_type="query")[0]
        except sqlite3.OperationalError:
            # chunks_vec doesn't exist yet — user hasn't run indexer.embed
            pass

    hits = retrieve(db, analysis, top_k=args.top_k, query_vec=query_vec, source_filter=args.source, lang=args.lang)
    cards = citations_mod.resolve_many(db, [h.chunk_id for h in hits])

    if args.no_llm:
        out = {
            "analysis": {
                "fts_query": analysis.fts_query,
                "passages":  [list(p) for p in analysis.passages],
                "tags":      analysis.tags,
                "intent":    analysis.intent,
            },
            "source_filter": args.source,
            "hits": [{"chunk_id": h.chunk_id, "score": h.score, "retrievers": h.retrievers} for h in hits],
            "cards": [c.asdict() for c in cards],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    from query.synthesize import synthesize  # imports openai SDK lazily
    answer = synthesize(args.question, cards, db=db, lang=args.lang)

    if args.json:
        print(json.dumps({**answer, "cards": [c.asdict() for c in cards]}, indent=2, ensure_ascii=False))
    else:
        print(_render_inline(answer, cards))
    return 0


if __name__ == "__main__":
    sys.exit(main())
