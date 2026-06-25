#!/usr/bin/env python3
"""Branch de-noising eval — A/B the lexicon branch with frame-strip OFF vs ON.

For each case in eval/set/denoise.yaml it builds the branched result twice
(filter_biblical_words strip_frames=False vs True), inspects the LEXICON branch,
and reports:
  noise@branch  how many frame-derived noise_codes appear in the branch (↓ good)
  subj@1        is the top lexicon hit a subject_code? (✓ good)
  subj present  any subject_code in the branch?

Deterministic / $0: no vector retrieval (the frame-strip effect lives in query
expansion, independent of vectors). See internal-docs/branch-denoising.md.

  python -m eval.denoise
  python -m eval.denoise --ids amor perdon
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT))

from indexer.db import open_db  # noqa: E402
from indexer.env import load_env  # noqa: E402
from query.analyzer import analyze  # noqa: E402
from query.concept_expand import filter_biblical_words  # noqa: E402
from query.retrieve import retrieve_branched  # noqa: E402
from lang import canon  # noqa: E402

DEFAULT_SET = REPO_ROOT / "eval" / "set" / "denoise.yaml"
DEFAULT_DB = REPO_ROOT / "indexer" / "index.db"


def _code_of(db, chunk_id: str) -> str | None:
    """The Strong's code a lexicon chunk is keyed on (its strongs: tag)."""
    doc = chunk_id.split(":", 1)[0]
    row = db.execute(
        "SELECT tag FROM tags WHERE doc_id=? AND tag LIKE 'strongs:%' LIMIT 1", (doc,)
    ).fetchone()
    return row[0].split(":", 1)[1] if row else None


def _lexicon_codes(db, case, *, strip_frames: bool, per_branch: int = 10) -> list[str]:
    """Ordered Strong's codes of the lexicon branch for a case."""
    lang = case["lang"]
    a = analyze(case["query"], lang=lang)  # fresh: retrieve_branched mutates tags
    if canon(lang) != "eng":
        a.fts_query = filter_biblical_words(case["query"], lang=lang, strip_frames=strip_frames)
    branches = retrieve_branched(db, a, lang=lang, per_branch=per_branch)
    lex = next((b for b in branches if b.key == "lexicon"), None)
    if lex is None:
        return []
    return [c for c in (_code_of(db, h.chunk_id) for h in lex.hits) if c]


def _score(codes: list[str], case) -> dict:
    subj, noise = set(case["subject_codes"]), set(case["noise_codes"])
    return {
        "noise": sum(1 for c in codes if c in noise),
        "subj1": bool(codes) and codes[0] in subj,
        "subj_present": any(c in subj for c in codes),
        "codes": codes,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=DEFAULT_SET)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--ids", nargs="*")
    args = ap.parse_args()

    load_env()
    db = open_db(args.db)
    cases = yaml.safe_load(args.set.read_text())["cases"]
    if args.ids:
        cases = [c for c in cases if c["id"] in args.ids]

    print(f"{'case':<10} {'noise OFF→ON':>14}  {'subj@1 OFF→ON':>15}  result")
    tot = {"noise_off": 0, "noise_on": 0, "subj1_off": 0, "subj1_on": 0, "n": 0}
    for c in cases:
        off = _score(_lexicon_codes(db, c, strip_frames=False), c)
        on = _score(_lexicon_codes(db, c, strip_frames=True), c)
        tot["noise_off"] += off["noise"]; tot["noise_on"] += on["noise"]
        tot["subj1_off"] += off["subj1"]; tot["subj1_on"] += on["subj1"]
        tot["n"] += 1
        verdict = "✓ improved" if on["noise"] < off["noise"] else (
                  "· no-op" if on["noise"] == off["noise"] and on["codes"] == off["codes"]
                  else "= same-noise")
        s1 = f"{'Y' if off['subj1'] else 'n'}→{'Y' if on['subj1'] else 'n'}"
        print(f"{c['id']:<10} {off['noise']:>6} → {on['noise']:<5}  {s1:>15}  {verdict}")
    print("-" * 60)
    print(f"{'TOTAL':<10} noise {tot['noise_off']}→{tot['noise_on']}   "
          f"subj@1 {tot['subj1_off']}/{tot['n']}→{tot['subj1_on']}/{tot['n']}")

    # Over-strip guards: frame-strip correctness on analyze().fts_query.
    guards = yaml.safe_load(args.set.read_text()).get("frame_guards", [])
    if args.ids:
        guards = [g for g in guards if g["id"] in args.ids]
    if guards:
        print(f"\n{'guard':<22} {'result':<8} fts_query")
        gpass = 0
        for g in guards:
            fts = analyze(g["query"], lang=g["lang"]).fts_query
            toks = set(fts.lower().split())  # OR-query → tokens (strip "OR")
            toks.discard("or")
            missing = [w for w in g.get("must_survive", []) if w.lower() not in toks]
            leaked = [w for w in g.get("must_strip", []) if w.lower() in toks]
            ok = not missing and not leaked
            gpass += ok
            why = ""
            if missing:
                why += f" OVER-STRIPPED:{missing}"
            if leaked:
                why += f" NOT-STRIPPED:{leaked}"
            print(f"{g['id']:<22} {'✓ ok' if ok else '✗ FAIL':<8} {fts!r}{why}")
        print(f"guards: {gpass}/{len(guards)} pass")

    # Speaker-detection guards (S1): analyze().speaker must match expect_speaker
    # (null = must NOT route to a speaker). Exercises the full pipeline incl. the
    # passage-gate and the generic-speaker exclusion — the two over-triggers the
    # v1 eval surfaced (Scripture-as-speaker; name-as-object).
    sguards = yaml.safe_load(args.set.read_text()).get("speaker_guards", [])
    if args.ids:
        sguards = [g for g in sguards if g["id"] in args.ids]
    if sguards:
        print(f"\n{'speaker guard':<24} {'result':<8} intent / speaker (want)")
        spass = 0
        for g in sguards:
            a = analyze(g["query"], lang=g.get("lang", "eng"))
            expected = g.get("expect_speaker")  # None → must not fire
            ok = (a.speaker == expected)
            spass += ok
            print(f"{g['id']:<24} {'✓ ok' if ok else '✗ FAIL':<8} "
                  f"{a.intent} / {a.speaker!r} (want {expected!r})")
        print(f"speaker guards: {spass}/{len(sguards)} pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
