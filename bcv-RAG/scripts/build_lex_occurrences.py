#!/usr/bin/env python3
"""Phase 1 — build the per-occurrence lex+stem sidecar from BHSA (the foundation for
lex-anchored retrieval and, later, per-occurrence WSD).

For every Hebrew/Aramaic word in BHSA, record its stable occurrence id (the BHSA word
node — ETCBC already disambiguated homographs), its lex-id (e.g. QDC[), verbal stem
(vs: qal/nif/…), part of speech, canonical ref (BBCCCVVV), and bridged Strong's. Three
sense* columns are reserved EMPTY now so the WSD layer is a pure re-tag later, not a
re-ingest.

Output: resources/occurrences/hbo.db (sqlite; a build artifact, regenerable from BHSA).
Run with the shoresh venv (it has cfabric + the local BHSA text-fabric corpus):

  shoresh/.venv/bin/python bcv-RAG/scripts/build_lex_occurrences.py
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import cfabric

ROOT = Path(__file__).resolve().parent.parent.parent
BHSA = os.path.expanduser("~/text-fabric-data/github/ETCBC/bhsa/tf/2021")
OUT = ROOT / "resources/occurrences/hbo.db"
STRONG_TSV = ROOT / "resources/word_freq/hbo_strong.tsv"

# ETCBC book name → (USFM code, Protestant canonical number 1..39). BHSA is OT-only and
# ordered by the Hebrew canon, so we map by NAME, not position.
BOOKS = {
    "Genesis": ("GEN", 1), "Exodus": ("EXO", 2), "Leviticus": ("LEV", 3),
    "Numbers": ("NUM", 4), "Deuteronomy": ("DEU", 5), "Joshua": ("JOS", 6),
    "Judges": ("JDG", 7), "Ruth": ("RUT", 8), "1_Samuel": ("1SA", 9),
    "2_Samuel": ("2SA", 10), "1_Kings": ("1KI", 11), "2_Kings": ("2KI", 12),
    "1_Chronicles": ("1CH", 13), "2_Chronicles": ("2CH", 14), "Ezra": ("EZR", 15),
    "Nehemiah": ("NEH", 16), "Esther": ("EST", 17), "Job": ("JOB", 18),
    "Psalms": ("PSA", 19), "Proverbs": ("PRO", 20), "Ecclesiastes": ("ECC", 21),
    "Song_of_songs": ("SNG", 22), "Isaiah": ("ISA", 23), "Jeremiah": ("JER", 24),
    "Lamentations": ("LAM", 25), "Ezekiel": ("EZK", 26), "Daniel": ("DAN", 27),
    "Hosea": ("HOS", 28), "Joel": ("JOL", 29), "Amos": ("AMO", 30),
    "Obadiah": ("OBA", 31), "Jonah": ("JON", 32), "Micah": ("MIC", 33),
    "Nahum": ("NAM", 34), "Habakkuk": ("HAB", 35), "Zephaniah": ("ZEP", 36),
    "Haggai": ("HAG", 37), "Zechariah": ("ZEC", 38), "Malachi": ("MAL", 39),
}


def _strong_bridge() -> dict[str, str]:
    """lex-id → padded Strong's (e.g. QDC[ → H6942), from word_freq/hbo_strong.tsv."""
    out: dict[str, str] = {}
    with STRONG_TSV.open(encoding="utf-8") as fh:
        next(fh, None)
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    return out


def main() -> None:
    print(f"loading BHSA from {BHSA} …")
    api = cfabric.Fabric(locations=BHSA, silent="deep").loadAll(silent="deep")
    F, T, L = api.F, api.T, api.L
    bridge = _strong_bridge()

    # Hebrew clause text per word — the per-occurrence CONTEXT we cluster senses on (cached
    # by clause node so a clause's text is built once, not once per word in it).
    clause_text: dict[int, str] = {}

    def _context(w: int) -> str:
        cl = L.u(w, otype="clause")
        if not cl:
            return ""
        c = cl[0]
        if c not in clause_text:
            clause_text[c] = "".join((F.g_word_utf8.v(cw) or "") + (F.trailer_utf8.v(cw) or "")
                                     for cw in L.d(c, otype="word")).strip()
        return clause_text[c]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    con = sqlite3.connect(OUT)
    con.execute("""CREATE TABLE occurrence(
        node INTEGER PRIMARY KEY, ref INTEGER, book TEXT, chapter INTEGER, verse INTEGER,
        lex TEXT, stem TEXT, sp TEXT, strong TEXT, context TEXT,
        gloss TEXT, sense TEXT, sense_source TEXT, sense_conf REAL)""")

    rows, skipped = [], 0
    for w in F.otype.s("word"):
        sec = T.sectionFromNode(w)            # (book, chapter, verse)
        bk = BOOKS.get(sec[0])
        if not bk:
            skipped += 1
            continue
        usfm, num = bk
        ch, vs_ = int(sec[1]), int(sec[2])
        ref = num * 1_000_000 + ch * 1_000 + vs_
        lex = F.lex.v(w)
        stem = F.vs.v(w)                      # 'qal'/'nif'/… or 'NA' for non-verbs
        rows.append((w, ref, usfm, ch, vs_, lex, ("" if stem == "NA" else stem),
                     F.sp.v(w), bridge.get(lex, ""), _context(w), None, None, None, None))

    con.executemany("INSERT INTO occurrence VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.execute("CREATE INDEX ix_occ_ref ON occurrence(ref)")
    con.execute("CREATE INDEX ix_occ_lexstem ON occurrence(lex, stem)")
    con.execute("CREATE INDEX ix_occ_strong ON occurrence(strong)")
    con.commit()

    n = con.execute("SELECT count(*) FROM occurrence").fetchone()[0]
    nverb = con.execute("SELECT count(*) FROM occurrence WHERE stem!=''").fetchone()[0]
    nstrong = con.execute("SELECT count(*) FROM occurrence WHERE strong!=''").fetchone()[0]
    nlex = con.execute("SELECT count(DISTINCT lex) FROM occurrence").fetchone()[0]
    con.close()
    print(f"wrote {OUT.relative_to(ROOT)}: {n} occurrences "
          f"({nverb} stem-bearing, {nstrong} Strong-bridged, {nlex} distinct lexemes; "
          f"{skipped} skipped no-book)")


if __name__ == "__main__":
    main()
