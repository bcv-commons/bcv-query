#!/usr/bin/env python3
"""Build the standalone, provenance-marked Strong's->words dataset (alignment
family) from Clear-Bible/Alignments.

This is the *distributable* dataset for consumers who want neither the services
nor the code — just "Strong's number -> the actual words, per language". It does
NOT touch the service-consumed resources (aligned_lex/, glosses, etc.); it is an
additional artifact built from the same .cache/alignments extract.

Design rules:
  * anchored on Hebrew/Greek ONLY  (strong + original lemma; never via English)
  * one language per file
  * every word carries its provenance (method / source corpus / base text)

Three tiers (the per-occurrence file is canonical; the other two are roll-ups):

  attestations/<code>.tsv      one row per aligned occurrence (opt-in, heavy)
      strong lemma surface ref target_id source_id method source_corpus base_text
  surfaces_by_method/<code>.tsv  per (strong,surface,method) with count
      strong lemma surface method source_corpus base_text count
  surfaces/<code>.tsv          per (strong,surface): friendly default download
      strong lemma surface count share methods review

  ref       = BBCCCVVV verse
  target_id = occurrence id (BBCCCVVV + WWW) in the target translation
  source_id = Clear/BCVW original-language token id (e.g. n40010030011)
  share     = P(strong|surface): this code's fraction of the surface's alignments
  methods   = ;-set of methods that attest the pair (ensemble agreement)
  review    = human-verified (any manual alignment) else machine

Usage:
  python3 scripts/build_strongs_words.py                 # all cached languages
  python3 scripts/build_strongs_words.py --langs es,fr   # subset (2-letter or iso3)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from ingest.clear_aligned import read_aligned_occurrences  # noqa: E402
from scripts.build_aligned_lex import discover_versions     # noqa: E402
from lang import canon                                       # noqa: E402

CACHE = HERE / ".cache" / "alignments" / "extracted"
OUT = HERE.parent / "resources" / "strongs"
LEMMA_TSV = HERE / "strong_lemma.tsv"
DATASET_SOURCE = "clear-alignments (github.com/Clear-Bible/Alignments)"

_WORD = re.compile(r"\w", re.UNICODE)


def load_canonical_lemmas() -> dict[str, str]:
    """{strong: dictionary lemma} from strong_lemma.tsv — one consistent lemma
    per code across all languages (the WLCM Hebrew source drops its lemma column,
    so the per-token lemma alone leaves Hebrew blank)."""
    out: dict[str, str] = {}
    if not LEMMA_TSV.exists():
        return out
    with LEMMA_TSV.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        si, li = header.index("strong"), header.index("lemma")
        for line in fh:
            c = line.rstrip("\n").split("\t")
            if len(c) > li and c[si] and c[li]:
                out.setdefault(c[si], c[li])
    return out


def _clean(surface: str) -> str:
    """Lowercase + strip; '' for noise we don't want in a public dataset."""
    s = (surface or "").strip().lower()
    if not s or not _WORD.search(s):     # punctuation-only
        return ""
    if s[0].isdigit():                    # verse-number artifacts (e.g. '13boca')
        return ""
    return s


def _header(fh, tier: str, code: str, versions: list[str]) -> None:
    today = _dt.date.today().isoformat()
    fh.write(
        f"# dataset=strongs/{tier}; lang={code}; "
        f"source={DATASET_SOURCE}; base_text={'+'.join(versions)}; "
        f"license=see resources/strongs/README.md; date={today}\n"
    )


