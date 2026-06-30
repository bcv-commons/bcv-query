#!/usr/bin/env python3
"""Run per-stem gloss generation for ALL remaining languages, in dependency order.

"Remaining" = a gloss language that has base (`default`) glosses but no per-stem cells yet.
Order matters because each run's reference languages come from already-per-stem cousins
(resolved via related_langs + regional_langs): doing a language adds it to the pool, which
can improve a later cousin's references. This greedily runs the language with the most
ready references first, then re-scores — so seed languages unlock their families.

  python scripts/build_perstem_all.py            # PLAN only (no API): order, refs, cost
  python scripts/build_perstem_all.py --run      # run each in order (incurs token cost)

Delegates each language to build_perstem_glosses_llm.py (so resume/--force, auto-refs and
the .env key handling all apply). Already-complete languages are skipped (0 cells → no API).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_perstem_glosses_llm as P   # noqa: E402  (reuse the single-language logic)


def _remaining():
    """Languages with a default-gloss file but no per-stem cells."""
    rem = []
    for p in sorted(P.WG.glob("*.csv")):
        if not P._existing_cells(p.stem):          # no stem cells yet
            # must have a base file to merge onto (it exists by definition here)
            rem.append(p.stem)
    return rem


def _order(remaining):
    """Greedy dependency order: most ready (per-stem) references first; running a
    language joins the pool for subsequent ones."""
    pool = P._perstem_langs()
    rem = list(remaining)
    order = []
    while rem:
        def ready_refs(L):
            refs = P._auto_refs(L, pool) or []
            return [r for r in refs if r != "English" and r in pool]
        rem.sort(key=lambda L: (-len(ready_refs(L)), L))
        pick = rem.pop(0)
        order.append((pick, P._auto_refs(pick, pool) or list(P.DEFAULT_REFS)))
        pool.add(pick)
    return order


def main():
    run = "--run" in sys.argv
    remaining = _remaining()
    if not remaining:
        print("Nothing remaining — every gloss language already has per-stem cells.", file=sys.stderr)
        return
    order = _order(remaining)

    print(f"Per-stem run plan ({len(order)} remaining, {'RUN' if run else 'PLAN'}):", file=sys.stderr)
    for i, (lang, refs) in enumerate(order, 1):
        print(f"  {i}. {lang:<22} refs: {','.join(refs)}", file=sys.stderr)
    if not run:
        print("\n  → dry-running each for exact cost (no API):", file=sys.stderr)
        for lang, _refs in order:
            subprocess.run([sys.executable, str(HERE / "build_perstem_glosses_llm.py"), lang])
        print("\n  Re-run with --run to generate (each language ~$0.2 on Haiku).", file=sys.stderr)
        return

    for lang, _refs in order:
        print(f"\n=== {lang} ===", file=sys.stderr)
        r = subprocess.run([sys.executable, str(HERE / "build_perstem_glosses_llm.py"), lang, "--run"])
        if r.returncode != 0:
            print(f"FAILED at {lang} (exit {r.returncode})", file=sys.stderr)
            sys.exit(r.returncode)
    print("\nAll remaining languages generated.", file=sys.stderr)


if __name__ == "__main__":
    main()
