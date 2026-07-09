#!/usr/bin/env python3
"""Enrich lexeme-spine.db with disambiguated BHSA senses via the occurrence bridge.

The keystone made concrete: `bhsa-macula-bridge.db` maps MACULA `key` ↔ BHSA `node`, and `hbo.db`
holds the per-occurrence sense. This adds `sense` / `sense_conf` / `sense_source` columns to
`lexeme-spine.db`, so a consumer (e.g. strongs-aligner) gets homograph-precise sense straight off the
one pinned artifact — no hbo.db, no bridge join on its side. OT/Hebrew only (senses are Hebrew).

Run after build_spine_words + build_bridge:
  python -m macula.build_spine_words && python -m macula.build_bridge && python -m macula.enrich_spine_senses
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPINE_DEFAULT = HERE / "lexeme-spine.db"
BRIDGE_DEFAULT = HERE / "bhsa-macula-bridge.db"
HBO_DEFAULT = ROOT / "resources" / "occurrences" / "hbo.db"


def _add_col(db: sqlite3.Connection, name: str, decl: str) -> None:
    cols = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    if name not in cols:
        db.execute(f"ALTER TABLE spine_words ADD COLUMN {name} {decl}")


def enrich(spine_path: Path, bridge_path: Path, hbo_path: Path) -> tuple[int, int]:
    db = sqlite3.connect(spine_path)
    # `lex` + `stem` (binyan) carried alongside `sense` so a consumer emits shoresh's canonical
    # sense key (lex, stem, sense) natively — BHSA-anchored, binyan-aware (senses/hbo_lex.tsv).
    for c, d in (("lex", "TEXT"), ("stem", "TEXT"),
                 ("sense", "TEXT"), ("sense_conf", "REAL"), ("sense_source", "TEXT")):
        _add_col(db, c, d)

    hbo = sqlite3.connect(f"file:{hbo_path}?mode=ro", uri=True)
    occ_by_node = {node: (lex, stem or "", sense, conf, src)
                   for node, lex, stem, sense, conf, src in hbo.execute(
        "SELECT node, lex, stem, sense, sense_conf, sense_source FROM occurrence "
        "WHERE sense IS NOT NULL AND sense != ''")}

    bridge = sqlite3.connect(f"file:{bridge_path}?mode=ro", uri=True)
    updates = []
    for node, key in bridge.execute("SELECT node, key FROM bridge"):
        o = occ_by_node.get(node)
        if o:
            updates.append((o[0], o[1], o[2], o[3], o[4], key))

    db.executemany(
        "UPDATE spine_words SET lex=?, stem=?, sense=?, sense_conf=?, sense_source=? WHERE key=?",
        updates)
    db.commit()
    total = db.execute("SELECT count(*) FROM spine_words").fetchone()[0]
    withsense = db.execute("SELECT count(*) FROM spine_words WHERE sense IS NOT NULL").fetchone()[0]
    db.close()
    return withsense, total


def main() -> None:
    ap = argparse.ArgumentParser(description="Add BHSA senses to lexeme-spine via the bridge.")
    ap.add_argument("--spine", type=Path, default=SPINE_DEFAULT)
    ap.add_argument("--bridge", type=Path, default=BRIDGE_DEFAULT)
    ap.add_argument("--hbo", type=Path, default=HBO_DEFAULT)
    args = ap.parse_args()
    for p in (args.spine, args.bridge, args.hbo):
        if not p.exists():
            sys.exit(f"missing input {p} — run build_spine_words + build_bridge first")

    withsense, total = enrich(args.spine, args.bridge, args.hbo)
    print(f"enriched {args.spine.name}: {withsense}/{total} tokens now carry a BHSA sense "
          f"({100*withsense/max(1,total):.1f}%)")


if __name__ == "__main__":
    main()
