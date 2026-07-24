#!/usr/bin/env python3
"""Enrich lexeme-spine.db with BHSA phrase-level syntax via the occurrence bridge — same pattern
as enrich_spine_senses.py, a sibling enrichment over the same bridge.

`bhsa-macula-bridge.db` maps MACULA `key` ↔ BHSA `node`; resources/occurrences/hbo_syntax.db (see
extract_hbo_syntax.py) holds BHSA's own phrase/function/rela per node. This adds `phrase_id` /
`function` / `rela` columns to `lexeme-spine.db`:

- `phrase_id` — the containing BHSA phrase's node id, a ready-made construct-chain / multi-word
  syntactic-unit grouping key (any tokens sharing the same phrase_id belong to the same phrase —
  e.g. a construct chain like "Spirit of God"). Requested by strongs-aligner as `chain_id`; named
  `phrase_id` here since a BHSA phrase is the general grouping unit (any phrase type), not
  construct chains specifically — `function`/`rela` carry the construct-specific meaning.
- `function` — the phrase's syntactic role (Subj/Pred/Objc/Time/Loca/Adju/Cmpl/...). Genuine,
  100%-coverage Hebrew syntactic-role data — MACULA's own `role` column has none for Hebrew at
  all (see build_spine_words.py's docstring).
- `rela` — the word's own subphrase relation where present (`NA`=chain head, `rec`=construct-
  governed dependent, `par`=coordination, ...).

OT/Hebrew only (BHSA has no Greek layer). `resources/occurrences/hbo_syntax.db` is a gitignored,
regenerable build artifact (same as hbo.db) — extract_hbo_syntax.py needs the local BHSA
text-fabric checkout, an occasional/heavy dependency not part of the routine build.

Run after build_spine_words + build_bridge:
  python -m macula.build_spine_words && python -m macula.build_bridge && python -m macula.enrich_spine_syntax
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
HBO_SYNTAX_DEFAULT = ROOT / "resources" / "occurrences" / "hbo_syntax.db"


def _add_col(db: sqlite3.Connection, name: str, decl: str) -> None:
    cols = {r[1] for r in db.execute("PRAGMA table_info(spine_words)")}
    if name not in cols:
        db.execute(f"ALTER TABLE spine_words ADD COLUMN {name} {decl}")


def enrich(spine_path: Path, bridge_path: Path, hbo_syntax_path: Path) -> tuple[int, int]:
    db = sqlite3.connect(spine_path)
    for c, d in (("phrase_id", "INTEGER"), ("function", "TEXT"), ("rela", "TEXT")):
        _add_col(db, c, d)

    hbo_syntax = sqlite3.connect(f"file:{hbo_syntax_path}?mode=ro", uri=True)
    syntax_by_node = {node: (phrase, func, rela) for node, phrase, func, rela in hbo_syntax.execute(
        "SELECT node, phrase, function, rela FROM syntax")}

    bridge = sqlite3.connect(f"file:{bridge_path}?mode=ro", uri=True)
    updates = []
    for node, key in bridge.execute("SELECT node, key FROM bridge"):
        s = syntax_by_node.get(node)
        if s and s[0] is not None:
            updates.append((s[0], s[1], s[2], key))

    db.executemany(
        "UPDATE spine_words SET phrase_id=?, function=?, rela=? WHERE key=?", updates)
    db.commit()
    total = db.execute("SELECT count(*) FROM spine_words").fetchone()[0]
    withsyntax = db.execute("SELECT count(*) FROM spine_words WHERE phrase_id IS NOT NULL").fetchone()[0]
    db.close()
    return withsyntax, total


def main() -> None:
    ap = argparse.ArgumentParser(description="Add BHSA phrase-level syntax to lexeme-spine via the bridge.")
    ap.add_argument("--spine", type=Path, default=SPINE_DEFAULT)
    ap.add_argument("--bridge", type=Path, default=BRIDGE_DEFAULT)
    ap.add_argument("--hbo-syntax", type=Path, default=HBO_SYNTAX_DEFAULT)
    args = ap.parse_args()
    for p in (args.spine, args.bridge, args.hbo_syntax):
        if not p.exists():
            sys.exit(f"missing input {p} — run build_spine_words + build_bridge "
                      f"(+ extract_hbo_syntax for hbo_syntax.db) first")

    withsyntax, total = enrich(args.spine, args.bridge, args.hbo_syntax)
    print(f"enriched {args.spine.name}: {withsyntax}/{total} tokens now carry BHSA phrase syntax "
          f"({100*withsyntax/max(1,total):.1f}%)")


if __name__ == "__main__":
    main()
