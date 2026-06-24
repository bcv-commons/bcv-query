#!/usr/bin/env python3
"""Build resources/strongs_tw.tsv — a Strong's → Translation-Words article map.

Collapses bcv-RAG/tw_links.tsv (occurrence-level: every unfoldingWord TWL link
already carries both its `tw_article` and the aligned `strong` code) into a flat
`strong → tw_article` lookup, ranked by occurrence count. Lets a consumer
(notably the shoresh original-language service) answer "which Translation-Words
article explains this Hebrew/Greek word?" from a Strong's number alone.

Output: resources/strongs_tw.tsv
  columns: strong, tw_article, category, is_kt, lemma, n
  - strong:      zero-padded G####/H#### (as in tw_links.tsv)
  - tw_article:  unfoldingWord article path, e.g. bible/kt/god
  - category:    kt | names | other
  - is_kt:       1 for key-term articles
  - lemma:       a representative original-language lemma for the pair
  - n:           occurrences of this (strong, article) pair in the aligned corpus
  Rows are sorted by strong, then n desc — so the primary article for a Strong's
  number comes first. A Strong's number may map to several articles (kept, ranked).

Re-derivable; rebuild after tw_links.tsv changes:
    python3 scripts/build_strongs_tw.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resource_paths import resource_path  # noqa: E402

TW_LINKS = Path(__file__).resolve().parent.parent / "tw_links.tsv"
OUT = resource_path("strongs_tw.tsv")


def main() -> int:
    if not TW_LINKS.exists():
        print(f"missing {TW_LINKS}; run scripts/build_tw_links.py first", file=sys.stderr)
        return 2

    n = Counter()                       # (strong, tw_article) -> occurrences
    meta: dict[tuple[str, str], tuple[str, str]] = {}   # -> (category, is_kt)
    lemma: dict[tuple[str, str], str] = {}              # -> representative lemma

    with TW_LINKS.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            strong = (row.get("strong") or "").strip()
            article = (row.get("tw_article") or "").strip()
            if not strong or not article:
                continue
            key = (strong, article)
            n[key] += 1
            meta[key] = (row.get("category", ""), row.get("is_kt", ""))
            lemma.setdefault(key, row.get("lemma", ""))

    # sort by strong asc, then occurrence count desc (primary article first)
    rows = sorted(n.items(), key=lambda kv: (kv[0][0], -kv[1]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("strong\ttw_article\tcategory\tis_kt\tlemma\tn\n")
        for (strong, article), cnt in rows:
            cat, is_kt = meta[(strong, article)]
            fh.write(f"{strong}\t{article}\t{cat}\t{is_kt}\t{lemma[(strong, article)]}\t{cnt}\n")

    strongs = {k[0] for k in n}
    print(f"  wrote {len(rows)} (strong, article) pairs over {len(strongs)} Strong's → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
