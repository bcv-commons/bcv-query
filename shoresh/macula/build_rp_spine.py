#!/usr/bin/env python3
"""Build a second, independently-sourced Greek spine_words db (same schema/contract as
build_spine_words.py's lexeme-spine.db) -- external request: end clients want to align a target
language fully against Robinson-Pierpont/TR, including words that tradition carries but Nestle 1904
(the existing NT spine's sole source) doesn't. A word absent from Nestle 1904 has no anchor in the
existing single-spine design no matter how good alignment gets -- this is a second, drop-in-alternate
spine db, not a patch onto the first (contract stays file-based/pinned, no schema change on the
existing db -- see internal-docs/data-contracts.md).

NAMING CAVEAT, verified directly against the source data before building anything: this is
Robinson-Pierpont's Byzantine-majority reconstruction (RP2018), NOT Textus Receptus proper
(Erasmus/Stephanus/Beza). At 1 John 5:7-8 the source's running Greek text is the SHORT reading -- no
Comma Johanneum words, no Strong's tags for it anywhere in the file (checked: 0 of 219,716 rows). The
traditional long TR wording appears only as inline English footnote prose, never as taggable Greek.
So this spine gives a complete, genuinely independent RP2018 anchor -- not a Comma-inclusive
TR-proper one. Don't relabel this "TR" downstream; a genuine Erasmus/Stephanus/Beza Strong's-tagged
source, if one turns up, would be a third, separate spine, not a rename of this one.

SOURCE: https://majoritybible.com/msb_nt_tables.tsv (Berean Bible group's Robinson-Pierpont 2018
interlinear). Public domain -- berean.bible/licensing.htm: "the Berean Bible and Majority Bible texts
are officially placed into the public domain as of April 30, 2023," no licensing required for any
use (verified directly this session, not just taken on the requester's word). 27 NT books, 219,716
source rows, 140,147 of them real Greek words (100% Strong's-tagged among those -- every row with
word text carries a Strong's number, verified directly); the remaining rows are blank per-verse
layout filler in the source table and are dropped here.

SCHEMA PARITY, and where it can't be full parity:
  - Same spine_words table/columns as lexeme-spine.db, so a consumer's existing SELECT works
    unchanged against this db -- point at a different file, no schema/edition-flag column needed
    (Hebrew and this Greek edition never share one table, so there's nothing to disambiguate inline).
  - `lexeme` is `grc:<bare-strong>` (NOT augmented) and `strong` is identical to it -- this source's
    Strong's tags carry no MACULA-style homograph augment letter, so there's nothing to roll up.
    Fabricating a split the source doesn't make would be worse than an honest bare anchor.
  - `lemma` is blank -- the source gives inflected surface + Strong's number only, no separate
    normalized-lemma column to carry over.
  - `morph` carries the raw Robinson-Pierpont parsing code verbatim (e.g. "V-2AAI-3S"). The
    structured person/number/gender/case_/tense/voice/mood/degree/state columns the Hebrew side
    uses are left BLANK in this v1 -- MACULA ships those pre-split; this source doesn't, and decoding
    RP's code suffixes needs a verified code table this pass didn't build (flagged, not guessed at).
    `is_content` (adj/noun/verb, matching the existing N/V/A convention) only needs the code's FIRST
    segment (N-/V-/A-), which is unambiguous, so that one field is populated correctly.
  - `role`, `stem`, `is_superscription` stay at schema defaults (blank/blank/0) -- none apply to Greek
    in the existing lexeme-spine.db either (checked directly).
  - No BHSA-bridge sense/syntax columns (sense*, phrase_id, function, rela) -- those come from
    Hebrew-only downstream enrichment steps (enrich_spine_senses.py, enrich_spine_syntax.py) that
    leave Greek rows NULL even in the existing lexeme-spine.db (checked directly). Out of scope for a
    Greek-only spine either way, so this build's CREATE TABLE only carries the base 24 columns.

  python -m macula.build_rp_spine                              # fetch + build rp2018-spine.db
  MSB_TSV=/path/to/local/msb_nt_tables.tsv python -m macula.build_rp_spine   # use a local copy
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from references import BOOK_NUMBERS  # USFM code -> book number; used only to sanity-check the map below

HERE = Path(__file__).resolve().parent
OUT_DEFAULT = HERE / "rp2018-spine.db"
SRC_URL = "https://majoritybible.com/msb_nt_tables.tsv"
SRC_ENV = "MSB_TSV"

# Source VerseId column spells books out in English ("1 John 5:7"); map to this project's own USFM
# codes (shoresh/references.py BOOK_NUMBERS) so the two spines' `book` values are directly comparable.
_BOOK_NAME_TO_CODE = {
    "Matthew": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Romans": "ROM", "1 Corinthians": "1CO", "2 Corinthians": "2CO", "Galatians": "GAL",
    "Ephesians": "EPH", "Philippians": "PHP", "Colossians": "COL",
    "1 Thessalonians": "1TH", "2 Thessalonians": "2TH", "1 Timothy": "1TI", "2 Timothy": "2TI",
    "Titus": "TIT", "Philemon": "PHM", "Hebrews": "HEB", "James": "JAS",
    "1 Peter": "1PE", "2 Peter": "2PE", "1 John": "1JN", "2 John": "2JN", "3 John": "3JN",
    "Jude": "JUD", "Revelation": "REV",
}
assert set(_BOOK_NAME_TO_CODE.values()) <= set(BOOK_NUMBERS), "book map drifted from references.py"

# Robinson-Pierpont parsing-code first segment -> open lexical class, parity with
# build_spine_words._CONTENT_CLASSES (noun/verb/adj = the STEPBible spine's N/V/A).
_CONTENT_POS = {"N", "V", "A"}


def _source_text(url: str, env: str) -> str:
    local = os.environ.get(env)
    if local:
        return Path(local).read_text(encoding="utf-8")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 -- fixed, project-pinned URL
        return resp.read().decode("utf-8")


def parse_rows(text: str) -> tuple[list[dict], int]:
    """One dict per real Greek word (blank per-verse layout filler rows dropped). Also returns a
    count of rows skipped for a non-numeric Str Grk value -- 4 known source rows (0.003% of 140,147)
    have their Translit/Str Grk columns shifted by one (e.g. Str Grk='ouai', a transliteration, not a
    number) -- a genuine source data glitch, not a parsing bug here; skipped rather than guessed at."""
    r = csv.reader(text.splitlines(), delimiter="\t")
    next(r)  # header
    out, skipped = [], 0
    cur_book = cur_ch = cur_v = None
    for row in r:
        if len(row) < 19:
            continue  # defensive -- source has one truncated/corrupt row (see docstring); no
                      # column we use survives past index 18 on it anyway
        verse_id = row[12].strip()
        if verse_id:
            name, cv = verse_id.rsplit(" ", 1)
            ch_s, v_s = cv.split(":")
            cur_book, cur_ch, cur_v = _BOOK_NAME_TO_CODE[name], int(ch_s), int(v_s)
        greek, strong_raw = row[6].strip(), row[11].strip()
        if not greek or not strong_raw:
            continue  # blank layout filler row, or (the one corrupt row) -- not a word
        if not strong_raw.isdigit():
            skipped += 1
            continue
        code = row[8].strip()
        pos = code.split("-", 1)[0]
        out.append({
            "book": cur_book, "chapter": cur_ch, "verse": cur_v,
            "msb_sort": row[2].strip(),
            "surface": greek, "strong": int(strong_raw), "morph": code,
            "is_content": 1 if pos in _CONTENT_POS else 0,
            "gloss": row[18].strip(),
        })
    return out, skipped


def build(words: list[dict], out_path: Path) -> int:
    out_path.unlink(missing_ok=True)
    db = sqlite3.connect(out_path)
    db.executescript("""
        CREATE TABLE spine_words (
            book TEXT NOT NULL, chapter INTEGER NOT NULL, verse INTEGER NOT NULL,
            idx INTEGER NOT NULL,
            key TEXT NOT NULL,           -- synthesized: "grc-rp:<source MSB Sort>" (source's own
                                          -- globally unique, monotonic row index -- no native
                                          -- per-occurrence node id exists in this source)
            surface TEXT NOT NULL,
            lexeme TEXT NOT NULL,        -- ANCHOR: grc:<bare-strong> -- see docstring (no augment)
            strong INTEGER,              -- identical to lexeme's number (nothing to roll up)
            lemma TEXT, is_content INTEGER NOT NULL, morph TEXT,
            gloss TEXT, role TEXT,
            stem TEXT,
            person TEXT, number TEXT, gender TEXT, case_ TEXT, tense TEXT, voice TEXT,
            mood TEXT, degree TEXT, state TEXT,   -- left blank in v1 -- see docstring
            is_superscription INTEGER NOT NULL DEFAULT 0,   -- always 0 -- Hebrew/Psalms-only concept
            PRIMARY KEY (book, chapter, verse, idx)
        );
        CREATE UNIQUE INDEX ix_ls_key ON spine_words(key);
        CREATE INDEX ix_ls_lexeme ON spine_words(lexeme);
        CREATE INDEX ix_ls_strong ON spine_words(strong);
        CREATE TABLE spine_meta (key TEXT PRIMARY KEY, value TEXT);
    """)

    rows, idx, prev = [], 0, None
    for w in words:
        cvk = (w["book"], w["chapter"], w["verse"])
        idx = idx + 1 if cvk == prev else 0
        prev = cvk
        lexeme = f"grc:{w['strong']}"
        rows.append((
            w["book"], w["chapter"], w["verse"], idx,
            f"grc-rp:{w['msb_sort']}", w["surface"], lexeme, w["strong"],
            None, w["is_content"], w["morph"], w["gloss"], "", "",
            "", "", "", "", "", "", "", "", "", 0,
        ))
    db.executemany(
        "INSERT INTO spine_words VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
    )
    db.commit()
    db.close()
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Robinson-Pierpont-anchored Greek spine_words (drop-in alternate to lexeme-spine.db's Greek side).")
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--url", default=SRC_URL)
    args = ap.parse_args()

    text = _source_text(args.url, SRC_ENV)
    src_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    words, skipped = parse_rows(text)
    if not words:
        sys.exit("parsed 0 words -- source format changed, check the column layout in the docstring")
    if skipped:
        print(f"  ! {skipped} row(s) skipped: non-numeric Str Grk (known source column-shift glitch, "
              f"see parse_rows docstring)", file=sys.stderr)

    content = sum(w["is_content"] for w in words)
    with_gloss = sum(1 for w in words if w["gloss"])
    n = build(words, args.out)

    out_sha = hashlib.sha256(args.out.read_bytes()).hexdigest()
    with sqlite3.connect(args.out) as db:
        db.executemany("INSERT INTO spine_meta VALUES (?,?)", [
            ("anchor", "lexeme = grc:bare-strong (no augment -- source has no homograph split)"),
            ("strong_rollup", "identical to lexeme -- nothing to strip"),
            ("content_classes", "adj,noun,verb (= STEPBible spine N/V/A); POS = Robinson-Pierpont "
                                 "parsing-code first segment"),
            ("source_greek", "Berean Bible group, Robinson-Pierpont 2018 Byzantine Textform "
                              "interlinear (majoritybible.com/msb_nt_tables.tsv)"),
            ("edition", "grc-rp2018"),
            ("edition_note", "RP2018 Byzantine-majority text, NOT Textus Receptus proper -- verified "
                              "directly: 1 John 5:7-8 carries the SHORT reading, no Comma Johanneum "
                              "Greek/Strong's anywhere in the source. See build_rp_spine.py docstring."),
            ("license", "Public domain -- berean.bible/licensing.htm: Berean Bible and Majority Bible "
                         "texts placed into the public domain 2023-04-30, no licensing required for "
                         "any use (verified directly, not just taken on the requester's word)."),
            ("morph_note", "raw Robinson-Pierpont parsing code verbatim in `morph`; structured "
                            "person/number/gender/case_/tense/voice/mood/degree/state columns "
                            "intentionally blank in v1 -- decoding RP's code suffixes needs a "
                            "verified code table this pass didn't build."),
            ("gloss_source", "Berean/MSB per-word English gloss, aligned in source"),
            ("source_sha256", src_sha),
            ("words", str(n)),
        ])
        from macula.spine_versification import declaration    # the spine's own verse numbering
        db.executemany("INSERT OR REPLACE INTO spine_meta(key, value) VALUES (?, ?)",
                       list(declaration(db, "rp2018").items()))
        db.commit()

    print(f"{n} words -> {args.out}")
    print(f"  content (N/V/A): {content}  ({100 * content / n:.1f}%)")
    print(f"  with gloss: {with_gloss}  ({100 * with_gloss / n:.1f}%)")
    print(f"  source sha256: {src_sha}")
    print(f"  build sha256:  {out_sha}")
    print("  -> pin both sha256s in the consumer's provenance note (same discipline as contract §1)")


if __name__ == "__main__":
    main()
