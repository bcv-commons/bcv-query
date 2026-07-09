#!/usr/bin/env python3
"""LXX cross-testament NT-gap dictionary — a per-language prior for the aligner's gloss/neural runs.

A language's OT attestation is large, its NT sparser. The LXX bridge lets us carry that language's own
OT surfaces into its NT: if the language renders Hebrew lexeme H as surface S (from the published
`aligned-lex` OT rows), and the LXX renders H into Greek G (`lxx_bridge`), then S is a candidate NT
rendering for G — a prior the gloss/neural run can lean on where the language's own NT eflomal was thin.

eflomal alone can't do this (it aligns OT and NT independently); the cross-testament transfer is the
monorepo-unique leverage. Output is a PRIOR (noisy candidates), not truth — the aligner's run confirms it.

  python3 scripts/build_nt_lex_priors.py --aligned-lex-dir /tmp/aligned-lex --iso fra ind
  # -> resources/prior_nt_lex/<iso>.parquet  (grc_lexeme, grc_strong, candidate_surface, via_hebrew,
  #                                            ot_count, share, nt_confirmed, nt_total)
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
LXX = ROOT / "resources" / "lxx_bridge.tsv"
OUT_DIR = ROOT / "resources" / "prior_nt_lex"
MIN_COUNT = 2      # drop candidate surfaces attested fewer times (noise)
TOPK = 15          # candidates kept per Greek lexeme


def load_bridge():
    """greek_strong -> [(hebrew_strong, lxx_count)] — how the LXX renders each Hebrew into Greek."""
    g2h = collections.defaultdict(list)
    for line in LXX.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        if len(p) >= 3:
            g2h[p[1].strip()].append((p[0].strip(), int(p[2]) if p[2].isdigit() else 1))
    return g2h


def build_iso(iso: str, aligned_dir: Path, g2h) -> Path | None:
    part = aligned_dir / f"iso={iso}" / "data.parquet"
    if not part.exists():
        print(f"[nt-priors] no aligned-lex for {iso} at {part}"); return None
    t = pq.read_table(part).to_pylist()

    ot_surf = collections.defaultdict(collections.Counter)   # H strong -> surface -> count
    nt_att = collections.defaultdict(set)                    # G strong -> {surfaces attested in NT}
    nt_tot = collections.Counter()                           # G strong -> total NT attestation count
    grc_lex = {}                                             # G strong -> its grc lexeme (if NT-attested)
    for r in t:
        s, surf, c = r["strong"], (r["surface"] or "").strip(), r["count"]
        if not s or not surf:
            continue
        if s.startswith("H"):
            ot_surf[s][surf] += c
        elif s.startswith("G"):
            nt_att[s].add(surf); nt_tot[s] += c
            grc_lex.setdefault(s, r["lexeme"])

    rows = []
    for g, hs in g2h.items():
        cand = collections.Counter()
        via = collections.defaultdict(set)
        for h, _lxxc in hs:
            for surf, c in ot_surf.get(h, {}).items():
                cand[surf] += c
                via[surf].add(h)
        total = sum(cand.values())
        if not total:
            continue
        lexeme = grc_lex.get(g) or f"grc:{int(g[1:])}"       # constructed if this G is an NT gap
        for surf, c in cand.most_common(TOPK):
            if c < MIN_COUNT:
                continue
            rows.append((lexeme, g, surf, "|".join(sorted(via[surf])[:3]),
                         c, round(c / total, 4), surf in nt_att.get(g, set()), nt_tot.get(g, 0)))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"{iso}.parquet"
    cols = list(zip(*rows)) if rows else ([],) * 8
    pq.write_table(pa.table({
        "grc_lexeme": pa.array(cols[0], pa.string()), "grc_strong": pa.array(cols[1], pa.string()),
        "candidate_surface": pa.array(cols[2], pa.string()), "via_hebrew": pa.array(cols[3], pa.string()),
        "ot_count": pa.array(cols[4], pa.int32()), "share": pa.array(cols[5], pa.float32()),
        "nt_confirmed": pa.array(cols[6], pa.bool_()), "nt_total": pa.array(cols[7], pa.int32()),
    }), dest, compression="zstd")
    gaps = sum(1 for r in rows if r[7] == 0)        # candidates for Greek lexemes with NO NT attestation
    print(f"[nt-priors] {iso}: {len(rows)} candidates for {len({r[1] for r in rows})} Greek lexemes "
          f"({gaps} rows target NT GAPS) -> {dest}")
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--aligned-lex-dir", type=Path, required=True,
                    help="dir holding iso=<iso>/data.parquet (a local mirror of bcv-commons/aligned-lex)")
    ap.add_argument("--iso", nargs="+", required=True)
    a = ap.parse_args()
    g2h = load_bridge()
    print(f"[nt-priors] lxx_bridge: {len(g2h)} Greek strongs with Hebrew sources")
    for iso in a.iso:
        build_iso(iso, a.aligned_lex_dir, g2h)


if __name__ == "__main__":
    main()
