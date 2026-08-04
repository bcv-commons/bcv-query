#!/usr/bin/env python3
"""Poetic-parallelism word pairs (candidate #7, bcv-commons-export-candidates.md) — which Hebrew words
occupy the matching slot across parallel half-verses in biblical poetry (Psalms/Proverbs/Job).

Synonymous parallelism is a well-known structural feature of biblical Hebrew poetry: two (or more)
half-verses restate the same idea in different words. Psalm 1:1 is a textbook example — three parallel
cola pairing {walk/stand/sit} and {wicked/sinners/scoffers}. Content words in the matching slot across
parallel cola are near-synonyms BY CONSTRUCTION — a real relationship the raw text doesn't state
explicitly (same shape as ot_nt_quotations.py / build_synoptic.py), derived directly from BHSA's own
`half_verse` structure via Context Fabric. Not derived from UBS MARBLE, not from Hebrew WordNet, not
from the LLM signal already baked into the neighbor pack — a genuinely independent, register-matched
(biblical, not modern) source. Built specifically to test the unresolved BEREL-vs-bge-m3 disagreement:
see domain-replacement-roadmap.md's 2026-08 section.

Method: for each verse in POETIC_BOOKS with exactly 2 half-verses (bicola — the clean/common case),
take the bag-of-content-words cross-product between the two halves as CANDIDATE pairs (no attempt at
precise slot-to-slot alignment within one verse — that's ambiguous/chiastic often enough to be
unreliable). Corroborate across the whole corpus instead: only keep pairs supported by >= MIN_VERSES
distinct verses — same "many independent occurrences = trust" principle as the xling/lxx signals.

Antithetic-parallelism contamination: Hebrew poetry (Proverbs especially) uses CONTRASTIVE parallelism
just as often as synonymous — "the righteous/the wicked" is a real, tight structural pairing, just an
antonym, not a synonym. Rather than trying to detect this from grammar alone (unreliable), cross-
reference every parallelism-corroborated pair against the LLM syn/ant signal already built for the
neighbor pack (semantic_neighbors/llm_edges.tsv) — two INDEPENDENT signals (structural parallelism +
LLM judgment) agreeing is real evidence either way. This labels pairs `likely_synonym` /
`likely_antonym` / `unclassified` (parallelism found it, LLM has no opinion either way — genuinely
ambiguous without more evidence, not silently dropped). The antithetic pairs are a real, valuable,
independently-derived output in their own right — same shape as the synonym pairs, just the opposite
relation — worth publishing alongside them, not discarding as noise.

  python -m macula.build_parallelism_pairs
"""
from __future__ import annotations

import argparse
import collections
import itertools
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO = ROOT / "resources" / "occurrences" / "hbo.db"
LLM_EDGES = ROOT / "resources" / "semantic_neighbors" / "llm_edges.tsv"
OUT_DIR = ROOT / "resources" / "parallelism"

POETIC_BOOKS = ["Psalms", "Proverbs", "Job"]
CONTENT_PDP = {"verb", "subs", "adjv"}
MIN_VERSES = 3   # a pair needs >= this many distinct supporting verses to be trusted — 2 is too easily
                 # PMI-inflated by chance (rare pairs get extreme PMI from tiny base rates); verified
                 # empirically (1,180 pairs at >=3 vs 3,417 at >=2, much cleaner top-of-list)

# T'OMIM (Smiley 2026, CC BY 4.0, DOI 10.5281/zenodo.19135731) — 256 poetic half-verse pairs / 2,437
# word-level tokens, expert-curated from 5 named Hebrew-parallelism scholars (Berlin 2008, Fokkelman
# 2001, Kugel 1981, Watson 1994, Tsumura 2023), same ETCBC/BHSA node numbering we already use. Pinned
# to this Zenodo record version — never fetched from a mutable "latest" URL. Validated (2026-08):
# our own RAW (unfiltered) extraction recovers 86.8% of T'OMIM's in-scope pairs — confirms the
# detection method is sound; T'OMIM's own pairs become the trusted "confirmed" tier in the output
# (it's a curated SAMPLE, not exhaustive, so absence from T'OMIM isn't evidence of a wrong pair).
TOMIM_URL = "https://zenodo.org/records/19135731/files/poetic_pairs_word.parquet?download=1"
TOMIM_CACHE = OUT_DIR / "_tomim_poetic_pairs_word.parquet"


def _load_llm_edges(path: Path) -> tuple[set[frozenset], set[frozenset]]:
    """(syn, ant): sets of frozenset({H_a, H_b}) — same loader as build_semantic_neighbors.py's, so
    both scripts read the identical LLM syn/ant judgments. Duplicated (not imported) since the two
    modules otherwise have no dependency on each other."""
    syn, ant = set(), set()
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if ln.startswith("#") or ln.startswith("target"):
                continue
            p = ln.split("\t")
            if len(p) >= 3 and p[0].strip() != p[2].strip():
                (syn if p[1].strip() == "syn" else ant).add(frozenset((p[0].strip(), p[2].strip())))
    return syn, ant


