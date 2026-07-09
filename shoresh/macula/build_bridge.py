#!/usr/bin/env python3
"""Build the BHSA ↔ MACULA occurrence bridge — internal-docs/bhsa-macula-bridge.md.

Maps hbo.db `node` ↔ macula-spine.db `key` per OT occurrence, so BHSA disambiguated **senses** ride
onto MACULA lexeme-anchored tokens (the keystone for anchoring on the widest/finest original).
OT/Hebrew only — hbo.db is Hebrew; there is no BHSA sense layer for Greek.

Both corpora are WLC-derived, so this is a near-parallel same-text alignment. Anchor-then-fill:
 1. FAST PATH — equal token count and every BHSA-strong position agrees with MACULA → map the whole
    verse positionally (conf 1.0). (~half of OT verses.)
 2. STRONG-IN-ORDER — else the nth BHSA token bearing Strong's S ↔ the nth MACULA token with rollup
    Strong's S (conf 0.9). This is the aligner's `hebrew_source` join, reused. Senses live on
    content words, which is exactly what this matches reliably.
Unmatched tokens are left unbridged — never fabricated (function morphemes carry no sense, so the
sense payoff is unaffected).

  python -m macula.build_bridge          # -> macula/bhsa-macula-bridge.db
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spine.common import load_equivalences
from macula.build_spine_words import rollup_strong

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HBO_DEFAULT = ROOT / "resources" / "occurrences" / "hbo.db"
MACULA_DEFAULT = HERE / "macula-spine.db"
OUT_DEFAULT = HERE / "bhsa-macula-bridge.db"


def _verse_map(macula: sqlite3.Connection):
    """(book,chapter,verse) -> [(key, rollup_strong)] in document (key) order, Hebrew OT only."""
    eq = load_equivalences()
    by_verse: dict[tuple, list] = collections.defaultdict(list)
    for book, ch, v, key, strong in macula.execute(
            "SELECT book, chapter, verse, key, strong FROM macula_words "
            "WHERE lang!='grc' ORDER BY book, chapter, verse, key"):
        by_verse[(book, ch, v)].append((key, rollup_strong(strong, "hbo", eq)))
    return by_verse


def bridge_verse(bhsa: list, mac: list) -> list[tuple]:
    """bhsa: [(node, strong)], mac: [(key, strong)] — both ordered. -> [(node, key, method, conf)]."""
    # FAST PATH: same length and every BHSA-strong position matches MACULA at that position.
    if len(bhsa) == len(mac) and all(
            bs is None or bs == mac[i][1] for i, (_, bs) in enumerate(bhsa)):
        return [(node, mac[i][0], "positional", 1.0) for i, (node, _) in enumerate(bhsa)]

    # STRONG-IN-ORDER: pair the nth occurrence of each Strong's value on each side.
    mac_by_s: dict[int, list] = collections.defaultdict(list)
    for key, s in mac:
        if s is not None:
            mac_by_s[s].append(key)
    seen: dict[int, int] = collections.defaultdict(int)
    out = []
    for node, s in bhsa:
        if s is None:
            continue
        keys = mac_by_s.get(s, [])
        i = seen[s]
        if i < len(keys):
            out.append((node, keys[i], "strong-in-order", 0.9))
            seen[s] = i + 1
    return out


def build(hbo_path: Path, macula_path: Path, out_path: Path):
    hbo = sqlite3.connect(f"file:{hbo_path}?mode=ro", uri=True)
    macula = sqlite3.connect(f"file:{macula_path}?mode=ro", uri=True)
    eq = load_equivalences()
    mac_verses = _verse_map(macula)

    # BHSA occurrences per verse, in node order, with whether the node carries a sense (the payoff).
    rows = collections.defaultdict(list)      # ref -> [(node, strong)]
    sense_nodes: set[int] = set()
    for node, ref, strong, sense in hbo.execute(
            "SELECT node, ref, strong, sense FROM occurrence ORDER BY ref, node"):
        rows[ref].append((node, rollup_strong(strong, "hbo", eq)))
        if sense not in (None, ""):
            sense_nodes.add(node)

    out_path.unlink(missing_ok=True)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE bridge (
            ref INTEGER NOT NULL, node INTEGER NOT NULL, key TEXT NOT NULL,
            method TEXT NOT NULL, conf REAL NOT NULL,
            PRIMARY KEY (ref, node)
        );
        CREATE INDEX ix_bridge_key ON bridge(key);
        CREATE TABLE bridge_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    out, methods = [], collections.Counter()
    bhsa_total = bridged = sense_total = sense_bridged = 0
    for ref, bhsa in rows.items():
        b, c, v = ref // 1_000_000, ref // 1000 % 1000, ref % 1000
        mac = mac_verses.get((_bhsa_book(b), c, v), [])
        bhsa_total += len(bhsa)
        sense_total += sum(1 for n, _ in bhsa if n in sense_nodes)
        if not mac:
            continue
        pairs = bridge_verse(bhsa, mac)
        bridged_nodes = {n for n, *_ in pairs}
        bridged += len(pairs)
        sense_bridged += sum(1 for n in bridged_nodes if n in sense_nodes)
        for node, key, method, conf in pairs:
            out.append((ref, node, key, method, conf))
            methods[method] += 1

    db.executemany("INSERT INTO bridge VALUES (?,?,?,?,?)", out)
    meta = {
        "hbo_sha256": hashlib.sha256(hbo_path.read_bytes()).hexdigest(),
        "macula_spine_sha256": hashlib.sha256(macula_path.read_bytes()).hexdigest(),
        "bhsa_nodes": str(bhsa_total), "bridged": str(bridged),
        "coverage_nodes": f"{100*bridged/max(1,bhsa_total):.1f}%",
        "sense_nodes": str(sense_total), "sense_bridged": str(sense_bridged),
        "coverage_sense": f"{100*sense_bridged/max(1,sense_total):.1f}%",
        "methods": ", ".join(f"{k}={n}" for k, n in methods.most_common()),
    }
    db.executemany("INSERT INTO bridge_meta VALUES (?,?)", list(meta.items()))
    db.commit()
    db.close()
    return meta


# BHSA ref book-number (1..39, Protestant) -> MACULA USFM code. Both are OT-only here.
_OT_CODES = ["GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
             "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
             "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
             "HAG", "ZEC", "MAL"]


def _bhsa_book(num: int) -> str:
    return _OT_CODES[num - 1] if 1 <= num <= len(_OT_CODES) else ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the BHSA↔MACULA occurrence bridge.")
    ap.add_argument("--hbo", type=Path, default=HBO_DEFAULT)
    ap.add_argument("--macula", type=Path, default=MACULA_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = ap.parse_args()
    for p in (args.hbo, args.macula):
        if not p.exists():
            sys.exit(f"missing input {p}")

    m = build(args.hbo, args.macula, args.out)
    print(f"bridge -> {args.out}")
    print(f"  BHSA nodes bridged : {m['bridged']}/{m['bhsa_nodes']} ({m['coverage_nodes']})")
    print(f"  SENSE-bearing nodes: {m['sense_bridged']}/{m['sense_nodes']} ({m['coverage_sense']})  <- the payoff")
    print(f"  methods: {m['methods']}")
    print(f"  build sha256: {hashlib.sha256(args.out.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
