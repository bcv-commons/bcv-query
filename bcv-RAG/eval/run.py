#!/usr/bin/env python3
"""Evaluation runner — score retrieval + synthesis quality against an eval set.

  python3 -m eval.run                    # full pipeline (retrieval + LLM)
  python3 -m eval.run --no-llm           # retrieval-only (no synthesis cost)
  python3 -m eval.run --no-vec           # disable vector retrieval
  python3 -m eval.run --set my-set.yaml  # custom eval set
  python3 -m eval.run --ids id1 id2      # run only specified case IDs

Output: eval/runs/<UTC-timestamp>.json (full) + eval/runs/latest.json (copy).
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))

from indexer import citations as citations_mod  # noqa: E402
from indexer.db import has_vec, open_db  # noqa: E402
from indexer.env import load_env  # noqa: E402
from indexer.references import human, parse_references  # noqa: E402
from query.analyzer import analyze  # noqa: E402
from query.retrieve import retrieve  # noqa: E402

DEFAULT_EVAL_SET = REPO_ROOT / "eval" / "set" / "v1.yaml"
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"
DEFAULT_OUT_DIR = REPO_ROOT / "eval" / "runs"
# With dual-pass scripture_search (vec + FTS over kind:scripture chunks),
# answer-bearing verses now rank 3-6 instead of 9-14, so 10 is enough.
# 12 was a transient mitigation when scripture_search was vec-only. We
# pulled it back to 10 to keep prompt size friendly to rate limits.
TOP_K = 10

# Match the prompt-instructed refusal phrase verbatim (and minor variants).
# Conservative on purpose: the previous broader regex flagged hedged answers
# like "the sources do not explicitly state X, but it is mentioned that …"
# as refusals, which produced false-positive failures. The synthesis prompt
# tells the LLM to set "answer" to a fixed phrase when it can't answer, so
# that's the only thing we flag as a real refusal.
_REFUSAL_RE = re.compile(
    r"i (?:do not|don't) see an answer to that in the indexed sources",
    re.IGNORECASE,
)


# ---------- helpers ----------

def _ranges_overlap(a_s: int, a_e: int, b_s: int, b_e: int) -> bool:
    return a_s <= b_e and a_e >= b_s


def _expected_passage_pairs(strings: list[str]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s in strings:
        out.extend(parse_references(s))
    return out


def _resource_tags(short_names: list[str]) -> list[str]:
    return [f"resource:{n}" for n in short_names]


def _retrieved_passage_ranges(cards: list) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for c in cards:
        if c.passage:
            ranges.extend(parse_references(c.passage))
    return ranges


def _passage_recall(cards: list, expected: list[tuple[int, int]]) -> tuple[float, list[str]]:
    if not expected:
        return 1.0, []
    retrieved = _retrieved_passage_ranges(cards)
    matched = 0
    missing: list[str] = []
    for e_s, e_e in expected:
        if any(_ranges_overlap(e_s, e_e, r_s, r_e) for r_s, r_e in retrieved):
            matched += 1
        else:
            missing.append(human(e_s, e_e))
    return matched / len(expected), missing


def _tag_recall(cards: list, expected_tags: list[str]) -> tuple[float, list[str]]:
    if not expected_tags:
        return 1.0, []
    union: set[str] = set()
    for c in cards:
        union.update(c.tags)
    missing = [t for t in expected_tags if t not in union]
    return (len(expected_tags) - len(missing)) / len(expected_tags), missing


def _is_refusal(answer: str | None) -> bool:
    return bool(answer) and bool(_REFUSAL_RE.search(answer or ""))


def _format_card(card, rank: int) -> dict:
    return {
        "rank": rank,
        "chunk_id": card.chunk_id,
        "title": card.document_title,
        "passage": card.passage,
        "tags": card.tags,
        "source": card.source,
        "excerpt": card.excerpt,
    }


# ---------- per-case evaluation ----------

def evaluate_case(
    case: dict,
    db: sqlite3.Connection,
    *,
    no_llm: bool,
    use_vec: bool,
    top_k: int,
    source_filter: str = "all",
) -> dict:
    case_id = case["id"]
    question = case["question"]
    expects = case.get("expects") or {}

    expected_passages = _expected_passage_pairs(expects.get("passages", []) or [])
    expected_tags_combined = (
        _resource_tags(expects.get("resources", []) or [])
        + (expects.get("tags", []) or [])
    )
    expected_substrings = expects.get("substrings", []) or []
    expected_refusal = bool(expects.get("refusal", False))

    case_start = time.monotonic()
    analysis = analyze(question)

    # Mirror /study's pre-retrieval concept expansion so the eval exercises the
    # Strong's-tag channel (analyze()->retrieve() alone skips expand_concepts).
    from query.concept_expand import expand_concepts
    analysis.tags.extend(expand_concepts(analysis.fts_query, analysis.tags))
    try:
        from query.lxx_expand import expand_lxx
        analysis.tags.extend(expand_lxx(analysis.tags))
    except Exception:
        pass

    query_vec: list[float] | None = None
    embed_error: str | None = None
    if use_vec:
        try:
            from indexer.embed import embed_texts
            query_vec = embed_texts([question], input_type="query")[0]
        except Exception as e:
            embed_error = f"{type(e).__name__}: {e}"

    hits = retrieve(db, analysis, query_vec=query_vec, top_k=top_k, source_filter=source_filter)
    cards = citations_mod.resolve_many(db, [h.chunk_id for h in hits])

    passage_recall, missing_passages = _passage_recall(cards, expected_passages)
    tag_recall, missing_tags = _tag_recall(cards, expected_tags_combined)

    answer_text: str | None = None
    citations: list = []
    confidence: str | None = None
    refusal_observed = False
    substring_hits: list[bool] = []

    if not no_llm:
        try:
            from query.synthesize import synthesize
            synth = synthesize(question, cards, db=db, analysis=analysis)
            answer_text = synth["answer"]
            citations = synth["citations"]
            confidence = synth["confidence"]
            refusal_observed = _is_refusal(answer_text)
            for s in expected_substrings:
                substring_hits.append(s.lower() in (answer_text or "").lower())
        except Exception as e:
            answer_text = f"<synthesis failed: {type(e).__name__}: {e}>"

    duration = round(time.monotonic() - case_start, 3)

    pass_passages = passage_recall == 1.0
    pass_tags = tag_recall == 1.0
    pass_substrings = (not expected_substrings) or all(substring_hits)
    if no_llm:
        # Without synthesis, we can't judge refusal — treat refusal-cases as
        # neither pass nor fail at the answer level, but still require that
        # NO meaningful passage/tag was expected (which is the normal shape).
        pass_refusal_ok = True
        pass_no_false_refusal = True
    else:
        pass_refusal_ok = (not expected_refusal) or refusal_observed
        pass_no_false_refusal = expected_refusal or (not refusal_observed)

    overall_pass = (
        pass_passages and pass_tags and pass_substrings
        and pass_refusal_ok and pass_no_false_refusal
    )

    result = {
        "id": case_id,
        "tags": case.get("tags", []),
        "question": question,
        "pass": overall_pass,
        "duration_s": duration,
        "metrics": {
            "passage_recall": round(passage_recall, 3),
            "tag_recall": round(tag_recall, 3),
            "substring_recall": round(
                sum(substring_hits) / len(substring_hits), 3
            ) if substring_hits else 1.0,
            "refusal_correct": pass_refusal_ok and pass_no_false_refusal,
        },
        "missing": {
            "passages": missing_passages,
            "tags": missing_tags,
            "substrings": [s for s, hit in zip(expected_substrings, substring_hits) if not hit],
        },
        "expects": expects,
        "analysis": {
            "fts_query": analysis.fts_query,
            "passages": [list(p) for p in analysis.passages],
            "tags": analysis.tags,
            "intent": analysis.intent,
        },
        "retrieved_top": [_format_card(c, i + 1) for i, c in enumerate(cards[:5])],
        "retrieved_count": len(cards),
        "answer": answer_text,
        "citations": citations,
        "confidence": confidence,
        "refusal_observed": refusal_observed,
        "embed_error": embed_error,
    }
    return result


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    if n == 0:
        return {"total": 0}
    passed = sum(1 for r in results if r.get("pass"))

    def _mean(key: str) -> float:
        values = [r["metrics"][key] for r in results if "metrics" in r and key in r["metrics"]]
        return round(sum(values) / len(values), 3) if values else 0.0

    return {
        "total": n,
        "passed": passed,
        "failed": n - passed,
        "pass_rate": round(passed / n, 3),
        "passage_recall_mean": _mean("passage_recall"),
        "tag_recall_mean": _mean("tag_recall"),
        "substring_recall_mean": _mean("substring_recall"),
        "refusal_correct_count": sum(
            1 for r in results
            if r.get("metrics", {}).get("refusal_correct") is True
        ),
    }


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", default=DEFAULT_EVAL_SET, type=Path, help="path to eval-set YAML")
    ap.add_argument("--db", default=DEFAULT_DB, type=Path)
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR, type=Path)
    ap.add_argument("--no-llm", action="store_true", help="skip LLM synthesis (retrieval-only)")
    ap.add_argument("--no-vec", action="store_true", help="skip vector retrieval (no OPENAI key required)")
    ap.add_argument("--source", choices=["all", "door43", "aquifer"], default="all",
                    help="restrict retrieval to one source (default: all)")
    ap.add_argument("--top-k", type=int, default=TOP_K)
    ap.add_argument("--ids", nargs="+", help="run only the listed case IDs")
    args = ap.parse_args()

    load_env()

    if not args.set.exists():
        print(f"eval set not found: {args.set}", file=sys.stderr)
        return 2
    if not args.db.exists():
        print(f"db not found: {args.db}\nrun ingest + indexer.build first", file=sys.stderr)
        return 2

    try:
        import yaml
    except ImportError:
        print("pyyaml required: pip install pyyaml", file=sys.stderr)
        return 3

    spec = yaml.safe_load(args.set.read_text(encoding="utf-8"))
    cases = spec.get("cases", []) or []
    if args.ids:
        wanted = set(args.ids)
        cases = [c for c in cases if c["id"] in wanted]
    if not cases:
        print("no cases to run", file=sys.stderr)
        return 2

    db = open_db(args.db)
    use_vec = (not args.no_vec) and has_vec(db)

    print(
        f"running {len(cases)} cases "
        f"(vec={'on' if use_vec else 'off'}, llm={'off' if args.no_llm else 'on'}, source={args.source})",
        file=sys.stderr,
    )

    run_start = time.monotonic()
    results: list[dict] = []
    for i, case in enumerate(cases, start=1):
        try:
            res = evaluate_case(case, db, no_llm=args.no_llm, use_vec=use_vec,
                                top_k=args.top_k, source_filter=args.source)
        except Exception as e:
            res = {
                "id": case.get("id"),
                "question": case.get("question"),
                "pass": False,
                "error": f"{type(e).__name__}: {e}",
            }
        symbol = "OK  " if res.get("pass") else "FAIL"
        print(f"  [{i}/{len(cases)}] {symbol}  {res.get('id')}  ({res.get('duration_s', 0)}s)", file=sys.stderr)
        results.append(res)

    summary = aggregate(results)

    embedding_model: str | None = None
    if use_vec:
        from indexer.embed import EMBEDDING_MODEL
        embedding_model = EMBEDDING_MODEL
    synthesis_model: str | None = None
    if not args.no_llm:
        from query.llm import GROQ_MODEL, OPENAI_MODEL
        synthesis_model = f"{GROQ_MODEL} (Groq, primary) → {OPENAI_MODEL} (OpenAI, fallback)"

    out = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "duration_s": round(time.monotonic() - run_start, 2),
        "config": {
            "eval_set": str(args.set.relative_to(REPO_ROOT) if args.set.is_relative_to(REPO_ROOT) else args.set),
            "db": str(args.db.relative_to(REPO_ROOT) if args.db.is_relative_to(REPO_ROOT) else args.db),
            "no_llm": args.no_llm,
            "use_vec": use_vec,
            "source": args.source,
            "top_k": args.top_k,
            "case_count": len(cases),
            "embedding_model": embedding_model,
            "synthesis_model": synthesis_model,
        },
        "summary": summary,
        "results": results,
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out_path = args.out_dir / f"{timestamp}.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    (args.out_dir / "latest.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"\n{'=' * 64}", file=sys.stderr)
    print(f"  Pass rate:               {summary['passed']}/{summary['total']}  ({summary['pass_rate'] * 100:.1f}%)", file=sys.stderr)
    print(f"  Passage recall (mean):   {summary['passage_recall_mean']}", file=sys.stderr)
    print(f"  Tag recall (mean):       {summary['tag_recall_mean']}", file=sys.stderr)
    print(f"  Substring recall (mean): {summary['substring_recall_mean']}", file=sys.stderr)
    print(f"  Refusal correct:         {summary['refusal_correct_count']}/{summary['total']}", file=sys.stderr)
    print(f"  Duration:                {out['duration_s']}s", file=sys.stderr)
    print(f"  Output:                  {out_path.relative_to(REPO_ROOT)}", file=sys.stderr)
    print(f"  Latest:                  {(args.out_dir / 'latest.json').relative_to(REPO_ROOT)}", file=sys.stderr)
    print(f"{'=' * 64}", file=sys.stderr)

    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
