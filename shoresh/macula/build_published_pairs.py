#!/usr/bin/env python3
"""Merge the three publication-confidence levers into one final published dataset.

Lever #1 (build_confidence_tiers.py): pairs where >=2 INDEPENDENT signal families agree.
Lever #2 (verify_pairs_llm.py): the remaining single-signal-family pairs, individually judged by an
LLM (biblical-Hebrew lexicographer prompt, strict).
Lever #3 (build_sefer_hashorashim.py + verify_pairs_llm.py): candidates from Radak's Sefer HaShorashim
(Public Domain, medieval rabbinic root dictionary), LLM-verified the same way as lever #2.

Historically each lever was scored against SDBH `core`-domain agreement (73.4% / 69.6% / 74.1% —
see domain-replacement-roadmap.md for that record). SDBH is retired as the validation yardstick as of
2026-08-14 (internal-docs/text-anchored-semantics-plan.md); `--validate` now scores against the
text-anchored intrinsic yardstick instead. FAMILY_GATE below still carries its SDBH-era value pending
re-derivation under the new yardstick.

A pair earns publication three ways: cross-signal agreement (no LLM needed), explicit LLM confirmation
on single-signal candidates, or LLM confirmation on Sefer HaShorashim candidates. Neither lever alone is
the whole story — this is their union, deduplicated, with per-pair provenance kept so downstream
consumers can see WHICH gate(s) a pair passed (pairs passing multiple gates are the highest-confidence
subset).

  python -m macula.build_published_pairs
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TIERS = ROOT / "resources" / "semantic_neighbors" / "confidence_tiers.tsv"
LLM_VERIFICATION = ROOT / "resources" / "semantic_neighbors" / "llm_pair_verification.tsv"
SEFER_HASHORASHIM_VERIFICATION = ROOT / "resources" / "sefer_hashorashim" / "llm_pair_verification.tsv"
OUT_DIR = ROOT / "resources" / "semantic_neighbors"

FAMILY_GATE = 2   # >=2 independent signal families — see build_confidence_tiers.py.
                  # Re-derived 2026-08-14 under the text-anchored intrinsic yardstick (SDBH retired,
                  # see internal-docs/text-anchored-semantics-plan.md) and reaffirmed: >=1 family does
                  # NOT clear a frequency-matched random baseline on held-out slot-filler co-occurrence
                  # (4.9% vs 5.9%), >=2 clearly does (14.2% vs 9.4%), >=3 further still (20.0% vs 9.0%)
                  # but at a steep pair-count cost (816 vs 3,225). 2 remains the right cutoff.


def load_family_tiers(tiers: Path = TIERS) -> dict[frozenset, tuple[int, str]]:
    """{frozenset({a,b}): (n_families, families_csv)}"""
    out = {}
    if not tiers.exists():
        return out
    with tiers.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 4:
                out[frozenset((p[0], p[1]))] = (int(p[2]), p[3])
    return out


def load_llm_verdicts() -> dict[frozenset, str]:
    out = {}
    if not LLM_VERIFICATION.exists():
        return out
    with LLM_VERIFICATION.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                out[frozenset((p[0], p[1]))] = p[2]
    return out


def load_sefer_hashorashim_verdicts() -> dict[frozenset, str]:
    out = {}
    if not SEFER_HASHORASHIM_VERIFICATION.exists():
        return out
    with SEFER_HASHORASHIM_VERIFICATION.open(encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("strong_a\t"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                out[frozenset((p[0], p[1]))] = p[2]
    return out


def build(tiers: Path = TIERS, llm_needs_tier_support: bool = False,
          exclude_families: frozenset = frozenset()) -> list[tuple[str, str, str, int, str]]:
    """[(strong_a, strong_b, gate, n_families, llm_verdict)] — gate is a "+"-joined subset of
    {cross_signal, llm_verified, sefer_hashorashim_verified}. llm_needs_tier_support: keep an
    llm_verified pair only if the tiers (the pack being published) link it by at least one signal; used for
    the BHSA-free release, whose LLM-verification candidates were originally drawn from BHSA-influenced
    tiers."""
    families = load_family_tiers(tiers)
    if exclude_families:     # e.g. "corroborated" (Wiktionary, CC BY-SA) for a strictly CC0 release
        families = {p: (len([f for f in fs.split("|") if f and f not in exclude_families]),
                        "|".join(f for f in fs.split("|") if f and f not in exclude_families))
                    for p, (n, fs) in families.items()}
        families = {p: v for p, v in families.items() if v[0] > 0}
    verdicts = load_llm_verdicts()
    sefer_verdicts = load_sefer_hashorashim_verdicts()

    cross_signal_pairs = {p for p, (n, _) in families.items() if n >= FAMILY_GATE}
    llm_yes_pairs = {p for p, v in verdicts.items() if v == "yes" and (not llm_needs_tier_support or p in families)}
    sefer_yes_pairs = {p for p, v in sefer_verdicts.items() if v == "yes"}
    published = cross_signal_pairs | llm_yes_pairs | sefer_yes_pairs

    rows = []
    for pair in published:
        a, b = sorted(pair)
        n_fam = families.get(pair, (0, ""))[0]
        verdict = verdicts.get(pair) or sefer_verdicts.get(pair, "")
        gates = []
        if pair in cross_signal_pairs:
            gates.append("cross_signal")
        if pair in llm_yes_pairs:
            gates.append("llm_verified")
        if pair in sefer_yes_pairs:
            gates.append("sefer_hashorashim_verified")
        rows.append((a, b, "+".join(gates), n_fam, verdict))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tiers", type=Path, default=TIERS)
    ap.add_argument("--llm-needs-tier-support", action="store_true")
    ap.add_argument("--exclude-families", default="", help="comma-separated signal families to ignore")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "published_pairs.tsv")
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()

    rows = build(args.tiers, args.llm_needs_tier_support,
                 frozenset(f for f in args.exclude_families.split(",") if f))
    multi = sum(1 for r in rows if "+" in r[2])
    print(f"[published-pairs] {len(rows)} total pairs (cross_signal only: "
          f"{sum(1 for r in rows if r[2] == 'cross_signal')}, llm_verified only: "
          f"{sum(1 for r in rows if r[2] == 'llm_verified')}, sefer_hashorashim_verified only: "
          f"{sum(1 for r in rows if r[2] == 'sefer_hashorashim_verified')}, multi-gate: {multi})",
          file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write("# Published Hebrew semantic-neighbor pairs: the union of three publication gates.\n"
                  "# cross_signal = >=2 independent signal families agree; llm_verified = explicit LLM pairwise\n"
                  "# judgment on single-signal candidates; sefer_hashorashim_verified = LLM-verified candidates\n"
                  "# from Radak's Sefer HaShorashim (Public Domain). `gate` shows which check(s) a pair passed;\n"
                  "# pairs passing several gates are the highest-confidence subset. CC0. See\n"
                  f"# build_published_pairs.py. Tiers: {args.tiers.parent.name}/{args.tiers.name}.\n")
        fh.write("strong_a\tstrong_b\tgate\tn_families\tllm_verdict\n")
        for a, b, gate, n_fam, verdict in sorted(rows, key=lambda r: (r[0], r[1])):
            fh.write(f"{a}\t{b}\t{gate}\t{n_fam}\t{verdict}\n")
    print(f"[published-pairs] -> {args.out}", file=sys.stderr)

    if args.validate:
        from macula.intrinsic_yardstick import Yardstick, validate_pairs

        ys = Yardstick()
        for label, pred in (("all published", lambda r: True),
                            ("cross_signal only", lambda r: r[2] == "cross_signal"),
                            ("llm_verified only", lambda r: r[2] == "llm_verified"),
                            ("sefer_hashorashim_verified only",
                             lambda r: r[2] == "sefer_hashorashim_verified"),
                            ("multi-gate", lambda r: "+" in r[2])):
            pairs = [(a, b) for a, b, gate, n_fam, verdict in rows if pred((a, b, gate, n_fam, verdict))]
            validate_pairs(ys, label, pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
