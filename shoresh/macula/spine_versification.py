"""Declare a spine's verse numbering in its spine_meta (computed from the spine, not assumed).

Consumers pair spine verses with target-edition verses, so they must know how the spine is numbered. The
lexeme-aligner assumed KJV numbering, which paired ~9% of OT verses with the wrong target verse (Oct 2026).
This records, from the spine's own chapter/verse shape:

  versification_ot          the .vrs scheme the OT matches in every chapter (Hebrew spines: "org"), or the
                            closest one with "(differs in N chapters)"
  versification_nt          the NT edition's own numbering (e.g. "nestle1904")
  versification_nt_vs_eng   NT chapters that differ from eng.vrs, as JSON: {"BOOK c": {eng_verses, spine_last,
                            missing: verse numbers absent (Acts 8:37), beyond_eng: numbers past the English
                            range (Nestle 1904 Mark 16:99 = the shorter ending)}}
  versification_note        how to read the above

  python -m macula.spine_versification macula/lexeme-spine-macula.db:nestle1904 macula/rp2018-spine.db:rp2018
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

VRS = Path(__file__).resolve().parents[1] / "versification" / "data" / "vrs"
NT_BOOKS = {"MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL", "1TH", "2TH",
            "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV"}


def _vrs(name: str) -> dict:
    out = {}
    for ln in (VRS / f"{name}.vrs").read_text(encoding="utf-8").splitlines():
        p = ln.split()
        if p and not ln.startswith("#") and len(p) > 1 and ":" in p[1]:
            out[p[0]] = {int(t.split(":")[0]): int(t.split(":")[1]) for t in p[1:]}
    return out


def declaration(db: sqlite3.Connection, nt_scheme: str | None) -> dict[str, str]:
    verses = collections.defaultdict(lambda: collections.defaultdict(set))
    for b, c, v in db.execute("SELECT DISTINCT book, chapter, verse FROM spine_words"):
        verses[b][c].add(v)
    ot = [b for b in verses if b not in NT_BOOKS]
    nt = [b for b in verses if b in NT_BOOKS]
    eng = _vrs("eng")
    out: dict[str, str] = {}
    if ot:
        best = None
        for name in ("org", "eng"):
            s = _vrs(name)
            bad = [(b, c) for b in ot for c in verses[b] if s.get(b, {}).get(c) != max(verses[b][c])]
            if best is None or len(bad) < len(best[1]):
                best = (name, bad)
        n_ch = sum(len(verses[b]) for b in ot)
        out["versification_ot"] = best[0] if not best[1] else f"{best[0]} (differs in {len(best[1])} of {n_ch} chapters)"
    if nt:
        diffs = {}
        for b in sorted(nt):
            for c in sorted(verses[b]):
                vs = verses[b][c]
                n_eng = eng.get(b, {}).get(c, 0)
                inside = [v for v in vs if v <= n_eng]
                d = {"eng_verses": n_eng, "spine_last": max(inside) if inside else 0}
                missing = [v for v in range(1, d["spine_last"] + 1) if v not in vs]   # e.g. ACT 8:37
                beyond = sorted(v for v in vs if v > n_eng)                          # e.g. MRK 16:99
                if missing:
                    d["missing"] = missing
                if beyond:
                    d["beyond_eng"] = beyond
                if missing or beyond or d["spine_last"] != n_eng:                   # 2CO 13 ends at 13
                    diffs[f"{b} {c}"] = d
        out["versification_nt"] = nt_scheme or "unspecified"
        out["versification_nt_vs_eng"] = json.dumps(diffs, ensure_ascii=False, separators=(",", ":"))
    out["versification_note"] = (
        "Verse numbers in spine_words follow these schemes (data/vrs/*.vrs in bcv-query shoresh/versification; "
        "org = Hebrew/BHS numbering, eng = English). versification_nt_vs_eng lists the NT chapters that differ "
        "from eng.vrs: verses missing in this edition (e.g. ACT 8:37), numbers beyond the English range (MRK 16:99 "
        "= the shorter ending in Nestle 1904), or a chapter ending earlier (2CO 13:13 = eng 13:13-14). Map to a "
        "target edition's numbering through a crosswalk; do not assume KJV.")
    return out


def declare(path: Path, nt_scheme: str | None) -> dict[str, str]:
    with sqlite3.connect(path) as db:
        d = declaration(db, nt_scheme)
        db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)", list(d.items()))
    return d


def main() -> int:
    for arg in sys.argv[1:]:
        path, _, nt = arg.partition(":")
        d = declare(Path(path), nt or None)
        print(f"{path}: " + "; ".join(f"{k}={v[:120]}" for k, v in d.items() if k != "versification_note"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