def build_language(data_dir: Path, iso3: str, code: str,
                   canon: dict[str, str]) -> dict:
    versions = discover_versions(data_dir, iso3)
    if not versions:
        return {}

    (OUT / "attestations").mkdir(parents=True, exist_ok=True)
    (OUT / "surfaces_by_method").mkdir(parents=True, exist_ok=True)
    (OUT / "surfaces").mkdir(parents=True, exist_ok=True)

    lemma_of: dict[str, str] = {}                          # strong -> lemma
    by_method: dict[tuple, int] = defaultdict(int)         # (strong,surf,method,src,base)->count
    pair_ids: dict[tuple, set] = defaultdict(set)          # (surf,strong)->{target_id}
    pair_methods: dict[tuple, set] = defaultdict(set)      # (surf,strong)->{method}
    surf_total: dict[str, set] = defaultdict(set)          # surf->{target_id} (any strong)

    occ = 0
    att_path = OUT / "attestations" / f"{code}.tsv"
    with att_path.open("w", encoding="utf-8") as att:
        _header(att, "attestations", code, versions)
        att.write("strong\tlemma\tsurface\tref\ttarget_id\tsource_id\t"
                  "method\tsource_corpus\tbase_text\n")
        for version in versions:
            for r in read_aligned_occurrences(data_dir, iso3, version):
                surf = _clean(r["surface"])
                if not surf:
                    continue
                strong = r["strong"]
                lemma = canon.get(strong) or r["lemma"]
                lemma_of.setdefault(strong, lemma)
                occ += 1
                att.write(
                    f"{strong}\t{lemma}\t{surf}\t{r['ref']}\t{r['target_id']}\t"
                    f"{r['source_id']}\t{r['method']}\t{r['source_corpus']}\t"
                    f"{version}\n"
                )
                # occurrence identity includes the version: the same target_id
                # in two editions (en BSB+YLT, ar AVD+ONAV) is a different word
                # and must not be deduped; manual+transfer on ONE edition should.
                oid = (version, r["target_id"])
                by_method[(strong, surf, r["method"], r["source_corpus"], version)] += 1
                pair_ids[(surf, strong)].add(oid)
                pair_methods[(surf, strong)].add(r["method"])
                surf_total[surf].add(oid)

    # Tier 2 — full, per method
    with (OUT / "surfaces_by_method" / f"{code}.tsv").open("w", encoding="utf-8") as fh:
        _header(fh, "surfaces_by_method", code, versions)
        fh.write("strong\tlemma\tsurface\tmethod\tsource_corpus\tbase_text\tcount\n")
        for (strong, surf, method, src, base), cnt in sorted(by_method.items()):
            fh.write(f"{strong}\t{lemma_of.get(strong,'')}\t{surf}\t{method}\t"
                     f"{src}\t{base}\t{cnt}\n")

    # Tier 1 — friendly collapsed
    rows = 0
    with (OUT / "surfaces" / f"{code}.tsv").open("w", encoding="utf-8") as fh:
        _header(fh, "surfaces", code, versions)
        fh.write("strong\tlemma\tsurface\tcount\tshare\tmethods\treview\n")
        # group by surface so share denominators are stable, then by count desc
        by_surf: dict[str, list] = defaultdict(list)
        for (surf, strong), ids in pair_ids.items():
            by_surf[surf].append((strong, len(ids)))
        for surf in sorted(by_surf):
            total = len(surf_total[surf]) or 1
            for strong, cnt in sorted(by_surf[surf], key=lambda x: -x[1]):
                methods = sorted(pair_methods[(surf, strong)])
                review = "human-verified" if "manual" in methods else "machine"
                fh.write(f"{strong}\t{lemma_of.get(strong,'')}\t{surf}\t{cnt}\t"
                         f"{cnt/total:.3f}\t{';'.join(methods)}\t{review}\n")
                rows += 1

    return {"versions": versions, "occurrences": occ,
            "pairs": len(pair_ids), "surfaces_rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", help="comma-separated subset (2-letter or iso3)")
    args = ap.parse_args()

    available = sorted(d.name for d in CACHE.iterdir() if (d / "data").exists()) \
        if CACHE.exists() else []
    if not available:
        print(f"no extracted alignments under {CACHE} — run build_aligned_all.py first",
              file=sys.stderr)
        sys.exit(1)

    if args.langs:
        # the cache dirs ARE the canonical iso3 tags; canon() maps any legacy
        # 2-letter / BCP-47 input to that canonical form for matching.
        want = {canon(x.strip()) for x in args.langs.split(",")}
        available = [i for i in available if i in want]

    lemmas = load_canonical_lemmas()
    print(f"canonical lemmas: {len(lemmas)} codes", file=sys.stderr)
    summary = []
    for iso3 in available:
        code = iso3                       # cache dir name = canonical tag
        print(f"=== {iso3} -> strongs/*/{code}.tsv ===", file=sys.stderr)
        try:
            st = build_language(CACHE / iso3 / "data", iso3, code, lemmas)
            if not st:
                print("  no aligned versions; skipping", file=sys.stderr)
                continue
            print(f"  {'+'.join(st['versions'])}: {st['occurrences']} occ, "
                  f"{st['pairs']} pairs, {st['surfaces_rows']} surface rows",
                  file=sys.stderr)
            summary.append((code, iso3, st))
        except Exception as e:
            print(f"  FAILED {iso3}: {e}", file=sys.stderr)

    print("\n=== strongs summary ===", file=sys.stderr)
    for code, iso3, st in summary:
        print(f"  {code:4} {iso3:4} {'+'.join(st['versions']):14} "
              f"occ={st['occurrences']:>8} pairs={st['pairs']:>7} "
              f"rows={st['surfaces_rows']:>7}", file=sys.stderr)


if __name__ == "__main__":
    main()