def fetch_tomim() -> Path:
    """Idempotent pinned fetch — cache locally, never re-download once present (same discipline as
    every other external fetch in this pipeline: pin, don't track "latest")."""
    if TOMIM_CACHE.exists():
        return TOMIM_CACHE
    import urllib.request
    TOMIM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"[parallelism] fetching T'OMIM (pinned) -> {TOMIM_CACHE}", file=sys.stderr)
    urllib.request.urlretrieve(TOMIM_URL, TOMIM_CACHE)
    return TOMIM_CACHE


def load_tomim_pairs() -> dict[frozenset, tuple[int, str]]:
    """{frozenset({H_a, H_b}): (pair_id, verse_ref)} — word-level candidate pairs from T'OMIM's expert-
    verified poetic half-verse pairs (bag-of-content-words cross-product within each pair_id, same
    technique as our own extraction — T'OMIM verifies WHICH verses parallel; word alignment within
    them is still ours to derive). Not restricted to POETIC_BOOKS — T'OMIM covers more books than we
    scan (Isaiah, Jeremiah, Lamentations, ...) and that extra coverage is real, independent value."""
    import pyarrow.parquet as pq

    path = fetch_tomim()
    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    node2strong = dict(hbo.execute("SELECT node, strong FROM occurrence WHERE strong IS NOT NULL"))

    rows = pq.read_table(path).to_pylist()
    by_pair: dict[int, dict[str, set]] = collections.defaultdict(lambda: {"source": set(), "target": set()})
    verse_ref: dict[int, str] = {}
    for r in rows:
        verse_ref.setdefault(r["pair_id"], r["verse_ref"])
        if r["pdp"] not in CONTENT_PDP:
            continue
        hs = _hs(node2strong.get(r["nd"]))
        if hs:
            by_pair[r["pair_id"]][r["side"]].add(hs)

    out: dict[frozenset, tuple[int, str]] = {}
    for pid, sides in by_pair.items():
        for a, b in itertools.product(sides["source"], sides["target"]):
            if a != b:
                out[frozenset((a, b))] = (pid, verse_ref[pid])
    print(f"[parallelism] T'OMIM: {len(by_pair)} expert-verified verse-pairs -> {len(out)} word pairs",
          file=sys.stderr)
    return out


def _hs(strong) -> str | None:
    """hbo.db's occurrence.strong is ALREADY "H0835"-formatted text (not a bare int, unlike
    lexeme-spine.db/spine.db elsewhere in this pipeline) — pass through, just reject empty/junk."""
    if not strong or not strong.startswith("H"):
        return None
    return strong


def extract() -> tuple[dict[frozenset, set[tuple[str, int, int]]], collections.Counter, int]:
    """(pair_refs, side_freq, n_sides) — pair_refs: {frozenset({H_a, H_b}): {(book, chapter, verse), ...}}.
    side_freq: how many bicola-SIDES each Strong's appears in (needed for PMI — without this, very
    common words like H3605 "all"/H0430 "God" pair with everything by sheer volume, not genuine
    slot-correspondence; PMI normalizes by each word's own base-rate frequency)."""
    from tf.fabric import Fabric

    TF = Fabric(locations="~/text-fabric-data/github/ETCBC/bhsa/tf/2021")
    api = TF.load("otype book chapter verse pdp lex", silent="deep")
    F, L, T = api.F, api.L, api.T

    hbo = sqlite3.connect(f"file:{HBO}?mode=ro", uri=True)
    node2strong = dict(hbo.execute("SELECT node, strong FROM occurrence WHERE strong IS NOT NULL"))
    print(f"[parallelism] {len(node2strong)} BHSA node->strong entries loaded", file=sys.stderr)

    pair_refs: dict[frozenset, set[tuple[str, int, int]]] = collections.defaultdict(set)
    n_verses = n_bicola = n_sides = 0
    side_freq: collections.Counter = collections.Counter()
    for book in POETIC_BOOKS:
        book_node = T.nodeFromSection((book,))
        if book_node is None:
            print(f"[parallelism] book not found: {book}", file=sys.stderr)
            continue
        for vn in L.d(book_node, otype="verse"):
            n_verses += 1
            halves = L.d(vn, otype="half_verse")
            if len(halves) != 2:
                continue   # skip 3+-way and single-colon verses — bicola only for this pass
            n_bicola += 1
            sides = []
            for hv in halves:
                strongs = set()
                for w in L.d(hv, otype="word"):
                    if F.pdp.v(w) in CONTENT_PDP:
                        hs = _hs(node2strong.get(w))
                        if hs:
                            strongs.add(hs)
                sides.append(strongs)
                n_sides += 1
                for s in strongs:
                    side_freq[s] += 1
            _, chapter, verse = T.sectionFromNode(vn)
            for a, b in itertools.product(sides[0], sides[1]):
                if a != b:
                    pair_refs[frozenset((a, b))].add((book, chapter, verse))
    print(f"[parallelism] {n_verses} verses scanned in {POETIC_BOOKS}, {n_bicola} bicola (2-part), "
          f"{len(pair_refs)} raw candidate pairs", file=sys.stderr)
    return pair_refs, side_freq, n_sides


