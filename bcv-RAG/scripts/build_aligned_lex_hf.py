#!/usr/bin/env python3
"""A2b — emit a target-language surface→Strong's lexicon from bcv-commons/lexeme-alignments (the
lexeme-aligner's own published output, ~924 languages as of 2026-07), the automated complement to
build_aligned_lex.py's Clear-Bible-manual-alignment source (~10 languages, higher per-row trust
where it exists).

Written to a SEPARATE directory (aligned_lex_hf/, not aligned_lex/) rather than overwriting or
merging with the manual-alignment set — same "never silently merge, tag provenance distinctly"
principle the aligner's own dataset follows (method/base_text columns, additive union, no
winner-take-all). query/concept_expand.py prefers aligned_lex/ (manual) when present for a
language and falls back to aligned_lex_hf/ (this) otherwise.

Language discovery is dynamic (HfApi().list_repo_files) — no hardcoded list, so newly-published
languages are picked up automatically on a re-run, no code change needed.

Quality cutoff (the "some glosses are lower quality" concern): the source dataset already tags
every row with `method` (eflomal/gloss/gapfill — gapfill is documented upstream as "the
lower-confidence coverage layer") and `hi_conf` (fraction of that pair's alignments that were
intersection-backed, i.e. score >= 0.9). This script:
  1. Aggregates each language's rows to one (surface, lexeme) mapping, computing a genuine
     aggregate `share` = count / (total count for that surface, across ALL methods/editions) —
     not just the per-slice share the raw schema documents, so it reflects the full pooled
     evidence, not one method/edition's view of it.
  2. Applies MIN_COUNT / MIN_SHARE (same thresholds already established in build_multiword.py,
     the sibling script mining this same dataset for multi-word expressions).
  3. Additionally drops any (surface, lexeme) pair whose ONLY evidence is `gapfill` (no eflomal or
     gloss corroboration at all) unless its count-weighted `hi_conf` clears MIN_GAPFILL_HI_CONF —
     the extra bar the "lower quality" concern calls for, targeted at exactly the tier the
     aligner's own docs flag as weakest, not a blanket per-language cutoff (every language's
     *overall* quality is already good enough per the go-ahead for this ingest).

Output: aligned_lex_hf/<iso>.tsv (surface, strong, count, share, hi_conf, methods) — same core
columns as aligned_lex/ (surface, strong, count, share) plus hi_conf/methods so a consumer can
apply its own stricter filter later without re-deriving anything.

  python3 scripts/build_aligned_lex_hf.py                  # all published languages
  python3 scripts/build_aligned_lex_hf.py fra ind swe       # just these
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from resource_paths import resource_path  # noqa: E402 — depth-independent, Docker-safe (unlike
# HERE.parent/"resources": that breaks inside the image, where bcv-RAG/ is flattened to /app/ with
# no repo-root sibling above it for "resources" to hang off of; resource_path() instead resolves via
# $BCV_RESOURCES_DIR (set in the Docker image) or by walking up to the nearest resources/ dir.

OUT_DIR = resource_path("aligned_lex_hf")

REPO = "bcv-commons/lexeme-alignments"
MIN_COUNT = 2          # an aggregate (surface, lexeme) pair needs at least this much combined evidence
MIN_SHARE = 0.10        # …and this much P(lexeme|surface) to be a real (not noise-tail) mapping
MIN_GAPFILL_HI_CONF = 0.5   # extra bar for pairs with ONLY gapfill (no eflomal/gloss) evidence

_STRONG_DIGITS = re.compile(r"\d+")


def strong_of(lexeme: str) -> str:
    """lang:augmented-strong -> H####/G#### (augment letter dropped) — the aligner's own derivation,
    see publish/lexeme-alignments/README.md."""
    lang, num = lexeme.split(":", 1)
    m = _STRONG_DIGITS.search(num)
    digits = m.group() if m else "0"
    return ("H" if lang == "hbo" else "G") + digits.zfill(4)


def discover_isos() -> list[str]:
    from huggingface_hub import HfApi
    files = HfApi().list_repo_files(REPO, repo_type="dataset")
    return sorted({f.split("/")[0][4:] for f in files if f.startswith("iso=") and f.endswith("data.parquet")})


def build_one(iso: str) -> dict:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(REPO, f"iso={iso}/data.parquet", repo_type="dataset")
    rows = pq.read_table(path, columns=["surface", "lexeme", "method", "count", "hi_conf"]).to_pylist()

    # Aggregate per (surface, lexeme): total count, methods that attested it, count-weighted hi_conf.
    agg: dict[tuple, dict] = {}
    for r in rows:
        key = (r["surface"], r["lexeme"])
        e = agg.setdefault(key, {"count": 0, "hi_conf_sum": 0.0, "methods": set()})
        e["count"] += r["count"]
        e["hi_conf_sum"] += r["count"] * (r["hi_conf"] or 0.0)
        e["methods"].add(r["method"])

    # Genuine aggregate share: this pair's total count / that surface's grand total, across every
    # lexeme/method/edition — not the narrower per-(method,base_text)-slice share the raw schema
    # documents (see this module's docstring).
    surface_totals: dict[str, int] = collections.defaultdict(int)
    for (surface, _lexeme), e in agg.items():
        surface_totals[surface] += e["count"]

    kept, dropped_quality, dropped_gapfill = [], 0, 0
    for (surface, lexeme), e in agg.items():
        if not surface.strip():
            continue
        count = e["count"]
        share = count / surface_totals[surface]
        hi_conf = e["hi_conf_sum"] / count if count else 0.0
        if count < MIN_COUNT or share < MIN_SHARE:
            dropped_quality += 1
            continue
        if e["methods"] == {"gapfill"} and hi_conf < MIN_GAPFILL_HI_CONF:
            dropped_gapfill += 1
            continue
        kept.append((surface, strong_of(lexeme), count, round(share, 4), round(hi_conf, 3),
                      ",".join(sorted(e["methods"]))))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{iso}.tsv"
    with out_path.open("w", encoding="utf-8") as fh:
        fh.write("# from bcv-commons/lexeme-alignments (HF, CC0-1.0) — automated, all methods pooled.\n")
        fh.write(f"# quality cutoff: count>={MIN_COUNT}, share>={MIN_SHARE}, "
                 f"gapfill-only requires hi_conf>={MIN_GAPFILL_HI_CONF}\n")
        fh.write("surface\tstrong\tcount\tshare\thi_conf\tmethods\n")
        for row in sorted(kept):
            fh.write("\t".join(str(v) for v in row) + "\n")

    return {"iso": iso, "kept": len(kept), "dropped_quality": dropped_quality,
            "dropped_gapfill_only": dropped_gapfill, "raw_rows": len(rows)}


def main() -> int:
    isos = sys.argv[1:] or discover_isos()
    print(f"[aligned_lex_hf] {len(isos)} language(s)", file=sys.stderr)
    totals = collections.Counter()
    for i, iso in enumerate(isos, 1):
        try:
            stats = build_one(iso)
        except Exception as exc:  # noqa: BLE001 — one bad language shouldn't abort the whole run
            print(f"  ! {iso}: {exc}", file=sys.stderr)
            continue
        totals["kept"] += stats["kept"]
        totals["dropped_quality"] += stats["dropped_quality"]
        totals["dropped_gapfill_only"] += stats["dropped_gapfill_only"]
        print(f"  [{i}/{len(isos)}] {iso}: {stats['kept']} kept "
              f"(dropped {stats['dropped_quality']} below count/share, "
              f"{stats['dropped_gapfill_only']} weak-gapfill-only) "
              f"from {stats['raw_rows']} raw rows", file=sys.stderr)
    print(f"[aligned_lex_hf] done: {totals['kept']} total rows kept across {len(isos)} languages "
          f"({totals['dropped_quality']} dropped below count/share, "
          f"{totals['dropped_gapfill_only']} dropped weak-gapfill-only)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
