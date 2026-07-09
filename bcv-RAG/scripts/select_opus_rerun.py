#!/usr/bin/env python3
"""Pick the lexemes worth re-running on a stronger model (the hedge).

After the cheap (Sonnet) pass + `macula.build_semantic_neighbors --llm-edges`, this selects the
targets where spending Opus actually pays: the LLM prior was NOT empirically confirmed (no `high`
edge), ranked by biblical salience (keyness) and capped. Everything the embedding already corroborated
keeps its cheap-model edge — no reason to pay Opus there.

  python3 scripts/select_opus_rerun.py [N]         # default N=800  -> /tmp/needs_opus.txt
Then:  ANTHROPIC_MODEL=claude-opus-4-8 python3 scripts/build_llm_neighbors.py --only /tmp/needs_opus.txt --redo
"""
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "resources" / "semantic_neighbors" / "neighbors.parquet"
KEYNESS = ROOT / "resources" / "strongs_keyness.tsv"
OUT = Path("/tmp/needs_opus.txt")


def hstrong(lx: str) -> str:
    m = re.search(r"(\d+)", lx)
    return f"H{int(m.group(1)):04d}" if m else ""


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 800
    rows = pq.read_table(PACK).to_pylist()

    has_high, llm_touched = set(), set()
    for r in rows:
        s = hstrong(r["lexeme"])
        if r["confidence"] == "high":
            has_high.add(s)
        if r["confidence"] in ("high", "prior"):       # the LLM asserted something for this lexeme
            llm_touched.add(s)

    key = {}
    if KEYNESS.exists():
        for ln in KEYNESS.read_text(encoding="utf-8").splitlines()[1:]:
            p = ln.split("\t")
            if len(p) >= 2 and p[0].startswith("H"):
                try:
                    key[p[0]] = float(p[1])
                except ValueError:
                    pass

    cands = [s for s in llm_touched if s not in has_high]        # LLM said it, embedding never backed it
    cands.sort(key=lambda s: -key.get(s, 0.0))                   # most biblically salient first
    OUT.write_text("\n".join(cands[:n]) + "\n", encoding="utf-8")
    print(f"{len(cands)} unconfirmed-prior lexemes; wrote top {min(n, len(cands))} "
          f"(by keyness) -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