def build(use_tomim: bool = True) -> list[tuple[str, str, str, str, str, str]]:
    """[(strong_a, strong_b, tier, evidence, relation, sample_ref)] — two tiers, not one filtered list:

    tier=tomim_confirmed — expert-verified (Berlin/Fokkelman/Kugel/Watson/Tsumura via T'OMIM). Trusted
      as-is; not run through our own PMI/verse-count filter (that filter has no demonstrated precision
      benefit — see the 2026-08 PMI-sweep finding in domain-replacement-roadmap.md — so there's no
      reason to additionally gate an already-expert-verified pair through it).
    tier=detected — our own BHSA half_verse extraction, min_verses>=MIN_VERSES, NOT found in T'OMIM
      (T'OMIM is a curated sample, not exhaustive — absence there isn't evidence against a pair, so
      these are genuinely a second, lower-trust-but-real tier, not "rejected").

    relation: likely_synonym / likely_antonym (cross-referenced against the independent LLM syn/ant
    signal) / unclassified (parallelism found it, LLM has no opinion either way)."""
    import math

    pair_refs, side_freq, n_sides = extract()
    syn, ant = _load_llm_edges(LLM_EDGES)
    tomim = load_tomim_pairs() if use_tomim else {}

    def relation_of(pair: frozenset) -> str:
        return "likely_antonym" if pair in ant else "likely_synonym" if pair in syn else "unclassified"

    rows = []
    for pair, (pid, ref) in tomim.items():
        a, b = sorted(pair)
        rows.append((a, b, "tomim_confirmed", f"pair_id={pid}", relation_of(pair), ref))

    for pair, refs in pair_refs.items():
        if len(refs) < MIN_VERSES or pair in tomim:
            continue
        a, b = sorted(pair)
        p_ab = len(refs) / n_sides
        p_a, p_b = side_freq[a] / n_sides, side_freq[b] / n_sides
        pmi = math.log(p_ab / (p_a * p_b)) if p_a and p_b else 0.0
        sample = sorted(refs)[0]
        rows.append((a, b, "detected", f"n_verses={len(refs)},pmi={round(pmi, 3)}",
                     relation_of(pair), f"{sample[0]} {sample[1]}:{sample[2]}"))

    tier_tally = collections.Counter(r[2] for r in rows)
    rel_tally = collections.Counter(r[4] for r in rows)
    print(f"[parallelism] {len(rows)} total pairs (tomim_confirmed={tier_tally['tomim_confirmed']} "
          f"detected={tier_tally['detected']}) | synonym={rel_tally['likely_synonym']} "
          f"antonym={rel_tally['likely_antonym']} unclassified={rel_tally['unclassified']}", file=sys.stderr)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR / "parallelism_pairs.tsv")
    ap.add_argument("--no-tomim", action="store_true", help="skip T'OMIM merge (our own extraction only)")
    args = ap.parse_args()

    rows = build(use_tomim=not args.no_tomim)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write(f"# Biblical Hebrew poetic-parallelism word pairs — two tiers. tomim_confirmed: expert-\n"
                 f"# verified (Berlin/Fokkelman/Kugel/Watson/Tsumura via T'OMIM, CC BY 4.0, DOI "
                 f"10.5281/zenodo.19135731). detected: our own BHSA half_verse extraction ({'/'.join(POETIC_BOOKS)}\n"
                 f"# only, min_verses>={MIN_VERSES}), not found in T'OMIM (T'OMIM is a curated sample, not "
                 f"exhaustive — absence isn't evidence against a pair). Independent of UBS MARBLE and Hebrew\n"
                 f"# WordNet; the LLM signal is used only to LABEL relation, never to find pairs. `relation`:\n"
                 f"# likely_synonym / likely_antonym / unclassified (parallelism found it, LLM has no opinion).\n"
                 f"# See build_parallelism_pairs.py.\n")
        fh.write("strong_a\tstrong_b\ttier\tevidence\trelation\tsample_ref\n")
        for a, b, tier, evidence, relation, ref in rows:
            fh.write(f"{a}\t{b}\t{tier}\t{evidence}\t{relation}\t{ref}\n")
    print(f"[parallelism] -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
