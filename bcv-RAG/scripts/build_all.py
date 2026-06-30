#!/usr/bin/env python3
"""Regenerate all derived data artifacts in dependency order (Strong's core).

See internal-docs/build-and-artifacts.md for the full picture. This encodes the
build DAG so "regenerate" is one command instead of tribal knowledge.

Steps (order matters — later steps read earlier outputs):
  1. build_strongs_freq      (local)            -> strongs_freq.tsv
  2. build_strong_lemma      (local)            -> strong_lemma.tsv
  3. build_multilingual_glosses (NETWORK: UBS)  -> strongs_gloss.tsv   [--downloads]
  4. build_strongs_keyness   (local + wordfreq) -> strongs_keyness.tsv
  5. build_tw_links          (NETWORK: TWL)     -> tw_links.tsv        [--downloads]
  6. build_forms             (local)            -> forms.tsv
  7. build_concepts          (local)            -> concepts.tsv

Requirements: a venv with `wordfreq` (requirements-build.txt) for step 4, and
the source DBs present locally (shoresh/spine/spine.db, shoresh/lxx/lxx.db,
bcv-RAG/indexer/index.db). Network steps are OFF by default (slow; their
outputs change rarely) — pass --downloads to refresh them.

Usage:
  python3 scripts/build_all.py                 # local steps only
  python3 scripts/build_all.py --downloads     # also refresh gloss + tw_links
  python3 scripts/build_all.py --list          # print the plan, run nothing
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

# (script, label, needs_network)
STEPS = [
    ("build_strongs_freq.py",        "strongs_freq.tsv (is_function)",     False),
    ("build_strong_lemma.py",        "strong_lemma.tsv",                   False),
    ("build_multilingual_glosses.py", "strongs_gloss.tsv (UBS download)",  True),
    ("build_bibleol_strongs_gloss.py", "strongs_gloss.tsv += BibleOL langs (dan/deu/nld/swa/amh)", False),  # AFTER ^ regen
    ("build_strongs_keyness.py",     "strongs_keyness.tsv (wordfreq)",     False),
    ("build_tw_links.py",            "tw_links.tsv (TWL download)",        True),
    ("build_forms.py",               "forms.tsv",                          False),
    ("build_concepts.py",            "concepts.tsv (registry)",            False),
    ("build_aligned_all.py",         "aligned_lex/*.tsv (Alignments release)", True),
]


def main() -> None:
    downloads = "--downloads" in sys.argv
    list_only = "--list" in sys.argv

    plan = [s for s in STEPS if downloads or not s[2]]
    skipped = [s for s in STEPS if s[2] and not downloads]

    print("Build plan (dependency order):", file=sys.stderr)
    for i, (script, label, net) in enumerate(STEPS, 1):
        mark = "RUN " if (downloads or not net) else "SKIP"
        tag = " [network]" if net else ""
        print(f"  {i}. [{mark}] {label}{tag}", file=sys.stderr)
    if skipped:
        print("  (network steps skipped; pass --downloads to refresh)", file=sys.stderr)
    if list_only:
        return

    for script, label, net in STEPS:
        if net and not downloads:
            continue
        args = [sys.executable, str(SCRIPTS / script)]
        if script == "build_tw_links.py":
            args.append("--all")
        print(f"\n=== {label} ===", file=sys.stderr)
        r = subprocess.run(args)
        if r.returncode != 0:
            print(f"FAILED at {script} (exit {r.returncode})", file=sys.stderr)
            sys.exit(r.returncode)
    print("\nAll artifacts regenerated.", file=sys.stderr)


if __name__ == "__main__":
    main()
